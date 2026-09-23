from __future__ import annotations

import hashlib
import json
import math
import shutil
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

import networkx as nx
import numpy as np
import pandas as pd

from .local_store import (
    connect_catalog,
    parquet_partition_dir,
    register_parquet_dataset,
    register_source_file,
    sha256_file,
    source_snapshot_path,
    utc_now,
)

GEOFABRIK_PBF_URL = "https://download.geofabrik.de/asia/bangladesh-260919.osm.pbf"
GEOFABRIK_MD5_URL = GEOFABRIK_PBF_URL + ".md5"
GEOFABRIK_SOURCE_PAGE = "https://download.geofabrik.de/asia/bangladesh.html"
PBF_FILENAME = "bangladesh-260919.osm.pbf"
PBF_VINTAGE = "2026-09-19"
OSM_DATA_TIMESTAMP = "2026-09-19T20:22:34Z"
SOURCE_ID = "OSM_GEOFABRIK_BANGLADESH_260919"
PROVIDER = "Geofabrik / OpenStreetMap contributors"
PROVIDER_VERSION = "bangladesh-260919"
OSM_ATTRIBUTION = "© OpenStreetMap contributors"
OSM_LICENSE = "Open Database License (ODbL) 1.0"

DRIVABLE_HIGHWAYS = {
    "motorway","motorway_link","trunk","trunk_link",
    "primary","primary_link","secondary","secondary_link",
    "tertiary","tertiary_link","unclassified","residential",
    "service","living_street","road",
}
PROHIBITED_ACCESS = {"no","private"}
TRUE_VALUES = {"yes","1","true"}
REVERSE_VALUES = {"-1","reverse"}


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2-lat1)
    dlambda = math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlambda/2)**2
    return 2*r*math.asin(min(1.0, math.sqrt(a)))


def _download(url: str, target: Path, timeout: int = 300) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    if part.exists():
        part.unlink()
    req = Request(url, headers={"User-Agent":"Mangrove-Climate-Risk/0.1"})
    try:
        with urlopen(req, timeout=timeout) as response, open(part,"wb") as f:
            while True:
                chunk=response.read(1024*1024)
                if not chunk:
                    break
                f.write(chunk)
        if not part.exists() or part.stat().st_size == 0:
            raise RuntimeError(f"Downloaded empty artifact: {url}")
        part.replace(target)
    except Exception:
        if part.exists():
            part.unlink()
        raise


def _md5_file(path: Path) -> str:
    h=hashlib.md5()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch_expected_md5(timeout: int = 60) -> str:
    req=Request(GEOFABRIK_MD5_URL, headers={"User-Agent":"Mangrove-Climate-Risk/0.1"})
    with urlopen(req, timeout=timeout) as response:
        text=response.read().decode("utf-8","replace").strip()
    token=text.split()[0].lower()
    if len(token)!=32 or any(c not in "0123456789abcdef" for c in token):
        raise ValueError("Unexpected Geofabrik MD5 response")
    return token


def ensure_pinned_pbf(root: str | Path) -> dict:
    root=Path(root).resolve()
    with connect_catalog(root) as conn:
        rows=conn.execute(
            """
            SELECT * FROM source_artifact
            WHERE source_id=? AND provider_version=? AND retrieval_status='COMPLETE'
            ORDER BY retrieved_at DESC
            """,
            (SOURCE_ID,PROVIDER_VERSION),
        ).fetchall()
    for row in rows:
        path=root/row["local_path"]
        if path.exists() and sha256_file(path)==row["sha256"]:
            return dict(row)

    tmp=root/"tmp"/PBF_FILENAME
    if tmp.exists():
        tmp.unlink()
    _download(GEOFABRIK_PBF_URL,tmp)
    expected_md5=_fetch_expected_md5()
    actual_md5=_md5_file(tmp)
    if actual_md5 != expected_md5:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"Geofabrik MD5 mismatch: expected {expected_md5}, got {actual_md5}"
        )

    digest=sha256_file(tmp)
    destination=source_snapshot_path(
        root,"GEOFABRIK","OSM_BANGLADESH",PROVIDER_VERSION,digest,PBF_FILENAME
    )
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        if sha256_file(destination)!=digest:
            raise RuntimeError("Content-addressed OSM PBF has unexpected bytes")
        tmp.unlink()
    else:
        shutil.move(str(tmp),str(destination))

    return register_source_file(
        root,
        source_id=SOURCE_ID,
        provider=PROVIDER,
        provider_version=PROVIDER_VERSION,
        artifact_path=destination,
        media_type="application/vnd.openstreetmap.data+pbf",
        valid_time_end=OSM_DATA_TIMESTAMP,
        retrieval_status="COMPLETE",
        note=(
            "Pinned Geofabrik Bangladesh OSM extract. Network-derived databases must "
            "retain OSM attribution and be handled separately from proprietary customer data."
        ),
        request_parameters={
            "download_url":GEOFABRIK_PBF_URL,
            "md5_url":GEOFABRIK_MD5_URL,
            "publisher_md5":expected_md5,
            "source_page":GEOFABRIK_SOURCE_PAGE,
            "osm_data_timestamp":OSM_DATA_TIMESTAMP,
            "attribution":OSM_ATTRIBUTION,
            "license":OSM_LICENSE,
        },
    )


def _direction(tags: dict) -> str:
    oneway=str(tags.get("oneway","")).strip().lower()
    if oneway in REVERSE_VALUES:
        return "REVERSE"
    if oneway in TRUE_VALUES:
        return "FORWARD"
    if oneway=="no":
        return "BOTH"
    if str(tags.get("junction","")).lower()=="roundabout":
        return "FORWARD"
    if str(tags.get("highway","")).lower()=="motorway":
        return "FORWARD"
    return "BOTH"


def _allowed(tags: dict) -> bool:
    highway=str(tags.get("highway","")).strip().lower()
    route=str(tags.get("route","")).strip().lower()
    if highway not in DRIVABLE_HIGHWAYS and route!="ferry":
        return False
    for key in ("access","vehicle","motor_vehicle"):
        if str(tags.get(key,"")).strip().lower() in PROHIBITED_ACCESS:
            return False
    if str(tags.get("construction","")).strip():
        return False
    return True


def parse_pbf_to_parquet(
    root: str | Path,
    pbf_record: dict,
    *,
    run_id: str,
    batch_size: int = 100000,
) -> tuple[Path,Path,dict]:
    try:
        import osmium
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as e:
        raise RuntimeError(
            "OSM parsing requires local dependencies. Install requirements-local.txt."
        ) from e

    root=Path(root).resolve()
    pbf_path=root/pbf_record["local_path"]
    outdir=parquet_partition_dir(
        root,layer="normalized",dataset="osm_road_network",
        partitions={"vintage":PROVIDER_VERSION},
    )
    outdir.mkdir(parents=True,exist_ok=True)
    edge_path=outdir/f"edges-{run_id}.parquet"
    node_path=outdir/f"nodes-{run_id}.parquet"

    edge_schema=pa.schema([
        ("osm_way_id",pa.int64()),("u",pa.int64()),("v",pa.int64()),
        ("from_lat",pa.float64()),("from_lon",pa.float64()),
        ("to_lat",pa.float64()),("to_lon",pa.float64()),
        ("length_m",pa.float64()),("road_class",pa.string()),
        ("name",pa.string()),("ref",pa.string()),("oneway_mode",pa.string()),
        ("bridge",pa.bool_()),("tunnel",pa.bool_()),("ferry",pa.bool_()),
        ("maxspeed",pa.string()),
    ])
    writer=pq.ParquetWriter(edge_path,edge_schema,compression="zstd")
    nodes={}
    rows=[]
    stats={"ways_seen":0,"ways_used":0,"directed_edges":0}

    def flush():
        nonlocal rows
        if not rows:
            return
        table=pa.Table.from_pylist(rows,schema=edge_schema)
        writer.write_table(table)
        rows=[]

    class Handler(osmium.SimpleHandler):
        def way(self,w):
            stats["ways_seen"]+=1
            tags={k:v for k,v in w.tags}
            if not _allowed(tags):
                return
            locs=[]
            for n in w.nodes:
                if not n.location.valid():
                    return
                locs.append((int(n.ref),float(n.location.lat),float(n.location.lon)))
            if len(locs)<2:
                return
            stats["ways_used"]+=1
            direction=_direction(tags)
            ferry=str(tags.get("route","")).lower()=="ferry"
            road_class="ferry" if ferry else str(tags.get("highway","")).lower()
            common={
                "osm_way_id":int(w.id),
                "road_class":road_class,
                "name":tags.get("name"),
                "ref":tags.get("ref"),
                "oneway_mode":direction,
                "bridge":str(tags.get("bridge","")).lower() in TRUE_VALUES,
                "tunnel":str(tags.get("tunnel","")).lower() in TRUE_VALUES,
                "ferry":ferry,
                "maxspeed":tags.get("maxspeed"),
            }
            for node_id,lat,lon in locs:
                nodes[node_id]=(lat,lon)
            for a,b in zip(locs[:-1],locs[1:]):
                aid,alat,alon=a; bid,blat,blon=b
                length=haversine_m(alat,alon,blat,blon)
                if length<=0:
                    continue
                def add(u,v,ulat,ulon,vlat,vlon):
                    rows.append({
                        **common,"u":u,"v":v,"from_lat":ulat,"from_lon":ulon,
                        "to_lat":vlat,"to_lon":vlon,"length_m":length,
                    })
                    stats["directed_edges"]+=1
                if direction in ("FORWARD","BOTH"):
                    add(aid,bid,alat,alon,blat,blon)
                if direction in ("REVERSE","BOTH"):
                    add(bid,aid,blat,blon,alat,alon)
                if len(rows)>=batch_size:
                    flush()

    handler=Handler()
    try:
        handler.apply_file(str(pbf_path),locations=True,idx="flex_mem")
        flush()
    finally:
        writer.close()

    node_df=pd.DataFrame(
        [{"node_id":nid,"latitude":lat,"longitude":lon} for nid,(lat,lon) in nodes.items()]
    ).sort_values("node_id").reset_index(drop=True)
    node_df.to_parquet(node_path,index=False)

    stats["unique_nodes"]=len(node_df)
    stats["edge_sha256"]=sha256_file(edge_path)
    stats["node_sha256"]=sha256_file(node_path)

    register_parquet_dataset(
        root,dataset_name="osm_road_network_edges",layer="normalized",
        parquet_path=edge_path,
        partition_spec={"vintage":PROVIDER_VERSION},
        row_count=stats["directed_edges"],run_id=run_id,
    )
    register_parquet_dataset(
        root,dataset_name="osm_road_network_nodes",layer="normalized",
        parquet_path=node_path,
        partition_spec={"vintage":PROVIDER_VERSION},
        row_count=stats["unique_nodes"],run_id=run_id,
    )
    return edge_path,node_path,stats


def load_graph(edge_path: str | Path) -> nx.DiGraph:
    edges=pd.read_parquet(edge_path)
    G=nx.DiGraph()
    for row in edges.itertuples(index=False):
        data={
            "length_m":float(row.length_m),
            "road_class":row.road_class,
            "osm_way_id":int(row.osm_way_id),
            "bridge":bool(row.bridge),
            "tunnel":bool(row.tunnel),
            "ferry":bool(row.ferry),
            "hazard_exposed":False,
            "hazard_blocked":False,
            "from_lat":float(row.from_lat),"from_lon":float(row.from_lon),
            "to_lat":float(row.to_lat),"to_lon":float(row.to_lon),
        }
        if G.has_edge(int(row.u),int(row.v)):
            current=G[int(row.u)][int(row.v)]
            if float(current["length_m"]) <= data["length_m"]:
                continue
        G.add_edge(int(row.u),int(row.v),**data)
    return G


def _xyz(lat,lon):
    p=math.radians(lat); l=math.radians(lon)
    return (math.cos(p)*math.cos(l),math.cos(p)*math.sin(l),math.sin(p))


def nearest_network_node(
    nodes: pd.DataFrame,
    lat: float,
    lon: float,
    *,
    max_snap_m: float = 500.0,
) -> dict:
    if nodes.empty:
        raise ValueError("Road node table is empty")
    try:
        from scipy.spatial import cKDTree
        arr=np.array([_xyz(a,b) for a,b in zip(nodes["latitude"],nodes["longitude"])])
        q=np.array(_xyz(float(lat),float(lon)))
        tree=cKDTree(arr)
        chord,idx=tree.query(q,k=1)
        angular=2*math.asin(min(1.0,float(chord)/2))
        distance=6371008.8*angular
        row=nodes.iloc[int(idx)]
    except ImportError:
        distances=np.array([
            haversine_m(float(lat),float(lon),float(a),float(b))
            for a,b in zip(nodes["latitude"],nodes["longitude"])
        ])
        idx=int(distances.argmin()); distance=float(distances[idx]); row=nodes.iloc[idx]

    quality="GOOD" if distance<=100 else "REVIEW" if distance<=max_snap_m else "REJECTED"
    return {
        "node_id":int(row["node_id"]),
        "node_latitude":float(row["latitude"]),
        "node_longitude":float(row["longitude"]),
        "snap_distance_m":float(distance),
        "snap_quality":quality,
        "accepted":bool(distance<=max_snap_m),
    }


def import_route_endpoints(
    root: str | Path,
    rows: list[dict],
    *,
    tenant_key: str = "INTERNAL",
) -> dict:
    inserted=0; existing=0; rejected=[]
    with connect_catalog(root) as conn:
        for i,row in enumerate(rows,start=1):
            try:
                key=str(row["endpoint_key"]).strip()
                endpoint_type=str(row["endpoint_type"]).strip()
                lat=float(row["latitude"]); lon=float(row["longitude"])
                source=str(row["source"]).strip()
                if not key or not endpoint_type or not source:
                    raise ValueError("endpoint_key, endpoint_type and source are required")
                if not (-90<=lat<=90 and -180<=lon<=180):
                    raise ValueError("invalid coordinate")
            except Exception as e:
                rejected.append({"row":i,"reason":str(e)}); continue

            existing_row=conn.execute(
                """
                SELECT route_endpoint_id FROM route_endpoint
                WHERE tenant_key=? AND endpoint_name=? AND endpoint_type=?
                """,
                (tenant_key,key,endpoint_type),
            ).fetchone()
            if existing_row:
                existing+=1; continue
            conn.execute(
                """
                INSERT INTO route_endpoint(
                    route_endpoint_id,tenant_key,endpoint_type,endpoint_name,
                    latitude,longitude,source,valid_from,valid_to
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(uuid.uuid4()),tenant_key,endpoint_type,key,lat,lon,source,
                    row.get("valid_from") or None,row.get("valid_to") or None,
                ),
            )
            inserted+=1
        conn.commit()
    return {"inserted":inserted,"existing":existing,"rejected":rejected}


def import_route_dependencies(
    root: str | Path,
    rows: list[dict],
    *,
    tenant_key: str = "INTERNAL",
) -> dict:
    inserted=0; existing=0; rejected=[]
    with connect_catalog(root) as conn:
        for i,row in enumerate(rows,start=1):
            try:
                external_system=str(row["external_system"]).strip()
                external_id=str(row["external_id"]).strip()
                endpoint_key=str(row["endpoint_key"]).strip()
                relationship=str(row.get("relationship") or "UNKNOWN").strip().upper()
                if relationship not in {"PRIMARY","SECONDARY","ALTERNATIVE","UNKNOWN"}:
                    raise ValueError("invalid relationship")
                share=row.get("shipment_share")
                share=None if share in (None,"") else float(share)
                if share is not None and not (0<=share<=1):
                    raise ValueError("shipment_share must be between 0 and 1")
            except Exception as e:
                rejected.append({"row":i,"reason":str(e)}); continue

            asset=conn.execute(
                """
                SELECT asset_location_id FROM asset_location
                WHERE tenant_key=? AND external_system=? AND external_id=?
                  AND site_identity_grade='EXACT_SITE' AND coordinate_status='RESOLVED'
                ORDER BY created_at DESC LIMIT 1
                """,
                (tenant_key,external_system,external_id),
            ).fetchone()
            endpoint=conn.execute(
                """
                SELECT route_endpoint_id FROM route_endpoint
                WHERE tenant_key=? AND endpoint_name=?
                ORDER BY rowid DESC LIMIT 1
                """,
                (tenant_key,endpoint_key),
            ).fetchone()
            if not asset or not endpoint:
                rejected.append({"row":i,"reason":"asset or endpoint not found/eligible"}); continue

            found=conn.execute(
                """
                SELECT asset_route_dependency_id FROM asset_route_dependency
                WHERE tenant_key=? AND asset_location_id=? AND route_endpoint_id=? AND relationship=?
                """,
                (tenant_key,asset["asset_location_id"],endpoint["route_endpoint_id"],relationship),
            ).fetchone()
            if found:
                existing+=1; continue
            conn.execute(
                """
                INSERT INTO asset_route_dependency(
                    asset_route_dependency_id,tenant_key,asset_location_id,route_endpoint_id,
                    relationship,shipment_share,valid_from,valid_to
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    str(uuid.uuid4()),tenant_key,asset["asset_location_id"],
                    endpoint["route_endpoint_id"],relationship,share,
                    row.get("valid_from") or None,row.get("valid_to") or None,
                ),
            )
            inserted+=1
        conn.commit()
    return {"inserted":inserted,"existing":existing,"rejected":rejected}


def route_dependencies(root: str | Path, tenant_key: str | None = None) -> list[dict]:
    sql="""
    SELECT d.asset_route_dependency_id,d.tenant_key,d.relationship,d.shipment_share,
           a.asset_location_id,a.external_system,a.external_id,
           a.latitude AS asset_latitude,a.longitude AS asset_longitude,
           e.route_endpoint_id,e.endpoint_type,e.endpoint_name,
           e.latitude AS endpoint_latitude,e.longitude AS endpoint_longitude
    FROM asset_route_dependency d
    JOIN asset_location a ON a.asset_location_id=d.asset_location_id
    JOIN route_endpoint e ON e.route_endpoint_id=d.route_endpoint_id
    WHERE a.site_identity_grade='EXACT_SITE' AND a.coordinate_status='RESOLVED'
      AND (d.valid_to IS NULL OR d.valid_to > datetime('now'))
    """
    params=()
    if tenant_key is not None:
        sql+=" AND d.tenant_key=?"; params=(tenant_key,)
    sql+=" ORDER BY d.tenant_key,a.external_system,a.external_id,d.relationship,e.endpoint_name"
    with connect_catalog(root) as conn:
        return [dict(x) for x in conn.execute(sql,params).fetchall()]
