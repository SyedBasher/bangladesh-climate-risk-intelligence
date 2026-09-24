from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.private_workspace_access import (
    AuditStateError,
    apply_access_schema,
    ensure_audit_secret,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enable named-user access control for the private pilot workspace."
    )
    parser.add_argument(
        "--root",
        default=os.getenv("CLR_PRIVATE_DATA", str(ROOT / "private_data")),
    )
    args = parser.parse_args()
    root = Path(args.root).resolve()
    try:
        result = apply_access_schema(
            root,
            ROOT / "migrations" / "001_private_workspace_access.sql",
        )
    except AuditStateError as exc:
        raise SystemExit(
            f"{exc}\n"
            "Do not delete or replace audit files to bypass this check. "
            "If this is an investigated pre-anchor workspace, use "
            "'manage_private_workspace_users.py reanchor-audit' with an "
            "active ADMIN and a documented reason."
        ) from exc
    secret = ensure_audit_secret(root)
    result["audit_secret_path"] = secret.relative_to(root).as_posix()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
