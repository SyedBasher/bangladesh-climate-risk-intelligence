from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.local_store import catalog_path, sha256_file

parser = argparse.ArgumentParser(
    description="Create a consistent SQLite catalog backup inside the private workspace."
)
parser.add_argument(
    "--root",
    default=os.getenv("CLR_PRIVATE_DATA", str(ROOT / "private_data")),
)
args = parser.parse_args()

workspace = Path(args.root).resolve()
source = catalog_path(workspace)
if not source.exists():
    raise SystemExit(f"Catalog not found: {source}")

stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
backup_dir = workspace / "backups" / "catalog"
backup_dir.mkdir(parents=True, exist_ok=True)
target = backup_dir / f"climate_risk_{stamp}.sqlite"

with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
    src.backup(dst)

manifest = {
    "backup_type": "SQLITE_CATALOG",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "source": source.relative_to(workspace).as_posix(),
    "backup": target.relative_to(workspace).as_posix(),
    "sha256": sha256_file(target),
    "bytes": target.stat().st_size,
}
manifest_path = target.with_suffix(".manifest.json")
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(json.dumps(manifest, indent=2))
