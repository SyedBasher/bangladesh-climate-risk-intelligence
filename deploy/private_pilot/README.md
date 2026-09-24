# Private Pilot Deployment Contract

This directory contains **examples**, not an automatic deployment.

The private-pilot backend remains bound to `127.0.0.1`. A TLS reverse proxy is the only component that should accept internet traffic.

## Required boundary

```
internet
   |
   | HTTPS :443
   v
TLS reverse proxy
   |
   | HTTP over loopback only
   v
127.0.0.1:8766
private pilot backend
   |
   v
gitignored private workspace
```

Do not expose port `8766` through the host firewall, load balancer, container ingress or cloud security group.

## Files

- `Caddyfile.example` — TLS reverse-proxy example.
- `clr-private-pilot.service.example` — systemd service-hardening example.

These files contain no credentials, tenant names, client data or deployment secrets.

## Reverse proxy

The Caddy example expects environment variables such as:

- `PILOT_HOST` — the private hostname owned by the operator.
- `PILOT_ACCESS_LOG` — a protected server-side access-log path.

The pilot backend sets `Secure` cookies by default, so browser access must be through HTTPS in hosted mode.

For local-only testing without TLS, start the backend explicitly with:

```bash
python scripts/run_private_pilot_app.py --allow-insecure-cookie
```

That flag is for workstation testing only.

## Service account

Run the application under a dedicated non-login operating-system account.

The systemd example assumes:

- repository/runtime under `/opt/bangladesh-climate-risk-intelligence`;
- private workspace under `/srv/clr/private_data`;
- only the private workspace is writable by the service.

Adapt paths to the actual host. Do not make the repository or system directories writable merely to make deployment easier.

## Firewall

The deployment should allow:

- inbound TCP 443 to the reverse proxy;
- outbound traffic only as required by the operating environment and update process.

It should not allow external inbound access to:

- 8766 — application backend;
- 2019 — Caddy admin API;
- SQLite/catalog files;
- private report directories.

## Access initialization

After the private analytical workspace exists:

```bash
python scripts/init_private_pilot_access.py
python scripts/manage_private_workspace_users.py create-user --username analyst@example.com
python scripts/manage_private_workspace_users.py grant --username analyst@example.com --tenant TENANT_A --role ANALYST
```

Passwords are entered through hidden terminal input.

## Roles

- `VIEWER` — open existing tenant reports.
- `ANALYST` — view and generate reports.
- `ADMIN` — analyst permissions plus tenant audit-log visibility and access-management authority through the CLI.

Changing a user's role, revoking membership, disabling a user or changing a password revokes affected active sessions.

## Audit

Pilot actions are written to the private SQLite catalog and linked by an HMAC hash chain.

Verify the chain with:

```bash
python scripts/manage_private_workspace_users.py verify-audit
```

This makes unauthorized modification detectable. It is **not** a substitute for filesystem, database or infrastructure controls that make logs append-only or externally retained.

For a production service, ship audit and reverse-proxy logs to a separately protected log destination.

## Secrets

The following remain inside the private workspace in the pilot:

- user password hashes and salts in SQLite;
- opaque session hashes in SQLite;
- `auth/audit_chain_secret.bin`.

Do not place any of these in GitHub.

For a production deployment, the audit-chain key and other service secrets should move to the hosting platform's secret manager or another independently controlled secret store.

## Backup and recovery

The SQLite catalog now contains both analytical lineage and access-control state. Catalog backups therefore contain sensitive authentication metadata.

A hosted pilot needs:

- encrypted backup storage;
- restricted backup credentials;
- a documented retention schedule;
- periodic restore tests;
- secure backup of the audit-chain key separate from GitHub.

A catalog restore without the corresponding audit-chain key prevents verification of the historical audit chain.

## Automated rehearsal before host exposure

Before configuring a real host, run:

```bash
python scripts/rehearse_private_pilot_deployment.py
```

The command performs a fail-closed preflight and non-destructive SQLite backup/restore rehearsal, including audit-chain verification.

See:

- `docs/PRIVATE_PILOT_DEPLOYMENT_REHEARSAL.md`
- `docs/EXTERNAL_SECURITY_REVIEW.md`

## Before a wider production launch

The pilot deliberately stops short of a full production identity platform. Before broader external use, add or validate:

- MFA or external identity provider/SSO;
- rate limiting and automated lockout controls;
- password reset/recovery workflow;
- centralized secret management;
- external append-only audit retention;
- monitored TLS/reverse-proxy configuration;
- vulnerability and dependency scanning;
- infrastructure backups and tested recovery;
- portfolio-snapshot versioning where historical portfolio reconstruction is required.
