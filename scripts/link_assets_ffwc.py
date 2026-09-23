from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from clr.ffwc_local import link_assets_to_stations

parser=argparse.ArgumentParser(description="Link private assets to nearest imported FFWC stations.")
parser.add_argument("--root",default=os.getenv("CLR_PRIVATE_DATA",str(ROOT/"private_data")))
parser.add_argument("--tenant",default=None)
parser.add_argument("--top-k",type=int,default=3)
args=parser.parse_args()

count=link_assets_to_stations(args.root,tenant_key=args.tenant,top_k=args.top_k)
print(json.dumps({"links_written":count,"top_k":args.top_k},indent=2))
