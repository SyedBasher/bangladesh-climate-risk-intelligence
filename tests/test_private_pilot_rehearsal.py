import json
import shutil
from pathlib import Path

import pytest

from clr.local_assets import import_asset_rows
from clr.local_store import (
    connect_catalog,
    initialize_workspace,
    register_source_file,
    start_processing_run,
    finish_processing_run,
    utc_now,
)
from clr.private_pilot_rehearsal import (
    create_catalog_backup,
    preflight_private_pilot,
    rehearse_backup_restore,
    run_private_pilot_rehearsal,
    validate_deployment_examples,
)
from clr.private_workspace_access import (
    apply_access_schema,
    create_session,
    create_user,
    grant_membership,
    record_audit_event,
    verify_audit_chain,
)


ROOT = Path(__file__).resolve().parents[1]


def _workspace(tmp_path):
    root = tmp_path / "private_data"
    initialize_workspace(
        root,
        ROOT / "migrations" / "000_local_private_data_plane.sql",
    )
    apply_access_schema(
        root,
        ROOT / "migrations" / "001_private_workspace_access.sql",
    )
    import_asset_rows(
        root,
        [{
            "external_system": "SYNTH",
            "external_id": "A",
            "asset_type": "FACTORY",
            "latitude": 24.0,
            "longitude": 90.4,
            "coordinate_source": "SYNTHETIC",
            "site_identity_grade": "EXACT_SITE",
            "coordinate_status": "RESOLVED",
        }],
        tenant_key="TENANT_A",
    )
    user = create_user(
        root,
        username="analyst",
        password="synthetic-long-password",
        iterations=100_000,
    )
    grant_membership(
        root,
        user_id=user["user_id"],
        tenant_key="TENANT_A",
        role="ANALYST",
    )
    record_audit_event(
        root,
        actor_user_id=user["user_id"],
        tenant_key="TENANT_A",
        action="REHEARSAL_FIXTURE_READY",
        outcome="SUCCESS",
    )
    return root, user


def test_deployment_examples_pass_static_safety_contract():
    result = validate_deployment_examples(ROOT)
    assert result["valid"]
    assert result["checks"]["reverse_proxy_loopback"]
    assert result["checks"]["backend_loopback"]
    assert result["checks"]["service_private_write_path"]
    assert result["checks"]["hsts_present"]


def test_deployment_example_validation_fails_if_backend_is_public(tmp_path):
    deploy = tmp_path / "deploy" / "private_pilot"
    deploy.mkdir(parents=True)
    caddy = (
        ROOT / "deploy" / "private_pilot" / "Caddyfile.example"
    ).read_text(encoding="utf-8")
    service = (
        ROOT
        / "deploy"
        / "private_pilot"
        / "clr-private-pilot.service.example"
    ).read_text(encoding="utf-8")
    service = service.replace("--host 127.0.0.1", "--host 0.0.0.0")
    (deploy / "Caddyfile.example").write_text(caddy, encoding="utf-8")
    (deploy / "clr-private-pilot.service.example").write_text(
        service,
        encoding="utf-8",
    )
    result = validate_deployment_examples(tmp_path)
    assert not result["valid"]
    assert not result["checks"]["backend_loopback"]


def test_preflight_checks_integrity_audit_sessions_and_deploy_config(tmp_path):
    root, _ = _workspace(tmp_path)
    result = preflight_private_pilot(root, repo_root=ROOT)
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["sqlite"]["integrity_check"] == "ok"
    assert result["audit"]["valid"]
    assert result["security_summary"]["active_users"] == 1


def test_backup_manifest_has_hash_and_integrity(tmp_path):
    root, _ = _workspace(tmp_path)
    backup = create_catalog_backup(root)
    backup_path = root / backup["backup"]
    manifest_path = root / backup["manifest_path"]
    assert backup_path.exists()
    assert manifest_path.exists()
    assert len(backup["sha256"]) == 64
    assert backup["integrity_check"] == "ok"
    assert backup["foreign_key_violations"] == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["sha256"] == backup["sha256"]


def test_backup_restore_rehearsal_is_non_destructive_and_verifies_audit(tmp_path):
    root, _ = _workspace(tmp_path)
    live_catalog = root / "catalog" / "climate_risk.sqlite"
    before = live_catalog.read_bytes()

    result = rehearse_backup_restore(root, repo_root=ROOT)

    assert result["status"] == "PASS"
    assert all(result["restore_checks"].values())
    assert result["restored_sqlite"]["integrity_check"] == "ok"
    assert result["restored_audit"]["valid"]
    assert live_catalog.read_bytes() == before
    assert not list((root / "tmp").glob("clr-restore-rehearsal-*"))


def test_full_rehearsal_writes_private_qa_manifest(tmp_path):
    root, _ = _workspace(tmp_path)
    result = run_private_pilot_rehearsal(root, repo_root=ROOT)
    assert result["status"] == "PASS"
    manifest = root / result["manifest"]
    assert manifest.exists()
    assert manifest.is_relative_to(root / "outputs" / "qa")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["guardrails"][0] == "The live catalog was never overwritten."


def test_preflight_fails_closed_on_stale_active_session(tmp_path):
    root, user = _workspace(tmp_path)
    token, session = create_session(
        root,
        user_id=user["user_id"],
        tenant_key="TENANT_A",
        role="ANALYST",
        ttl_minutes=30,
    )
    assert token
    with connect_catalog(root) as conn:
        conn.execute(
            """
            UPDATE workspace_tenant_membership
            SET role='VIEWER'
            WHERE user_id=? AND tenant_key='TENANT_A'
            """,
            (user["user_id"],),
        )
        conn.commit()

    result = preflight_private_pilot(root, repo_root=ROOT)
    assert result["status"] == "FAIL"
    assert not result["checks"]["no_orphan_active_sessions"]
    assert result["security_summary"]["orphan_or_stale_active_sessions"] == 1

    with pytest.raises(ValueError, match="preflight failed"):
        rehearse_backup_restore(root, repo_root=ROOT)


def test_rehearsal_detects_audit_tampering_before_backup(tmp_path):
    root, _ = _workspace(tmp_path)
    assert verify_audit_chain(root)["valid"]
    with connect_catalog(root) as conn:
        conn.execute(
            """
            UPDATE workspace_audit_event
            SET action='TAMPERED'
            WHERE audit_event_id=1
            """
        )
        conn.commit()

    result = preflight_private_pilot(root, repo_root=ROOT)
    assert result["status"] == "FAIL"
    assert not result["checks"]["audit_chain_valid"]

    with pytest.raises(ValueError, match="preflight failed"):
        rehearse_backup_restore(root, repo_root=ROOT)
