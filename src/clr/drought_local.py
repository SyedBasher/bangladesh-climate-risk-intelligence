from __future__ import annotations

from pathlib import Path

import pandas as pd

from .chirps import BASELINE_END,BASELINE_START
from .chirps_local import extract_year_source_subset,load_year_source_subset
from .drought import annual_spi_summary,target_year_spi
from .local_store import (
    connect_catalog,
    parquet_partition_dir,
    register_parquet_dataset,
    utc_now,
)


def required_spi_years(
    target_year:int,
    *,
    baseline_start:int=BASELINE_START,
    baseline_end:int=BASELINE_END,
)->list[int]:
    years=set(range(int(baseline_start)-1,int(baseline_end)+1))
    years.update({int(target_year)-1,int(target_year)})
    return sorted(years)


def ensure_spi_source_years(
    root:str|Path,
    assets:list[dict],
    target_year:int,
    *,
    baseline_start:int=BASELINE_START,
    baseline_end:int=BASELINE_END,
)->dict[int,dict]:
    records={}
    for year in required_spi_years(
        target_year,baseline_start=baseline_start,baseline_end=baseline_end
    ):
        record,_=extract_year_source_subset(root,assets,year)
        records[year]=record
    return records


def build_spi_metrics(
    root:str|Path,
    assets:list[dict],
    target_year:int,
    *,
    baseline_start:int=BASELINE_START,
    baseline_end:int=BASELINE_END,
)->tuple[pd.DataFrame,pd.DataFrame,dict[int,dict]]:
    records={}
    frames=[]
    for year in required_spi_years(
        target_year,baseline_start=baseline_start,baseline_end=baseline_end
    ):
        record,frame=load_year_source_subset(root,assets,year)
        records[year]=record
        frames.append(frame)
    daily=pd.concat(frames,ignore_index=True)

    monthly_rows=[]
    annual_rows=[]
    for asset in assets:
        x=daily[daily["asset_location_id"]==asset["asset_location_id"]][
            ["date","rain_mm"]
        ].copy()
        monthly=target_year_spi(
            x,int(target_year),
            baseline_start=int(baseline_start),
            baseline_end=int(baseline_end),
        )
        for row in monthly.to_dict(orient="records"):
            monthly_rows.append({
                "tenant_key":asset["tenant_key"],
                "asset_location_id":asset["asset_location_id"],
                "external_id":asset["external_id"],
                "site_identity_grade":asset["site_identity_grade"],
                "indicator_id":row["indicator_id"],
                "period":str(row["period"]),
                "value":row["value"],
                "unit":row["unit"],
                "value_class":row["value_class"],
                "measurement_basis":row["measurement_basis"],
                "method_version":row["method_version"],
                "quality_flag":row["quality_flag"],
                "scale_months":int(row["scale_months"]),
            })
        annual=annual_spi_summary(monthly)
        for row in annual.to_dict(orient="records"):
            annual_rows.append({
                "tenant_key":asset["tenant_key"],
                "asset_location_id":asset["asset_location_id"],
                "external_id":asset["external_id"],
                "site_identity_grade":asset["site_identity_grade"],
                "indicator_id":row["indicator_id"],
                "value":row["value"],
                "unit":row["unit"],
                "value_class":"CALCULATED",
                "measurement_basis":"CALCULATED_FROM_SATELLITE_GAUGE_PRECIPITATION",
                "method_version":"CHIRPS_SPI_GAMMA_0.1",
                "quality_flag":row["quality_flag"],
                "target_year":int(target_year),
            })
    return pd.DataFrame(monthly_rows),pd.DataFrame(annual_rows),records


def write_spi_parquet(
    root:str|Path,
    monthly:pd.DataFrame,
    annual:pd.DataFrame,
    *,
    target_year:int,
    run_id:str,
)->tuple[Path,Path]:
    directory=parquet_partition_dir(
        root,layer="indicators",dataset="chirps_spi",
        partitions={"year":int(target_year)},
    )
    directory.mkdir(parents=True,exist_ok=True)
    monthly_path=directory/f"monthly-{run_id}.parquet"
    annual_path=directory/f"annual-{run_id}.parquet"
    monthly.to_parquet(monthly_path,index=False)
    annual.to_parquet(annual_path,index=False)
    register_parquet_dataset(
        root,dataset_name="chirps_spi_monthly",layer="indicators",
        parquet_path=monthly_path,partition_spec={"year":int(target_year)},
        row_count=len(monthly),run_id=run_id,
    )
    register_parquet_dataset(
        root,dataset_name="chirps_spi_annual_summary",layer="indicators",
        parquet_path=annual_path,partition_spec={"year":int(target_year)},
        row_count=len(annual),run_id=run_id,
    )
    return monthly_path,annual_path


def _lineage_sources(records:dict[int,dict],target_year:int,baseline_start:int,baseline_end:int):
    baseline_years=set(range(int(baseline_start)-1,int(baseline_end)+1))
    target_years={int(target_year)-1,int(target_year)}
    baseline=[records[y]["source_artifact_id"] for y in sorted(baseline_years) if y in records]
    target=[records[y]["source_artifact_id"] for y in sorted(target_years) if y in records]
    return baseline,target


def insert_spi_indicators(
    root:str|Path,
    monthly:pd.DataFrame,
    annual:pd.DataFrame,
    records:dict[int,dict],
    *,
    target_year:int,
    baseline_start:int,
    baseline_end:int,
    run_id:str,
)->int:
    baseline_sources,target_sources=_lineage_sources(
        records,target_year,baseline_start,baseline_end
    )
    primary=records[int(target_year)]["source_artifact_id"]
    count=0
    with connect_catalog(root) as conn:
        for row in monthly.to_dict(orient="records"):
            period=pd.Period(row["period"],freq="M")
            value=None if pd.isna(row["value"]) else float(row["value"])
            null_reason=None if value is not None else row["quality_flag"]
            cur=conn.execute(
                """
                INSERT INTO asset_indicator(
                    tenant_key,asset_location_id,indicator_id,value_numeric,value_text,
                    unit,value_class,measurement_basis,source_artifact_id,method_version,
                    period_start,period_end,quality_flag,null_reason,run_id,calculated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row["tenant_key"],row["asset_location_id"],row["indicator_id"],
                    value,None,row["unit"],row["value_class"],row["measurement_basis"],
                    primary,row["method_version"],
                    period.start_time.date().isoformat(),
                    period.end_time.date().isoformat(),
                    row["quality_flag"],null_reason,run_id,utc_now(),
                ),
            )
            for sid in baseline_sources:
                conn.execute(
                    "INSERT OR IGNORE INTO asset_indicator_source(asset_indicator_id,source_artifact_id,source_role) VALUES(?,?,?)",
                    (cur.lastrowid,sid,"BASELINE_SERIES"),
                )
            for sid in target_sources:
                conn.execute(
                    "INSERT OR IGNORE INTO asset_indicator_source(asset_indicator_id,source_artifact_id,source_role) VALUES(?,?,?)",
                    (cur.lastrowid,sid,"TARGET_SERIES"),
                )
            count+=1

        for row in annual.to_dict(orient="records"):
            value=None if pd.isna(row["value"]) else float(row["value"])
            null_reason=None if value is not None else row["quality_flag"]
            cur=conn.execute(
                """
                INSERT INTO asset_indicator(
                    tenant_key,asset_location_id,indicator_id,value_numeric,value_text,
                    unit,value_class,measurement_basis,source_artifact_id,method_version,
                    period_start,period_end,quality_flag,null_reason,run_id,calculated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row["tenant_key"],row["asset_location_id"],row["indicator_id"],
                    value,None,row["unit"],row["value_class"],row["measurement_basis"],
                    primary,row["method_version"],f"{target_year}-01-01",f"{target_year}-12-31",
                    row["quality_flag"],null_reason,run_id,utc_now(),
                ),
            )
            for sid in baseline_sources:
                conn.execute(
                    "INSERT OR IGNORE INTO asset_indicator_source(asset_indicator_id,source_artifact_id,source_role) VALUES(?,?,?)",
                    (cur.lastrowid,sid,"BASELINE_SERIES"),
                )
            for sid in target_sources:
                conn.execute(
                    "INSERT OR IGNORE INTO asset_indicator_source(asset_indicator_id,source_artifact_id,source_role) VALUES(?,?,?)",
                    (cur.lastrowid,sid,"TARGET_SERIES"),
                )
            count+=1
        conn.commit()
    return count
