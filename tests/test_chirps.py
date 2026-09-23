import pandas as pd
from clr.chirps import summarize_daily_rainfall, daily_tif_url
from datetime import date

def test_url_convention():
    assert daily_tif_url(date(2026,1,1)).endswith("2026/chirps-v3.0.rnl.2026.01.01.tif")

def test_rain_summary():
    baseline = pd.DataFrame({"date":[f"{y}-07-01" for y in range(1991,2021)],"rain_mm":[float(y-1990) for y in range(1991,2021)]})
    target = pd.DataFrame({"date":pd.date_range("2026-06-01", periods=5, freq="D"),"rain_mm":[10,20,60,5,80]})
    out = {x.indicator_id:x.value for x in summarize_daily_rainfall(pd.concat([baseline,target]), 2026)}
    assert out["rain_gt_50mm_days"] == 2
    assert out["max_1d_rain_mm"] == 80
    assert out["max_5d_rain_mm"] == 175
