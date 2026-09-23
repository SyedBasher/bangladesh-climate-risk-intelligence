from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from clr.ibtracs_local import (
    DEFAULT_MAX_DISTANCE_KM,
    DEFAULT_START_YEAR,
    asset_storm_context,
    historical_asset_summary,
    insert_cyclone_indicators,
    read_ibtracs_csv,
    retrieve_ibtracs_ni,
    write_cyclone_parquet,
)
from clr.local_assets import coarse_climate_assets
from clr.local_store import finish_processing_run,start_processing_run

parser=argparse.ArgumentParser(
    description="Attach NOAA IBTrACS North Indian cyclone-track context to private assets."
)
parser.add_argument("--start-year",type=int,default=DEFAULT_START_YEAR)
parser.add_argument("--max-distance-km",type=float,default=DEFAULT_MAX_DISTANCE_KM)
parser.add_argument("--root",default=os.getenv("CLR_PRIVATE_DATA",str(ROOT/"private_data")))
parser.add_argument("--tenant",default=None)
parser.add_argument("--refresh-source",action="store_true")
args=parser.parse_args()

root=Path(args.root).resolve()
assets=coarse_climate_assets(root,tenant_key=args.tenant)
if not assets:
    raise SystemExit("No resolved EXACT_SITE/PROBABLE_SITE private assets are available.")

try:
    git_commit=subprocess.run(
        ["git","rev-parse","HEAD"],cwd=ROOT,
        capture_output=True,text=True,check=True
    ).stdout.strip()
except Exception:
    git_commit=None

run_id=start_processing_run(
    root,pipeline_name="ibtracs_cyclone_track_context",
    pipeline_version="0.1.0",git_commit=git_commit,
    profile_name="cyclone_coastal_context",
    parameters={
        "start_year":args.start_year,
        "max_distance_km":args.max_distance_km,
        "asset_count":len(assets),
        "subset":"NI",
        "release":"v04r01",
    },
)

try:
    source=retrieve_ibtracs_ni(
        root,force_refresh=args.refresh_source
    )
    tracks=read_ibtracs_csv(
        root/source["local_path"],start_year=args.start_year
    )
    nearest,timeline=asset_storm_context(
        tracks,assets,max_distance_km=args.max_distance_km
    )
    end_year=max(
        args.start_year,
        int(tracks["season"].astype(float).max()) if not tracks.empty else args.start_year,
    )
    summary=historical_asset_summary(
        nearest,assets,start_year=args.start_year,end_year=end_year
    )
    nearest_path,timeline_path,summary_path=write_cyclone_parquet(
        root,nearest,timeline,summary,start_year=args.start_year,run_id=run_id
    )
    n=insert_cyclone_indicators(
        root,nearest,summary,
        source_artifact_id=source["source_artifact_id"],
        start_year=args.start_year,end_year=end_year,run_id=run_id,
    )
    finish_processing_run(root,run_id,status="SUCCESS")
    print(json.dumps({
        "run_id":run_id,"status":"SUCCESS",
        "assets":len(assets),"track_rows":len(tracks),
        "asset_storm_pairs_within_radius":len(nearest),
        "timeline_rows_within_radius":len(timeline),
        "sqlite_indicator_rows":n,
        "nearest_parquet":str(nearest_path),
        "timeline_parquet":str(timeline_path),
        "summary_parquet":str(summary_path),
        "source_sha256":source["sha256"],
        "warning":(
            "IBTrACS track-point proximity and storm-center intensity are historical "
            "context, not site wind, storm surge, damage, return period or loss."
        ),
    },indent=2))
except Exception as e:
    finish_processing_run(
        root,run_id,status="FAILED",
        error_summary=f"{type(e).__name__}: {e}"
    )
    raise
