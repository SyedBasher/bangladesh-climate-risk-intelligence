from pathlib import Path

import pandas as pd

from clr.chirps_local import (
    BASELINE_DEPENDENT,
    asset_signature,
    insert_rainfall_indicators,
    required_years,
    source_subset_id,
    year_urls,
)
from clr.local_assets import accepted_assets, import_asset_rows
from clr.local_store import connect_catalog, initialize_workspace, start_processing_run


def schema_path():
    return Path(__file__).resolve().parents[1] / "migrations" / "000_local_private_data_plane.sql"


def _assets():
    return [{
        "asset_location_id": "A1",
        "tenant_key": "INTERNAL",
        "external_system": "SYNTH",
        "external_id": "F1",
        "site_identity_grade": "EXACT_SITE",
        "latitude": 24.0,
        "longitude": 90.4,
    }]


def test_asset_signature_and_source_id_are_stable():
    a = _assets()
    assert asset_signature(a) == asset_signature(list(reversed(a)))
    sid = source_subset_id(2025, a)
    assert sid.startswith("CHIRPS_V3_FINAL_RNL_SUBSET_2025_")


def test_year_url_plan_is_complete():
    urls = year_urls(2025)
    assert len(urls) == 365
    assert urls[0]["date"] == "2025-01-01"
    assert urls[-1]["date"] == "2025-12-31"
    assert urls[0]["url"].endswith("chirps-v3.0.rnl.2025.01.01.cog")


def test_required_years_add_target_outside_baseline():
    years = required_years(2025, 1991, 2020)
    assert years[0] == 1991
    assert years[-1] == 2025
    assert len(years) == 31


def test_r95_metrics_are_marked_baseline_dependent():
    assert {
        "r95p_mm",
        "r95p_share_pct",
        "r95p_days",
        "r95_threshold_mm",
    }.issubset(BASELINE_DEPENDENT)


def test_indicator_lineage_target_and_baseline(tmp_path):
    root = tmp_path / "private_data"
    initialize_workspace(root, schema_path())
    import_asset_rows(root, [{
        "external_system": "SYNTH",
        "external_id": "A",
        "asset_type": "FACTORY",
        "latitude": 24.0,
        "longitude": 90.4,
        "coordinate_source": "SYNTHETIC",
        "site_identity_grade": "EXACT_SITE",
        "coordinate_status": "RESOLVED",
    }])
    asset = accepted_assets(root)[0]
    run_id = start_processing_run(
        root,
        pipeline_name="chirps_test",
        pipeline_version="0.1",
    )

    target_id = "00000000-0000-0000-0000-000000000001"
    baseline_id = "00000000-0000-0000-0000-000000000002"

    with connect_catalog(root) as conn:
        for sid, source_id in [
            (target_id, "TARGET"),
            (baseline_id, "BASELINE"),
        ]:
            conn.execute(
                """
                INSERT INTO source_artifact(
                    source_artifact_id,source_id,provider,provider_version,local_path,
                    sha256,byte_size,retrieved_at,retrieval_status,note
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    sid,
                    source_id,
                    "UCSB CHC",
                    "CHIRPS_v3.0_final_rnl_0.05deg",
                    f"raw/{source_id}.parquet",
                    ("a" if source_id == "TARGET" else "b") * 64,
                    1,
                    "2026-09-23T00:00:00+00:00",
                    "COMPLETE",
                    "synthetic",
                ),
            )
        conn.commit()

    metrics = pd.DataFrame([
        {
            "tenant_key": "INTERNAL",
            "asset_location_id": asset["asset_location_id"],
            "external_id": "A",
            "site_identity_grade": "EXACT_SITE",
            "indicator_id": "rx1day_mm",
            "value": 100.0,
            "unit": "mm",
            "value_class": "CALCULATED",
            "measurement_basis": "CALCULATED_FROM_SATELLITE_GAUGE_BLEND_WITH_REANALYSIS_DAILY_DISAGGREGATION",
            "method_version": "CHIRPS_EXTREMES_0.1",
            "quality_flag": "COMPLETE_BASELINE_AND_YEAR",
            "target_year": 2025,
            "baseline_start": 2020,
            "baseline_end": 2020,
        },
        {
            "tenant_key": "INTERNAL",
            "asset_location_id": asset["asset_location_id"],
            "external_id": "A",
            "site_identity_grade": "EXACT_SITE",
            "indicator_id": "r95p_mm",
            "value": 150.0,
            "unit": "mm/year",
            "value_class": "CALCULATED",
            "measurement_basis": "CALCULATED_FROM_SATELLITE_GAUGE_BLEND_WITH_REANALYSIS_DAILY_DISAGGREGATION",
            "method_version": "CHIRPS_EXTREMES_0.1",
            "quality_flag": "COMPLETE_BASELINE_AND_YEAR",
            "target_year": 2025,
            "baseline_start": 2020,
            "baseline_end": 2020,
        },
    ])

    count = insert_rainfall_indicators(
        root,
        metrics,
        {
            2020: {"source_artifact_id": baseline_id},
            2025: {"source_artifact_id": target_id},
        },
        target_year=2025,
        baseline_start=2020,
        baseline_end=2020,
        run_id=run_id,
    )
    assert count == 2

    with connect_catalog(root) as conn:
        rows = conn.execute(
            """
            SELECT ai.indicator_id, ais.source_role
            FROM asset_indicator ai
            JOIN asset_indicator_source ais
              ON ai.asset_indicator_id=ais.asset_indicator_id
            ORDER BY ai.indicator_id, ais.source_role
            """
        ).fetchall()

    roles = {}
    for row in rows:
        roles.setdefault(row["indicator_id"], set()).add(row["source_role"])

    assert roles["rx1day_mm"] == {"TARGET_SERIES"}
    assert roles["r95p_mm"] == {"TARGET_SERIES", "BASELINE_SERIES"}
