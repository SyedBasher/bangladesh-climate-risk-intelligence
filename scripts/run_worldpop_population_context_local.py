from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from clr.local_assets import coarse_climate_assets
from clr.local_store import finish_processing_run,start_processing_run
from clr.worldpop_local import (
    DATA_YEAR_DEFAULT,
    RADII_KM,
    build_population_context,
    insert_population_indicators,
    write_population_parquet,
)

parser=argparse.ArgumentParser(
    description="Attach WorldPop Global2 population context around private assets."
)
parser.add_argument("--year",type=int,default=DATA_YEAR_DEFAULT)
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
    root,pipeline_name="worldpop_population_context",
    pipeline_version="0.1.0",git_commit=git_commit,
    profile_name="exposure_built_environment",
    parameters={
        "year":args.year,"radii_km":args.radii_km,
        "asset_count":len(assets),"resolution":"100m",
    },
)
try:
    frame=build_population_context(
        root,assets,year=args.year,radii_km=tuple(args.radii_km)
    )
    path=write_population_parquet(
        root,frame,year=args.year,run_id=run_id
    )
    n=insert_population_indicators(root,frame,run_id=run_id)
    finish_processing_run(root,run_id,status="SUCCESS")
    print(json.dumps({
        "run_id":run_id,"status":"SUCCESS","assets":len(assets),
        "radii_km":args.radii_km,"rows":len(frame),
        "sqlite_indicator_rows":n,"parquet":str(path),
        "warning":(
            "WorldPop population around an asset is modeled residential population "
            "context; it is not factory workforce, employees or daytime population."
        ),
    },indent=2))
except Exception as e:
    finish_processing_run(
        root,run_id,status="FAILED",
        error_summary=f"{type(e).__name__}: {e}"
    )
    raise
