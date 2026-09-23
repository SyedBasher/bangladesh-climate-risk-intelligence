from __future__ import annotations

import hashlib
import math
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .local_store import (
    connect_catalog,
    parquet_partition_dir,
    register_parquet_dataset,
    register_source_file,
    sha256_file,
    source_snapshot_path,
    utc_now,
)

IBTRACS_NI_CSV_URL=(
    "https://www.ncei.noaa.gov/data/"
    "international-best-track-archive-for-climate-stewardship-ibtracs/"
    "v04r01/access/csv/ibtracs.NI.list.v04r01.csv"
)
PROVIDER="NOAA National Centers for Environmental Information"
PROVIDER_VERSION="IBTrACS_v04r01"
SOURCE_ID="NOAA_IBTRACS_NI_V04R01"
MEASUREMENT_BASIS="HISTORICAL_TROPICAL_CYCLONE_BEST_TRACK"
DEFAULT_START_YEAR=1980
DEFAULT_MAX_DISTANCE_KM=500.0
SUMMARY_RADII_KM=(100.0,250.0)


def haversine_km(lat1,lon1,lat2,lon2)->float:
    r=6371.0088
    p1=math.radians(float(lat1)); p2=math.radians(float(lat2))
    dphi=math.radians(float(lat2)-float(lat1))
    dlambda=math.radians(float(lon2)-float(lon1))
    a=math.sin(dphi/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dlambda/2)**2
    return 2*r*math.asin(min(1.0,math.sqrt(a)))


def _download(url:str,target:Path,session=None)->dict:
    s=session or requests.Session()
    target.parent.mkdir(parents=True,exist_ok=True)
    part=target.with_suffix(target.suffix+".part")
    if part.exists():
        part.unlink()
    response=s.get(
        url,stream=True,timeout=180,
        headers={"User-Agent":"Mangrove-Climate-Risk/0.1"},
    )
    response.raise_for_status()
    with open(part,"wb") as f:
        for chunk in response.iter_content(chunk_size=1024*1024):
            if chunk:
                f.write(chunk)
    if not part.exists() or part.stat().st_size==0:
        raise RuntimeError("IBTrACS download is empty")
    part.replace(target)
    return {
        "last_modified":response.headers.get("Last-Modified"),
        "etag":response.headers.get("ETag"),
        "content_length":response.headers.get("Content-Length"),
    }


def _verified_source(root:Path):
    with connect_catalog(root) as conn:
        rows=conn.execute(
            """
            SELECT * FROM source_artifact
            WHERE source_id=? AND retrieval_status='COMPLETE'
            ORDER BY retrieved_at DESC
            """,(SOURCE_ID,)
        ).fetchall()
    for row in rows:
        path=root/row["local_path"]
        if path.exists() and sha256_file(path)==row["sha256"]:
            return dict(row)
    return None


def retrieve_ibtracs_ni(
    root:str|Path,
    *,
    force_refresh:bool=False,
    session=None,
)->dict:
    root=Path(root).resolve()
    if not force_refresh:
        cached=_verified_source(root)
        if cached is not None:
            return cached

    tmp=root/"tmp"/"ibtracs.NI.list.v04r01.csv"
    if tmp.exists():
        tmp.unlink()
    headers=_download(IBTRACS_NI_CSV_URL,tmp,session=session)
    digest=sha256_file(tmp)
    destination=source_snapshot_path(
        root,"NOAA_NCEI","IBTRACS_NI",PROVIDER_VERSION,
        digest,"ibtracs.NI.list.v04r01.csv",
    )
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        if sha256_file(destination)!=digest:
            raise RuntimeError("Content-addressed IBTrACS snapshot has unexpected bytes")
        tmp.unlink()
    else:
        shutil.move(str(tmp),str(destination))

    return register_source_file(
        root,source_id=SOURCE_ID,provider=PROVIDER,
        provider_version=PROVIDER_VERSION,artifact_path=destination,
        media_type="text/csv",retrieval_status="COMPLETE",
        note=(
            "Official IBTrACS v04r01 North Indian basin CSV snapshot. "
            "Track positions and agency intensity fields are historical best-track "
            "context; they are not site-level wind, storm surge or damage estimates."
        ),
        request_parameters={
            "download_url":IBTRACS_NI_CSV_URL,
            "subset":"NI",
            "release":"v04r01",
            "http_last_modified":headers.get("last_modified"),
            "http_etag":headers.get("etag"),
            "http_content_length":headers.get("content_length"),
        },
    )


def _numeric(series:pd.Series)->pd.Series:
    return pd.to_numeric(series,errors="coerce")


def read_ibtracs_csv(
    path:str|Path,
    *,
    start_year:int=DEFAULT_START_YEAR,
)->pd.DataFrame:
    frame=pd.read_csv(path,dtype=str,low_memory=False)
    required={"SID","SEASON","ISO_TIME","LAT","LON","NAME","TRACK_TYPE"}
    missing=required-set(frame.columns)
    if missing:
        raise ValueError(f"IBTrACS CSV missing required columns {sorted(missing)}")

    frame["season_num"]=_numeric(frame["SEASON"])
    frame["track_lat"]=_numeric(frame["LAT"])
    frame["track_lon"]=_numeric(frame["LON"])
    frame["iso_time_parsed"]=pd.to_datetime(frame["ISO_TIME"],errors="coerce",utc=True)

    frame=frame[
        frame["season_num"].ge(int(start_year))
        & frame["track_lat"].between(-90,90)
        & frame["track_lon"].between(-180,180)
        & frame["iso_time_parsed"].notna()
        & frame["SID"].fillna("").ne("")
    ].copy()

    numeric_fields=[
        "WMO_WIND","WMO_PRES","USA_WIND","USA_PRES",
        "STORM_SPEED","STORM_DIR","DIST2LAND","LANDFALL",
    ]
    for field in numeric_fields:
        if field in frame.columns:
            frame[field.lower()]=_numeric(frame[field])
        else:
            frame[field.lower()]=np.nan

    keep=[
        "SID","SEASON","NAME","BASIN","SUBBASIN","ISO_TIME","NATURE",
        "TRACK_TYPE","WMO_AGENCY","USA_AGENCY",
        "track_lat","track_lon","iso_time_parsed",
        "wmo_wind","wmo_pres","usa_wind","usa_pres",
        "storm_speed","storm_dir","dist2land","landfall",
    ]
    for field in keep:
        if field not in frame.columns:
            frame[field]=None

    out=frame[keep].rename(columns={
        "SID":"sid","SEASON":"season","NAME":"storm_name",
        "BASIN":"basin","SUBBASIN":"subbasin","ISO_TIME":"iso_time",
        "NATURE":"nature","TRACK_TYPE":"track_type",
        "WMO_AGENCY":"wmo_agency","USA_AGENCY":"usa_agency",
    })
    return out.sort_values(["sid","iso_time_parsed"]).reset_index(drop=True)


def asset_storm_context(
    tracks:pd.DataFrame,
    assets:list[dict],
    *,
    max_distance_km:float=DEFAULT_MAX_DISTANCE_KM,
)->tuple[pd.DataFrame,pd.DataFrame]:
    if max_distance_km<=0:
        raise ValueError("max_distance_km must be positive")
    if tracks.empty:
        raise ValueError("IBTrACS track table is empty")
    if not assets:
        raise ValueError("No assets supplied")

    nearest_rows=[]
    timeline_rows=[]

    for asset in assets:
        alat=float(asset["latitude"]); alon=float(asset["longitude"])
        for sid,storm in tracks.groupby("sid",sort=False):
            distances=np.array([
                haversine_km(alat,alon,lat,lon)
                for lat,lon in zip(storm["track_lat"],storm["track_lon"])
            ],dtype=float)
            idx=int(distances.argmin())
            min_distance=float(distances[idx])
            if min_distance>max_distance_km:
                continue
            closest=storm.iloc[idx]

            nearest_rows.append({
                "tenant_key":asset["tenant_key"],
                "asset_location_id":asset["asset_location_id"],
                "external_system":asset["external_system"],
                "external_id":asset["external_id"],
                "site_identity_grade":asset["site_identity_grade"],
                "sid":sid,
                "season":int(float(closest["season"])),
                "storm_name":None if pd.isna(closest["storm_name"]) else str(closest["storm_name"]),
                "closest_trackpoint_time":closest["iso_time_parsed"].isoformat(),
                "closest_trackpoint_distance_km":min_distance,
                "track_latitude":float(closest["track_lat"]),
                "track_longitude":float(closest["track_lon"]),
                "nature":None if pd.isna(closest["nature"]) else str(closest["nature"]),
                "track_type":None if pd.isna(closest["track_type"]) else str(closest["track_type"]),
                "wmo_agency":None if pd.isna(closest["wmo_agency"]) else str(closest["wmo_agency"]),
                "wmo_wind_knots":None if pd.isna(closest["wmo_wind"]) else float(closest["wmo_wind"]),
                "wmo_pressure_hpa":None if pd.isna(closest["wmo_pres"]) else float(closest["wmo_pres"]),
                "usa_agency":None if pd.isna(closest["usa_agency"]) else str(closest["usa_agency"]),
                "usa_wind_knots":None if pd.isna(closest["usa_wind"]) else float(closest["usa_wind"]),
                "usa_pressure_hpa":None if pd.isna(closest["usa_pres"]) else float(closest["usa_pres"]),
                "storm_translation_speed_knots":None if pd.isna(closest["storm_speed"]) else float(closest["storm_speed"]),
                "storm_translation_direction_deg":None if pd.isna(closest["storm_dir"]) else float(closest["storm_dir"]),
                "ibtracs_distance_to_land_km":None if pd.isna(closest["dist2land"]) else float(closest["dist2land"]),
                "ibtracs_landfall_next3h_km":None if pd.isna(closest["landfall"]) else float(closest["landfall"]),
            })

            within=storm.iloc[np.where(distances<=max_distance_km)[0]].copy()
            for local_i,(row_index,row) in enumerate(within.iterrows()):
                original_pos=storm.index.get_loc(row_index)
                timeline_rows.append({
                    "tenant_key":asset["tenant_key"],
                    "asset_location_id":asset["asset_location_id"],
                    "external_id":asset["external_id"],
                    "sid":sid,
                    "storm_name":None if pd.isna(row["storm_name"]) else str(row["storm_name"]),
                    "iso_time":row["iso_time_parsed"].isoformat(),
                    "distance_km":float(distances[original_pos]),
                    "track_latitude":float(row["track_lat"]),
                    "track_longitude":float(row["track_lon"]),
                    "nature":None if pd.isna(row["nature"]) else str(row["nature"]),
                    "track_type":None if pd.isna(row["track_type"]) else str(row["track_type"]),
                    "wmo_agency":None if pd.isna(row["wmo_agency"]) else str(row["wmo_agency"]),
                    "wmo_wind_knots":None if pd.isna(row["wmo_wind"]) else float(row["wmo_wind"]),
                    "wmo_pressure_hpa":None if pd.isna(row["wmo_pres"]) else float(row["wmo_pres"]),
                    "usa_agency":None if pd.isna(row["usa_agency"]) else str(row["usa_agency"]),
                    "usa_wind_knots":None if pd.isna(row["usa_wind"]) else float(row["usa_wind"]),
                    "usa_pressure_hpa":None if pd.isna(row["usa_pres"]) else float(row["usa_pres"]),
                })

    nearest=pd.DataFrame(nearest_rows)
    timeline=pd.DataFrame(timeline_rows)
    if not nearest.empty:
        nearest=nearest.sort_values(
            ["asset_location_id","season","sid"]
        ).reset_index(drop=True)
    if not timeline.empty:
        timeline=timeline.sort_values(
            ["asset_location_id","sid","iso_time"]
        ).reset_index(drop=True)
    return nearest,timeline


def historical_asset_summary(
    nearest:pd.DataFrame,
    assets:list[dict],
    *,
    start_year:int=DEFAULT_START_YEAR,
    end_year:int|None=None,
)->pd.DataFrame:
    if end_year is None:
        end_year=pd.Timestamp.utcnow().year
    rows=[]
    grouped={
        key:g for key,g in nearest.groupby("asset_location_id")
    } if not nearest.empty else {}

    for asset in assets:
        g=grouped.get(asset["asset_location_id"])
        base={
            "tenant_key":asset["tenant_key"],
            "asset_location_id":asset["asset_location_id"],
            "external_id":asset["external_id"],
            "period_start_year":int(start_year),
            "period_end_year":int(end_year),
        }
        if g is None or g.empty:
            base.update({
                "nearest_trackpoint_distance_km":None,
                "nearest_storm_sid":None,
                "storms_within_100km_count":0,
                "storms_within_250km_count":0,
                "quality_flag":"NO_STORMS_WITHIN_ANALYSIS_RADIUS",
            })
        else:
            nearest_row=g.loc[g["closest_trackpoint_distance_km"].idxmin()]
            base.update({
                "nearest_trackpoint_distance_km":float(nearest_row["closest_trackpoint_distance_km"]),
                "nearest_storm_sid":str(nearest_row["sid"]),
                "storms_within_100km_count":int(
                    (g["closest_trackpoint_distance_km"]<=SUMMARY_RADII_KM[0]).sum()
                ),
                "storms_within_250km_count":int(
                    (g["closest_trackpoint_distance_km"]<=SUMMARY_RADII_KM[1]).sum()
                ),
                "quality_flag":"HISTORICAL_TRACK_CONTEXT",
            })
        rows.append(base)
    return pd.DataFrame(rows)


def write_cyclone_parquet(
    root:str|Path,
    nearest:pd.DataFrame,
    timeline:pd.DataFrame,
    summary:pd.DataFrame,
    *,
    start_year:int,
    run_id:str,
)->tuple[Path,Path,Path]:
    directory=parquet_partition_dir(
        root,layer="indicators",dataset="ibtracs_cyclone_context",
        partitions={"start_year":int(start_year),"version":"v04r01"},
    )
    directory.mkdir(parents=True,exist_ok=True)
    nearest_path=directory/f"asset-storm-nearest-{run_id}.parquet"
    timeline_path=directory/f"asset-storm-timeline-{run_id}.parquet"
    summary_path=directory/f"asset-history-summary-{run_id}.parquet"
    nearest.to_parquet(nearest_path,index=False)
    timeline.to_parquet(timeline_path,index=False)
    summary.to_parquet(summary_path,index=False)

    for dataset,path,rows in (
        ("ibtracs_asset_storm_nearest",nearest_path,len(nearest)),
        ("ibtracs_asset_storm_timeline",timeline_path,len(timeline)),
        ("ibtracs_asset_history_summary",summary_path,len(summary)),
    ):
        register_parquet_dataset(
            root,dataset_name=dataset,layer="indicators",
            parquet_path=path,
            partition_spec={"start_year":int(start_year),"version":"v04r01"},
            row_count=rows,run_id=run_id,
        )
    return nearest_path,timeline_path,summary_path


def insert_cyclone_indicators(
    root:str|Path,
    nearest:pd.DataFrame,
    summary:pd.DataFrame,
    *,
    source_artifact_id:str,
    start_year:int,
    end_year:int,
    run_id:str,
)->int:
    count=0
    with connect_catalog(root) as conn:
        for row in nearest.to_dict(orient="records"):
            period_start=str(row["closest_trackpoint_time"])
            specs=[
                (
                    "ibtracs_storm_closest_trackpoint_distance_km",
                    row["closest_trackpoint_distance_km"],None,"km"
                ),
                (
                    "ibtracs_wmo_wind_knots_at_closest_trackpoint",
                    row["wmo_wind_knots"],None,"knots"
                ),
                (
                    "ibtracs_usa_wind_knots_at_closest_trackpoint",
                    row["usa_wind_knots"],None,"knots"
                ),
                (
                    "ibtracs_wmo_pressure_hpa_at_closest_trackpoint",
                    row["wmo_pressure_hpa"],None,"hPa"
                ),
                (
                    "ibtracs_usa_pressure_hpa_at_closest_trackpoint",
                    row["usa_pressure_hpa"],None,"hPa"
                ),
                (
                    "ibtracs_storm_sid",
                    None,row["sid"],None
                ),
            ]
            for indicator_id,value_numeric,value_text,unit in specs:
                if value_numeric is not None and pd.isna(value_numeric):
                    value_numeric=None
                null_reason=None
                if value_numeric is None and value_text is None:
                    null_reason="IBTRACS_FIELD_UNAVAILABLE_AT_CLOSEST_TRACKPOINT"
                cur=conn.execute(
                    """
                    INSERT INTO asset_indicator(
                        tenant_key,asset_location_id,indicator_id,value_numeric,value_text,
                        unit,value_class,measurement_basis,source_artifact_id,method_version,
                        period_start,period_end,quality_flag,null_reason,run_id,calculated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        row["tenant_key"],row["asset_location_id"],indicator_id,
                        value_numeric,value_text,unit,"SOURCE",MEASUREMENT_BASIS,
                        source_artifact_id,"IBTRACS_TRACKPOINT_CONTEXT_0.1",
                        period_start,period_start,"HISTORICAL_TRACK_CONTEXT",
                        null_reason,run_id,utc_now(),
                    ),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO asset_indicator_source(
                        asset_indicator_id,source_artifact_id,source_role
                    ) VALUES(?,?,?)
                    """,(cur.lastrowid,source_artifact_id,"IBTRACS_TRACK")
                )
                count+=1

        for row in summary.to_dict(orient="records"):
            specs=[
                (
                    "ibtracs_nearest_trackpoint_distance_km_since_start_year",
                    row["nearest_trackpoint_distance_km"],"km"
                ),
                (
                    "ibtracs_storms_with_trackpoint_within_100km_count_since_start_year",
                    row["storms_within_100km_count"],"count"
                ),
                (
                    "ibtracs_storms_with_trackpoint_within_250km_count_since_start_year",
                    row["storms_within_250km_count"],"count"
                ),
            ]
            for indicator_id,value,unit in specs:
                if value is not None and pd.isna(value):
                    value=None
                null_reason=None if value is not None else "NO_STORMS_WITHIN_ANALYSIS_RADIUS"
                cur=conn.execute(
                    """
                    INSERT INTO asset_indicator(
                        tenant_key,asset_location_id,indicator_id,value_numeric,value_text,
                        unit,value_class,measurement_basis,source_artifact_id,method_version,
                        period_start,period_end,quality_flag,null_reason,run_id,calculated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        row["tenant_key"],row["asset_location_id"],indicator_id,
                        None if value is None else float(value),None,unit,
                        "CALCULATED",MEASUREMENT_BASIS,source_artifact_id,
                        "IBTRACS_HISTORICAL_CONTEXT_0.1",
                        f"{int(start_year)}-01-01",f"{int(end_year)}-12-31",
                        row["quality_flag"],null_reason,run_id,utc_now(),
                    ),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO asset_indicator_source(
                        asset_indicator_id,source_artifact_id,source_role
                    ) VALUES(?,?,?)
                    """,(cur.lastrowid,source_artifact_id,"IBTRACS_TRACK")
                )
                count+=1
        conn.commit()
    return count
