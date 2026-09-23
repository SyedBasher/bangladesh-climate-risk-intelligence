from pathlib import Path

import pandas as pd

from clr.jrc_local import insert_flood_indicators
from clr.local_assets import import_asset_rows, accepted_assets
from clr.local_store import connect_catalog, initialize_workspace, start_processing_run


def schema_path():
    return Path(__file__).resolve().parents[1] / "migrations" / "000_local_private_data_plane.sql"


def test_flood_indicator_records_all_source_roles(tmp_path):
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
        pipeline_name="jrc_test",
        pipeline_version="0.1",
    )

    sources = {
        "DEPTH": "00000000-0000-0000-0000-000000000001",
        "PERMANENT_WATER_MASK": "00000000-0000-0000-0000-000000000002",
        "SPURIOUS_DEPTH_MASK": "00000000-0000-0000-0000-000000000003",
        "TILE_EXTENTS": "00000000-0000-0000-0000-000000000004",
    }
    with connect_catalog(root) as conn:
        for role, sid in sources.items():
            conn.execute(
                """
                INSERT INTO source_artifact(
                    source_artifact_id,source_id,provider,provider_version,local_path,
                    sha256,byte_size,retrieved_at,retrieval_status,note
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    sid, role, "JRC", "2.1.2", f"raw/{role}.tif",
                    (role.lower()[0] * 64), 1,
                    "2026-09-23T00:00:00+00:00", "COMPLETE", "synthetic",
                ),
            )
        conn.commit()

    frame = pd.DataFrame([{
        "tenant_key": "INTERNAL",
        "asset_location_id": asset["asset_location_id"],
        "indicator_id": "flood_rp100_depth_m",
        "published_depth_m": 0.8,
        "quality_flag": "OK",
        "null_reason": None,
        "depth_source_artifact_id": sources["DEPTH"],
        "permanent_water_source_artifact_id": sources["PERMANENT_WATER_MASK"],
        "spurious_depth_source_artifact_id": sources["SPURIOUS_DEPTH_MASK"],
    }])

    count = insert_flood_indicators(
        root,
        frame,
        run_id=run_id,
        tile_extents_source_artifact_id=sources["TILE_EXTENTS"],
    )
    assert count == 1

    with connect_catalog(root) as conn:
        indicator = conn.execute(
            "SELECT asset_indicator_id,value_numeric FROM asset_indicator"
        ).fetchone()
        roles = {
            row["source_role"]
            for row in conn.execute(
                "SELECT source_role FROM asset_indicator_source WHERE asset_indicator_id=?",
                (indicator["asset_indicator_id"],),
            ).fetchall()
        }
    assert indicator["value_numeric"] == 0.8
    assert roles == {
        "DEPTH",
        "PERMANENT_WATER_MASK",
        "SPURIOUS_DEPTH_MASK",
        "TILE_EXTENTS",
    }
