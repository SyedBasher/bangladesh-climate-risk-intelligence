from __future__ import annotations

import hashlib
import hmac
import html
import json
import sqlite3
import threading
import time
from collections import OrderedDict, deque
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from .local_store import canonical_tenant_key, connect_catalog
from .private_decision_workspace import (
    MAX_INDICATOR_RUNS,
    build_and_write_private_decision_workspace,
)
from .private_workspace_access import (
    AuditStateError,
    DEFAULT_SESSION_MINUTES,
    MAX_PASSWORD_CHARS,
    authenticate_user,
    create_session,
    record_audit_event,
    revoke_session,
    role_allows,
    verify_audit_chain,
    verify_session,
)
from .private_workspace_app import (
    MAX_FORM_BYTES,
    _is_loopback_host,
    _private_root,
    _safe_output_file,
    workspace_catalog,
)

PILOT_SESSION_COOKIE = "clr_pilot_session"
MAX_LOGIN_FORM_BYTES = 4 * 1024
MAX_LOGIN_USERNAME_CHARS = 128
MAX_LOGIN_TENANT_CHARS = 128
DEFAULT_LOGIN_ATTEMPTS_PER_KEY = 8
DEFAULT_LOGIN_WINDOW_SECONDS = 5 * 60
DEFAULT_LOGIN_GLOBAL_ATTEMPTS = 20
DEFAULT_LOGIN_GLOBAL_WINDOW_SECONDS = 60
MAX_LOGIN_RATE_KEYS = 2048


class _LoginRateLimiter:
    """Bound expensive password checks without retaining raw account identifiers."""

    def __init__(
        self,
        *,
        attempts_per_key: int = DEFAULT_LOGIN_ATTEMPTS_PER_KEY,
        window_seconds: int = DEFAULT_LOGIN_WINDOW_SECONDS,
        global_attempts: int = DEFAULT_LOGIN_GLOBAL_ATTEMPTS,
        global_window_seconds: int = DEFAULT_LOGIN_GLOBAL_WINDOW_SECONDS,
        max_keys: int = MAX_LOGIN_RATE_KEYS,
    ):
        self.attempts_per_key = max(1, int(attempts_per_key))
        self.window_seconds = max(1, int(window_seconds))
        self.global_attempts = max(1, int(global_attempts))
        self.global_window_seconds = max(1, int(global_window_seconds))
        self.max_keys = max(16, int(max_keys))
        self._by_key: OrderedDict[str, deque[float]] = OrderedDict()
        self._global: deque[float] = deque()
        self._lock = threading.Lock()

    @staticmethod
    def key(username: str, tenant: str) -> str:
        user_key = str(username).strip().casefold()
        tenant_candidate = str(tenant).strip()
        try:
            tenant_key = canonical_tenant_key(tenant_candidate).casefold()
        except ValueError:
            tenant_key = "<invalid-tenant>"
        raw = f"{user_key}\x00{tenant_key}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _prune(queue: deque[float], cutoff: float) -> None:
        while queue and queue[0] <= cutoff:
            queue.popleft()

    def allow(self, username: str, tenant: str, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else float(now)
        key = self.key(username, tenant)
        with self._lock:
            self._prune(
                self._global,
                current - self.global_window_seconds,
            )
            queue = self._by_key.get(key)
            if queue is None:
                queue = deque()
                self._by_key[key] = queue
            else:
                self._by_key.move_to_end(key)
            self._prune(queue, current - self.window_seconds)

            if (
                len(self._global) >= self.global_attempts
                or len(queue) >= self.attempts_per_key
            ):
                return False

            queue.append(current)
            self._global.append(current)
            while len(self._by_key) > self.max_keys:
                self._by_key.popitem(last=False)
            return True

    def reset(self, username: str, tenant: str) -> None:
        key = self.key(username, tenant)
        with self._lock:
            self._by_key.pop(key, None)


def _login_audit_detail(username: str) -> dict[str, str]:
    normalized = str(username).strip().casefold()[:MAX_LOGIN_USERNAME_CHARS]
    return {
        "username_sha256": hashlib.sha256(
            normalized.encode("utf-8")
        ).hexdigest()
    }


def _audit_tenant_or_none(tenant: str) -> str | None:
    try:
        return canonical_tenant_key(tenant)
    except ValueError:
        return None


def _is_sqlite_busy(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message


def _privacy_safe_log_message(fmt: str, args: tuple[Any, ...]) -> str:
    safe_args = list(args)
    if safe_args:
        request_line = str(safe_args[0])
        parts = request_line.split(" ", 2)
        if len(parts) >= 2:
            parts[1] = parts[1].split("?", 1)[0]
            safe_args[0] = " ".join(parts)
    try:
        return fmt % tuple(safe_args)
    except Exception:
        return str(fmt).split("?", 1)[0]


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _parse_cookie(header: str | None) -> dict[str, str]:
    if not header:
        return {}
    jar = cookies.SimpleCookie()
    try:
        jar.load(header)
    except cookies.CookieError:
        return {}
    return {key: morsel.value for key, morsel in jar.items()}


def _csrf_for_token(token: str) -> str:
    return hashlib.sha256(("csrf:" + token).encode("utf-8")).hexdigest()


def _validate_csrf(token: str, supplied: str | None) -> bool:
    expected = _csrf_for_token(token)
    actual = str(supplied or "")
    return bool(actual and hmac.compare_digest(expected, actual))


def _layout(
    title: str,
    body: str,
    *,
    identity: dict[str, Any] | None = None,
) -> str:
    identity_html = ""
    if identity:
        label = identity.get("display_name") or identity.get("username")
        identity_html = (
            f'<div class="who">{_esc(label)}'
            f'<span>{_esc(identity["tenant_key"])} · {_esc(identity["role"])}</span></div>'
        )
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)} · Climate Intelligence Pilot</title>
<style>
:root{{--bg:#f4f6f4;--panel:#fff;--ink:#172019;--muted:#687169;--line:#dce2dd;--green:#173f2b;--soft:#edf3ef;--red:#8b3434}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;line-height:1.45}}
header{{background:var(--green);color:#fff}}.shell{{max-width:1200px;margin:0 auto;padding:22px 24px}}header .shell{{display:flex;justify-content:space-between;align-items:center;gap:16px}}
.brand{{font-weight:760}}.brand small{{display:block;font-size:11px;font-weight:500;opacity:.72;text-transform:uppercase;letter-spacing:.08em}}.who{{font-size:12px;text-align:right}}.who span{{display:block;opacity:.72}}
main.shell{{padding-top:28px;padding-bottom:60px}}h1{{font-size:32px;margin:0 0 8px;letter-spacing:-.025em}}h2{{font-size:20px;margin:0 0 8px}}.lead{{color:var(--muted);margin:0 0 20px}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:18px;margin-bottom:14px}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}
label{{font-size:12px;font-weight:700;display:block;margin-bottom:5px}}select,input[type=text],input[type=password]{{width:100%;padding:9px 10px;border:1px solid var(--line);border-radius:8px;background:white;color:var(--ink)}}
.field{{margin-bottom:12px}}.checks{{max-height:250px;overflow:auto;border:1px solid var(--line);border-radius:8px;padding:8px;background:#fafbfa}}.check{{display:flex;gap:8px;align-items:flex-start;padding:7px 5px;border-bottom:1px solid #edf0ed}}.check:last-child{{border-bottom:0}}.check label{{font-weight:500;margin:0}}
button,.button{{display:inline-block;border:0;border-radius:8px;padding:9px 13px;background:var(--green);color:#fff;font-weight:700;cursor:pointer;text-decoration:none;font-size:13px}}.button.secondary,button.secondary{{background:#fff;color:var(--green);border:1px solid var(--line)}}.actions{{display:flex;gap:8px;flex-wrap:wrap;align-items:center}}
.meta,.muted{{font-size:11px;color:var(--muted)}}.error{{background:#fff0f0;border:1px solid #e5bcbc;color:#6d2929;border-radius:9px;padding:11px;margin-bottom:14px}}.notice{{background:#f4f8f5;border:1px solid #cfded4;border-radius:9px;padding:11px;margin-bottom:14px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:8px 7px;border-bottom:1px solid #edf0ed;text-align:left;vertical-align:top}}th{{font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}}.login{{max-width:460px;margin:70px auto}}.hidden{{display:none}}
footer{{font-size:11px;color:var(--muted);padding-top:18px}}@media(max-width:760px){{.grid{{grid-template-columns:1fr}}header .shell{{align-items:flex-start;flex-direction:column}}.who{{text-align:left}}.shell{{padding-left:14px;padding-right:14px}}}}
</style></head><body>
<header><div class="shell"><div class="brand">Climate Intelligence Private Pilot<small>Mangrove Intelligence · Named-user access</small></div>{identity_html}</div></header>
<main class="shell">{body}<footer>Pilot access layer only. Analytical calculations remain in the governed engine and Decision Workspace adapter.</footer></main>
</body></html>"""


def render_login(error: str | None = None) -> str:
    error_html = f'<div class="error">{_esc(error)}</div>' if error else ""
    return _layout(
        "Sign in",
        f"""<div class="login panel"><h1>Sign in</h1>
<p class="lead">Use your named pilot account and authorized tenant.</p>
{error_html}
<form method="post" action="/login">
<div class="field"><label for="username">Username</label><input id="username" name="username" type="text" maxlength="{MAX_LOGIN_USERNAME_CHARS}" autocomplete="username" required></div>
<div class="field"><label for="tenant">Tenant key</label><input id="tenant" name="tenant" type="text" maxlength="{MAX_LOGIN_TENANT_CHARS}" autocomplete="organization" required></div>
<div class="field"><label for="password">Password</label><input id="password" name="password" type="password" maxlength="{MAX_PASSWORD_CHARS}" autocomplete="current-password" required></div>
<button type="submit">Sign in</button></form></div>""",
    )


def _run_label(row: dict[str, Any]) -> str:
    params = row.get("parameters") or {}
    bits = [row.get("pipeline_name") or "pipeline", row.get("pipeline_version") or ""]
    if params.get("year"):
        bits.append(f"year={params['year']}")
    if params.get("return_period"):
        bits.append(f"RP{params['return_period']}")
    return " · ".join(str(x) for x in bits if str(x))


def render_dashboard(
    catalog: dict[str, Any],
    *,
    identity: dict[str, Any],
    csrf: str,
    error: str | None = None,
) -> str:
    can_generate = role_allows(identity["role"], "GENERATE_REPORT")
    error_html = f'<div class="error">{_esc(error)}</div>' if error else ""

    assets = "".join(
        f'<option value="{_esc(x["asset_location_id"])}">{_esc(x["external_system"])}:{_esc(x["external_id"])} · {_esc(x["asset_type"])}</option>'
        for x in catalog["assets"]
    )
    portfolios = "".join(
        f'<option value="{_esc(x["portfolio_id"])}">{_esc(x["portfolio_id"])} · {int(x["exposure_row_count"])} rows</option>'
        for x in catalog["portfolios"]
    )
    runs = "".join(
        f"""<div class="check"><input type="checkbox" id="run-{idx}" name="indicator_run" value="{_esc(x["run_id"])}">
<label for="run-{idx}">{_esc(_run_label(x))}<div class="meta">{_esc(x["run_id"])} · {int(x["indicator_row_count"])} rows</div></label></div>"""
        for idx, x in enumerate(catalog["indicator_runs"])
    ) or '<div class="muted">No successful indicator runs are available.</div>'
    compound = '<option value="">None</option>' + "".join(
        f'<option value="{_esc(x["run_id"])}">{_esc(_run_label(x))}</option>'
        for x in catalog["compound_runs"]
    )
    routes = '<option value="">None</option>' + "".join(
        f'<option value="{_esc(x["run_id"])}">{_esc(_run_label(x))}</option>'
        for x in catalog["route_runs"]
    )

    report_rows = "".join(
        f"""<tr><td>{_esc(x.get("generated_at"))}</td><td>{_esc(x.get("scope_type"))}</td><td>{_esc(x.get("subject_id"))}</td>
<td><a class="button secondary" href="/report?path={quote(x["html_path"])}">Open</a>
<a class="button secondary" href="/file?path={quote(x["json_path"])}">JSON</a>
<a class="button secondary" href="/file?path={quote(x["manifest_path"])}">Manifest</a></td></tr>"""
        for x in catalog["reports"]
    ) or '<tr><td colspan="4" class="muted">No generated private reports.</td></tr>'

    if can_generate:
        generate_panel = f"""<section class="panel"><h2>Generate report</h2>
<p class="muted">Every analytical run is selected explicitly; the application does not choose a latest vintage.</p>
<form method="post" action="/generate"><input type="hidden" name="csrf" value="{_esc(csrf)}">
<div class="field"><label>Scope</label><div class="actions">
<label><input type="radio" name="scope" value="ASSET" checked onchange="toggleScope()"> Asset</label>
<label><input type="radio" name="scope" value="PORTFOLIO" onchange="toggleScope()"> Portfolio</label></div></div>
<div id="asset-field" class="field"><label>Asset</label><select name="asset_location_id">{assets}</select></div>
<div id="portfolio-field" class="field hidden"><label>Portfolio</label><select name="portfolio_id">{portfolios}</select></div>
<div class="field"><label>Indicator runs (maximum {MAX_INDICATOR_RUNS})</label><div class="checks">{runs}</div></div>
<div class="field"><label>Compound run</label><select name="compound_run">{compound}</select></div>
<div class="field"><label>Logistics run</label><select name="route_run">{routes}</select></div>
<div class="field"><label>Portfolio footprint hazard indicator</label><input type="text" name="flood_indicator_id" value="flood_rp100_depth_m"></div>
<button type="submit">Generate private report</button></form></section>"""
    else:
        generate_panel = """<section class="panel"><h2>Report generation</h2>
<p class="lead">Your VIEWER role can open existing reports but cannot generate new analytical reports.</p></section>"""

    admin_link = (
        '<a class="button secondary" href="/audit">Audit log</a>'
        if role_allows(identity["role"], "VIEW_AUDIT")
        else ""
    )

    body = f"""<h1>Decision workspace</h1>
<p class="lead">Named-user private pilot with tenant and role authorization.</p>{error_html}
<div class="grid">{generate_panel}
<section class="panel"><h2>Tenant readiness</h2>
<table><tbody>
<tr><th>Assets</th><td>{len(catalog["assets"])}</td></tr>
<tr><th>Portfolios</th><td>{len(catalog["portfolios"])}</td></tr>
<tr><th>Indicator runs</th><td>{len(catalog["indicator_runs"])}</td></tr>
<tr><th>Compound runs</th><td>{len(catalog["compound_runs"])}</td></tr>
<tr><th>Logistics runs</th><td>{len(catalog["route_runs"])}</td></tr>
</tbody></table>
<div class="actions" style="margin-top:16px">{admin_link}
<form method="post" action="/logout"><input type="hidden" name="csrf" value="{_esc(csrf)}"><button class="secondary" type="submit">Sign out</button></form></div>
</section></div>
<section class="panel"><h2>Generated reports</h2><table><thead><tr><th>Generated</th><th>Scope</th><th>Subject</th><th>Files</th></tr></thead><tbody>{report_rows}</tbody></table></section>
<script>function toggleScope(){{const s=document.querySelector('input[name="scope"]:checked').value;document.getElementById('asset-field').classList.toggle('hidden',s!=='ASSET');document.getElementById('portfolio-field').classList.toggle('hidden',s!=='PORTFOLIO');}}</script>"""
    return _layout("Decision workspace", body, identity=identity)


def render_audit(root: str | Path, *, identity: dict[str, Any], csrf: str) -> str:
    if not role_allows(identity["role"], "VIEW_AUDIT"):
        raise PermissionError("Audit access requires ADMIN role")
    chain = verify_audit_chain(root)
    with connect_catalog(root) as conn:
        rows = conn.execute(
            """
            SELECT audit_event_id,occurred_at,actor_user_id,tenant_key,action,
                   target_type,target_id,outcome
            FROM workspace_audit_event
            WHERE tenant_key=? OR tenant_key IS NULL
            ORDER BY audit_event_id DESC
            LIMIT 100
            """,
            (identity["tenant_key"],),
        ).fetchall()
    body_rows = "".join(
        f"<tr><td>{int(x['audit_event_id'])}</td><td>{_esc(x['occurred_at'])}</td><td>{_esc(x['action'])}</td><td>{_esc(x['outcome'])}</td><td>{_esc(x['target_type'])}</td><td>{_esc(x['target_id'])}</td></tr>"
        for x in rows
    ) or '<tr><td colspan="6" class="muted">No audit events.</td></tr>'
    status = "VALID" if chain["valid"] else f'INVALID at event {chain["failed_event_id"]}'
    return _layout(
        "Audit log",
        f"""<h1>Audit log</h1><p class="lead">Tamper-evident chain status: <strong>{_esc(status)}</strong> · checked events: {int(chain["checked_events"])}</p>
<div class="actions"><a class="button secondary" href="/">Back to workspace</a>
<form method="post" action="/logout"><input type="hidden" name="csrf" value="{_esc(csrf)}"><button class="secondary" type="submit">Sign out</button></form></div>
<section class="panel" style="margin-top:16px"><table><thead><tr><th>ID</th><th>Time</th><th>Action</th><th>Outcome</th><th>Target type</th><th>Target</th></tr></thead><tbody>{body_rows}</tbody></table></section>""",
        identity=identity,
    )


def make_pilot_handler(
    root: str | Path,
    *,
    session_minutes: int = DEFAULT_SESSION_MINUTES,
    secure_cookie: bool = True,
    login_attempts_per_key: int = DEFAULT_LOGIN_ATTEMPTS_PER_KEY,
    login_window_seconds: int = DEFAULT_LOGIN_WINDOW_SECONDS,
    login_global_attempts: int = DEFAULT_LOGIN_GLOBAL_ATTEMPTS,
    login_global_window_seconds: int = DEFAULT_LOGIN_GLOBAL_WINDOW_SECONDS,
):
    private_root = _private_root(root)
    login_limiter = _LoginRateLimiter(
        attempts_per_key=login_attempts_per_key,
        window_seconds=login_window_seconds,
        global_attempts=login_global_attempts,
        global_window_seconds=login_global_window_seconds,
    )

    class Handler(BaseHTTPRequestHandler):
        server_version = "CLRPrivatePilot/0.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            message = _privacy_safe_log_message(fmt, args)
            print(f"[pilot] {self.client_address[0]} {message}")

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

        def _html(
            self,
            status: int,
            content: str,
            *,
            extra: list[tuple[str, str]] | None = None,
        ) -> None:
            data = content.encode("utf-8")
            self._headers(status, content_length=len(data), extra=extra)
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

        def _service_unavailable(self) -> None:
            self._html(
                503,
                _layout(
                    "Temporarily unavailable",
                    '<div class="error">The private workspace is temporarily unavailable. Please retry or contact the administrator.</div>',
                ),
                extra=[("Retry-After", "1")],
            )

        def _token(self) -> str | None:
            return _parse_cookie(self.headers.get("Cookie")).get(PILOT_SESSION_COOKIE)

        def _identity(self) -> tuple[str, dict[str, Any]] | tuple[None, None]:
            token = self._token()
            if not token:
                return None, None
            identity = verify_session(private_root, token)
            if identity is None:
                return None, None
            return token, identity

        def _require_auth(self) -> tuple[str, dict[str, Any]] | tuple[None, None]:
            token, identity = self._identity()
            if identity is None:
                self._redirect("/login")
                return None, None
            return token, identity

        def _form(
            self,
            *,
            max_bytes: int = MAX_FORM_BYTES,
        ) -> dict[str, list[str]]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0 or length > int(max_bytes):
                if length > int(max_bytes):
                    self.close_connection = True
                raise ValueError("Invalid form size")
            ctype = self.headers.get("Content-Type", "")
            if not ctype.startswith("application/x-www-form-urlencoded"):
                raise ValueError("Unsupported form content type")
            raw = self.rfile.read(length).decode("utf-8")
            return parse_qs(raw, keep_blank_values=True)

        def _cookie_header(self, token: str, *, max_age: int) -> str:
            secure = "; Secure" if secure_cookie else ""
            return (
                f"{PILOT_SESSION_COOKIE}={token}; Path=/; HttpOnly; "
                f"SameSite=Strict; Max-Age={int(max_age)}{secure}"
            )

        def _login_origin_allowed(self) -> bool:
            origin = self.headers.get("Origin")
            if not origin:
                return True
            parsed = urlparse(origin)
            expected_scheme = "https" if secure_cookie else "http"
            host = (self.headers.get("Host") or "").strip().lower()
            return (
                parsed.scheme.lower() == expected_scheme
                and parsed.netloc.lower() == host
                and not parsed.path.strip("/")
                and not parsed.query
                and not parsed.fragment
            )

        def _do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/login":
                _, identity = self._identity()
                if identity:
                    self._redirect("/")
                else:
                    self._html(200, render_login())
                return

            token, identity = self._require_auth()
            if identity is None or token is None:
                return
            csrf = _csrf_for_token(token)

            if parsed.path == "/":
                self._html(
                    200,
                    render_dashboard(
                        workspace_catalog(private_root, identity["tenant_key"]),
                        identity=identity,
                        csrf=csrf,
                    ),
                )
                return

            if parsed.path == "/audit":
                if not role_allows(identity["role"], "VIEW_AUDIT"):
                    record_audit_event(
                        private_root,
                        actor_user_id=identity["user_id"],
                        tenant_key=identity["tenant_key"],
                        action="AUDIT_VIEW",
                        outcome="DENIED",
                    )
                    self._html(403, _layout("Forbidden", '<div class="error">ADMIN role required.</div>', identity=identity))
                    return
                record_audit_event(
                    private_root,
                    actor_user_id=identity["user_id"],
                    tenant_key=identity["tenant_key"],
                    action="AUDIT_VIEW",
                    outcome="SUCCESS",
                )
                self._html(200, render_audit(private_root, identity=identity, csrf=csrf))
                return

            if parsed.path in {"/report", "/file"}:
                if not role_allows(identity["role"], "VIEW_REPORT"):
                    self._html(403, _layout("Forbidden", '<div class="error">Report access denied.</div>', identity=identity))
                    return
                relative = parse_qs(parsed.query).get("path", [""])[0]
                try:
                    suffixes = (".html",) if parsed.path == "/report" else (".json",)
                    target = _safe_output_file(
                        private_root,
                        identity["tenant_key"],
                        relative,
                        suffixes=suffixes,
                    )
                    data = target.read_bytes()
                    ctype = (
                        "text/html; charset=utf-8"
                        if parsed.path == "/report"
                        else "application/json; charset=utf-8"
                    )
                    record_audit_event(
                        private_root,
                        actor_user_id=identity["user_id"],
                        tenant_key=identity["tenant_key"],
                        action="REPORT_VIEWED" if parsed.path == "/report" else "REPORT_FILE_VIEWED",
                        outcome="SUCCESS",
                        target_type="REPORT_FILE",
                        target_id=target.name,
                    )
                    self._headers(200, content_type=ctype, content_length=len(data))
                    self.wfile.write(data)
                except (ValueError, FileNotFoundError):
                    record_audit_event(
                        private_root,
                        actor_user_id=identity["user_id"],
                        tenant_key=identity["tenant_key"],
                        action="REPORT_FILE_ACCESS",
                        outcome="DENIED",
                    )
                    self._html(404, _layout("Not found", '<div class="error">Report file not available.</div>', identity=identity))
                return

            self._html(404, _layout("Not found", "<h1>Not found</h1>", identity=identity))

        def _do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/login":
                try:
                    if not self._login_origin_allowed():
                        self._html(
                            403,
                            render_login("Sign-in request origin was not accepted."),
                        )
                        return
                    form = self._form(max_bytes=MAX_LOGIN_FORM_BYTES)
                    username = form.get("username", [""])[0]
                    tenant = form.get("tenant", [""])[0]
                    password = form.get("password", [""])[0]
                    if (
                        len(username) > MAX_LOGIN_USERNAME_CHARS
                        or len(tenant) > MAX_LOGIN_TENANT_CHARS
                        or len(password) > MAX_PASSWORD_CHARS
                    ):
                        self._html(
                            401,
                            render_login("Invalid account, tenant, or password."),
                        )
                        return
                    if not login_limiter.allow(username, tenant):
                        self._html(
                            429,
                            render_login("Too many sign-in attempts. Please retry later."),
                            extra=[("Retry-After", "60")],
                        )
                        return
                    identity = authenticate_user(
                        private_root,
                        username=username,
                        password=password,
                        tenant_key=tenant,
                    )
                    if identity is None:
                        record_audit_event(
                            private_root,
                            actor_user_id=None,
                            tenant_key=_audit_tenant_or_none(tenant),
                            action="LOGIN",
                            outcome="DENIED",
                            detail=_login_audit_detail(username),
                        )
                        self._html(
                            401,
                            render_login("Invalid account, tenant, or password."),
                        )
                        return
                    login_limiter.reset(username, tenant)
                    token, session = create_session(
                        private_root,
                        user_id=identity["user_id"],
                        tenant_key=identity["tenant_key"],
                        role=identity["role"],
                        ttl_minutes=session_minutes,
                        user_agent=(self.headers.get("User-Agent") or "")[:512],
                        client_label="PRIVATE_PILOT_WEB",
                    )
                    record_audit_event(
                        private_root,
                        actor_user_id=identity["user_id"],
                        tenant_key=identity["tenant_key"],
                        action="LOGIN",
                        outcome="SUCCESS",
                        target_type="SESSION",
                        target_id=session["session_id"],
                    )
                    self._redirect(
                        "/",
                        extra=[
                            (
                                "Set-Cookie",
                                self._cookie_header(
                                    token,
                                    max_age=session_minutes * 60,
                                ),
                            )
                        ],
                    )
                except (sqlite3.OperationalError, AuditStateError):
                    raise
                except Exception:
                    self._html(401, render_login("Sign-in failed."))
                return

            token, identity = self._require_auth()
            if identity is None or token is None:
                return
            try:
                form = self._form()
            except ValueError as exc:
                self._html(400, _layout("Invalid request", f'<div class="error">{_esc(exc)}</div>', identity=identity))
                return

            if not _validate_csrf(token, form.get("csrf", [""])[0]):
                record_audit_event(
                    private_root,
                    actor_user_id=identity["user_id"],
                    tenant_key=identity["tenant_key"],
                    action="CSRF_CHECK",
                    outcome="DENIED",
                )
                self._html(403, _layout("Forbidden", '<div class="error">Invalid CSRF token.</div>', identity=identity))
                return

            if parsed.path == "/logout":
                revoke_session(
                    private_root,
                    token=token,
                    actor_user_id=identity["user_id"],
                )
                expired = self._cookie_header("", max_age=0)
                self._redirect("/login", extra=[("Set-Cookie", expired)])
                return

            if parsed.path == "/generate":
                if not role_allows(identity["role"], "GENERATE_REPORT"):
                    record_audit_event(
                        private_root,
                        actor_user_id=identity["user_id"],
                        tenant_key=identity["tenant_key"],
                        action="REPORT_GENERATE",
                        outcome="DENIED",
                    )
                    self._html(403, _layout("Forbidden", '<div class="error">Your role cannot generate reports.</div>', identity=identity))
                    return
                try:
                    scope = form.get("scope", [""])[0].strip().upper()
                    runs = [x.strip() for x in form.get("indicator_run", []) if x.strip()]
                    if not runs:
                        raise ValueError("Select at least one successful indicator run.")
                    if len(runs) > MAX_INDICATOR_RUNS:
                        raise ValueError(
                            f"Select no more than {MAX_INDICATOR_RUNS} indicator runs."
                        )
                    kwargs: dict[str, Any] = {
                        "scope_type": scope,
                        "tenant_key": identity["tenant_key"],
                        "indicator_run_ids": runs,
                        "compound_run_id": form.get("compound_run", [""])[0].strip() or None,
                        "route_run_id": form.get("route_run", [""])[0].strip() or None,
                        "flood_indicator_id": form.get("flood_indicator_id", ["flood_rp100_depth_m"])[0].strip() or "flood_rp100_depth_m",
                    }
                    if scope == "ASSET":
                        kwargs["asset_location_id"] = form.get("asset_location_id", [""])[0].strip()
                    elif scope == "PORTFOLIO":
                        kwargs["portfolio_id"] = form.get("portfolio_id", [""])[0].strip()
                    else:
                        raise ValueError("Scope must be ASSET or PORTFOLIO.")
                    result = build_and_write_private_decision_workspace(
                        private_root,
                        **kwargs,
                    )
                    record_audit_event(
                        private_root,
                        actor_user_id=identity["user_id"],
                        tenant_key=identity["tenant_key"],
                        action="REPORT_GENERATE",
                        outcome="SUCCESS",
                        target_type=scope,
                        target_id=result["scope"]["subject_id"],
                        detail={
                            "indicator_run_ids": runs,
                            "compound_run_id": kwargs["compound_run_id"],
                            "route_run_id": kwargs["route_run_id"],
                            "manifest": result["outputs"]["manifest"],
                        },
                    )
                    self._redirect(f'/report?path={quote(result["outputs"]["html"])}')
                except (sqlite3.OperationalError, AuditStateError):
                    raise
                except Exception as exc:
                    record_audit_event(
                        private_root,
                        actor_user_id=identity["user_id"],
                        tenant_key=identity["tenant_key"],
                        action="REPORT_GENERATE",
                        outcome="FAILURE",
                        detail={"error_type": type(exc).__name__},
                    )
                    self._html(
                        400,
                        render_dashboard(
                            workspace_catalog(private_root, identity["tenant_key"]),
                            identity=identity,
                            csrf=_csrf_for_token(token),
                            error=str(exc),
                        ),
                    )
                return

            self._html(404, _layout("Not found", "<h1>Not found</h1>", identity=identity))

        def do_GET(self) -> None:
            try:
                self._do_GET()
            except AuditStateError:
                self._service_unavailable()
            except sqlite3.OperationalError as exc:
                if not _is_sqlite_busy(exc):
                    raise
                self._service_unavailable()

        def do_POST(self) -> None:
            try:
                self._do_POST()
            except AuditStateError:
                self._service_unavailable()
            except sqlite3.OperationalError as exc:
                if not _is_sqlite_busy(exc):
                    raise
                self._service_unavailable()

    return Handler


def serve_private_pilot(
    root: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8766,
    session_minutes: int = DEFAULT_SESSION_MINUTES,
    secure_cookie: bool = True,
) -> None:
    if not _is_loopback_host(host):
        raise ValueError(
            "Private Pilot 0.1 binds only to loopback. Expose it through a hardened TLS reverse proxy."
        )
    private_root = _private_root(root)
    handler = make_pilot_handler(
        private_root,
        session_minutes=session_minutes,
        secure_cookie=secure_cookie,
    )
    server = ThreadingHTTPServer((host, int(port)), handler)
    print(f"Private pilot backend: http://{host}:{int(port)}/")
    try:
        server.serve_forever()
    finally:
        server.server_close()
