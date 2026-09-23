from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.jrc_local import (
    DEFAULT_RETURN_PERIODS,
    artifact_plan,
    asset_tile_plan,
    ensure_tile_extents,
    extract_flood_rows,
    insert_flood_indicators,
    retrieve_plan,
    write_normalized_flood_parquet,
)
from clr.local_assets import accepted_assets
from clr.local_store import finish_processing_run, start_processing_run

parser = argparse.ArgumentParser(
    description="Run JRC RP flood-depth extraction for accepted private assets."
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

try:
    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
except Exception:
    git_commit = None

run_id = start_processing_run(
    root,
    pipeline_name="jrc_global_river_flood_hazard",
    pipeline_version="0.1.0",
    git_commit=git_commit,
    profile_name="factory_core_production",
    parameters={
        "tenant": args.tenant,
        "asset_count": len(assets),
        "return_periods": args.return_periods,
    },
)

try:
    tile_record, tile_path = ensure_tile_extents(root)
    asset_tiles = asset_tile_plan(assets, tile_path)
    plan = artifact_plan(asset_tiles["tile_prefix"].unique(), args.return_periods)
    records = retrieve_plan(root, plan)
    extracted = extract_flood_rows(
        root,
        asset_tiles,
        records,
        return_periods=args.return_periods,
    )
    parquet_path = write_normalized_flood_parquet(
        root,
        extracted,
        run_id=run_id,
    )
    indicator_count = insert_flood_indicators(
        root,
        extracted,
        run_id=run_id,
        tile_extents_source_artifact_id=tile_record["source_artifact_id"],
    )
    finish_processing_run(root, run_id, status="SUCCESS")

    print(json.dumps({
        "run_id": run_id,
        "status": "SUCCESS",
        "assets": len(assets),
        "unique_tiles": int(asset_tiles["tile_prefix"].nunique()),
        "return_periods": args.return_periods,
        "downloaded_or_registered_artifacts": len(records),
        "indicator_rows": indicator_count,
        "normalized_parquet": str(parquet_path),
    }, indent=2))
except Exception as e:
    finish_processing_run(
        root,
        run_id,
        status="FAILED",
        error_summary=f"{type(e).__name__}: {e}",
    )
    raise
