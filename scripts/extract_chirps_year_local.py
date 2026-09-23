from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.chirps_local import extract_year_source_subset
from clr.local_assets import coarse_climate_assets

parser = argparse.ArgumentParser(
    description="Stream one year of official CHIRPS COGs and save a private source-subset snapshot."
)
parser.add_argument("--year", type=int, required=True)
parser.add_argument(
    "--root",
    default=os.getenv("CLR_PRIVATE_DATA", str(ROOT / "private_data")),
)
parser.add_argument("--tenant", default=None)
args = parser.parse_args()

assets = coarse_climate_assets(args.root, tenant_key=args.tenant)
if not assets:
    raise SystemExit("No resolved EXACT_SITE/PROBABLE_SITE private assets are available.")

record, frame = extract_year_source_subset(args.root, assets, args.year)
print(json.dumps({
    "year": args.year,
    "assets": len(assets),
    "rows": len(frame),
    "source_artifact_id": record["source_artifact_id"],
    "sha256": record["sha256"],
    "local_path": record["local_path"],
}, indent=2))
