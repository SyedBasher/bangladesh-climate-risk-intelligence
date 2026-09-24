from __future__ import annotations

import argparse
import json
from pathlib import Path

from clr.decision_report_html import render_decision_workspace_html
from clr.synthetic_decision_demo import synthetic_decision_workspace_report


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HTML = ROOT / "examples" / "synthetic" / "decision_workspace_demo.html"
DEFAULT_JSON = ROOT / "examples" / "synthetic" / "decision_workspace_demo.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the synthetic public Decision Reports & Portfolio Workspace demo."
    )
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    args = parser.parse_args()

    report = synthetic_decision_workspace_report()
    html = render_decision_workspace_html(
        report,
        document_title="Synthetic Decision & Portfolio Report",
        synthetic=True,
    )

    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.html.write_text(html, encoding="utf-8")
    args.json.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
