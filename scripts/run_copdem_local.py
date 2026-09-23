from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.copdem_local import (
    RADIUS_M,
    cdse_access_token,
    download_product_package,
    extract_dem_raster,
    extract_dem_rows,
    insert_dem_indicators,
    product_plan,
    write_normalized_dem_parquet,
)
from clr.local_assets import accepted_assets
from clr.local_store import finish_processing_run, start_processing_run

parser = argparse.ArgumentParser(
    description="Run Copernicus DEM GLO-30 asset extraction locally."
)
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

asset_grids, products = product_plan(assets)
token = cdse_access_token()

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
    pipeline_name="copdem_glo30_dsm_context",
    pipeline_version="0.1.0",
    git_commit=git_commit,
    profile_name="factory_core_production",
    parameters={
        "tenant": args.tenant,
        "asset_count": len(assets),
        "grid_cells": sorted(asset_grids["grid_id"].unique().tolist()),
        "product_ids": [p["id"] for p in products],
        "context_radius_m": RADIUS_M,
    },
)

try:
    records = {}
    for product in products:
        package = download_product_package(
            root,
            product,
            access_token=token,
        )
        dem = extract_dem_raster(
            root,
            package,
            grid_id=product["grid_id"],
            product=product,
        )
        records[product["grid_id"]] = {
            "product": product,
            "package": package,
            "dem": dem,
        }

    extracted = extract_dem_rows(
        root,
        asset_grids,
        records,
        radius_m=RADIUS_M,
    )
    parquet_path = write_normalized_dem_parquet(
        root,
        extracted,
        run_id=run_id,
    )
    indicator_count = insert_dem_indicators(
        root,
        extracted,
        run_id=run_id,
        radius_m=RADIUS_M,
    )
    finish_processing_run(root, run_id, status="SUCCESS")

    print(json.dumps({
        "run_id": run_id,
        "status": "SUCCESS",
        "assets": len(assets),
        "unique_grid_cells": int(asset_grids["grid_id"].nunique()),
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
