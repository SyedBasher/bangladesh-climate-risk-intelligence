from __future__ import annotations

from html import escape
from typing import Any


def _text(value: Any, fallback: str = "Not available") -> str:
    if value is None:
        return fallback
    value = str(value).strip()
    return escape(value) if value else fallback


def _display_value(row: dict[str, Any]) -> str:
    value = row.get("value")
    if value is None:
        reason = row.get("null_reason") or row.get("quality_flag") or "Unavailable"
        return f'<span class="null">Not available — {_text(reason)}</span>'
    unit = row.get("unit")
    rendered = _text(value)
    return f"{rendered} {_text(unit, '')}".strip()


def _empty(message: str) -> str:
    return f'<div class="empty">{escape(message)}</div>'


def _cards(rows: list[dict[str, Any]], *, title_key: str = "text") -> str:
    if not rows:
        return _empty("No governed evidence is available for this section.")
    parts = []
    for row in rows:
        title = row.get("finding_id") or row.get("statement_id") or row.get("level") or "Evidence"
        body = row.get(title_key) or row.get("evidence_state") or row.get("description") or "No narrative supplied."
        guardrail = row.get("guardrail")
        refs = row.get("source_refs") or row.get("research_refs") or []
        refs_html = ""
        if refs:
            refs_html = f'<div class="meta">Sources: {", ".join(_text(x) for x in refs)}</div>'
        guard_html = f'<div class="guard">{_text(guardrail)}</div>' if guardrail else ""
        parts.append(
            '<article class="card">'
            f'<div class="card-kicker">{_text(row.get("evidence_class") or row.get("level") or "EVIDENCE")}</div>'
            f'<h3>{_text(title)}</h3>'
            f'<p>{_text(body)}</p>{refs_html}{guard_html}'
            '</article>'
        )
    return '<div class="cards">' + "".join(parts) + "</div>"


def _kv_table(values: dict[str, Any]) -> str:
    if not values:
        return _empty("No readiness metadata supplied.")
    rows = []
    for key, value in values.items():
        rows.append(
            f"<tr><th>{_text(str(key).replace('_', ' ').title())}</th>"
            f"<td>{_text(value)}</td></tr>"
        )
    return '<table class="table kv"><tbody>' + "".join(rows) + "</tbody></table>"


def _direct_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return _empty("No direct physical evidence supplied.")
    body = []
    for row in rows:
        period = " – ".join(
            x for x in [_text(row.get("period_start"), ""), _text(row.get("period_end"), "")] if x
        )
        body.append(
            "<tr>"
            f"<td><strong>{_text(row.get('label') or row.get('indicator_id'))}</strong>"
            f"<div class='meta'>{_text(row.get('indicator_id'))}</div></td>"
            f"<td>{_display_value(row)}</td>"
            f"<td>{_text(row.get('value_class'))}<div class='meta'>{_text(row.get('measurement_basis'))}</div></td>"
            f"<td>{_text(row.get('source_id'))}<div class='meta'>{_text(row.get('source_vintage'))}</div></td>"
            f"<td>{_text(row.get('quality_flag'))}<div class='meta'>{period or 'Period not supplied'}</div></td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="table"><thead><tr>'
        "<th>Evidence</th><th>Value</th><th>Class / basis</th><th>Source / vintage</th><th>Quality / period</th>"
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>"
    )


def _generic_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return _empty("No governed evidence is available for this section.")
    head = "".join(f"<th>{escape(label)}</th>" for _, label in columns)
    body = []
    for row in rows:
        cells = []
        for key, _ in columns:
            if key == "value":
                cell = _display_value(row)
            else:
                cell = _text(row.get(key))
            cells.append(f"<td>{cell}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="table-wrap"><table class="table"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def _missing_data(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return _empty("No additional data requests were supplied.")
    parts = []
    for row in rows:
        why = row.get("why_it_matters")
        question = row.get("decision_question")
        source = row.get("source_module")
        extra = []
        if why:
            extra.append(f"Why it matters: {_text(why)}")
        if question:
            extra.append(f"Decision question: {_text(question)}")
        if source:
            extra.append(f"Raised by: {_text(source)}")
        parts.append(
            '<article class="missing">'
            f'<h3>{_text(row.get("data_item"))}</h3>'
            + "".join(f"<p>{x}</p>" for x in extra)
            + "</article>"
        )
    return '<div class="missing-grid">' + "".join(parts) + "</div>"


def _provenance(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return _empty("No additional provenance manifest supplied.")
    parts = []
    for row in rows:
        source = row.get("source_module") or row.get("source_id") or "Evidence source"
        manifest = row.get("input_manifest")
        detail = ""
        if isinstance(manifest, dict):
            inputs = manifest.get("inputs", [])
            if inputs:
                detail = "<ul>" + "".join(
                    f"<li>{_text(x.get('dataset_name') or x.get('source_id') or 'input')}"
                    + (f" · {_text(x.get('partition_spec'))}" if x.get("partition_spec") else "")
                    + "</li>"
                    for x in inputs
                    if isinstance(x, dict)
                ) + "</ul>"
        parts.append(f'<article class="provenance"><h3>{_text(source)}</h3>{detail or "<p>Manifest retained in the structured report.</p>"}</article>')
    return '<div class="cards">' + "".join(parts) + "</div>"


def render_decision_workspace_html(
    report: dict[str, Any],
    *,
    document_title: str = "Decision Report",
    synthetic: bool = False,
) -> str:
    """Render a governed workspace object as standalone printable HTML.

    This function is intentionally presentation-only. It does not calculate
    hazards, scores, losses, rankings, or new narrative findings.
    """
    if report.get("report_type") != "DECISION_PORTFOLIO_WORKSPACE":
        raise ValueError("Expected DECISION_PORTFOLIO_WORKSPACE report")

    scope = report.get("scope") or {}
    subject = _text(scope.get("subject_id"))
    scope_type = _text(scope.get("scope_type"))
    tenant = _text(scope.get("tenant_scope"))
    synthetic_label = '<span class="pill">Synthetic public demonstration</span>' if synthetic else ""

    cross = report.get("cross_asset_portfolio") or {}
    compound_metrics = list(cross.get("cross_asset_metrics") or [])
    shared = list(cross.get("shared_bottlenecks") or [])
    portfolio_metrics = list(cross.get("portfolio_metrics") or [])

    compound_table = _generic_table(
        compound_metrics,
        [
            ("metric_id", "Metric"),
            ("value", "Value"),
            ("denominator", "Denominator"),
            ("quality_flag", "Quality"),
        ],
    )
    shared_table = _generic_table(
        shared,
        [
            ("physical_edge_key", "Physical edge"),
            ("distinct_asset_count", "Distinct assets"),
            ("distinct_dependency_count", "Dependencies"),
            ("max_jrc_depth_m", "Max modelled depth (m)"),
        ],
    )
    portfolio_table = _generic_table(
        portfolio_metrics,
        [
            ("metric_id", "Metric"),
            ("value", "Value"),
            ("classification", "Classification"),
            ("quality_flag", "Quality"),
        ],
    )

    guardrails = report.get("guardrails") or []
    guardrail_html = "<ul>" + "".join(f"<li>{_text(x)}</li>" for x in guardrails) + "</ul>"

    source_modules = report.get("source_modules") or []
    modules_html = " · ".join(
        f"{_text(x.get('report_type'))} {_text(x.get('schema_version'), '')}".strip()
        for x in source_modules
    ) or "No source modules listed"

    css = """
:root{--ink:#18221b;--muted:#667068;--line:#dce2dd;--panel:#fff;--soft:#f3f6f3;--green:#173f2b;--green2:#2d6a4f;--amber:#7b581d}
*{box-sizing:border-box}
body{margin:0;background:#f5f6f4;color:var(--ink);font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;line-height:1.48}
.shell{max-width:1180px;margin:0 auto;padding:32px 26px 56px}
header{background:var(--green);color:white}
header .shell{padding-top:30px;padding-bottom:30px}
.eyebrow,.card-kicker{font-size:11px;letter-spacing:.1em;text-transform:uppercase;font-weight:750}
header .eyebrow{color:#dbe8df}
h1{font-size:38px;line-height:1.08;margin:7px 0 9px;letter-spacing:-.03em}
header p{margin:0;color:rgba(255,255,255,.78)}
.pill{display:inline-block;margin-top:16px;border:1px solid rgba(255,255,255,.28);border-radius:999px;padding:6px 10px;font-size:11px}
.toolbar{display:flex;justify-content:flex-end;margin-bottom:18px}.toolbar button{border:1px solid var(--line);background:white;border-radius:8px;padding:8px 12px;cursor:pointer}
section{margin-top:22px;background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:20px;break-inside:avoid}
h2{font-size:21px;margin:0 0 5px;letter-spacing:-.015em}
.section-note{font-size:13px;color:var(--muted);margin-bottom:14px}
.cards,.missing-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.card,.missing,.provenance{border:1px solid var(--line);border-radius:10px;padding:14px;background:#fff;break-inside:avoid}
.card-kicker{color:var(--green2)}
.card h3,.missing h3,.provenance h3{font-size:15px;margin:4px 0 7px}.card p,.missing p,.provenance p{font-size:13px;color:#465049;margin:0}
.meta,.guard{font-size:11px;color:var(--muted);margin-top:8px}.guard{border-top:1px solid #edf0ed;padding-top:8px}
.table-wrap{overflow-x:auto}.table{width:100%;border-collapse:collapse;font-size:12px}.table th,.table td{padding:9px 8px;border-bottom:1px solid #edf0ed;text-align:left;vertical-align:top}.table th{font-size:10px;text-transform:uppercase;letter-spacing:.055em;color:var(--muted)}.kv th{width:34%}
.null{color:var(--amber)}.empty{background:var(--soft);color:var(--muted);border-radius:9px;padding:13px;font-size:12px}
.guardrails{background:#fffaf0}.guardrails li+li{margin-top:5px}
.subsection{margin-top:16px}.subsection h3{font-size:14px;margin:0 0 8px}
footer{margin-top:22px;color:var(--muted);font-size:11px}
@media(max-width:700px){.shell{padding-left:14px;padding-right:14px}h1{font-size:30px}section{padding:15px}.cards,.missing-grid{grid-template-columns:1fr}}
@media print{
  @page{size:A4;margin:14mm}
  body{background:white;font-size:10pt}
  header{background:white;color:var(--ink);border-bottom:2px solid var(--green)}
  header .shell{padding:0 0 14px}header .eyebrow,header p{color:var(--muted)}
  .shell{max-width:none;padding:0}.no-print{display:none!important}
  section{border:0;border-top:1px solid var(--line);border-radius:0;padding:14px 0;margin-top:10px;box-shadow:none}
  .table-wrap{overflow:visible}.card,.missing,.provenance{break-inside:avoid}
  a{color:inherit;text-decoration:none}
}
"""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_text(document_title)} · {subject}</title>
<style>{css}</style>
</head>
<body>
<header>
  <div class="shell">
    <div class="eyebrow">Bangladesh Climate &amp; Location Risk Intelligence · Mangrove Intelligence</div>
    <h1>{_text(document_title)}</h1>
    <p>{scope_type} · {subject} · Tenant scope: {tenant}</p>
    {synthetic_label}
  </div>
</header>
<main class="shell">
  <div class="toolbar no-print"><button type="button" onclick="window.print()">Print / Save as PDF</button></div>

  <section>
    <h2>Executive evidence summary</h2>
    <div class="section-note">Descriptive evidence statements only. No overall climate-risk score.</div>
    {_cards(list(report.get("executive_evidence_summary") or []))}
  </section>

  <section>
    <h2>Asset and data readiness</h2>
    <div class="section-note">Identity, coordinate and completeness information used to judge which evidence can be attached defensibly.</div>
    {_kv_table(dict(report.get("data_readiness") or {}))}
  </section>

  <section>
    <h2>Direct physical evidence</h2>
    <div class="section-note">Source, vintage, measurement basis, value class and quality remain visible.</div>
    {_direct_table(list(report.get("direct_physical_evidence") or []))}
  </section>

  <section>
    <h2>Second-order exposure</h2>
    <div class="section-note">Transparent exposure arithmetic or governed second-order evidence, not estimated loss.</div>
    {_cards(list(report.get("second_order_exposure") or []))}
  </section>

  <section>
    <h2>Compound evidence</h2>
    <div class="section-note">Co-occurrence or combined evidence states remain separate from causal or economic-loss claims.</div>
    {_cards(list(report.get("compound_evidence") or []), title_key="evidence_state")}
  </section>

  <section>
    <h2>Operational transmission</h2>
    <div class="section-note">Operational channels are shown only where evidence or an explicit question exists.</div>
    {_cards(list(report.get("operational_transmission") or []))}
  </section>

  <section>
    <h2>Logistics dependencies</h2>
    <div class="section-note">Route hazard exposure does not establish road closure or impassability.</div>
    {_cards(list(report.get("logistics_dependencies") or []), title_key="evidence_state")}
  </section>

  <section>
    <h2>Cross-asset and portfolio evidence</h2>
    <div class="section-note">Counts, shares and financial exposure/concentration remain separate. Share denominators are shown explicitly.</div>
    <div class="subsection"><h3>Cross-asset metrics</h3>{compound_table}</div>
    <div class="subsection"><h3>Shared bottlenecks</h3>{shared_table}</div>
    <div class="subsection"><h3>Portfolio metrics</h3>{portfolio_table}</div>
  </section>

  <section>
    <h2>What data would change the answer?</h2>
    <div class="section-note">Missing information that could materially refine interpretation or enable a separately governed model.</div>
    {_missing_data(list(report.get("what_data_would_change_the_answer") or []))}
  </section>

  <section>
    <h2>Evidence provenance</h2>
    <div class="section-note">Source modules: {modules_html}</div>
    {_provenance(list(report.get("evidence_provenance") or []))}
  </section>

  <section class="guardrails">
    <h2>Guardrails</h2>
    {guardrail_html}
  </section>

  <footer>Generated from a structured DECISION_PORTFOLIO_WORKSPACE object. The renderer does not calculate hazards, scores, losses or new findings.</footer>
</main>
</body>
</html>
"""
