from pathlib import Path

from clr.local_assets import accepted_assets, import_asset_rows
from clr.local_store import initialize_workspace


def schema_path():
    return Path(__file__).resolve().parents[1] / "migrations" / "000_local_private_data_plane.sql"


def test_only_exact_resolved_assets_enter_era5_selection(tmp_path):
    root = tmp_path / "private_data"
    initialize_workspace(root, schema_path())
    result = import_asset_rows(
        root,
        [
            {
                "external_system": "SYNTH",
                "external_id": "A",
                "asset_type": "FACTORY",
                "latitude": 24.0,
                "longitude": 90.4,
                "coordinate_source": "SYNTHETIC",
                "site_identity_grade": "EXACT_SITE",
                "coordinate_status": "RESOLVED",
            },
            {
                "external_system": "SYNTH",
                "external_id": "B",
                "asset_type": "FACTORY",
                "latitude": 23.9,
                "longitude": 90.3,
                "coordinate_source": "SYNTHETIC",
                "site_identity_grade": "PROBABLE_SITE",
                "coordinate_status": "RESOLVED",
            },
            {
                "external_system": "SYNTH",
                "external_id": "C",
                "asset_type": "FACTORY",
                "latitude": 23.8,
                "longitude": 90.2,
                "coordinate_source": "SYNTHETIC",
                "site_identity_grade": "EXACT_SITE",
                "coordinate_status": "PENDING",
            },
        ],
    )
    assert result["inserted"] == 3
    accepted = accepted_assets(root)
    assert [x["external_id"] for x in accepted] == ["A"]


def test_asset_import_is_idempotent(tmp_path):
    root = tmp_path / "private_data"
    initialize_workspace(root, schema_path())
    rows = [{
        "external_system": "SYNTH",
        "external_id": "A",
        "asset_type": "FACTORY",
        "latitude": 24.0,
        "longitude": 90.4,
        "coordinate_source": "SYNTHETIC",
        "site_identity_grade": "EXACT_SITE",
        "coordinate_status": "RESOLVED",
    }]
    first = import_asset_rows(root, rows)
    second = import_asset_rows(root, rows)
    assert first["inserted"] == 1
    assert second["inserted"] == 0
    assert second["existing"] == 1


def test_invalid_coordinate_fails_closed(tmp_path):
    root = tmp_path / "private_data"
    initialize_workspace(root, schema_path())
    result = import_asset_rows(
        root,
        [{
            "external_system": "SYNTH",
            "external_id": "BAD",
            "asset_type": "FACTORY",
            "latitude": 124.0,
            "longitude": 90.4,
            "coordinate_source": "SYNTHETIC",
            "site_identity_grade": "EXACT_SITE",
            "coordinate_status": "RESOLVED",
        }],
    )
    assert result["inserted"] == 0
    assert len(result["rejected"]) == 1
