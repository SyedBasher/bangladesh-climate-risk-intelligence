from __future__ import annotations

import json
import math
import uuid
from pathlib import Path

import networkx as nx
import pandas as pd

from .local_store import (
    connect_catalog,
    parquet_partition_dir,
    register_parquet_dataset,
    sha256_file,
    utc_now,
)
from .logistics import baseline_route, edge_disjoint_count
from .osm_local import NetworkNodeIndex, load_graph, route_dependencies


def latest_registered_network(root: str | Path) -> dict:
    root=Path(root).resolve()
    with connect_catalog(root) as conn:
        edge_rows=conn.execute(
            """
            SELECT * FROM parquet_dataset
            WHERE dataset_name='osm_road_network_edges'
            ORDER BY created_at DESC
            """
        ).fetchall()
        node_rows=conn.execute(
            """
            SELECT * FROM parquet_dataset
            WHERE dataset_name='osm_road_network_nodes'
            ORDER BY created_at DESC
            """
        ).fetchall()
        source_rows=conn.execute(
            """
            SELECT * FROM source_artifact
            WHERE source_id='OSM_GEOFABRIK_BANGLADESH_260919'
              AND retrieval_status='COMPLETE'
            ORDER BY retrieved_at DESC
            """
        ).fetchall()

    def verified(rows):
        for row in rows:
            p=root/row["relative_path"]
            if p.exists() and (row["sha256"] is None or sha256_file(p)==row["sha256"]):
                return dict(row),p
        return None,None

    edge_meta,edge_path=verified(edge_rows)
    node_meta,node_path=verified(node_rows)
    source=None
    for row in source_rows:
        p=root/row["local_path"]
        if p.exists() and sha256_file(p)==row["sha256"]:
            source=dict(row); break

    if edge_path is None or node_path is None or source is None:
        raise FileNotFoundError(
            "Verified OSM road network is unavailable. Run scripts/prepare_osm_network_local.py."
        )
    return {
        "edge_meta":edge_meta,"edge_path":edge_path,
        "node_meta":node_meta,"node_path":node_path,
        "source":source,
    }


def _physical_edge_key(u, v) -> str:
    a,b=sorted((int(u),int(v)))
    return f"{a}:{b}"


def analyze_baseline_routes(
    root: str | Path,
    *,
    run_id: str,
    tenant_key: str | None = None,
    max_snap_m: float = 500.0,
) -> tuple[pd.DataFrame,pd.DataFrame,dict]:
    root=Path(root).resolve()
    network=latest_registered_network(root)
    nodes=pd.read_parquet(network["node_path"])
    G=load_graph(network["edge_path"])
    node_index=NetworkNodeIndex(nodes)
    deps=route_dependencies(root,tenant_key=tenant_key)
    if not deps:
        raise ValueError("No explicit asset-route dependencies are available")

    summaries=[]
    route_rows=[]
    for dep in deps:
        analysis_id=str(uuid.uuid4())
        origin=node_index.nearest(
            float(dep["asset_latitude"]),float(dep["asset_longitude"]),
            max_snap_m=max_snap_m,
        )
        dest=node_index.nearest(
            float(dep["endpoint_latitude"]),float(dep["endpoint_longitude"]),
            max_snap_m=max_snap_m,
        )

        summary={
            "route_analysis_id":analysis_id,
            "tenant_key":dep["tenant_key"],
            "asset_route_dependency_id":dep["asset_route_dependency_id"],
            "external_system":dep["external_system"],
            "external_id":dep["external_id"],
            "endpoint_type":dep["endpoint_type"],
            "endpoint_name":dep["endpoint_name"],
            "relationship":dep["relationship"],
            "origin_node_id":origin["node_id"],
            "destination_node_id":dest["node_id"],
            "origin_snap_distance_m":origin["snap_distance_m"],
            "destination_snap_distance_m":dest["snap_distance_m"],
            "origin_snap_quality":origin["snap_quality"],
            "destination_snap_quality":dest["snap_quality"],
            "baseline_length_m":None,
            "edge_disjoint_route_count":None,
            "quality_flag":"OK",
        }

        if not origin["accepted"] or not dest["accepted"]:
            summary["quality_flag"]="SNAP_REJECTED"
            summaries.append(summary)
            continue

        try:
            route=baseline_route(G,origin["node_id"],dest["node_id"],weight="length_m")
        except (nx.NetworkXNoPath,nx.NodeNotFound):
            summary["quality_flag"]="NO_NETWORK_PATH"
            summaries.append(summary)
            continue

        summary["baseline_length_m"]=float(route["length"])
        summary["edge_disjoint_route_count"]=int(
            edge_disjoint_count(G,origin["node_id"],dest["node_id"],cap=10)
        )
        summaries.append(summary)

        cumulative=0.0
        for seq,(u,v) in enumerate(route["edges"],start=1):
            d=G.get_edge_data(u,v)
            if d is None:
                raise RuntimeError(f"Missing graph edge {(u,v)}")
            length=float(d["length_m"])
            route_rows.append({
                "route_analysis_id":analysis_id,
                "tenant_key":dep["tenant_key"],
                "asset_route_dependency_id":dep["asset_route_dependency_id"],
                "external_system":dep["external_system"],
                "external_id":dep["external_id"],
                "endpoint_type":dep["endpoint_type"],
                "endpoint_name":dep["endpoint_name"],
                "relationship":dep["relationship"],
                "edge_sequence":seq,
                "u":int(u),"v":int(v),
                "physical_edge_key":_physical_edge_key(u,v),
                "osm_way_id":int(d["osm_way_id"]),
                "road_class":d["road_class"],
                "bridge":bool(d.get("bridge",False)),
                "tunnel":bool(d.get("tunnel",False)),
                "ferry":bool(d.get("ferry",False)),
                "length_m":length,
                "cumulative_start_m":cumulative,
                "cumulative_end_m":cumulative+length,
                "from_lat":float(d["from_lat"]),"from_lon":float(d["from_lon"]),
                "to_lat":float(d["to_lat"]),"to_lon":float(d["to_lon"]),
            })
            cumulative+=length

    summary_df=pd.DataFrame(summaries)
    edge_df=pd.DataFrame(route_rows)
    if not edge_df.empty:
        counts=(
            edge_df[["asset_route_dependency_id","physical_edge_key"]]
            .drop_duplicates()
            .groupby("physical_edge_key")
            .size()
            .rename("shared_dependency_count")
        )
        edge_df=edge_df.merge(counts,on="physical_edge_key",how="left")

    source_id=network["source"]["source_artifact_id"]
    with connect_catalog(root) as conn:
        for row in summary_df.to_dict(orient="records"):
            conn.execute(
                """
                INSERT INTO logistics_route_analysis(
                    route_analysis_id,tenant_key,asset_route_dependency_id,run_id,scenario_id,
                    origin_node_id,destination_node_id,origin_snap_distance_m,
                    destination_snap_distance_m,baseline_length_m,edge_disjoint_route_count,
                    quality_flag,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row["route_analysis_id"],row["tenant_key"],
                    row["asset_route_dependency_id"],run_id,"BASELINE",
                    row["origin_node_id"],row["destination_node_id"],
                    row["origin_snap_distance_m"],row["destination_snap_distance_m"],
                    row["baseline_length_m"],row["edge_disjoint_route_count"],
                    row["quality_flag"],utc_now(),
                ),
            )
            conn.execute(
                """
                INSERT INTO logistics_route_analysis_source(
                    route_analysis_id,source_artifact_id,source_role
                ) VALUES(?,?,?)
                """,
                (row["route_analysis_id"],source_id,"OSM_PBF"),
            )
        conn.commit()

    outdir=parquet_partition_dir(
        root,layer="indicators",dataset="osm_logistics_routes",
        partitions={"network_vintage":"bangladesh-260919"},
    )
    outdir.mkdir(parents=True,exist_ok=True)
    summary_path=outdir/f"route-summary-{run_id}.parquet"
    edge_path=outdir/f"route-edges-{run_id}.parquet"
    summary_df.to_parquet(summary_path,index=False)
    edge_df.to_parquet(edge_path,index=False)

    register_parquet_dataset(
        root,dataset_name="osm_logistics_route_summary",layer="indicators",
        parquet_path=summary_path,
        partition_spec={"network_vintage":"bangladesh-260919"},
        row_count=len(summary_df),run_id=run_id,
    )
    register_parquet_dataset(
        root,dataset_name="osm_logistics_route_edges",layer="indicators",
        parquet_path=edge_path,
        partition_spec={"network_vintage":"bangladesh-260919"},
        row_count=len(edge_df),run_id=run_id,
    )

    qa={
        "dependencies":len(summary_df),
        "routes_ok":int((summary_df["quality_flag"]=="OK").sum()) if not summary_df.empty else 0,
        "snap_rejected":int((summary_df["quality_flag"]=="SNAP_REJECTED").sum()) if not summary_df.empty else 0,
        "no_path":int((summary_df["quality_flag"]=="NO_NETWORK_PATH").sum()) if not summary_df.empty else 0,
        "shared_physical_edges":0 if edge_df.empty else int((edge_df["shared_dependency_count"]>1).sum()),
        "osm_source_artifact_id":source_id,
    }
    return summary_df,edge_df,qa


def latest_route_edges(root: str | Path) -> tuple[dict,Path]:
    root=Path(root).resolve()
    with connect_catalog(root) as conn:
        rows=conn.execute(
            """
            SELECT * FROM parquet_dataset
            WHERE dataset_name='osm_logistics_route_edges'
            ORDER BY created_at DESC
            """
        ).fetchall()
    for row in rows:
        p=root/row["relative_path"]
        if p.exists() and (row["sha256"] is None or sha256_file(p)==row["sha256"]):
            return dict(row),p
    raise FileNotFoundError("No verified baseline route-edge Parquet is available")
