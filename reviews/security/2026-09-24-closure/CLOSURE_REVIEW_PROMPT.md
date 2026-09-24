# Claude Code + DeepSeek Closure Re-Audit Prompt

You are conducting a **narrow security closure re-audit** of the public repository:

`SyedBasher/bangladesh-climate-risk-intelligence`

Do not perform another broad architecture review. Do not redesign the product. Your job is to verify whether the two most recent remediation tranches actually close the pilot-relevant findings identified in the 2026-09-24 DeepSeek + Claude re-audit, and whether those changes introduced any material regression.

## Required working method

Use **DeepSeek API as the primary analysis agent** and Claude Code as the orchestrator and verifier.

Claude Code must:

1. fetch the remote repository and verify the exact current `origin/main`;
2. provide DeepSeek the relevant current files, diffs and finding descriptions in focused bundles;
3. ask DeepSeek for a structured verdict on each target finding;
4. independently inspect the current code and tests;
5. execute the relevant tests/reproductions locally;
6. challenge or override a DeepSeek verdict when the repository evidence disagrees;
7. record every disagreement and the evidence used to resolve it;
8. produce one complete Markdown report, not a chat summary.

Do **not** accept a PR description, comment, README claim or test name as proof. Verify the implementation.

If DeepSeek cannot determine an item from the supplied bundle, give it the missing code or resolve the item directly through local inspection/execution. Do not convert "not determinable" into "closed".

## Repository checkpoint

Expected current `main`:

`23ee198ad2c6897d8fcc5ea451f3add91f4b2ea8`

First run:

```bash
git fetch --all --prune
git checkout main
git pull --ff-only
git rev-parse HEAD
git status --porcelain
```

If the remote SHA does not match the expected SHA, stop and state the discrepancy before reviewing.

The two remediation checkpoints to verify are:

- PR #30 — audit transaction and concurrency hardening
- PR #31 — pre-host pilot safety cleanup

Do not rely on their descriptions. Review current `main`.

## Read first

Read these files before assigning verdicts:

```text
reviews/security/2026-09-24-closure/TARGET_FINDINGS.md
docs/EXTERNAL_SECURITY_REVIEW.md
docs/HOSTED_PRIVATE_PILOT_SECURITY.md
deploy/private_pilot/README.md
SECURITY.md
```

Then inspect at minimum:

```text
src/clr/private_workspace_access.py
src/clr/private_workspace_pilot_app.py
src/clr/private_auth_benchmark.py
src/clr/private_decision_workspace.py
src/clr/private_pilot_rehearsal.py
src/clr/compound_local.py
src/clr/local_store.py
src/clr/public_boundary.py

scripts/manage_private_workspace_users.py
scripts/init_private_pilot_access.py
scripts/run_private_pilot_app.py
scripts/benchmark_private_pilot_auth.py

deploy/private_pilot/Caddyfile.example
deploy/private_pilot/clr-private-pilot.service.example

.gitignore
.dockerignore

tests/test_private_workspace_access.py
tests/test_private_workspace_pilot_app.py
tests/test_private_auth_benchmark.py
tests/test_private_decision_workspace.py
tests/test_private_pilot_rehearsal.py
tests/test_compound_local.py
tests/test_public_boundary.py
```

## Verdict vocabulary

Assign exactly one status to every target finding:

- **CLOSED** — the original failure path is no longer reproducible, and the implemented control has a meaningful regression test.
- **PARTIALLY CLOSED** — material risk was reduced, but a meaningful part of the same failure path remains.
- **STILL OPEN** — the original failure path remains reproducible or the claimed fix does not enforce what it says.
- **HOST-DEPENDENT** — repository-side work is complete enough to proceed, but closure requires evidence from the real deployed host.
- **NOT APPLICABLE** — only if the original finding no longer applies because the relevant code path has been deliberately removed. Explain why.

Do not use "looks fixed" or "probably closed".

## Target findings

Review every item in `TARGET_FINDINGS.md`.

The most important reproductions are:

### Audit crash recovery — NEW-01

Reproduce a failure after the SQLite audit transaction commits but before final anchor promotion.

Verify:
- the signed pending anchor remains;
- the DB contains the committed event;
- the next verify/write promotes the pending anchor only if it matches committed state;
- a pre-commit pending anchor is discarded;
- an ambiguous pending state fails closed;
- non-empty audit history cannot be silently re-anchored by deleting the anchor;
- exceptional re-anchor requires an active ADMIN, a reason, a cryptographically valid chain, and creates `AUDIT_ANCHOR_RESET`.

### Atomic privileged changes — NEW-02

Force audit-state failure during:
- create user;
- password reset;
- enable/disable;
- membership grant;
- membership revoke.

Verify the security mutation and audit event are one transaction and no privileged state change persists without its audit event.

Do not test only one mutation and generalise without inspecting the others.

### Cross-process audit serialization — NEW-03

Use real separate processes, not only threads.

Verify multiple writers can append without the old spurious stale-anchor failure and that the final HMAC chain + authenticated anchor verify.

### Audit HTTP failure semantics — NEW-06

Break audit state and exercise login/report/audit paths.

Verify an audit-state failure produces a controlled 503-class response and is not misreported as invalid credentials, report 404, or connection termination.

### Login CPU control — H-01 residual

Do not judge only the numeric default.

Verify:
- shipped default global ceiling is 20/60s per process;
- per-account and global ceilings are enforced before expensive authentication work;
- invalid/unknown usernames cannot bypass the global ceiling;
- the host benchmark uses the current password KDF parameters;
- its recommendation arithmetic uses measured median hash cost, vCPU count and target CPU-share budget;
- the launcher/deployment example can receive a host-calibrated value.

Classify the final result **HOST-DEPENDENT** if the repository implementation is sound but actual calibration still requires the real VPS. Do not call real-host CPU capacity closed from workstation measurements.

### Tenant-spelling limiter bypass — NEW-04

Reproduce the original case/whitespace tenant variants.

Verify they consume the same per-account bucket. Also test malformed tenant strings and confirm they do not create unlimited fresh buckets.

### Password-reset upper bound — NEW-05

Attempt a reset above `MAX_PASSWORD_CHARS`.

Verify it is rejected before hashing/state change and that the previous valid password remains usable.

### Custom-root Docker boundary — NEW-08

Do not rely only on substring presence.

Evaluate representative paths such as:

```text
pilot/auth/private.json
pilot/catalog/private.json
pilot/raw/era5/private.json
pilot/normalized/assets/private.json
pilot/indicators/asset/private.json
pilot/manifests/plans/private.json
pilot/outputs/reports/private.html
pilot/tmp/private.json
pilot/backups/recovery/private.json
```

Verify they are excluded under Docker ignore semantics. If Docker is unavailable, explicitly state that this portion is pattern-semantics verification rather than an executed Docker build.

### Boundary-layout drift — NEW-09

Verify `public_boundary.py` derives protected workspace paths from the canonical layout rather than duplicating a hand-maintained child list.

Add a synthetic future workspace directory in a temporary test or monkeypatch and determine whether the boundary checker would pick it up without a second manual edit.

### Compound shared-edge default — NEW-10

Verify `cross_asset_summary()` has no optimistic evidence default.

Omitting the evidence-availability argument must not silently produce valid zero shared-bottleneck metrics.

### All-null heat month — NEW-11

Create a full calendar month whose temperature values are all null.

Verify:
- >35°C count is null;
- >38°C count is null;
- monthly max is null;
- quality is non-OK;
- downstream annual compound output remains fail-closed.

### Query-log status preservation — NEW-13

Exercise a query-bearing request, preferably a 503 failure.

Verify:
- query parameters are removed from the application log;
- HTTP method/path/version remain useful;
- response status remains in the log;
- tenant/report identifiers from the query do not leak.

### .gitignore blank-rule trap — I-02

Run `git check-ignore --no-index -v` against custom-root private paths.

Verify the result is attributed to an explicit private-workspace rule, not an empty pattern.

### Indicator-run fanout — L-03

Submit more than the allowed run count over HTTP and call the governed adapter directly.

Verify:
- HTTP rejects it before report generation;
- direct adapter invocation also rejects it;
- the cap cannot be bypassed by skipping the HTTP layer.

## Regression sweep

After targeted reproductions, run:

```bash
python -m pytest -q
python scripts/check_public_boundary.py
```

Also inspect for regressions in these already-sound controls:

1. tenant isolation for reports, selectors and run IDs;
2. path traversal confinement;
3. session revocation after password/role/membership/user-state change;
4. loopback-only bind;
5. Secure + HttpOnly + SameSite cookie defaults;
6. no real/private data in tracked files;
7. explicit run/vintage selection;
8. source lineage and denominator preservation;
9. no arbitrary composite climate-risk score;
10. no automatic hazard -> damage/downtime/PD/LGD/ECL conversion.

Only report a regression if you can support it with code or execution.

## Host-dependent items

Do not misclassify these as repository failures merely because the host does not exist yet:

- real DNS and certificate chain;
- firewall/security-group exposure;
- OS patch state;
- actual service-account ownership/permissions;
- actual Caddy access-log permissions;
- real host PBKDF2 calibration;
- external/off-host append-only audit retention;
- off-host encrypted backup destination and restore drill;
- cloud IAM/secrets manager;
- actual reverse-proxy/network rate limiting.

Instead list them under **Host-side gates before outside pilot users**.

## New findings

You may report new findings, but this is not a fresh architecture audit.

A new finding must include:
- exact file/function/config;
- demonstrated or realistic failure path;
- precondition;
- confidentiality/integrity/availability impact;
- reachability in the documented pilot;
- concrete fix;
- regression test.

Do not create a finding for style, theoretical best practice, or a future multi-host architecture that is outside the documented small single-process pilot.

## DeepSeek challenge requirement

For each bundle sent to DeepSeek, ask it to:

1. identify the strongest reason the claimed remediation may be incomplete;
2. identify any tautological or self-asserted guard;
3. distinguish repository closure from host-dependent closure;
4. state what execution would falsify its own verdict.

Claude Code must then perform or inspect that falsification test where practical.

Record in the final report:
- DeepSeek's verdict;
- Claude's verified verdict;
- whether they disagreed;
- evidence resolving the disagreement.

## Required report

Save the complete final report as:

`reviews/security/2026-09-24-closure/CLOSURE_REAUDIT_REPORT.md`

Use the structure in `REPORT_TEMPLATE.md`.

Do not merely print the report to the terminal. Write the Markdown file.

The final report must include:
- exact reviewed SHA;
- dirty/clean working-tree state;
- test commands and results;
- one row per target finding;
- new findings, if any;
- controls re-verified as sound;
- host-side gates;
- final statement answering only this question:

> Does any **repository-side** Critical, High or Medium issue remain that should block provisioning the private pilot host?

Do not give a general certification that the system is "secure".
