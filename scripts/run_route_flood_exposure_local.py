from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from clr.local_store import finish_processing_run,start_processing_run
from clr.logistics_local import latest_route_edges
from clr.route_flood_local import annotate_route_edges_with_jrc,publish_route_flood_exposure

parser=argparse.ArgumentParser(
    description="Overlay baseline private OSM routes with JRC river-flood exposure."
)
parser.add_argument("--root",default=os.getenv("CLR_PRIVATE_DATA",str(ROOT/"private_data")))
parser.add_argument("--return-period",type=int,default=100)
parser.add_argument("--spacing-m",type=float,default=100.0)
args=parser.parse_args()

root=Path(args.root).resolve()
try:
    git_commit=subprocess.run(
        ["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,text=True,check=True
    ).stdout.strip()
except Exception:
    git_commit=None

meta,path=latest_route_edges(root)
route_edges=pd.read_parquet(path)
run_id=start_processing_run(
    root,pipeline_name="osm_route_jrc_flood_exposure",
    pipeline_version="0.1.0",git_commit=git_commit,
    profile_name="logistics_flood_exposure",
    parameters={
        "return_period":args.return_period,"spacing_m":args.spacing_m,
        "baseline_route_dataset":meta["relative_path"],
    },
)
try:
    annotated,sources=annotate_route_edges_with_jrc(
        root,route_edges,return_period=args.return_period,spacing_m=args.spacing_m
    )
    summary,edge_path,bottleneck_path=publish_route_flood_exposure(
        root,annotated,sources,run_id=run_id
    )
    finish_processing_run(root,run_id,status="SUCCESS")
    print(json.dumps({
        "run_id":run_id,"status":"SUCCESS","routes":len(summary),
        "exposed_routes":int((summary["hazard_exposed_length_m"]>0).sum()),
        "complete_hazard_coverage_routes":int((summary["quality_flag"]=="OK").sum()),
        "edge_exposure_parquet":str(edge_path),
        "shared_bottleneck_parquet":str(bottleneck_path),
        "note":"Exposure only. No road closure or detour is inferred.",
    },indent=2))
except Exception as e:
    finish_processing_run(root,run_id,status="FAILED",error_summary=f"{type(e).__name__}: {e}")
    raise
