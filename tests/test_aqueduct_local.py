from pathlib import Path

from shapely.geometry import Polygon

from clr.aqueduct_local import (
    insert_aqueduct_indicators,match_assets_to_aqueduct
)
from clr.local_assets import accepted_assets,import_asset_rows
from clr.local_store import (
    connect_catalog,initialize_workspace,register_source_file,start_processing_run
)


def schema_path():
    return Path(__file__).resolve().parents[1]/"migrations"/"000_local_private_data_plane.sql"


def _assets():
    return [
        {
            "tenant_key":"INTERNAL","asset_location_id":"A","external_id":"A",
            "latitude":24.0,"longitude":90.0,
        },
        {
            "tenant_key":"INTERNAL","asset_location_id":"B","external_id":"B",
            "latitude":26.0,"longitude":92.0,
        },
    ]


def test_aqueduct_point_in_polygon_and_no_match():
    features=[{
        "geometry":Polygon([(89,23),(91,23),(91,25),(89,25)]),
        "properties":{
            "bws_raw":0.45,"bws_score":3.2,"bws_label":"High",
            "bws_cat":3,"pfaf_id":123456,
        },
    }]
    out=match_assets_to_aqueduct(_assets(),features).set_index("external_id")
    assert out.loc["A","match_status"]=="MATCHED"
    assert out.loc["A","bws_raw"]==0.45
    assert out.loc["A","bws_label"]=="High"
    assert out.loc["B","match_status"]=="NO_MATCH"
    assert out.loc["B","null_reason"]=="NO_AQUEDUCT_POLYGON_MATCH"


def test_aqueduct_boundary_overlap_fails_closed():
    assets=[{
        "tenant_key":"INTERNAL","asset_location_id":"A","external_id":"A",
        "latitude":24.0,"longitude":90.0,
    }]
    features=[
        {
            "geometry":Polygon([(89,23),(90,23),(90,25),(89,25)]),
            "properties":{"bws_raw":0.1,"bws_score":1.0,"bws_label":"Low","bws_cat":0},
        },
        {
            "geometry":Polygon([(90,23),(91,23),(91,25),(90,25)]),
            "properties":{"bws_raw":0.5,"bws_score":3.0,"bws_label":"High","bws_cat":3},
        },
    ]
    out=match_assets_to_aqueduct(assets,features)
    assert out.iloc[0]["match_status"]=="AMBIGUOUS"
    assert out.iloc[0]["null_reason"]=="AMBIGUOUS_AQUEDUCT_BOUNDARY"


def test_aqueduct_indicators_retain_wri_source_lineage(tmp_path):
    root=tmp_path/"private_data"
    initialize_workspace(root,schema_path())
    import_asset_rows(root,[{
        "external_system":"SYNTH","external_id":"A","asset_type":"FACTORY",
        "latitude":24.0,"longitude":90.0,"coordinate_source":"SYNTHETIC",
        "site_identity_grade":"EXACT_SITE","coordinate_status":"RESOLVED",
    }])
    asset=accepted_assets(root)[0]

    source_path=root/"raw"/"aqueduct.gpkg"
    source_path.parent.mkdir(parents=True,exist_ok=True)
    source_path.write_bytes(b"synthetic-aqueduct")
    source=register_source_file(
        root,source_id="AQUEDUCT_SYNTH",provider="WRI",
        provider_version="Aqueduct_4.0",artifact_path=source_path,
        retrieved_at="2026-09-23T00:00:00+00:00",
    )
    frame=match_assets_to_aqueduct(
        [{
            "tenant_key":"INTERNAL","asset_location_id":asset["asset_location_id"],
            "external_id":"A","latitude":24.0,"longitude":90.0,
        }],
        [{
            "geometry":Polygon([(89,23),(91,23),(91,25),(89,25)]),
            "properties":{
                "bws_raw":0.45,"bws_score":3.2,
                "bws_label":"High","bws_cat":3,
            },
        }],
    )
    frame["source_artifact_id"]=source["source_artifact_id"]
    frame["method_version"]="AQUEDUCT4_POINT_IN_POLYGON_0.1"
    run_id=start_processing_run(
        root,pipeline_name="aqueduct_test",pipeline_version="0.1"
    )
    assert insert_aqueduct_indicators(root,frame,run_id=run_id)==4

    with connect_catalog(root) as conn:
        rows=conn.execute(
            """
            SELECT ai.indicator_id,ai.value_numeric,ai.value_text,ais.source_role
            FROM asset_indicator ai
            JOIN asset_indicator_source ais
              ON ai.asset_indicator_id=ais.asset_indicator_id
            ORDER BY ai.indicator_id
            """
        ).fetchall()
    assert len(rows)==4
    assert all(r["source_role"]=="PRIMARY" for r in rows)
    names={r["indicator_id"] for r in rows}
    assert names=={
        "wri_aqueduct4_bws_raw","wri_aqueduct4_bws_score",
        "wri_aqueduct4_bws_cat","wri_aqueduct4_bws_label",
    }
