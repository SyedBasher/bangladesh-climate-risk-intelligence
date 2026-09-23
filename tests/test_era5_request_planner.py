import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from live_integration.adapters.era5_cds import daily_heat_request, hourly_humid_heat_month_request

PTS=[{"latitude":23.95,"longitude":90.38},{"latitude":24.17,"longitude":90.42}]

def test_daily_uses_official_daily_product_and_local_tz():
    p=daily_heat_request(PTS,2025,"daily_maximum")
    assert p.dataset=="derived-era5-land-daily-statistics"
    assert p.production_class=="PRODUCTION"
    assert p.request["time_zone"]=="utc+06:00"
    assert p.request["frequency"]=="1_hourly"

def test_hourly_uses_parent_production_archive():
    p=hourly_humid_heat_month_request(PTS,2025,2)
    assert p.dataset=="reanalysis-era5-land"
    assert p.production_class=="PRODUCTION"
    assert len(p.request["day"])==28
    assert "2m_dewpoint_temperature" in p.request["variable"]
