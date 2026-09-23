import pandas as pd

from clr.era5_soil_moisture_local import (
    monthly_request,monthly_soil_anomalies,required_soil_years
)


def _monthly_frame():
    rows=[]
    for year in list(range(1991,2021))+[2025]:
        for month in range(1,13):
            if year<=2020:
                offset=(year-1991)*0.001
                l1=0.20+month*0.002+offset
                l2=0.25+month*0.0015+offset*0.8
            else:
                l1=0.20+month*0.002+0.0145
                l2=0.25+month*0.0015+0.0145*0.8
            rows.append({
                "asset_location_id":"A","tenant_key":"INTERNAL","external_id":"A",
                "date":f"{year:04d}-{month:02d}","swvl1":l1,"swvl2":l2,
                "source_artifact_id":f"SRC-{year}",
            })
    return pd.DataFrame(rows)


def test_soil_request_uses_official_monthly_dataset_variables():
    assets=[{"latitude":24.0,"longitude":90.4}]
    req=monthly_request(assets,2025)
    assert req["product_type"]==["monthly_averaged_reanalysis"]
    assert set(req["variable"])=={
        "volumetric_soil_water_layer_1",
        "volumetric_soil_water_layer_2",
    }
    assert req["data_format"]=="netcdf"
    assert req["download_format"]=="unarchived"


def test_required_soil_years_do_not_require_gap_years():
    years=required_soil_years(2025,baseline_start=1991,baseline_end=2020)
    assert years[:2]==[1991,1992]
    assert years[-1]==2025
    assert 2021 not in years
    assert len(years)==31


def test_calendar_month_soil_anomaly_is_zero_at_baseline_mean():
    out=monthly_soil_anomalies(
        _monthly_frame(),2025,baseline_start=1991,baseline_end=2020
    )
    assert len(out)==24
    assert out["quality_flag"].eq("OK").all()
    assert out["value"].abs().max() < 1e-10
    assert set(out["indicator_id"])=={
        "soil_moisture_l1_anomaly_z",
        "soil_moisture_l2_anomaly_z",
    }
