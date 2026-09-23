import pandas as pd
from clr.era5_land import annual_heat_indicators

def test_local_day_heat_counts():
    t = pd.date_range("2026-05-01 00:00", periods=48, freq="h", tz="UTC")
    vals_c = [30.0]*48
    vals_c[6] = 36.0
    vals_c[30] = 39.0
    df = pd.DataFrame({"time_utc":t, "t2m":[v+273.15 for v in vals_c]})
    out = {x.indicator_id:x.value for x in annual_heat_indicators(df, 2026)}
    assert out["days_tmax_gt_35c"] >= 2
    assert out["days_tmax_gt_38c"] >= 1
