from __future__ import annotations
import pandas as pd

FINE_HAZARDS = {
    "flood_rp10_depth_m","flood_rp50_depth_m","flood_rp100_depth_m",
    "elevation_dsm_m","distance_to_river_m","gfm_flood_detection_rate"
}

def fine_hazard_allowed(asset: dict) -> bool:
    return asset.get("site_identity_grade") == "EXACT_SITE" and asset.get("coordinate_status") == "RESOLVED"

def attach_hazard(asset: dict, indicator_id: str, value, source_vintage: str|None,
                  quality_flag: str="OK") -> dict:
    if indicator_id in FINE_HAZARDS and not fine_hazard_allowed(asset):
        return {
            "external_id":asset["external_id"],"indicator_id":indicator_id,"value":None,
            "source_vintage":source_vintage,"quality_flag":"BLOCKED_GEOQUALITY",
            "null_reason":"Fine-resolution hazard requires EXACT_SITE + RESOLVED coordinate."
        }
    return {
        "external_id":asset["external_id"],"indicator_id":indicator_id,"value":value,
        "source_vintage":source_vintage,"quality_flag":quality_flag,"null_reason":None
    }

def scale_exposure(asset: dict, flood_depth_m=None, heat_days=None) -> dict:
    """Transparent exposure arithmetic only; no damage/downtime/productivity coefficients."""
    out={}
    workers=asset.get("worker_total")
    machines=asset.get("machine_count_external")
    capacity=asset.get("annual_capacity_external")
    if workers is not None and heat_days is not None:
        out["worker_heat_exposure_days"]=float(workers)*float(heat_days)
    if flood_depth_m is not None:
        inside=float(flood_depth_m) > 0
        if workers is not None:
            out["workers_at_modelled_flooded_site"]=float(workers) if inside else 0.0
        if machines is not None and not pd.isna(machines):
            out["machines_at_modelled_flooded_site"]=float(machines) if inside else 0.0
        if capacity is not None and not pd.isna(capacity):
            out["annual_capacity_at_modelled_flooded_site"]=float(capacity) if inside else 0.0
    return out

def missing_data_questions(asset: dict, hazards_present: set[str]) -> list[str]:
    sector=asset.get("sector_mapped","")
    q=[]
    if "HEAT" in hazards_present:
        q += [
            "What are operating hours and shift worker counts?",
            "What cooling/ventilation, roof treatment and drinking-water arrangements exist?",
            "Is backup power available for cooling/ventilation?"
        ]
    if "FLOOD" in hazards_present:
        q += [
            "What is ground-floor and critical-equipment elevation?",
            "Where are inventory and electrical systems located vertically?",
            "Which access route and alternative routes connect the site to the primary highway/port?"
        ]
    if sector in {"RMG_COMPOSITE","RMG_WOVEN"}:
        q.append("Does the site have wet processing/dyeing/washing, and what are its water source and daily water use?")
    if sector=="FOOTWEAR":
        q.append("Is leather tanning or other water-intensive leather processing performed on site, or is this an assembly/finishing facility?")
    return list(dict.fromkeys(q))
