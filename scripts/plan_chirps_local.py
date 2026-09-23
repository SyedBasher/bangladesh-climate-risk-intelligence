from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.chirps import BASELINE_END, BASELINE_START, expected_days
from clr.chirps_local import asset_signature, required_years, year_urls
from clr.local_assets import coarse_climate_assets

parser = argparse.ArgumentParser(
    description="Plan CHIRPS v3 final RNL source-subset extraction for private assets."
)
parser.add_argument("--year", type=int, default=2025)
parser.add_argument("--baseline-start", type=int, default=BASELINE_START)
parser.add_argument("--baseline-end", type=int, default=BASELINE_END)
parser.add_argument(
    "--root",
    default=os.getenv("CLR_PRIVATE_DATA", str(ROOT / "private_data")),
)
parser.add_argument("--tenant", default=None)
args = parser.parse_args()

assets = coarse_climate_assets(args.root, tenant_key=args.tenant)
if not assets:
    raise SystemExit("No resolved EXACT_SITE/PROBABLE_SITE private assets are available.")

years = required_years(args.year, args.baseline_start, args.baseline_end)
remote_files = sum(expected_days(y, y) for y in years)
plan = {
    "product": "CHIRPS v3 final RNL daily 0.05-degree COG",
    "asset_count": len(assets),
    "asset_signature": asset_signature(assets),
    "target_year": args.year,
    "baseline_start": args.baseline_start,
    "baseline_end": args.baseline_end,
    "years": years,
    "remote_cog_count": remote_files,
    "storage_mode": "SOURCE_SUBSET",
    "note": (
        "Official COGs are streamed and untransformed grid-cell rainfall values are "
        "saved locally as immutable yearly Parquet source-subset snapshots."
    ),
    "target_urls": year_urls(args.year),
}

outdir = Path(args.root).resolve() / "manifests" / "plans" / "chirps"
outdir.mkdir(parents=True, exist_ok=True)
path = outdir / f"chirps_plan_{args.year}_{asset_signature(assets)[:16]}.json"
path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

print(json.dumps({
    "asset_count": len(assets),
    "asset_signature": asset_signature(assets),
    "years_required": len(years),
    "remote_cog_count": remote_files,
    "plan_path": str(path),
}, indent=2))
