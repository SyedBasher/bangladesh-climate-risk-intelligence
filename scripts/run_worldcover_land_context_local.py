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
from clr.worldcover_local import (
    RADII_M,
    build_land_context,
    ensure_required_tiles,
    insert_land_indicators,
    write_land_parquet,
)

parser=argparse.ArgumentParser(
    description="Attach ESA WorldCover 2021 v200 land context to exact private assets."
)
parser.add_argument(
    "--radii-m",type=float,nargs="+",default=list(RADII_M)
)
parser.add_argument(
    "--root",default=os.getenv("CLR_PRIVATE_DATA",str(ROOT/"private_data"))
)
parser.add_argument("--tenant",default=None)
args=parser.parse_args()

if any(x<=0 for x in args.radii_m):
    raise SystemExit("--radii-m values must be positive")

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
    root,pipeline_name="esa_worldcover2021_land_context",
    pipeline_version="0.1.0",git_commit=git_commit,
    profile_name="surface_water_land_context",
    parameters={
        "asset_count":len(assets),
        "year":2021,"version":"v200",
        "radii_m":args.radii_m,
    },
)
try:
    records=ensure_required_tiles(
        root,assets,max_radius_m=max(args.radii_m)
    )
    frame=build_land_context(
        root,assets,records,radii_m=tuple(args.radii_m)
    )
    path=write_land_parquet(root,frame,run_id=run_id)
    n=insert_land_indicators(root,frame,run_id=run_id)
    finish_processing_run(root,run_id,status="SUCCESS")
    print(json.dumps({
        "run_id":run_id,"status":"SUCCESS",
        "assets":len(assets),"tiles":len(records),
        "rows":len(frame),"sqlite_indicator_rows":n,
        "parquet":str(path),
        "warning":(
            "WorldCover is land-cover context. It does not establish zoning, "
            "land-use permission, ownership, factory floor area or property value."
        ),
    },indent=2))
except Exception as e:
    finish_processing_run(
        root,run_id,status="FAILED",
        error_summary=f"{type(e).__name__}: {e}"
    )
    raise
