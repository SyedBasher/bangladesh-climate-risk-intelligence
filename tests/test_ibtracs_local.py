from pathlib import Path

import pandas as pd

from clr.ibtracs_local import (
    asset_storm_context,
    historical_asset_summary,
    insert_cyclone_indicators,
    read_ibtracs_csv,
)
from clr.local_assets import accepted_assets,import_asset_rows
from clr.local_store import (
    connect_catalog,initialize_workspace,register_source_file,start_processing_run
)


ROOT=Path(__file__).resolve().parents[1]


def schema_path():
    return ROOT/"migrations"/"000_local_private_data_plane.sql"


def fixture_path():
    return ROOT/"examples"/"synthetic"/"ibtracs_ni_sample.csv"


def _assets():
    return [
        {
            "tenant_key":"INTERNAL","asset_location_id":"A",
            "external_system":"SYNTH","external_id":"COASTAL_A",
            "site_identity_grade":"EXACT_SITE",
            "latitude":22.0,"longitude":91.0,
        },
        {
            "tenant_key":"INTERNAL","asset_location_id":"B",
            "external_system":"SYNTH","external_id":"INLAND_B",
            "site_identity_grade":"PROBABLE_SITE",
            "latitude":28.0,"longitude":88.0,
        },
    ]


def test_ibtracs_units_row_is_removed_and_fields_are_numeric():
    frame=read_ibtracs_csv(fixture_path(),start_year=1980)
    assert len(frame)==5
    assert set(frame["sid"])=={"2025001N15090","2025002N12085"}
    assert frame["iso_time_parsed"].notna().all()
    assert frame["track_lat"].dtype.kind in "fc"
    assert frame["track_lon"].dtype.kind in "fc"


def test_closest_trackpoint_preserves_separate_agency_intensity_fields():
    tracks=read_ibtracs_csv(fixture_path(),start_year=1980)
    nearest,timeline=asset_storm_context(
        tracks,[_assets()[0]],max_distance_km=500
    )
    assert len(nearest)==1
    row=nearest.iloc[0]
    assert row["sid"]=="2025001N15090"
    assert row["closest_trackpoint_distance_km"] < 0.01
    assert row["wmo_wind_knots"]==55
    assert row["usa_wind_knots"]==60
    assert row["wmo_pressure_hpa"]==980
    assert row["usa_pressure_hpa"]==975
    assert len(timeline)>=1
    assert set(timeline["sid"])=={"2025001N15090"}


def test_historical_counts_are_counts_not_probabilities():
    tracks=read_ibtracs_csv(fixture_path(),start_year=1980)
    nearest,_=asset_storm_context(
        tracks,_assets(),max_distance_km=500
    )
    summary=historical_asset_summary(
        nearest,_assets(),start_year=1980,end_year=2025
    ).set_index("external_id")
    assert summary.loc["COASTAL_A","storms_within_100km_count"]==1
    assert summary.loc["COASTAL_A","storms_within_250km_count"]==1
    assert pd.isna(summary.loc["INLAND_B","nearest_trackpoint_distance_km"])
    assert summary.loc["INLAND_B","storms_within_100km_count"]==0
    assert summary.loc["INLAND_B","quality_flag"]=="NO_STORMS_WITHIN_ANALYSIS_RADIUS"


def test_no_storm_event_tables_keep_stable_schema():
    tracks=read_ibtracs_csv(fixture_path(),start_year=1980)
    far=[{
        "tenant_key":"INTERNAL","asset_location_id":"X",
        "external_system":"SYNTH","external_id":"FAR",
        "site_identity_grade":"EXACT_SITE",
        "latitude":35.0,"longitude":100.0,
    }]
    nearest,timeline=asset_storm_context(
        tracks,far,max_distance_km=50
    )
    assert nearest.empty
    assert timeline.empty
    assert "closest_trackpoint_distance_km" in nearest.columns
    assert "distance_km" in timeline.columns


def test_cyclone_indicators_retain_ibtracs_lineage(tmp_path):
    root=tmp_path/"private_data"
    initialize_workspace(root,schema_path())
    import_asset_rows(root,[{
        "external_system":"SYNTH","external_id":"A","asset_type":"FACTORY",
        "latitude":22.0,"longitude":91.0,"coordinate_source":"SYNTHETIC",
        "site_identity_grade":"EXACT_SITE","coordinate_status":"RESOLVED",
    }])
    asset=accepted_assets(root)[0]

    raw=root/"raw"/"ibtracs.csv"
    raw.parent.mkdir(parents=True,exist_ok=True)
    raw.write_text(fixture_path().read_text(encoding="utf-8"),encoding="utf-8")
    source=register_source_file(
        root,source_id="IBTRACS_SYNTH",provider="NOAA NCEI",
        provider_version="IBTrACS_v04r01",artifact_path=raw,
        retrieved_at="2026-09-23T00:00:00+00:00",
    )

    tracks=read_ibtracs_csv(raw,start_year=1980)
    private_asset=[{
        "tenant_key":"INTERNAL",
        "asset_location_id":asset["asset_location_id"],
        "external_system":"SYNTH","external_id":"A",
        "site_identity_grade":"EXACT_SITE",
        "latitude":22.0,"longitude":91.0,
    }]
    nearest,_=asset_storm_context(
        tracks,private_asset,max_distance_km=500
    )
    summary=historical_asset_summary(
        nearest,private_asset,start_year=1980,end_year=2025
    )
    run_id=start_processing_run(
        root,pipeline_name="cyclone_test",pipeline_version="0.1"
    )
    n=insert_cyclone_indicators(
        root,nearest,summary,
        source_artifact_id=source["source_artifact_id"],
        start_year=1980,end_year=2025,run_id=run_id,
    )
    assert n>0

    with connect_catalog(root) as conn:
        roles={
            row["source_role"]
            for row in conn.execute(
                "SELECT DISTINCT source_role FROM asset_indicator_source"
            ).fetchall()
        }
        wind=conn.execute(
            """
            SELECT indicator_id,value_numeric
            FROM asset_indicator
            WHERE indicator_id IN (
                'ibtracs_wmo_wind_knots_at_closest_trackpoint',
                'ibtracs_usa_wind_knots_at_closest_trackpoint'
            )
            ORDER BY indicator_id
            """
        ).fetchall()
    assert roles=={"IBTRACS_TRACK"}
    values={row["indicator_id"]:row["value_numeric"] for row in wind}
    assert values["ibtracs_wmo_wind_knots_at_closest_trackpoint"]==55
    assert values["ibtracs_usa_wind_knots_at_closest_trackpoint"]==60
