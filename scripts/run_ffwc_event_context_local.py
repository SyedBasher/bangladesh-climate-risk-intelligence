from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from clr.ffwc_local import ffwc_event_context,insert_ffwc_context_indicators
from clr.local_store import (
    finish_processing_run,parquet_partition_dir,register_parquet_dataset,start_processing_run
)

parser=argparse.ArgumentParser(description="Build nearest-FFWC-station context for an event window.")
parser.add_argument("--start",required=True)
parser.add_argument("--end",required=True)
parser.add_argument("--root",default=os.getenv("CLR_PRIVATE_DATA",str(ROOT/"private_data")))
args=parser.parse_args()

root=Path(args.root).resolve()
try:
    git_commit=subprocess.run(
        ["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,text=True,check=True
    ).stdout.strip()
except Exception:
    git_commit=None
run_id=start_processing_run(
    root,pipeline_name="ffwc_event_station_context",pipeline_version="0.1.0",
    git_commit=git_commit,profile_name="event_validation",
    parameters={"start":args.start,"end":args.end,"station_rank":1},
)
try:
    summary=ffwc_event_context(root,start=args.start,end=args.end,rank_order=1)
    if summary.empty:
        raise ValueError("No asset-station links are available; import/link FFWC stations first")
    n=insert_ffwc_context_indicators(
        root,summary,start=args.start,end=args.end,run_id=run_id
    )
    outdir=parquet_partition_dir(
        root,layer="indicators",dataset="ffwc_event_context",
        partitions={"start":args.start[:10],"end":args.end[:10]},
    )
    outdir.mkdir(parents=True,exist_ok=True)
    path=outdir/f"summary-{run_id}.parquet"
    summary.to_parquet(path,index=False)
    register_parquet_dataset(
        root,dataset_name="ffwc_event_context_summary",layer="indicators",
        parquet_path=path,
        partition_spec={"start":args.start[:10],"end":args.end[:10]},
        row_count=len(summary),run_id=run_id,
    )
    finish_processing_run(root,run_id,status="SUCCESS")
    print(json.dumps({
        "run_id":run_id,"status":"SUCCESS","assets":len(summary),
        "indicator_rows":n,"summary_parquet":str(path),
        "warning":"Nearest-station water level is contextual evidence, not interpolated site flood depth.",
    },indent=2))
except Exception as e:
    finish_processing_run(root,run_id,status="FAILED",error_summary=f"{type(e).__name__}: {e}")
    raise
