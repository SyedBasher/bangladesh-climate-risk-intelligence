from pathlib import Path

from clr.local_store import (
    connect_catalog,
    initialize_workspace,
    parquet_partition_dir,
    register_source_file,
    start_processing_run,
    finish_processing_run,
)


def schema_path():
    return Path(__file__).resolve().parents[1] / "migrations" / "000_local_private_data_plane.sql"


def test_initialize_workspace_creates_catalog_and_layers(tmp_path):
    root = tmp_path / "private_data"
    result = initialize_workspace(root, schema_path())
    assert Path(result["catalog"]).exists()
    assert (root / ".private-data-root").exists()
    assert (root / "raw" / "era5_land").is_dir()
    assert (root / "indicators" / "portfolio").is_dir()
    with connect_catalog(root) as conn:
        row = conn.execute(
            "SELECT value FROM workspace_meta WHERE key='workspace_kind'"
        ).fetchone()
        assert row["value"] == "LOCAL_PRIVATE"


def test_register_source_file_uses_relative_path_and_hash(tmp_path):
    root = tmp_path / "private_data"
    initialize_workspace(root, schema_path())
    source = root / "raw" / "era5_land" / "synthetic.nc"
    source.write_bytes(b"synthetic climate bytes")

    row = register_source_file(
        root,
        source_id="ERA5L_DAILY",
        provider="Copernicus CDS",
        provider_version="SYNTHETIC",
        artifact_path=source,
        retrieved_at="2026-09-23T00:00:00+00:00",
    )
    assert row["local_path"] == "raw/era5_land/synthetic.nc"
    assert len(row["sha256"]) == 64
    assert not row["local_path"].startswith("/")

    with connect_catalog(root) as conn:
        dbrow = conn.execute(
            "SELECT local_path, sha256 FROM source_artifact WHERE source_id='ERA5L_DAILY'"
        ).fetchone()
        assert dbrow["local_path"] == row["local_path"]
        assert dbrow["sha256"] == row["sha256"]


def test_source_registration_rejects_file_outside_workspace(tmp_path):
    root = tmp_path / "private_data"
    initialize_workspace(root, schema_path())
    outside = tmp_path / "outside.nc"
    outside.write_bytes(b"x")
    try:
        register_source_file(
            root,
            source_id="X",
            provider="X",
            artifact_path=outside,
        )
    except ValueError as e:
        assert "inside the private workspace" in str(e)
    else:
        raise AssertionError("Expected source registration to fail closed")


def test_processing_run_ledger(tmp_path):
    root = tmp_path / "private_data"
    initialize_workspace(root, schema_path())
    run_id = start_processing_run(
        root,
        pipeline_name="synthetic",
        pipeline_version="0.1",
        git_commit="abc123",
        parameters={"year": 2025},
    )
    finish_processing_run(root, run_id, status="SUCCESS")
    with connect_catalog(root) as conn:
        row = conn.execute(
            "SELECT status, finished_at FROM processing_run WHERE run_id=?",
            (run_id,),
        ).fetchone()
        assert row["status"] == "SUCCESS"
        assert row["finished_at"] is not None


def test_parquet_partition_convention(tmp_path):
    path = parquet_partition_dir(
        tmp_path,
        layer="indicators",
        dataset="asset_heat",
        partitions={"year": 2025, "source": "ERA5L_DAILY"},
    )
    assert path.as_posix().endswith(
        "indicators/asset_heat/year=2025/source=ERA5L_DAILY"
    )
