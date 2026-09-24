from __future__ import annotations

import getpass
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.private_workspace_auth import set_workspace_password


def main() -> None:
    root = Path(
        os.getenv("CLR_PRIVATE_DATA", str(ROOT / "private_data"))
    ).resolve()
    first = getpass.getpass("New private workspace password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise SystemExit("Passwords do not match.")
    result = set_workspace_password(root, first)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
