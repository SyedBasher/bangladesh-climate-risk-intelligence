from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from clr.era5_soil_moisture_local import (
    BASELINE_END,BASELINE_START,
    build_soil_metrics,ensure_soil_sources,insert_soil_indicators,write_soil_parquet,
)
from clr.local_assets import coarse_climate_assets
from clr.local_store import finish_processing_run,start_processing_run

parser=argparse.ArgumentParser(description="Calculate ERA5-Land monthly soil-moisture anomalies.")
parser.add_argument("--year",type=int,default=2025)
parser.add_argument("--baseline-start",type=int,default=BASELINE_START)
parser.add_argument("--baseline-end",type=int,default=BASELINE_END)
parser.add_argument("--root",default=os.getenv("CLR_PRIVATE_DATA",str(ROOT/"private_data")))
parser.add_argument("--tenant",default=None)
args=parser.parse_args()

root=Path(args.root).resolve()
assets=coarse_climate_assets(root,tenant_key=args.tenant)
if not assets:
    raise SystemExit("No resolved EXACT_SITE/PROBABLE_SITE private assets are available.")

try:
    git_commit=subprocess.run(
        ["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,text=True,check=True
    ).stdout.strip()
except Exception:
    git_commit=None

run_id=start_processing_run(
    root,pipeline_name="era5_land_soil_moisture_anomaly",pipeline_version="0.1.0",
    git_commit=git_commit,profile_name="water_stress_drought",
    parameters={
        "target_year":args.year,"baseline_start":args.baseline_start,
        "baseline_end":args.baseline_end,"asset_count":len(assets),
        "layers":["0-7cm","7-28cm"],
    },
)
try:
    ensure_soil_sources(
        root,assets,args.year,
        baseline_start=args.baseline_start,baseline_end=args.baseline_end,
    )
    monthly,annual,records=build_soil_metrics(
        root,assets,args.year,
        baseline_start=args.baseline_start,baseline_end=args.baseline_end,
    )
    monthly_path,annual_path=write_soil_parquet(
        root,monthly,annual,target_year=args.year,run_id=run_id
    )
    n=insert_soil_indicators(
        root,monthly,annual,records,target_year=args.year,
        baseline_start=args.baseline_start,baseline_end=args.baseline_end,
        run_id=run_id,
    )
    finish_processing_run(root,run_id,status="SUCCESS")
    print(json.dumps({
        "run_id":run_id,"status":"SUCCESS","assets":len(assets),
        "monthly_indicator_rows":len(monthly),
        "annual_summary_rows":len(annual),"sqlite_indicator_rows":n,
        "monthly_parquet":str(monthly_path),"annual_parquet":str(annual_path),
        "warning":"ERA5-Land soil moisture is reanalysis grid-cell context, not an in-situ factory measurement.",
    },indent=2))
except Exception as e:
    finish_processing_run(root,run_id,status="FAILED",error_summary=f"{type(e).__name__}: {e}")
    raise
