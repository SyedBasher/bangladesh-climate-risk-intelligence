from pathlib import Path

import pandas as pd

from clr.local_assets import import_asset_rows
from clr.local_store import connect_catalog, initialize_workspace, register_source_file, start_processing_run
from clr.osm_local import import_route_dependencies, import_route_endpoints
from clr.route_flood_local import _edge_sample_points, publish_route_flood_exposure


def schema_path():
    return Path(__file__).resolve().parents[1] / "migrations" / "000_local_private_data_plane.sql"


def _register(root,source_id,filename,byte):
    p=root/"raw"/filename
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_bytes(byte)
    return register_source_file(
        root,source_id=source_id,provider="SYNTH",provider_version="v1",
        artifact_path=p,retrieved_at="2026-09-23T00:00:00+00:00"
    )


def test_edge_sampling_includes_both_ends():
    row={"length_m":250,"from_lat":24.0,"from_lon":90.0,"to_lat":24.0,"to_lon":90.003}
    pts=_edge_sample_points(row,100)
    assert pts[0]==(24.0,90.0)
    assert pts[-1]==(24.0,90.003)
    assert len(pts)==4


def test_unknown_hazard_coverage_withholds_route_share(tmp_path):
    root=tmp_path/"private_data"
    initialize_workspace(root,schema_path())
    import_asset_rows(root,[{
        "external_system":"SYNTH","external_id":"A","asset_type":"FACTORY",
        "latitude":24.0,"longitude":90.4,"coordinate_source":"SYNTHETIC",
        "site_identity_grade":"EXACT_SITE","coordinate_status":"RESOLVED",
    }])
    import_route_endpoints(root,[{
        "endpoint_key":"PORT_X","endpoint_type":"PORT","latitude":22.3,
        "longitude":91.8,"source":"SYNTHETIC",
    }])
    import_route_dependencies(root,[{
        "external_system":"SYNTH","external_id":"A","endpoint_key":"PORT_X",
        "relationship":"PRIMARY","shipment_share":"1",
    }])
    with connect_catalog(root) as conn:
        dep=conn.execute("SELECT asset_route_dependency_id FROM asset_route_dependency").fetchone()[0]

    osm=_register(root,"OSM_GEOFABRIK_BANGLADESH_260919","osm.pbf",b"osm")
    tile=_register(root,"JRC_TILE_EXTENTS","tiles.geojson",b"tiles")
    depth=_register(root,"DEPTH","depth.tif",b"depth")
    perm=_register(root,"PERM","perm.tif",b"perm")
    spur=_register(root,"SPUR","spur.tif",b"spur")
    run_id=start_processing_run(root,pipeline_name="route_flood_test",pipeline_version="0.1")

    annotated=pd.DataFrame([
        {
            "route_analysis_id":"baseline-1","tenant_key":"INTERNAL",
            "asset_route_dependency_id":dep,"external_system":"SYNTH","external_id":"A",
            "endpoint_name":"PORT_X","relationship":"PRIMARY","physical_edge_key":"1:2",
            "osm_way_id":10,"road_class":"primary","bridge":False,"ferry":False,
            "length_m":100.0,"cumulative_end_m":100.0,"shared_dependency_count":1,
            "hazard_exposed":True,"jrc_max_valid_depth_m":0.4,
        },
        {
            "route_analysis_id":"baseline-1","tenant_key":"INTERNAL",
            "asset_route_dependency_id":dep,"external_system":"SYNTH","external_id":"A",
            "endpoint_name":"PORT_X","relationship":"PRIMARY","physical_edge_key":"2:3",
            "osm_way_id":11,"road_class":"primary","bridge":False,"ferry":False,
            "length_m":100.0,"cumulative_end_m":200.0,"shared_dependency_count":1,
            "hazard_exposed":None,"jrc_max_valid_depth_m":None,
        },
    ])
    source_map={
        "return_period":100,"tile_extents":tile,
        "records":{
            ("TILE","DEPTH",100):depth,
            ("TILE","PERMANENT_WATER_MASK",None):perm,
            ("TILE","SPURIOUS_DEPTH_MASK",None):spur,
        },
    }
    summary,_,_=publish_route_flood_exposure(root,annotated,source_map,run_id=run_id)
    row=summary.iloc[0]
    assert row["hazard_exposed_length_m"]==100
    assert row["hazard_unknown_length_m"]==100
    assert pd.isna(row["hazard_exposed_share"])
    assert row["quality_flag"]=="PARTIAL_HAZARD_COVERAGE"

    with connect_catalog(root) as conn:
        stored=conn.execute(
            "SELECT hazard_exposed_share,hazard_detour_ratio,isolation_flag FROM logistics_route_analysis WHERE scenario_id='JRC_RP100_EXPOSURE_ONLY'"
        ).fetchone()
    assert stored[0] is None
    assert stored[1] is None
    assert stored[2] is None
