import pandas as pd

from clr.era5_local import (
    DATASET,
    annual_heat_indicators_from_daily,
    daily_request,
    request_digest,
    request_plan,
)


ASSETS = [
    {
        "asset_location_id": "A1",
        "tenant_key": "INTERNAL",
        "external_system": "SYNTH",
        "external_id": "FACTORY_A",
        "latitude": 24.0,
        "longitude": 90.4,
    },
    {
        "asset_location_id": "A2",
        "tenant_key": "INTERNAL",
        "external_system": "SYNTH",
        "external_id": "FACTORY_B",
        "latitude": 23.8,
        "longitude": 90.2,
    },
]


def test_daily_request_uses_bangladesh_local_day_and_small_area():
    req = daily_request(ASSETS, 2025, "daily_maximum")
    assert req["time_zone"] == "utc+06:00"
    assert req["frequency"] == "1_hourly"
    assert req["variable"] == ["2m_temperature"]
    assert req["year"] == "2025"
    north, west, south, east = req["area"]
    assert north == 24.1
    assert south == 23.7
    assert west == 90.1
    assert east == 90.5


def test_request_plan_has_max_and_min_with_stable_digest():
    plan = request_plan(ASSETS, 2025)
    assert len(plan) == 2
    assert {x["statistic"] for x in plan} == {"daily_maximum", "daily_minimum"}
    assert all(x["dataset"] == DATASET for x in plan)
    assert request_digest(plan[0]["request"]) == plan[0]["request_sha256"]


def test_annual_heat_threshold_counts_are_transparent():
    dates = pd.date_range("2025-04-01", periods=5, freq="D").date.astype(str)
    daily_max = pd.DataFrame({
        "asset_location_id": ["A1"] * 5,
        "tenant_key": ["INTERNAL"] * 5,
        "external_id": ["FACTORY_A"] * 5,
        "date": dates,
        "temp_c": [34.0, 35.1, 38.1, 40.0, 30.0],
        "source_artifact_id": ["MAX1"] * 5,
    })
    daily_min = pd.DataFrame({
        "asset_location_id": ["A1"] * 5,
        "tenant_key": ["INTERNAL"] * 5,
        "external_id": ["FACTORY_A"] * 5,
        "date": dates,
        "temp_c": [27.0, 28.1, 29.0, 26.0, 30.0],
        "source_artifact_id": ["MIN1"] * 5,
    })
    out = annual_heat_indicators_from_daily(daily_max, daily_min, 2025)
    values = dict(zip(out["indicator_id"], out["value"]))
    assert values["days_tmax_gt_35c"] == 3
    assert values["days_tmax_gt_38c"] == 2
    assert values["warm_nights_gt_28c"] == 3
    assert "risk_score" not in out.columns
