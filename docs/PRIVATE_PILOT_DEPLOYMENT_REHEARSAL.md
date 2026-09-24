# Private Pilot Deployment Rehearsal

This is the operational checkpoint between the hosted-private-pilot security foundation and an outside-user pilot.

It is deliberately non-destructive.

## Command

After the private workspace and named-user access schema are initialized:

```bash
python scripts/rehearse_private_pilot_deployment.py
```

or:

```bash
make -f Makefile.local private-pilot-rehearse
```

The command exits non-zero if the rehearsal does not pass.

## What the preflight checks

The preflight requires all of the following:

- private workspace marker exists;
- SQLite catalog exists;
- SQLite `PRAGMA integrity_check` returns `ok`;
- SQLite foreign-key check is clean;
- private-pilot access schema is present;
- audit-chain key exists;
- audit-head anchor exists;
- current audit chain **and** anchored event count/head verify;
- no active session is orphaned, tied to a disabled user, missing a membership, or carrying a stale role;
- checked-in Caddy and systemd deployment examples retain the expected loopback/TLS/service-hardening controls.

The preflight is intentionally fail-closed.

## What the restore rehearsal does

If preflight passes, the command performs both a **negative** and a **positive** recovery control:

1. creates a transient SQLite snapshot using SQLite's backup API;
2. verifies integrity, foreign keys, and a governed source-vs-backup logical-state fingerprint;
3. restores that catalog **without** the audit key and confirms audit verification fails with `AUDIT_SECRET_MISSING`;
4. creates an AES-256-GCM encrypted recovery bundle containing the catalog, audit key, and authenticated audit-head anchor;
5. restores that encrypted bundle into a second isolated temporary workspace;
6. verifies bundle authentication, catalog fingerprint, SQLite integrity, audit-key hash, audit-anchor hash, event count, audit head, and the complete audit chain;
7. removes all temporary plaintext snapshots and restore workspaces automatically.

The live catalog is never overwritten.

The negative control matters: the rehearsal no longer makes a catalog-only restore look recoverable by copying the live audit key into it.


## Output

A successful rehearsal creates only:

- a private QA manifest under `private_data/outputs/qa/`.

The transient SQLite snapshot, encrypted rehearsal bundle, decrypted recovery target, and ephemeral rehearsal passphrase exist only inside the gitignored temporary rehearsal directory and are removed automatically.

Operational backups are created separately with:

```bash
python scripts/backup_private_catalog.py --destination /secure/off-host/location
```

No rehearsal artifact or operational backup is committed to GitHub.


## PASS criteria

The deployment rehearsal is `PASS` only when every restore check passes.

A failure in any of these areas blocks the rehearsal:

- database integrity;
- access schema;
- anchored audit-chain verification;
- expected catalog-only recovery failure without the audit key;
- encrypted recovery-bundle authentication and restore;
- active-session consistency;
- deployment example safety checks.

## What this rehearsal does not prove

It does not test an actual cloud or server environment.

In particular it does not prove:

- DNS configuration;
- a real TLS certificate chain;
- production firewall/security-group rules;
- external log shipping;
- operating-system patch state;
- cloud IAM;
- durability of an actual off-host backup provider;
- restore from a real off-host failure scenario;
- internet-side rate limiting;
- MFA/SSO;
- vulnerability posture of the deployed host.

Those checks begin only after a private host is provisioned.

## Host deployment checkpoint

When a host is available, perform this sequence before inviting outside users:

1. provision a dedicated private pilot host;
2. create a non-login service account;
3. place the private workspace outside the repository;
4. apply the access schema;
5. configure Caddy or an equivalent TLS reverse proxy;
6. confirm the backend listens only on `127.0.0.1:8766`;
7. confirm only HTTPS/443 is externally reachable;
8. create separate VIEWER, ANALYST and ADMIN pilot accounts;
9. test each role;
10. attempt cross-tenant report and run access and confirm denial;
11. generate one private governed report;
12. verify its selection/hash manifest;
13. verify the audit chain;
14. create an encrypted off-host backup;
15. restore that backup into a clean rehearsal environment;
16. verify the restored audit chain;
17. review reverse-proxy and application logs for unexpected sensitive data;
18. run the external security review described in `docs/EXTERNAL_SECURITY_REVIEW.md`.

## Go/no-go rule

Do not invite outside pilot users merely because the application starts successfully.

The pilot is ready for an outside user only after:

- the local rehearsal passes;
- the host deployment checklist passes;
- backup restore has been demonstrated;
- tenant/role isolation has been demonstrated;
- audit verification passes after the rehearsal;
- material findings from the external security review are resolved or explicitly accepted.
