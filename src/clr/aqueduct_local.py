from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
from shapely.geometry import Point,shape

from .local_store import (
    connect_catalog,
    register_source_file,
    sha256_file,
    source_snapshot_path,
    utc_now,
)

PROVIDER="World Resources Institute"
PROVIDER_VERSION="Aqueduct_4.0"
SOURCE_ID_PREFIX="WRI_AQUEDUCT4_BASELINE_ANNUAL"
MEASUREMENT_BASIS="STATIC_MODEL"
REQUIRED_FIELDS={"bws_raw","bws_score","bws_label","bws_cat"}
OPTIONAL_ID_FIELDS=("pfaf_id","aq30_id","gid_1","name_1","gid_0","name_0")


def register_aqueduct_snapshot(
    root:str|Path,
    source_path:str|Path,
    *,
    source_url:str,
    retrieved_at:str|None=None,
)->dict:
    root=Path(root).resolve()
    src=Path(source_path).resolve()
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(src)
    if src.suffix.lower() not in {".gpkg",".geojson",".json",".zip"}:
        raise ValueError("Aqueduct source must be GPKG, GeoJSON/JSON, or ZIP containing one")

    digest=sha256_file(src)
    destination=source_snapshot_path(
        root,"WRI","AQUEDUCT4_BASELINE_ANNUAL",PROVIDER_VERSION,
        digest,src.name,
    )
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        if sha256_file(destination)!=digest:
            raise RuntimeError("Content-addressed Aqueduct snapshot has unexpected bytes")
    else:
        shutil.copy2(src,destination)

    return register_source_file(
        root,
        source_id=f"{SOURCE_ID_PREFIX}_{digest[:16]}",
        provider=PROVIDER,provider_version=PROVIDER_VERSION,
        artifact_path=destination,
        media_type=(
            "application/geopackage+sqlite3"
            if src.suffix.lower()==".gpkg"
            else "application/zip"
            if src.suffix.lower()==".zip"
            else "application/geo+json"
        ),
        retrieved_at=retrieved_at,retrieval_status="COMPLETE",
        note=(
            "WRI Aqueduct 4.0 baseline annual spatial snapshot. "
            "Mangrove preserves WRI baseline-water-stress fields without rescaling "
            "or combining them into an overall score."
        ),
        request_parameters={
            "source_url":source_url,
            "dataset":"Aqueduct 4.0 Current and Future Global Maps Data",
            "subset":"Baseline Annual",
            "license":"CC BY 4.0",
        },
    )


def _materialize_spatial_file(path:Path):
    if path.suffix.lower()!=".zip":
        return None,path
    td=tempfile.TemporaryDirectory()
    with zipfile.ZipFile(path) as z:
        members=[
            m for m in z.namelist()
            if Path(m).suffix.lower() in {".gpkg",".geojson",".json"}
        ]
        if len(members)!=1:
            td.cleanup()
            raise ValueError(
                f"Aqueduct ZIP must contain exactly one GPKG/GeoJSON file; found {members}"
            )
        z.extract(members[0],td.name)
        return td,Path(td.name)/members[0]


def read_aqueduct_features(
    source_path:str|Path,
    assets:list[dict],
    *,
    layer:str|None=None,
    pad_deg:float=0.05,
)->tuple[list[dict],str|None]:
    try:
        import fiona
    except ImportError as e:
        raise RuntimeError("fiona is required. Install requirements-local.txt.") from e

    if not assets:
        raise ValueError("No assets supplied")
    path=Path(source_path).resolve()
    holder,spatial=_materialize_spatial_file(path)
    try:
        layers=list(fiona.listlayers(spatial))
        if layer is None:
            if len(layers)!=1:
                raise ValueError(
                    f"Aqueduct source has multiple layers {layers}; provide --layer explicitly"
                )
            layer=layers[0]
        elif layer not in layers:
            raise ValueError(f"Aqueduct layer {layer!r} not found; available: {layers}")

        lats=[float(a["latitude"]) for a in assets]
        lons=[float(a["longitude"]) for a in assets]
        bbox=(
            min(lons)-pad_deg,min(lats)-pad_deg,
            max(lons)+pad_deg,max(lats)+pad_deg,
        )
        features=[]
        with fiona.open(spatial,layer=layer) as src:
            props=set(src.schema.get("properties",{}))
            missing=REQUIRED_FIELDS-props
            if missing:
                raise ValueError(f"Aqueduct layer missing required fields {sorted(missing)}")
            for feature in src.filter(bbox=bbox):
                geometry=feature.get("geometry")
                if not geometry:
                    continue
                geom=shape(geometry)
                if not geom.is_valid:
                    raise ValueError("Aqueduct source contains invalid geometry in candidate area")
                p=dict(feature.get("properties") or {})
                features.append({"geometry":geom,"properties":p})
        return features,layer
    finally:
        if holder is not None:
            holder.cleanup()


def match_assets_to_aqueduct(
    assets:list[dict],
    features:list[dict],
)->pd.DataFrame:
    rows=[]
    for asset in assets:
        pt=Point(float(asset["longitude"]),float(asset["latitude"]))
        matches=[f for f in features if f["geometry"].covers(pt)]
        if len(matches)==0:
            rows.append({
                "tenant_key":asset["tenant_key"],
                "asset_location_id":asset["asset_location_id"],
                "external_id":asset["external_id"],
                "match_status":"NO_MATCH",
                "null_reason":"NO_AQUEDUCT_POLYGON_MATCH",
            })
            continue
        if len(matches)>1:
            rows.append({
                "tenant_key":asset["tenant_key"],
                "asset_location_id":asset["asset_location_id"],
                "external_id":asset["external_id"],
                "match_status":"AMBIGUOUS",
                "null_reason":"AMBIGUOUS_AQUEDUCT_BOUNDARY",
            })
            continue

        props=matches[0]["properties"]
        row={
            "tenant_key":asset["tenant_key"],
            "asset_location_id":asset["asset_location_id"],
            "external_id":asset["external_id"],
            "match_status":"MATCHED",
            "null_reason":None,
            "bws_raw":None if props.get("bws_raw") is None else float(props["bws_raw"]),
            "bws_score":None if props.get("bws_score") is None else float(props["bws_score"]),
            "bws_label":None if props.get("bws_label") is None else str(props["bws_label"]),
            "bws_cat":None if props.get("bws_cat") is None else int(props["bws_cat"]),
        }
        for field in OPTIONAL_ID_FIELDS:
            if field in props and props.get(field) is not None:
                row[field]=str(props[field])
        rows.append(row)
    return pd.DataFrame(rows)


def build_aqueduct_context(
    root:str|Path,
    assets:list[dict],
    source_record:dict,
    *,
    layer:str|None=None,
)->pd.DataFrame:
    root=Path(root).resolve()
    features,resolved_layer=read_aqueduct_features(
        root/source_record["local_path"],assets,layer=layer
    )
    matched=match_assets_to_aqueduct(assets,features)
    matched["source_artifact_id"]=source_record["source_artifact_id"]
    matched["source_layer"]=resolved_layer
    matched["method_version"]="AQUEDUCT4_POINT_IN_POLYGON_0.1"
    return matched


def insert_aqueduct_indicators(
    root:str|Path,
    frame:pd.DataFrame,
    *,
    run_id:str,
)->int:
    specs=[
        ("wri_aqueduct4_bws_raw","bws_raw","ratio","numeric"),
        ("wri_aqueduct4_bws_score","bws_score","WRI_0_5_score","numeric"),
        ("wri_aqueduct4_bws_cat","bws_cat","WRI_category_code","numeric"),
        ("wri_aqueduct4_bws_label","bws_label",None,"text"),
    ]
    count=0
    with connect_catalog(root) as conn:
        for row in frame.to_dict(orient="records"):
            matched=row["match_status"]=="MATCHED"
            for indicator_id,field,unit,kind in specs:
                value=row.get(field) if matched else None
                if pd.isna(value):
                    value=None
                null_reason=None if value is not None else (
                    row.get("null_reason") or "SOURCE_VALUE_MISSING"
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
                        float(value) if kind=="numeric" and value is not None else None,
                        str(value) if kind=="text" and value is not None else None,
                        unit,"SOURCE",MEASUREMENT_BASIS,row["source_artifact_id"],
                        row["method_version"],None,None,
                        "SOURCE_CONTEXT" if matched else row["match_status"],
                        null_reason,run_id,utc_now(),
                    ),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO asset_indicator_source(
                        asset_indicator_id,source_artifact_id,source_role
                    ) VALUES(?,?,?)
                    """,
                    (cur.lastrowid,row["source_artifact_id"],"PRIMARY"),
                )
                count+=1
        conn.commit()
    return count
