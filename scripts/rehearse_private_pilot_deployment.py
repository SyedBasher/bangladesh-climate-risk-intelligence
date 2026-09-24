from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.private_pilot_rehearsal import run_private_pilot_rehearsal


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the non-destructive private-pilot deployment rehearsal."
    )
    parser.add_argument(
        "--root",
        default=os.getenv("CLR_PRIVATE_DATA", str(ROOT / "private_data")),
    )
    args = parser.parse_args()
    result = run_private_pilot_rehearsal(
        Path(args.root).resolve(),
        repo_root=ROOT,
    )
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
