from __future__ import annotations
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable
import math
import numpy as np
import pandas as pd
import rasterio
from .common import IndicatorResult, require_coordinate

BASE_FINAL_RNL_COG = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/rnl/cogs"

def daily_cog_url(d: date) -> str:
    return f"{BASE_FINAL_RNL_COG}/{d.year}/chirps-v3.0.rnl.{d:%Y.%m.%d}.cog"

def daily_tif_url(d: date) -> str:
    return (
        "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/rnl/"
        f"{d.year}/chirps-v3.0.rnl.{d:%Y.%m.%d}.tif"
    )

def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)

def sample_daily_raster(path_or_url: str | Path, lat: float, lon: float):
    require_coordinate(lat, lon)
    with rasterio.open(path_or_url) as ds:
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
        val = float(arr[0])
        if not math.isfinite(val) or val < 0:
            return None
        return val

def summarize_daily_rainfall(daily: pd.DataFrame, target_year: int, baseline_start: int = 1991, baseline_end: int = 2020) -> list[IndicatorResult]:
    required = {"date", "rain_mm"}
    if not required.issubset(daily.columns):
        raise ValueError(f"daily rainfall requires columns {required}")
    x = daily.copy()
    x["date"] = pd.to_datetime(x["date"])
    x = x.dropna(subset=["rain_mm"])
    x["year"] = x["date"].dt.year
    baseline = x[x["year"].between(baseline_start, baseline_end)]
    target = x[x["year"] == target_year]
    if target.empty:
        raise ValueError("No target-year rainfall observations.")
    if baseline.empty:
        raise ValueError("No baseline rainfall observations.")
    p95 = float(np.quantile(baseline["rain_mm"].to_numpy(), 0.95))
    vals = target.sort_values("date")["rain_mm"].to_numpy(dtype=float)
    roll5 = pd.Series(vals).rolling(5, min_periods=5).sum()
    meta = dict(unit="days/year", value_class="CALCULATED", measurement_basis="CALCULATED_FROM_SATELLITE_GAUGE_BLEND", source_vintage="CHIRPS_V3_FINAL_RNL")
    return [
        IndicatorResult("rain_p95_days", float((vals > p95).sum()), **meta),
        IndicatorResult("rain_gt_50mm_days", float((vals > 50.0).sum()), **meta),
        IndicatorResult("max_1d_rain_mm", float(np.max(vals)), unit="mm", value_class="CALCULATED", measurement_basis="CALCULATED_FROM_SATELLITE_GAUGE_BLEND", source_vintage="CHIRPS_V3_FINAL_RNL"),
        IndicatorResult("max_5d_rain_mm", float(roll5.max()), unit="mm", value_class="CALCULATED", measurement_basis="CALCULATED_FROM_SATELLITE_GAUGE_BLEND", source_vintage="CHIRPS_V3_FINAL_RNL"),
    ]

def sample_points_from_cog(url: str, points: list[tuple[float, float]]) -> list[float | None]:
    out = []
    vsi_url = url if str(url).startswith("/vsicurl/") else f"/vsicurl/{url}"
    with rasterio.open(vsi_url) as ds:
        for arr in ds.sample([(lon, lat) for lat, lon in points], masked=True):
            try:
                if arr.mask[0]:
                    out.append(None)
                    continue
            except Exception:
                pass
            val = float(arr[0])
            out.append(None if (not math.isfinite(val) or val < 0) else val)
    return out
