from __future__ import annotations

import hashlib
import json
import math
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import numpy as np
import pandas as pd
import rasterio
import requests

from .local_store import (
    connect_catalog,
    register_source_file,
    sha256_file,
    source_snapshot_path,
    utc_now,
)

STAC_API="https://stac.eodc.eu/api/v1"
STAC_SEARCH=f"{STAC_API}/search"
COLLECTION="GFM"
PROVIDER="Copernicus Emergency Management Service / EODC"
PROVIDER_VERSION="GFM_STAC"
REQUIRED_ASSETS=(
    "ensemble_flood_extent",
    "exclusion_mask",
    "reference_water_mask",
    "ensemble_likelihood",
)
OPTIONAL_ASSETS=("advisory_flags",)
MEASUREMENT_BASIS="CALCULATED_FROM_SENTINEL1_GFM_OBSERVED_FLOOD"


def asset_signature(assets:list[dict])->str:
    payload=[
        {
            "asset_location_id":str(a["asset_location_id"]),
            "latitude":round(float(a["latitude"]),8),
            "longitude":round(float(a["longitude"]),8),
        }
        for a in sorted(assets,key=lambda x:str(x["asset_location_id"]))
    ]
    return hashlib.sha256(
        json.dumps(payload,sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()


def _bbox(assets:list[dict],buffer_deg:float)->list[float]:
    if not assets:
        raise ValueError("No assets supplied")
    if buffer_deg<0:
        raise ValueError("buffer_deg cannot be negative")
    lats=[float(a["latitude"]) for a in assets]
    lons=[float(a["longitude"]) for a in assets]
    return [
        min(lons)-buffer_deg,min(lats)-buffer_deg,
        max(lons)+buffer_deg,max(lats)+buffer_deg,
    ]


def search_gfm_items(
    assets:list[dict],
    start:str,
    end:str,
    *,
    buffer_deg:float=0.02,
    session=None,
    max_items:int=5000,
)->list[dict]:
    s=session or requests.Session()
    payload={
        "collections":[COLLECTION],
        "bbox":_bbox(assets,buffer_deg),
        "datetime":f"{start}/{end}",
        "limit":100,
    }
    items=[]
    method="POST"; url=STAC_SEARCH; body=payload
    while url:
        response=s.request(method,url,json=body if method=="POST" else None,timeout=60)
        response.raise_for_status()
        data=response.json()
        items.extend(data.get("features") or [])
        if len(items)>max_items:
            raise RuntimeError(f"GFM query exceeded max_items={max_items}")
        next_link=next((x for x in data.get("links",[]) if x.get("rel")=="next"),None)
        if not next_link:
            break
        url=urljoin(STAC_API,next_link["href"])
        method=str(next_link.get("method","GET")).upper()
        body=next_link.get("body")
    return items


def _sample_href(href:str,assets:list[dict])->list[float|None]:
    vsi=href if href.startswith("/vsicurl/") else f"/vsicurl/{href}"
    opts={
        "GDAL_DISABLE_READDIR_ON_OPEN":"EMPTY_DIR",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS":".tif,.tiff,.cog",
    }
    with rasterio.Env(**opts):
        with rasterio.open(vsi) as ds:
            coords=[(float(a["longitude"]),float(a["latitude"])) for a in assets]
            out=[]
            for arr in ds.sample(coords,masked=True):
                try:
                    if bool(arr.mask[0]):
                        out.append(None); continue
                except Exception:
                    pass
                val=float(arr[0])
                if not np.isfinite(val) or (ds.nodata is not None and val==ds.nodata):
                    out.append(None)
                else:
                    out.append(val)
            return out


def _item_datetime(item:dict)->str|None:
    p=item.get("properties") or {}
    return p.get("datetime") or p.get("start_datetime")


def sample_gfm_items(items:list[dict],assets:list[dict])->pd.DataFrame:
    rows=[]
    for item in items:
        item_assets=item.get("assets") or {}
        missing=[k for k in REQUIRED_ASSETS if k not in item_assets]
        if missing:
            continue
        samples={}
        for key in REQUIRED_ASSETS+OPTIONAL_ASSETS:
            asset=item_assets.get(key)
            if not asset or not asset.get("href"):
                samples[key]=[None]*len(assets)
            else:
                samples[key]=_sample_href(asset["href"],assets)
        for i,a in enumerate(assets):
            flood=samples["ensemble_flood_extent"][i]
            excl=samples["exclusion_mask"][i]
            refw=samples["reference_water_mask"][i]
            likelihood=samples["ensemble_likelihood"][i]
            advisory=samples["advisory_flags"][i]
            covered=flood is not None
            eligible=bool(
                covered and excl==0 and refw==0
            )
            rows.append({
                "asset_location_id":a["asset_location_id"],
                "tenant_key":a["tenant_key"],
                "external_system":a["external_system"],
                "external_id":a["external_id"],
                "item_id":item.get("id"),
                "observed_at":_item_datetime(item),
                "ensemble_flood_extent":flood,
                "exclusion_mask":excl,
                "reference_water_mask":refw,
                "ensemble_likelihood":likelihood,
                "advisory_flags":advisory,
                "covered":covered,
                "eligible":eligible,
                "flood_positive":bool(eligible and flood==1),
                "advisory_flagged":bool(eligible and advisory not in (None,0)),
            })
    if not rows:
        return pd.DataFrame(columns=[
            "asset_location_id","tenant_key","external_system","external_id","item_id",
            "observed_at","ensemble_flood_extent","exclusion_mask","reference_water_mask",
            "ensemble_likelihood","advisory_flags","covered","eligible",
            "flood_positive","advisory_flagged",
        ])
    return pd.DataFrame(rows).drop_duplicates(
        subset=["asset_location_id","item_id"]
    ).sort_values(["asset_location_id","observed_at","item_id"]).reset_index(drop=True)


def extract_gfm_event_source_subset(
    root:str|Path,
    assets:list[dict],
    start:str,
    end:str,
    *,
    buffer_deg:float=0.02,
    session=None,
)->tuple[dict,pd.DataFrame]:
    root=Path(root).resolve()
    sig=asset_signature(assets)
    source_id=f"GFM_EVENT_{start}_{end}_{sig[:16]}".replace(":","-")
    with connect_catalog(root) as conn:
        existing=conn.execute(
            """
            SELECT * FROM source_artifact
            WHERE source_id=? AND retrieval_status='COMPLETE'
            ORDER BY retrieved_at DESC
            """,(source_id,)
        ).fetchall()
    for row in existing:
        path=root/row["local_path"]
        if path.exists() and sha256_file(path)==row["sha256"]:
            return dict(row),pd.read_parquet(path)

    items=search_gfm_items(
        assets,start,end,buffer_deg=buffer_deg,session=session
    )
    frame=sample_gfm_items(items,assets)
    tmp=root/"tmp"/f"gfm_event_{start}_{end}_{sig[:16]}.parquet"
    tmp.parent.mkdir(parents=True,exist_ok=True)
    frame.to_parquet(tmp,index=False)
    digest=sha256_file(tmp)
    destination=source_snapshot_path(
        root,"CEMS_EODC","GFM",PROVIDER_VERSION,digest,tmp.name
    )
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        if sha256_file(destination)!=digest:
            raise RuntimeError("Content-addressed GFM subset has unexpected bytes")
        tmp.unlink()
    else:
        shutil.move(str(tmp),str(destination))

    item_manifest=[
        {
            "id":x.get("id"),
            "datetime":_item_datetime(x),
            "assets":{
                k:(x.get("assets") or {}).get(k,{}).get("href")
                for k in REQUIRED_ASSETS+OPTIONAL_ASSETS
                if k in (x.get("assets") or {})
            },
        }
        for x in items
    ]
    record=register_source_file(
        root,source_id=source_id,provider=PROVIDER,provider_version=PROVIDER_VERSION,
        artifact_path=destination,media_type="application/vnd.apache.parquet",
        valid_time_start=start,valid_time_end=end,retrieval_status="COMPLETE",
        note=(
            "Immutable asset-point source subset from official GFM STAC/COG assets. "
            "Counts refer to Sentinel-1 acquisitions, not calendar-day flood frequency."
        ),
        request_parameters={
            "stac_api":STAC_API,"collection":COLLECTION,
            "bbox":_bbox(assets,buffer_deg),"start":start,"end":end,
            "asset_signature":sig,"items":item_manifest,
        },
    )
    return record,frame


def summarize_gfm_event(frame:pd.DataFrame, assets:list[dict]|None=None)->pd.DataFrame:
    rows=[]
    groups={k:g for k,g in frame.groupby("asset_location_id",dropna=False)}
    asset_rows=assets or [
        {
            "asset_location_id":k,
            "tenant_key":g.iloc[0]["tenant_key"],
            "external_id":g.iloc[0]["external_id"],
        }
        for k,g in groups.items()
    ]
    for asset in asset_rows:
        asset_id=asset["asset_location_id"]
        g=groups.get(asset_id)
        if g is None or g.empty:
            rows.append({
                "tenant_key":asset["tenant_key"],
                "asset_location_id":asset_id,
                "external_id":asset["external_id"],
                "gfm_matched_item_count":0,
                "gfm_covered_acquisition_count":0,
                "gfm_eligible_acquisition_count":0,
                "gfm_flood_positive_acquisition_count":0,
                "gfm_advisory_flagged_eligible_count":0,
                "gfm_flood_positive_acquisition_rate":None,
                "gfm_max_likelihood_on_positive":None,
                "quality_flag":"NO_ELIGIBLE_ACQUISITIONS",
            })
            continue
        first=g.iloc[0]
        covered=int(g["covered"].sum())
        eligible=int(g["eligible"].sum())
        positive=int(g["flood_positive"].sum())
        advisory=int(g["advisory_flagged"].sum())
        rate=None if eligible==0 else positive/eligible
        positive_like=g.loc[g["flood_positive"],"ensemble_likelihood"].dropna()
        quality="NO_ELIGIBLE_ACQUISITIONS" if eligible==0 else (
            "ADVISORY_FLAGS_PRESENT" if advisory>0 else "OK"
        )
        rows.append({
            "tenant_key":first["tenant_key"],
            "asset_location_id":asset_id,
            "external_id":first["external_id"],
            "gfm_matched_item_count":int(len(g)),
            "gfm_covered_acquisition_count":covered,
            "gfm_eligible_acquisition_count":eligible,
            "gfm_flood_positive_acquisition_count":positive,
            "gfm_advisory_flagged_eligible_count":advisory,
            "gfm_flood_positive_acquisition_rate":rate,
            "gfm_max_likelihood_on_positive":None if positive_like.empty else float(positive_like.max()),
            "quality_flag":quality,
        })
    return pd.DataFrame(rows)


def evidence_relation(jrc_depth_m,eligible_count:int,positive_count:int)->str:
    jrc_exposed=jrc_depth_m is not None and float(jrc_depth_m)>0
    if positive_count>0 and jrc_exposed:
        return "MODELLED_AND_OBSERVED"
    if positive_count>0 and not jrc_exposed:
        return "OBSERVED_FLOOD_REVIEW_MODELLED_POINT_HAZARD"
    if eligible_count>0 and jrc_exposed:
        return "MODELLED_NO_GFM_DETECTION_IN_WINDOW"
    if eligible_count>0:
        return "NO_GFM_DETECTION_AND_NO_MODELLED_POINT_DEPTH"
    return "NO_ELIGIBLE_GFM_EVIDENCE"


def insert_gfm_indicators(
    root:str|Path,
    summary:pd.DataFrame,
    *,
    source_artifact_id:str,
    start:str,
    end:str,
    run_id:str,
)->int:
    specs=[
        ("gfm_eligible_acquisition_count","count"),
        ("gfm_flood_positive_acquisition_count","count"),
        ("gfm_advisory_flagged_eligible_count","count"),
        ("gfm_flood_positive_acquisition_rate","share"),
    ]
    n=0
    with connect_catalog(root) as conn:
        for row in summary.to_dict(orient="records"):
            for indicator_id,unit in specs:
                val=row[indicator_id]
                if pd.isna(val):
                    val=None
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
                        MEASUREMENT_BASIS,source_artifact_id,"GFM_EVENT_0.1",
                        start,end,row["quality_flag"],
                        "NO_ELIGIBLE_ACQUISITIONS" if val is None else None,
                        run_id,utc_now(),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO asset_indicator_source(
                        asset_indicator_id,source_artifact_id,source_role
                    ) VALUES(?,?,?)
                    """,(cur.lastrowid,source_artifact_id,"GFM_EVENT_SERIES")
                )
                n+=1
        conn.commit()
    return n
