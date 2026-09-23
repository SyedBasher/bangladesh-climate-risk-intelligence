from __future__ import annotations
from dataclasses import dataclass, asdict
from calendar import monthrange
from pathlib import Path
import json

DAILY_DATASET = "derived-era5-land-daily-statistics"
HOURLY_DATASET = "reanalysis-era5-land"

@dataclass(frozen=True)
class CDSRequestPlan:
    source_id: str
    dataset: str
    request: dict
    target: str
    production_class: str

    def to_dict(self):
        return asdict(self)

def _area_from_points(points, pad=0.1):
    lats=[float(p["latitude"]) for p in points]
    lons=[float(p["longitude"]) for p in points]
    return [min(90.0,max(lats)+pad),max(-180.0,min(lons)-pad),max(-90.0,min(lats)-pad),min(180.0,max(lons)+pad)]

def daily_heat_request(points, year:int, statistic:str, variable:str="2m_temperature"):
    if statistic not in {"daily_maximum","daily_minimum","daily_mean"}:
        raise ValueError("Unsupported daily statistic.")
    request={"variable":[variable],"year":str(year),"month":[f"{m:02d}" for m in range(1,13)],"day":[f"{d:02d}" for d in range(1,32)],"daily_statistic":statistic,"time_zone":"utc+06:00","frequency":"1_hourly","area":_area_from_points(points)}
    return CDSRequestPlan("ERA5L_DAILY",DAILY_DATASET,request,f"era5land_daily_{variable}_{statistic}_{year}.zip","PRODUCTION")

def hourly_humid_heat_month_request(points, year:int, month:int):
    request={"variable":["2m_temperature","2m_dewpoint_temperature","surface_pressure"],"year":str(year),"month":f"{month:02d}","day":[f"{d:02d}" for d in range(1,monthrange(year,month)[1]+1)],"time":[f"{h:02d}:00" for h in range(24)],"data_format":"netcdf","download_format":"unarchived","area":_area_from_points(points)}
    return CDSRequestPlan("ERA5L_HOURLY",HOURLY_DATASET,request,f"era5land_hourly_humidheat_{year}_{month:02d}.nc","PRODUCTION")

def write_plan(plans,path):
    Path(path).write_text(json.dumps([p.to_dict() for p in plans],indent=2),encoding="utf-8")
