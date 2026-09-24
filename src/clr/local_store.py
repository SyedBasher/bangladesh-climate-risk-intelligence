from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

WORKSPACE_DIRS = (
    "auth",
    "catalog",
    "raw/era5_land",
    "raw/chirps",
    "raw/jrc_flood",
    "raw/gfm",
    "raw/ffwc",
    "raw/dem",
    "raw/osm",
    "normalized/assets",
    "normalized/admin",
    "normalized/climate",
    "normalized/roads",
    "normalized/events",
    "indicators/asset",
    "indicators/admin",
    "indicators/portfolio",
    "indicators/logistics",
    "manifests/source_vintages",
    "outputs/reports",
    "outputs/qa",
    "backups/catalog",
    "tmp",
)

SAFE_PART = re.compile(r"[^A-Za-z0-9._=-]+")
TENANT_KEY_RE = re.compile(r"^[A-Za-z0-9._=-]{1,128}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_part(value: object) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError("Empty path component")
    return SAFE_PART.sub("_", text)


def canonical_tenant_key(value: object) -> str:
    """Validate a tenant key that is safe as both a DB scope and path segment."""
    raw = str(value)
    if raw != raw.strip():
        raise ValueError("tenant_key cannot have leading or trailing whitespace")
    tenant = raw
    if not TENANT_KEY_RE.fullmatch(tenant):
        raise ValueError(
            "tenant_key must be 1-128 characters using only letters, numbers, dot, underscore, equals, and hyphen"
        )
    if tenant.startswith(".") or tenant.endswith("."):
        raise ValueError("tenant_key cannot start or end with a dot")
    return tenant


def tenant_report_dir(root: str | Path, tenant_key: object) -> Path:
    """Return the tenant report root and prove it is a strict child."""
    tenant = canonical_tenant_key(tenant_key)
    reports_root = (Path(root).resolve() / "outputs" / "reports").resolve()
    path = (reports_root / tenant).resolve()
    if path.parent != reports_root:
        raise ValueError("tenant report directory is not a strict child of outputs/reports")
    return path


def _within(root: Path, path: Path) -> bool:
    root = root.resolve()
    path = path.resolve()
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def catalog_path(root: str | Path) -> Path:
    return Path(root).resolve() / "catalog" / "climate_risk.sqlite"


def initialize_workspace(root: str | Path, schema_path: str | Path) -> dict:
    root = Path(root).resolve()
    if (root / ".git").exists():
        raise ValueError("Refusing to initialize a private workspace at a Git repository root")
    root.mkdir(parents=True, exist_ok=True)

    # Make every initialized workspace self-protecting even when its directory
    # name is not one of the repository's conventional private-data names.
    workspace_gitignore = root / ".gitignore"
    protective_block = (
        "# Managed by climate-risk private workspace initialization.\n"
        "*\n"
    )
    existing_ignore = (
        workspace_gitignore.read_text(encoding="utf-8")
        if workspace_gitignore.exists()
        else ""
    )
    if protective_block not in existing_ignore:
        prefix = existing_ignore
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        workspace_gitignore.write_text(
            prefix + protective_block,
            encoding="utf-8",
        )
    for rel in WORKSPACE_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)

    marker = root / ".private-data-root"
    if not marker.exists():
        marker.write_text(
            "PRIVATE DATA WORKSPACE. DO NOT COMMIT THIS DIRECTORY TO GIT.\n",
            encoding="utf-8",
        )

    db = catalog_path(root)
    schema_sql = Path(schema_path).read_text(encoding="utf-8")
    with sqlite3.connect(db) as conn:
        conn.executescript(schema_sql)
        conn.executemany(
            "INSERT OR REPLACE INTO workspace_meta(key,value) VALUES(?,?)",
            [
                ("schema_version", "0.1.0"),
                ("workspace_kind", "LOCAL_PRIVATE"),
                ("initialized_at", utc_now()),
            ],
        )
        conn.commit()

    workspace_manifest = {
        "schema_version": "0.1.0",
        "workspace_kind": "LOCAL_PRIVATE",
        "catalog": "catalog/climate_risk.sqlite",
        "raw_snapshot_rule": "immutable-after-registration",
        "git_policy": "workspace-root-excluded",
    }
    (root / "workspace.json").write_text(
        json.dumps(workspace_manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "root": str(root),
        "catalog": str(db),
        "directories_created": len(WORKSPACE_DIRS),
    }


def connect_catalog(root: str | Path) -> sqlite3.Connection:
    db = catalog_path(root)
    if not db.exists():
        raise FileNotFoundError(
            f"Local catalog does not exist: {db}. Run scripts/init_private_workspace.py first."
        )
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def source_snapshot_path(
    root: str | Path,
    provider: str,
    dataset: str,
    provider_version: str,
    sha256: str,
    filename: str,
) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError("sha256 must be a lowercase 64-character digest")
    name = Path(filename).name
    if name != filename or name in {"", ".", ".."}:
        raise ValueError("filename must be a basename")
    return (
        Path(root).resolve()
        / "raw"
        / _safe_part(provider)
        / _safe_part(dataset)
        / _safe_part(provider_version)
        / sha256
        / name
    )


def write_source_manifest(root: str | Path, record: Mapping) -> tuple[Path, str]:
    root = Path(root).resolve()
    source_id = _safe_part(record["source_id"])
    retrieved_at = str(record["retrieved_at"])
    date_part = retrieved_at[:10]
    artifact_sha = str(record["sha256"])
    path = (
        root
        / "manifests"
        / "source_vintages"
        / source_id
        / date_part
        / f"{artifact_sha}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dict(record), sort_keys=True, indent=2) + "\n"
    path.write_text(payload, encoding="utf-8")
    return path, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def register_source_file(
    root: str | Path,
    *,
    source_id: str,
    provider: str,
    artifact_path: str | Path,
    provider_version: str | None = None,
    retrieved_at: str | None = None,
    media_type: str | None = None,
    valid_time_start: str | None = None,
    valid_time_end: str | None = None,
    retrieval_status: str = "COMPLETE",
    note: str | None = None,
    request_parameters: Mapping | None = None,
) -> dict:
    if retrieval_status not in {"COMPLETE", "PARTIAL", "FAILED", "BLOCKED"}:
        raise ValueError("Unsupported retrieval status")

    root = Path(root).resolve()
    artifact = Path(artifact_path).resolve()
    if not artifact.exists() or not artifact.is_file():
        raise FileNotFoundError(artifact)
    if not _within(root, artifact):
        raise ValueError("Source artifacts must be stored inside the private workspace")

    digest = sha256_file(artifact)
    retrieved_at = retrieved_at or utc_now()
    relative = artifact.relative_to(root).as_posix()

    with connect_catalog(root) as conn:
        existing = conn.execute(
            "SELECT * FROM source_artifact WHERE source_id=? AND sha256=?",
            (source_id, digest),
        ).fetchone()
        if existing:
            return dict(existing)

        artifact_id = str(uuid.uuid4())
        record = {
            "source_artifact_id": artifact_id,
            "source_id": source_id,
            "provider": provider,
            "provider_version": provider_version,
            "local_path": relative,
            "sha256": digest,
            "byte_size": artifact.stat().st_size,
            "media_type": media_type,
            "retrieved_at": retrieved_at,
            "valid_time_start": valid_time_start,
            "valid_time_end": valid_time_end,
            "retrieval_status": retrieval_status,
            "note": note,
            "request_parameters": dict(request_parameters or {}),
        }
        manifest_path, manifest_sha = write_source_manifest(root, record)
        record["request_manifest_path"] = manifest_path.relative_to(root).as_posix()
        record["request_manifest_sha256"] = manifest_sha

        conn.execute(
            """
            INSERT INTO source_artifact(
                source_artifact_id, source_id, provider, provider_version,
                local_path, sha256, byte_size, media_type, retrieved_at,
                valid_time_start, valid_time_end, request_manifest_path,
                request_manifest_sha256, retrieval_status, note
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                record["source_artifact_id"], source_id, provider, provider_version,
                relative, digest, record["byte_size"], media_type, retrieved_at,
                valid_time_start, valid_time_end, record["request_manifest_path"],
                manifest_sha, retrieval_status, note,
            ),
        )
        conn.commit()
    return record


def start_processing_run(
    root: str | Path,
    *,
    pipeline_name: str,
    pipeline_version: str,
    git_commit: str | None = None,
    profile_name: str | None = None,
    parameters: Mapping | None = None,
) -> str:
    run_id = str(uuid.uuid4())
    with connect_catalog(root) as conn:
        conn.execute(
            """
            INSERT INTO processing_run(
                run_id,pipeline_name,pipeline_version,git_commit,profile_name,
                started_at,status,parameters_json
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                run_id, pipeline_name, pipeline_version, git_commit, profile_name,
                utc_now(), "RUNNING", json.dumps(dict(parameters or {}), sort_keys=True),
            ),
        )
        conn.commit()
    return run_id


def finish_processing_run(
    root: str | Path,
    run_id: str,
    *,
    status: str,
    error_summary: str | None = None,
) -> None:
    if status not in {"SUCCESS", "FAILED", "PARTIAL"}:
        raise ValueError("Final run status must be SUCCESS, FAILED or PARTIAL")
    with connect_catalog(root) as conn:
        cur = conn.execute(
            "UPDATE processing_run SET finished_at=?, status=?, error_summary=? WHERE run_id=?",
            (utc_now(), status, error_summary, run_id),
        )
        if cur.rowcount != 1:
            raise KeyError(f"Unknown processing run: {run_id}")
        conn.commit()


def parquet_partition_dir(
    root: str | Path,
    *,
    layer: str,
    dataset: str,
    partitions: Mapping[str, object] | None = None,
) -> Path:
    if layer not in {"normalized", "indicators"}:
        raise ValueError("Parquet layer must be normalized or indicators")
    path = Path(root).resolve() / layer / _safe_part(dataset)
    for key, value in (partitions or {}).items():
        path = path / f"{_safe_part(key)}={_safe_part(value)}"
    return path


def register_parquet_dataset(
    root: str | Path,
    *,
    dataset_name: str,
    layer: str,
    parquet_path: str | Path,
    partition_spec: Mapping | None = None,
    row_count: int | None = None,
    run_id: str | None = None,
) -> str:
    root = Path(root).resolve()
    path = Path(parquet_path).resolve()
    if not path.exists() or not path.is_file() or path.suffix.lower() != ".parquet":
        raise ValueError("parquet_path must point to an existing .parquet file")
    if not _within(root, path):
        raise ValueError("Parquet datasets must be stored inside the private workspace")
    if row_count is not None and row_count < 0:
        raise ValueError("row_count cannot be negative")
    dataset_id = str(uuid.uuid4())
    digest = sha256_file(path)
    with connect_catalog(root) as conn:
        conn.execute(
            """
            INSERT INTO parquet_dataset(
                parquet_dataset_id,dataset_name,layer,relative_path,
                partition_spec_json,row_count,sha256,created_at,run_id
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                dataset_id, dataset_name, layer.upper(),
                path.relative_to(root).as_posix(),
                json.dumps(dict(partition_spec or {}), sort_keys=True),
                row_count, digest, utc_now(), run_id,
            ),
        )
        conn.commit()
    return dataset_id
