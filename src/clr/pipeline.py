from __future__ import annotations
import csv
from pathlib import Path
from .common import require_coordinate

FINE_RESOLUTION_ACCEPTED_GRADES = {"EXACT_SITE"}

def validate_asset(asset: dict, *, require_exact_site: bool=False) -> tuple[bool, str]:
    try:
        lat=float(asset["latitude"]); lon=float(asset["longitude"])
        require_coordinate(lat,lon)
    except Exception as e:
        return False, f"INVALID_COORDINATE:{e}"
    if asset.get("coordinate_source")=="SYNTHETIC_TEST_POINT":
        return True,"TEST_POINT"
    if asset.get("coordinate_status") not in {None,"","RESOLVED"}:
        return False,"COORDINATE_NOT_RESOLVED"
    if require_exact_site and asset.get("site_identity_grade") not in FINE_RESOLUTION_ACCEPTED_GRADES:
        return False,"SITE_IDENTITY_NOT_EXACT"
    return True,"OK"

def load_assets(path: str | Path):
    with open(path,newline="",encoding="utf-8") as f:
        return list(csv.DictReader(f))
