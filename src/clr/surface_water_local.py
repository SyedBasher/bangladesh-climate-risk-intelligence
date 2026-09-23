from __future__ import annotations

import math
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import requests
from pyproj import Geod
from rasterio.windows import Window, from_bounds

from .local_store import (
    connect_catalog,
    parquet_partition_dir,
    register_parquet_dataset,
    register_source_file,
    sha256_file,
    source_snapshot_path,
    utc_now,
)

PROVIDER="European Commission Joint Research Centre / Global Surface Water"
PROVIDER_VERSION="GSW_v1.5_2024"
BASE_URL=(
    "https://s3.waw4-1.cloudferro.com/swift/v1/global-surface-water/"
    "download2024/Aggregated/VER1-5"
)
LAYERS=("occurrence","recurrence")
HIGH_OCCURRENCE_THRESHOLD_PCT=90.0
DEFAULT_SEARCH_RADIUS_KM=20.0
GEOD=Geod(ellps="WGS84")


def _axis_token(value:int,positive:str,negative:str,width:int)->str:
    suffix=positive if value>=0 else negative
    return f"{abs(int(value)):0{width}d}{suffix}"


def tile_id_for_point(lat:float,lon:float)->str:
    if not (-90<=float(lat)<=90 and -180<=float(lon)<=180):
        raise ValueError("Invalid coordinate")
    if float(lon)==180:
        lon=179.999999999
    if float(lat)==90:
        lat=89.999999999
    lon0=math.floor(float(lon)/10.0)*10
    lat0=math.floor(float(lat)/10.0)*10
    return (
        f"{_axis_token(lon0,'E','W',1)}_"
        f"{_axis_token(lat0,'N','S',1)}"
    )


def tile_url(layer:str,tile_id:str)->str:
    if layer not in LAYERS:
        raise ValueError(f"Unsupported GSW layer: {layer}")
    filename=f"{layer}_{tile_id}_v1_5_2024.tif"
    return f"{BASE_URL}/{layer}/{filename}"


def _bbox_for_asset(lat:float,lon:float,radius_km:float):
    lat_margin=float(radius_km)/110.574
    cos=max(0.05,math.cos(math.radians(float(lat))))
    lon_margin=float(radius_km)/(111.320*cos)
    return (
        float(lon)-lon_margin,float(lat)-lat_margin,
        float(lon)+lon_margin,float(lat)+lat_margin,
    )


def tiles_for_bbox(bounds)->list[str]:
    west,south,east,north=map(float,bounds)
    if west<-180 or east>180:
        raise ValueError("Antimeridian-crossing GSW searches are not supported")
    south=max(-89.999999,south)
    north=min(89.999999,north)
    lon_starts=range(
        math.floor(west/10.0)*10,
        math.floor((east-1e-12)/10.0)*10+1,
        10,
    )
    lat_starts=range(
        math.floor(south/10.0)*10,
        math.floor((north-1e-12)/10.0)*10+1,
        10,
    )
    return [
        f"{_axis_token(lon0,'E','W',1)}_{_axis_token(lat0,'N','S',1)}"
        for lon0 in lon_starts for lat0 in lat_starts
    ]


def required_tiles(
    assets:list[dict],
    *,
    search_radius_km:float=DEFAULT_SEARCH_RADIUS_KM,
)->list[str]:
    tiles=set()
    for asset in assets:
        tiles.update(tiles_for_bbox(_bbox_for_asset(
            float(asset["latitude"]),float(asset["longitude"]),
            float(search_radius_km),
        )))
    return sorted(tiles)


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


def _download(url:str,target:Path,session=None)->dict:
    s=session or requests.Session()
    target.parent.mkdir(parents=True,exist_ok=True)
    part=target.with_suffix(target.suffix+".part")
    part.unlink(missing_ok=True)
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
        raise RuntimeError(f"Empty GSW download: {url}")
    part.replace(target)
    return {
        "etag":response.headers.get("ETag"),
        "last_modified":response.headers.get("Last-Modified"),
        "content_length":response.headers.get("Content-Length"),
    }


def ensure_tile(
    root:str|Path,
    layer:str,
    tile_id:str,
    *,
    session=None,
)->dict:
    root=Path(root).resolve()
    if layer not in LAYERS:
        raise ValueError(f"Unsupported GSW layer: {layer}")
    source_id=f"JRC_GSW15_{layer.upper()}_{tile_id}"
    cached=_verified_source(root,source_id)
    if cached is not None:
        return cached

    url=tile_url(layer,tile_id)
    filename=url.rsplit("/",1)[-1]
    tmp=root/"tmp"/filename
    tmp.unlink(missing_ok=True)
    headers=_download(url,tmp,session=session)
    digest=sha256_file(tmp)
    dest=source_snapshot_path(
        root,"EC_JRC_GSW",layer.upper(),PROVIDER_VERSION,
        digest,filename,
    )
    dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists():
        if sha256_file(dest)!=digest:
            raise RuntimeError("Content-addressed GSW tile has unexpected bytes")
        tmp.unlink()
    else:
        shutil.move(str(tmp),str(dest))

    with rasterio.open(dest) as ds:
        if ds.count!=1 or ds.crs is None:
            raise ValueError(f"Unexpected GSW raster structure: {filename}")
        if str(ds.crs).upper()!="EPSG:4326":
            raise ValueError(f"GSW tile must be EPSG:4326: {filename}")

    return register_source_file(
        root,source_id=source_id,provider=PROVIDER,
        provider_version=PROVIDER_VERSION,
        artifact_path=dest,media_type="image/tiff",
        valid_time_start="1984-01-01",valid_time_end="2024-12-31",
        retrieval_status="COMPLETE",
        note=(
            f"JRC Global Surface Water v1.5 long-run {layer} tile. "
            "Occurrence/recurrence describe surface-water history and are not flood frequency."
        ),
        request_parameters={
            "source_url":url,"layer":layer,"tile_id":tile_id,
            "period":"1984-2024","version":"1.5",
            "http_etag":headers.get("etag"),
            "http_last_modified":headers.get("last_modified"),
            "http_content_length":headers.get("content_length"),
        },
    )


def ensure_required_tiles(
    root:str|Path,
    assets:list[dict],
    *,
    search_radius_km:float=DEFAULT_SEARCH_RADIUS_KM,
    session=None,
)->dict[str,dict[str,dict]]:
    out={}
    for tile in required_tiles(assets,search_radius_km=search_radius_km):
        out[tile]={}
        for layer in LAYERS:
            out[tile][layer]=ensure_tile(
                root,layer,tile,session=session
            )
    return out


def _sample_point(path:Path,lat:float,lon:float):
    with rasterio.open(path) as ds:
        arr=next(ds.sample([(float(lon),float(lat))],masked=True))
        try:
            if bool(arr.mask[0]):
                return None
        except Exception:
            pass
        value=float(arr[0])
        if not np.isfinite(value):
            return None
        if ds.nodata is not None and value==float(ds.nodata):
            return None
        if value<0 or value>100:
            return None
        return value


def _candidate_water_distance(
    path:Path,
    lat:float,
    lon:float,
    *,
    threshold_pct:float,
    search_radius_km:float,
)->float|None:
    west,south,east,north=_bbox_for_asset(lat,lon,search_radius_km)
    with rasterio.open(path) as ds:
        if not (
            ds.bounds.left<east and ds.bounds.right>west
            and ds.bounds.bottom<north and ds.bounds.top>south
        ):
            return None
        raw=from_bounds(west,south,east,north,transform=ds.transform)
        full=Window(0,0,ds.width,ds.height)
        try:
            window=raw.intersection(full).round_offsets().round_lengths()
        except Exception:
            return None
        if window.width<=0 or window.height<=0:
            return None
        arr=ds.read(1,window=window,masked=True)
        data=np.asarray(arr,dtype=float)
        valid=~np.ma.getmaskarray(arr) & np.isfinite(data)
        water=valid & (data>=float(threshold_pct)) & (data<=100)
        rr,cc=np.where(water)
        if len(rr)==0:
            return None
        transform=ds.window_transform(window)
        xs=transform.c+(cc.astype(float)+0.5)*transform.a
        ys=transform.f+(rr.astype(float)+0.5)*transform.e
        _,_,dist_m=GEOD.inv(
            np.full(len(xs),float(lon)),
            np.full(len(xs),float(lat)),
            xs,ys,
        )
        dist=np.asarray(dist_m,dtype=float)
        dist=dist[np.isfinite(dist)]
        if len(dist)==0:
            return None
        within=dist[dist<=float(search_radius_km)*1000.0]
        if len(within)==0:
            return None
        return float(within.min())


def build_surface_water_context(
    root:str|Path,
    assets:list[dict],
    tile_records:dict[str,dict[str,dict]],
    *,
    occurrence_threshold_pct:float=HIGH_OCCURRENCE_THRESHOLD_PCT,
    search_radius_km:float=DEFAULT_SEARCH_RADIUS_KM,
)->pd.DataFrame:
    if not assets:
        raise ValueError("No assets supplied")
    root=Path(root).resolve()
    rows=[]
    for asset in assets:
        lat=float(asset["latitude"]); lon=float(asset["longitude"])
        home=tile_id_for_point(lat,lon)
        if home not in tile_records:
            raise ValueError(f"Missing home GSW tile {home}")
        occurrence_record=tile_records[home]["occurrence"]
        recurrence_record=tile_records[home]["recurrence"]
        occurrence=_sample_point(
            root/occurrence_record["local_path"],lat,lon
        )
        recurrence=_sample_point(
            root/recurrence_record["local_path"],lat,lon
        )

        candidate=[]
        lineage=[]
        for tile in tiles_for_bbox(
            _bbox_for_asset(lat,lon,search_radius_km)
        ):
            if tile not in tile_records:
                raise ValueError(f"Missing GSW search tile {tile}")
            record=tile_records[tile]["occurrence"]
            lineage.append(record["source_artifact_id"])
            distance=_candidate_water_distance(
                root/record["local_path"],lat,lon,
                threshold_pct=occurrence_threshold_pct,
                search_radius_km=search_radius_km,
            )
            if distance is not None:
                candidate.append(distance)
        distance_m=min(candidate) if candidate else None

        rows.append({
            "tenant_key":asset["tenant_key"],
            "asset_location_id":asset["asset_location_id"],
            "external_system":asset["external_system"],
            "external_id":asset["external_id"],
            "site_identity_grade":asset["site_identity_grade"],
            "occurrence_pct_at_site":occurrence,
            "recurrence_pct_at_site":recurrence,
            "distance_to_high_occurrence_water_m":distance_m,
            "high_occurrence_threshold_pct":float(occurrence_threshold_pct),
            "distance_search_radius_km":float(search_radius_km),
            "occurrence_source_artifact_id":occurrence_record["source_artifact_id"],
            "recurrence_source_artifact_id":recurrence_record["source_artifact_id"],
            "distance_occurrence_source_artifact_ids":sorted(set(lineage)),
            "occurrence_quality_flag":(
                "OK" if occurrence is not None else "SOURCE_NODATA_AT_ASSET"
            ),
            "recurrence_quality_flag":(
                "OK" if recurrence is not None else "SOURCE_NODATA_AT_ASSET"
            ),
            "distance_quality_flag":(
                "OK" if distance_m is not None
                else "NO_HIGH_OCCURRENCE_WATER_WITHIN_SEARCH_RADIUS"
            ),
        })
    return pd.DataFrame(rows)


def write_surface_water_parquet(
    root:str|Path,
    frame:pd.DataFrame,
    *,
    run_id:str,
)->Path:
    directory=parquet_partition_dir(
        root,layer="indicators",dataset="jrc_gsw15_surface_water_context",
        partitions={"period":"1984_2024"},
    )
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/f"surface-water-{run_id}.parquet"
    serial=frame.copy()
    serial["distance_occurrence_source_artifact_ids"]=serial[
        "distance_occurrence_source_artifact_ids"
    ].map(lambda x:";".join(x))
    serial.to_parquet(path,index=False)
    register_parquet_dataset(
        root,dataset_name="jrc_gsw15_surface_water_context",
        layer="indicators",parquet_path=path,
        partition_spec={"period":"1984_2024"},
        row_count=len(serial),run_id=run_id,
    )
    return path


def insert_surface_water_indicators(
    root:str|Path,
    frame:pd.DataFrame,
    *,
    run_id:str,
)->int:
    count=0
    with connect_catalog(root) as conn:
        for row in frame.to_dict(orient="records"):
            threshold=float(row["high_occurrence_threshold_pct"])
            search_radius=float(row["distance_search_radius_km"])
            threshold_token=(
                str(int(threshold))
                if threshold.is_integer()
                else str(threshold).replace(".","p")
            )
            radius_token=(
                str(int(search_radius))
                if search_radius.is_integer()
                else str(search_radius).replace(".","p")
            )
            specs=[
                (
                    "jrc_gsw15_occurrence_pct_at_site",
                    row["occurrence_pct_at_site"],"percent","SOURCE",
                    row["occurrence_quality_flag"],"JRC_GSW_OCCURRENCE",
                    [row["occurrence_source_artifact_id"]],
                    row["occurrence_source_artifact_id"],
                    "GSW15_POINT_0.1",
                ),
                (
                    "jrc_gsw15_recurrence_pct_at_site",
                    row["recurrence_pct_at_site"],"percent","SOURCE",
                    row["recurrence_quality_flag"],"JRC_GSW_RECURRENCE",
                    [row["recurrence_source_artifact_id"]],
                    row["recurrence_source_artifact_id"],
                    "GSW15_POINT_0.1",
                ),
                (
                    f"jrc_gsw15_distance_to_occurrence_ge{threshold_token}pct_water_m",
                    row["distance_to_high_occurrence_water_m"],"m","CALCULATED",
                    row["distance_quality_flag"],"JRC_GSW_OCCURRENCE",
                    row["distance_occurrence_source_artifact_ids"],
                    row["occurrence_source_artifact_id"],
                    f"GSW15_DISTANCE_OCC_GE{threshold_token}_{radius_token}KM_0.1",
                ),
            ]
            for (
                indicator_id,value,unit,value_class,quality,role,
                source_ids,primary,method_version
            ) in specs:
                value=None if value is None or pd.isna(value) else float(value)
                null_reason=None if value is not None else quality
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
                        value,None,unit,value_class,
                        (
                            "SATELLITE_OBSERVED"
                            if value_class=="SOURCE"
                            else "CALCULATED_FROM_SATELLITE_OBSERVED"
                        ),
                        primary,method_version,
                        "1984-01-01","2024-12-31",
                        quality,null_reason,run_id,utc_now(),
                    ),
                )
                for sid in source_ids:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO asset_indicator_source(
                            asset_indicator_id,source_artifact_id,source_role
                        ) VALUES(?,?,?)
                        """,(cur.lastrowid,sid,role)
                    )
                count+=1
        conn.commit()
    return count
