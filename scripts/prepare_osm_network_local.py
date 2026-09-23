from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from clr.local_store import finish_processing_run,start_processing_run
from clr.osm_local import ensure_pinned_pbf,parse_pbf_to_parquet

root=Path(os.getenv("CLR_PRIVATE_DATA",str(ROOT/"private_data"))).resolve()
try:
    git_commit=subprocess.run(
        ["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,text=True,check=True
    ).stdout.strip()
except Exception:
    git_commit=None

run_id=start_processing_run(
    root,pipeline_name="osm_bangladesh_road_network",
    pipeline_version="0.1.0",git_commit=git_commit,
    profile_name="logistics_network",
    parameters={"pbf":"bangladesh-260919.osm.pbf"},
)
try:
    record=ensure_pinned_pbf(root)
    edges,nodes,stats=parse_pbf_to_parquet(root,record,run_id=run_id)
    finish_processing_run(root,run_id,status="SUCCESS")
    print(json.dumps({
        "run_id":run_id,"status":"SUCCESS",
        "pbf_sha256":record["sha256"],
        "edges_parquet":str(edges),"nodes_parquet":str(nodes),
        **stats,
    },indent=2))
except Exception as e:
    finish_processing_run(root,run_id,status="FAILED",error_summary=f"{type(e).__name__}: {e}")
    raise
