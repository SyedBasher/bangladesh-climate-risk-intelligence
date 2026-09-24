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


def _active_admin_count(root: Path) -> int:
    with connect_catalog(root) as conn:
        return int(
            conn.execute(
                """
                SELECT count(DISTINCT u.user_id) AS n
                FROM workspace_user u
                JOIN workspace_tenant_membership m
                  ON m.user_id=u.user_id
                WHERE u.is_active=1 AND m.role='ADMIN'
                """
            ).fetchone()["n"]
        )


def _actor_user_id(
    root: Path,
    actor_username: str | None,
    *,
    bootstrap_allowed: bool,
) -> str | None:
    if actor_username:
        with connect_catalog(root) as conn:
            row = conn.execute(
                """
                SELECT u.user_id,
                       max(CASE WHEN m.role='ADMIN' THEN 1 ELSE 0 END) AS is_admin
                FROM workspace_user u
                LEFT JOIN workspace_tenant_membership m
                  ON m.user_id=u.user_id
                WHERE u.username=? COLLATE NOCASE
                  AND u.is_active=1
                GROUP BY u.user_id
                """,
                (actor_username,),
            ).fetchone()
        if row is None:
            raise SystemExit(f"Unknown or disabled actor: {actor_username}")
        if not row["is_admin"]:
            raise SystemExit("CLI actor must be an active ADMIN.")
        return row["user_id"]

    if bootstrap_allowed and _active_admin_count(root) == 0:
        return None
    raise SystemExit(
        "--actor-username is required after the first ADMIN has been bootstrapped."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage private pilot users and access.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-user")
    p.add_argument("--username", required=True)
    p.add_argument("--display-name")
    p.add_argument("--actor-username")

    p = sub.add_parser("grant")
    p.add_argument("--username", required=True)
    p.add_argument("--tenant", required=True)
    p.add_argument("--role", required=True, choices=["ADMIN", "ANALYST", "VIEWER"])
    p.add_argument("--actor-username")

    p = sub.add_parser("revoke")
    p.add_argument("--username", required=True)
    p.add_argument("--tenant", required=True)
    p.add_argument("--actor-username")

    p = sub.add_parser("disable")
    p.add_argument("--username", required=True)
    p.add_argument("--actor-username")

    p = sub.add_parser("enable")
    p.add_argument("--username", required=True)
    p.add_argument("--actor-username")

    p = sub.add_parser("reset-password")
    p.add_argument("--username", required=True)
    p.add_argument("--actor-username")

    sub.add_parser("verify-audit")

    args = parser.parse_args()
    root = _root()

    if args.command == "create-user":
        actor_user_id = _actor_user_id(
            root,
            args.actor_username,
            bootstrap_allowed=True,
        )
        result = create_user(
            root,
            username=args.username,
            display_name=args.display_name,
            password=_password("New password: "),
            actor_user_id=actor_user_id,
        )
        print(json.dumps(result, indent=2))
        return

    if args.command == "verify-audit":
        result = verify_audit_chain(root)
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result["valid"] else 2)

    actor_user_id = _actor_user_id(
        root,
        args.actor_username,
        bootstrap_allowed=(args.command == "grant"),
    )
    user_id = _user_id(root, args.username)
    if args.command == "grant":
        grant_membership(
            root,
            user_id=user_id,
            tenant_key=args.tenant,
            role=args.role,
            actor_user_id=actor_user_id,
        )
        print("Access granted.")
    elif args.command == "revoke":
        revoke_membership(
            root,
            user_id=user_id,
            tenant_key=args.tenant,
            actor_user_id=actor_user_id,
        )
        print("Access revoked.")
    elif args.command == "disable":
        set_user_active(
            root,
            user_id=user_id,
            is_active=False,
            actor_user_id=actor_user_id,
        )
        print("User disabled.")
    elif args.command == "enable":
        set_user_active(
            root,
            user_id=user_id,
            is_active=True,
            actor_user_id=actor_user_id,
        )
        print("User enabled.")
    elif args.command == "reset-password":
        set_user_password(
            root,
            user_id=user_id,
            password=_password("New password: "),
            actor_user_id=actor_user_id,
        )
        print("Password changed and existing sessions revoked.")


if __name__ == "__main__":
    main()
