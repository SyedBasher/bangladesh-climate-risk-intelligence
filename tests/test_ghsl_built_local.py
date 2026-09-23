from pathlib import Path
import zipfile

import numpy as np
import rasterio
from rasterio.transform import from_origin

from clr.ghsl_built_local import (
    build_built_context,
    discover_tile_pairs,
    insert_built_indicators,
    register_tile_pairs,
)
from clr.local_assets import import_asset_rows,coarse_climate_assets
from clr.local_store import connect_catalog,initialize_workspace,start_processing_run


def schema_path():
    return Path(__file__).resolve().parents[1]/"migrations"/"000_local_private_data_plane.sql"


def _write_zip(directory,component,value):
    tile="R5_C20"
    if component=="TOTAL":
        name=f"GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100_V1_0_{tile}.zip"
        tif=name[:-4]+".tif"
    else:
        name=f"GHS_BUILT_S_NRES_E2020_GLOBE_R2023A_54009_100_V1_0_{tile}.zip"
        tif=name[:-4]+".tif"

    raster=directory/tif
    data=np.full((40,40),float(value),dtype="float32")
    with rasterio.open(
        raster,"w",driver="GTiff",
        height=40,width=40,count=1,dtype="float32",
        crs="EPSG:3857",
        transform=from_origin(-2000,2000,100,100),
        nodata=-9999,
    ) as ds:
        ds.write(data,1)

    package=directory/name
    with zipfile.ZipFile(package,"w") as z:
        z.write(raster,arcname=tif)
    raster.unlink()
    return package


def test_ghsl_tile_pair_discovery_requires_matching_total_and_nres(tmp_path):
    _write_zip(tmp_path,"TOTAL",20)
    _write_zip(tmp_path,"NRES",5)
    pairs=discover_tile_pairs(tmp_path)
    assert len(pairs)==1
    assert pairs[0]["tile_id"]=="R5_C20"


def test_ghsl_context_and_lineage(tmp_path):
    tile_dir=tmp_path/"tiles"
    tile_dir.mkdir()
    _write_zip(tile_dir,"TOTAL",20)
    _write_zip(tile_dir,"NRES",5)

    root=tmp_path/"private_data"
    initialize_workspace(root,schema_path())
    import_asset_rows(root,[{
        "external_system":"SYNTH","external_id":"A","asset_type":"FACTORY",
        "latitude":0.0,"longitude":0.0,"coordinate_source":"SYNTHETIC",
        "site_identity_grade":"EXACT_SITE","coordinate_status":"RESOLVED",
    }])
    assets=coarse_climate_assets(root)
    bundles=register_tile_pairs(root,tile_dir)
    frame=build_built_context(
        root,assets,bundles,radii_km=(1.0,)
    )
    assert len(frame)==1
    row=frame.iloc[0]
    assert row["quality_flag"]=="OK"
    assert row["total_built_surface_m2"]>0
    assert row["nres_built_surface_m2"]>0
    assert abs(row["nres_share_of_built_surface"]-0.25)<1e-9
    assert 0<row["built_surface_fraction_of_buffer"]<1
    assert row["tile_coverage_share"]>0.995

    run_id=start_processing_run(
        root,pipeline_name="ghsl_test",pipeline_version="0.1"
    )
    n=insert_built_indicators(
        root,frame,bundles,run_id=run_id
    )
    assert n==4

    with connect_catalog(root) as conn:
        roles={
            x["source_role"]
            for x in conn.execute(
                "SELECT DISTINCT source_role FROM asset_indicator_source"
            ).fetchall()
        }
        primary={
            x["indicator_id"]:x["source_id"]
            for x in conn.execute(
                """
                SELECT ai.indicator_id,sa.source_id
                FROM asset_indicator ai
                JOIN source_artifact sa
                  ON ai.source_artifact_id=sa.source_artifact_id
                """
            ).fetchall()
        }
    assert roles=={"GHSL_BUILT_TOTAL","GHSL_BUILT_NRES"}
    assert "TOTAL" in primary[
        "ghsl2020_total_built_surface_within_1km_m2"
    ]
    assert "NRES" in primary[
        "ghsl2020_nres_built_surface_within_1km_m2"
    ]


def test_ghsl_missing_neighbor_tiles_returns_null_not_partial_value(tmp_path):
    tile_dir=tmp_path/"tiles"
    tile_dir.mkdir()
    _write_zip(tile_dir,"TOTAL",20)
    _write_zip(tile_dir,"NRES",5)

    root=tmp_path/"private_data"
    initialize_workspace(root,schema_path())
    import_asset_rows(root,[{
        "external_system":"SYNTH","external_id":"EDGE","asset_type":"FACTORY",
        "latitude":0.0,"longitude":0.0175,"coordinate_source":"SYNTHETIC",
        "site_identity_grade":"EXACT_SITE","coordinate_status":"RESOLVED",
    }])
    assets=coarse_climate_assets(root)
    bundles=register_tile_pairs(root,tile_dir)
    frame=build_built_context(
        root,assets,bundles,radii_km=(1.0,)
    )
    row=frame.iloc[0]
    assert row["quality_flag"]=="INCOMPLETE_TILE_COVERAGE"
    assert row["total_built_surface_m2"] is None
    assert row["nres_built_surface_m2"] is None
