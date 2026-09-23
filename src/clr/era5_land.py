from __future__ import annotations
import pandas as pd
import numpy as np
from .common import IndicatorResult

DHAKA_TZ = "Asia/Dhaka"

def _to_celsius(series, units: str):
    u = units.upper()
    if u in ("K", "KELVIN"):
        return series.astype(float) - 273.15
    if u in ("C", "DEGC", "CELSIUS"):
        return series.astype(float)
    raise ValueError(f"Unsupported temperature unit: {units}")

def annual_heat_indicators(hourly: pd.DataFrame, year: int, temperature_column: str = "t2m", temperature_units: str = "K", timestamp_column: str = "time_utc") -> list[IndicatorResult]:
    if timestamp_column not in hourly or temperature_column not in hourly:
        raise ValueError("Hourly ERA5-Land input is missing required columns.")
    x = hourly[[timestamp_column, temperature_column]].dropna().copy()
    t = pd.to_datetime(x[timestamp_column], utc=True)
    x["local_time"] = t.dt.tz_convert(DHAKA_TZ)
    x["temp_c"] = _to_celsius(x[temperature_column], temperature_units)
    x = x[x["local_time"].dt.year == year]
    if x.empty:
        raise ValueError("No hourly values for target local year.")
    x["local_date"] = x["local_time"].dt.date
    daily = x.groupby("local_date")["temp_c"].agg(["max", "min"])
    common = dict(unit="days/year", value_class="CALCULATED", measurement_basis="CALCULATED_FROM_REANALYSIS", source_vintage="ERA5_LAND")
    return [
        IndicatorResult("days_tmax_gt_35c", float((daily["max"] > 35).sum()), **common),
        IndicatorResult("days_tmax_gt_38c", float((daily["max"] > 38).sum()), **common),
        IndicatorResult("warm_nights_gt_28c", float((daily["min"] > 28).sum()), **common),
    ]

def heat_trend(annual_metric: pd.DataFrame, value_column: str = "mean_temp_c") -> IndicatorResult:
    if not {"year", value_column}.issubset(annual_metric.columns):
        raise ValueError("Annual metric requires year and requested value column.")
    x = annual_metric[["year", value_column]].dropna()
    if len(x) < 10:
        raise ValueError("At least 10 annual observations required for a heat trend.")
    slope = np.polyfit(x["year"].astype(float), x[value_column].astype(float), 1)[0] * 10.0
    return IndicatorResult("heat_trend_c_decade", float(slope), "degC/decade", "CALCULATED", "CALCULATED_FROM_REANALYSIS", source_vintage="ERA5_LAND")
