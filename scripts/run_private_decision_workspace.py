from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.private_decision_workspace import build_and_write_private_decision_workspace


parser = argparse.ArgumentParser(
    description="Assemble a governed decision workspace from explicit private local runs."
)
parser.add_argument(
    "--root",
    default=os.getenv("CLR_PRIVATE_DATA", str(ROOT / "private_data")),
)
parser.add_argument("--scope", choices=["ASSET", "PORTFOLIO"], required=True)
parser.add_argument("--tenant", required=True)
parser.add_argument(
    "--indicator-run",
    action="append",
    dest="indicator_runs",
    required=True,
    help="Explicit successful processing run ID. Repeat for multiple indicator pipelines.",
)
parser.add_argument("--compound-run")
parser.add_argument("--route-run")
parser.add_argument("--asset-location-id")
parser.add_argument("--external-system")
parser.add_argument("--external-id")
parser.add_argument("--portfolio-id")
parser.add_argument("--flood-indicator-id", default="flood_rp100_depth_m")
args = parser.parse_args()

result = build_and_write_private_decision_workspace(
    args.root,
    scope_type=args.scope,
    tenant_key=args.tenant,
    indicator_run_ids=args.indicator_runs,
    asset_location_id=args.asset_location_id,
    external_system=args.external_system,
    external_id=args.external_id,
    portfolio_id=args.portfolio_id,
    compound_run_id=args.compound_run,
    route_run_id=args.route_run,
    flood_indicator_id=args.flood_indicator_id,
)
print(json.dumps(result, indent=2))
