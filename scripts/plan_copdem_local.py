from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.copdem_local import product_plan
from clr.local_assets import accepted_assets

parser = argparse.ArgumentParser(
    description="Plan Copernicus DEM GLO-30 DGED tiles for accepted private assets."
)
parser.add_argument(
    "--root",
    default=os.getenv("CLR_PRIVATE_DATA", str(ROOT / "private_data")),
)
parser.add_argument("--tenant", default=None)
args = parser.parse_args()

assets = accepted_assets(args.root, tenant_key=args.tenant)
if not assets:
    raise SystemExit("No EXACT_SITE + RESOLVED private assets are available.")

asset_grids, products = product_plan(assets)

outdir = Path(args.root).resolve() / "manifests" / "plans" / "copdem"
outdir.mkdir(parents=True, exist_ok=True)

asset_path = outdir / "asset_grid_plan.json"
asset_path.write_text(
    json.dumps(asset_grids.to_dict(orient="records"), indent=2) + "\n",
    encoding="utf-8",
)
product_path = outdir / "product_plan.json"
product_path.write_text(json.dumps(products, indent=2) + "\n", encoding="utf-8")

print(json.dumps({
    "accepted_assets": len(assets),
    "unique_grid_cells": int(asset_grids["grid_id"].nunique()),
    "products": len(products),
    "asset_grid_plan": str(asset_path),
    "product_plan": str(product_path),
    "download_auth_required": True,
}, indent=2))
