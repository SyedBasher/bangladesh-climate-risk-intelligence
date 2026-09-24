from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.local_store import connect_catalog
from clr.private_workspace_access import (
    create_user,
    grant_membership,
    revoke_membership,
    set_user_active,
    set_user_password,
    verify_audit_chain,
)


def _root() -> Path:
    return Path(
        os.getenv("CLR_PRIVATE_DATA", str(ROOT / "private_data"))
    ).resolve()


def _password(prompt: str) -> str:
    first = getpass.getpass(prompt)
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise SystemExit("Passwords do not match.")
    return first


def _user_id(root: Path, username: str) -> str:
    with connect_catalog(root) as conn:
        row = conn.execute(
            "SELECT user_id FROM workspace_user WHERE username=? COLLATE NOCASE",
            (username,),
        ).fetchone()
    if row is None:
        raise SystemExit(f"Unknown user: {username}")
    return row["user_id"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage private pilot users and access.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-user")
    p.add_argument("--username", required=True)
    p.add_argument("--display-name")

    p = sub.add_parser("grant")
    p.add_argument("--username", required=True)
    p.add_argument("--tenant", required=True)
    p.add_argument("--role", required=True, choices=["ADMIN", "ANALYST", "VIEWER"])

    p = sub.add_parser("revoke")
    p.add_argument("--username", required=True)
    p.add_argument("--tenant", required=True)

    p = sub.add_parser("disable")
    p.add_argument("--username", required=True)

    p = sub.add_parser("enable")
    p.add_argument("--username", required=True)

    p = sub.add_parser("reset-password")
    p.add_argument("--username", required=True)

    sub.add_parser("verify-audit")

    args = parser.parse_args()
    root = _root()

    if args.command == "create-user":
        result = create_user(
            root,
            username=args.username,
            display_name=args.display_name,
            password=_password("New password: "),
        )
        print(json.dumps(result, indent=2))
        return

    if args.command == "verify-audit":
        result = verify_audit_chain(root)
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result["valid"] else 2)

    user_id = _user_id(root, args.username)
    if args.command == "grant":
        grant_membership(
            root,
            user_id=user_id,
            tenant_key=args.tenant,
            role=args.role,
        )
        print("Access granted.")
    elif args.command == "revoke":
        revoke_membership(
            root,
            user_id=user_id,
            tenant_key=args.tenant,
        )
        print("Access revoked.")
    elif args.command == "disable":
        set_user_active(root, user_id=user_id, is_active=False)
        print("User disabled.")
    elif args.command == "enable":
        set_user_active(root, user_id=user_id, is_active=True)
        print("User enabled.")
    elif args.command == "reset-password":
        set_user_password(
            root,
            user_id=user_id,
            password=_password("New password: "),
        )
        print("Password changed and existing sessions revoked.")


if __name__ == "__main__":
    main()
