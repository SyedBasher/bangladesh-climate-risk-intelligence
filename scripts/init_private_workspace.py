from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.local_store import initialize_workspace

parser = argparse.ArgumentParser(
    description="Initialize the gitignored local private-data workspace."
)
parser.add_argument(
    "--root",
    default=os.getenv("CLR_PRIVATE_DATA", str(ROOT / "private_data")),
    help="Private workspace root. Defaults to ./private_data or CLR_PRIVATE_DATA.",
)
args = parser.parse_args()

result = initialize_workspace(
    Path(args.root),
    ROOT / "migrations" / "000_local_private_data_plane.sql",
)
print(json.dumps(result, indent=2))
