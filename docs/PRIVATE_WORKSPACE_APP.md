# Private Authenticated Workspace 0.1

> **Legacy local compatibility shell.** This shared-password interface is disabled by default and must not be used for the hosted pilot. The supported hosted path is `scripts/run_private_pilot_app.py`.

This was the first user-facing shell over the private Decision Workspace adapter.

It remains a **local-only compatibility application**. Version 0.1 binds only to a loopback interface and is not a production internet deployment.

## Architecture

```
browser on the same workstation
        |
        v
local authenticated workspace
        |
        v
private decision-workspace adapter
        |
        +--> SQLite catalog
        +--> registered Parquet
        +--> governed report assembler
        +--> printable HTML renderer
        |
        v
private_data/outputs/reports/
```

The web shell does not calculate hazards or financial losses itself.

## What the shell can do

After authentication to one tenant, a user can:

- choose an asset or portfolio;
- see only that tenant's current asset/portfolio selectors;
- choose one or more successful indicator runs explicitly;
- optionally choose one explicit compound run;
- optionally choose one explicit logistics run;
- generate the governed private Decision Workspace report;
- open the printable HTML;
- inspect the structured JSON;
- inspect the selection/hash manifest;
- view previously generated reports for the authenticated tenant.

The shell does not automatically choose a "latest" run.

## Authentication setup

Configure the password from a terminal:

```bash
python scripts/set_private_workspace_password.py
```

The command uses hidden terminal input. The password is never accepted as a command-line argument.

The private workspace stores:

```
private_data/auth/workspace_auth.json
private_data/auth/session_secret.bin
```

The password file contains only:

- KDF name;
- PBKDF2 iteration count;
- random salt;
- password hash.

The session signing secret is generated separately and is rotated whenever the workspace password changes, immediately invalidating previously issued sessions.

Both files are inside the gitignored private workspace.

## Start the legacy local app

Startup requires an explicit compatibility opt-in:

```bash
python scripts/run_private_workspace_app.py --allow-legacy-shared-password
```

Do not use this command on the hosted pilot server.

Default address:

```
http://127.0.0.1:8765/
```

Alternative local port:

```bash
python scripts/run_private_workspace_app.py --allow-legacy-shared-password --port 8877
```

The shell refuses non-loopback bindings such as:

```
0.0.0.0
192.168.x.x
public/cloud host addresses
```

Remote access is intentionally deferred until a separately governed TLS deployment exists.

## Authentication model

Version 0.1 is a single-workspace-password model.

At sign-in the user supplies:

- tenant key;
- workspace password.

For the local web shell, tenant keys must already use only letters, numbers, dot, underscore, equals, and hyphen. Leading/trailing whitespace and leading/trailing dots are rejected. Unsafe tenant strings are rejected rather than sanitized, preventing path-segment tenant IDs or alternate spellings from mapping outside the tenant report directory.

A successful session is bound to that tenant.

Sessions are:

- HMAC-SHA256 signed;
- short-lived;
- `HttpOnly`;
- `SameSite=Strict`;
- protected by a per-session CSRF token for state-changing forms.

The session payload is signed, not encrypted. It contains the tenant key, issue/expiry times, nonce and CSRF token, but no analytical data.

## Tenant isolation

The authenticated tenant controls:

- asset selectors;
- portfolio selectors;
- indicator-run selectors;
- compound-run selectors;
- logistics-run selectors;
- generated-report listing;
- report file access.

The shell does not list or display another tenant's assets, portfolios or reports.

Report-file access resolves paths only inside:

```
private_data/outputs/reports/{authenticated-tenant}/
```

Traversal to another tenant or another private-workspace directory is rejected. The resolved tenant report directory must also be a strict child of `outputs/reports`, so path confinement does not depend only on string validation.

## Information minimisation

The app selector/catalog deliberately does not display:

- latitude;
- longitude;
- borrower IDs;
- exposure-row details;
- source raster paths.

Those remain in the local analytical data plane.

The decision report itself continues to follow the existing report contract and guardrails.

## Run selection

Only `SUCCESS` processing runs with tenant-scoped evidence are offered.

Indicator runs are selected with explicit checkboxes.

Compound and route runs are optional explicit selections.

The underlying adapter still performs its own validation, including:

- successful-run requirement;
- overlapping-vintage detection;
- tenant checks;
- source-lineage checks;
- Parquet path/hash verification;
- mixed-currency portfolio blocking.

The app cannot bypass those rules.

## Generated reports

The shell calls the existing private adapter.

Generated files remain:

- structured JSON;
- printable HTML;
- selection/hash manifest.

No report is stored in the public repository.

## HTTP hardening in 0.1

Responses include:

- `Cache-Control: no-store`;
- `Pragma: no-cache`;
- `X-Content-Type-Options: nosniff`;
- `X-Frame-Options: DENY`;
- `Referrer-Policy: no-referrer`;
- a restrictive Content Security Policy.

The app also caps form bodies to 64 KiB.

## Deliberate limitations

This version is not intended for internet exposure.

It does not yet provide:

- TLS termination;
- reverse-proxy integration;
- individual user accounts;
- role-based access control;
- password reset/recovery;
- hardware/MFA authentication;
- centralized audit logs;
- SSO;
- hosted database access;
- remote deployment support.

The absence of those features is why non-loopback binding is blocked.

## Named-user hosted pilot

The named-user pilot layer described in `docs/HOSTED_PRIVATE_PILOT_SECURITY.md` now implements the first deployment-security step above this local single-password shell.

The local shell is retained only for one-workstation compatibility/testing and now requires explicit opt-in. The named-user pilot is the only supported path for role-based tenant access, revocable sessions, audit anchoring, and TLS reverse-proxy deployment.

## Hosted deployment status

The named-user hosted-pilot layer now provides the supported remote-access path. This legacy shell must not be co-hosted with it.

Remaining production controls such as MFA/SSO, separately protected append-only audit retention, infrastructure secret management, and full host disaster recovery remain deployment/production hardening items.

The hosted layer continues to call the same governed adapter and renderer rather than reimplementing analytical logic.
