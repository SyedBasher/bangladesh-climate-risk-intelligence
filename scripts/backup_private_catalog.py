from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.private_pilot_rehearsal import create_catalog_backup


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create and integrity-check a consistent SQLite catalog backup."
    )
    parser.add_argument(
        "--root",
        default=os.getenv("CLR_PRIVATE_DATA", str(ROOT / "private_data")),
    )
    args = parser.parse_args()
    manifest = create_catalog_backup(Path(args.root).resolve())
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
