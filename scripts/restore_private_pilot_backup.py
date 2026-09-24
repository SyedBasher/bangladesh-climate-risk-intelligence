from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.private_pilot_rehearsal import restore_encrypted_recovery_bundle


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Restore an encrypted private-pilot recovery bundle into a new, "
            "empty recovery directory. The live workspace is never overwritten."
        )
    )
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()

    target = Path(args.target).resolve()
    if target.exists() and any(target.iterdir()):
        raise SystemExit("Restore target must be empty.")
    passphrase = getpass.getpass("Recovery-backup passphrase: ")
    result = restore_encrypted_recovery_bundle(
        Path(args.bundle).resolve(),
        target,
        passphrase=passphrase,
    )
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
