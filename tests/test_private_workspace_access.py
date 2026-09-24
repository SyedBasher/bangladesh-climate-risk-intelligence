from datetime import datetime, timezone
from pathlib import Path

import pytest

from clr.local_store import connect_catalog, initialize_workspace
from clr.private_workspace_access import (
    access_schema_ready,
    apply_access_schema,
    authenticate_user,
    create_session,
    create_user,
    grant_membership,
    record_audit_event,
    revoke_membership,
    role_allows,
    set_user_active,
    set_user_password,
    verify_audit_chain,
    verify_session,
)


ROOT = Path(__file__).resolve().parents[1]


def _workspace(tmp_path):
    root = tmp_path / "private_data"
    initialize_workspace(root, ROOT / "migrations" / "000_local_private_data_plane.sql")
    apply_access_schema(root, ROOT / "migrations" / "001_private_workspace_access.sql")
    return root


def test_access_schema_is_idempotent(tmp_path):
    root = _workspace(tmp_path)
    assert access_schema_ready(root)
    second = apply_access_schema(
        root,
        ROOT / "migrations" / "001_private_workspace_access.sql",
    )
    assert second["access_schema_version"] == "0.1.0"


def test_named_user_authentication_and_role_permissions(tmp_path):
    root = _workspace(tmp_path)
    user = create_user(
        root,
        username="analyst@example.com",
        display_name="Analyst",
        password="synthetic-long-password",
        iterations=100_000,
    )
    grant_membership(
        root,
        user_id=user["user_id"],
        tenant_key="TENANT_A",
        role="ANALYST",
    )
    identity = authenticate_user(
        root,
        username="ANALYST@example.com",
        password="synthetic-long-password",
        tenant_key="TENANT_A",
    )
    assert identity is not None
    assert identity["role"] == "ANALYST"
    assert role_allows("ANALYST", "GENERATE_REPORT")
    assert role_allows("ANALYST", "VIEW_REPORT")
    assert not role_allows("ANALYST", "MANAGE_ACCESS")
    assert role_allows("VIEWER", "VIEW_REPORT")
    assert not role_allows("VIEWER", "GENERATE_REPORT")


def test_session_is_opaque_server_side_and_revoked_by_role_change(tmp_path):
    root = _workspace(tmp_path)
    user = create_user(
        root,
        username="user1",
        password="synthetic-long-password",
        iterations=100_000,
    )
    grant_membership(
        root,
        user_id=user["user_id"],
        tenant_key="TENANT_A",
        role="ANALYST",
    )
    token, session = create_session(
        root,
        user_id=user["user_id"],
        tenant_key="TENANT_A",
        role="ANALYST",
        ttl_minutes=30,
        now=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )
    assert user["user_id"] not in token
    assert verify_session(
        root,
        token,
        now=datetime(2026, 9, 24, 0, 10, tzinfo=timezone.utc),
    )["session_id"] == session["session_id"]

    grant_membership(
        root,
        user_id=user["user_id"],
        tenant_key="TENANT_A",
        role="VIEWER",
    )
    assert verify_session(
        root,
        token,
        now=datetime(2026, 9, 24, 0, 11, tzinfo=timezone.utc),
    ) is None


def test_password_change_and_disable_revoke_sessions(tmp_path):
    root = _workspace(tmp_path)
    user = create_user(
        root,
        username="user2",
        password="synthetic-long-password",
        iterations=100_000,
    )
    grant_membership(
        root,
        user_id=user["user_id"],
        tenant_key="TENANT_A",
        role="ANALYST",
    )
    token, _ = create_session(
        root,
        user_id=user["user_id"],
        tenant_key="TENANT_A",
        role="ANALYST",
        ttl_minutes=30,
    )
    assert verify_session(root, token) is not None

    set_user_password(
        root,
        user_id=user["user_id"],
        password="synthetic-new-password",
        iterations=100_000,
    )
    assert verify_session(root, token) is None

    identity = authenticate_user(
        root,
        username="user2",
        password="synthetic-new-password",
        tenant_key="TENANT_A",
    )
    assert identity is not None
    token2, _ = create_session(
        root,
        user_id=user["user_id"],
        tenant_key="TENANT_A",
        role="ANALYST",
        ttl_minutes=30,
    )
    set_user_active(root, user_id=user["user_id"], is_active=False)
    assert verify_session(root, token2) is None
    assert (
        authenticate_user(
            root,
            username="user2",
            password="synthetic-new-password",
            tenant_key="TENANT_A",
        )
        is None
    )


def test_membership_revoke_removes_access_and_session(tmp_path):
    root = _workspace(tmp_path)
    user = create_user(
        root,
        username="user3",
        password="synthetic-long-password",
        iterations=100_000,
    )
    grant_membership(
        root,
        user_id=user["user_id"],
        tenant_key="TENANT_A",
        role="VIEWER",
    )
    token, _ = create_session(
        root,
        user_id=user["user_id"],
        tenant_key="TENANT_A",
        role="VIEWER",
    )
    revoke_membership(
        root,
        user_id=user["user_id"],
        tenant_key="TENANT_A",
    )
    assert verify_session(root, token) is None
    assert (
        authenticate_user(
            root,
            username="user3",
            password="synthetic-long-password",
            tenant_key="TENANT_A",
        )
        is None
    )


def test_audit_chain_is_tamper_evident_and_redacts_sensitive_detail(tmp_path):
    root = _workspace(tmp_path)
    record_audit_event(
        root,
        actor_user_id=None,
        tenant_key="TENANT_A",
        action="LOGIN_FAILED",
        outcome="DENIED",
        detail={
            "username": "unknown",
            "password": "must-not-persist",
            "token": "must-not-persist",
        },
    )
    result = verify_audit_chain(root)
    assert result["valid"]
    assert result["checked_events"] == 1

    with connect_catalog(root) as conn:
        row = conn.execute(
            "SELECT detail_json FROM workspace_audit_event"
        ).fetchone()
        assert "must-not-persist" not in row["detail_json"]
        conn.execute(
            "UPDATE workspace_audit_event SET action='TAMPERED' WHERE audit_event_id=1"
        )
        conn.commit()

    result = verify_audit_chain(root)
    assert not result["valid"]
    assert result["reason"] == "EVENT_HASH_MISMATCH"


def test_invalid_username_tenant_and_role_fail_closed(tmp_path):
    root = _workspace(tmp_path)
    with pytest.raises(ValueError):
        create_user(
            root,
            username="../bad",
            password="synthetic-long-password",
        )
    user = create_user(
        root,
        username="safe-user",
        password="synthetic-long-password",
        iterations=100_000,
    )
    with pytest.raises(ValueError):
        grant_membership(
            root,
            user_id=user["user_id"],
            tenant_key="TENANT/A",
            role="ANALYST",
        )
    with pytest.raises(ValueError):
        grant_membership(
            root,
            user_id=user["user_id"],
            tenant_key="TENANT_A",
            role="SUPERUSER",
        )
