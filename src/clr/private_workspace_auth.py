from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Any

AUTH_DIR = "auth"
CREDENTIAL_FILE = "workspace_auth.json"
SESSION_SECRET_FILE = "session_secret.bin"
SESSION_VERSION = 1
DEFAULT_ITERATIONS = 310_000
DEFAULT_SESSION_TTL = 60 * 60


def _private_root(root: str | Path) -> Path:
    root = Path(root).resolve()
    if not (root / ".private-data-root").exists():
        raise ValueError(
            f"Authentication requires an initialized private workspace: {root}"
        )
    return root


def auth_dir(root: str | Path) -> Path:
    path = _private_root(root) / AUTH_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def credential_path(root: str | Path) -> Path:
    return auth_dir(root) / CREDENTIAL_FILE


def session_secret_path(root: str | Path) -> Path:
    return auth_dir(root) / SESSION_SECRET_FILE


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("ascii"))


def _password_digest(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        int(iterations),
    )


def set_workspace_password(
    root: str | Path,
    password: str,
    *,
    iterations: int = DEFAULT_ITERATIONS,
) -> dict[str, Any]:
    root = _private_root(root)
    if len(password) < 12:
        raise ValueError("Workspace password must contain at least 12 characters")
    if iterations < 100_000:
        raise ValueError("PBKDF2 iterations must be at least 100000")

    salt = secrets.token_bytes(16)
    digest = _password_digest(password, salt, iterations)
    record = {
        "version": 1,
        "kdf": "PBKDF2-HMAC-SHA256",
        "iterations": int(iterations),
        "salt": _b64e(salt),
        "password_hash": _b64e(digest),
    }
    path = credential_path(root)
    path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass

    # Rotate the signing secret whenever the password changes so all
    # previously issued sessions are immediately invalidated.
    secret_path = session_secret_path(root)
    secret_path.write_bytes(secrets.token_bytes(32))
    try:
        secret_path.chmod(0o600)
    except OSError:
        pass

    return {
        "credential_path": path.relative_to(root).as_posix(),
        "session_secret_path": secret_path.relative_to(root).as_posix(),
        "kdf": record["kdf"],
        "iterations": record["iterations"],
    }


def _load_credentials(root: str | Path) -> dict[str, Any]:
    path = credential_path(root)
    if not path.exists():
        raise FileNotFoundError(
            "Private workspace password is not configured. "
            "Run scripts/set_private_workspace_password.py first."
        )
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Workspace credential file is invalid JSON") from exc
    required = {"version", "kdf", "iterations", "salt", "password_hash"}
    missing = required - set(record)
    if missing:
        raise ValueError(f"Workspace credential file is missing: {sorted(missing)}")
    if record["kdf"] != "PBKDF2-HMAC-SHA256":
        raise ValueError("Unsupported workspace password KDF")
    return record


def verify_workspace_password(root: str | Path, password: str) -> bool:
    record = _load_credentials(root)
    try:
        salt = _b64d(record["salt"])
        expected = _b64d(record["password_hash"])
        actual = _password_digest(password, salt, int(record["iterations"]))
    except Exception:
        return False
    return hmac.compare_digest(actual, expected)


def _load_session_secret(root: str | Path) -> bytes:
    path = session_secret_path(root)
    if not path.exists():
        raise FileNotFoundError(
            "Session signing secret is missing. Re-run private workspace password setup."
        )
    secret = path.read_bytes()
    if len(secret) < 32:
        raise ValueError("Session signing secret is too short")
    return secret


def create_session_token(
    root: str | Path,
    *,
    tenant_key: str,
    ttl_seconds: int = DEFAULT_SESSION_TTL,
    now: int | None = None,
) -> tuple[str, dict[str, Any]]:
    tenant = str(tenant_key).strip()
    if not tenant:
        raise ValueError("tenant_key must be non-empty")
    ttl = int(ttl_seconds)
    if ttl < 60 or ttl > 24 * 60 * 60:
        raise ValueError("Session TTL must be between 60 seconds and 24 hours")
    issued = int(time.time() if now is None else now)
    payload = {
        "v": SESSION_VERSION,
        "tenant": tenant,
        "iat": issued,
        "exp": issued + ttl,
        "nonce": secrets.token_urlsafe(16),
        "csrf": secrets.token_urlsafe(24),
    }
    encoded = _b64e(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = _b64e(
        hmac.new(
            _load_session_secret(root),
            encoded.encode("ascii"),
            hashlib.sha256,
        ).digest()
    )
    return f"{encoded}.{signature}", payload


def verify_session_token(
    root: str | Path,
    token: str,
    *,
    now: int | None = None,
) -> dict[str, Any] | None:
    try:
        encoded, supplied_sig = token.split(".", 1)
        expected_sig = _b64e(
            hmac.new(
                _load_session_secret(root),
                encoded.encode("ascii"),
                hashlib.sha256,
            ).digest()
        )
        if not hmac.compare_digest(supplied_sig, expected_sig):
            return None
        payload = json.loads(_b64d(encoded).decode("utf-8"))
        current = int(time.time() if now is None else now)
        if payload.get("v") != SESSION_VERSION:
            return None
        if not str(payload.get("tenant", "")).strip():
            return None
        if current < int(payload.get("iat", 0)) - 60:
            return None
        if current >= int(payload.get("exp", 0)):
            return None
        if not str(payload.get("csrf", "")).strip():
            return None
        return payload
    except Exception:
        return None


def validate_csrf(session: dict[str, Any], supplied: str | None) -> bool:
    expected = str(session.get("csrf", ""))
    actual = str(supplied or "")
    return bool(expected and actual and hmac.compare_digest(expected, actual))
