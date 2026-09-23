from __future__ import annotations
import json
import re
from pathlib import Path

import rasterio
from shapely.geometry import Point, shape

from .common import IndicatorResult, require_coordinate

JRC_VERSION = "2.1.2"
BASE = "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/CEMS-GLOFAS/flood_hazard"
RETURN_PERIODS = {10, 20, 50, 75, 100, 200, 500}
TILE_PREFIX_RE = re.compile(r"(ID\d+_[NS]\d+_[EW]\d+)", re.IGNORECASE)


def load_tile_extents(path):
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    if obj.get("type") != "FeatureCollection":
        raise ValueError("Expected GeoJSON FeatureCollection.")
    return obj


def tile_prefix_from_properties(properties: dict) -> str:
    # Prefer a full tile prefix wherever JRC supplies it, independent of property key.
    for value in properties.values():
        if value in (None, ""):
            continue
        match = TILE_PREFIX_RE.search(str(value))
        if match:
            return match.group(1).upper()
    raise ValueError("Tile properties do not expose a complete JRC tile prefix.")


def _coord_token(value: float, positive: str, negative: str) -> str:
    rounded = round(float(value))
    if abs(float(value) - rounded) > 1e-6:
        raise ValueError("JRC fallback tile geometry is not aligned to integer degrees.")
    return f"{positive if rounded >= 0 else negative}{abs(int(rounded))}"


def tile_prefix_from_feature(feature: dict) -> str:
    properties = feature.get("properties", {})
    try:
        return tile_prefix_from_properties(properties)
    except ValueError:
        pass

    numeric_id = None
    for key in ("ID", "id", "Id", "tile_id"):
        value = properties.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text.upper().startswith("ID"):
            text = text[2:]
        if text.isdigit():
            numeric_id = int(text)
            break
    if numeric_id is None:
        raise ValueError("Tile feature lacks both a complete prefix and an explicit numeric ID.")

    geom = shape(feature["geometry"])
    minx, miny, maxx, maxy = geom.bounds
    # JRC filenames use the tile's north and west edges, e.g. N30_E80.
    north = _coord_token(maxy, "N", "S")
    west = _coord_token(minx, "E", "W")
    candidate = f"ID{numeric_id}_{north}_{west}"
    if not TILE_PREFIX_RE.fullmatch(candidate):
        raise ValueError(f"Could not construct a valid JRC tile prefix: {candidate}")
    return candidate


def resolve_tile(tile_extents, lat, lon):
    require_coordinate(lat, lon)
    p = Point(lon, lat)
    hits = []
    for feature in tile_extents["features"]:
        if shape(feature["geometry"]).covers(p):
            hits.append(tile_prefix_from_feature(feature))
    hits = sorted(set(hits))
    if len(hits) == 1:
        return hits[0]
    if len(hits) == 0:
        raise ValueError("Point is outside supplied JRC tile coverage.")
    raise ValueError(f"Ambiguous tile match: {hits}")


def raw_depth_filename(tile_prefix: str, return_period: int) -> str:
    if return_period not in RETURN_PERIODS:
        raise ValueError(f"Unsupported return period: {return_period}")
    if not TILE_PREFIX_RE.fullmatch(tile_prefix):
        raise ValueError(f"Invalid JRC tile prefix: {tile_prefix}")
    return f"{tile_prefix.upper()}_RP{return_period}_depth.tif"


def permanent_water_filename(tile_prefix: str) -> str:
    if not TILE_PREFIX_RE.fullmatch(tile_prefix):
        raise ValueError(f"Invalid JRC tile prefix: {tile_prefix}")
    return f"{tile_prefix.upper()}_permanent_water.tif"


def spurious_depth_filename(tile_prefix: str) -> str:
    if not TILE_PREFIX_RE.fullmatch(tile_prefix):
        raise ValueError(f"Invalid JRC tile prefix: {tile_prefix}")
    return f"{tile_prefix.upper()}_spurious_depth_areas.tif"


def raw_depth_url(return_period, filename):
    if return_period not in RETURN_PERIODS:
        raise ValueError(f"Unsupported return period: {return_period}")
    return f"{BASE}/RP{return_period}/{filename}"


def permanent_water_url(filename: str) -> str:
    return f"{BASE}/Permanent_WaterBodies/{filename}"


def spurious_depth_url(filename: str) -> str:
    return f"{BASE}/Spurious_Depths/{filename}"


def sample_raster_value(path, lat, lon):
    require_coordinate(lat, lon)
    with rasterio.open(path) as ds:
        x, y = lon, lat
        if ds.crs and str(ds.crs).upper() not in ("EPSG:4326", "OGC:CRS84"):
            from rasterio.warp import transform
            xs, ys = transform("EPSG:4326", ds.crs, [lon], [lat])
            x, y = xs[0], ys[0]
        arr = list(ds.sample([(x, y)], masked=True))[0]
        try:
            if arr.mask[0]:
                return None
        except Exception:
            pass
        return float(arr[0])


def extract_depth(
    depth_path,
    lat,
    lon,
    return_period,
    permanent_water_path=None,
    spurious_depth_path=None,
    *,
    require_masks=False,
):
    if require_masks and (permanent_water_path is None or spurious_depth_path is None):
        raise ValueError("Production flood extraction requires both JRC masks.")

    depth = sample_raster_value(depth_path, lat, lon)
    if depth is None:
        return IndicatorResult(
            f"flood_rp{return_period}_depth_m", None, "m", "SOURCE",
            "HYDROLOGICAL_HYDRODYNAMIC_MODEL",
            quality_flag="NO_VALUE", null_reason="SOURCE_NODATA",
            source_vintage=f"JRC_GLOFAS_FLOOD_HAZARD_{JRC_VERSION}",
        )

    flags = []
    if permanent_water_path and sample_raster_value(permanent_water_path, lat, lon) not in (None, 0.0):
        flags.append("PERMANENT_WATER")
    if spurious_depth_path and sample_raster_value(spurious_depth_path, lat, lon) not in (None, 0.0):
        flags.append("SPURIOUS_DEPTH_MASK")

    return IndicatorResult(
        f"flood_rp{return_period}_depth_m", depth, "m", "SOURCE",
        "HYDROLOGICAL_HYDRODYNAMIC_MODEL",
        quality_flag=";".join(flags) if flags else "OK",
        source_vintage=f"JRC_GLOFAS_FLOOD_HAZARD_{JRC_VERSION}",
    )
