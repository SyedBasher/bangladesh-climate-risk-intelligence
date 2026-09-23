from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pandas as pd

from .local_store import (
    connect_catalog,
    register_source_file,
    sha256_file,
    source_snapshot_path,
    utc_now,
)
from .osm_local import haversine_m
from .local_assets import coarse_climate_assets

PROVIDER="Bangladesh Water Development Board / Flood Forecasting & Warning Centre"
MEASUREMENT_BASIS="CALCULATED_FROM_OFFICIAL_FFWC_STATION_OBSERVATIONS"


def _register_snapshot(
    root:str|Path,
    source_path:str|Path,
    *,
    source_kind:str,
    source_url:str,
    retrieved_at:str|None=None,
)->dict:
    root=Path(root).resolve()
    src=Path(source_path).resolve()
    if not src.exists():
        raise FileNotFoundError(src)
    digest=sha256_file(src)
    filename=f"ffwc_{source_kind.lower()}_{digest[:16]}{src.suffix.lower() or '.csv'}"
    dest=source_snapshot_path(
        root,"BWDB_FFWC",source_kind.upper(),"snapshot",digest,filename
    )
    dest.parent.mkdir(parents=True,exist_ok=True)
    if not dest.exists():
        shutil.copy2(src,dest)
    elif sha256_file(dest)!=digest:
        raise RuntimeError("FFWC content-addressed snapshot has unexpected bytes")
    return register_source_file(
        root,source_id=f"FFWC_{source_kind.upper()}_{digest[:16]}",
        provider=PROVIDER,provider_version="OFFICIAL_SNAPSHOT",
        artifact_path=dest,media_type="text/csv",
        retrieved_at=retrieved_at,retrieval_status="COMPLETE",
        note=(
            "Exact official FFWC/BWDB snapshot imported into the private local data plane. "
            "No undocumented web API endpoint is assumed."
        ),
        request_parameters={"source_url":source_url,"source_kind":source_kind},
    )


def import_station_snapshot(
    root:str|Path,
    csv_path:str|Path,
    *,
    source_url:str,
    retrieved_at:str|None=None,
)->dict:
    record=_register_snapshot(
        root,csv_path,source_kind="STATIONS",source_url=source_url,retrieved_at=retrieved_at
    )
    frame=pd.read_csv(csv_path)
    required={"station_id","station_name","latitude","longitude"}
    if not required.issubset(frame.columns):
        raise ValueError(f"FFWC station snapshot missing {sorted(required-set(frame.columns))}")
    inserted=0
    with connect_catalog(root) as conn:
        for row in frame.to_dict(orient="records"):
            lat=float(row["latitude"]); lon=float(row["longitude"])
            if not (-90<=lat<=90 and -180<=lon<=180):
                raise ValueError(f"Invalid FFWC station coordinate for {row['station_id']}")
            danger=row.get("danger_level_m")
            danger=None if pd.isna(danger) else float(danger)
            metadata={
                k:v for k,v in row.items()
                if k not in {"station_id","station_name","river_name","latitude","longitude","danger_level_m"}
                and not pd.isna(v)
            }
            conn.execute(
                """
                INSERT INTO hydro_station(
                    station_id,provider,station_name,river_name,latitude,longitude,
                    danger_level_m,source_artifact_id,metadata_json,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(station_id) DO UPDATE SET
                    provider=excluded.provider,station_name=excluded.station_name,
                    river_name=excluded.river_name,latitude=excluded.latitude,
                    longitude=excluded.longitude,danger_level_m=excluded.danger_level_m,
                    source_artifact_id=excluded.source_artifact_id,
                    metadata_json=excluded.metadata_json,updated_at=excluded.updated_at
                """,
                (
                    str(row["station_id"]),PROVIDER,str(row["station_name"]),
                    None if pd.isna(row.get("river_name")) else str(row.get("river_name")),
                    lat,lon,danger,record["source_artifact_id"],
                    json.dumps(metadata,sort_keys=True),utc_now(),
                ),
            )
            inserted+=1
        conn.commit()
    return {"source":record,"rows":inserted}


def import_observation_snapshot(
    root:str|Path,
    csv_path:str|Path,
    *,
    source_url:str,
    retrieved_at:str|None=None,
)->dict:
    record=_register_snapshot(
        root,csv_path,source_kind="OBSERVATIONS",source_url=source_url,retrieved_at=retrieved_at
    )
    frame=pd.read_csv(csv_path)
    required={"station_id","observed_at","water_level_m"}
    if not required.issubset(frame.columns):
        raise ValueError(f"FFWC observation snapshot missing {sorted(required-set(frame.columns))}")
    inserted=0
    with connect_catalog(root) as conn:
        known={x[0] for x in conn.execute("SELECT station_id FROM hydro_station").fetchall()}
        for row in frame.to_dict(orient="records"):
            sid=str(row["station_id"])
            if sid not in known:
                raise ValueError(f"Unknown FFWC station_id {sid}; import stations first")
            water=float(row["water_level_m"])
            danger=row.get("danger_level_m")
            danger=None if pd.isna(danger) else float(danger)
            conn.execute(
                """
                INSERT OR IGNORE INTO hydro_observation(
                    provider,station_id,observed_at,water_level_m,danger_level_m,
                    source_artifact_id,quality_flag
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    PROVIDER,sid,str(row["observed_at"]),water,danger,
                    record["source_artifact_id"],"OFFICIAL_SOURCE",
                ),
            )
            inserted+=1
        conn.commit()
    return {"source":record,"rows_processed":inserted}


def link_assets_to_stations(
    root:str|Path,
    *,
    tenant_key:str|None=None,
    top_k:int=3,
)->int:
    if top_k<1:
        raise ValueError("top_k must be >=1")
    assets=coarse_climate_assets(root,tenant_key=tenant_key)
    with connect_catalog(root) as conn:
        stations=[dict(x) for x in conn.execute(
            "SELECT station_id,latitude,longitude FROM hydro_station"
        ).fetchall()]
        count=0
        for asset in assets:
            ranked=sorted(
                (
                    (
                        haversine_m(
                            float(asset["latitude"]),float(asset["longitude"]),
                            float(s["latitude"]),float(s["longitude"])
                        )/1000.0,
                        s["station_id"],
                    )
                    for s in stations
                ),
                key=lambda x:x[0],
            )[:top_k]
            for rank,(distance,sid) in enumerate(ranked,start=1):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO asset_hydro_station_link(
                        asset_location_id,station_id,distance_km,rank_order,
                        method_version,created_at
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    (
                        asset["asset_location_id"],sid,float(distance),rank,
                        "NEAREST_GAUGE_HAVERSINE_0.1",utc_now(),
                    ),
                )
                count+=1
        conn.commit()
    return count


def ffwc_event_context(
    root:str|Path,
    *,
    start:str,
    end:str,
    rank_order:int=1,
)->pd.DataFrame:
    with connect_catalog(root) as conn:
        rows=conn.execute(
            """
            SELECT a.tenant_key,a.asset_location_id,a.external_id,
                   l.station_id,l.distance_km,s.station_name,s.river_name,
                   s.danger_level_m AS station_danger_level_m,
                   o.observed_at,o.water_level_m,o.danger_level_m,
                   o.source_artifact_id
            FROM asset_hydro_station_link l
            JOIN asset_location a ON a.asset_location_id=l.asset_location_id
            JOIN hydro_station s ON s.station_id=l.station_id
            LEFT JOIN hydro_observation o
              ON o.station_id=l.station_id
             AND o.observed_at>=? AND o.observed_at<=?
            WHERE l.rank_order=?
            ORDER BY a.asset_location_id,o.observed_at
            """,(start,end,rank_order)
        ).fetchall()
    frame=pd.DataFrame([dict(x) for x in rows])
    if frame.empty:
        return frame
    out=[]
    for asset_id,g in frame.groupby("asset_location_id"):
        first=g.iloc[0]
        obs=g[g["observed_at"].notna()].copy()
        if obs.empty:
            out.append({
                "tenant_key":first["tenant_key"],"asset_location_id":asset_id,
                "external_id":first["external_id"],"station_id":first["station_id"],
                "station_name":first["station_name"],"river_name":first["river_name"],
                "station_distance_km":float(first["distance_km"]),
                "observation_count":0,"max_water_level_m":None,
                "max_above_danger_m":None,"quality_flag":"NO_OBSERVATIONS_IN_WINDOW",
                "source_artifact_ids":[],
            })
            continue
        levels=obs["water_level_m"].astype(float)
        above=[]
        for r in obs.to_dict(orient="records"):
            danger=r["danger_level_m"]
            if pd.isna(danger):
                danger=r["station_danger_level_m"]
            if not pd.isna(danger):
                above.append(float(r["water_level_m"])-float(danger))
        out.append({
            "tenant_key":first["tenant_key"],"asset_location_id":asset_id,
            "external_id":first["external_id"],"station_id":first["station_id"],
            "station_name":first["station_name"],"river_name":first["river_name"],
            "station_distance_km":float(first["distance_km"]),
            "observation_count":int(len(obs)),
            "max_water_level_m":float(levels.max()),
            "max_above_danger_m":None if not above else float(max(above)),
            "quality_flag":"OFFICIAL_STATION_CONTEXT",
            "source_artifact_ids":sorted(set(obs["source_artifact_id"].dropna().astype(str))),
        })
    return pd.DataFrame(out)


def insert_ffwc_context_indicators(
    root:str|Path,
    summary:pd.DataFrame,
    *,
    start:str,
    end:str,
    run_id:str,
)->int:
    specs=[
        ("ffwc_nearest_station_distance_km","station_distance_km","km"),
        ("ffwc_nearest_station_observation_count","observation_count","count"),
        ("ffwc_nearest_station_max_water_level_m","max_water_level_m","m"),
        ("ffwc_nearest_station_max_above_danger_m","max_above_danger_m","m"),
    ]
    n=0
    with connect_catalog(root) as conn:
        for row in summary.to_dict(orient="records"):
            for indicator_id,field,unit in specs:
                val=row[field]
                if pd.isna(val):
                    val=None
                null_reason=None if val is not None else (
                    "NO_OBSERVATIONS_IN_WINDOW" if row["observation_count"]==0
                    else "DANGER_LEVEL_UNAVAILABLE"
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
                        row["tenant_key"],row["asset_location_id"],indicator_id,
                        None if val is None else float(val),None,unit,"CALCULATED",
                        MEASUREMENT_BASIS,None,"FFWC_STATION_CONTEXT_0.1",
                        start,end,row["quality_flag"],null_reason,run_id,utc_now(),
                    ),
                )
                for sid in row["source_artifact_ids"]:
                    conn.execute(
                        """
                        INSERT INTO asset_indicator_source(
                            asset_indicator_id,source_artifact_id,source_role
                        ) VALUES(?,?,?)
                        """,(cur.lastrowid,sid,"FFWC_WATER_LEVEL")
                    )
                n+=1
        conn.commit()
    return n
