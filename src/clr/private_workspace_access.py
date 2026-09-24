from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .local_store import canonical_tenant_key, connect_catalog, utc_now

ACCESS_SCHEMA_VERSION = "0.1.0"
DEFAULT_ITERATIONS = 310_000
DEFAULT_SESSION_MINUTES = 60
AUDIT_SECRET_FILE = "audit_chain_secret.bin"
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._@+-]{3,128}$")
ROLES = {"ADMIN", "ANALYST", "VIEWER"}
PERMISSIONS = {
    "ADMIN": {"VIEW_REPORT", "GENERATE_REPORT", "MANAGE_ACCESS", "VIEW_AUDIT"},
    "ANALYST": {"VIEW_REPORT", "GENERATE_REPORT"},
    "VIEWER": {"VIEW_REPORT"},
}


def _private_root(root: str | Path) -> Path:
    root = Path(root).resolve()
    if not (root / ".private-data-root").exists():
        raise ValueError(f"Not an initialized private workspace: {root}")
    return root


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text.encode("ascii"))


def _password_digest(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        int(iterations),
    )


def _validate_username(username: str) -> str:
    value = str(username).strip()
    if not _USERNAME_RE.fullmatch(value):
        raise ValueError(
            "username must be 3-128 characters using letters, numbers, dot, underscore, @, + or hyphen"
        )
    return value


def _validate_tenant(tenant_key: str) -> str:
    return canonical_tenant_key(tenant_key)


def _validate_role(role: str) -> str:
    value = str(role).upper().strip()
    if value not in ROLES:
        raise ValueError(f"role must be one of {sorted(ROLES)}")
    return value


def apply_access_schema(root: str | Path, migration_path: str | Path) -> dict[str, Any]:
    root = _private_root(root)
    sql = Path(migration_path).read_text(encoding="utf-8")
    with connect_catalog(root) as conn:
        conn.executescript(sql)
        row = conn.execute(
            "SELECT value FROM workspace_security_meta WHERE key='access_schema_version'"
        ).fetchone()
        conn.commit()
    return {
        "access_schema_version": row["value"] if row else None,
        "catalog": "catalog/climate_risk.sqlite",
    }


def access_schema_ready(root: str | Path) -> bool:
    try:
        with connect_catalog(_private_root(root)) as conn:
            row = conn.execute(
                "SELECT value FROM workspace_security_meta WHERE key='access_schema_version'"
            ).fetchone()
        return bool(row and row["value"] == ACCESS_SCHEMA_VERSION)
    except sqlite3.OperationalError:
        return False


def _audit_secret_path(root: str | Path) -> Path:
    root = _private_root(root)
    path = root / "auth" / AUDIT_SECRET_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def ensure_audit_secret(root: str | Path) -> Path:
    path = _audit_secret_path(root)
    if not path.exists():
        path.write_bytes(secrets.token_bytes(32))
        try:
            path.chmod(0o600)
        except OSError:
            pass
    if len(path.read_bytes()) < 32:
        raise ValueError("Audit-chain secret is too short")
    return path


def _audit_secret(root: str | Path) -> bytes:
    return ensure_audit_secret(root).read_bytes()


def _event_hash(secret: bytes, record: dict[str, Any]) -> str:
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def record_audit_event(
    root: str | Path,
    *,
    actor_user_id: str | None,
    tenant_key: str | None,
    action: str,
    outcome: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    root = _private_root(root)
    outcome = str(outcome).upper().strip()
    if outcome not in {"SUCCESS", "DENIED", "FAILURE"}:
        raise ValueError("Invalid audit outcome")
    action = str(action).strip()
    if not action:
        raise ValueError("Audit action must be non-empty")
    occurred_at = occurred_at or utc_now()
    clean_detail = dict(detail or {})
    for forbidden in ("password", "token", "session_token", "secret"):
        clean_detail.pop(forbidden, None)

    with connect_catalog(root) as conn:
        # Serialize the read-head + append operation so concurrent web requests
        # cannot create two events pointing at the same prior hash.
        conn.execute("BEGIN IMMEDIATE")
        prev = conn.execute(
            "SELECT event_hash FROM workspace_audit_event ORDER BY audit_event_id DESC LIMIT 1"
        ).fetchone()
        prev_hash = prev["event_hash"] if prev else None
        record = {
            "occurred_at": occurred_at,
            "actor_user_id": actor_user_id,
            "tenant_key": tenant_key,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "outcome": outcome,
            "detail": clean_detail,
            "prev_hash": prev_hash,
        }
        event_hash = _event_hash(_audit_secret(root), record)
        cur = conn.execute(
            """
            INSERT INTO workspace_audit_event(
                occurred_at,actor_user_id,tenant_key,action,target_type,target_id,
                outcome,detail_json,prev_hash,event_hash
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                occurred_at,
                actor_user_id,
                tenant_key,
                action,
                target_type,
                target_id,
                outcome,
                json.dumps(clean_detail, sort_keys=True, separators=(",", ":")),
                prev_hash,
                event_hash,
            ),
        )
        conn.commit()
    return {"audit_event_id": cur.lastrowid, "event_hash": event_hash, "prev_hash": prev_hash}


def verify_audit_chain(root: str | Path) -> dict[str, Any]:
    root = _private_root(root)
    secret = _audit_secret(root)
    with connect_catalog(root) as conn:
        rows = conn.execute(
            "SELECT * FROM workspace_audit_event ORDER BY audit_event_id"
        ).fetchall()
    expected_prev = None
    for row in rows:
        detail = json.loads(row["detail_json"] or "{}")
        record = {
            "occurred_at": row["occurred_at"],
            "actor_user_id": row["actor_user_id"],
            "tenant_key": row["tenant_key"],
            "action": row["action"],
            "target_type": row["target_type"],
            "target_id": row["target_id"],
            "outcome": row["outcome"],
            "detail": detail,
            "prev_hash": row["prev_hash"],
        }
        if row["prev_hash"] != expected_prev:
            return {
                "valid": False,
                "checked_events": int(row["audit_event_id"]) - 1,
                "failed_event_id": row["audit_event_id"],
                "reason": "PREVIOUS_HASH_MISMATCH",
            }
        calculated = _event_hash(secret, record)
        if not hmac.compare_digest(calculated, row["event_hash"]):
            return {
                "valid": False,
                "checked_events": int(row["audit_event_id"]) - 1,
                "failed_event_id": row["audit_event_id"],
                "reason": "EVENT_HASH_MISMATCH",
            }
        expected_prev = row["event_hash"]
    return {
        "valid": True,
        "checked_events": len(rows),
        "failed_event_id": None,
        "reason": None,
        "head_hash": expected_prev,
    }


def create_user(
    root: str | Path,
    *,
    username: str,
    password: str,
    display_name: str | None = None,
    iterations: int = DEFAULT_ITERATIONS,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    root = _private_root(root)
    username = _validate_username(username)
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    if iterations < 100_000:
        raise ValueError("PBKDF2 iterations must be at least 100000")
    salt = secrets.token_bytes(16)
    digest = _password_digest(password, salt, iterations)
    user_id = str(uuid.uuid4())
    now = utc_now()
    with connect_catalog(root) as conn:
        conn.execute(
            """
            INSERT INTO workspace_user(
                user_id,username,display_name,password_hash,password_salt,
                password_iterations,is_active,created_at,updated_at,password_changed_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                user_id,
                username,
                display_name,
                _b64e(digest),
                _b64e(salt),
                int(iterations),
                1,
                now,
                now,
                now,
            ),
        )
        conn.commit()
    record_audit_event(
        root,
        actor_user_id=actor_user_id,
        tenant_key=None,
        action="USER_CREATED",
        outcome="SUCCESS",
        target_type="USER",
        target_id=user_id,
        detail={"username": username},
    )
    return {"user_id": user_id, "username": username, "is_active": True}


def set_user_password(
    root: str | Path,
    *,
    user_id: str,
    password: str,
    iterations: int = DEFAULT_ITERATIONS,
    actor_user_id: str | None = None,
) -> None:
    root = _private_root(root)
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    salt = secrets.token_bytes(16)
    digest = _password_digest(password, salt, iterations)
    now = utc_now()
    with connect_catalog(root) as conn:
        cur = conn.execute(
            """
            UPDATE workspace_user
            SET password_hash=?,password_salt=?,password_iterations=?,
                updated_at=?,password_changed_at=?
            WHERE user_id=?
            """,
            (_b64e(digest), _b64e(salt), int(iterations), now, now, user_id),
        )
        if cur.rowcount != 1:
            raise KeyError(f"Unknown user: {user_id}")
        conn.execute(
            """
            UPDATE workspace_session
            SET revoked_at=?
            WHERE user_id=? AND revoked_at IS NULL
            """,
            (now, user_id),
        )
        conn.commit()
    record_audit_event(
        root,
        actor_user_id=actor_user_id,
        tenant_key=None,
        action="PASSWORD_CHANGED",
        outcome="SUCCESS",
        target_type="USER",
        target_id=user_id,
    )


def set_user_active(
    root: str | Path,
    *,
    user_id: str,
    is_active: bool,
    actor_user_id: str | None = None,
) -> None:
    root = _private_root(root)
    now = utc_now()
    with connect_catalog(root) as conn:
        cur = conn.execute(
            "UPDATE workspace_user SET is_active=?,updated_at=? WHERE user_id=?",
            (1 if is_active else 0, now, user_id),
        )
        if cur.rowcount != 1:
            raise KeyError(f"Unknown user: {user_id}")
        if not is_active:
            conn.execute(
                "UPDATE workspace_session SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                (now, user_id),
            )
        conn.commit()
    record_audit_event(
        root,
        actor_user_id=actor_user_id,
        tenant_key=None,
        action="USER_ENABLED" if is_active else "USER_DISABLED",
        outcome="SUCCESS",
        target_type="USER",
        target_id=user_id,
    )


def grant_membership(
    root: str | Path,
    *,
    user_id: str,
    tenant_key: str,
    role: str,
    actor_user_id: str | None = None,
) -> None:
    root = _private_root(root)
    tenant = _validate_tenant(tenant_key)
    role = _validate_role(role)
    now = utc_now()
    with connect_catalog(root) as conn:
        user = conn.execute(
            "SELECT 1 FROM workspace_user WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if user is None:
            raise KeyError(f"Unknown user: {user_id}")
        conn.execute(
            """
            INSERT INTO workspace_tenant_membership(
                user_id,tenant_key,role,created_at,updated_at
            ) VALUES(?,?,?,?,?)
            ON CONFLICT(user_id,tenant_key)
            DO UPDATE SET role=excluded.role,updated_at=excluded.updated_at
            """,
            (user_id, tenant, role, now, now),
        )
        conn.execute(
            """
            UPDATE workspace_session
            SET revoked_at=?
            WHERE user_id=? AND tenant_key=? AND revoked_at IS NULL
            """,
            (now, user_id, tenant),
        )
        conn.commit()
    record_audit_event(
        root,
        actor_user_id=actor_user_id,
        tenant_key=tenant,
        action="MEMBERSHIP_GRANTED",
        outcome="SUCCESS",
        target_type="USER",
        target_id=user_id,
        detail={"role": role},
    )


def revoke_membership(
    root: str | Path,
    *,
    user_id: str,
    tenant_key: str,
    actor_user_id: str | None = None,
) -> None:
    root = _private_root(root)
    tenant = _validate_tenant(tenant_key)
    now = utc_now()
    with connect_catalog(root) as conn:
        conn.execute(
            "DELETE FROM workspace_tenant_membership WHERE user_id=? AND tenant_key=?",
            (user_id, tenant),
        )
        conn.execute(
            """
            UPDATE workspace_session
            SET revoked_at=?
            WHERE user_id=? AND tenant_key=? AND revoked_at IS NULL
            """,
            (now, user_id, tenant),
        )
        conn.commit()
    record_audit_event(
        root,
        actor_user_id=actor_user_id,
        tenant_key=tenant,
        action="MEMBERSHIP_REVOKED",
        outcome="SUCCESS",
        target_type="USER",
        target_id=user_id,
    )


def authenticate_user(
    root: str | Path,
    *,
    username: str,
    password: str,
    tenant_key: str,
) -> dict[str, Any] | None:
    root = _private_root(root)
    try:
        username = _validate_username(username)
        tenant = _validate_tenant(tenant_key)
    except ValueError:
        return None
    with connect_catalog(root) as conn:
        row = conn.execute(
            """
            SELECT u.*,m.role
            FROM workspace_user u
            JOIN workspace_tenant_membership m ON m.user_id=u.user_id
            WHERE u.username=? COLLATE NOCASE
              AND m.tenant_key=?
            """,
            (username, tenant),
        ).fetchone()
    if row is None or not row["is_active"]:
        return None
    try:
        actual = _password_digest(
            password,
            _b64d(row["password_salt"]),
            int(row["password_iterations"]),
        )
        expected = _b64d(row["password_hash"])
    except Exception:
        return None
    if not hmac.compare_digest(actual, expected):
        return None
    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "tenant_key": tenant,
        "role": row["role"],
    }


def role_allows(role: str, permission: str) -> bool:
    role = _validate_role(role)
    return str(permission).upper().strip() in PERMISSIONS[role]


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(
    root: str | Path,
    *,
    user_id: str,
    tenant_key: str,
    role: str,
    ttl_minutes: int = DEFAULT_SESSION_MINUTES,
    user_agent: str | None = None,
    client_label: str | None = None,
    now: datetime | None = None,
) -> tuple[str, dict[str, Any]]:
    root = _private_root(root)
    tenant = _validate_tenant(tenant_key)
    role = _validate_role(role)
    ttl = int(ttl_minutes)
    if ttl < 1 or ttl > 24 * 60:
        raise ValueError("Session TTL must be between 1 minute and 24 hours")
    now = now or datetime.now(timezone.utc)
    expires = now + timedelta(minutes=ttl)
    token = secrets.token_urlsafe(48)
    session_id = str(uuid.uuid4())
    ua_hash = (
        hashlib.sha256(user_agent.encode("utf-8")).hexdigest()
        if user_agent
        else None
    )
    with connect_catalog(root) as conn:
        membership = conn.execute(
            """
            SELECT u.is_active,m.role
            FROM workspace_user u
            JOIN workspace_tenant_membership m ON m.user_id=u.user_id
            WHERE u.user_id=? AND m.tenant_key=?
            """,
            (user_id, tenant),
        ).fetchone()
        if membership is None or not membership["is_active"]:
            raise PermissionError("User is not active for the requested tenant")
        if membership["role"] != role:
            raise PermissionError("Session role does not match current membership")
        conn.execute(
            """
            INSERT INTO workspace_session(
                session_id,user_id,tenant_key,role,token_hash,created_at,expires_at,
                revoked_at,last_seen_at,user_agent_hash,client_label
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                session_id,
                user_id,
                tenant,
                role,
                _token_hash(token),
                now.isoformat(),
                expires.isoformat(),
                None,
                now.isoformat(),
                ua_hash,
                client_label,
            ),
        )
        conn.commit()
    return token, {
        "session_id": session_id,
        "user_id": user_id,
        "tenant_key": tenant,
        "role": role,
        "created_at": now.isoformat(),
        "expires_at": expires.isoformat(),
    }


def verify_session(
    root: str | Path,
    token: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    root = _private_root(root)
    now = now or datetime.now(timezone.utc)
    with connect_catalog(root) as conn:
        row = conn.execute(
            """
            SELECT s.*,u.username,u.display_name,u.is_active,m.role AS current_role
            FROM workspace_session s
            JOIN workspace_user u ON u.user_id=s.user_id
            LEFT JOIN workspace_tenant_membership m
              ON m.user_id=s.user_id AND m.tenant_key=s.tenant_key
            WHERE s.token_hash=?
            """,
            (_token_hash(token),),
        ).fetchone()
        if row is None:
            return None
        if row["revoked_at"] is not None or not row["is_active"]:
            return None
        if row["current_role"] is None or row["current_role"] != row["role"]:
            return None
        if now >= datetime.fromisoformat(row["expires_at"]):
            return None
        conn.execute(
            "UPDATE workspace_session SET last_seen_at=? WHERE session_id=?",
            (now.isoformat(), row["session_id"]),
        )
        conn.commit()
    return {
        "session_id": row["session_id"],
        "user_id": row["user_id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "tenant_key": row["tenant_key"],
        "role": row["role"],
        "expires_at": row["expires_at"],
    }


def revoke_session(
    root: str | Path,
    *,
    token: str | None = None,
    session_id: str | None = None,
    actor_user_id: str | None = None,
) -> bool:
    if not token and not session_id:
        raise ValueError("token or session_id is required")
    root = _private_root(root)
    now = utc_now()
    with connect_catalog(root) as conn:
        if token:
            row = conn.execute(
                "SELECT * FROM workspace_session WHERE token_hash=?",
                (_token_hash(token),),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM workspace_session WHERE session_id=?",
                (session_id,),
            ).fetchone()
        if row is None:
            return False
        conn.execute(
            "UPDATE workspace_session SET revoked_at=? WHERE session_id=?",
            (now, row["session_id"]),
        )
        conn.commit()
    record_audit_event(
        root,
        actor_user_id=actor_user_id or row["user_id"],
        tenant_key=row["tenant_key"],
        action="SESSION_REVOKED",
        outcome="SUCCESS",
        target_type="SESSION",
        target_id=row["session_id"],
    )
    return True
