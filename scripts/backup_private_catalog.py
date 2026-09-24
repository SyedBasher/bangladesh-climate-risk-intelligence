from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.private_pilot_rehearsal import create_encrypted_recovery_bundle


def _passphrase() -> str:
    first = getpass.getpass("Recovery-backup passphrase: ")
    second = getpass.getpass("Confirm passphrase: ")
    if first != second:
        raise SystemExit("Passphrases do not match.")
    return first


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create an encrypted private-pilot recovery bundle containing "
            "the SQLite catalog, audit-chain key, and audit-head anchor."
        )
    )
    parser.add_argument(
        "--root",
        default=os.getenv("CLR_PRIVATE_DATA", str(ROOT / "private_data")),
    )
    parser.add_argument(
        "--destination",
        help=(
            "Optional destination directory. Prefer encrypted/off-host storage "
            "for operational backups."
        ),
    )
    args = parser.parse_args()
    result = create_encrypted_recovery_bundle(
        Path(args.root).resolve(),
        passphrase=_passphrase(),
        destination_dir=(
            Path(args.destination).resolve()
            if args.destination
            else None
        ),
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
