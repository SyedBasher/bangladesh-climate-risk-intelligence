from __future__ import annotations

import subprocess
from pathlib import Path

from .local_store import WORKSPACE_DIRS

FORBIDDEN_PREFIXES = (
    "private_data/",
    "local_data/",
    "data/",
    "raw/",
    "processed/",
    "private/",
    "customer_data/",
    "source_snapshots/",
    "outputs/",
    "build/",
    "cache/",
    "artifacts/",
    "backups/",
)

FORBIDDEN_SUFFIXES = (
    ".db", ".db-wal", ".db-shm",
    ".sqlite", ".sqlite-wal", ".sqlite-shm",
    ".sqlite3", ".sqlite3-wal", ".sqlite3-shm",
    ".duckdb", ".parquet", ".feather",
    ".pbf", ".tif", ".tiff", ".nc", ".grib", ".grib2", ".gpkg",
    ".shp", ".shx", ".dbf", ".vrt", ".clrbackup",
)

FORBIDDEN_PATH_FRAGMENTS = tuple(
    sorted(
        {
            "/" + rel.strip("/").lower() + "/"
            for rel in WORKSPACE_DIRS
        }
    )
)


FORBIDDEN_BASENAMES = {
    ".env",
    ".cdsapirc",
    ".private-data-root",
    "credentials.json",
    "secrets.json",
    "workspace.json",
    "workspace_auth.json",
    "audit_chain_secret.bin",
    "audit_head_anchor.json",
    "audit_head_anchor.pending.json",
    "audit_append.lock",
    "session_secret.bin",
}


def tracked_files(repo_root: str | Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=Path(repo_root),
        check=True,
        capture_output=True,
        text=True,
    )
    return [x.strip().replace("\\", "/") for x in result.stdout.splitlines() if x.strip()]


def boundary_violations(paths: list[str]) -> list[str]:
    bad = []
    for path in paths:
        p = path.replace("\\", "/")
        lower = p.lower()
        base = Path(p).name.lower()
        if any(lower.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
            bad.append(p)
            continue
        padded = "/" + lower.lstrip("/")
        if any(fragment in padded for fragment in FORBIDDEN_PATH_FRAGMENTS):
            bad.append(p)
            continue
        if lower.endswith(FORBIDDEN_SUFFIXES):
            bad.append(p)
            continue
        if base in FORBIDDEN_BASENAMES:
            bad.append(p)
            continue
        if base.startswith("decision-workspace-") and base.endswith(
            (".html", ".json", ".manifest.json")
        ):
            bad.append(p)
            continue
        if base.startswith("private-pilot-rehearsal-") and base.endswith(".json"):
            bad.append(p)
    return sorted(set(bad))


def assert_public_boundary(repo_root: str | Path) -> None:
    violations = boundary_violations(tracked_files(repo_root))
    if violations:
        raise RuntimeError(
            "Private-data boundary violation; forbidden tracked files: "
            + ", ".join(violations)
        )
