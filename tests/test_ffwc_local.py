from pathlib import Path

import pandas as pd

from clr.ffwc_local import (
    MEASUREMENT_BASIS,
    ffwc_event_context,
    import_observation_snapshot,
    import_station_snapshot,
    insert_ffwc_context_indicators,
    link_assets_to_stations,
)
from clr.local_assets import import_asset_rows
from clr.local_store import connect_catalog, initialize_workspace, start_processing_run


def schema_path():
    return Path(__file__).resolve().parents[1] / "migrations" / "000_local_private_data_plane.sql"


def _write(path,text):
    path.write_text(text,encoding="utf-8")
    return path


def test_ffwc_snapshots_deduplicate_observations_and_build_context(tmp_path):
    root=tmp_path/"private_data"
    initialize_workspace(root,schema_path())

    import_asset_rows(root,[{
        "external_system":"SYNTH","external_id":"A","asset_type":"FACTORY",
        "latitude":24.0,"longitude":90.4,"coordinate_source":"SYNTHETIC",
        "site_identity_grade":"EXACT_SITE","coordinate_status":"RESOLVED",
    }])

    stations=_write(
        tmp_path/"stations.csv",
        "station_id,station_name,river_name,latitude,longitude,danger_level_m\n"
        "S1,Near Gauge,River A,24.01,90.41,6.50\n"
        "S2,Far Gauge,River B,25.00,91.00,7.00\n",
    )
    station_result=import_station_snapshot(
        root,stations,source_url="https://ffwc.gov.bd/official-station-export"
    )
    assert station_result["rows"]==2

    obs1=_write(
        tmp_path/"obs1.csv",
        "station_id,observed_at,water_level_m,danger_level_m\n"
        "S1,2025-07-15T06:00:00+06:00,6.20,6.50\n"
        "S1,2025-07-15T09:00:00+06:00,6.70,6.50\n",
    )
    import_observation_snapshot(
        root,obs1,source_url="https://ffwc.gov.bd/official-observation-export-1"
    )

    obs2=_write(
        tmp_path/"obs2.csv",
        "station_id,observed_at,water_level_m,danger_level_m\n"
        "S1,2025-07-15T06:00:00+06:00,6.30,6.50\n"
        "S1,2025-07-15T09:00:00+06:00,6.80,6.50\n",
    )
    second=import_observation_snapshot(
        root,obs2,source_url="https://ffwc.gov.bd/official-observation-export-2"
    )

    with connect_catalog(root) as conn:
        count=conn.execute(
            "SELECT count(*) AS n FROM hydro_observation WHERE station_id='S1'"
        ).fetchone()["n"]
        latest=conn.execute(
            "SELECT water_level_m,source_artifact_id FROM hydro_observation "
            "WHERE station_id='S1' AND observed_at='2025-07-15T09:00:00+06:00'"
        ).fetchone()
    assert count==2
    assert latest["water_level_m"]==6.8
    assert latest["source_artifact_id"]==second["source"]["source_artifact_id"]

    links=link_assets_to_stations(root,top_k=1)
    assert links==1

    summary=ffwc_event_context(
        root,
        start="2025-07-15T00:00:00+06:00",
        end="2025-07-15T23:59:59+06:00",
    )
    assert len(summary)==1
    row=summary.iloc[0]
    assert row["station_id"]=="S1"
    assert row["station_distance_km"] < 2
    assert row["observation_count"]==2
    assert row["max_water_level_m"]==6.8
    assert abs(row["max_above_danger_m"]-0.3)<1e-9
    assert MEASUREMENT_BASIS=="CALCULATED_FROM_OFFICIAL_FFWC_STATION_OBSERVATIONS"

    run_id=start_processing_run(
        root,pipeline_name="ffwc_test",pipeline_version="0.1"
    )
    n=insert_ffwc_context_indicators(
        root,summary,
        start="2025-07-15T00:00:00+06:00",
        end="2025-07-15T23:59:59+06:00",
        run_id=run_id,
    )
    assert n==4

    with connect_catalog(root) as conn:
        roles={
            x["source_role"]
            for x in conn.execute(
                "SELECT DISTINCT source_role FROM asset_indicator_source"
            ).fetchall()
        }
    assert "FFWC_STATION_METADATA" in roles
    assert "FFWC_WATER_LEVEL" in roles


def test_ffwc_no_observations_is_explicit_not_interpolated(tmp_path):
    root=tmp_path/"private_data"
    initialize_workspace(root,schema_path())
    import_asset_rows(root,[{
        "external_system":"SYNTH","external_id":"A","asset_type":"FACTORY",
        "latitude":24.0,"longitude":90.4,"coordinate_source":"SYNTHETIC",
        "site_identity_grade":"PROBABLE_SITE","coordinate_status":"RESOLVED",
    }])
    stations=_write(
        tmp_path/"stations.csv",
        "station_id,station_name,river_name,latitude,longitude,danger_level_m\n"
        "S1,Near Gauge,River A,24.01,90.41,6.50\n",
    )
    import_station_snapshot(
        root,stations,source_url="https://ffwc.gov.bd/official-station-export"
    )
    assert link_assets_to_stations(root,top_k=1)==1
    summary=ffwc_event_context(
        root,start="2025-07-01T00:00:00+06:00",end="2025-07-01T23:59:59+06:00"
    )
    row=summary.iloc[0]
    assert row["observation_count"]==0
    assert pd.isna(row["max_water_level_m"])
    assert row["quality_flag"]=="NO_OBSERVATIONS_IN_WINDOW"
