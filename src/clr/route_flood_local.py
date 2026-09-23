from __future__ import annotations

import math
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

from .jrc_flood import load_tile_extents, resolve_tile
from .jrc_local import artifact_plan, ensure_tile_extents, retrieve_plan
from .local_store import (
    connect_catalog,
    parquet_partition_dir,
    register_parquet_dataset,
    sha256_file,
    utc_now,
)
from .logistics_local import latest_route_edges
from .osm_local import SOURCE_ID as OSM_SOURCE_ID


def _edge_sample_points(row, spacing_m: float) -> list[tuple[float,float]]:
    length=float(row["length_m"])
    n=max(1,int(math.ceil(length/spacing_m)))
    return [
        (
            float(row["from_lat"])+(float(row["to_lat"])-float(row["from_lat"]))*(i/n),
            float(row["from_lon"])+(float(row["to_lon"])-float(row["from_lon"]))*(i/n),
        )
        for i in range(n+1)
    ]


def _sample_ds(ds, lat: float, lon: float):
    x,y=lon,lat
    if ds.crs and str(ds.crs).upper() not in ("EPSG:4326","OGC:CRS84"):
        from rasterio.warp import transform
        xs,ys=transform("EPSG:4326",ds.crs,[lon],[lat])
        x,y=xs[0],ys[0]
    arr=list(ds.sample([(x,y)],masked=True))[0]
    try:
        if arr.mask[0]:
            return None
    except Exception:
        pass
    val=float(arr[0])
    return val if np.isfinite(val) else None


def annotate_route_edges_with_jrc(
    root: str | Path,
    route_edges: pd.DataFrame,
    *,
    return_period: int = 100,
    spacing_m: float = 100.0,
) -> tuple[pd.DataFrame,dict]:
    if route_edges.empty:
        raise ValueError("Route-edge table is empty")
    if spacing_m<=0:
        raise ValueError("spacing_m must be positive")

    root=Path(root).resolve()
    tile_record,tile_path=ensure_tile_extents(root)
    extents=load_tile_extents(tile_path)

    edge_points={}
    needed_tiles=set()
    for idx,row in route_edges.iterrows():
        points=_edge_sample_points(row,spacing_m)
        tagged=[]
        for lat,lon in points:
            tile=resolve_tile(extents,lat,lon)
            needed_tiles.add(tile)
            tagged.append((lat,lon,tile))
        edge_points[idx]=tagged

    plan=artifact_plan(sorted(needed_tiles),[int(return_period)])
    records=retrieve_plan(root,plan)

    opened={}
    def ds_for(tile,role,rp=None):
        key=(tile,role,rp)
        if key not in opened:
            rec=records[key]
            opened[key]=rasterio.open(root/rec["local_path"])
        return opened[key]

    rows=[]
    try:
        for idx,row in route_edges.iterrows():
            depths=[]
            valid=0; masked=0; nodata=0; permanent=0; spurious=0
            tiles=set()
            for lat,lon,tile in edge_points[idx]:
                tiles.add(tile)
                p=_sample_ds(ds_for(tile,"PERMANENT_WATER_MASK",None),lat,lon)
                s=_sample_ds(ds_for(tile,"SPURIOUS_DEPTH_MASK",None),lat,lon)
                if p not in (None,0.0):
                    permanent+=1; masked+=1; continue
                if s not in (None,0.0):
                    spurious+=1; masked+=1; continue
                d=_sample_ds(ds_for(tile,"DEPTH",int(return_period)),lat,lon)
                if d is None:
                    nodata+=1; continue
                valid+=1; depths.append(float(d))

            max_depth=max(depths) if depths else None
            any_exposed=bool(depths and max_depth>0)
            uncertain=(masked>0 or nodata>0)
            if any_exposed:
                exposed=True
                quality="EXPOSED"
            elif uncertain:
                exposed=None
                quality="UNKNOWN_MASKED_OR_NODATA"
            else:
                exposed=False
                quality="NO_POSITIVE_DEPTH_SAMPLED"

            out=dict(row)
            out.update({
                "jrc_return_period":int(return_period),
                "jrc_sample_spacing_m":float(spacing_m),
                "jrc_sample_count":len(edge_points[idx]),
                "jrc_valid_sample_count":valid,
                "jrc_masked_sample_count":masked,
                "jrc_nodata_sample_count":nodata,
                "jrc_permanent_water_sample_count":permanent,
                "jrc_spurious_depth_sample_count":spurious,
                "jrc_max_valid_depth_m":max_depth,
                "hazard_exposed":exposed,
                "hazard_quality_flag":quality,
                "jrc_tiles":";".join(sorted(tiles)),
            })
            rows.append(out)
    finally:
        for ds in opened.values():
            ds.close()

    annotated=pd.DataFrame(rows)
    source_map={
        "tile_extents":tile_record,
        "records":records,
        "return_period":int(return_period),
        "tiles":sorted(needed_tiles),
    }
    return annotated,source_map


def publish_route_flood_exposure(
    root: str | Path,
    annotated: pd.DataFrame,
    source_map: dict,
    *,
    run_id: str,
) -> tuple[pd.DataFrame,Path,Path]:
    root=Path(root).resolve()
    if annotated.empty:
        raise ValueError("Annotated route-edge table is empty")

    summaries=[]
    with connect_catalog(root) as conn:
        osm_row=conn.execute(
            """
            SELECT * FROM source_artifact
            WHERE source_id=? AND retrieval_status='COMPLETE'
            ORDER BY retrieved_at DESC LIMIT 1
            """,
            (OSM_SOURCE_ID,),
        ).fetchone()
        if not osm_row:
            raise ValueError("Registered OSM PBF source is missing")
        osm_source=dict(osm_row)

        for analysis_id,grp in annotated.groupby("route_analysis_id"):
            first=grp.iloc[0]
            total=float(grp["length_m"].sum())
            exposed=float(grp.loc[grp["hazard_exposed"]==True,"length_m"].sum())
            unknown=float(grp.loc[grp["hazard_exposed"].isna(),"length_m"].sum())
            share=None if total==0 or unknown>0 else exposed/total
            quality="OK" if unknown==0 else "PARTIAL_HAZARD_COVERAGE"
            new_id=str(uuid.uuid4())
            baseline=float(grp["cumulative_end_m"].max())
            summaries.append({
                "route_analysis_id":new_id,
                "parent_baseline_route_analysis_id":analysis_id,
                "tenant_key":first["tenant_key"],
                "asset_route_dependency_id":first["asset_route_dependency_id"],
                "external_system":first["external_system"],
                "external_id":first["external_id"],
                "endpoint_name":first["endpoint_name"],
                "relationship":first["relationship"],
                "scenario_id":f"JRC_RP{source_map['return_period']}_EXPOSURE_ONLY",
                "baseline_length_m":baseline,
                "hazard_exposed_length_m":exposed,
                "hazard_unknown_length_m":unknown,
                "hazard_assessment_coverage_share":None if total==0 else (total-unknown)/total,
                "hazard_exposed_share":share,
                "quality_flag":quality,
            })
            conn.execute(
                """
                INSERT INTO logistics_route_analysis(
                    route_analysis_id,tenant_key,asset_route_dependency_id,run_id,scenario_id,
                    baseline_length_m,hazard_exposed_length_m,hazard_exposed_share,
                    quality_flag,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    new_id,first["tenant_key"],first["asset_route_dependency_id"],run_id,
                    f"JRC_RP{source_map['return_period']}_EXPOSURE_ONLY",
                    baseline,exposed,share,quality,utc_now(),
                ),
            )
            lineage={(osm_source["source_artifact_id"],"OSM_PBF"),
                     (source_map["tile_extents"]["source_artifact_id"],"JRC_TILE_EXTENTS")}
            for (tile,role,rp),rec in source_map["records"].items():
                role_map={
                    "DEPTH":"JRC_DEPTH",
                    "PERMANENT_WATER_MASK":"JRC_PERMANENT_WATER_MASK",
                    "SPURIOUS_DEPTH_MASK":"JRC_SPURIOUS_DEPTH_MASK",
                }
                lineage.add((rec["source_artifact_id"],role_map[role]))
            conn.executemany(
                """
                INSERT INTO logistics_route_analysis_source(
                    route_analysis_id,source_artifact_id,source_role
                ) VALUES(?,?,?)
                """,
                [(new_id,sid,role) for sid,role in sorted(lineage)],
            )
        conn.commit()

    summary_df=pd.DataFrame(summaries)

    outdir=parquet_partition_dir(
        root,layer="indicators",dataset="osm_route_flood_exposure",
        partitions={"return_period":source_map["return_period"]},
    )
    outdir.mkdir(parents=True,exist_ok=True)
    edge_path=outdir/f"route-edge-flood-{run_id}.parquet"
    summary_path=outdir/f"route-flood-summary-{run_id}.parquet"
    annotated.to_parquet(edge_path,index=False)
    summary_df.to_parquet(summary_path,index=False)

    register_parquet_dataset(
        root,dataset_name="osm_route_flood_edge_exposure",layer="indicators",
        parquet_path=edge_path,
        partition_spec={"return_period":source_map["return_period"]},
        row_count=len(annotated),run_id=run_id,
    )
    register_parquet_dataset(
        root,dataset_name="osm_route_flood_summary",layer="indicators",
        parquet_path=summary_path,
        partition_spec={"return_period":source_map["return_period"]},
        row_count=len(summary_df),run_id=run_id,
    )

    bottlenecks=(
        annotated[
            (annotated["hazard_exposed"]==True)
            & (annotated["shared_dependency_count"]>1)
        ][
            ["physical_edge_key","osm_way_id","road_class","bridge","ferry",
             "length_m","shared_dependency_count","jrc_max_valid_depth_m"]
        ]
        .drop_duplicates("physical_edge_key")
        .sort_values(["shared_dependency_count","length_m"],ascending=[False,False])
    )
    bottleneck_path=outdir/f"shared-hazard-bottlenecks-{run_id}.parquet"
    bottlenecks.to_parquet(bottleneck_path,index=False)
    register_parquet_dataset(
        root,dataset_name="osm_shared_hazard_bottlenecks",layer="indicators",
        parquet_path=bottleneck_path,
        partition_spec={"return_period":source_map["return_period"]},
        row_count=len(bottlenecks),run_id=run_id,
    )
    return summary_df,edge_path,bottleneck_path
