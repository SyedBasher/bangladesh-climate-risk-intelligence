from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.local_assets import import_asset_csv

parser = argparse.ArgumentParser(
    description="Import a private asset CSV into the local SQLite catalog."
)
parser.add_argument("--csv", required=True, help="Private CSV path; never commit this file.")
parser.add_argument(
    "--root",
    default=os.getenv("CLR_PRIVATE_DATA", str(ROOT / "private_data")),
)
parser.add_argument("--tenant", default="INTERNAL")
args = parser.parse_args()

result = import_asset_csv(args.root, args.csv, tenant_key=args.tenant)
print(json.dumps(result, indent=2))
if result["rejected"]:
    raise SystemExit(2)
