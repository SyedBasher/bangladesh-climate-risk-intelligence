from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from clr.local_store import finish_processing_run,start_processing_run
from clr.logistics_local import analyze_baseline_routes

parser=argparse.ArgumentParser(description="Calculate private baseline OSM logistics routes.")
parser.add_argument("--root",default=os.getenv("CLR_PRIVATE_DATA",str(ROOT/"private_data")))
parser.add_argument("--tenant",default=None)
parser.add_argument("--max-snap-m",type=float,default=500.0)
args=parser.parse_args()

root=Path(args.root).resolve()
try:
    git_commit=subprocess.run(
        ["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,text=True,check=True
    ).stdout.strip()
except Exception:
    git_commit=None

run_id=start_processing_run(
    root,pipeline_name="osm_baseline_logistics_routes",
    pipeline_version="0.1.0",git_commit=git_commit,
    profile_name="logistics_baseline",
    parameters={"tenant":args.tenant,"max_snap_m":args.max_snap_m},
)
try:
    summary,edges,qa=analyze_baseline_routes(
        root,run_id=run_id,tenant_key=args.tenant,max_snap_m=args.max_snap_m
    )
    finish_processing_run(root,run_id,status="SUCCESS")
    print(json.dumps({
        "run_id":run_id,"status":"SUCCESS",
        "route_summaries":len(summary),"route_edges":len(edges),**qa,
    },indent=2))
except Exception as e:
    finish_processing_run(root,run_id,status="FAILED",error_summary=f"{type(e).__name__}: {e}")
    raise
