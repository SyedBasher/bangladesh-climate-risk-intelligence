# External Security Review Scope

The next review should be security-focused, not a general architecture rewrite.

## Review objective

Determine whether the private pilot can safely support a small number of named outside pilot users behind a TLS reverse proxy **without weakening the existing public/private data boundary or analytical governance**.

The reviewer should identify concrete vulnerabilities, privilege-boundary failures, sensitive-data leakage, unsafe deployment assumptions and missing controls.

## In-scope code

Review at minimum:

- `src/clr/private_workspace_access.py`
- `src/clr/private_workspace_pilot_app.py`
- `src/clr/private_workspace_app.py`
- `src/clr/private_decision_workspace.py`
- `src/clr/private_pilot_rehearsal.py`
- `src/clr/decision_reports.py`
- `src/clr/decision_report_html.py`
- `src/clr/local_store.py`
- `migrations/000_local_private_data_plane.sql`
- `migrations/001_private_workspace_access.sql`
- `deploy/private_pilot/`
- `scripts/manage_private_workspace_users.py`
- `scripts/run_private_pilot_app.py`
- `scripts/rehearse_private_pilot_deployment.py`
- `scripts/backup_private_catalog.py`
- `scripts/restore_private_pilot_backup.py`
- private workspace/access/pilot/rehearsal tests;
- public-boundary enforcement.

## Security questions

The review should explicitly examine:

### Authentication

- password hashing and parameter choices;
- credential enumeration;
- password-reset effects;
- disabled-user handling;
- session-token entropy and storage;
- expiration and revocation;
- cookie flags;
- CSRF protection.

### Authorization

- tenant isolation;
- role enforcement;
- manually altered requests;
- direct-object reference risks;
- report-path confinement;
- cross-tenant run IDs;
- stale-role sessions;
- ADMIN-only audit access.

### Input/output handling

- HTML escaping;
- query/form parsing;
- path traversal;
- unsafe filenames;
- response headers;
- report content that could expose data not intended for the authenticated tenant;
- accidental logging of secrets, tokens, borrower IDs or coordinates.

### SQLite/concurrency

- transaction boundaries;
- write locking;
- audit-chain race conditions;
- DB locking/denial-of-service risks under the intended small-pilot load;
- foreign-key assumptions;
- migration safety.

### Audit

- event-chain construction;
- secret handling;
- event omission possibilities;
- audit-log tampering;
- sensitive detail leakage;
- whether an attacker with application DB write access could suppress evidence;
- distinction between tamper-evident and immutable logging.

### Deployment

- loopback binding;
- TLS proxy assumptions;
- forwarded headers;
- service-account permissions;
- systemd hardening;
- Caddy/admin exposure;
- log locations;
- firewall assumptions;
- secret placement;
- backup exposure.

### Public/private boundary

- possibility of committing real data through generated outputs, backups, QA manifests or logs;
- whether `.gitignore` and the boundary checker cover new private artifacts;
- risk of absolute private paths or credentials appearing in public artifacts.

### Analytical governance

Security changes must not create alternate report-generation paths that bypass:

- explicit run/vintage selection;
- source lineage;
- tenant checks;
- geocoding rules;
- denominator rules;
- fail-closed behavior;
- prohibition on arbitrary composite scores or automatic hazard-to-loss conversion.

## Severity convention

Report each finding as one of:

- **Critical** — credible compromise of private data, credentials, cross-tenant isolation or host control with little/no special access.
- **High** — serious privilege escalation, authentication bypass, sensitive-data exposure or integrity failure.
- **Medium** — meaningful weakness requiring conditions or limited access.
- **Low** — hardening issue with limited direct impact.
- **Informational** — documentation/maintainability issue without a demonstrated security consequence.

Do not inflate severity solely because the application handles private information.

## Evidence required for every finding

For each finding provide:

1. severity;
2. exact file/function/line or configuration block;
3. attack precondition;
4. realistic exploitation path;
5. confidentiality/integrity/availability impact;
6. whether the issue is reachable in the documented deployment model;
7. concrete fix;
8. regression test that should be added.

Do not report a theoretical issue as exploitable if the documented loopback/reverse-proxy boundary makes it unreachable.

## Required final sections

The final report should contain:

- executive summary;
- threat model;
- findings ordered by severity;
- controls that were reviewed and appear sound;
- tests attempted;
- deployment assumptions that must be verified on the real host;
- unresolved production gaps such as MFA/rate limiting/external log retention;
- a concise **outside-pilot readiness checklist**.

The reviewer should not give a binary certification. The project owner decides whether residual risk is acceptable after reviewing evidence.
