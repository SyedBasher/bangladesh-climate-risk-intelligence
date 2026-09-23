from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from clr.local_assets import accepted_assets
from clr.local_store import finish_processing_run,start_processing_run
from clr.surface_water_local import (
    DEFAULT_SEARCH_RADIUS_KM,
    HIGH_OCCURRENCE_THRESHOLD_PCT,
    build_surface_water_context,
    ensure_required_tiles,
    insert_surface_water_indicators,
    write_surface_water_parquet,
)

parser=argparse.ArgumentParser(
    description="Attach JRC Global Surface Water v1.5 context to exact private assets."
)
parser.add_argument(
    "--occurrence-threshold-pct",type=float,
    default=HIGH_OCCURRENCE_THRESHOLD_PCT
)
parser.add_argument(
    "--search-radius-km",type=float,
    default=DEFAULT_SEARCH_RADIUS_KM
)
parser.add_argument(
    "--root",default=os.getenv("CLR_PRIVATE_DATA",str(ROOT/"private_data"))
)
parser.add_argument("--tenant",default=None)
args=parser.parse_args()

if not (0<args.occurrence_threshold_pct<=100):
    raise SystemExit("--occurrence-threshold-pct must be in (0,100]")
if args.search_radius_km<=0:
    raise SystemExit("--search-radius-km must be positive")

root=Path(args.root).resolve()
assets=accepted_assets(root,tenant_key=args.tenant)
if not assets:
    raise SystemExit("No EXACT_SITE + RESOLVED private assets are available.")

try:
    git_commit=subprocess.run(
        ["git","rev-parse","HEAD"],cwd=ROOT,
        capture_output=True,text=True,check=True
    ).stdout.strip()
except Exception:
    git_commit=None

run_id=start_processing_run(
    root,pipeline_name="jrc_gsw15_surface_water_context",
    pipeline_version="0.1.0",git_commit=git_commit,
    profile_name="surface_water_land_context",
    parameters={
        "asset_count":len(assets),
        "period":"1984-2024",
        "occurrence_threshold_pct":args.occurrence_threshold_pct,
        "search_radius_km":args.search_radius_km,
    },
)
try:
    records=ensure_required_tiles(
        root,assets,
        search_radius_km=args.search_radius_km,
    )
    frame=build_surface_water_context(
        root,assets,records,
        occurrence_threshold_pct=args.occurrence_threshold_pct,
        search_radius_km=args.search_radius_km,
    )
    path=write_surface_water_parquet(root,frame,run_id=run_id)
    n=insert_surface_water_indicators(root,frame,run_id=run_id)
    finish_processing_run(root,run_id,status="SUCCESS")
    print(json.dumps({
        "run_id":run_id,"status":"SUCCESS",
        "assets":len(assets),"tiles":len(records),
        "rows":len(frame),"sqlite_indicator_rows":n,
        "parquet":str(path),
        "warning":(
            "JRC occurrence and recurrence describe long-run open-water history. "
            "They are not flood probability or flood frequency. Distance is to "
            f"occurrence >= {args.occurrence_threshold_pct}% water within the "
            f"{args.search_radius_km} km search radius."
        ),
    },indent=2))
except Exception as e:
    finish_processing_run(
        root,run_id,status="FAILED",
        error_summary=f"{type(e).__name__}: {e}"
    )
    raise
