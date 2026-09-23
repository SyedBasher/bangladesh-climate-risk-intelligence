from __future__ import annotations
from pathlib import Path
import numpy as np
import rasterio
from rasterio.windows import Window
from .common import IndicatorResult, require_coordinate

def sample_elevation(path: str | Path, lat: float, lon: float, source_vintage: str) -> IndicatorResult:
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
                return IndicatorResult("elevation_dsm_m", None, "m", "SOURCE", "STATIC_MODEL", quality_flag="NO_VALUE", null_reason="SOURCE_NODATA", source_vintage=source_vintage)
        except Exception:
            pass
        return IndicatorResult("elevation_dsm_m", float(arr[0]), "m", "SOURCE", "STATIC_MODEL", source_vintage=source_vintage)
