from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.jrc_local import (
    DEFAULT_RETURN_PERIODS,
    artifact_plan,
    asset_tile_plan,
    ensure_tile_extents,
)
from clr.local_assets import accepted_assets

parser = argparse.ArgumentParser(
    description="Plan JRC flood artifacts for accepted private assets."
)
parser.add_argument(
    "--root",
    default=os.getenv("CLR_PRIVATE_DATA", str(ROOT / "private_data")),
)
parser.add_argument("--tenant", default=None)
parser.add_argument(
    "--return-periods",
    nargs="+",
    type=int,
    default=list(DEFAULT_RETURN_PERIODS),
)
args = parser.parse_args()

root = Path(args.root).resolve()
assets = accepted_assets(root, tenant_key=args.tenant)
if not assets:
    raise SystemExit("No EXACT_SITE + RESOLVED private assets are available.")

tile_record, tile_path = ensure_tile_extents(root)
asset_tiles = asset_tile_plan(assets, tile_path)
plan = artifact_plan(asset_tiles["tile_prefix"].unique(), args.return_periods)

outdir = root / "manifests" / "plans" / "jrc_flood"
outdir.mkdir(parents=True, exist_ok=True)

asset_path = outdir / "asset_tile_plan.json"
asset_path.write_text(
    json.dumps(asset_tiles.to_dict(orient="records"), indent=2) + "\n",
    encoding="utf-8",
)

plan_path = outdir / "artifact_plan.json"
plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

print(json.dumps({
    "accepted_assets": len(assets),
    "unique_tiles": int(asset_tiles["tile_prefix"].nunique()),
    "return_periods": args.return_periods,
    "artifacts_required": len(plan),
    "tile_extents_sha256": tile_record["sha256"],
    "asset_tile_plan": str(asset_path),
    "artifact_plan": str(plan_path),
}, indent=2))
