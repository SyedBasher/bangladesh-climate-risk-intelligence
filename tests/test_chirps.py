from datetime import date

import numpy as np
import pandas as pd
import pytest

from clr.chirps import (
    daily_cog_url,
    daily_tif_url,
    precipitation_quantile_type8,
    summarize_daily_rainfall,
)


def test_url_convention():
    assert daily_tif_url(date(2026,1,1)).endswith(
        "2026/chirps-v3.0.rnl.2026.01.01.tif"
    )
    assert daily_cog_url(date(2025,1,1)).endswith(
        "cogs/2025/chirps-v3.0.rnl.2025.01.01.cog"
    )


def test_precipitation_percentile_uses_type8():
    values = np.array([1, 2, 3, 4, 5, 10, 20], dtype=float)
    expected = float(np.quantile(values, 0.95, method="median_unbiased"))
    assert precipitation_quantile_type8(values, 0.95) == expected


def test_rain_summary_partial_test_mode():
    baseline = pd.DataFrame({
        "date": pd.date_range("1991-01-01", periods=10, freq="D"),
        "rain_mm": [0,1,2,3,4,5,6,7,8,9],
    })
    target = pd.DataFrame({
        "date": pd.date_range("2025-06-01", periods=5, freq="D"),
        "rain_mm": [10,20,60,5,80],
    })
    out = {
        x.indicator_id:x.value
        for x in summarize_daily_rainfall(
            pd.concat([baseline,target], ignore_index=True),
            2025,
            require_complete=False,
        )
    }
    assert out["r50mm_days"] == 2
    assert out["rx1day_mm"] == 80
    assert out["rx5day_mm"] == 175
    assert out["prcptot_mm"] == 175
    assert out["r95p_days"] >= 1
    assert "r95_threshold_mm" in out


def test_partial_year_is_blocked_in_production_mode():
    baseline = pd.DataFrame({
        "date": pd.date_range("1991-01-01", periods=10, freq="D"),
        "rain_mm": [1.0] * 10,
    })
    target = pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=10, freq="D"),
        "rain_mm": [2.0] * 10,
    })
    with pytest.raises(ValueError, match="Incomplete baseline coverage"):
        summarize_daily_rainfall(
            pd.concat([baseline,target], ignore_index=True),
            2025,
        )
