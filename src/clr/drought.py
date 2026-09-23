from __future__ import annotations

import calendar
import math

import numpy as np
import pandas as pd
from scipy.stats import gamma as gamma_dist
from scipy.stats import norm


BASELINE_START = 1991
BASELINE_END = 2020
SPI_SCALES = (3, 12)
MIN_POSITIVE_CALIBRATION_VALUES = 10
MEASUREMENT_BASIS = "CALCULATED_FROM_SATELLITE_GAUGE_PRECIPITATION"


def daily_to_monthly_precip(
    daily: pd.DataFrame,
    *,
    require_complete_months: bool = True,
) -> pd.DataFrame:
    required={"date","rain_mm"}
    if not required.issubset(daily.columns):
        raise ValueError(f"Daily rainfall requires columns {sorted(required)}")

    x=daily.copy()
    x["date"]=pd.to_datetime(x["date"])
    x["rain_mm"]=pd.to_numeric(x["rain_mm"],errors="coerce")
    if x["date"].duplicated().any():
        raise ValueError("Duplicate rainfall dates are not allowed")
    if x["rain_mm"].isna().any():
        raise ValueError("Rainfall contains missing values")
    if (x["rain_mm"]<0).any():
        raise ValueError("Rainfall cannot be negative")

    x=x.sort_values("date").reset_index(drop=True)
    x["period"]=x["date"].dt.to_period("M")

    if require_complete_months:
        for period,g in x.groupby("period"):
            expected=calendar.monthrange(period.year,period.month)[1]
            unique=g["date"].dt.date.nunique()
            if unique!=expected:
                raise ValueError(
                    f"Incomplete rainfall month {period}: {unique} days, expected {expected}"
                )

    monthly=(
        x.groupby("period",as_index=False)["rain_mm"]
        .sum()
        .rename(columns={"rain_mm":"precip_mm"})
    )
    monthly["year"]=monthly["period"].dt.year.astype(int)
    monthly["month"]=monthly["period"].dt.month.astype(int)
    return monthly[["period","year","month","precip_mm"]]


def _ensure_contiguous_months(monthly: pd.DataFrame) -> pd.DataFrame:
    x=monthly.copy().sort_values("period").reset_index(drop=True)
    if x.empty:
        raise ValueError("Monthly precipitation is empty")
    expected=pd.period_range(x["period"].min(),x["period"].max(),freq="M")
    if len(expected)!=len(x) or list(expected)!=list(x["period"]):
        raise ValueError("Monthly precipitation has missing or duplicate months")
    return x


def spi_gamma_monthly(
    monthly: pd.DataFrame,
    *,
    scale: int,
    baseline_start: int = BASELINE_START,
    baseline_end: int = BASELINE_END,
) -> pd.DataFrame:
    if scale not in SPI_SCALES:
        raise ValueError(f"Unsupported SPI scale: {scale}")
    if baseline_end < baseline_start:
        raise ValueError("baseline_end must be >= baseline_start")

    x=_ensure_contiguous_months(monthly)
    x["accum_precip_mm"]=x["precip_mm"].rolling(scale,min_periods=scale).sum()
    x["spi"]=np.nan
    x["quality_flag"]="NOT_CALCULATED"

    expected_baseline_years=baseline_end-baseline_start+1

    for month in range(1,13):
        cal=x[
            x["year"].between(baseline_start,baseline_end)
            & (x["month"]==month)
        ]["accum_precip_mm"].dropna()

        if len(cal)!=expected_baseline_years:
            flag=f"INCOMPLETE_BASELINE_{len(cal)}_OF_{expected_baseline_years}"
            mask=x["month"]==month
            x.loc[mask,"quality_flag"]=flag
            continue

        values=cal.to_numpy(dtype=float)
        positive=values[values>0]
        q_zero=float((values==0).sum()/len(values))

        if len(positive)<MIN_POSITIVE_CALIBRATION_VALUES:
            mask=x["month"]==month
            x.loc[mask,"quality_flag"]="INSUFFICIENT_POSITIVE_BASELINE"
            continue
        if np.allclose(positive,positive[0]):
            mask=x["month"]==month
            x.loc[mask,"quality_flag"]="ZERO_VARIANCE_BASELINE"
            continue

        try:
            shape,loc,scale_param=gamma_dist.fit(positive,floc=0)
        except Exception:
            mask=x["month"]==month
            x.loc[mask,"quality_flag"]="GAMMA_FIT_FAILED"
            continue

        mask=(x["month"]==month) & x["accum_precip_mm"].notna()
        for idx,val in x.loc[mask,"accum_precip_mm"].items():
            value=float(val)
            if value<=0:
                probability=q_zero
            else:
                probability=q_zero+(1.0-q_zero)*float(
                    gamma_dist.cdf(value,shape,loc=loc,scale=scale_param)
                )
            probability=min(max(probability,1e-10),1-1e-10)
            x.at[idx,"spi"]=float(norm.ppf(probability))
            x.at[idx,"quality_flag"]="OK"

    x["scale_months"]=int(scale)
    return x[
        ["period","year","month","precip_mm","accum_precip_mm","scale_months","spi","quality_flag"]
    ]


def target_year_spi(
    daily: pd.DataFrame,
    target_year: int,
    *,
    baseline_start: int = BASELINE_START,
    baseline_end: int = BASELINE_END,
) -> pd.DataFrame:
    monthly=daily_to_monthly_precip(daily,require_complete_months=True)
    frames=[]
    for scale in SPI_SCALES:
        frame=spi_gamma_monthly(
            monthly,scale=scale,
            baseline_start=baseline_start,baseline_end=baseline_end,
        )
        frames.append(frame[frame["year"]==int(target_year)].copy())
    out=pd.concat(frames,ignore_index=True)
    if len(out)!=24:
        raise ValueError(
            f"Target year SPI requires 24 monthly scale observations; found {len(out)}"
        )
    out["indicator_id"]=out["scale_months"].map({3:"spi3",12:"spi12"})
    out["value"]=out["spi"]
    out["unit"]="standardized_index"
    out["value_class"]="CALCULATED"
    out["measurement_basis"]=MEASUREMENT_BASIS
    out["method_version"]="CHIRPS_SPI_GAMMA_0.1"
    return out


def annual_spi_summary(monthly_spi: pd.DataFrame) -> pd.DataFrame:
    required={"indicator_id","value","quality_flag"}
    if not required.issubset(monthly_spi.columns):
        raise ValueError("Monthly SPI frame is missing required columns")
    rows=[]
    for indicator_id,g in monthly_spi.groupby("indicator_id"):
        valid=g[(g["quality_flag"]=="OK") & g["value"].notna()]
        if len(valid)!=12:
            rows.append({
                "indicator_id":f"{indicator_id}_min_year",
                "value":None,
                "unit":"standardized_index",
                "quality_flag":"INCOMPLETE_MONTHLY_SPI",
            })
            rows.append({
                "indicator_id":f"{indicator_id}_months_le_minus1",
                "value":None,
                "unit":"months/year",
                "quality_flag":"INCOMPLETE_MONTHLY_SPI",
            })
            continue
        rows.append({
            "indicator_id":f"{indicator_id}_min_year",
            "value":float(valid["value"].min()),
            "unit":"standardized_index",
            "quality_flag":"OK",
        })
        rows.append({
            "indicator_id":f"{indicator_id}_months_le_minus1",
            "value":float((valid["value"]<=-1.0).sum()),
            "unit":"months/year",
            "quality_flag":"OK",
        })
    return pd.DataFrame(rows)
