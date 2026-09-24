from __future__ import annotations

import html
import ipaddress
import json
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from .local_store import canonical_tenant_key, connect_catalog, tenant_report_dir
from .private_decision_workspace import build_and_write_private_decision_workspace
from .private_workspace_auth import (
    DEFAULT_SESSION_TTL,
    create_session_token,
    validate_csrf,
    verify_session_token,
    verify_workspace_password,
)

SESSION_COOKIE = "clr_workspace_session"
MAX_FORM_BYTES = 64 * 1024


def _require_safe_tenant_key(value: Any) -> str:
    return canonical_tenant_key(value)


def _private_root(root: str | Path) -> Path:
    root = Path(root).resolve()
    if not (root / ".private-data-root").exists():
        raise ValueError(f"Not an initialized private workspace: {root}")
    return root


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _json_params(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def tenant_exists(root: str | Path, tenant_key: str) -> bool:
    root = _private_root(root)
    try:
        tenant = _require_safe_tenant_key(tenant_key)
    except ValueError:
        return False
    with connect_catalog(root) as conn:
        asset = conn.execute(
            "SELECT 1 FROM asset_location WHERE tenant_key=? LIMIT 1",
            (tenant,),
        ).fetchone()
        portfolio = conn.execute(
            "SELECT 1 FROM portfolio_exposure WHERE tenant_key=? LIMIT 1",
            (tenant,),
        ).fetchone()
        cross = conn.execute(
            "SELECT 1 FROM cross_asset_metric WHERE tenant_key=? LIMIT 1",
            (tenant,),
        ).fetchone()
    return bool(asset or portfolio or cross)


def workspace_catalog(root: str | Path, tenant_key: str) -> dict[str, Any]:
    root = _private_root(root)
    tenant = _require_safe_tenant_key(tenant_key)

    with connect_catalog(root) as conn:
        assets = [
            dict(row)
            for row in conn.execute(
                """
                SELECT asset_location_id,external_system,external_id,asset_type,
                       site_identity_grade,coordinate_status,coordinate_precision_m
                FROM asset_location
                WHERE tenant_key=? AND valid_to IS NULL
                ORDER BY external_system,external_id,asset_location_id
                """,
                (tenant,),
            ).fetchall()
        ]
        portfolios = [
            dict(row)
            for row in conn.execute(
                """
                SELECT portfolio_id,
                       count(*) AS exposure_row_count,
                       count(DISTINCT asset_location_id) AS linked_asset_count,
                       min(valuation_date) AS valuation_date_min,
                       max(valuation_date) AS valuation_date_max
                FROM portfolio_exposure
                WHERE tenant_key=?
                GROUP BY portfolio_id
                ORDER BY portfolio_id
                """,
                (tenant,),
            ).fetchall()
        ]
        indicator_runs = [
            dict(row)
            for row in conn.execute(
                """
                SELECT pr.run_id,pr.pipeline_name,pr.pipeline_version,pr.git_commit,
                       pr.started_at,pr.finished_at,pr.parameters_json,
                       count(ai.asset_indicator_id) AS indicator_row_count,
                       count(DISTINCT ai.asset_location_id) AS asset_count,
                       count(DISTINCT ai.indicator_id) AS indicator_count
                FROM processing_run pr
                JOIN asset_indicator ai ON ai.run_id=pr.run_id
                WHERE pr.status='SUCCESS' AND ai.tenant_key=?
                GROUP BY pr.run_id
                ORDER BY pr.finished_at DESC, pr.started_at DESC
                """,
                (tenant,),
            ).fetchall()
        ]
        compound_runs = [
            dict(row)
            for row in conn.execute(
                """
                SELECT pr.run_id,pr.pipeline_name,pr.pipeline_version,pr.git_commit,
                       pr.started_at,pr.finished_at,pr.parameters_json,
                       count(cam.cross_asset_metric_id) AS metric_count
                FROM processing_run pr
                JOIN cross_asset_metric cam ON cam.run_id=pr.run_id
                WHERE pr.status='SUCCESS' AND cam.tenant_key=?
                GROUP BY pr.run_id
                ORDER BY pr.finished_at DESC, pr.started_at DESC
                """,
                (tenant,),
            ).fetchall()
        ]
        route_runs = [
            dict(row)
            for row in conn.execute(
                """
                SELECT pr.run_id,pr.pipeline_name,pr.pipeline_version,pr.git_commit,
                       pr.started_at,pr.finished_at,pr.parameters_json,
                       count(lra.route_analysis_id) AS route_count
                FROM processing_run pr
                JOIN logistics_route_analysis lra ON lra.run_id=pr.run_id
                WHERE pr.status='SUCCESS' AND lra.tenant_key=?
                GROUP BY pr.run_id
                ORDER BY pr.finished_at DESC, pr.started_at DESC
                """,
                (tenant,),
            ).fetchall()
        ]

    for collection in (indicator_runs, compound_runs, route_runs):
        for row in collection:
            row["parameters"] = _json_params(row.pop("parameters_json", None))

    reports = list_private_reports(root, tenant)
    return {
        "tenant_key": tenant,
        "assets": assets,
        "portfolios": portfolios,
        "indicator_runs": indicator_runs,
        "compound_runs": compound_runs,
        "route_runs": route_runs,
        "reports": reports,
    }


def list_private_reports(root: str | Path, tenant_key: str) -> list[dict[str, Any]]:
    root = _private_root(root)
    tenant = _require_safe_tenant_key(tenant_key)
    base = tenant_report_dir(root, tenant)
    if not base.exists():
        return []
    out = []
    for manifest_path in sorted(
        base.rglob("decision-workspace-*.manifest.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:50]:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            selection = manifest.get("selection", {})
            stem = manifest_path.name[: -len(".manifest.json")]
            html_path = manifest_path.with_name(stem + ".html")
            json_path = manifest_path.with_name(stem + ".json")
            if not html_path.exists() or not json_path.exists():
                continue
            out.append(
                {
                    "scope_type": selection.get("scope_type"),
                    "subject_id": selection.get("subject_id"),
                    "generated_at": manifest.get("generated_at"),
                    "html_path": html_path.relative_to(root).as_posix(),
                    "json_path": json_path.relative_to(root).as_posix(),
                    "manifest_path": manifest_path.relative_to(root).as_posix(),
                }
            )
        except Exception:
            continue
    return out


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _safe_output_file(
    root: str | Path,
    tenant_key: str,
    relative_path: str,
    *,
    suffixes: tuple[str, ...],
) -> Path:
    root = _private_root(root)
    tenant = _require_safe_tenant_key(tenant_key)
    base = tenant_report_dir(root, tenant)
    target = (root / relative_path).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError("Requested report path is outside the authenticated tenant") from exc
    if target.suffix.lower() not in suffixes:
        raise ValueError("Unsupported report file type")
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(target)
    return target


def _layout(title: str, body: str, *, tenant: str | None = None) -> str:
    tenant_html = (
        f'<span class="tenant">Tenant: {_esc(tenant)}</span>' if tenant else ""
    )
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)} · Private Climate Intelligence Workspace</title>
<style>
:root{{--bg:#f4f6f4;--panel:#fff;--ink:#172019;--muted:#687169;--line:#dce2dd;--green:#173f2b;--green2:#2d6a4f;--soft:#edf3ef;--amber:#8a5a16;--red:#8b3434}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;line-height:1.45}}
header{{background:var(--green);color:#fff}}.shell{{max-width:1200px;margin:0 auto;padding:22px 24px}}header .shell{{display:flex;align-items:center;justify-content:space-between;gap:20px}}
.brand{{font-weight:760}}.brand small{{display:block;font-size:11px;font-weight:500;opacity:.72;text-transform:uppercase;letter-spacing:.08em}}.tenant{{font-size:12px;border:1px solid rgba(255,255,255,.3);padding:6px 9px;border-radius:999px}}
main.shell{{padding-top:28px;padding-bottom:60px}}h1{{font-size:32px;margin:0 0 8px;letter-spacing:-.025em}}h2{{font-size:20px;margin:0 0 8px}}h3{{font-size:15px;margin:0 0 6px}}
.lead{{color:var(--muted);margin:0 0 20px}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}.panel{{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:18px;margin-bottom:14px}}
label{{font-size:12px;font-weight:700;display:block;margin-bottom:5px}}select,input[type=text],input[type=password]{{width:100%;padding:9px 10px;border:1px solid var(--line);border-radius:8px;background:white;color:var(--ink)}}
.field{{margin-bottom:12px}}.checks{{max-height:250px;overflow:auto;border:1px solid var(--line);border-radius:8px;padding:8px;background:#fafbfa}}.check{{display:flex;gap:8px;align-items:flex-start;padding:7px 5px;border-bottom:1px solid #edf0ed}}.check:last-child{{border-bottom:0}}.check label{{font-weight:500;margin:0}}
.meta{{font-size:11px;color:var(--muted)}}button,.button{{display:inline-block;border:0;border-radius:8px;padding:9px 13px;background:var(--green);color:#fff;font-weight:700;cursor:pointer;text-decoration:none;font-size:13px}}.button.secondary,button.secondary{{background:#fff;color:var(--green);border:1px solid var(--line)}}
.actions{{display:flex;gap:8px;flex-wrap:wrap;align-items:center}}.error{{background:#fff0f0;border:1px solid #e5bcbc;color:#6d2929;border-radius:9px;padding:11px;margin-bottom:14px}}.notice{{background:#f7f2e8;border:1px solid #e5d5b8;color:#5b481f;border-radius:9px;padding:11px;margin-bottom:14px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:8px 7px;border-bottom:1px solid #edf0ed;text-align:left;vertical-align:top}}th{{font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}}.muted{{color:var(--muted)}}.hidden{{display:none}}
.login{{max-width:440px;margin:70px auto}}footer{{font-size:11px;color:var(--muted);padding-top:20px}}
@media(max-width:760px){{.grid{{grid-template-columns:1fr}}header .shell{{align-items:flex-start;flex-direction:column}}.shell{{padding-left:14px;padding-right:14px}}}}
</style></head><body>
<header><div class="shell"><div class="brand">Private Climate Intelligence Workspace<small>Mangrove Intelligence · Local authenticated shell</small></div>{tenant_html}</div></header>
<main class="shell">{body}<footer>Local-only application shell. Analytical calculations remain in the governed pipeline and decision-workspace adapter.</footer></main>
</body></html>"""


def render_login(*, error: str | None = None) -> str:
    error_html = f'<div class="error">{_esc(error)}</div>' if error else ""
    return _layout(
        "Sign in",
        f"""<div class="login panel">
<h1>Sign in</h1>
<p class="lead">Authenticate to one tenant in the local private data workspace.</p>
{error_html}
<form method="post" action="/login">
<div class="field"><label for="tenant">Tenant key</label><input id="tenant" name="tenant" type="text" autocomplete="organization" required></div>
<div class="field"><label for="password">Workspace password</label><input id="password" name="password" type="password" autocomplete="current-password" required></div>
<button type="submit">Sign in</button>
</form>
</div>""",
    )


def _run_label(row: dict[str, Any]) -> str:
    parameters = row.get("parameters") or {}
    bits = [row.get("pipeline_name") or "pipeline", row.get("pipeline_version") or ""]
    if parameters.get("year"):
        bits.append(f"year={parameters['year']}")
    if parameters.get("return_period"):
        bits.append(f"RP{parameters['return_period']}")
    return " · ".join(str(x) for x in bits if str(x))


def render_dashboard(
    catalog: dict[str, Any],
    *,
    csrf: str,
    error: str | None = None,
    notice: str | None = None,
) -> str:
    tenant = catalog["tenant_key"]
    error_html = f'<div class="error">{_esc(error)}</div>' if error else ""
    notice_html = f'<div class="notice">{_esc(notice)}</div>' if notice else ""

    asset_opts = "".join(
        f'<option value="{_esc(x["asset_location_id"])}">{_esc(x["external_system"])}:{_esc(x["external_id"])} · {_esc(x["asset_type"])} · {_esc(x["site_identity_grade"])}</option>'
        for x in catalog["assets"]
    )
    portfolio_opts = "".join(
        f'<option value="{_esc(x["portfolio_id"])}">{_esc(x["portfolio_id"])} · {int(x["exposure_row_count"])} rows · {int(x["linked_asset_count"])} linked assets</option>'
        for x in catalog["portfolios"]
    )
    indicator_checks = "".join(
        f"""<div class="check"><input type="checkbox" id="run-{idx}" name="indicator_run" value="{_esc(x["run_id"])}">
<label for="run-{idx}">{_esc(_run_label(x))}<div class="meta">{_esc(x["run_id"])} · {int(x["indicator_row_count"])} rows · {int(x["asset_count"])} assets</div></label></div>"""
        for idx, x in enumerate(catalog["indicator_runs"])
    ) or '<div class="muted">No successful tenant-scoped indicator runs are available.</div>'

    compound_opts = '<option value="">None</option>' + "".join(
        f'<option value="{_esc(x["run_id"])}">{_esc(_run_label(x))} · {int(x["metric_count"])} metrics</option>'
        for x in catalog["compound_runs"]
    )
    route_opts = '<option value="">None</option>' + "".join(
        f'<option value="{_esc(x["run_id"])}">{_esc(_run_label(x))} · {int(x["route_count"])} route analyses</option>'
        for x in catalog["route_runs"]
    )

    report_rows = "".join(
        f"""<tr><td>{_esc(x.get("generated_at"))}</td><td>{_esc(x.get("scope_type"))}</td><td>{_esc(x.get("subject_id"))}</td>
<td><a class="button secondary" href="/report?path={quote(x["html_path"])}">Open</a>
<a class="button secondary" href="/file?path={quote(x["json_path"])}">JSON</a>
<a class="button secondary" href="/file?path={quote(x["manifest_path"])}">Manifest</a></td></tr>"""
        for x in catalog["reports"]
    ) or '<tr><td colspan="4" class="muted">No generated private reports yet.</td></tr>'

    body = f"""
<h1>Decision workspace</h1>
<p class="lead">Choose one private subject and the exact successful analytical runs that should feed the governed report. The app does not select vintages automatically.</p>
{error_html}{notice_html}
<div class="grid">
<section class="panel">
<h2>Build report</h2>
<form method="post" action="/generate">
<input type="hidden" name="csrf" value="{_esc(csrf)}">
<div class="field"><label>Scope</label>
<div class="actions"><label><input type="radio" name="scope" value="ASSET" checked onchange="toggleScope()"> Asset</label>
<label><input type="radio" name="scope" value="PORTFOLIO" onchange="toggleScope()"> Portfolio</label></div></div>

<div id="asset-field" class="field"><label for="asset">Asset</label><select id="asset" name="asset_location_id">{asset_opts}</select></div>
<div id="portfolio-field" class="field hidden"><label for="portfolio">Portfolio</label><select id="portfolio" name="portfolio_id">{portfolio_opts}</select></div>

<div class="field"><label>Indicator runs · select explicitly</label><div class="checks">{indicator_checks}</div></div>
<div class="field"><label for="compound">Compound / cross-asset run</label><select id="compound" name="compound_run">{compound_opts}</select></div>
<div class="field"><label for="route">Logistics run</label><select id="route" name="route_run">{route_opts}</select></div>
<div class="field"><label for="flood">Portfolio footprint hazard indicator</label><input id="flood" name="flood_indicator_id" type="text" value="flood_rp100_depth_m"></div>
<button type="submit">Generate private report</button>
</form>
</section>

<section class="panel">
<h2>Tenant data readiness</h2>
<table><tbody>
<tr><th>Current assets</th><td>{len(catalog["assets"])}</td></tr>
<tr><th>Portfolios</th><td>{len(catalog["portfolios"])}</td></tr>
<tr><th>Successful indicator runs</th><td>{len(catalog["indicator_runs"])}</td></tr>
<tr><th>Compound runs</th><td>{len(catalog["compound_runs"])}</td></tr>
<tr><th>Logistics runs</th><td>{len(catalog["route_runs"])}</td></tr>
</tbody></table>
<p class="meta">Coordinates, borrower identifiers and exposure-row details are not displayed on this shell.</p>
<form method="post" action="/logout" style="margin-top:16px"><input type="hidden" name="csrf" value="{_esc(csrf)}"><button class="secondary" type="submit">Sign out</button></form>
</section>
</div>

<section class="panel">
<h2>Generated private reports</h2>
<table><thead><tr><th>Generated</th><th>Scope</th><th>Subject</th><th>Files</th></tr></thead><tbody>{report_rows}</tbody></table>
</section>

<script>
function toggleScope(){{
  const scope=document.querySelector('input[name="scope"]:checked').value;
  document.getElementById('asset-field').classList.toggle('hidden',scope!=='ASSET');
  document.getElementById('portfolio-field').classList.toggle('hidden',scope!=='PORTFOLIO');
}}
</script>
"""
    return _layout("Decision workspace", body, tenant=tenant)


def _parse_cookie(header: str | None) -> dict[str, str]:
    if not header:
        return {}
    jar = cookies.SimpleCookie()
    try:
        jar.load(header)
    except cookies.CookieError:
        return {}
    return {key: morsel.value for key, morsel in jar.items()}


def make_handler(
    root: str | Path,
    *,
    session_ttl: int = DEFAULT_SESSION_TTL,
):
    private_root = _private_root(root)

    class Handler(BaseHTTPRequestHandler):
        server_version = "CLRPrivateWorkspace/0.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            # Avoid logging query strings or private subject identifiers.
            message = fmt % args
            safe = message.split("?", 1)[0]
            print(f"[workspace] {self.client_address[0]} {safe}")

        def _headers(
            self,
            status: int,
            *,
            content_type: str = "text/html; charset=utf-8",
            content_length: int | None = None,
            extra: list[tuple[str, str]] | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                "img-src 'self' data:; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
            )
            if content_length is not None:
                self.send_header("Content-Length", str(content_length))
            for key, value in extra or []:
                self.send_header(key, value)
            self.end_headers()

        def _send_html(
            self,
            status: int,
            content: str,
            *,
            extra: list[tuple[str, str]] | None = None,
        ) -> None:
            data = content.encode("utf-8")
            self._headers(
                status,
                content_length=len(data),
                extra=extra,
            )
            self.wfile.write(data)

        def _redirect(
            self,
            location: str,
            *,
            extra: list[tuple[str, str]] | None = None,
        ) -> None:
            headers = [("Location", location)]
            headers.extend(extra or [])
            self._headers(303, content_length=0, extra=headers)

        def _session(self) -> dict[str, Any] | None:
            token = _parse_cookie(self.headers.get("Cookie")).get(SESSION_COOKIE)
            if not token:
                return None
            session = verify_session_token(private_root, token)
            if not session:
                return None
            if not tenant_exists(private_root, session["tenant"]):
                return None
            return session

        def _form(self) -> dict[str, list[str]]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0 or length > MAX_FORM_BYTES:
                raise ValueError("Invalid form size")
            ctype = self.headers.get("Content-Type", "")
            if not ctype.startswith("application/x-www-form-urlencoded"):
                raise ValueError("Unsupported form content type")
            raw = self.rfile.read(length).decode("utf-8")
            return parse_qs(raw, keep_blank_values=True)

        def _require_auth(self) -> dict[str, Any] | None:
            session = self._session()
            if not session:
                self._redirect("/login")
                return None
            return session

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/login":
                if self._session():
                    self._redirect("/")
                    return
                self._send_html(200, render_login())
                return

            if parsed.path == "/":
                session = self._require_auth()
                if not session:
                    return
                catalog = workspace_catalog(private_root, session["tenant"])
                query = parse_qs(parsed.query)
                notice = query.get("notice", [None])[0]
                self._send_html(
                    200,
                    render_dashboard(
                        catalog,
                        csrf=session["csrf"],
                        notice=notice,
                    ),
                )
                return

            if parsed.path in {"/report", "/file"}:
                session = self._require_auth()
                if not session:
                    return
                query = parse_qs(parsed.query)
                relative = query.get("path", [""])[0]
                try:
                    if parsed.path == "/report":
                        target = _safe_output_file(
                            private_root,
                            session["tenant"],
                            relative,
                            suffixes=(".html",),
                        )
                        data = target.read_bytes()
                        self._headers(
                            200,
                            content_type="text/html; charset=utf-8",
                            content_length=len(data),
                        )
                    else:
                        target = _safe_output_file(
                            private_root,
                            session["tenant"],
                            relative,
                            suffixes=(".json",),
                        )
                        data = target.read_bytes()
                        self._headers(
                            200,
                            content_type="application/json; charset=utf-8",
                            content_length=len(data),
                        )
                    self.wfile.write(data)
                except (ValueError, FileNotFoundError) as exc:
                    self._send_html(
                        404,
                        _layout(
                            "Not found",
                            f'<div class="error">{_esc(exc)}</div>',
                            tenant=session["tenant"],
                        ),
                    )
                return

            self._send_html(404, _layout("Not found", "<h1>Not found</h1>"))

        def do_POST(self) -> None:
            parsed = urlparse(self.path)

            if parsed.path == "/login":
                try:
                    form = self._form()
                    tenant = form.get("tenant", [""])[0].strip()
                    password = form.get("password", [""])[0]
                    valid_tenant = tenant_exists(private_root, tenant)
                    valid_password = verify_workspace_password(private_root, password)
                    if not (valid_tenant and valid_password):
                        self._send_html(
                            401,
                            render_login(error="Invalid tenant or password."),
                        )
                        return
                    token, _ = create_session_token(
                        private_root,
                        tenant_key=tenant,
                        ttl_seconds=session_ttl,
                    )
                    cookie = (
                        f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; "
                        f"SameSite=Strict; Max-Age={int(session_ttl)}"
                    )
                    self._redirect("/", extra=[("Set-Cookie", cookie)])
                except Exception:
                    self._send_html(
                        401,
                        render_login(error="Sign-in failed."),
                    )
                return

            session = self._require_auth()
            if not session:
                return
            try:
                form = self._form()
            except ValueError as exc:
                self._send_html(
                    400,
                    _layout("Invalid request", f'<div class="error">{_esc(exc)}</div>', tenant=session["tenant"]),
                )
                return

            supplied_csrf = form.get("csrf", [""])[0]
            if not validate_csrf(session, supplied_csrf):
                self._send_html(
                    403,
                    _layout("Forbidden", '<div class="error">Invalid CSRF token.</div>', tenant=session["tenant"]),
                )
                return

            if parsed.path == "/logout":
                expired = (
                    f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; "
                    "Max-Age=0"
                )
                self._redirect("/login", extra=[("Set-Cookie", expired)])
                return

            if parsed.path == "/generate":
                try:
                    scope = form.get("scope", [""])[0].strip().upper()
                    runs = [x.strip() for x in form.get("indicator_run", []) if x.strip()]
                    if not runs:
                        raise ValueError("Select at least one successful indicator run.")
                    kwargs: dict[str, Any] = {
                        "scope_type": scope,
                        "tenant_key": session["tenant"],
                        "indicator_run_ids": runs,
                        "compound_run_id": form.get("compound_run", [""])[0].strip() or None,
                        "route_run_id": form.get("route_run", [""])[0].strip() or None,
                        "flood_indicator_id": form.get(
                            "flood_indicator_id", ["flood_rp100_depth_m"]
                        )[0].strip()
                        or "flood_rp100_depth_m",
                    }
                    if scope == "ASSET":
                        kwargs["asset_location_id"] = form.get(
                            "asset_location_id", [""]
                        )[0].strip()
                    elif scope == "PORTFOLIO":
                        kwargs["portfolio_id"] = form.get(
                            "portfolio_id", [""]
                        )[0].strip()
                    else:
                        raise ValueError("Scope must be ASSET or PORTFOLIO.")

                    result = build_and_write_private_decision_workspace(
                        private_root,
                        **kwargs,
                    )
                    target = result["outputs"]["html"]
                    self._redirect(f"/report?path={quote(target)}")
                except Exception as exc:
                    catalog = workspace_catalog(private_root, session["tenant"])
                    self._send_html(
                        400,
                        render_dashboard(
                            catalog,
                            csrf=session["csrf"],
                            error=str(exc),
                        ),
                    )
                return

            self._send_html(404, _layout("Not found", "<h1>Not found</h1>"))

    return Handler


def serve_private_workspace(
    root: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    session_ttl: int = DEFAULT_SESSION_TTL,
) -> None:
    if not _is_loopback_host(host):
        raise ValueError(
            "Private Workspace 0.1 is localhost-only. "
            "Remote binding requires a separately hardened TLS deployment."
        )
    private_root = _private_root(root)
    handler = make_handler(private_root, session_ttl=session_ttl)
    server = ThreadingHTTPServer((host, int(port)), handler)
    print(f"Private workspace: http://{host}:{int(port)}/")
    try:
        server.serve_forever()
    finally:
        server.server_close()
