from pathlib import Path

import pandas as pd

from clr.copdem_local import insert_dem_indicators
from clr.local_assets import accepted_assets, import_asset_rows
from clr.local_store import connect_catalog, initialize_workspace, start_processing_run


def schema_path():
    return Path(__file__).resolve().parents[1] / "migrations" / "000_local_private_data_plane.sql"


def test_dem_indicators_retain_raster_and_package_lineage(tmp_path):
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
        pipeline_name="copdem_test",
        pipeline_version="0.1",
    )

    package_id = "00000000-0000-0000-0000-000000000001"
    dem_id = "00000000-0000-0000-0000-000000000002"
    with connect_catalog(root) as conn:
        for sid, source_id in [(package_id, "PACKAGE"), (dem_id, "DEM")]:
            conn.execute(
                """
                INSERT INTO source_artifact(
                    source_artifact_id,source_id,provider,provider_version,local_path,
                    sha256,byte_size,retrieved_at,retrieval_status,note
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    sid, source_id, "Copernicus", "COP-DEM_GLO-30-DGED/2024_1",
                    f"raw/{source_id}", ("a" if source_id == "PACKAGE" else "b") * 64,
                    1, "2026-09-23T00:00:00+00:00", "COMPLETE", "synthetic",
                ),
            )
        conn.commit()

    frame = pd.DataFrame([{
        "tenant_key": "INTERNAL",
        "asset_location_id": asset["asset_location_id"],
        "external_system": "SYNTH",
        "external_id": "A",
        "grid_id": "N24_E090",
        "elevation_dsm_m": 12.0,
        "dsm_local_median_500m_m": 14.0,
        "dsm_relative_elevation_500m_m": -2.0,
        "dsm_local_relief_p90_p10_500m_m": 3.0,
        "dsm_valid_fraction_500m": 1.0,
        "context_quality_flag": "OK",
        "context_null_reason": None,
        "dem_source_artifact_id": dem_id,
        "package_source_artifact_id": package_id,
        "dataset": "COP-DEM_GLO-30-DGED/2024_1",
        "product_id": "synthetic",
    }])

    count = insert_dem_indicators(root, frame, run_id=run_id)
    assert count == 3

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

    assert set(roles) == {
        "elevation_dsm_m",
        "dsm_relative_elevation_500m_m",
        "dsm_local_relief_p90_p10_500m_m",
    }
    assert all(v == {"DEM_RASTER", "SOURCE_PACKAGE"} for v in roles.values())
