from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from clr.gfm_local import (
    attach_jrc_event_relation,
    extract_gfm_event_source_subset,
    insert_event_relation_indicators,
    insert_gfm_indicators,
    summarize_gfm_event,
)
from clr.local_assets import accepted_assets
from clr.local_store import (
    finish_processing_run,
    parquet_partition_dir,
    register_parquet_dataset,
    start_processing_run,
)

parser=argparse.ArgumentParser(description="Extract GFM observed-flood evidence for an event window.")
parser.add_argument("--start",required=True,help="ISO date/time start")
parser.add_argument("--end",required=True,help="ISO date/time end")
parser.add_argument("--root",default=os.getenv("CLR_PRIVATE_DATA",str(ROOT/"private_data")))
parser.add_argument("--tenant",default=None)
parser.add_argument("--return-period",type=int,default=100)
args=parser.parse_args()

root=Path(args.root).resolve()
assets=accepted_assets(root,tenant_key=args.tenant)
if not assets:
    raise SystemExit("No EXACT_SITE + RESOLVED private assets are available.")

try:
    git_commit=subprocess.run(
        ["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,text=True,check=True
    ).stdout.strip()
except Exception:
    git_commit=None

run_id=start_processing_run(
    root,pipeline_name="gfm_observed_flood_event",pipeline_version="0.1.0",
    git_commit=git_commit,profile_name="event_validation",
    parameters={
        "start":args.start,"end":args.end,"tenant":args.tenant,
        "asset_count":len(assets),"jrc_return_period":args.return_period,
    },
)
try:
    source,observations=extract_gfm_event_source_subset(
        root,assets,args.start,args.end
    )
    summary=summarize_gfm_event(observations,assets=assets)
    summary=attach_jrc_event_relation(
        root,summary,return_period=args.return_period
    )
    count=insert_gfm_indicators(
        root,summary,source_artifact_id=source["source_artifact_id"],
        start=args.start,end=args.end,run_id=run_id,
    )
    relation_count=insert_event_relation_indicators(
        root,summary,gfm_source_artifact_id=source["source_artifact_id"],
        start=args.start,end=args.end,run_id=run_id,
        return_period=args.return_period,
    )

    outdir=parquet_partition_dir(
        root,layer="indicators",dataset="gfm_event_validation",
        partitions={"start":args.start[:10],"end":args.end[:10]},
    )
    outdir.mkdir(parents=True,exist_ok=True)
    path=outdir/f"summary-{run_id}.parquet"
    summary.to_parquet(path,index=False)
    register_parquet_dataset(
        root,dataset_name="gfm_event_validation_summary",layer="indicators",
        parquet_path=path,
        partition_spec={"start":args.start[:10],"end":args.end[:10]},
        row_count=len(summary),run_id=run_id,
    )
    finish_processing_run(root,run_id,status="SUCCESS")
    print(json.dumps({
        "run_id":run_id,"status":"SUCCESS","assets":len(assets),
        "gfm_source_artifact_id":source["source_artifact_id"],
        "source_rows":len(observations),
        "indicator_rows":count+relation_count,
        "summary_parquet":str(path),
        "warning":"GFM acquisition rate is not flood probability or annual flood frequency.",
    },indent=2))
except Exception as e:
    finish_processing_run(root,run_id,status="FAILED",error_summary=f"{type(e).__name__}: {e}")
    raise
