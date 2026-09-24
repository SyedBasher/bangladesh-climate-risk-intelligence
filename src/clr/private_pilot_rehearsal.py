from __future__ import annotations

import base64
import hashlib
import io
import json
import secrets
import shutil
import struct
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .local_store import (
    _sqlite_connection,
    catalog_path,
    connect_catalog,
    sha256_file,
)
from .private_workspace_access import (
    ACCESS_SCHEMA_VERSION,
    AUDIT_ANCHOR_FILE,
    AUDIT_SECRET_FILE,
    access_schema_ready,
    verify_audit_chain,
)

AUDIT_SECRET_REL = Path("auth") / AUDIT_SECRET_FILE
AUDIT_ANCHOR_REL = Path("auth") / AUDIT_ANCHOR_FILE
RECOVERY_FORMAT_VERSION = 1
RECOVERY_MAGIC = b"CLRRECOVERY1\n"
RECOVERY_KDF_ITERATIONS = 600_000
MIN_BACKUP_PASSPHRASE_CHARS = 16


def _private_root(root: str | Path) -> Path:
    root = Path(root).resolve()
    if not (root / ".private-data-root").exists():
        raise ValueError(f"Not an initialized private workspace: {root}")
    return root


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _check_sqlite_integrity(db_path: str | Path) -> dict[str, Any]:
    db = Path(db_path)
    if not db.exists():
        raise FileNotFoundError(db)
    with _sqlite_connection(db) as conn:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        foreign = conn.execute("PRAGMA foreign_key_check").fetchall()
    return {
        "integrity_check": row[0] if row else None,
        "foreign_key_violations": len(foreign),
        "valid": bool(row and row[0] == "ok" and not foreign),
    }


def _catalog_state_fingerprint(db_path: str | Path) -> dict[str, Any]:
    db = Path(db_path)
    with _sqlite_connection(db) as conn:
        tables = [
            row["name"]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        ]
        counts = {
            name: int(
                conn.execute(
                    f'SELECT count(*) AS n FROM "{name}"'
                ).fetchone()["n"]
            )
            for name in tables
        }
        audit = None
        if "workspace_audit_event" in counts:
            row = conn.execute(
                """
                SELECT count(*) AS n,
                       max(audit_event_id) AS max_id
                FROM workspace_audit_event
                """
            ).fetchone()
            head = conn.execute(
                """
                SELECT event_hash
                FROM workspace_audit_event
                ORDER BY audit_event_id DESC
                LIMIT 1
                """
            ).fetchone()
            audit = {
                "event_count": int(row["n"]),
                "max_event_id": row["max_id"],
                "head_hash": head["event_hash"] if head else None,
            }
        user_version = int(
            conn.execute("PRAGMA user_version").fetchone()[0]
        )
    body = {
        "table_row_counts": counts,
        "audit": audit,
        "user_version": user_version,
    }
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        **body,
        "state_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def create_catalog_backup(
    root: str | Path,
    *,
    destination_dir: str | Path | None = None,
) -> dict[str, Any]:
    root = _private_root(root)
    source = catalog_path(root)
    if not source.exists():
        raise FileNotFoundError(source)

    backup_dir = (
        Path(destination_dir).resolve()
        if destination_dir is not None
        else root / "backups" / "catalog"
    )
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    target = backup_dir / f"climate_risk_{stamp}.sqlite"

    source_before = _catalog_state_fingerprint(source)
    with _sqlite_connection(source) as src, _sqlite_connection(target) as dst:
        src.backup(dst)
    source_after = _catalog_state_fingerprint(source)
    backup_state = _catalog_state_fingerprint(target)

    integrity = _check_sqlite_integrity(target)
    snapshot_verified = (
        source_before["state_sha256"] == source_after["state_sha256"]
        and source_after["state_sha256"] == backup_state["state_sha256"]
    )
    if not integrity["valid"] or not snapshot_verified:
        target.unlink(missing_ok=True)
        raise ValueError(
            "SQLite backup did not pass integrity/state-snapshot verification"
        )

    manifest = {
        "backup_type": "SQLITE_CATALOG_SNAPSHOT",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": source.relative_to(root).as_posix(),
        "backup": (
            target.relative_to(root).as_posix()
            if target.is_relative_to(root)
            else str(target)
        ),
        "sha256": sha256_file(target),
        "bytes": target.stat().st_size,
        "integrity_check": integrity["integrity_check"],
        "foreign_key_violations": integrity["foreign_key_violations"],
        "source_state_sha256": source_after["state_sha256"],
        "backup_state_sha256": backup_state["state_sha256"],
        "snapshot_verified": snapshot_verified,
        "audit_snapshot": backup_state.get("audit"),
    }
    manifest_path = target.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest["manifest_path"] = (
        manifest_path.relative_to(root).as_posix()
        if manifest_path.is_relative_to(root)
        else str(manifest_path)
    )
    return manifest


def _derive_recovery_key(
    passphrase: str,
    salt: bytes,
    iterations: int,
) -> bytes:
    if len(passphrase) < MIN_BACKUP_PASSPHRASE_CHARS:
        raise ValueError(
            f"Backup passphrase must contain at least {MIN_BACKUP_PASSPHRASE_CHARS} characters"
        )
    if len(passphrase) > 4096:
        raise ValueError("Backup passphrase is too long")
    return hashlib.pbkdf2_hmac(
        "sha256",
        passphrase.encode("utf-8"),
        salt,
        int(iterations),
        dklen=32,
    )


def _tar_bytes(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        for name in sorted(files):
            data = files[name]
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mode = 0o600
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def create_encrypted_recovery_bundle(
    root: str | Path,
    *,
    passphrase: str,
    destination_dir: str | Path | None = None,
) -> dict[str, Any]:
    root = _private_root(root)
    chain = verify_audit_chain(root)
    if not chain["valid"]:
        raise ValueError(
            f"Audit chain must verify before backup: {chain['reason']}"
        )

    secret_path = root / AUDIT_SECRET_REL
    anchor_path = root / AUDIT_ANCHOR_REL
    if not secret_path.exists() or not anchor_path.exists():
        raise FileNotFoundError(
            "Audit secret and audit anchor are required for recovery backup"
        )

    destination = (
        Path(destination_dir).resolve()
        if destination_dir is not None
        else root / "backups" / "recovery"
    )
    destination.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    bundle_path = destination / f"private_pilot_{stamp}.clrbackup"

    with tempfile.TemporaryDirectory(
        prefix="clr-backup-build-",
        dir=root / "tmp",
    ) as tmp:
        temp = Path(tmp).resolve()
        catalog_manifest = create_catalog_backup(
            root,
            destination_dir=temp,
        )
        catalog_snapshot = temp / Path(catalog_manifest["backup"]).name

        recovery_manifest = {
            "format_version": RECOVERY_FORMAT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "catalog_sha256": sha256_file(catalog_snapshot),
            "catalog_state_sha256": catalog_manifest[
                "backup_state_sha256"
            ],
            "audit_event_count": int(chain["checked_events"]),
            "audit_head_hash": chain.get("head_hash"),
            "audit_secret_sha256": sha256_file(secret_path),
            "audit_anchor_sha256": sha256_file(anchor_path),
            "contents": [
                "catalog/climate_risk.sqlite",
                f"auth/{AUDIT_SECRET_FILE}",
                f"auth/{AUDIT_ANCHOR_FILE}",
                "recovery_manifest.json",
            ],
        }
        files = {
            "catalog/climate_risk.sqlite": catalog_snapshot.read_bytes(),
            f"auth/{AUDIT_SECRET_FILE}": secret_path.read_bytes(),
            f"auth/{AUDIT_ANCHOR_FILE}": anchor_path.read_bytes(),
            "recovery_manifest.json": (
                json.dumps(
                    recovery_manifest,
                    indent=2,
                    sort_keys=True,
                ) + "\n"
            ).encode("utf-8"),
        }
        plaintext = _tar_bytes(files)

    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    key = _derive_recovery_key(
        passphrase,
        salt,
        RECOVERY_KDF_ITERATIONS,
    )
    header = {
        "format_version": RECOVERY_FORMAT_VERSION,
        "cipher": "AES-256-GCM",
        "kdf": "PBKDF2-HMAC-SHA256",
        "kdf_iterations": RECOVERY_KDF_ITERATIONS,
        "salt_b64": base64.urlsafe_b64encode(salt).decode("ascii"),
        "nonce_b64": base64.urlsafe_b64encode(nonce).decode("ascii"),
    }
    header_bytes = json.dumps(
        header,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(
        nonce,
        plaintext,
        header_bytes,
    )
    bundle_path.write_bytes(
        RECOVERY_MAGIC
        + struct.pack(">I", len(header_bytes))
        + header_bytes
        + ciphertext
    )
    try:
        bundle_path.chmod(0o600)
    except OSError:
        pass

    return {
        "backup_type": "ENCRYPTED_PRIVATE_PILOT_RECOVERY",
        "format_version": RECOVERY_FORMAT_VERSION,
        "created_at": recovery_manifest["created_at"],
        "bundle": (
            bundle_path.relative_to(root).as_posix()
            if bundle_path.is_relative_to(root)
            else str(bundle_path)
        ),
        "bundle_sha256": sha256_file(bundle_path),
        "bytes": bundle_path.stat().st_size,
        "catalog_state_sha256": recovery_manifest[
            "catalog_state_sha256"
        ],
        "audit_event_count": recovery_manifest["audit_event_count"],
        "audit_head_hash": recovery_manifest["audit_head_hash"],
        "encrypted": True,
    }


def _read_encrypted_recovery_bundle(
    bundle_path: str | Path,
    *,
    passphrase: str,
) -> dict[str, bytes]:
    raw = Path(bundle_path).read_bytes()
    if not raw.startswith(RECOVERY_MAGIC):
        raise ValueError("Invalid recovery bundle magic")
    offset = len(RECOVERY_MAGIC)
    if len(raw) < offset + 4:
        raise ValueError("Truncated recovery bundle")
    header_len = struct.unpack(">I", raw[offset:offset + 4])[0]
    offset += 4
    if header_len <= 0 or header_len > 16 * 1024:
        raise ValueError("Invalid recovery bundle header length")
    header_bytes = raw[offset:offset + header_len]
    ciphertext = raw[offset + header_len:]
    header = json.loads(header_bytes.decode("utf-8"))
    if int(header.get("format_version", -1)) != RECOVERY_FORMAT_VERSION:
        raise ValueError("Unsupported recovery bundle version")
    if header.get("cipher") != "AES-256-GCM":
        raise ValueError("Unsupported recovery bundle cipher")
    salt = base64.urlsafe_b64decode(header["salt_b64"].encode("ascii"))
    nonce = base64.urlsafe_b64decode(header["nonce_b64"].encode("ascii"))
    key = _derive_recovery_key(
        passphrase,
        salt,
        int(header["kdf_iterations"]),
    )
    try:
        plaintext = AESGCM(key).decrypt(
            nonce,
            ciphertext,
            header_bytes,
        )
    except Exception as exc:
        raise ValueError(
            "Recovery bundle authentication failed"
        ) from exc

    allowed = {
        "catalog/climate_risk.sqlite",
        f"auth/{AUDIT_SECRET_FILE}",
        f"auth/{AUDIT_ANCHOR_FILE}",
        "recovery_manifest.json",
    }
    files: dict[str, bytes] = {}
    with tarfile.open(
        fileobj=io.BytesIO(plaintext),
        mode="r:gz",
    ) as tar:
        members = tar.getmembers()
        names = {member.name for member in members}
        if names != allowed:
            raise ValueError("Recovery bundle contains unexpected files")
        for member in members:
            if not member.isfile():
                raise ValueError(
                    "Recovery bundle contains a non-file member"
                )
            extracted = tar.extractfile(member)
            if extracted is None:
                raise ValueError("Recovery bundle member could not be read")
            files[member.name] = extracted.read()
    return files


def restore_encrypted_recovery_bundle(
    bundle_path: str | Path,
    restore_root: str | Path,
    *,
    passphrase: str,
) -> dict[str, Any]:
    restore_root = Path(restore_root).resolve()
    if restore_root.exists() and any(restore_root.iterdir()):
        raise ValueError("Recovery target must be empty")
    restore_root.mkdir(parents=True, exist_ok=True)
    files = _read_encrypted_recovery_bundle(
        bundle_path,
        passphrase=passphrase,
    )
    manifest = json.loads(
        files["recovery_manifest.json"].decode("utf-8")
    )

    for name, data in files.items():
        if name == "recovery_manifest.json":
            continue
        target = restore_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if name.startswith("auth/"):
            try:
                target.chmod(0o600)
            except OSError:
                pass

    (restore_root / ".private-data-root").write_text(
        "PRIVATE DATA WORKSPACE. RECOVERED FROM ENCRYPTED BUNDLE.\n",
        encoding="utf-8",
    )

    catalog = catalog_path(restore_root)
    integrity = _check_sqlite_integrity(catalog)
    state = _catalog_state_fingerprint(catalog)
    secret_ok = (
        sha256_file(restore_root / AUDIT_SECRET_REL)
        == manifest["audit_secret_sha256"]
    )
    anchor_ok = (
        sha256_file(restore_root / AUDIT_ANCHOR_REL)
        == manifest["audit_anchor_sha256"]
    )
    catalog_ok = (
        sha256_file(catalog) == manifest["catalog_sha256"]
        and state["state_sha256"] == manifest["catalog_state_sha256"]
    )
    chain = verify_audit_chain(restore_root)
    checks = {
        "sqlite_integrity": integrity["valid"],
        "catalog_snapshot_matches_manifest": catalog_ok,
        "audit_secret_matches_manifest": secret_ok,
        "audit_anchor_matches_manifest": anchor_ok,
        "audit_chain_valid": bool(chain.get("valid")),
        "audit_event_count_matches_manifest": (
            int(chain.get("checked_events", -1))
            == int(manifest["audit_event_count"])
        ),
        "audit_head_matches_manifest": (
            chain.get("head_hash") == manifest["audit_head_hash"]
        ),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "sqlite": integrity,
        "catalog_state": state,
        "audit": chain,
        "manifest": manifest,
    }


def _restore_catalog_copy(
    source_backup: str | Path,
    restore_root: str | Path,
) -> Path:
    source = Path(source_backup).resolve()
    restore_root = Path(restore_root).resolve()
    if not source.exists():
        raise FileNotFoundError(source)

    (restore_root / "catalog").mkdir(parents=True, exist_ok=True)
    (restore_root / "auth").mkdir(parents=True, exist_ok=True)
    (restore_root / ".private-data-root").write_text(
        "PRIVATE DATA WORKSPACE. RESTORE REHEARSAL ONLY.\n",
        encoding="utf-8",
    )
    target = catalog_path(restore_root)
    shutil.copy2(source, target)
    return target


def _catalog_security_summary(root: str | Path) -> dict[str, Any]:
    root = _private_root(root)
    with connect_catalog(root) as conn:
        users = conn.execute(
            "SELECT count(*) AS n FROM workspace_user"
        ).fetchone()["n"]
        active_users = conn.execute(
            "SELECT count(*) AS n FROM workspace_user WHERE is_active=1"
        ).fetchone()["n"]
        memberships = conn.execute(
            "SELECT count(*) AS n FROM workspace_tenant_membership"
        ).fetchone()["n"]
        tenants = conn.execute(
            "SELECT count(DISTINCT tenant_key) AS n FROM workspace_tenant_membership"
        ).fetchone()["n"]
        active_sessions = conn.execute(
            """
            SELECT count(*) AS n
            FROM workspace_session
            WHERE revoked_at IS NULL
              AND expires_at > ?
            """,
            (datetime.now(timezone.utc).isoformat(),),
        ).fetchone()["n"]
        orphan_sessions = conn.execute(
            """
            SELECT count(*) AS n
            FROM workspace_session s
            LEFT JOIN workspace_user u ON u.user_id=s.user_id
            LEFT JOIN workspace_tenant_membership m
              ON m.user_id=s.user_id AND m.tenant_key=s.tenant_key
            WHERE s.revoked_at IS NULL
              AND s.expires_at > ?
              AND (
                    u.user_id IS NULL
                    OR u.is_active=0
                    OR m.user_id IS NULL
                    OR m.role<>s.role
              )
            """,
            (datetime.now(timezone.utc).isoformat(),),
        ).fetchone()["n"]
    return {
        "users": users,
        "active_users": active_users,
        "memberships": memberships,
        "tenants": tenants,
        "active_sessions": active_sessions,
        "orphan_or_stale_active_sessions": orphan_sessions,
    }


def validate_deployment_examples(repo_root: str | Path) -> dict[str, Any]:
    repo_root = Path(repo_root).resolve()
    caddy_path = repo_root / "deploy" / "private_pilot" / "Caddyfile.example"
    service_path = (
        repo_root
        / "deploy"
        / "private_pilot"
        / "clr-private-pilot.service.example"
    )
    if not caddy_path.exists() or not service_path.exists():
        raise FileNotFoundError(
            "Private pilot deployment examples are incomplete"
        )

    caddy = caddy_path.read_text(encoding="utf-8")
    service = service_path.read_text(encoding="utf-8")
    checks = {
        "reverse_proxy_loopback": "reverse_proxy 127.0.0.1:8766" in caddy,
        "caddy_admin_loopback": "admin 127.0.0.1:2019" in caddy,
        "hsts_present": "Strict-Transport-Security" in caddy,
        "backend_loopback": "--host 127.0.0.1 --port 8766" in service,
        "service_no_new_privileges": "NoNewPrivileges=true" in service,
        "service_protect_system": "ProtectSystem=strict" in service,
        "service_private_tmp": "PrivateTmp=true" in service,
        "service_private_write_path": (
            "ReadWritePaths=/srv/clr/private_data" in service
        ),
        "service_umask": "UMask=0077" in service,
        "service_memory_limit": "MemoryMax=" in service,
        "service_tasks_limit": "TasksMax=" in service,
        "service_fd_limit": "LimitNOFILE=" in service,
        "service_address_families": "RestrictAddressFamilies=" in service,
        "service_protect_proc": "ProtectProc=invisible" in service,
    }
    return {
        "checks": checks,
        "valid": all(checks.values()),
    }


def preflight_private_pilot(
    root: str | Path,
    *,
    repo_root: str | Path,
) -> dict[str, Any]:
    root = _private_root(root)
    repo_root = Path(repo_root).resolve()

    db = catalog_path(root)
    if not db.exists():
        raise FileNotFoundError(db)

    access_ready = access_schema_ready(root)
    integrity = _check_sqlite_integrity(db)
    audit_secret = root / AUDIT_SECRET_REL
    audit_anchor = root / AUDIT_ANCHOR_REL
    audit = (
        verify_audit_chain(root)
        if access_ready and audit_secret.exists() and audit_anchor.exists()
        else {
            "valid": False,
            "checked_events": 0,
            "reason": "AUDIT_RECOVERY_STATE_MISSING",
        }
    )
    security = _catalog_security_summary(root) if access_ready else {}
    deploy = validate_deployment_examples(repo_root)

    checks = {
        "private_root_marker": (root / ".private-data-root").exists(),
        "catalog_exists": db.exists(),
        "sqlite_integrity": integrity["valid"],
        "access_schema_ready": access_ready,
        "audit_secret_present": audit_secret.exists(),
        "audit_anchor_present": audit_anchor.exists(),
        "audit_chain_and_anchor_valid": bool(audit.get("valid")),
        "no_orphan_active_sessions": (
            security.get("orphan_or_stale_active_sessions", 1) == 0
            if access_ready
            else False
        ),
        "deployment_examples_valid": deploy["valid"],
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "sqlite": integrity,
        "access_schema_version": (
            ACCESS_SCHEMA_VERSION if access_ready else None
        ),
        "audit": audit,
        "security_summary": security,
        "deployment_examples": deploy,
    }


def rehearse_backup_restore(
    root: str | Path,
    *,
    repo_root: str | Path,
) -> dict[str, Any]:
    root = _private_root(root)
    repo_root = Path(repo_root).resolve()

    preflight = preflight_private_pilot(root, repo_root=repo_root)
    if preflight["status"] != "PASS":
        raise ValueError(
            "Private pilot preflight failed; restore rehearsal not started"
        )

    passphrase = secrets.token_urlsafe(32)

    with tempfile.TemporaryDirectory(
        prefix="clr-restore-rehearsal-",
        dir=root / "tmp",
    ) as tmp:
        base = Path(tmp).resolve()

        raw_dir = base / "catalog_snapshot"
        backup = create_catalog_backup(
            root,
            destination_dir=raw_dir,
        )
        raw_backup = raw_dir / Path(backup["backup"]).name

        catalog_only_root = base / "catalog_only_restore"
        _restore_catalog_copy(raw_backup, catalog_only_root)
        catalog_only_audit = verify_audit_chain(catalog_only_root)
        catalog_only_fails_without_key = (
            not catalog_only_audit["valid"]
            and catalog_only_audit["reason"] == "AUDIT_SECRET_MISSING"
        )

        bundle_dir = base / "encrypted_bundle"
        recovery = create_encrypted_recovery_bundle(
            root,
            passphrase=passphrase,
            destination_dir=bundle_dir,
        )
        bundle_path = bundle_dir / Path(recovery["bundle"]).name

        restored_root = base / "encrypted_restore"
        restored = restore_encrypted_recovery_bundle(
            bundle_path,
            restored_root,
            passphrase=passphrase,
        )

        checks = {
            "catalog_only_restore_fails_without_audit_key": (
                catalog_only_fails_without_key
            ),
            "catalog_snapshot_logically_verified": bool(
                backup["snapshot_verified"]
            ),
            "encrypted_recovery_bundle_created": bool(
                recovery["encrypted"]
            ),
            "encrypted_recovery_restore_passes": (
                restored["status"] == "PASS"
            ),
            "restored_audit_chain_valid": bool(
                restored["audit"].get("valid")
            ),
            "restored_catalog_state_matches_backup": (
                restored["catalog_state"]["state_sha256"]
                == recovery["catalog_state_sha256"]
            ),
        }

    result = {
        "rehearsal_type": "PRIVATE_PILOT_BACKUP_RESTORE",
        "performed_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if all(checks.values()) else "FAIL",
        "preflight": preflight,
        "backup_rehearsal": {
            "catalog_snapshot": {
                "snapshot_verified": backup["snapshot_verified"],
                "catalog_state_sha256": backup["backup_state_sha256"],
            },
            "catalog_only_audit": catalog_only_audit,
            "encrypted_bundle": {
                "encrypted": recovery["encrypted"],
                "catalog_state_sha256": recovery[
                    "catalog_state_sha256"
                ],
                "audit_event_count": recovery["audit_event_count"],
                "audit_head_hash": recovery["audit_head_hash"],
            },
        },
        "restore_checks": checks,
        "restored_sqlite": restored["sqlite"],
        "restored_audit": restored["audit"],
        "guardrails": [
            "The live catalog was never overwritten.",
            "Catalog-only recovery is expected to fail audit verification without the matching audit key.",
            "The successful rehearsal restores the catalog, audit key, and audit anchor from an authenticated encrypted bundle.",
            "The rehearsal passphrase and decrypted recovery workspace exist only inside the temporary gitignored rehearsal directory.",
            "No plaintext session tokens are stored or restored.",
        ],
    }
    return result


def write_rehearsal_manifest(
    root: str | Path,
    result: dict[str, Any],
) -> str:
    root = _private_root(root)
    out = root / "outputs" / "qa"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"private-pilot-rehearsal-{_utc_stamp()}.json"
    path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path.relative_to(root).as_posix()


def run_private_pilot_rehearsal(
    root: str | Path,
    *,
    repo_root: str | Path,
) -> dict[str, Any]:
    result = rehearse_backup_restore(root, repo_root=repo_root)
    manifest = write_rehearsal_manifest(root, result)
    return {
        "status": result["status"],
        "manifest": manifest,
        "checks": result["restore_checks"],
        "preflight_status": result["preflight"]["status"],
    }
