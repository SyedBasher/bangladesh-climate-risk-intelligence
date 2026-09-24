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
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

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
AUDIT_PENDING_ANCHOR_FILE = "audit_head_anchor.pending.json"
AUDIT_LOCK_FILE = "audit_append.lock"
AUDIT_ANCHOR_VERSION = 1
AUDIT_LOCK_TIMEOUT_SECONDS = 10.0
_AUDIT_APPEND_LOCK = threading.RLock()


class AuditStateError(RuntimeError):
    """Audit state cannot be advanced safely."""
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


def _audit_pending_anchor_path(root: str | Path) -> Path:
    root = _private_root(root)
    path = root / "auth" / AUDIT_PENDING_ANCHOR_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _audit_lock_path(root: str | Path) -> Path:
    root = _private_root(root)
    path = root / "auth" / AUDIT_LOCK_FILE
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


def _anchor_payload(
    root: str | Path,
    *,
    event_count: int,
    head_hash: str | None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    updated_at = updated_at or utc_now()
    body = _anchor_body(
        event_count=event_count,
        head_hash=head_hash,
        updated_at=updated_at,
    )
    return {
        **body,
        "anchor_mac": _anchor_mac(_audit_secret(root), body),
    }


def _write_anchor_payload(path: Path, payload: dict[str, Any]) -> None:
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


def _write_audit_anchor(
    root: str | Path,
    *,
    event_count: int,
    head_hash: str | None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    root = _private_root(root)
    payload = _anchor_payload(
        root,
        event_count=event_count,
        head_hash=head_hash,
        updated_at=updated_at,
    )
    path = _audit_anchor_path(root)
    _write_anchor_payload(path, payload)
    return {
        "path": path.relative_to(root).as_posix(),
        "event_count": int(payload["event_count"]),
        "head_hash": payload.get("head_hash"),
        "updated_at": payload["updated_at"],
    }


def _stage_pending_anchor(
    root: str | Path,
    *,
    event_count: int,
    head_hash: str | None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    root = _private_root(root)
    payload = _anchor_payload(
        root,
        event_count=event_count,
        head_hash=head_hash,
        updated_at=updated_at,
    )
    path = _audit_pending_anchor_path(root)
    _write_anchor_payload(path, payload)
    return payload


def _read_anchor_file(
    root: str | Path,
    path: Path,
    *,
    missing_reason: str,
) -> dict[str, Any]:
    root = _private_root(root)
    if not path.exists():
        return {"valid": False, "reason": missing_reason}
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
        "path": path.relative_to(root).as_posix(),
    }


def _read_audit_anchor(root: str | Path) -> dict[str, Any]:
    return _read_anchor_file(
        root,
        _audit_anchor_path(root),
        missing_reason="AUDIT_ANCHOR_MISSING",
    )


def _read_pending_anchor(root: str | Path) -> dict[str, Any]:
    return _read_anchor_file(
        root,
        _audit_pending_anchor_path(root),
        missing_reason="AUDIT_PENDING_ANCHOR_MISSING",
    )


@contextmanager
def _audit_process_lock(
    root: str | Path,
    *,
    timeout_seconds: float = AUDIT_LOCK_TIMEOUT_SECONDS,
):
    root = _private_root(root)
    path = _audit_lock_path(root)
    handle = path.open("a+b", buffering=0)
    try:
        try:
            path.chmod(0o600)
        except OSError:
            pass
        deadline = time.monotonic() + max(0.1, float(timeout_seconds))
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
            while True:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise AuditStateError(
                            "Timed out waiting for the audit writer lock"
                        ) from exc
                    time.sleep(0.025)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(
                        handle.fileno(),
                        fcntl.LOCK_EX | fcntl.LOCK_NB,
                    )
                    break
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise AuditStateError(
                            "Timed out waiting for the audit writer lock"
                        ) from exc
                    time.sleep(0.025)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


@contextmanager
def _audit_write_guard(root: str | Path):
    with _AUDIT_APPEND_LOCK:
        with _audit_process_lock(root):
            yield


def _event_hash(secret: bytes, record: dict[str, Any]) -> str:
    payload = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hmac.new(
        secret,
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _db_audit_state(conn: sqlite3.Connection) -> dict[str, Any]:
    count = int(
        conn.execute(
            "SELECT count(*) AS n FROM workspace_audit_event"
        ).fetchone()["n"]
    )
    head = conn.execute(
        """
        SELECT audit_event_id,event_hash
        FROM workspace_audit_event
        ORDER BY audit_event_id DESC
        LIMIT 1
        """
    ).fetchone()
    return {
        "event_count": count,
        "head_hash": head["event_hash"] if head else None,
        "head_event_id": head["audit_event_id"] if head else None,
    }


def _state_matches_anchor(
    state: dict[str, Any],
    anchor: dict[str, Any],
) -> bool:
    return bool(
        anchor.get("valid")
        and int(anchor["event_count"]) == int(state["event_count"])
        and anchor.get("head_hash") == state.get("head_hash")
    )


def _recover_pending_anchor_locked(
    root: str | Path,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    root = _private_root(root)
    pending_path = _audit_pending_anchor_path(root)
    if not pending_path.exists():
        return {"recovered": False, "discarded": False}

    pending = _read_pending_anchor(root)
    if not pending.get("valid"):
        raise AuditStateError(
            f"Pending audit anchor is invalid: {pending.get('reason')}"
        )

    state = _db_audit_state(conn)
    current = _read_audit_anchor(root)

    if _state_matches_anchor(state, pending):
        try:
            os.replace(pending_path, _audit_anchor_path(root))
        except OSError as exc:
            raise AuditStateError(
                "Committed audit state has a valid pending anchor that "
                "could not be promoted"
            ) from exc
        return {
            "recovered": True,
            "discarded": False,
            "event_count": state["event_count"],
            "head_hash": state["head_hash"],
        }

    if _state_matches_anchor(state, current):
        pending_path.unlink(missing_ok=True)
        return {"recovered": False, "discarded": True}

    raise AuditStateError(
        "Pending audit anchor matches neither the committed database "
        "state nor the current anchor"
    )


def _require_anchor_matches_db_locked(
    root: str | Path,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    recovery = _recover_pending_anchor_locked(root, conn)
    anchor = _read_audit_anchor(root)
    if not anchor.get("valid"):
        raise AuditStateError(
            f"Audit anchor is not valid: {anchor.get('reason')}"
        )
    state = _db_audit_state(conn)
    if not _state_matches_anchor(state, anchor):
        raise AuditStateError(
            "Audit database head no longer matches the authenticated anchor"
        )
    return {
        "anchor": anchor,
        "state": state,
        "recovery": recovery,
    }


def _normalize_audit_event(
    *,
    actor_user_id: str | None,
    tenant_key: str | None,
    action: str,
    outcome: str,
    target_type: str | None,
    target_id: str | None,
    detail: dict[str, Any] | None,
    occurred_at: str | None,
) -> dict[str, Any]:
    outcome_value = str(outcome).upper().strip()
    if outcome_value not in {"SUCCESS", "DENIED", "FAILURE"}:
        raise ValueError("Invalid audit outcome")
    action_value = str(action).strip()
    if not action_value:
        raise ValueError("Audit action must be non-empty")
    return {
        "occurred_at": occurred_at or utc_now(),
        "actor_user_id": actor_user_id,
        "tenant_key": (
            None if tenant_key is None else str(tenant_key)[:128]
        ),
        "action": action_value,
        "target_type": (
            None if target_type is None else str(target_type)[:64]
        ),
        "target_id": (
            None
            if target_id is None
            else str(target_id)[:MAX_AUDIT_TEXT_CHARS]
        ),
        "outcome": outcome_value,
        "detail": _bounded_audit_detail(detail),
    }


def _insert_audit_event_locked(
    root: str | Path,
    conn: sqlite3.Connection,
    event: dict[str, Any],
) -> dict[str, Any]:
    prev = conn.execute(
        """
        SELECT event_hash
        FROM workspace_audit_event
        ORDER BY audit_event_id DESC
        LIMIT 1
        """
    ).fetchone()
    prev_hash = prev["event_hash"] if prev else None
    record = {
        **event,
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
            event["occurred_at"],
            event["actor_user_id"],
            event["tenant_key"],
            event["action"],
            event["target_type"],
            event["target_id"],
            event["outcome"],
            json.dumps(
                event["detail"],
                sort_keys=True,
                separators=(",", ":"),
            ),
            prev_hash,
            event_hash,
        ),
    )
    return {
        "audit_event_id": cur.lastrowid,
        "event_hash": event_hash,
        "prev_hash": prev_hash,
    }


def _commit_audited_transaction_locked(
    root: str | Path,
    conn: sqlite3.Connection,
    *,
    updated_at: str,
) -> dict[str, Any]:
    state = _db_audit_state(conn)
    _stage_pending_anchor(
        root,
        event_count=state["event_count"],
        head_hash=state["head_hash"],
        updated_at=updated_at,
    )
    try:
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    pending_path = _audit_pending_anchor_path(root)
    try:
        os.replace(pending_path, _audit_anchor_path(root))
    except OSError as exc:
        raise AuditStateError(
            "Audited database transaction committed, but the pending "
            "audit anchor could not be promoted"
        ) from exc
    return state


def _run_audited_transaction(
    root: str | Path,
    *,
    event: dict[str, Any],
    mutation: Callable[[sqlite3.Connection], Any],
) -> tuple[Any, dict[str, Any]]:
    root = _private_root(root)
    with _audit_write_guard(root):
        with connect_catalog(root) as conn:
            conn.execute("BEGIN IMMEDIATE")
            _require_anchor_matches_db_locked(root, conn)
            try:
                result = mutation(conn)
                audit = _insert_audit_event_locked(
                    root,
                    conn,
                    event,
                )
                state = _commit_audited_transaction_locked(
                    root,
                    conn,
                    updated_at=event["occurred_at"],
                )
            except Exception:
                try:
                    conn.rollback()
                finally:
                    raise
    return result, {
        **audit,
        "anchor_event_count": state["event_count"],
    }


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
    event = _normalize_audit_event(
        actor_user_id=actor_user_id,
        tenant_key=tenant_key,
        action=action,
        outcome=outcome,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        occurred_at=occurred_at,
    )
    _, audit = _run_audited_transaction(
        root,
        event=event,
        mutation=lambda conn: None,
    )
    return audit


def _verify_audit_rows(
    rows: list[sqlite3.Row],
    secret: bytes,
) -> dict[str, Any]:
    expected_prev = None
    for index, row in enumerate(rows):
        try:
            detail = json.loads(row["detail_json"] or "{}")
        except Exception:
            return {
                "valid": False,
                "checked_events": index,
                "failed_event_id": row["audit_event_id"],
                "reason": "DETAIL_JSON_INVALID",
                "head_hash": expected_prev,
            }
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
                "checked_events": index,
                "failed_event_id": row["audit_event_id"],
                "reason": "PREVIOUS_HASH_MISMATCH",
                "head_hash": expected_prev,
            }
        calculated = _event_hash(secret, record)
        if not hmac.compare_digest(calculated, row["event_hash"]):
            return {
                "valid": False,
                "checked_events": index,
                "failed_event_id": row["audit_event_id"],
                "reason": "EVENT_HASH_MISMATCH",
                "head_hash": expected_prev,
            }
        expected_prev = row["event_hash"]
    return {
        "valid": True,
        "checked_events": len(rows),
        "failed_event_id": None,
        "reason": None,
        "head_hash": expected_prev,
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

    with _audit_write_guard(root):
        with connect_catalog(root) as conn:
            if require_anchor:
                try:
                    _recover_pending_anchor_locked(root, conn)
                except AuditStateError as exc:
                    return {
                        "valid": False,
                        "checked_events": 0,
                        "failed_event_id": None,
                        "reason": "AUDIT_ANCHOR_RECOVERY_FAILED",
                        "head_hash": None,
                        "error": str(exc),
                    }
            rows = conn.execute(
                "SELECT * FROM workspace_audit_event ORDER BY audit_event_id"
            ).fetchall()

    result = _verify_audit_rows(rows, secret)
    if not result["valid"] or not require_anchor:
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
    if anchor.get("head_hash") != result["head_hash"]:
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
    with _audit_write_guard(root):
        path = _audit_anchor_path(root)
        with connect_catalog(root) as conn:
            if path.exists():
                _recover_pending_anchor_locked(root, conn)
                anchor = _read_audit_anchor(root)
                if not anchor.get("valid"):
                    raise AuditStateError(
                        f"Existing audit anchor is invalid: "
                        f"{anchor.get('reason')}"
                    )
                return {
                    "path": anchor["path"],
                    "event_count": int(anchor["event_count"]),
                    "head_hash": anchor.get("head_hash"),
                    "bootstrapped": False,
                }

            rows = conn.execute(
                "SELECT * FROM workspace_audit_event ORDER BY audit_event_id"
            ).fetchall()
            chain = _verify_audit_rows(rows, _audit_secret(root))
            if not chain["valid"]:
                raise AuditStateError(
                    "Cannot initialize an audit anchor from an invalid chain: "
                    f"{chain['reason']}"
                )
            if chain["checked_events"]:
                raise AuditStateError(
                    "Existing audit history has no authenticated anchor. "
                    "Use the explicit re-anchor command with an operator reason."
                )
            anchored = _write_audit_anchor(
                root,
                event_count=0,
                head_hash=None,
            )
            anchored["bootstrapped"] = True
            return anchored


def reanchor_audit(
    root: str | Path,
    *,
    actor_user_id: str | None,
    reason: str,
) -> dict[str, Any]:
    root = _private_root(root)
    reason_value = str(reason).strip()
    if not reason_value:
        raise ValueError("A re-anchor reason is required")
    reason_value = reason_value[:MAX_AUDIT_TEXT_CHARS]

    with _audit_write_guard(root):
        with connect_catalog(root) as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT * FROM workspace_audit_event ORDER BY audit_event_id"
            ).fetchall()
            chain = _verify_audit_rows(rows, _audit_secret(root))
            if not chain["valid"]:
                conn.rollback()
                raise AuditStateError(
                    "Cannot re-anchor an invalid audit chain: "
                    f"{chain['reason']}"
                )

            old_anchor = _read_audit_anchor(root)
            event = _normalize_audit_event(
                actor_user_id=actor_user_id,
                tenant_key=None,
                action="AUDIT_ANCHOR_RESET",
                outcome="SUCCESS",
                target_type="AUDIT_CHAIN",
                target_id=None,
                detail={
                    "reason": reason_value,
                    "previous_anchor_reason": old_anchor.get("reason"),
                    "previous_anchor_event_count": old_anchor.get(
                        "event_count"
                    ),
                    "current_chain_event_count": chain["checked_events"],
                },
                occurred_at=utc_now(),
            )
            audit = _insert_audit_event_locked(root, conn, event)
            state = _commit_audited_transaction_locked(
                root,
                conn,
                updated_at=event["occurred_at"],
            )

    return {
        **audit,
        "anchor_event_count": state["event_count"],
        "reason": reason_value,
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
