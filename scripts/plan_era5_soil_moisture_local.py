from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from clr.era5_soil_moisture_local import (
    BASELINE_END,BASELINE_START,monthly_request,request_digest,required_soil_years
)
from clr.local_assets import coarse_climate_assets

parser=argparse.ArgumentParser(description="Plan ERA5-Land monthly soil-moisture CDS requests.")
parser.add_argument("--year",type=int,default=2025)
parser.add_argument("--baseline-start",type=int,default=BASELINE_START)
parser.add_argument("--baseline-end",type=int,default=BASELINE_END)
parser.add_argument("--root",default=os.getenv("CLR_PRIVATE_DATA",str(ROOT/"private_data")))
parser.add_argument("--tenant",default=None)
args=parser.parse_args()

assets=coarse_climate_assets(args.root,tenant_key=args.tenant)
if not assets:
    raise SystemExit("No resolved EXACT_SITE/PROBABLE_SITE private assets are available.")

plans=[]
for year in required_soil_years(
    args.year,baseline_start=args.baseline_start,baseline_end=args.baseline_end
):
    req=monthly_request(assets,year)
    plans.append({
        "year":year,"request_sha256":request_digest(req),"request":req
    })

outdir=Path(args.root).resolve()/"manifests"/"plans"/"era5_soil_moisture"
outdir.mkdir(parents=True,exist_ok=True)
path=outdir/f"soil_moisture_plan_{args.year}.json"
path.write_text(json.dumps(plans,indent=2)+"\n",encoding="utf-8")
print(json.dumps({
    "assets":len(assets),"requests":len(plans),
    "baseline":[args.baseline_start,args.baseline_end],
    "target_year":args.year,"plan_path":str(path),
},indent=2))
