from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from clr.local_assets import import_asset_rows,accepted_assets
from clr.local_store import (
    connect_catalog,initialize_workspace,register_source_file,start_processing_run
)
from clr.worldcover_local import (
    build_land_context,
    insert_land_indicators,
    tile_filename,
    tile_id_for_point,
    tile_url,
)


ROOT=Path(__file__).resolve().parents[1]


def schema_path():
    return ROOT/"migrations"/"000_local_private_data_plane.sql"


def _write_worldcover(path):
    data=np.full((300,300),40,dtype="uint8")
    data[135:165,135:165]=50
    with rasterio.open(
        path,"w",driver="GTiff",
        height=300,width=300,count=1,dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(0.0,0.03,0.0001,0.0001),
        nodata=0,
    ) as ds:
        ds.write(data,1)


def test_worldcover_tile_naming():
    assert tile_id_for_point(23.95,90.38)=="N21E090"
    assert tile_id_for_point(24.01,90.38)=="N24E090"
    assert tile_filename("N21E090")==(
        "ESA_WorldCover_10m_2021_v200_N21E090_Map.tif"
    )
    assert tile_url("N21E090").endswith(
        "/v200/2021/map/ESA_WorldCover_10m_2021_v200_N21E090_Map.tif"
    )


def test_worldcover_point_and_radius_shares_with_lineage(tmp_path):
    root=tmp_path/"private_data"
    initialize_workspace(root,schema_path())
    import_asset_rows(root,[{
        "external_system":"SYNTH","external_id":"A","asset_type":"FACTORY",
        "latitude":0.015,"longitude":0.015,"coordinate_source":"SYNTHETIC",
        "site_identity_grade":"EXACT_SITE","coordinate_status":"RESOLVED",
    }])
    asset=accepted_assets(root)[0]

    raster=root/"raw"/"worldcover.tif"
    raster.parent.mkdir(parents=True,exist_ok=True)
    _write_worldcover(raster)
    source=register_source_file(
        root,source_id="WC",provider="ESA WorldCover",
        provider_version="WorldCover_2021_v200",artifact_path=raster,
        retrieved_at="2026-09-24T00:00:00+00:00",
    )

    frame=build_land_context(
        root,[asset],{"N00E000":source},radii_m=(250.0,)
    )
    assert len(frame)==1
    row=frame.iloc[0]
    assert row["point_class_code"]==50
    assert row["point_class_label"]=="built_up"
    assert row["quality_flag"]=="OK"
    assert row["valid_pixel_share"]>0.99

    shares=[
        row[c] for c in frame.columns if c.startswith("class_")
    ]
    assert abs(sum(shares)-1.0)<1e-9
    assert row["class_50_built_up_share"]>0
    assert row["class_40_cropland_share"]>0

    run_id=start_processing_run(
        root,pipeline_name="worldcover_test",pipeline_version="0.1"
    )
    n=insert_land_indicators(root,frame,run_id=run_id)
    assert n==14

    with connect_catalog(root) as conn:
        roles={
            x["source_role"]
            for x in conn.execute(
                "SELECT DISTINCT source_role FROM asset_indicator_source"
            ).fetchall()
        }
        label=conn.execute(
            """
            SELECT value_text FROM asset_indicator
            WHERE indicator_id='worldcover2021_class_label_at_site'
            """
        ).fetchone()["value_text"]
        built=conn.execute(
            """
            SELECT value_numeric FROM asset_indicator
            WHERE indicator_id='worldcover2021_built_up_share_within_250m'
            """
        ).fetchone()["value_numeric"]
    assert roles=={"ESA_WORLDCOVER"}
    assert label=="built_up"
    assert 0<built<1
