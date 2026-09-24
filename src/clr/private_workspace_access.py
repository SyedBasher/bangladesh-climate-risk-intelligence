from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .local_store import canonical_tenant_key, connect_catalog, utc_now

ACCESS_SCHEMA_VERSION = "0.1.0"
DEFAULT_ITERATIONS = 310_000
DEFAULT_SESSION_MINUTES = 60
SESSION_TOUCH_INTERVAL_MINUTES = 5
MAX_PASSWORD_CHARS = 1024
MAX_AUDIT_TEXT_CHARS = 256
MAX_AUDIT_DETAIL_ITEMS = 20
MAX_AUDIT_DETAIL_BYTES = 4096
AUDIT_SECRET_FILE = "audit_chain_secret.bin"
AUDIT_ANCHOR_FILE = "audit_head_anchor.json"
AUDIT_ANCHOR_VERSION = 1
_AUDIT_APPEND_LOCK = threading.RLock()
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


_DUMMY_AUTH_SALT = hashlib.sha256(
    b"clr-private-pilot-dummy-auth"
).digest()[:16]
_DUMMY_AUTH_EXPECTED = b"\x00" * 32


def _dummy_password_work(password: str, iterations: int) -> None:
    actual = _password_digest(
        str(password)[:MAX_PASSWORD_CHARS],
        _DUMMY_AUTH_SALT,
        max(1, int(iterations)),
    )
    hmac.compare_digest(actual, _DUMMY_AUTH_EXPECTED)


def _sanitize_audit_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 3:
        return "[truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_AUDIT_TEXT_CHARS]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, child in list(value.items())[:MAX_AUDIT_DETAIL_ITEMS]:
            key_text = str(key)[:64]
            lower_key = key_text.lower()
            if any(
                marker in lower_key
                for marker in (
                    "password",
                    "token",
                    "secret",
                    "credential",
                    "api_key",
                    "apikey",
                )
            ):
                continue
            out[key_text] = _sanitize_audit_value(child, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        return [
            _sanitize_audit_value(x, depth=depth + 1)
            for x in list(value)[:MAX_AUDIT_DETAIL_ITEMS]
        ]
    return str(value)[:MAX_AUDIT_TEXT_CHARS]


def _bounded_audit_detail(detail: dict[str, Any] | None) -> dict[str, Any]:
    clean = _sanitize_audit_value(dict(detail or {}))
    if not isinstance(clean, dict):
        clean = {"detail": clean}
    encoded = json.dumps(
        clean,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    if len(encoded) <= MAX_AUDIT_DETAIL_BYTES:
        return clean
    return {
        "detail_truncated": True,
        "detail_sha256": hashlib.sha256(encoded).hexdigest(),
        "original_sanitized_bytes": len(encoded),
    }


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
    ensure_audit_secret(root)
    anchor = initialize_audit_anchor(root)
    return {
        "access_schema_version": row["value"] if row else None,
        "catalog": "catalog/climate_risk.sqlite",
        "audit_anchor": anchor["path"],
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
    path = _audit_secret_path(root)
    if not path.exists():
        raise FileNotFoundError("Audit-chain secret is missing")
    data = path.read_bytes()
    if len(data) < 32:
        raise ValueError("Audit-chain secret is too short")
    return data


def _audit_anchor_path(root: str | Path) -> Path:
    root = _private_root(root)
    path = root / "auth" / AUDIT_ANCHOR_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _anchor_body(
    *,
    event_count: int,
    head_hash: str | None,
    updated_at: str,
) -> dict[str, Any]:
    return {
        "version": AUDIT_ANCHOR_VERSION,
        "event_count": int(event_count),
        "head_hash": head_hash,
        "updated_at": updated_at,
    }


def _anchor_mac(secret: bytes, body: dict[str, Any]) -> str:
    payload = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _write_audit_anchor(
    root: str | Path,
    *,
    event_count: int,
    head_hash: str | None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    root = _private_root(root)
    secret = _audit_secret(root)
    updated_at = updated_at or utc_now()
    body = _anchor_body(
        event_count=event_count,
        head_hash=head_hash,
        updated_at=updated_at,
    )
    payload = dict(body)
    payload["anchor_mac"] = _anchor_mac(secret, body)
    path = _audit_anchor_path(root)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return {
        "path": path.relative_to(root).as_posix(),
        "event_count": int(event_count),
        "head_hash": head_hash,
        "updated_at": updated_at,
    }


def _read_audit_anchor(root: str | Path) -> dict[str, Any]:
    path = _audit_anchor_path(root)
    if not path.exists():
        return {"valid": False, "reason": "AUDIT_ANCHOR_MISSING"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        body = _anchor_body(
            event_count=int(payload["event_count"]),
            head_hash=payload.get("head_hash"),
            updated_at=str(payload["updated_at"]),
        )
        actual = str(payload["anchor_mac"])
    except Exception:
        return {"valid": False, "reason": "AUDIT_ANCHOR_INVALID"}
    expected = _anchor_mac(_audit_secret(root), body)
    if not hmac.compare_digest(actual, expected):
        return {"valid": False, "reason": "AUDIT_ANCHOR_MAC_MISMATCH"}
    return {
        "valid": True,
        "reason": None,
        **body,
        "path": path.relative_to(_private_root(root)).as_posix(),
    }


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
    clean_detail = _bounded_audit_detail(detail)
    target_type = None if target_type is None else str(target_type)[:64]
    target_id = (
        None if target_id is None
        else str(target_id)[:MAX_AUDIT_TEXT_CHARS]
    )
    tenant_key = None if tenant_key is None else str(tenant_key)[:128]

    with _AUDIT_APPEND_LOCK:
        anchor = _read_audit_anchor(root)
        if not anchor.get("valid"):
            raise ValueError(
                f"Audit anchor is not valid: {anchor.get('reason')}"
            )
        with connect_catalog(root) as conn:
            conn.execute("BEGIN IMMEDIATE")
            prev = conn.execute(
                "SELECT event_hash FROM workspace_audit_event ORDER BY audit_event_id DESC LIMIT 1"
            ).fetchone()
            prev_hash = prev["event_hash"] if prev else None
            current_count = int(
                conn.execute(
                    "SELECT count(*) AS n FROM workspace_audit_event"
                ).fetchone()["n"]
            )
            if (
                current_count != int(anchor["event_count"])
                or prev_hash != anchor.get("head_hash")
            ):
                conn.rollback()
                raise ValueError(
                    "Audit database head no longer matches the external anchor"
                )
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
                    json.dumps(
                        clean_detail,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    prev_hash,
                    event_hash,
                ),
            )
            conn.commit()
            new_count = current_count + 1

        anchored = _write_audit_anchor(
            root,
            event_count=new_count,
            head_hash=event_hash,
            updated_at=occurred_at,
        )
    return {
        "audit_event_id": cur.lastrowid,
        "event_hash": event_hash,
        "prev_hash": prev_hash,
        "anchor_event_count": anchored["event_count"],
    }


def verify_audit_chain(
    root: str | Path,
    *,
    require_anchor: bool = True,
) -> dict[str, Any]:
    root = _private_root(root)
    try:
        secret = _audit_secret(root)
    except FileNotFoundError:
        return {
            "valid": False,
            "checked_events": 0,
            "failed_event_id": None,
            "reason": "AUDIT_SECRET_MISSING",
            "head_hash": None,
        }
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
                "head_hash": expected_prev,
            }
        calculated = _event_hash(secret, record)
        if not hmac.compare_digest(calculated, row["event_hash"]):
            return {
                "valid": False,
                "checked_events": int(row["audit_event_id"]) - 1,
                "failed_event_id": row["audit_event_id"],
                "reason": "EVENT_HASH_MISMATCH",
                "head_hash": expected_prev,
            }
        expected_prev = row["event_hash"]

    result = {
        "valid": True,
        "checked_events": len(rows),
        "failed_event_id": None,
        "reason": None,
        "head_hash": expected_prev,
    }
    if not require_anchor:
        return result

    anchor = _read_audit_anchor(root)
    if not anchor.get("valid"):
        return {
            **result,
            "valid": False,
            "reason": anchor.get("reason"),
        }
    if int(anchor["event_count"]) != len(rows):
        return {
            **result,
            "valid": False,
            "reason": "EVENT_COUNT_MISMATCH",
            "anchor_event_count": int(anchor["event_count"]),
        }
    if anchor.get("head_hash") != expected_prev:
        return {
            **result,
            "valid": False,
            "reason": "HEAD_HASH_MISMATCH",
            "anchor_head_hash": anchor.get("head_hash"),
        }
    result["anchor_event_count"] = int(anchor["event_count"])
    result["anchor_path"] = anchor["path"]
    return result


def initialize_audit_anchor(root: str | Path) -> dict[str, Any]:
    root = _private_root(root)
    path = _audit_anchor_path(root)
    if path.exists():
        anchor = _read_audit_anchor(root)
        if not anchor.get("valid"):
            raise ValueError(
                f"Existing audit anchor is invalid: {anchor.get('reason')}"
            )
        return {
            "path": anchor["path"],
            "event_count": int(anchor["event_count"]),
            "head_hash": anchor.get("head_hash"),
            "bootstrapped": False,
        }

    chain = verify_audit_chain(root, require_anchor=False)
    if not chain["valid"]:
        raise ValueError(
            f"Cannot bootstrap audit anchor from invalid chain: {chain['reason']}"
        )
    anchored = _write_audit_anchor(
        root,
        event_count=int(chain["checked_events"]),
        head_hash=chain.get("head_hash"),
    )
    anchored["bootstrapped"] = True
    return anchored


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
    if len(password) > MAX_PASSWORD_CHARS:
        raise ValueError(f"Password cannot exceed {MAX_PASSWORD_CHARS} characters")
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
    password_text = str(password)
    with connect_catalog(root) as conn:
        max_iterations = int(
            conn.execute(
                "SELECT COALESCE(MAX(password_iterations), ?) AS n FROM workspace_user",
                (DEFAULT_ITERATIONS,),
            ).fetchone()["n"]
        )
        try:
            valid_username = _validate_username(username)
            tenant = _validate_tenant(tenant_key)
        except ValueError:
            row = None
            tenant = None
        else:
            row = conn.execute(
                """
                SELECT u.*,m.role
                FROM workspace_user u
                JOIN workspace_tenant_membership m ON m.user_id=u.user_id
                WHERE u.username=? COLLATE NOCASE
                  AND m.tenant_key=?
                """,
                (valid_username, tenant),
            ).fetchone()

    if len(password_text) > MAX_PASSWORD_CHARS:
        _dummy_password_work(password_text, max_iterations)
        return None

    if row is None or not row["is_active"]:
        _dummy_password_work(password_text, max_iterations)
        return None

    try:
        iterations = int(row["password_iterations"])
        actual = _password_digest(
            password_text,
            _b64d(row["password_salt"]),
            iterations,
        )
        expected = _b64d(row["password_hash"])
        if max_iterations > iterations:
            _dummy_password_work(
                password_text,
                max_iterations - iterations,
            )
    except Exception:
        _dummy_password_work(password_text, max_iterations)
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

    last_seen = None
    if row["last_seen_at"]:
        try:
            last_seen = datetime.fromisoformat(row["last_seen_at"])
        except ValueError:
            last_seen = None
    should_touch = (
        last_seen is None
        or now - last_seen >= timedelta(minutes=SESSION_TOUCH_INTERVAL_MINUTES)
    )
    if should_touch:
        try:
            with connect_catalog(root, busy_timeout_ms=50) as conn:
                conn.execute(
                    """
                    UPDATE workspace_session
                    SET last_seen_at=?
                    WHERE session_id=?
                      AND (last_seen_at IS NULL OR last_seen_at<?)
                    """,
                    (
                        now.isoformat(),
                        row["session_id"],
                        (
                            now - timedelta(
                                minutes=SESSION_TOUCH_INTERVAL_MINUTES
                            )
                        ).isoformat(),
                    ),
                )
                conn.commit()
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "locked" not in message and "busy" not in message:
                raise

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
