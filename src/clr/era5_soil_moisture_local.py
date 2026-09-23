from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .era5_local import area_from_assets
from .local_store import (
    connect_catalog,
    parquet_partition_dir,
    register_parquet_dataset,
    register_source_file,
    sha256_file,
    source_snapshot_path,
    utc_now,
)

DATASET="reanalysis-era5-land-monthly-means"
PROVIDER="Copernicus Climate Data Store / ECMWF"
PROVIDER_KEY="ECMWF_COPERNICUS_CDS"
VARIABLES=(
    "volumetric_soil_water_layer_1",
    "volumetric_soil_water_layer_2",
)
BASELINE_START=1991
BASELINE_END=2020
MEASUREMENT_BASIS="CALCULATED_FROM_REANALYSIS_SOIL_MOISTURE"


def monthly_request(assets:list[dict],year:int)->dict:
    if not (1950<=int(year)<=2100):
        raise ValueError("ERA5-Land year outside supported planning range")
    return {
        "product_type":["monthly_averaged_reanalysis"],
        "variable":list(VARIABLES),
        "year":[str(int(year))],
        "month":[f"{m:02d}" for m in range(1,13)],
        "time":["00:00"],
        "data_format":"netcdf",
        "download_format":"unarchived",
        "area":area_from_assets(assets),
    }


def request_digest(request:dict)->str:
    payload=json.dumps(request,sort_keys=True,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def source_id_for_request(year:int,request:dict)->str:
    return f"ERA5L_MONTHLY_SOIL_{int(year)}_{request_digest(request)[:16]}"


def required_soil_years(
    target_year:int,
    *,
    baseline_start:int=BASELINE_START,
    baseline_end:int=BASELINE_END,
)->list[int]:
    years=set(range(int(baseline_start),int(baseline_end)+1))
    years.add(int(target_year))
    return sorted(years)


def _verified_source(root:Path,source_id:str):
    with connect_catalog(root) as conn:
        rows=conn.execute(
            """
            SELECT * FROM source_artifact
            WHERE source_id=? AND retrieval_status='COMPLETE'
            ORDER BY retrieved_at DESC
            """,(source_id,)
        ).fetchall()
    for row in rows:
        p=root/row["local_path"]
        if p.exists() and sha256_file(p)==row["sha256"]:
            return dict(row)
    return None


def retrieve_monthly_year(
    root:str|Path,
    assets:list[dict],
    year:int,
    *,
    client=None,
)->dict:
    root=Path(root).resolve()
    request=monthly_request(assets,year)
    source_id=source_id_for_request(year,request)
    cached=_verified_source(root,source_id)
    if cached is not None:
        return cached

    if client is None:
        try:
            import cdsapi
        except ImportError as e:
            raise RuntimeError("cdsapi is required. Install requirements-local.txt.") from e
        client=cdsapi.Client()

    digest=request_digest(request)
    tmp=root/"tmp"/f"era5land_soil_{int(year)}_{digest[:12]}.nc"
    tmp.parent.mkdir(parents=True,exist_ok=True)
    if tmp.exists():
        tmp.unlink()

    client.retrieve(DATASET,request).download(str(tmp))
    if not tmp.exists() or tmp.stat().st_size==0:
        raise RuntimeError("CDS soil-moisture retrieval did not create a non-empty artifact")

    artifact_sha=sha256_file(tmp)
    version="monthly_means_retrieval_"+datetime.now(timezone.utc).strftime("%Y%m%d")
    destination=source_snapshot_path(
        root,PROVIDER_KEY,DATASET,version,artifact_sha,
        f"era5land_soil_{int(year)}.nc",
    )
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        if sha256_file(destination)!=artifact_sha:
            raise RuntimeError("Existing ERA5 soil-moisture artifact has unexpected bytes")
        tmp.unlink()
    else:
        shutil.move(str(tmp),str(destination))

    return register_source_file(
        root,source_id=source_id,provider=PROVIDER,provider_version=version,
        artifact_path=destination,media_type="application/x-netcdf",
        valid_time_start=f"{int(year)}-01-01",
        valid_time_end=f"{int(year)}-12-31",
        retrieval_status="COMPLETE",
        note=(
            "ERA5-Land monthly averaged volumetric soil water layers 1 and 2. "
            "Reanalysis grid-cell context; not an in-situ soil-moisture measurement."
        ),
        request_parameters={"dataset":DATASET,**request},
    )


def _coord_name(ds,candidates):
    for name in candidates:
        if name in ds.coords or name in ds.dims:
            return name
    raise ValueError(f"Missing coordinate; expected one of {candidates}")


def _soil_var(ds,layer:int)->str:
    candidates={
        1:("swvl1","volumetric_soil_water_layer_1"),
        2:("swvl2","volumetric_soil_water_layer_2"),
    }[int(layer)]
    for name in candidates:
        if name in ds.data_vars:
            return name
    for name,var in ds.data_vars.items():
        long_name=str(var.attrs.get("long_name","")).lower()
        if f"soil water layer {layer}" in long_name:
            return name
    raise ValueError(f"Could not identify soil-water layer {layer} among {list(ds.data_vars)}")


def extract_monthly_soil_file(
    path:str|Path,
    assets:list[dict],
    *,
    source_artifact_id:str,
)->pd.DataFrame:
    try:
        import xarray as xr
    except ImportError as e:
        raise RuntimeError("xarray is required. Install requirements-local.txt.") from e

    rows=[]
    with xr.open_dataset(path) as ds:
        lat_name=_coord_name(ds,("latitude","lat"))
        lon_name=_coord_name(ds,("longitude","lon"))
        time_name=_coord_name(ds,("valid_time","time","date"))
        vars_by_layer={1:_soil_var(ds,1),2:_soil_var(ds,2)}

        for asset in assets:
            selected={}
            grid_lat=None; grid_lon=None
            for layer,var_name in vars_by_layer.items():
                da=ds[var_name].sel(
                    {
                        lat_name:float(asset["latitude"]),
                        lon_name:float(asset["longitude"]),
                    },
                    method="nearest",
                )
                for dim in list(da.dims):
                    if dim not in {time_name} and da.sizes.get(dim,1)==1:
                        da=da.squeeze(dim,drop=True)
                frame=da.to_dataframe(name=f"swvl{layer}").reset_index()
                if time_name not in frame.columns:
                    raise ValueError(f"Time coordinate {time_name} not found")
                selected[layer]=frame[[time_name,f"swvl{layer}"]]
                grid_lat=float(da[lat_name].values)
                grid_lon=float(da[lon_name].values)

            merged=selected[1].merge(selected[2],on=time_name,how="inner")
            merged["date"]=pd.to_datetime(merged[time_name]).dt.to_period("M").astype(str)
            merged["asset_location_id"]=asset["asset_location_id"]
            merged["tenant_key"]=asset["tenant_key"]
            merged["external_system"]=asset["external_system"]
            merged["external_id"]=asset["external_id"]
            merged["grid_latitude"]=grid_lat
            merged["grid_longitude"]=grid_lon
            merged["source_artifact_id"]=source_artifact_id
            rows.append(merged[
                [
                    "asset_location_id","tenant_key","external_system","external_id",
                    "date","swvl1","swvl2","grid_latitude","grid_longitude",
                    "source_artifact_id",
                ]
            ])

    if not rows:
        raise ValueError("No ERA5-Land soil-moisture rows extracted")
    out=pd.concat(rows,ignore_index=True)
    out["swvl1"]=pd.to_numeric(out["swvl1"],errors="coerce")
    out["swvl2"]=pd.to_numeric(out["swvl2"],errors="coerce")
    if out[["swvl1","swvl2"]].isna().any().any():
        raise ValueError("ERA5-Land soil-moisture extraction contains missing values")
    return out.drop_duplicates(
        subset=["asset_location_id","date"]
    ).sort_values(["asset_location_id","date"]).reset_index(drop=True)


def monthly_soil_anomalies(
    monthly:pd.DataFrame,
    target_year:int,
    *,
    baseline_start:int=BASELINE_START,
    baseline_end:int=BASELINE_END,
)->pd.DataFrame:
    required={
        "asset_location_id","tenant_key","external_id","date",
        "swvl1","swvl2","source_artifact_id",
    }
    if not required.issubset(monthly.columns):
        raise ValueError(f"Soil-moisture frame missing {sorted(required-set(monthly.columns))}")

    x=monthly.copy()
    period=pd.PeriodIndex(x["date"],freq="M")
    x["year"]=period.year
    x["month"]=period.month

    rows=[]
    expected=baseline_end-baseline_start+1
    for asset_id,g in x.groupby("asset_location_id"):
        target=g[g["year"]==int(target_year)]
        if target["month"].nunique()!=12:
            raise ValueError(
                f"Incomplete target-year soil moisture for asset {asset_id}: "
                f"{target['month'].nunique()} months"
            )
        first=g.iloc[0]
        for layer in (1,2):
            field=f"swvl{layer}"
            for month in range(1,13):
                cal=g[
                    g["year"].between(baseline_start,baseline_end)
                    & (g["month"]==month)
                ][field].dropna()
                if len(cal)!=expected:
                    raise ValueError(
                        f"Incomplete soil-moisture baseline for asset {asset_id}, "
                        f"layer {layer}, month {month}: {len(cal)} of {expected}"
                    )
                target_row=target[target["month"]==month]
                if len(target_row)!=1:
                    raise ValueError("Target month is missing or duplicated")
                value=float(target_row.iloc[0][field])
                mean=float(cal.mean())
                sd=float(cal.std(ddof=1))
                if not np.isfinite(sd) or sd<=0:
                    z=None
                    quality="ZERO_VARIANCE_BASELINE"
                else:
                    z=float((value-mean)/sd)
                    quality="OK"
                rows.append({
                    "tenant_key":first["tenant_key"],
                    "asset_location_id":asset_id,
                    "external_id":first["external_id"],
                    "indicator_id":f"soil_moisture_l{layer}_anomaly_z",
                    "period":f"{int(target_year):04d}-{month:02d}",
                    "value":z,
                    "raw_value_m3_m3":value,
                    "baseline_mean_m3_m3":mean,
                    "baseline_sd_m3_m3":sd,
                    "unit":"standardized_anomaly",
                    "value_class":"CALCULATED",
                    "measurement_basis":MEASUREMENT_BASIS,
                    "method_version":"ERA5L_MONTHLY_SOIL_ANOMALY_0.1",
                    "quality_flag":quality,
                    "source_artifact_id":target_row.iloc[0]["source_artifact_id"],
                })
    return pd.DataFrame(rows)


def annual_soil_summary(monthly_anomalies:pd.DataFrame,target_year:int)->pd.DataFrame:
    rows=[]
    for (asset_id,indicator_id),g in monthly_anomalies.groupby(
        ["asset_location_id","indicator_id"]
    ):
        first=g.iloc[0]
        valid=g[(g["quality_flag"]=="OK") & g["value"].notna()]
        suffix=indicator_id.replace("_anomaly_z","")
        if len(valid)!=12:
            vals=[
                (f"{suffix}_min_z_year",None,"standardized_anomaly"),
                (f"{suffix}_months_le_minus1",None,"months/year"),
            ]
            quality="INCOMPLETE_MONTHLY_ANOMALY"
        else:
            vals=[
                (f"{suffix}_min_z_year",float(valid["value"].min()),"standardized_anomaly"),
                (f"{suffix}_months_le_minus1",float((valid["value"]<=-1).sum()),"months/year"),
            ]
            quality="OK"
        for iid,value,unit in vals:
            rows.append({
                "tenant_key":first["tenant_key"],
                "asset_location_id":asset_id,
                "external_id":first["external_id"],
                "indicator_id":iid,
                "value":value,"unit":unit,"value_class":"CALCULATED",
                "measurement_basis":MEASUREMENT_BASIS,
                "method_version":"ERA5L_MONTHLY_SOIL_ANOMALY_0.1",
                "quality_flag":quality,"target_year":int(target_year),
            })
    return pd.DataFrame(rows)


def ensure_soil_sources(
    root:str|Path,
    assets:list[dict],
    target_year:int,
    *,
    baseline_start:int=BASELINE_START,
    baseline_end:int=BASELINE_END,
    client=None,
)->dict[int,dict]:
    records={}
    for year in required_soil_years(
        target_year,baseline_start=baseline_start,baseline_end=baseline_end
    ):
        records[year]=retrieve_monthly_year(root,assets,year,client=client)
    return records


def build_soil_metrics(
    root:str|Path,
    assets:list[dict],
    target_year:int,
    *,
    baseline_start:int=BASELINE_START,
    baseline_end:int=BASELINE_END,
)->tuple[pd.DataFrame,pd.DataFrame,dict[int,dict]]:
    records={}
    frames=[]
    for year in required_soil_years(
        target_year,baseline_start=baseline_start,baseline_end=baseline_end
    ):
        request=monthly_request(assets,year)
        source_id=source_id_for_request(year,request)
        record=_verified_source(Path(root).resolve(),source_id)
        if record is None:
            raise FileNotFoundError(
                f"Missing verified ERA5-Land monthly soil-moisture source for {year}"
            )
        records[year]=record
        frame=extract_monthly_soil_file(
            Path(root).resolve()/record["local_path"],assets,
            source_artifact_id=record["source_artifact_id"],
        )
        frames.append(frame)

    monthly_source=pd.concat(frames,ignore_index=True)
    monthly=monthly_soil_anomalies(
        monthly_source,target_year,
        baseline_start=baseline_start,baseline_end=baseline_end,
    )
    annual=annual_soil_summary(monthly,target_year)
    return monthly,annual,records


def write_soil_parquet(
    root:str|Path,
    monthly:pd.DataFrame,
    annual:pd.DataFrame,
    *,
    target_year:int,
    run_id:str,
)->tuple[Path,Path]:
    directory=parquet_partition_dir(
        root,layer="indicators",dataset="era5_land_soil_moisture",
        partitions={"year":int(target_year)},
    )
    directory.mkdir(parents=True,exist_ok=True)
    monthly_path=directory/f"monthly-{run_id}.parquet"
    annual_path=directory/f"annual-{run_id}.parquet"
    monthly.to_parquet(monthly_path,index=False)
    annual.to_parquet(annual_path,index=False)
    register_parquet_dataset(
        root,dataset_name="era5_land_soil_moisture_monthly_anomaly",
        layer="indicators",parquet_path=monthly_path,
        partition_spec={"year":int(target_year)},row_count=len(monthly),run_id=run_id,
    )
    register_parquet_dataset(
        root,dataset_name="era5_land_soil_moisture_annual_summary",
        layer="indicators",parquet_path=annual_path,
        partition_spec={"year":int(target_year)},row_count=len(annual),run_id=run_id,
    )
    return monthly_path,annual_path


def insert_soil_indicators(
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
    baseline_sources=[
        records[y]["source_artifact_id"]
        for y in range(int(baseline_start),int(baseline_end)+1)
    ]
    target_source=records[int(target_year)]["source_artifact_id"]
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
                    row["source_artifact_id"],row["method_version"],
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
            conn.execute(
                "INSERT OR IGNORE INTO asset_indicator_source(asset_indicator_id,source_artifact_id,source_role) VALUES(?,?,?)",
                (cur.lastrowid,target_source,"TARGET_SERIES"),
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
                    target_source,row["method_version"],f"{target_year}-01-01",
                    f"{target_year}-12-31",row["quality_flag"],null_reason,run_id,utc_now(),
                ),
            )
            for sid in baseline_sources:
                conn.execute(
                    "INSERT OR IGNORE INTO asset_indicator_source(asset_indicator_id,source_artifact_id,source_role) VALUES(?,?,?)",
                    (cur.lastrowid,sid,"BASELINE_SERIES"),
                )
            conn.execute(
                "INSERT OR IGNORE INTO asset_indicator_source(asset_indicator_id,source_artifact_id,source_role) VALUES(?,?,?)",
                (cur.lastrowid,target_source,"TARGET_SERIES"),
            )
            count+=1
        conn.commit()
    return count
