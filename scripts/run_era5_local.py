from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.era5_local import (
    SOURCE_ID_MAX,
    SOURCE_ID_MIN,
    annual_heat_indicators_from_daily,
    daily_request,
    extract_daily_temperature_zip,
    insert_heat_indicators,
    retrieve_request_to_private_store,
    write_normalized_parquet,
)
from clr.local_assets import accepted_assets
from clr.local_store import (
    finish_processing_run,
    start_processing_run,
)

parser = argparse.ArgumentParser(
    description="Run one authoritative ERA5-Land daily heat ingestion year locally."
)
parser.add_argument("--year", required=True, type=int)
parser.add_argument(
    "--root",
    default=os.getenv("CLR_PRIVATE_DATA", str(ROOT / "private_data")),
)
parser.add_argument("--tenant", default=None)
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
    pipeline_name="era5_land_daily_heat",
    pipeline_version="0.1.0",
    git_commit=git_commit,
    profile_name="factory_heat_production",
    parameters={"year": args.year, "tenant": args.tenant, "asset_count": len(assets)},
)

try:
    max_request = daily_request(assets, args.year, "daily_maximum")
    min_request = daily_request(assets, args.year, "daily_minimum")

    max_artifact = retrieve_request_to_private_store(
        root,
        source_id=SOURCE_ID_MAX,
        year=args.year,
        statistic="daily_maximum",
        request=max_request,
    )
    min_artifact = retrieve_request_to_private_store(
        root,
        source_id=SOURCE_ID_MIN,
        year=args.year,
        statistic="daily_minimum",
        request=min_request,
    )

    max_zip = root / max_artifact["local_path"]
    min_zip = root / min_artifact["local_path"]

    daily_max = extract_daily_temperature_zip(
        max_zip,
        assets,
        statistic="daily_maximum",
        source_artifact_id=max_artifact["source_artifact_id"],
    )
    daily_min = extract_daily_temperature_zip(
        min_zip,
        assets,
        statistic="daily_minimum",
        source_artifact_id=min_artifact["source_artifact_id"],
    )

    max_parquet = write_normalized_parquet(
        root, daily_max, year=args.year, statistic="daily_maximum", run_id=run_id
    )
    min_parquet = write_normalized_parquet(
        root, daily_min, year=args.year, statistic="daily_minimum", run_id=run_id
    )

    indicators = annual_heat_indicators_from_daily(daily_max, daily_min, args.year)
    indicator_count = insert_heat_indicators(root, indicators, run_id)
    finish_processing_run(root, run_id, status="SUCCESS")

    print(json.dumps({
        "run_id": run_id,
        "status": "SUCCESS",
        "year": args.year,
        "assets": len(assets),
        "indicator_rows": indicator_count,
        "max_artifact_sha256": max_artifact["sha256"],
        "min_artifact_sha256": min_artifact["sha256"],
        "daily_max_parquet": str(max_parquet),
        "daily_min_parquet": str(min_parquet),
    }, indent=2))
except Exception as e:
    finish_processing_run(root, run_id, status="FAILED", error_summary=f"{type(e).__name__}: {e}")
    raise
