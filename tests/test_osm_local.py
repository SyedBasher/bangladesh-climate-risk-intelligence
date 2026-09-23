from pathlib import Path

import pandas as pd

from clr.local_assets import import_asset_rows
from clr.local_store import initialize_workspace
from clr.osm_local import (
    _allowed,
    _direction,
    haversine_m,
    import_route_dependencies,
    import_route_endpoints,
    nearest_network_node,
    route_dependencies,
)


def schema_path():
    return Path(__file__).resolve().parents[1] / "migrations" / "000_local_private_data_plane.sql"


def test_road_access_and_oneway_rules():
    assert _allowed({"highway":"primary"})
    assert not _allowed({"highway":"footway"})
    assert not _allowed({"highway":"primary","access":"private"})
    assert _allowed({"route":"ferry"})
    assert _direction({"highway":"primary","oneway":"yes"}) == "FORWARD"
    assert _direction({"highway":"primary","oneway":"-1"}) == "REVERSE"
    assert _direction({"highway":"primary"}) == "BOTH"
    assert _direction({"highway":"primary","junction":"roundabout"}) == "FORWARD"


def test_haversine_and_snap_quality():
    d=haversine_m(24.0,90.0,24.0,90.001)
    assert 90 < d < 110
    nodes=pd.DataFrame([
        {"node_id":1,"latitude":24.0,"longitude":90.0},
        {"node_id":2,"latitude":25.0,"longitude":91.0},
    ])
    snap=nearest_network_node(nodes,24.0,90.0005,max_snap_m=500)
    assert snap["node_id"]==1
    assert snap["accepted"]
    assert snap["snap_distance_m"] < 100


def test_route_dependency_requires_exact_resolved_asset_and_explicit_endpoint(tmp_path):
    root=tmp_path/"private_data"
    initialize_workspace(root,schema_path())
    import_asset_rows(root,[
        {
            "external_system":"SYNTH","external_id":"A","asset_type":"FACTORY",
            "latitude":24.0,"longitude":90.4,"coordinate_source":"SYNTHETIC",
            "site_identity_grade":"EXACT_SITE","coordinate_status":"RESOLVED",
        },
        {
            "external_system":"SYNTH","external_id":"B","asset_type":"FACTORY",
            "latitude":24.1,"longitude":90.5,"coordinate_source":"SYNTHETIC",
            "site_identity_grade":"PROBABLE_SITE","coordinate_status":"RESOLVED",
        },
    ])
    result=import_route_endpoints(root,[{
        "endpoint_key":"PORT_X","endpoint_type":"PORT",
        "latitude":22.3,"longitude":91.8,"source":"SYNTHETIC",
    }])
    assert result["inserted"]==1

    deps=import_route_dependencies(root,[
        {
            "external_system":"SYNTH","external_id":"A","endpoint_key":"PORT_X",
            "relationship":"PRIMARY","shipment_share":"1",
        },
        {
            "external_system":"SYNTH","external_id":"B","endpoint_key":"PORT_X",
            "relationship":"PRIMARY","shipment_share":"1",
        },
        {
            "external_system":"SYNTH","external_id":"A","endpoint_key":"MISSING",
            "relationship":"PRIMARY","shipment_share":"1",
        },
    ])
    assert deps["inserted"]==1
    assert len(deps["rejected"])==2
    current=route_dependencies(root)
    assert len(current)==1
    assert current[0]["external_id"]=="A"
    assert current[0]["endpoint_name"]=="PORT_X"
