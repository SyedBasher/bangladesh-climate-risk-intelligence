# Private Authenticated Workspace 0.1

This is the first user-facing shell over the private Decision Workspace adapter.

It is intentionally a **local-only** application. Version 0.1 binds only to a loopback interface and is not a production internet deployment.

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

The session signing secret is generated separately.

Both files are inside the gitignored private workspace.

## Start the app

```bash
python scripts/run_private_workspace_app.py
```

Default address:

```
http://127.0.0.1:8765/
```

Alternative local port:

```bash
python scripts/run_private_workspace_app.py --port 8877
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

Traversal to another tenant or another private-workspace directory is rejected.

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

## Next deployment step

A later hosted private pilot should introduce, before any internet-facing use:

1. TLS and reverse-proxy hardening;
2. named users and role/tenant authorization;
3. immutable access/audit logging;
4. secret management outside the application filesystem where appropriate;
5. session revocation and password reset procedures;
6. explicit deployment backups and disaster recovery;
7. portfolio-snapshot versioning if historical portfolio reconstruction is required.

The hosted layer should continue to call the same governed adapter and renderer rather than reimplementing analytical logic.
