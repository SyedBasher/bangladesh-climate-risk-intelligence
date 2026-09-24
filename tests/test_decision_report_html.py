from pathlib import Path

import pytest

from clr.decision_report_html import render_decision_workspace_html
from clr.synthetic_decision_demo import synthetic_decision_workspace_report


ROOT = Path(__file__).resolve().parents[1]


def test_synthetic_workspace_is_structured_and_non_scored():
    report = synthetic_decision_workspace_report()
    assert report["report_type"] == "DECISION_PORTFOLIO_WORKSPACE"
    assert report["scope"]["tenant_scope"] == "SYNTHETIC_PUBLIC"
    assert len(report["direct_physical_evidence"]) == 7
    assert any(
        row["value"] is None and row["null_reason"]
        for row in report["direct_physical_evidence"]
    )
    assert all(
        row.get("denominator") is not None
        for row in report["cross_asset_portfolio"]["cross_asset_metrics"]
        if row.get("unit") == "share"
    )
    assert "risk_score" not in str(report).lower()
    assert "composite_score" not in str(report).lower()


def test_html_renderer_is_presentation_only_and_printable():
    report = synthetic_decision_workspace_report()
    html = render_decision_workspace_html(
        report,
        document_title="Synthetic Decision & Portfolio Report",
        synthetic=True,
    )
    lower = html.lower()
    assert "synthetic public demonstration" in lower
    assert "print / save as pdf" in lower
    assert "@media print" in lower
    assert "executive evidence summary" in lower
    assert "direct physical evidence" in lower
    assert "what data would change the answer?" in lower
    assert "not available" in lower
    assert "no overall climate-risk score" in lower
    assert html.count("<th>Denominator</th>") >= 2
    assert report["cross_asset_portfolio"]["portfolio_metrics"][0]["denominator_count"] == 4
    assert "risk_score" not in lower
    assert "composite_score" not in lower


def test_html_renderer_escapes_user_supplied_content():
    report = synthetic_decision_workspace_report()
    report["executive_evidence_summary"][0]["text"] = "<script>alert(1)</script>"
    html = render_decision_workspace_html(report, synthetic=True)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_html_renderer_rejects_wrong_report_type():
    with pytest.raises(ValueError):
        render_decision_workspace_html({"report_type": "ASSET_INTELLIGENCE"})


def test_committed_synthetic_demo_files_are_present_and_safe():
    html_path = ROOT / "examples" / "synthetic" / "decision_workspace_demo.html"
    json_path = ROOT / "examples" / "synthetic" / "decision_workspace_demo.json"
    assert html_path.exists()
    assert json_path.exists()
    html = html_path.read_text(encoding="utf-8").lower()
    json_text = json_path.read_text(encoding="utf-8").lower()
    assert "synthetic public demonstration" in html
    assert "decision_portfolio_workspace" in json_text
    assert "risk_score" not in html
    assert "risk_score" not in json_text
