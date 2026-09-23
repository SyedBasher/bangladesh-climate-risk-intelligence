from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.era5_local import request_plan
from clr.local_assets import accepted_assets

parser = argparse.ArgumentParser(
    description="Plan authoritative ERA5-Land daily max/min requests for accepted private assets."
)
parser.add_argument("--year", required=True, type=int)
parser.add_argument(
    "--root",
    default=os.getenv("CLR_PRIVATE_DATA", str(ROOT / "private_data")),
)
parser.add_argument("--tenant", default=None)
args = parser.parse_args()

assets = accepted_assets(args.root, tenant_key=args.tenant)
if not assets:
    raise SystemExit("No EXACT_SITE + RESOLVED private assets are available.")

plan = request_plan(assets, args.year)
outdir = Path(args.root).resolve() / "manifests" / "plans" / "era5_land"
outdir.mkdir(parents=True, exist_ok=True)
path = outdir / f"era5_land_daily_{args.year}.json"
path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

print(json.dumps({
    "accepted_assets": len(assets),
    "year": args.year,
    "requests": len(plan),
    "plan_path": str(path),
}, indent=2))
