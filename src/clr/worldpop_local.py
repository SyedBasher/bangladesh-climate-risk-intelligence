from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path

import pandas as pd
import requests
from pyproj import Geod

from .local_store import (
    connect_catalog,
    parquet_partition_dir,
    register_parquet_dataset,
    register_source_file,
    sha256_file,
    source_snapshot_path,
    utc_now,
)

API_ROOT="https://api.worldpop.org/v2"
PROVIDER="WorldPop, University of Southampton"
PROVIDER_VERSION="Global2_R2025A_v1"
DATA_YEAR_DEFAULT=2025
RESOLUTION="100m"
RADII_KM=(1.0,5.0,10.0)
MEASUREMENT_BASIS="CALCULATED_FROM_MODELLED_POPULATION"
GEOD=Geod(ellps="WGS84")


def geodesic_circle(lon:float,lat:float,radius_km:float,vertices:int=96)->dict:
    if radius_km<=0:
        raise ValueError("radius_km must be positive")
    if vertices<24:
        raise ValueError("vertices must be >=24")
    coords=[]
    distance_m=float(radius_km)*1000.0
    for i in range(vertices):
        az=360.0*i/vertices
        x,y,_=GEOD.fwd(float(lon),float(lat),az,distance_m)
        coords.append([float(x),float(y)])
    coords.append(coords[0])
    return {"type":"Polygon","coordinates":[coords]}


def _query_key(asset:dict,year:int,radius_km:float)->str:
    payload={
        "asset_location_id":str(asset["asset_location_id"]),
        "latitude":round(float(asset["latitude"]),8),
        "longitude":round(float(asset["longitude"]),8),
        "year":int(year),"resolution":RESOLUTION,
        "radius_km":float(radius_km),
    }
    digest=hashlib.sha256(
        json.dumps(payload,sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()
    return digest[:24]


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
            return dict(row),json.loads(p.read_text(encoding="utf-8"))
    return None,None


def _headers()->dict:
    h={"User-Agent":"Mangrove-Climate-Risk/0.1"}
    api_key=os.getenv("WORLDPOP_API_KEY")
    if api_key:
        h["X-API-Key"]=api_key
    return h


def query_population(
    asset:dict,
    *,
    year:int,
    radius_km:float,
    session=None,
    poll_seconds:float=1.0,
    timeout_seconds:float=180.0,
)->dict:
    s=session or requests.Session()
    payload={
        "geojson":geodesic_circle(
            float(asset["longitude"]),float(asset["latitude"]),float(radius_km)
        ),
        "year":int(year),
        "resolution":RESOLUTION,
    }
    response=s.post(
        f"{API_ROOT}/population",
        json=payload,headers=_headers(),timeout=60
    )
    response.raise_for_status()
    created=response.json()
    task_id=created.get("task_id") or created.get("taskid")
    if not task_id:
        raise RuntimeError(f"WorldPop task response missing task_id: {created}")

    started=time.monotonic()
    final=None
    while True:
        if time.monotonic()-started>timeout_seconds:
            raise TimeoutError(f"WorldPop task {task_id} exceeded timeout")
        status=s.get(
            f"{API_ROOT}/tasks/{task_id}",
            headers=_headers(),timeout=60
        )
        status.raise_for_status()
        final=status.json()
        state=str(final.get("status","")).lower()
        if state in {"success","finished"}:
            break
        if state in {"failure","failed","error"}:
            raise RuntimeError(f"WorldPop task failed: {final}")
        time.sleep(poll_seconds)

    result=final.get("result") or final.get("data")
    if not isinstance(result,dict):
        raise RuntimeError(f"WorldPop task missing result object: {final}")
    total=result.get("total_population")
    area=result.get("area_km2")
    density=result.get("population_density")
    if total is None:
        raise RuntimeError(f"WorldPop result missing total_population: {result}")
    if area is None:
        area=math.pi*float(radius_km)**2
    if density is None and float(area)>0:
        density=float(total)/float(area)

    return {
        "request":{
            "asset_location_id":asset["asset_location_id"],
            "external_system":asset["external_system"],
            "external_id":asset["external_id"],
            "latitude":float(asset["latitude"]),
            "longitude":float(asset["longitude"]),
            "radius_km":float(radius_km),
            "year":int(year),
            "resolution":RESOLUTION,
            "geojson":payload["geojson"],
        },
        "provider_task_id":task_id,
        "provider_response":final,
        "normalized_result":{
            "total_population":float(total),
            "area_km2":float(area),
            "population_density_per_km2":float(density),
            "data_year":int(result.get("data_year",year)),
            "data_source":str(result.get("data_source") or "WorldPop Global 2 Population Data"),
        },
    }


def ensure_population_query(
    root:str|Path,
    asset:dict,
    *,
    year:int=DATA_YEAR_DEFAULT,
    radius_km:float,
    session=None,
)->tuple[dict,dict]:
    root=Path(root).resolve()
    key=_query_key(asset,year,radius_km)
    source_id=f"WORLDPOP_G2_{int(year)}_{str(radius_km).replace('.','p')}KM_{key}"
    record,payload=_verified_source(root,source_id)
    if record is not None:
        return record,payload

    payload=query_population(
        asset,year=year,radius_km=radius_km,session=session
    )
    tmp=root/"tmp"/f"{source_id}.json"
    tmp.parent.mkdir(parents=True,exist_ok=True)
    tmp.write_text(
        json.dumps(payload,sort_keys=True,indent=2)+"\n",
        encoding="utf-8",
    )
    digest=sha256_file(tmp)
    dest=source_snapshot_path(
        root,"WORLDPOP","GLOBAL2_POPULATION",PROVIDER_VERSION,
        digest,tmp.name,
    )
    dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists():
        if sha256_file(dest)!=digest:
            raise RuntimeError("Content-addressed WorldPop snapshot has unexpected bytes")
        tmp.unlink()
    else:
        tmp.replace(dest)

    record=register_source_file(
        root,
        source_id=source_id,provider=PROVIDER,
        provider_version=PROVIDER_VERSION,
        artifact_path=dest,media_type="application/json",
        valid_time_start=f"{int(year)}-01-01",
        valid_time_end=f"{int(year)}-12-31",
        retrieval_status="COMPLETE",
        note=(
            "Official WorldPop API v2 population total for a geodesic circular buffer. "
            "This is surrounding population context, not factory workforce or employees."
        ),
        request_parameters={
            "api_root":API_ROOT,
            "year":int(year),"resolution":RESOLUTION,
            "radius_km":float(radius_km),
            "query_key":key,
        },
    )
    return record,payload


def build_population_context(
    root:str|Path,
    assets:list[dict],
    *,
    year:int=DATA_YEAR_DEFAULT,
    radii_km:tuple[float,...]=RADII_KM,
    session=None,
)->pd.DataFrame:
    if not assets:
        raise ValueError("No assets supplied")
    radii=tuple(float(x) for x in radii_km)
    if len(set(radii))!=len(radii) or any(x<=0 for x in radii):
        raise ValueError("radii_km must contain unique positive values")

    rows=[]
    for asset in assets:
        for radius in radii:
            record,payload=ensure_population_query(
                root,asset,year=year,radius_km=radius,session=session
            )
            result=payload["normalized_result"]
            rows.append({
                "tenant_key":asset["tenant_key"],
                "asset_location_id":asset["asset_location_id"],
                "external_system":asset["external_system"],
                "external_id":asset["external_id"],
                "site_identity_grade":asset["site_identity_grade"],
                "data_year":int(result["data_year"]),
                "radius_km":float(radius),
                "population_total":float(result["total_population"]),
                "population_density_per_km2":float(result["population_density_per_km2"]),
                "provider_area_km2":float(result["area_km2"]),
                "source_artifact_id":record["source_artifact_id"],
                "quality_flag":"WORLDPOP_PROVIDER_RESULT",
            })
    return pd.DataFrame(rows)


def write_population_parquet(
    root:str|Path,
    frame:pd.DataFrame,
    *,
    year:int,
    run_id:str,
)->Path:
    directory=parquet_partition_dir(
        root,layer="indicators",dataset="worldpop_population_context",
        partitions={"year":int(year),"resolution":"100m"},
    )
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/f"population-context-{run_id}.parquet"
    frame.to_parquet(path,index=False)
    register_parquet_dataset(
        root,dataset_name="worldpop_population_context",layer="indicators",
        parquet_path=path,
        partition_spec={"year":int(year),"resolution":"100m"},
        row_count=len(frame),run_id=run_id,
    )
    return path


def _radius_token(radius:float)->str:
    return str(int(radius)) if float(radius).is_integer() else str(radius).replace(".","p")


def insert_population_indicators(
    root:str|Path,
    frame:pd.DataFrame,
    *,
    run_id:str,
)->int:
    count=0
    with connect_catalog(root) as conn:
        for row in frame.to_dict(orient="records"):
            token=_radius_token(float(row["radius_km"]))
            specs=[
                (
                    f"worldpop_population_within_{token}km",
                    float(row["population_total"]),"people"
                ),
                (
                    f"worldpop_population_density_within_{token}km",
                    float(row["population_density_per_km2"]),"people/km2"
                ),
            ]
            for indicator_id,value,unit in specs:
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
                        value,None,unit,"CALCULATED",MEASUREMENT_BASIS,
                        row["source_artifact_id"],"WORLDPOP_API_RADIUS_0.1",
                        f"{int(row['data_year'])}-01-01",
                        f"{int(row['data_year'])}-12-31",
                        row["quality_flag"],None,run_id,utc_now(),
                    ),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO asset_indicator_source(
                        asset_indicator_id,source_artifact_id,source_role
                    ) VALUES(?,?,?)
                    """,
                    (
                        cur.lastrowid,row["source_artifact_id"],
                        "WORLDPOP_POPULATION",
                    ),
                )
                count+=1
        conn.commit()
    return count
