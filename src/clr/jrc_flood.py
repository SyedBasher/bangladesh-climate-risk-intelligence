from __future__ import annotations
import json
from pathlib import Path
from typing import Optional
import rasterio
from shapely.geometry import Point, shape
from .common import IndicatorResult, require_coordinate

JRC_VERSION="2.1.2"
BASE="https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/CEMS-GLOFAS/flood_hazard"

def load_tile_extents(path):
    with open(path,"r",encoding="utf-8") as f: obj=json.load(f)
    if obj.get("type")!="FeatureCollection": raise ValueError("Expected GeoJSON FeatureCollection.")
    return obj

def _tile_label(properties):
    for key in ("tile_id","tile","name","Name","ID","id","filename"):
        val=properties.get(key)
        if val not in (None,""): return str(val)
    raise ValueError("Tile extent feature has no recognized tile identifier property.")

def resolve_tile(tile_extents,lat,lon):
    require_coordinate(lat,lon); p=Point(lon,lat); hits=[]
    for feature in tile_extents["features"]:
        if shape(feature["geometry"]).covers(p): hits.append(_tile_label(feature.get("properties",{})))
    if len(hits)==1: return hits[0]
    if len(hits)==0: raise ValueError("Point is outside supplied JRC tile coverage.")
    raise ValueError(f"Ambiguous tile match: {hits}")

def raw_depth_url(return_period,filename):
    if return_period not in {10,20,50,75,100,200,500}: raise ValueError(f"Unsupported return period: {return_period}")
    return f"{BASE}/RP{return_period}/{filename}"

def _sample(path,lat,lon):
    require_coordinate(lat,lon)
    with rasterio.open(path) as ds:
        x,y=lon,lat
        if ds.crs and str(ds.crs).upper() not in ("EPSG:4326","OGC:CRS84"):
            from rasterio.warp import transform
            xs,ys=transform("EPSG:4326",ds.crs,[lon],[lat]); x,y=xs[0],ys[0]
        arr=list(ds.sample([(x,y)],masked=True))[0]
        try:
            if arr.mask[0]: return None
        except Exception: pass
        return float(arr[0])

def extract_depth(depth_path,lat,lon,return_period,permanent_water_path=None,spurious_depth_path=None):
    depth=_sample(depth_path,lat,lon)
    if depth is None:
        return IndicatorResult(f"flood_rp{return_period}_depth_m",None,"m","SOURCE","HYDROLOGICAL_HYDRODYNAMIC_MODEL",quality_flag="NO_VALUE",null_reason="SOURCE_NODATA",source_vintage=f"JRC_GLOFAS_FLOOD_HAZARD_{JRC_VERSION}")
    flags=[]
    if permanent_water_path and _sample(permanent_water_path,lat,lon) not in (None,0.0): flags.append("PERMANENT_WATER")
    if spurious_depth_path and _sample(spurious_depth_path,lat,lon) not in (None,0.0): flags.append("SPURIOUS_DEPTH_MASK")
    return IndicatorResult(f"flood_rp{return_period}_depth_m",depth,"m","SOURCE","HYDROLOGICAL_HYDRODYNAMIC_MODEL",quality_flag=";".join(flags) if flags else "OK",source_vintage=f"JRC_GLOFAS_FLOOD_HAZARD_{JRC_VERSION}")
