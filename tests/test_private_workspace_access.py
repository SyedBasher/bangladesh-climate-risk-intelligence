from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import json

import sqlite3
import pytest

import clr.private_workspace_access as access_module

from clr.local_store import catalog_path, connect_catalog, initialize_workspace
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
    for bad in (".", "..", "...", ".hidden", "TENANT."):
        with pytest.raises(ValueError):
            grant_membership(
                root,
                user_id=user["user_id"],
                tenant_key=bad,
                role="ANALYST",
            )
    with pytest.raises(ValueError):
        grant_membership(
            root,
            user_id=user["user_id"],
            tenant_key="TENANT_A",
            role="SUPERUSER",
        )


def test_concurrent_audit_appends_remain_one_valid_chain(tmp_path):
    root = _workspace(tmp_path)

    def append_event(index):
        return record_audit_event(
            root,
            actor_user_id=None,
            tenant_key="TENANT_A",
            action="CONCURRENT_TEST",
            outcome="SUCCESS",
            target_type="TEST",
            target_id=str(index),
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(append_event, range(18)))

    assert len({x["event_hash"] for x in results}) == 18
    chain = verify_audit_chain(root)
    assert chain["valid"]
    assert chain["checked_events"] == 18


def test_unknown_and_known_accounts_both_perform_password_hash_work(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    user = create_user(
        root,
        username="timing-user",
        password="synthetic-long-password",
        iterations=100_000,
    )
    grant_membership(
        root,
        user_id=user["user_id"],
        tenant_key="TENANT_A",
        role="VIEWER",
    )

    original = access_module._password_digest
    calls = []

    def counted(password, salt, iterations):
        calls.append(int(iterations))
        return original(password, salt, iterations)

    monkeypatch.setattr(access_module, "_password_digest", counted)

    assert authenticate_user(
        root,
        username="missing-user",
        password="wrong-password-value",
        tenant_key="TENANT_A",
    ) is None
    missing_calls = list(calls)
    calls.clear()

    assert authenticate_user(
        root,
        username="timing-user",
        password="wrong-password-value",
        tenant_key="TENANT_A",
    ) is None
    existing_calls = list(calls)
    calls.clear()

    assert authenticate_user(
        root,
        username="../invalid",
        password="wrong-password-value",
        tenant_key="TENANT_A",
    ) is None
    invalid_calls = list(calls)

    assert sum(missing_calls) == 100_000
    assert sum(existing_calls) == 100_000
    assert sum(invalid_calls) == 100_000


def test_audit_detail_is_bounded_and_sensitive_nested_values_are_removed(tmp_path):
    root = _workspace(tmp_path)
    record_audit_event(
        root,
        actor_user_id=None,
        tenant_key="TENANT_A",
        action="LOGIN",
        outcome="DENIED",
        detail={
            "username": "u" * 20_000,
            "Password": "must-not-persist",
            "api_token": "must-not-persist",
            "nested": {
                "password": "must-not-persist",
                "credential_blob": "must-not-persist",
                "token": "must-not-persist",
                "note": "n" * 20_000,
            },
        },
    )
    with connect_catalog(root) as conn:
        detail_json = conn.execute(
            """
            SELECT detail_json
            FROM workspace_audit_event
            ORDER BY audit_event_id DESC
            LIMIT 1
            """
        ).fetchone()["detail_json"]
    assert len(detail_json.encode("utf-8")) <= access_module.MAX_AUDIT_DETAIL_BYTES
    assert "must-not-persist" not in detail_json
    assert "u" * 1000 not in detail_json
    assert verify_audit_chain(root)["valid"]


def test_session_touch_is_infrequent_and_lock_failure_is_best_effort(tmp_path):
    root = _workspace(tmp_path)
    user = create_user(
        root,
        username="touch-user",
        password="synthetic-long-password",
        iterations=100_000,
    )
    grant_membership(
        root,
        user_id=user["user_id"],
        tenant_key="TENANT_A",
        role="VIEWER",
    )
    start = datetime(2026, 9, 24, 0, 0, tzinfo=timezone.utc)
    token, session = create_session(
        root,
        user_id=user["user_id"],
        tenant_key="TENANT_A",
        role="VIEWER",
        ttl_minutes=30,
        now=start,
    )

    identity = verify_session(root, token, now=start + timedelta(minutes=1))
    assert identity["session_id"] == session["session_id"]
    with connect_catalog(root) as conn:
        seen = conn.execute(
            "SELECT last_seen_at FROM workspace_session WHERE session_id=?",
            (session["session_id"],),
        ).fetchone()["last_seen_at"]
    assert seen == start.isoformat()

    identity = verify_session(root, token, now=start + timedelta(minutes=6))
    assert identity["session_id"] == session["session_id"]
    with connect_catalog(root) as conn:
        seen = conn.execute(
            "SELECT last_seen_at FROM workspace_session WHERE session_id=?",
            (session["session_id"],),
        ).fetchone()["last_seen_at"]
    assert seen == (start + timedelta(minutes=6)).isoformat()

    locker = sqlite3.connect(catalog_path(root), timeout=0.1)
    try:
        locker.execute("BEGIN IMMEDIATE")
        identity = verify_session(
            root,
            token,
            now=start + timedelta(minutes=12),
        )
        assert identity["session_id"] == session["session_id"]
    finally:
        locker.rollback()
        locker.close()


def test_audit_tail_truncation_is_detected_by_external_anchor(tmp_path):
    root = _workspace(tmp_path)
    for index in range(4):
        record_audit_event(
            root,
            actor_user_id=None,
            tenant_key="TENANT_A",
            action="TAIL_TEST",
            outcome="SUCCESS",
            target_type="TEST",
            target_id=str(index),
        )
    baseline = verify_audit_chain(root)
    assert baseline["valid"]
    assert baseline["checked_events"] == 4
    assert baseline["anchor_event_count"] == 4

    with connect_catalog(root) as conn:
        conn.execute(
            "DELETE FROM workspace_audit_event WHERE audit_event_id=(SELECT max(audit_event_id) FROM workspace_audit_event)"
        )
        conn.commit()

    result = verify_audit_chain(root)
    assert not result["valid"]
    assert result["reason"] == "EVENT_COUNT_MISMATCH"
    assert result["anchor_event_count"] == 4
    assert result["checked_events"] == 3


def test_audit_anchor_tampering_is_detected(tmp_path):
    root = _workspace(tmp_path)
    record_audit_event(
        root,
        actor_user_id=None,
        tenant_key="TENANT_A",
        action="ANCHOR_TEST",
        outcome="SUCCESS",
    )
    anchor = root / "auth" / "audit_head_anchor.json"
    payload = json.loads(anchor.read_text(encoding="utf-8"))
    payload["event_count"] = int(payload["event_count"]) + 1
    anchor.write_text(json.dumps(payload), encoding="utf-8")

    result = verify_audit_chain(root)
    assert not result["valid"]
    assert result["reason"] == "AUDIT_ANCHOR_MAC_MISMATCH"
