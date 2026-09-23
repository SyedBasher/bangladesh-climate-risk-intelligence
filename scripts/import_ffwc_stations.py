from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from clr.ffwc_local import import_station_snapshot

parser=argparse.ArgumentParser(description="Import an official FFWC station CSV snapshot.")
parser.add_argument("--csv",required=True)
parser.add_argument("--source-url",required=True)
parser.add_argument("--root",default=os.getenv("CLR_PRIVATE_DATA",str(ROOT/"private_data")))
args=parser.parse_args()

result=import_station_snapshot(args.root,args.csv,source_url=args.source_url)
print(json.dumps({
    "rows":result["rows"],
    "source_artifact_id":result["source"]["source_artifact_id"],
    "sha256":result["source"]["sha256"],
},indent=2))
