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
- current audit chain verifies;
- no active session is orphaned, tied to a disabled user, missing a membership, or carrying a stale role;
- checked-in Caddy and systemd deployment examples retain the expected loopback/TLS/service-hardening controls.

The preflight is intentionally fail-closed.

## What the restore rehearsal does

If preflight passes, the command:

1. creates a new SQLite backup using SQLite's backup API;
2. verifies the backup with integrity and foreign-key checks;
3. hashes the backup;
4. creates an isolated temporary restore workspace inside the gitignored private `tmp/` directory;
5. copies the backup into the temporary catalog path;
6. copies the matching audit-chain key only for the purpose of verification;
7. confirms the restored database hash matches the backup;
8. reruns SQLite integrity checks;
9. confirms the access schema survived restore;
10. verifies the historical audit chain;
11. checks restored access/session state for stale active sessions;
12. removes the temporary restore workspace automatically.

The live catalog is never overwritten.

## Output

A successful run creates:

- a catalog backup under `private_data/backups/catalog/`;
- its manifest with SHA-256 and integrity results;
- a rehearsal QA manifest under `private_data/outputs/qa/`.

No rehearsal manifest or backup is committed to GitHub.

## PASS criteria

The deployment rehearsal is `PASS` only when every restore check passes.

A failure in any of these areas blocks the rehearsal:

- database integrity;
- access schema;
- audit-chain verification;
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
- real backup encryption;
- restore from off-host storage;
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
