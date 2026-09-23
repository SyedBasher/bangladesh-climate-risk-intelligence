from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from clr.aqueduct_local import (
    build_aqueduct_context,insert_aqueduct_indicators,register_aqueduct_snapshot
)
from clr.local_assets import coarse_climate_assets
from clr.local_store import (
    finish_processing_run,parquet_partition_dir,register_parquet_dataset,start_processing_run
)

parser=argparse.ArgumentParser(description="Attach WRI Aqueduct 4.0 baseline water-stress context.")
parser.add_argument("--file",required=True,help="Official WRI GPKG/GeoJSON or ZIP")
parser.add_argument("--source-url",required=True)
parser.add_argument("--layer",default=None)
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
    root,pipeline_name="wri_aqueduct4_baseline_water_stress",
    pipeline_version="0.1.0",git_commit=git_commit,
    profile_name="water_stress_drought",
    parameters={
        "asset_count":len(assets),"source_url":args.source_url,"layer":args.layer,
    },
)
try:
    source=register_aqueduct_snapshot(
        root,args.file,source_url=args.source_url
    )
    frame=build_aqueduct_context(root,assets,source,layer=args.layer)
    n=insert_aqueduct_indicators(root,frame,run_id=run_id)

    outdir=parquet_partition_dir(
        root,layer="indicators",dataset="wri_aqueduct4_baseline_water_stress",
        partitions={"version":"4.0"},
    )
    outdir.mkdir(parents=True,exist_ok=True)
    path=outdir/f"context-{run_id}.parquet"
    frame.to_parquet(path,index=False)
    register_parquet_dataset(
        root,dataset_name="wri_aqueduct4_baseline_water_stress",
        layer="indicators",parquet_path=path,
        partition_spec={"version":"4.0"},row_count=len(frame),run_id=run_id,
    )
    finish_processing_run(root,run_id,status="SUCCESS")
    print(json.dumps({
        "run_id":run_id,"status":"SUCCESS","assets":len(frame),
        "matched":int((frame["match_status"]=="MATCHED").sum()),
        "sqlite_indicator_rows":n,"parquet":str(path),
        "source_artifact_id":source["source_artifact_id"],
        "warning":"WRI Aqueduct is structural basin context and a prioritization tool; it is not real-time site water availability.",
    },indent=2))
except Exception as e:
    finish_processing_run(root,run_id,status="FAILED",error_summary=f"{type(e).__name__}: {e}")
    raise
