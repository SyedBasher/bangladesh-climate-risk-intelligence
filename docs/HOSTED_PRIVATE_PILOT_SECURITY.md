# Hosted Private Pilot Security Foundation 0.1

## Scope

This layer converts the local single-password workspace into a controlled named-user pilot without changing the analytical engine.

The pilot adds:

- named users;
- tenant memberships;
- three explicit roles;
- opaque revocable server-side sessions;
- role checks at both UI and action boundaries;
- tenant-confined report access;
- tamper-evident audit chaining;
- a TLS reverse-proxy deployment contract.

It does **not** make the application a general public SaaS platform.

## Separation from analytical logic

The hosted-pilot layer does not calculate:

- hazards;
- exposure metrics;
- composite scores;
- damage;
- downtime;
- PD;
- LGD;
- expected loss.

Report generation continues to call `build_and_write_private_decision_workspace()`.

All run/vintage, tenant, lineage, denominator and fail-closed controls in the underlying adapter remain active.

## Access-control schema

The optional migration is:

`migrations/001_private_workspace_access.sql`

It adds only access/security tables:

- `workspace_user`;
- `workspace_tenant_membership`;
- `workspace_session`;
- `workspace_audit_event`;
- `workspace_security_meta`.

It does not modify climate, asset, hazard, logistics or portfolio tables.

Apply it with:

```bash
python scripts/init_private_pilot_access.py
```

The migration is idempotent.

## Users and passwords

A user record stores:

- opaque UUID user ID;
- case-insensitive username;
- optional display name;
- PBKDF2-HMAC-SHA256 password hash;
- random salt;
- KDF iteration count;
- active/disabled status;
- password-change timestamp.

Plaintext passwords are never stored.

CLI user creation and password reset use hidden terminal input.

## Tenant memberships and roles

Authorization is tenant-specific.

A user can hold a different role in different tenants.

Roles are intentionally small:

| Role | View reports | Generate reports | View tenant audit | Manage access |
| --- | --- | --- | --- | --- |
| VIEWER | Yes | No | No | No |
| ANALYST | Yes | Yes | No | No |
| ADMIN | Yes | Yes | Yes | Yes |

The current pilot performs access management through the server-side CLI rather than an in-browser admin form.

This avoids exposing account-management actions until recovery, MFA and stronger administrative safeguards are designed.

## Sessions

The pilot uses opaque random session tokens.

The browser receives the token.

SQLite stores only:

- SHA-256 of the token;
- user ID;
- tenant;
- role at issuance;
- issued/expiry times;
- revocation time;
- last-seen time;
- optional hashed user-agent value.

A session becomes invalid when:

- it expires;
- it is explicitly revoked;
- the user is disabled;
- the membership is removed;
- the role changes;
- the password changes.

The browser cookie is:

- `HttpOnly`;
- `SameSite=Strict`;
- `Secure` by default in pilot mode.

The backend still binds only to loopback. TLS is terminated by the reverse proxy.

## CSRF

State-changing pilot forms use a CSRF value derived from the opaque session token.

The session token remains only in the HttpOnly cookie; the derived CSRF value is safe to place in the form.

## Audit chain

Security-relevant actions create `workspace_audit_event` rows.

Each row records:

- timestamp;
- actor user ID where known;
- tenant;
- action;
- target type/ID where appropriate;
- outcome;
- small non-secret JSON detail;
- previous event hash;
- current event hash.

The event hash is an HMAC over the canonical event body and prior hash, using:

`private_data/auth/audit_chain_secret.bin`

The verifier detects:

- modified event contents;
- broken links in the chain.

Sensitive detail keys such as password, token and secret are stripped before storage.

The chain is **tamper-evident**, not inherently immutable. Production infrastructure should additionally retain audit events in a separately protected append-only destination.

## Audited pilot actions

The web pilot records, among other actions:

- login success/denial;
- report generation success/denial/failure;
- report/file access;
- audit-log access;
- CSRF denial;
- session revocation.

The access-management module also records:

- user creation;
- password change;
- user enable/disable;
- membership grant/revoke.

## Network boundary

The application refuses non-loopback bind addresses.

A hosted topology is therefore:

```
HTTPS client
   |
TLS reverse proxy / firewall
   |
127.0.0.1:8766
   |
private pilot backend
```

The reverse proxy must not make the private data directories directly browsable.

## Information minimisation

The pilot selector continues to exclude:

- coordinates;
- borrower IDs;
- exposure-row details;
- source raster paths.

Only the authenticated tenant's selector/report paths are available.

## Error handling

Authentication failures use a generic response rather than revealing whether:

- a username exists;
- the password was wrong;
- the user lacks membership in the supplied tenant.

Detailed secrets are not written to the audit event.

## Pilot limitations

The current pilot intentionally does not implement:

- MFA;
- SSO;
- email-based password recovery;
- automated brute-force lockout;
- browser-based user administration;
- external session store;
- external log aggregation;
- hardware-backed secret storage.

These are production-hardening items, not analytical-engine requirements.

## Next step

After this security foundation is proven with synthetic and private local tests, the next engineering step should be a deployment/operations checkpoint rather than new analytical features:

1. provision one private host;
2. terminate TLS at the reverse proxy;
3. run the backend as a restricted service account;
4. create named pilot users;
5. test tenant isolation and role changes;
6. generate/report against private data;
7. verify the audit chain;
8. perform backup and restore rehearsal;
9. conduct an external security/code review before inviting outside pilot users.
