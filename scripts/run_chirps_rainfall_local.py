from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.chirps import BASELINE_END, BASELINE_START
from clr.chirps_local import (
    build_asset_metrics,
    insert_rainfall_indicators,
    write_indicator_parquet,
)
from clr.local_assets import coarse_climate_assets
from clr.local_store import finish_processing_run, start_processing_run

parser = argparse.ArgumentParser(
    description="Calculate CHIRPS rainfall-extreme indicators from local source-subset snapshots."
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

root = Path(args.root).resolve()
assets = coarse_climate_assets(root, tenant_key=args.tenant)
if not assets:
    raise SystemExit("No resolved EXACT_SITE/PROBABLE_SITE private assets are available.")

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
    pipeline_name="chirps_v3_rainfall_extremes",
    pipeline_version="0.1.0",
    git_commit=git_commit,
    profile_name="factory_core_production",
    parameters={
        "target_year": args.year,
        "baseline_start": args.baseline_start,
        "baseline_end": args.baseline_end,
        "asset_count": len(assets),
        "source_product": "CHIRPS_V3_FINAL_RNL",
    },
)

try:
    metrics, source_records = build_asset_metrics(
        root,
        assets,
        args.year,
        baseline_start=args.baseline_start,
        baseline_end=args.baseline_end,
    )
    parquet_path = write_indicator_parquet(
        root,
        metrics,
        target_year=args.year,
        run_id=run_id,
    )
    indicator_count = insert_rainfall_indicators(
        root,
        metrics,
        source_records,
        target_year=args.year,
        baseline_start=args.baseline_start,
        baseline_end=args.baseline_end,
        run_id=run_id,
    )
    finish_processing_run(root, run_id, status="SUCCESS")

    print(json.dumps({
        "run_id": run_id,
        "status": "SUCCESS",
        "target_year": args.year,
        "baseline": [args.baseline_start, args.baseline_end],
        "assets": len(assets),
        "indicator_rows": indicator_count,
        "indicator_parquet": str(parquet_path),
    }, indent=2))
except Exception as e:
    finish_processing_run(
        root,
        run_id,
        status="FAILED",
        error_summary=f"{type(e).__name__}: {e}",
    )
    raise
