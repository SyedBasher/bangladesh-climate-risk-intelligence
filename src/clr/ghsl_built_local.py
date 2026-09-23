from __future__ import annotations

import math
import re
import shutil
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import CRS, Transformer
from rasterio.windows import Window, from_bounds
from shapely.geometry import Point, box
from shapely.ops import unary_union

from .local_store import (
    connect_catalog,
    parquet_partition_dir,
    register_parquet_dataset,
    register_source_file,
    sha256_file,
    source_snapshot_path,
    utc_now,
)

PROVIDER="European Commission Joint Research Centre / GHSL"
PROVIDER_VERSION="GHS_BUILT_S_R2023A_V1_0"
EPOCH=2020
RESOLUTION_M=100
RADII_KM=(1.0,5.0,10.0)
MEASUREMENT_BASIS="CALCULATED_FROM_STATIC_BUILT_SURFACE"

TOTAL_RE=re.compile(
    r"^GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100_V1_0_(R\d+_C\d+)\.zip$"
)
NRES_RE=re.compile(
    r"^GHS_BUILT_S_NRES_E2020_GLOBE_R2023A_54009_100_V1_0_(R\d+_C\d+)\.zip$"
)
TOTAL_BASE=(
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/"
    "GHS_BUILT_S_GLOBE_R2023A/"
    "GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100/V1-0/tiles/"
)
NRES_BASE=(
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/"
    "GHS_BUILT_S_GLOBE_R2023A/"
    "GHS_BUILT_S_NRES_E2020_GLOBE_R2023A_54009_100/V1-0/tiles/"
)


def discover_tile_pairs(tile_dir:str|Path)->list[dict]:
    tile_dir=Path(tile_dir).resolve()
    if not tile_dir.is_dir():
        raise FileNotFoundError(tile_dir)
    total={}
    nres={}
    for path in sorted(tile_dir.glob("*.zip")):
        m=TOTAL_RE.match(path.name)
        if m:
            total[m.group(1)]=path
            continue
        m=NRES_RE.match(path.name)
        if m:
            nres[m.group(1)]=path
    if not total and not nres:
        raise ValueError("No supported GHSL 2020 100m tile ZIPs found")
    if set(total)!=set(nres):
        missing_total=sorted(set(nres)-set(total))
        missing_nres=sorted(set(total)-set(nres))
        raise ValueError(
            f"GHSL TOTAL/NRES tile mismatch; missing_total={missing_total}, "
            f"missing_nres={missing_nres}"
        )
    return [
        {"tile_id":tile,"total_zip":total[tile],"nres_zip":nres[tile]}
        for tile in sorted(total)
    ]


def _register_package(
    root:Path,
    zip_path:Path,
    *,
    component:str,
    tile_id:str,
)->dict:
    component=component.upper()
    if component not in {"TOTAL","NRES"}:
        raise ValueError("component must be TOTAL or NRES")
    regex=TOTAL_RE if component=="TOTAL" else NRES_RE
    if not regex.match(zip_path.name):
        raise ValueError(f"Unexpected GHSL {component} filename: {zip_path.name}")
    digest=sha256_file(zip_path)
    destination=source_snapshot_path(
        root,"JRC_GHSL",f"GHS_BUILT_S_{component}",
        PROVIDER_VERSION,digest,zip_path.name,
    )
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        if sha256_file(destination)!=digest:
            raise RuntimeError("Content-addressed GHSL package has unexpected bytes")
    else:
        shutil.copy2(zip_path,destination)

    source_url=(TOTAL_BASE if component=="TOTAL" else NRES_BASE)+zip_path.name
    source_id=f"GHSL_BUILT_{component}_E2020_{tile_id}_PACKAGE"
    return register_source_file(
        root,source_id=source_id,provider=PROVIDER,
        provider_version=PROVIDER_VERSION,
        artifact_path=destination,media_type="application/zip",
        valid_time_start="2020-01-01",valid_time_end="2020-12-31",
        retrieval_status="COMPLETE",
        note=(
            f"Official GHSL GHS-BUILT-S R2023A 2020 {component} 100m tile package. "
            "Built-up surface is expressed in square metres; it is not property value."
        ),
        request_parameters={
            "source_url":source_url,"epoch":EPOCH,
            "resolution_m":RESOLUTION_M,"component":component,
            "tile_id":tile_id,
        },
    )


def _extract_raster(
    root:Path,
    package:dict,
    *,
    component:str,
    tile_id:str,
)->dict:
    package_path=root/package["local_path"]
    with zipfile.ZipFile(package_path) as z:
        tifs=[m for m in z.namelist() if Path(m).suffix.lower() in {".tif",".tiff"}]
        if len(tifs)!=1:
            raise ValueError(
                f"GHSL package {package_path.name} must contain exactly one TIFF; found {tifs}"
            )
        member=tifs[0]
        tmp=root/"tmp"/Path(member).name
        tmp.parent.mkdir(parents=True,exist_ok=True)
        if tmp.exists():
            tmp.unlink()
        with z.open(member) as src,open(tmp,"wb") as dst:
            shutil.copyfileobj(src,dst)

    digest=sha256_file(tmp)
    destination=source_snapshot_path(
        root,"JRC_GHSL",f"GHS_BUILT_S_{component}_RASTER",
        PROVIDER_VERSION,digest,tmp.name,
    )
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        if sha256_file(destination)!=digest:
            raise RuntimeError("Content-addressed GHSL raster has unexpected bytes")
        tmp.unlink()
    else:
        tmp.replace(destination)

    record=register_source_file(
        root,
        source_id=f"GHSL_BUILT_{component}_E2020_{tile_id}_RASTER",
        provider=PROVIDER,provider_version=PROVIDER_VERSION,
        artifact_path=destination,media_type="image/tiff",
        valid_time_start="2020-01-01",valid_time_end="2020-12-31",
        retrieval_status="COMPLETE",
        note=(
            f"Unmodified TIFF extracted from official GHSL {component} tile package "
            f"{package['source_artifact_id']}."
        ),
        request_parameters={
            "parent_package_source_artifact_id":package["source_artifact_id"],
            "epoch":EPOCH,"resolution_m":RESOLUTION_M,
            "component":component,"tile_id":tile_id,
        },
    )
    return record


def register_tile_pairs(root:str|Path,tile_dir:str|Path)->list[dict]:
    root=Path(root).resolve()
    bundles=[]
    for pair in discover_tile_pairs(tile_dir):
        tile=pair["tile_id"]
        total_pkg=_register_package(
            root,pair["total_zip"],component="TOTAL",tile_id=tile
        )
        nres_pkg=_register_package(
            root,pair["nres_zip"],component="NRES",tile_id=tile
        )
        total_raster=_extract_raster(
            root,total_pkg,component="TOTAL",tile_id=tile
        )
        nres_raster=_extract_raster(
            root,nres_pkg,component="NRES",tile_id=tile
        )
        bundles.append({
            "tile_id":tile,
            "total_package":total_pkg,"nres_package":nres_pkg,
            "total_raster":total_raster,"nres_raster":nres_raster,
        })
    return bundles


def _validate_rasters(root:Path,bundles:list[dict])->dict:
    if not bundles:
        raise ValueError("No GHSL tile bundles supplied")
    total_paths=[root/b["total_raster"]["local_path"] for b in bundles]
    nres_paths=[root/b["nres_raster"]["local_path"] for b in bundles]

    properties=[]
    bounds_by_component={"TOTAL":[],"NRES":[]}
    for component,paths in (("TOTAL",total_paths),("NRES",nres_paths)):
        for path in paths:
            with rasterio.open(path) as ds:
                if ds.count!=1:
                    raise ValueError(f"GHSL raster must have one band: {path}")
                if ds.crs is None:
                    raise ValueError(f"GHSL raster has no CRS: {path}")
                crs=CRS.from_user_input(ds.crs)
                if not crs.is_projected:
                    raise ValueError(f"GHSL 100m workflow requires projected CRS: {path}")
                if abs(ds.transform.b)>1e-9 or abs(ds.transform.d)>1e-9:
                    raise ValueError("Rotated GHSL rasters are not supported")
                px=abs(float(ds.transform.a)); py=abs(float(ds.transform.e))
                if not (95<=px<=105 and 95<=py<=105):
                    raise ValueError(
                        f"GHSL raster pixel size must be approximately 100m; got {px},{py}"
                    )
                properties.append((crs.to_wkt(),round(px,6),round(py,6)))
                bounds_by_component[component].append(box(*ds.bounds))

    if len(set(properties))!=1:
        raise ValueError("GHSL TOTAL/NRES rasters must share CRS and resolution")

    for component,geoms in bounds_by_component.items():
        for i,a in enumerate(geoms):
            for b in geoms[i+1:]:
                if a.intersection(b).area>1e-6:
                    raise ValueError(f"Overlapping GHSL {component} tiles are not supported")

    total_union=unary_union(bounds_by_component["TOTAL"])
    nres_union=unary_union(bounds_by_component["NRES"])
    if total_union.symmetric_difference(nres_union).area>1e-3:
        raise ValueError("GHSL TOTAL and NRES tile coverage must match")

    return {
        "crs":CRS.from_wkt(properties[0][0]),
        "pixel_area_m2":properties[0][1]*properties[0][2],
        "coverage_geometry":total_union,
        "total_paths":total_paths,
        "nres_paths":nres_paths,
    }


def _sum_circle(
    paths:list[Path],
    x:float,y:float,radius_m:float,
)->dict:
    total_value=0.0
    selected_cells=0
    valid_cells=0
    nodata_cells=0

    for path in paths:
        with rasterio.open(path) as ds:
            if not (
                ds.bounds.left < x+radius_m
                and ds.bounds.right > x-radius_m
                and ds.bounds.bottom < y+radius_m
                and ds.bounds.top > y-radius_m
            ):
                continue
            raw=from_bounds(
                x-radius_m,y-radius_m,x+radius_m,y+radius_m,
                transform=ds.transform,
            )
            full=Window(0,0,ds.width,ds.height)
            try:
                window=raw.intersection(full).round_offsets().round_lengths()
            except Exception:
                continue
            if window.width<=0 or window.height<=0:
                continue
            arr=ds.read(1,window=window,masked=True)
            transform=ds.window_transform(window)
            rows=np.arange(arr.shape[0],dtype=float)+0.5
            cols=np.arange(arr.shape[1],dtype=float)+0.5
            xs=transform.c+cols*transform.a
            ys=transform.f+rows*transform.e
            mask=(
                (xs[np.newaxis,:]-x)**2
                +(ys[:,np.newaxis]-y)**2
                <=float(radius_m)**2
            )
            selected_cells+=int(mask.sum())
            valid=mask & ~np.ma.getmaskarray(arr) & np.isfinite(np.asarray(arr))
            valid_cells+=int(valid.sum())
            nodata_cells+=int(mask.sum()-valid.sum())
            if valid.any():
                total_value+=float(np.asarray(arr,dtype=float)[valid].sum())

    return {
        "sum_value":total_value,
        "selected_cells":selected_cells,
        "valid_cells":valid_cells,
        "nodata_cells":nodata_cells,
    }


def build_built_context(
    root:str|Path,
    assets:list[dict],
    bundles:list[dict],
    *,
    radii_km:tuple[float,...]=RADII_KM,
)->pd.DataFrame:
    root=Path(root).resolve()
    cfg=_validate_rasters(root,bundles)
    transformer=Transformer.from_crs("EPSG:4326",cfg["crs"],always_xy=True)
    radii=tuple(float(x) for x in radii_km)
    rows=[]

    for asset in assets:
        x,y=transformer.transform(
            float(asset["longitude"]),float(asset["latitude"])
        )
        for radius_km in radii:
            radius_m=radius_km*1000.0
            circle=Point(x,y).buffer(radius_m,resolution=96)
            coverage=float(
                circle.intersection(cfg["coverage_geometry"]).area/circle.area
            )
            total=_sum_circle(cfg["total_paths"],x,y,radius_m)
            nres=_sum_circle(cfg["nres_paths"],x,y,radius_m)

            if total["selected_cells"]!=nres["selected_cells"]:
                raise ValueError("GHSL TOTAL/NRES sampled cell counts differ")

            selected=max(1,total["selected_cells"])
            nodata_share=max(
                total["nodata_cells"],nres["nodata_cells"]
            )/selected

            if coverage<0.995:
                quality="INCOMPLETE_TILE_COVERAGE"
            elif nodata_share>0.01:
                quality="SOURCE_NODATA_WITHIN_BUFFER"
            else:
                quality="OK"

            total_m2=None if quality!="OK" else float(total["sum_value"])
            nres_m2=None if quality!="OK" else float(nres["sum_value"])
            circle_area=float(circle.area)
            built_fraction=(
                None if total_m2 is None else total_m2/circle_area
            )
            nres_share=(
                None
                if total_m2 is None or total_m2<=0
                else nres_m2/total_m2
            )

            rows.append({
                "tenant_key":asset["tenant_key"],
                "asset_location_id":asset["asset_location_id"],
                "external_system":asset["external_system"],
                "external_id":asset["external_id"],
                "site_identity_grade":asset["site_identity_grade"],
                "epoch":EPOCH,"radius_km":radius_km,
                "total_built_surface_m2":total_m2,
                "nres_built_surface_m2":nres_m2,
                "built_surface_fraction_of_buffer":built_fraction,
                "nres_share_of_built_surface":nres_share,
                "tile_coverage_share":coverage,
                "nodata_cell_share":nodata_share,
                "quality_flag":quality,
            })
    return pd.DataFrame(rows)


def write_built_parquet(
    root:str|Path,
    frame:pd.DataFrame,
    *,
    run_id:str,
)->Path:
    directory=parquet_partition_dir(
        root,layer="indicators",dataset="ghsl_built_environment_context",
        partitions={"epoch":EPOCH,"resolution_m":RESOLUTION_M},
    )
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/f"built-context-{run_id}.parquet"
    frame.to_parquet(path,index=False)
    register_parquet_dataset(
        root,dataset_name="ghsl_built_environment_context",
        layer="indicators",parquet_path=path,
        partition_spec={"epoch":EPOCH,"resolution_m":RESOLUTION_M},
        row_count=len(frame),run_id=run_id,
    )
    return path


def _radius_token(radius:float)->str:
    return str(int(radius)) if float(radius).is_integer() else str(radius).replace(".","p")


def insert_built_indicators(
    root:str|Path,
    frame:pd.DataFrame,
    bundles:list[dict],
    *,
    run_id:str,
)->int:
    total_sources=[
        b["total_raster"]["source_artifact_id"] for b in bundles
    ]
    nres_sources=[
        b["nres_raster"]["source_artifact_id"] for b in bundles
    ]
    count=0
    with connect_catalog(root) as conn:
        for row in frame.to_dict(orient="records"):
            token=_radius_token(float(row["radius_km"]))
            specs=[
                (
                    f"ghsl2020_total_built_surface_within_{token}km_m2",
                    row["total_built_surface_m2"],"m2","TOTAL"
                ),
                (
                    f"ghsl2020_nres_built_surface_within_{token}km_m2",
                    row["nres_built_surface_m2"],"m2","NRES"
                ),
                (
                    f"ghsl2020_built_surface_fraction_within_{token}km",
                    row["built_surface_fraction_of_buffer"],"share","BOTH"
                ),
                (
                    f"ghsl2020_nres_share_of_built_surface_within_{token}km",
                    row["nres_share_of_built_surface"],"share","BOTH"
                ),
            ]
            for indicator_id,value,unit,lineage in specs:
                value=None if value is None or pd.isna(value) else float(value)
                null_reason=None if value is not None else row["quality_flag"]
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
                        (total_sources[0] if total_sources else None),
                        "GHSL_BUILT_RADIUS_0.1",
                        "2020-01-01","2020-12-31",
                        row["quality_flag"],null_reason,run_id,utc_now(),
                    ),
                )
                if lineage in {"TOTAL","BOTH"}:
                    for sid in total_sources:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO asset_indicator_source(
                                asset_indicator_id,source_artifact_id,source_role
                            ) VALUES(?,?,?)
                            """,(cur.lastrowid,sid,"GHSL_BUILT_TOTAL")
                        )
                if lineage in {"NRES","BOTH"}:
                    for sid in nres_sources:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO asset_indicator_source(
                                asset_indicator_id,source_artifact_id,source_role
                            ) VALUES(?,?,?)
                            """,(cur.lastrowid,sid,"GHSL_BUILT_NRES")
                        )
                count+=1
        conn.commit()
    return count
