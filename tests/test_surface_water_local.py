from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin

from clr.local_assets import import_asset_rows,accepted_assets
from clr.local_store import (
    connect_catalog,initialize_workspace,register_source_file,start_processing_run
)
from clr.surface_water_local import (
    build_surface_water_context,
    insert_surface_water_indicators,
    tile_id_for_point,
    tile_url,
)


ROOT=Path(__file__).resolve().parents[1]


def schema_path():
    return ROOT/"migrations"/"000_local_private_data_plane.sql"


def _write_raster(path,value,high=False):
    data=np.full((100,100),float(value),dtype="float32")
    if high:
        data[50,53]=95.0
    with rasterio.open(
        path,"w",driver="GTiff",
        height=100,width=100,count=1,dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(0.0,0.03,0.0003,0.0003),
        nodata=255,
    ) as ds:
        ds.write(data,1)


def _source(root,path,source_id):
    return register_source_file(
        root,source_id=source_id,provider="JRC",
        provider_version="GSW_v1.5_2024",artifact_path=path,
        retrieved_at="2026-09-24T00:00:00+00:00",
    )


def test_gsw_tile_naming_and_urls():
    assert tile_id_for_point(24.2,90.4)=="90E_20N"
    assert tile_id_for_point(24.2,89.9)=="80E_20N"
    assert tile_id_for_point(-2.0,-1.0)=="10W_10S"
    assert tile_url("occurrence","90E_20N").endswith(
        "/occurrence/occurrence_90E_20N_v1_5_2024.tif"
    )


def test_surface_water_point_and_distance_context(tmp_path):
    root=tmp_path/"private_data"
    initialize_workspace(root,schema_path())
    import_asset_rows(root,[{
        "external_system":"SYNTH","external_id":"A","asset_type":"FACTORY",
        "latitude":0.015,"longitude":0.015,"coordinate_source":"SYNTHETIC",
        "site_identity_grade":"EXACT_SITE","coordinate_status":"RESOLVED",
    }])
    asset=accepted_assets(root)[0]

    occurrence=root/"raw"/"occurrence.tif"
    recurrence=root/"raw"/"recurrence.tif"
    occurrence.parent.mkdir(parents=True,exist_ok=True)
    _write_raster(occurrence,40,high=True)
    _write_raster(recurrence,60,high=False)
    occ=_source(root,occurrence,"OCC")
    rec=_source(root,recurrence,"REC")

    records={"0E_0N":{"occurrence":occ,"recurrence":rec}}
    frame=build_surface_water_context(
        root,[asset],records,
        occurrence_threshold_pct=90,
        search_radius_km=1,
    )
    row=frame.iloc[0]
    assert row["occurrence_pct_at_site"]==40
    assert row["recurrence_pct_at_site"]==60
    assert 0 < row["distance_to_high_occurrence_water_m"] < 500
    assert row["distance_quality_flag"]=="OK"

    run_id=start_processing_run(
        root,pipeline_name="surface_water_test",pipeline_version="0.1"
    )
    n=insert_surface_water_indicators(root,frame,run_id=run_id)
    assert n==3
    with connect_catalog(root) as conn:
        names={
            x["indicator_id"]
            for x in conn.execute("SELECT indicator_id FROM asset_indicator").fetchall()
        }
        roles={
            x["source_role"]
            for x in conn.execute(
                "SELECT DISTINCT source_role FROM asset_indicator_source"
            ).fetchall()
        }
    assert "jrc_gsw15_occurrence_pct_at_site" in names
    assert "jrc_gsw15_recurrence_pct_at_site" in names
    assert "jrc_gsw15_distance_to_occurrence_ge90pct_water_m" in names
    assert roles=={"JRC_GSW_OCCURRENCE","JRC_GSW_RECURRENCE"}


def test_no_high_occurrence_water_is_explicit_null(tmp_path):
    root=tmp_path/"private_data"
    initialize_workspace(root,schema_path())
    import_asset_rows(root,[{
        "external_system":"SYNTH","external_id":"A","asset_type":"FACTORY",
        "latitude":0.015,"longitude":0.015,"coordinate_source":"SYNTHETIC",
        "site_identity_grade":"EXACT_SITE","coordinate_status":"RESOLVED",
    }])
    asset=accepted_assets(root)[0]

    occurrence=root/"raw"/"occurrence.tif"
    recurrence=root/"raw"/"recurrence.tif"
    occurrence.parent.mkdir(parents=True,exist_ok=True)
    _write_raster(occurrence,40,high=False)
    _write_raster(recurrence,60,high=False)
    occ=_source(root,occurrence,"OCC")
    rec=_source(root,recurrence,"REC")
    frame=build_surface_water_context(
        root,[asset],{"0E_0N":{"occurrence":occ,"recurrence":rec}},
        occurrence_threshold_pct=90,search_radius_km=1,
    )
    row=frame.iloc[0]
    assert pd.isna(row["distance_to_high_occurrence_water_m"])
    assert row["distance_quality_flag"]=="NO_HIGH_OCCURRENCE_WATER_WITHIN_SEARCH_RADIUS"
