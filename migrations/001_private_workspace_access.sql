CREATE TABLE IF NOT EXISTS workspace_user (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    display_name TEXT,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    password_iterations INTEGER NOT NULL CHECK(password_iterations >= 100000),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    password_changed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspace_tenant_membership (
    user_id TEXT NOT NULL REFERENCES workspace_user(user_id) ON DELETE CASCADE,
    tenant_key TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('ADMIN','ANALYST','VIEWER')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(user_id, tenant_key)
);

CREATE INDEX IF NOT EXISTS workspace_membership_tenant_idx
    ON workspace_tenant_membership(tenant_key, role);

CREATE TABLE IF NOT EXISTS workspace_session (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES workspace_user(user_id) ON DELETE CASCADE,
    tenant_key TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('ADMIN','ANALYST','VIEWER')),
    token_hash TEXT NOT NULL UNIQUE CHECK(length(token_hash)=64),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    last_seen_at TEXT,
    user_agent_hash TEXT,
    client_label TEXT
);

CREATE INDEX IF NOT EXISTS workspace_session_user_idx
    ON workspace_session(user_id, tenant_key, expires_at, revoked_at);

CREATE TABLE IF NOT EXISTS workspace_audit_event (
    audit_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    actor_user_id TEXT REFERENCES workspace_user(user_id),
    tenant_key TEXT,
    action TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    outcome TEXT NOT NULL CHECK(outcome IN ('SUCCESS','DENIED','FAILURE')),
    detail_json TEXT NOT NULL DEFAULT '{}',
    prev_hash TEXT,
    event_hash TEXT NOT NULL UNIQUE CHECK(length(event_hash)=64)
);

CREATE INDEX IF NOT EXISTS workspace_audit_tenant_time_idx
    ON workspace_audit_event(tenant_key, occurred_at);

CREATE TABLE IF NOT EXISTS workspace_security_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO workspace_security_meta(key,value)
VALUES('access_schema_version','0.1.0');
