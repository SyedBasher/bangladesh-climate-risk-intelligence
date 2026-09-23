from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.chirps import BASELINE_END, BASELINE_START
from clr.chirps_local import extract_year_source_subset
from clr.local_assets import coarse_climate_assets

parser = argparse.ArgumentParser(
    description="Build CHIRPS percentile baseline as yearly private source-subset snapshots."
)
parser.add_argument("--start", type=int, default=BASELINE_START)
parser.add_argument("--end", type=int, default=BASELINE_END)
parser.add_argument(
    "--root",
    default=os.getenv("CLR_PRIVATE_DATA", str(ROOT / "private_data")),
)
parser.add_argument("--tenant", default=None)
args = parser.parse_args()

if args.end < args.start:
    raise SystemExit("--end must be >= --start")

assets = coarse_climate_assets(args.root, tenant_key=args.tenant)
if not assets:
    raise SystemExit("No resolved EXACT_SITE/PROBABLE_SITE private assets are available.")

completed = []
for year in range(args.start, args.end + 1):
    record, frame = extract_year_source_subset(args.root, assets, year)
    item = {
        "year": year,
        "rows": len(frame),
        "source_artifact_id": record["source_artifact_id"],
        "sha256": record["sha256"],
    }
    completed.append(item)
    print(json.dumps(item))

print(json.dumps({
    "status": "COMPLETE",
    "start": args.start,
    "end": args.end,
    "years": len(completed),
    "assets": len(assets),
}, indent=2))
