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

PROVIDER="ESA WorldCover consortium"
PROVIDER_VERSION="WorldCover_2021_v200"
BASE_URL="https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"
RADII_M=(250.0,1000.0)
GEOD=Geod(ellps="WGS84")

CLASS_LABELS={
    10:"tree_cover",
    20:"shrubland",
    30:"grassland",
    40:"cropland",
    50:"built_up",
    60:"bare_sparse_vegetation",
    70:"snow_ice",
    80:"permanent_water_bodies",
    90:"herbaceous_wetland",
    95:"mangroves",
    100:"moss_lichen",
}
VALID_CODES=set(CLASS_LABELS)


def _token(value:int,positive:str,negative:str,width:int)->str:
    return f"{positive if value>=0 else negative}{abs(int(value)):0{width}d}"


def tile_id_for_point(lat:float,lon:float)->str:
    if not (-90<=float(lat)<=90 and -180<=float(lon)<=180):
        raise ValueError("Invalid coordinate")
    if float(lon)==180:
        lon=179.999999999
    if float(lat)==90:
        lat=89.999999999
    lat0=math.floor(float(lat)/3.0)*3
    lon0=math.floor(float(lon)/3.0)*3
    return f"{_token(lat0,'N','S',2)}{_token(lon0,'E','W',3)}"


def tile_filename(tile_id:str)->str:
    return f"ESA_WorldCover_10m_2021_v200_{tile_id}_Map.tif"


def tile_url(tile_id:str)->str:
    return f"{BASE_URL}/{tile_filename(tile_id)}"


def _bbox_for_asset(lat:float,lon:float,radius_m:float):
    radius_km=float(radius_m)/1000.0
    lat_margin=radius_km/110.574
    cos=max(0.05,math.cos(math.radians(float(lat))))
    lon_margin=radius_km/(111.320*cos)
    return (
        float(lon)-lon_margin,float(lat)-lat_margin,
        float(lon)+lon_margin,float(lat)+lat_margin,
    )


def tiles_for_bbox(bounds)->list[str]:
    west,south,east,north=map(float,bounds)
    if west<-180 or east>180:
        raise ValueError("Antimeridian-crossing WorldCover searches are not supported")
    south=max(-89.999999,south)
    north=min(89.999999,north)
    lon_starts=range(
        math.floor(west/3.0)*3,
        math.floor((east-1e-12)/3.0)*3+1,
        3,
    )
    lat_starts=range(
        math.floor(south/3.0)*3,
        math.floor((north-1e-12)/3.0)*3+1,
        3,
    )
    return [
        f"{_token(lat0,'N','S',2)}{_token(lon0,'E','W',3)}"
        for lat0 in lat_starts for lon0 in lon_starts
    ]


def required_tiles(
    assets:list[dict],
    *,
    max_radius_m:float=max(RADII_M),
)->list[str]:
    tiles=set()
    for asset in assets:
        tiles.update(tiles_for_bbox(_bbox_for_asset(
            float(asset["latitude"]),float(asset["longitude"]),
            float(max_radius_m),
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
        raise RuntimeError(f"Empty WorldCover download: {url}")
    part.replace(target)
    return {
        "etag":response.headers.get("ETag"),
        "last_modified":response.headers.get("Last-Modified"),
        "content_length":response.headers.get("Content-Length"),
    }


def ensure_tile(
    root:str|Path,
    tile_id:str,
    *,
    session=None,
)->dict:
    root=Path(root).resolve()
    source_id=f"ESA_WORLDCOVER2021_{tile_id}"
    cached=_verified_source(root,source_id)
    if cached is not None:
        return cached

    url=tile_url(tile_id)
    filename=tile_filename(tile_id)
    tmp=root/"tmp"/filename
    tmp.unlink(missing_ok=True)
    headers=_download(url,tmp,session=session)
    digest=sha256_file(tmp)
    dest=source_snapshot_path(
        root,"ESA_WORLDCOVER","MAP",PROVIDER_VERSION,
        digest,filename,
    )
    dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists():
        if sha256_file(dest)!=digest:
            raise RuntimeError("Content-addressed WorldCover tile has unexpected bytes")
        tmp.unlink()
    else:
        shutil.move(str(tmp),str(dest))

    with rasterio.open(dest) as ds:
        if ds.count!=1 or ds.crs is None:
            raise ValueError(f"Unexpected WorldCover raster structure: {filename}")
        if str(ds.crs).upper()!="EPSG:4326":
            raise ValueError(f"WorldCover tile must be EPSG:4326: {filename}")
        px=abs(float(ds.transform.a)); py=abs(float(ds.transform.e))
        if not (0.00007<=px<=0.00010 and 0.00007<=py<=0.00010):
            raise ValueError(f"Unexpected WorldCover 10m pixel size: {px},{py}")

    return register_source_file(
        root,source_id=source_id,provider=PROVIDER,
        provider_version=PROVIDER_VERSION,
        artifact_path=dest,media_type="image/tiff",
        valid_time_start="2021-01-01",valid_time_end="2021-12-31",
        retrieval_status="COMPLETE",
        note=(
            "ESA WorldCover 2021 v200 10m land-cover map tile. "
            "Land-cover classes are contextual and do not establish zoning, "
            "land-use permission, ownership or property value."
        ),
        request_parameters={
            "source_url":url,"tile_id":tile_id,
            "year":2021,"version":"v200",
            "license":"CC BY 4.0",
            "attribution":(
                "© ESA WorldCover project 2021 / Contains modified Copernicus "
                "Sentinel data (2021) processed by ESA WorldCover consortium"
            ),
            "http_etag":headers.get("etag"),
            "http_last_modified":headers.get("last_modified"),
            "http_content_length":headers.get("content_length"),
        },
    )


def ensure_required_tiles(
    root:str|Path,
    assets:list[dict],
    *,
    max_radius_m:float=max(RADII_M),
    session=None,
)->dict[str,dict]:
    return {
        tile:ensure_tile(root,tile,session=session)
        for tile in required_tiles(assets,max_radius_m=max_radius_m)
    }


def _sample_point(path:Path,lat:float,lon:float):
    with rasterio.open(path) as ds:
        arr=next(ds.sample([(float(lon),float(lat))],masked=True))
        try:
            if bool(arr.mask[0]):
                return None
        except Exception:
            pass
        value=int(arr[0])
        return value if value in VALID_CODES else None


def _class_counts_in_radius(
    path:Path,
    lat:float,
    lon:float,
    radius_m:float,
):
    west,south,east,north=_bbox_for_asset(lat,lon,radius_m)
    with rasterio.open(path) as ds:
        if not (
            ds.bounds.left<east and ds.bounds.right>west
            and ds.bounds.bottom<north and ds.bounds.top>south
        ):
            return {},0,0
        raw=from_bounds(west,south,east,north,transform=ds.transform)
        full=Window(0,0,ds.width,ds.height)
        try:
            window=raw.intersection(full).round_offsets().round_lengths()
        except Exception:
            return {},0,0
        if window.width<=0 or window.height<=0:
            return {},0,0
        arr=ds.read(1,window=window,masked=True)
        data=np.asarray(arr)
        transform=ds.window_transform(window)
        rr,cc=np.indices(data.shape)
        xs=transform.c+(cc.astype(float)+0.5)*transform.a
        ys=transform.f+(rr.astype(float)+0.5)*transform.e
        _,_,dist=GEOD.inv(
            np.full(data.size,float(lon)),
            np.full(data.size,float(lat)),
            xs.ravel(),ys.ravel(),
        )
        circle=np.asarray(dist,dtype=float).reshape(data.shape)<=float(radius_m)
        source_valid=~np.ma.getmaskarray(arr)
        selected=int(circle.sum())
        valid=circle & source_valid & np.isin(data,list(VALID_CODES))
        valid_count=int(valid.sum())
        counts={}
        if valid_count:
            values,frequency=np.unique(data[valid],return_counts=True)
            counts={int(v):int(n) for v,n in zip(values,frequency)}
        return counts,selected,valid_count


def build_land_context(
    root:str|Path,
    assets:list[dict],
    tile_records:dict[str,dict],
    *,
    radii_m:tuple[float,...]=RADII_M,
)->pd.DataFrame:
    if not assets:
        raise ValueError("No assets supplied")
    root=Path(root).resolve()
    rows=[]
    for asset in assets:
        lat=float(asset["latitude"]); lon=float(asset["longitude"])
        home=tile_id_for_point(lat,lon)
        if home not in tile_records:
            raise ValueError(f"Missing WorldCover home tile {home}")
        point_record=tile_records[home]
        point_code=_sample_point(
            root/point_record["local_path"],lat,lon
        )
        point_label=CLASS_LABELS.get(point_code)

        for radius_m in tuple(float(x) for x in radii_m):
            tiles=tiles_for_bbox(_bbox_for_asset(lat,lon,radius_m))
            total_counts={code:0 for code in VALID_CODES}
            selected=0; valid=0; lineage=[]
            for tile in tiles:
                if tile not in tile_records:
                    raise ValueError(f"Missing WorldCover radius tile {tile}")
                record=tile_records[tile]
                lineage.append(record["source_artifact_id"])
                counts,n_selected,n_valid=_class_counts_in_radius(
                    root/record["local_path"],lat,lon,radius_m
                )
                selected+=n_selected; valid+=n_valid
                for code,n in counts.items():
                    total_counts[code]+=n

            valid_share=None if selected==0 else valid/selected
            quality=(
                "NO_PIXELS_IN_RADIUS" if selected==0
                else "LOW_VALID_PIXEL_COVERAGE"
                if valid_share is None or valid_share<0.95
                else "OK"
            )
            row={
                "tenant_key":asset["tenant_key"],
                "asset_location_id":asset["asset_location_id"],
                "external_system":asset["external_system"],
                "external_id":asset["external_id"],
                "site_identity_grade":asset["site_identity_grade"],
                "point_class_code":point_code,
                "point_class_label":point_label,
                "point_source_artifact_id":point_record["source_artifact_id"],
                "radius_m":radius_m,
                "selected_pixel_count":selected,
                "valid_pixel_count":valid,
                "valid_pixel_share":valid_share,
                "quality_flag":quality,
                "source_artifact_ids":sorted(set(lineage)),
            }
            for code,label in CLASS_LABELS.items():
                row[f"class_{code}_{label}_share"]=(
                    None if quality!="OK" or valid==0
                    else total_counts[code]/valid
                )
            rows.append(row)
    return pd.DataFrame(rows)


def write_land_parquet(
    root:str|Path,
    frame:pd.DataFrame,
    *,
    run_id:str,
)->Path:
    directory=parquet_partition_dir(
        root,layer="indicators",dataset="worldcover2021_land_context",
        partitions={"year":2021,"version":"v200"},
    )
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/f"land-context-{run_id}.parquet"
    serial=frame.copy()
    serial["source_artifact_ids"]=serial[
        "source_artifact_ids"
    ].map(lambda x:";".join(x))
    serial.to_parquet(path,index=False)
    register_parquet_dataset(
        root,dataset_name="worldcover2021_land_context",
        layer="indicators",parquet_path=path,
        partition_spec={"year":2021,"version":"v200"},
        row_count=len(serial),run_id=run_id,
    )
    return path


def _radius_token(radius_m:float)->str:
    return str(int(radius_m)) if float(radius_m).is_integer() else str(radius_m).replace(".","p")


def insert_land_indicators(
    root:str|Path,
    frame:pd.DataFrame,
    *,
    run_id:str,
)->int:
    count=0
    point_done=set()
    with connect_catalog(root) as conn:
        for row in frame.to_dict(orient="records"):
            asset_id=row["asset_location_id"]
            if asset_id not in point_done:
                code=row["point_class_code"]
                label=row["point_class_label"]
                for indicator_id,value_numeric,value_text,unit in (
                    (
                        "worldcover2021_class_code_at_site",
                        None if code is None else float(code),None,
                        "class_code",
                    ),
                    (
                        "worldcover2021_class_label_at_site",
                        None,label,None,
                    ),
                ):
                    null_reason=None if (
                        value_numeric is not None or value_text is not None
                    ) else "SOURCE_NODATA_AT_ASSET"
                    cur=conn.execute(
                        """
                        INSERT INTO asset_indicator(
                            tenant_key,asset_location_id,indicator_id,value_numeric,value_text,
                            unit,value_class,measurement_basis,source_artifact_id,method_version,
                            period_start,period_end,quality_flag,null_reason,run_id,calculated_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            row["tenant_key"],asset_id,indicator_id,
                            value_numeric,value_text,unit,"SOURCE",
                            "SATELLITE_OBSERVED",
                            row["point_source_artifact_id"],
                            "WORLDCOVER2021_POINT_0.1",
                            "2021-01-01","2021-12-31",
                            "OK" if null_reason is None else "SOURCE_NODATA_AT_ASSET",
                            null_reason,run_id,utc_now(),
                        ),
                    )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO asset_indicator_source(
                            asset_indicator_id,source_artifact_id,source_role
                        ) VALUES(?,?,?)
                        """,
                        (
                            cur.lastrowid,row["point_source_artifact_id"],
                            "ESA_WORLDCOVER",
                        ),
                    )
                    count+=1
                point_done.add(asset_id)

            token=_radius_token(float(row["radius_m"]))
            valid_share=row["valid_pixel_share"]
            specs=[
                (
                    f"worldcover2021_valid_pixel_share_within_{token}m",
                    valid_share,"share"
                )
            ]
            for code,label in CLASS_LABELS.items():
                specs.append((
                    f"worldcover2021_{label}_share_within_{token}m",
                    row[f"class_{code}_{label}_share"],"share"
                ))
            for indicator_id,value,unit in specs:
                value=None if value is None or pd.isna(value) else float(value)
                null_reason=None if value is not None else row["quality_flag"]
                primary=(
                    row["source_artifact_ids"][0]
                    if row["source_artifact_ids"] else None
                )
                cur=conn.execute(
                    """
                    INSERT INTO asset_indicator(
                        tenant_key,asset_location_id,indicator_id,value_numeric,value_text,
                        unit,value_class,measurement_basis,source_artifact_id,method_version,
                        period_start,period_end,quality_flag,null_reason,run_id,calculated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        row["tenant_key"],asset_id,indicator_id,
                        value,None,unit,"CALCULATED",
                        "CALCULATED_FROM_SATELLITE_OBSERVED",
                        primary,"WORLDCOVER2021_RADIUS_PIXEL_SHARE_0.1",
                        "2021-01-01","2021-12-31",
                        row["quality_flag"],null_reason,run_id,utc_now(),
                    ),
                )
                for sid in row["source_artifact_ids"]:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO asset_indicator_source(
                            asset_indicator_id,source_artifact_id,source_role
                        ) VALUES(?,?,?)
                        """,(cur.lastrowid,sid,"ESA_WORLDCOVER")
                    )
                count+=1
        conn.commit()
    return count
