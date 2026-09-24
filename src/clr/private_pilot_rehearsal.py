from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .local_store import catalog_path, connect_catalog, sha256_file
from .private_workspace_access import (
    ACCESS_SCHEMA_VERSION,
    access_schema_ready,
    verify_audit_chain,
)

AUDIT_SECRET_REL = Path("auth") / "audit_chain_secret.bin"


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
    with sqlite3.connect(db) as conn:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        foreign = conn.execute("PRAGMA foreign_key_check").fetchall()
    return {
        "integrity_check": row[0] if row else None,
        "foreign_key_violations": len(foreign),
        "valid": bool(row and row[0] == "ok" and not foreign),
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

    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)

    integrity = _check_sqlite_integrity(target)
    if not integrity["valid"]:
        target.unlink(missing_ok=True)
        raise ValueError("SQLite backup failed integrity checks")

    manifest = {
        "backup_type": "SQLITE_CATALOG",
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


def _copy_audit_secret_for_rehearsal(
    source_root: Path,
    restore_root: Path,
) -> bool:
    source = source_root / AUDIT_SECRET_REL
    if not source.exists():
        return False
    target = restore_root / AUDIT_SECRET_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return True


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
              AND (u.user_id IS NULL OR u.is_active=0 OR m.user_id IS NULL OR m.role<>s.role)
            """
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
        raise FileNotFoundError("Private pilot deployment examples are incomplete")

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
        "service_private_write_path": "ReadWritePaths=/srv/clr/private_data" in service,
        "service_umask": "UMask=0077" in service,
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
    audit = (
        verify_audit_chain(root)
        if access_ready and audit_secret.exists()
        else {
            "valid": False,
            "checked_events": 0,
            "reason": "AUDIT_SECRET_OR_ACCESS_SCHEMA_MISSING",
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
        "audit_chain_valid": bool(audit.get("valid")),
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
        "access_schema_version": ACCESS_SCHEMA_VERSION if access_ready else None,
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
        raise ValueError("Private pilot preflight failed; restore rehearsal not started")

    backup = create_catalog_backup(root)
    backup_path = root / backup["backup"]
    backup_hash_before = sha256_file(backup_path)

    with tempfile.TemporaryDirectory(
        prefix="clr-restore-rehearsal-",
        dir=root / "tmp",
    ) as tmp:
        restore_root = Path(tmp).resolve()
        restored_catalog = _restore_catalog_copy(backup_path, restore_root)
        copied_secret = _copy_audit_secret_for_rehearsal(root, restore_root)

        restored_hash = sha256_file(restored_catalog)
        restored_integrity = _check_sqlite_integrity(restored_catalog)
        restored_access = access_schema_ready(restore_root)
        restored_audit = (
            verify_audit_chain(restore_root)
            if copied_secret and restored_access
            else {
                "valid": False,
                "checked_events": 0,
                "reason": "AUDIT_SECRET_OR_ACCESS_SCHEMA_MISSING",
            }
        )
        restored_security = (
            _catalog_security_summary(restore_root) if restored_access else {}
        )

        checks = {
            "backup_hash_matches_restore": backup_hash_before == restored_hash,
            "restored_sqlite_integrity": restored_integrity["valid"],
            "restored_access_schema_ready": restored_access,
            "audit_secret_restored_for_test": copied_secret,
            "restored_audit_chain_valid": bool(restored_audit.get("valid")),
            "restored_no_orphan_active_sessions": (
                restored_security.get("orphan_or_stale_active_sessions", 1) == 0
            ),
        }

    result = {
        "rehearsal_type": "PRIVATE_PILOT_BACKUP_RESTORE",
        "performed_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if all(checks.values()) else "FAIL",
        "preflight": preflight,
        "backup": backup,
        "restore_checks": checks,
        "restored_sqlite": restored_integrity,
        "restored_audit": restored_audit,
        "restored_security_summary": restored_security,
        "guardrails": [
            "The live catalog was never overwritten.",
            "The restore target existed only inside the gitignored private workspace tmp directory.",
            "No plaintext session tokens are stored or restored.",
            "Audit-chain verification requires the matching private audit-chain secret.",
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
        "backup": result["backup"]["backup"],
        "checks": result["restore_checks"],
        "preflight_status": result["preflight"]["status"],
    }
