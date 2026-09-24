from __future__ import annotations

import calendar
from pathlib import Path

import pandas as pd

from clr.compound_local import (
    _insert_cross_metric,
    cross_asset_summary,
    flood_route_asset_state,
    heat_drought_annual,
    heat_drought_monthly,
    shared_flood_exposed_edges,
)
from clr.local_store import (
    connect_catalog,
    initialize_workspace,
    register_source_file,
    start_processing_run,
)


ROOT=Path(__file__).resolve().parents[1]


def schema_path():
    return ROOT/"migrations"/"000_local_private_data_plane.sql"


def _daily_heat(year=2025):
    rows=[]
    for month in range(1,13):
        days=calendar.monthrange(year,month)[1]
        for day in range(1,days+1):
            temp=34.0
            if month==1 and day<=5:
                temp=36.0
            if month==7 and day<=3:
                temp=36.5
            rows.append({
                "tenant_key":"INTERNAL",
                "asset_location_id":"A",
                "external_id":"A",
                "date":f"{year:04d}-{month:02d}-{day:02d}",
                "temp_c":temp,
                "source_artifact_id":"HEAT-SOURCE",
            })
    return pd.DataFrame(rows)


def _spi(year=2025):
    rows=[]
    for month in range(1,13):
        for iid in ("spi3","spi12"):
            value=0.0
            if iid=="spi3" and month==1:
                value=-1.2
            if iid=="spi12" and month==7:
                value=-1.4
            rows.append({
                "tenant_key":"INTERNAL",
                "asset_location_id":"A",
                "external_id":"A",
                "indicator_id":iid,
                "period":f"{year:04d}-{month:02d}",
                "value":value,
                "quality_flag":"OK",
            })
    return pd.DataFrame(rows)


def test_heat_drought_same_month_join_is_transparent():
    monthly=heat_drought_monthly(_daily_heat(),_spi(),year=2025)
    assert len(monthly)==12

    jan=monthly[monthly["period"]=="2025-01"].iloc[0]
    jul=monthly[monthly["period"]=="2025-07"].iloc[0]
    assert jan["days_tmax_gt_35c"]==5
    assert bool(jan["heat_spi3_cooccurrence"]) is True
    assert bool(jan["heat_spi12_cooccurrence"]) is False
    assert jul["days_tmax_gt_35c"]==3
    assert bool(jul["heat_spi12_cooccurrence"]) is True

    annual=heat_drought_annual(monthly,year=2025).set_index("indicator_id")
    assert annual.loc[
        "compound_heat_drought_spi3_cooccurrence_month_count","value"
    ]==1
    assert annual.loc[
        "compound_heat_days_gt35_during_spi3_le_minus1_months","value"
    ]==5
    assert annual.loc[
        "compound_heat_drought_spi12_cooccurrence_month_count","value"
    ]==1
    assert annual.loc[
        "compound_heat_days_gt35_during_spi12_le_minus1_months","value"
    ]==3


def test_incomplete_heat_month_makes_annual_compound_null():
    daily=_daily_heat()
    daily=daily[daily["date"]!="2025-03-15"].copy()
    monthly=heat_drought_monthly(daily,_spi(),year=2025)
    annual=heat_drought_annual(monthly,year=2025)
    assert set(annual["quality_flag"])=={"INCOMPLETE_YEAR_INPUT"}
    assert annual["value"].isna().all()


def test_flood_route_evidence_states_require_complete_route_coverage():
    site=pd.DataFrame([
        {"tenant_key":"INTERNAL","asset_location_id":"A1","external_system":"S","external_id":"A","asset_indicator_id":1,"site_depth_m":0.5},
        {"tenant_key":"INTERNAL","asset_location_id":"A2","external_system":"S","external_id":"B","asset_indicator_id":2,"site_depth_m":0.5},
        {"tenant_key":"INTERNAL","asset_location_id":"A3","external_system":"S","external_id":"C","asset_indicator_id":3,"site_depth_m":0.0},
        {"tenant_key":"INTERNAL","asset_location_id":"A4","external_system":"S","external_id":"D","asset_indicator_id":4,"site_depth_m":0.0},
        {"tenant_key":"INTERNAL","asset_location_id":"A5","external_system":"S","external_id":"E","asset_indicator_id":5,"site_depth_m":0.5},
        {"tenant_key":"INTERNAL","asset_location_id":"A6","external_system":"S","external_id":"F","asset_indicator_id":6,"site_depth_m":0.5},
    ])
    route=pd.DataFrame([
        {"tenant_key":"INTERNAL","external_system":"S","external_id":"A","quality_flag":"OK","hazard_exposed_length_m":100.0,"hazard_exposed_share":0.2},
        {"tenant_key":"INTERNAL","external_system":"S","external_id":"A","quality_flag":"OK","hazard_exposed_length_m":0.0,"hazard_exposed_share":0.0},
        {"tenant_key":"INTERNAL","external_system":"S","external_id":"B","quality_flag":"OK","hazard_exposed_length_m":0.0,"hazard_exposed_share":0.0},
        {"tenant_key":"INTERNAL","external_system":"S","external_id":"C","quality_flag":"OK","hazard_exposed_length_m":50.0,"hazard_exposed_share":0.1},
        {"tenant_key":"INTERNAL","external_system":"S","external_id":"D","quality_flag":"OK","hazard_exposed_length_m":0.0,"hazard_exposed_share":0.0},
        {"tenant_key":"INTERNAL","external_system":"S","external_id":"E","quality_flag":"PARTIAL_HAZARD_COVERAGE","hazard_exposed_length_m":50.0,"hazard_exposed_share":None},
    ])
    out=flood_route_asset_state(site,route,return_period=100).set_index("external_id")
    assert out.loc["A","evidence_state"]=="SITE_AND_ROUTE_EXPOSED"
    assert out.loc["B","evidence_state"]=="SITE_ONLY_EXPOSED"
    assert out.loc["C","evidence_state"]=="ROUTE_ONLY_EXPOSED"
    assert out.loc["D","evidence_state"]=="NEITHER_POINT_NOR_ROUTE_EXPOSED"
    assert out.loc["E","evidence_state"]=="ROUTE_HAZARD_COVERAGE_INCOMPLETE"
    assert out.loc["F","evidence_state"]=="NO_ROUTE_DEPENDENCY"


def test_shared_bottleneck_requires_multiple_distinct_assets():
    edge=pd.DataFrame([
        {"tenant_key":"INTERNAL","external_system":"S","external_id":"A","asset_route_dependency_id":"A1","physical_edge_key":"1:2","osm_way_id":10,"road_class":"primary","bridge":False,"ferry":False,"length_m":100.0,"hazard_exposed":True,"jrc_max_valid_depth_m":0.4},
        {"tenant_key":"INTERNAL","external_system":"S","external_id":"A","asset_route_dependency_id":"A2","physical_edge_key":"1:2","osm_way_id":10,"road_class":"primary","bridge":False,"ferry":False,"length_m":100.0,"hazard_exposed":True,"jrc_max_valid_depth_m":0.5},
        {"tenant_key":"INTERNAL","external_system":"S","external_id":"B","asset_route_dependency_id":"B1","physical_edge_key":"1:2","osm_way_id":10,"road_class":"primary","bridge":False,"ferry":False,"length_m":100.0,"hazard_exposed":True,"jrc_max_valid_depth_m":0.3},
        {"tenant_key":"INTERNAL","external_system":"S","external_id":"A","asset_route_dependency_id":"A1","physical_edge_key":"2:3","osm_way_id":11,"road_class":"secondary","bridge":False,"ferry":False,"length_m":80.0,"hazard_exposed":True,"jrc_max_valid_depth_m":0.2},
        {"tenant_key":"INTERNAL","external_system":"S","external_id":"A","asset_route_dependency_id":"A2","physical_edge_key":"2:3","osm_way_id":11,"road_class":"secondary","bridge":False,"ferry":False,"length_m":80.0,"hazard_exposed":True,"jrc_max_valid_depth_m":0.2},
        {"tenant_key":"INTERNAL","external_system":"S","external_id":"C","asset_route_dependency_id":"C1","physical_edge_key":"3:4","osm_way_id":12,"road_class":"primary","bridge":False,"ferry":False,"length_m":90.0,"hazard_exposed":False,"jrc_max_valid_depth_m":0.0},
    ])
    out=shared_flood_exposed_edges(edge)
    assert len(out)==1
    row=out.iloc[0]
    assert row["physical_edge_key"]=="1:2"
    assert row["distinct_asset_count"]==2
    assert row["distinct_dependency_count"]==3
    assert row["max_jrc_depth_m"]==0.5


def test_cross_asset_summary_uses_explicit_denominators():
    heat=pd.DataFrame([
        {"indicator_id":"compound_heat_drought_spi3_cooccurrence_month_count","value":2.0,"quality_flag":"OK"},
        {"indicator_id":"compound_heat_drought_spi3_cooccurrence_month_count","value":0.0,"quality_flag":"OK"},
        {"indicator_id":"compound_heat_drought_spi3_cooccurrence_month_count","value":None,"quality_flag":"INCOMPLETE_YEAR_INPUT"},
        {"indicator_id":"compound_heat_drought_spi12_cooccurrence_month_count","value":1.0,"quality_flag":"OK"},
        {"indicator_id":"compound_heat_drought_spi12_cooccurrence_month_count","value":0.0,"quality_flag":"OK"},
    ])
    flood=pd.DataFrame([
        {"evidence_state":"SITE_AND_ROUTE_EXPOSED"},
        {"evidence_state":"SITE_ONLY_EXPOSED"},
        {"evidence_state":"ROUTE_HAZARD_COVERAGE_INCOMPLETE"},
    ])
    edges=pd.DataFrame([
        {"asset_keys":"S:A;S:B","distinct_asset_count":2},
        {"asset_keys":"S:B;S:C","distinct_asset_count":2},
    ])
    out=cross_asset_summary(heat,flood,edges,year=2025,return_period=100)
    spi3=out[out["metric_id"]=="asset_share_with_heat_spi3_cooccurrence"].iloc[0]
    assert spi3["value"]==0.5
    assert spi3["denominator"]==2
    fr=out[out["metric_id"]=="rp100_asset_share_site_and_route_exposed"].iloc[0]
    assert fr["value"]==0.5
    assert fr["denominator"]==2
    affected=out[
        out["metric_id"]=="rp100_assets_using_shared_flood_exposed_edges_count"
    ].iloc[0]
    assert affected["value"]==3


def test_cross_asset_metric_schema_and_source_lineage(tmp_path):
    root=tmp_path/"private_data"
    initialize_workspace(root,schema_path())
    source_file=root/"raw"/"source.bin"
    source_file.parent.mkdir(parents=True,exist_ok=True)
    source_file.write_bytes(b"source")
    source=register_source_file(
        root,source_id="SRC",provider="SYNTH",
        provider_version="v1",artifact_path=source_file,
        retrieved_at="2026-09-24T00:00:00+00:00",
    )
    run_id=start_processing_run(
        root,pipeline_name="compound_test",pipeline_version="0.1"
    )
    metric_id=_insert_cross_metric(
        root,tenant_key="INTERNAL",
        analysis_type="HEAT_DROUGHT",
        metric_id="assets_with_heat_spi3_cooccurrence_count",
        value=2,unit="assets",
        period_start="2025-01-01",period_end="2025-12-31",
        method_version="TEST",quality_flag="OK",
        input_manifest={"inputs":[{"dataset_name":"synthetic","sha256":"a"*64}]},
        run_id=run_id,
        source_roles={"HEAT_SOURCE":{source["source_artifact_id"]}},
        denominator=4,
    )
    with connect_catalog(root) as conn:
        row=conn.execute(
            "SELECT * FROM cross_asset_metric WHERE cross_asset_metric_id=?",
            (metric_id,),
        ).fetchone()
        lineage=conn.execute(
            "SELECT * FROM cross_asset_metric_source WHERE cross_asset_metric_id=?",
            (metric_id,),
        ).fetchall()
    assert row["value_numeric"]==2
    assert '"denominator": 4' in row["input_manifest_json"]
    assert len(lineage)==1
    assert lineage[0]["source_role"]=="HEAT_SOURCE"
