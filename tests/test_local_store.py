import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from clr.local_store import (
    canonical_tenant_key,
    connect_catalog,
    initialize_workspace,
    parquet_partition_dir,
    register_source_file,
    start_processing_run,
    finish_processing_run,
    tenant_report_dir,
)


def schema_path():
    return Path(__file__).resolve().parents[1] / "migrations" / "000_local_private_data_plane.sql"


def test_initialize_workspace_creates_catalog_and_layers(tmp_path):
    root = tmp_path / "private_data"
    result = initialize_workspace(root, schema_path())
    assert Path(result["catalog"]).exists()
    assert (root / ".private-data-root").exists()
    assert (root / "auth").is_dir()
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


def test_request_parameters_are_preserved_in_manifest(tmp_path):
    root = tmp_path / "private_data"
    initialize_workspace(root, schema_path())
    source = root / "raw" / "era5_land" / "request.zip"
    source.write_bytes(b"synthetic archive")
    request = {
        "dataset": "derived-era5-land-daily-statistics",
        "year": "2025",
        "daily_statistic": "daily_maximum",
        "time_zone": "utc+06:00",
    }

    row = register_source_file(
        root,
        source_id="ERA5L_DAILY_MAX",
        provider="Copernicus CDS",
        artifact_path=source,
        retrieved_at="2026-09-23T00:00:00+00:00",
        request_parameters=request,
    )
    manifest = json.loads(
        (root / row["request_manifest_path"]).read_text(encoding="utf-8")
    )
    assert manifest["request_parameters"] == request


def test_source_registration_is_idempotent_for_same_bytes(tmp_path):
    root = tmp_path / "private_data"
    initialize_workspace(root, schema_path())
    source = root / "raw" / "era5_land" / "same.nc"
    source.write_bytes(b"same bytes")

    first = register_source_file(
        root,
        source_id="ERA5L_DAILY",
        provider="Copernicus CDS",
        artifact_path=source,
        retrieved_at="2026-09-23T00:00:00+00:00",
    )
    second = register_source_file(
        root,
        source_id="ERA5L_DAILY",
        provider="Copernicus CDS",
        artifact_path=source,
        retrieved_at="2026-09-24T00:00:00+00:00",
    )
    assert first["source_artifact_id"] == second["source_artifact_id"]
    with connect_catalog(root) as conn:
        count = conn.execute(
            "SELECT count(*) AS n FROM source_artifact WHERE source_id='ERA5L_DAILY'"
        ).fetchone()["n"]
        assert count == 1


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


def test_initialized_workspace_is_self_protecting_for_git(tmp_path):
    root = tmp_path / "custom_workspace_name"
    initialize_workspace(root, schema_path())
    ignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert "*" in ignore.splitlines()
    assert "!.gitignore" not in ignore.splitlines()
    assert (root / ".private-data-root").exists()
    assert (root / "workspace.json").exists()


def test_initialize_workspace_refuses_repository_root(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    try:
        initialize_workspace(root, schema_path())
    except ValueError as exc:
        assert "Git repository root" in str(exc)
    else:
        raise AssertionError("Expected repository-root initialization to fail closed")


def test_canonical_tenant_key_rejects_path_segments_and_keeps_normal_dots(tmp_path):
    assert canonical_tenant_key("ACME.BD") == "ACME.BD"
    assert canonical_tenant_key("TENANT_A-1") == "TENANT_A-1"
    for bad in (".", "..", "...", ".hidden", "TENANT.", "TENANT/A", "", " TENANT", "TENANT "):
        try:
            canonical_tenant_key(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected tenant key to be rejected: {bad!r}")

    root = tmp_path / "private_data"
    initialize_workspace(root, schema_path())
    reports_root = (root / "outputs" / "reports").resolve()
    tenant_dir = tenant_report_dir(root, "ACME.BD")
    assert tenant_dir.parent == reports_root


def test_custom_workspace_is_ignored_inside_an_unrelated_git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    root = repo / "climate_private_workspace"
    initialize_workspace(root, schema_path())
    secret = root / "auth" / "audit_chain_secret.bin"
    secret.write_bytes(b"synthetic-secret")

    for path in [
        root / ".private-data-root",
        root / "workspace.json",
        secret,
        root / "manifests" / "source_vintages",
        root / "outputs" / "reports",
    ]:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(path.relative_to(repo))],
            cwd=repo,
        )
        assert result.returncode == 0, path


def test_connect_catalog_context_manager_closes_handle(tmp_path):
    root = tmp_path / "private_data"
    initialize_workspace(root, schema_path())
    conn = connect_catalog(root)
    with conn as db:
        assert db.execute("SELECT 1").fetchone()[0] == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")


def test_connect_catalog_sets_busy_timeout(tmp_path):
    root = tmp_path / "private_data"
    initialize_workspace(root, schema_path())
    with connect_catalog(root, busy_timeout_ms=1234) as conn:
        value = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert value == 1234
