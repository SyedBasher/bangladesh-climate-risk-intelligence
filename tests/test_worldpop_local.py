from pathlib import Path

import pandas as pd

from clr.local_assets import import_asset_rows
from clr.local_store import connect_catalog, initialize_workspace, start_processing_run
from clr.worldpop_local import (
    build_population_context,
    geodesic_circle,
    insert_population_indicators,
)


def schema_path():
    return Path(__file__).resolve().parents[1]/"migrations"/"000_local_private_data_plane.sql"


class FakeResponse:
    def __init__(self,payload):
        self._payload=payload
    def raise_for_status(self):
        return None
    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.tasks={}
        self.n=0
    def post(self,url,json,headers,timeout):
        self.n+=1
        task=f"T{self.n}"
        radius_hint=len(json["geojson"]["coordinates"][0])
        self.tasks[task]={
            "status":"success",
            "result":{
                "total_population":1000.0*self.n,
                "area_km2":3.14159*self.n*self.n,
                "data_year":2025,
                "data_source":"WorldPop Global 2 Population Data",
                "population_density":318.31,
            },
        }
        return FakeResponse({"task_id":task})
    def get(self,url,headers,timeout):
        task=url.rsplit("/",1)[-1]
        return FakeResponse(self.tasks[task])


def test_geodesic_circle_is_closed_and_reasonable():
    geom=geodesic_circle(90.4,24.0,1.0,vertices=36)
    ring=geom["coordinates"][0]
    assert len(ring)==37
    assert ring[0]==ring[-1]
    assert all(len(pt)==2 for pt in ring)


def test_worldpop_queries_are_cached_and_lineage_is_written(tmp_path):
    root=tmp_path/"private_data"
    initialize_workspace(root,schema_path())
    import_asset_rows(root,[{
        "external_system":"SYNTH","external_id":"A","asset_type":"FACTORY",
        "latitude":24.0,"longitude":90.4,"coordinate_source":"SYNTHETIC",
        "site_identity_grade":"PROBABLE_SITE","coordinate_status":"RESOLVED",
    }])
    from clr.local_assets import coarse_climate_assets
    assets=coarse_climate_assets(root)
    session=FakeSession()

    frame=build_population_context(
        root,assets,year=2025,radii_km=(1.0,5.0),session=session
    )
    assert len(frame)==2
    assert session.n==2
    assert set(frame["radius_km"])=={1.0,5.0}
    assert set(frame["data_year"])=={2025}

    # Re-running should reuse the exact private source snapshots.
    again=build_population_context(
        root,assets,year=2025,radii_km=(1.0,5.0),session=session
    )
    assert len(again)==2
    assert session.n==2

    run_id=start_processing_run(
        root,pipeline_name="worldpop_test",pipeline_version="0.1"
    )
    n=insert_population_indicators(root,frame,run_id=run_id)
    assert n==4

    with connect_catalog(root) as conn:
        roles={
            row["source_role"]
            for row in conn.execute(
                "SELECT DISTINCT source_role FROM asset_indicator_source"
            ).fetchall()
        }
        names={
            row["indicator_id"]
            for row in conn.execute(
                "SELECT indicator_id FROM asset_indicator"
            ).fetchall()
        }
    assert roles=={"WORLDPOP_POPULATION"}
    assert "worldpop_population_within_1km" in names
    assert "worldpop_population_density_within_5km" in names
