from __future__ import annotations

import subprocess
from pathlib import Path

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
    ".db", ".sqlite", ".sqlite3", ".duckdb", ".parquet", ".feather",
    ".pbf", ".tif", ".tiff", ".nc", ".grib", ".grib2", ".gpkg",
    ".shp", ".shx", ".dbf", ".vrt",
)

FORBIDDEN_BASENAMES = {
    ".env", ".cdsapirc", "credentials.json", "secrets.json",
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
        if lower.endswith(FORBIDDEN_SUFFIXES):
            bad.append(p)
            continue
        if base in FORBIDDEN_BASENAMES:
            bad.append(p)
    return sorted(set(bad))


def assert_public_boundary(repo_root: str | Path) -> None:
    violations = boundary_violations(tracked_files(repo_root))
    if violations:
        raise RuntimeError(
            "Private-data boundary violation; forbidden tracked files: "
            + ", ".join(violations)
        )
