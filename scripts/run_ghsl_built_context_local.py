from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from clr.ghsl_built_local import (
    RADII_KM,
    build_built_context,
    insert_built_indicators,
    register_tile_pairs,
    write_built_parquet,
)
from clr.local_assets import coarse_climate_assets
from clr.local_store import finish_processing_run,start_processing_run

parser=argparse.ArgumentParser(
    description="Attach GHSL 2020 total/non-residential built-up context."
)
parser.add_argument(
    "--tile-dir",required=True,
    help="Directory containing paired official GHSL TOTAL and NRES 2020 100m tile ZIPs."
)
parser.add_argument(
    "--radii-km",type=float,nargs="+",default=list(RADII_KM)
)
parser.add_argument(
    "--root",default=os.getenv("CLR_PRIVATE_DATA",str(ROOT/"private_data"))
)
parser.add_argument("--tenant",default=None)
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
    root,pipeline_name="ghsl_built_environment_context",
    pipeline_version="0.1.0",git_commit=git_commit,
    profile_name="exposure_built_environment",
    parameters={
        "epoch":2020,"resolution_m":100,
        "radii_km":args.radii_km,"asset_count":len(assets),
    },
)
try:
    bundles=register_tile_pairs(root,args.tile_dir)
    frame=build_built_context(
        root,assets,bundles,radii_km=tuple(args.radii_km)
    )
    path=write_built_parquet(root,frame,run_id=run_id)
    n=insert_built_indicators(
        root,frame,bundles,run_id=run_id
    )
    finish_processing_run(root,run_id,status="SUCCESS")
    print(json.dumps({
        "run_id":run_id,"status":"SUCCESS",
        "assets":len(assets),"tile_pairs":len(bundles),
        "radii_km":args.radii_km,"rows":len(frame),
        "sqlite_indicator_rows":n,"parquet":str(path),
        "warning":(
            "GHSL built-up and NRES surface are surrounding built-environment context; "
            "they are not property value, replacement cost or factory floor area."
        ),
    },indent=2))
except Exception as e:
    finish_processing_run(
        root,run_id,status="FAILED",
        error_summary=f"{type(e).__name__}: {e}"
    )
    raise
