from __future__ import annotations

import calendar
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

from .common import IndicatorResult, require_coordinate

BASE_FINAL_RNL_COG = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/rnl/cogs"
BASELINE_START = 1991
BASELINE_END = 2020
WET_DAY_MM = 1.0
CUSTOM_HEAVY_DAY_MM = 50.0
MEASUREMENT_BASIS = "CALCULATED_FROM_SATELLITE_GAUGE_BLEND_WITH_REANALYSIS_DAILY_DISAGGREGATION"
SOURCE_VINTAGE = "CHIRPS_V3_FINAL_RNL"


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


def expected_days(start_year: int, end_year: int) -> int:
    return sum(366 if calendar.isleap(y) else 365 for y in range(start_year, end_year + 1))


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


def _max_spell(mask: pd.Series) -> int:
    if mask.empty:
        return 0
    groups = (mask != mask.shift()).cumsum()
    lengths = mask.groupby(groups).sum()
    return int(lengths.max()) if len(lengths) else 0


def precipitation_quantile_type8(values, q: float) -> float:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        raise ValueError("Cannot calculate a precipitation percentile from an empty sample")
    return float(np.quantile(arr, q, method="median_unbiased"))


def _validate_daily_coverage(frame: pd.DataFrame, start_year: int, end_year: int, label: str) -> None:
    dates = pd.to_datetime(frame["date"]).dt.normalize()
    in_period = frame[dates.dt.year.between(start_year, end_year)].copy()
    actual = pd.to_datetime(in_period["date"]).dt.date.nunique()
    expected = expected_days(start_year, end_year)
    if actual != expected:
        raise ValueError(
            f"Incomplete {label} coverage: {actual} unique days, expected {expected}"
        )
    if in_period["rain_mm"].isna().any():
        raise ValueError(f"{label} contains missing rainfall values")


def rainfall_extreme_metrics(
    daily: pd.DataFrame,
    target_year: int,
    *,
    baseline_start: int = BASELINE_START,
    baseline_end: int = BASELINE_END,
    require_complete: bool = True,
) -> dict[str, float]:
    required = {"date", "rain_mm"}
    if not required.issubset(daily.columns):
        raise ValueError(f"daily rainfall requires columns {required}")

    x = daily.copy()
    x["date"] = pd.to_datetime(x["date"])
    x["rain_mm"] = pd.to_numeric(x["rain_mm"], errors="coerce")
    x = x.sort_values("date").reset_index(drop=True)

    if require_complete:
        _validate_daily_coverage(x, baseline_start, baseline_end, "baseline")
        _validate_daily_coverage(x, target_year, target_year, "target year")

    baseline = x[x["date"].dt.year.between(baseline_start, baseline_end)]
    target = x[x["date"].dt.year == int(target_year)]
    if baseline.empty:
        raise ValueError("No baseline rainfall observations")
    if target.empty:
        raise ValueError("No target-year rainfall observations")
    if target["rain_mm"].isna().any():
        raise ValueError("Target year contains missing rainfall values")

    baseline_wet = baseline.loc[baseline["rain_mm"] >= WET_DAY_MM, "rain_mm"].dropna()
    if baseline_wet.empty:
        raise ValueError("Baseline contains no wet days (rainfall >= 1 mm)")

    p95 = precipitation_quantile_type8(baseline_wet.to_numpy(), 0.95)
    vals = target["rain_mm"].to_numpy(dtype=float)
    wet = vals >= WET_DAY_MM
    very_wet = vals > p95

    roll5 = pd.Series(vals).rolling(5, min_periods=5).sum()
    prcptot = float(vals[wet].sum())
    r95p = float(vals[very_wet].sum())

    return {
        "rx1day_mm": float(np.max(vals)),
        "rx5day_mm": float(roll5.max()),
        "r50mm_days": float((vals >= CUSTOM_HEAVY_DAY_MM).sum()),
        "prcptot_mm": prcptot,
        "r95p_mm": r95p,
        "r95p_share_pct": 0.0 if prcptot == 0 else float(100.0 * r95p / prcptot),
        "r95p_days": float(very_wet.sum()),
        "r95_threshold_mm": p95,
        "calendar_cdd_days": float(_max_spell(pd.Series(vals < WET_DAY_MM))),
        "calendar_cwd_days": float(_max_spell(pd.Series(vals >= WET_DAY_MM))),
    }


def summarize_daily_rainfall(
    daily: pd.DataFrame,
    target_year: int,
    baseline_start: int = BASELINE_START,
    baseline_end: int = BASELINE_END,
    *,
    require_complete: bool = True,
) -> list[IndicatorResult]:
    metrics = rainfall_extreme_metrics(
        daily,
        target_year,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        require_complete=require_complete,
    )

    units = {
        "rx1day_mm": "mm",
        "rx5day_mm": "mm",
        "r50mm_days": "days/year",
        "prcptot_mm": "mm/year",
        "r95p_mm": "mm/year",
        "r95p_share_pct": "percent",
        "r95p_days": "days/year",
        "r95_threshold_mm": "mm/day",
        "calendar_cdd_days": "days",
        "calendar_cwd_days": "days",
    }
    results = []
    for indicator_id, value in metrics.items():
        results.append(
            IndicatorResult(
                indicator_id,
                float(value),
                units[indicator_id],
                "CALCULATED",
                MEASUREMENT_BASIS,
                quality_flag="COMPLETE_BASELINE_AND_YEAR" if require_complete else "PARTIAL_TEST",
                method_version="CHIRPS_EXTREMES_0.1",
                source_vintage=SOURCE_VINTAGE,
            )
        )
    return results
