import calendar

import pandas as pd

from clr.drought import annual_spi_summary,target_year_spi
from clr.drought_local import required_spi_years


def _synthetic_daily():
    rows=[]
    years=list(range(1990,2021))+[2024,2025]
    for year in years:
        for month in range(1,13):
            days=calendar.monthrange(year,month)[1]
            if year<=2020:
                monthly_total=40.0+month*4.0+(year-1990)*1.7
            elif year==2024:
                monthly_total=70.0+month*3.0
            else:
                monthly_total=8.0 if month<=4 else 70.0+month*3.0
            daily=monthly_total/days
            for day in range(1,days+1):
                rows.append({
                    "date":f"{year:04d}-{month:02d}-{day:02d}",
                    "rain_mm":daily,
                })
    return pd.DataFrame(rows)


def test_required_spi_years_use_only_baseline_and_target_leads():
    years=required_spi_years(2025,baseline_start=1991,baseline_end=2020)
    assert years[0]==1990
    assert years[-2:]==[2024,2025]
    assert 2021 not in years
    assert 2022 not in years
    assert 2023 not in years
    assert len(years)==33


def test_target_year_spi_accepts_gap_between_calibration_and_target():
    out=target_year_spi(
        _synthetic_daily(),2025,baseline_start=1991,baseline_end=2020
    )
    assert len(out)==24
    assert set(out["indicator_id"])=={"spi3","spi12"}
    jan_spi3=out[
        (out["indicator_id"]=="spi3") & (out["month"]==1)
    ].iloc[0]["value"]
    apr_spi3=out[
        (out["indicator_id"]=="spi3") & (out["month"]==4)
    ].iloc[0]["value"]
    assert jan_spi3 < 0
    assert apr_spi3 < 0
    assert out["quality_flag"].eq("OK").all()


def test_annual_spi_summary_is_transparent():
    monthly=pd.DataFrame({
        "indicator_id":["spi3"]*12+["spi12"]*12,
        "value":[-1.2,-0.4,0.1,0.2,0.4,0.6,0.2,-1.1,-0.8,0.0,0.3,0.1]
               +[-0.2]*12,
        "quality_flag":["OK"]*24,
    })
    summary=annual_spi_summary(monthly).set_index("indicator_id")
    assert summary.loc["spi3_min_year","value"]==-1.2
    assert summary.loc["spi3_months_le_minus1","value"]==2
    assert summary.loc["spi12_months_le_minus1","value"]==0
