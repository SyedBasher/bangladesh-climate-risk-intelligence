from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from clr.osm_local import import_route_endpoints

parser=argparse.ArgumentParser(description="Import private logistics endpoints into SQLite.")
parser.add_argument("--csv",required=True)
parser.add_argument("--root",default=os.getenv("CLR_PRIVATE_DATA",str(ROOT/"private_data")))
parser.add_argument("--tenant",default="INTERNAL")
args=parser.parse_args()

with open(args.csv,newline="",encoding="utf-8-sig") as f:
    rows=list(csv.DictReader(f))
result=import_route_endpoints(args.root,rows,tenant_key=args.tenant)
print(json.dumps(result,indent=2))
if result["rejected"]:
    raise SystemExit(2)
