# Post-Remediation Independent Security & Technical Audit

**Repository:** `SyedBasher/bangladesh-climate-risk-intelligence`
**Commit reviewed:** `17fdcb52c3060de205ddffba12187866df0c266c` — "Harden audit integrity and encrypted recovery" (`main`)
**Baseline:** `80f640c127ca287245d9edbe2da72fe89141d332` — the commit audited in the original independent review
**Remediation commits:** `eee71e8` (boundary + tenant isolation, PR #25) · `c7adb02` (analytical governance, PR #26) · `53bc765` (auth + SQLite robustness, PR #27) · `17fdcb5` (audit integrity + encrypted recovery, PR #28)
**Date:** 2026-09-24
**Review type:** Post-remediation re-audit. No production code was modified; nothing was merged.

---

## 1. Executive Summary

### Current commit reviewed

`17fdcb52c3060de205ddffba12187866df0c266c` on `main`, verified by `git fetch` and `git rev-parse origin/main` before any inspection. The working tree was clean apart from one untracked file from the previous audit. Local `main` was fast-forwarded to the remote SHA so that no analysis ran against a stale checkout.

### Scope

All four remediation PRs were reviewed as a single changeset (49 files, +3,283/−418) against the original 35-finding register (3 High, 12 Medium, 15 Low, 5 Informational). The re-audit covered: the public/private boundary; tenant isolation across every request path; analytical governance and denominator/null semantics; authentication and resource controls; SQLite lifecycle and contention; audit-chain integrity and the new head anchor; encrypted backup and recovery; privileged CLI operations; deployment configuration; and test quality, including a deliberate hunt for false-positive assertions.

### Overall change since the original audit

**Substantial and genuine.** Every High and Medium finding received a targeted, code-level remediation rather than a documentation change, and the three findings that most threatened the pilot's core promises — cross-tenant report confinement (M-01), the public/private boundary under a custom workspace root (M-05), and the compound-pipeline crash (H-03) — are **closed and independently verified by execution**, not merely by reading the diff. The test suite grew from 203 tests (2 failing on Windows) to **236 tests, all passing**, and the new tests are mostly behavioural rather than structural.

The two findings that are not fully closed were the two most ambitious: the audit head anchor (H-02) and the login resource-exhaustion bound (H-01). Both are meaningfully improved, and both carry a residual that the project's own documentation now describes with unusual precision and honesty — the anchor documentation explicitly states what the anchor does *not* prove, which is exactly the property a reviewer needs.

### Count of original findings now

| Status | Count | High | Medium | Low | Info |
| --- | --- | --- | --- | --- | --- |
| **Closed** | **14** | 1 | 11 | 2 | 1 |
| **Partially closed** | **7** | 2 | 2 | 3 | 0 |
| **Still open** | **14** | 0 | 0 | 10 | 4 |
| **Superseded** | 0 | 0 | 0 | 0 | 0 |
| **Acceptably deferred** | 0 *as findings* — see §15 for the residuals that are proportionate to defer | — | — | — | — |
| **Total** | **35** | 3 | 12 | 15 | 5 |

No original finding was silently dropped. Every one of the 35 is carried into §4 and §5 with a verdict and evidence.

### Count / severity of NEW findings

| Severity | Count | IDs |
| --- | --- | --- |
| Critical | 0 | — |
| High | 0 | — |
| Medium | 3 | NEW-01 (audit append/anchor split-brain on crash), NEW-02 (privileged mutations not atomic with their audit record), NEW-03 (audit anchor is not multi-process safe) |
| Low | 8 | NEW-04 … NEW-10, NEW-12 |
| Informational | 3 | NEW-11, NEW-13, NEW-14 |

**No Critical or High finding exists in either the original or the new set.** The new findings are all second-order consequences of the audit-hardening work itself, they fail closed, and none of them is remotely triggerable. Two of the three Mediums were independently identified by DeepSeek *and* by this reviewer; one (NEW-02) was found only by this reviewer.

### Headline judgement

The remediation did what it claimed. The remaining risk is concentrated in three places: the audit anchor's crash/repair behaviour, the calibration of the login rate limit against the real cost of PBKDF2 on a small host, and a set of hand-maintained guard lists (boundary checker, `.dockerignore`, `.gitignore`) that have already begun to drift from the layout they protect. None of these is a data-compromise risk. See §17 for the concrete readiness checklist and §18 for the ordered next actions.

---

## 2. Verification of Repository State

| Check | Command | Result |
| --- | --- | --- |
| Remote fetch | `git fetch --all --prune` | Fetched `80f640c..17fdcb5` on `main`, plus the four remediation branches |
| Remote `main` SHA | `git rev-parse origin/main` | `17fdcb52c3060de205ddffba12187866df0c266c` — **matches the expected SHA** |
| Local `main` fast-forward | `git merge --ff-only origin/main` | Advanced to `17fdcb5` |
| HEAD after checkout | `git rev-parse HEAD` | `17fdcb52c3060de205ddffba12187866df0c266c` |
| Working tree | `git status --porcelain` | One untracked file (`DEEPSEEK_FULL_TECHNICAL_SECURITY_AUDIT_2026-09-24.md`, the prior audit report). **No modified, staged or deleted tracked files.** |
| Remediation log | `git log --oneline -8` | `17fdcb5` · `53bc765` · `c7adb02` · `eee71e8` on top of `80f640c` — the four squash commits named in the review request |
| Changeset size | `git diff --stat 80f640c..17fdcb5` | 49 files, +3,283 / −418 |

**No discrepancy.** The four commits on top of the audited baseline are legitimate remediation changes: each touches only the areas described by its message, each is accompanied by tests, and no unrelated file was modified. `deploy/private_pilot/Caddyfile.example` was deliberately **not** changed (relevant to H-01, §6).

---

## 3. Threat Model and Intended Pilot Deployment

The threat model of the original audit is unchanged and remains the correct frame. It is restated here only where the remediation changed the picture.

### Intended deployment (the standard against which readiness is judged)

- ~2–5 named users; named-user private pilot only (`scripts/run_private_pilot_app.py`).
- Backend bound to `127.0.0.1:8766`; TLS terminated by a reverse proxy.
- Private workspace outside Git (documented target `/srv/clr/private_data`), Linux host, dedicated non-login service account, intended hostname `climate.mangroveintel.com`.
- **Not** a public multi-tenant SaaS product. MFA, SSO, hardware-backed keys, browser-based user administration, external session stores and enterprise log infrastructure remain proportionate deferrals.

### Actors

| Actor | Capability | Changed by the remediation? |
| --- | --- | --- |
| A1 Anonymous internet client | Reaches the TLS proxy only | Rate-limited and size-bounded in-app (H-01 residual remains) |
| A2–A4 Authenticated VIEWER / ANALYST / tenant ADMIN | One tenant | Unchanged; audit of *global* events still visible to every tenant ADMIN (L-09) |
| A5 Operator with filesystem access to the workspace | Full root write: catalog **and** `auth/` (secret + anchor) | **Now materially relevant to H-02**: the anchor sits inside the same trust domain as the key it is authenticated with |
| A6 Supply chain | Arbitrary code as `clrpilot` | Out of scope |
| A7 Outside reader of the public repo | Public tree only | Boundary strengthened (M-05/M-09) |

### Trust-boundary change introduced by PR #28

The audit anchor is a new artefact in the trust model. Its placement determines what it can prove:

- **Detects:** SQLite-only tail truncation, restoration of an older catalog snapshot, accidental row deletion, and any modification of the anchor without the audit HMAC key.
- **Does not detect:** an actor who can write `auth/` as well as the database — i.e. actor A5. Such an actor can read `audit_chain_secret.bin`, delete or rewrite the anchor, and re-MAC a consistent anchor over a truncated table.
- **Is not** immutable logging, and **is not** truncation-evidence against the operator.

This is exactly the property the project now documents (`docs/HOSTED_PRIVATE_PILOT_SECURITY.md`, "Audit chain and head anchor": *"It detects SQLite-only tail truncation and accidental/restricted DB tampering; it does not make the log immutable against an operator or attacker who can rewrite the database, anchor and audit key together."*). The implementation matches the documented claim, and the claim is honest. That honesty is why H-02 is assessed as *partially* closed rather than closed: the control works against the attacker it names, and the documentation says so.

---

## 4. Original Finding Remediation Matrix

Every High and Medium original finding. Verdicts are from the current code plus the reproductions in §14, not from PR descriptions.

### H-01 — Unauthenticated login resource exhaustion (CPU amplification + permanent audit growth)

| Field | Assessment |
| --- | --- |
| **Original severity** | High (availability) |
| **Original issue** | No rate limit anywhere in the stack; every attempt with a valid-format username burned ~140 ms PBKDF2; every attempt unconditionally appended a permanent audit row carrying up to ~60 KB of attacker text. Measured: one unauthenticated request wrote a **60,015-byte** audit row. |
| **Current status** | **PARTIALLY CLOSED** |
| **Current evidence** | `src/clr/private_workspace_pilot_app.py`: `_LoginRateLimiter` (per-key 8/300 s, global 120/60 s, 2048-key LRU) consulted before `authenticate_user`; `MAX_LOGIN_FORM_BYTES = 4*1024`; username/tenant capped at 128 chars, password at 1024; oversize returns 401 **before** any audit write; `_login_audit_detail` records only `username_sha256`. `src/clr/private_workspace_access.py`: `_bounded_audit_detail` with `MAX_AUDIT_DETAIL_BYTES = 4096`, `MAX_AUDIT_TEXT_CHARS = 256`, `MAX_AUDIT_DETAIL_ITEMS = 20`. |
| **Regression test / reproduction** | Measured on the current code: 40 attempts with **distinct usernames** (defeating the per-key bucket) at the shipped limits → all `401`, **no `429`**, median **656 ms** per attempt; audit rows written: 40, max `detail_json` = **86 bytes** (was 60,015). At the shipped global cap of 120 attempts/60 s this is **≈79 CPU-seconds per minute ≈ 66 % of a 2-vCPU pilot host's total capacity** for as long as the attacker sustains it. Repo tests: `test_failed_login_rate_limit_caps_pbkdf_and_audit_rows`, `test_oversized_login_fields_are_rejected_without_audit_growth`. |
| **Residual risk** | (a) The **disk** half is closed (per-row bound + hash-only username). (b) The **CPU** half is bounded but the bound is high: the global ceiling is set in *attempts*, not in *CPU seconds*, and one attempt costs ~0.65 s on this host. 120/min therefore permits ~2/3 of a 2-vCPU host's CPU. (c) `verify_audit_chain` still `fetchall()`s the whole table, so a grown audit table makes the ADMIN `/audit` page allocate proportionally (estimate in §12). (d) No audit retention policy. (e) `deploy/private_pilot/Caddyfile.example` was **not** changed — there is still no proxy-level per-IP limit. (f) A legitimate user who mistypes 8 times is locked out of their own account for 5 minutes. |
| **Pilot relevance** | **Blocker until the cap is calibrated** (see §18). Everything else about this finding is either closed or a deferrable hardening item. |

### H-02 — Audit chain cannot detect tail truncation

| Field | Assessment |
| --- | --- |
| **Original severity** | High (audit integrity) |
| **Original issue** | `verify_audit_chain` walked `prev_hash` links only. Verified: deleting the newest events left `valid: true`. |
| **Current status** | **PARTIALLY CLOSED** |
| **Current evidence** | `auth/audit_head_anchor.json` records `{version, event_count, head_hash, updated_at}` MAC'd with the audit HMAC key (`_anchor_mac`). `verify_audit_chain` now requires the anchor by default and returns `EVENT_COUNT_MISMATCH` / `HEAD_HASH_MISMATCH` / `AUDIT_ANCHOR_MAC_MISMATCH`. `record_audit_event` re-reads the anchor inside `BEGIN IMMEDIATE` and refuses to append if the DB count/head disagree. |
| **Regression test / reproduction** | **Reproduced:** 4 events → delete the newest → `valid=False, reason=EVENT_COUNT_MISMATCH, checked_events=3, anchor_event_count=4`. Anchor MAC tamper (bump `event_count` by 1 without the key) → `AUDIT_ANCHOR_MAC_MISMATCH`. Content rewrite and mid-chain deletion remain detected. Repo tests: `test_audit_tail_truncation_is_detected_by_external_anchor`, `test_audit_anchor_tampering_is_detected`. |
| **Residual risk** | (a) The anchor is **not external**: it lives in `auth/`, the same directory as the secret that authenticates it, so actor A5 can rewrite both (see §3 and §9). (b) **Deleting the anchor and re-running the init script silently legitimises the DB state** — reproduced: after deleting the only event, removing the anchor and re-running `initialize_audit_anchor` produced `bootstrapped=True, event_count=0` and `verify_audit_chain → valid=True`. The *supported* repair step therefore erases the evidence of truncation. (c) No `DELETE`/`UPDATE` trigger on `workspace_audit_event`. (d) No documented repair procedure for a mismatched anchor (see NEW-01). |
| **Pilot relevance** | Not a blocker provided the limitation is understood and the repair procedure is written down. The honest documentation materially reduces the risk; the residual is precision, not deception. |

### H-03 — Compound/cross-asset pipeline crashes on a NaN denominator

| Field | Assessment |
| --- | --- |
| **Original severity** | High (functional; fails closed) |
| **Original issue** | `cross_asset_summary` mixed `int` and `None` in one `denominator` column → pandas `float64` → `NaN`; the guard `if denominator is not None` then called `int(nan)` → `ValueError` on every real compound run. |
| **Current status** | **CLOSED** |
| **Current evidence** | `src/clr/compound_local.py:805-813`: `denominator_value = None if denominator is None or pd.isna(denominator) else int(denominator)`, plus a new negative-value guard. The same NaN-aware helper (`_optional_nonnegative_int`) was adopted in `decision_reports.py` and `product_output.py`. |
| **Regression test / reproduction** | **Reproduced with the original fixture shape:** the guard now passes **9/9** rows (previously 3 raised). The repo's own `test_cross_asset_metric_nan_denominator_is_omitted_not_converted` performs a real `_insert_cross_metric(..., denominator=float("nan"))` against a workspace and asserts the manifest has no `denominator` key; `test_cross_asset_metric_schema_and_source_lineage` exercises the full insert into `cross_asset_metric`. Both pass. |
| **Residual risk** | None material. The three `SHARED_BOTTLENECK` rows still emit `denominator: None`, which is intentional (they are counts, not shares). |
| **Pilot relevance** | Closed. Compound/cross-asset evidence is now reachable end-to-end. |

### M-01 — Dot-segment tenant keys defeat report-directory confinement

| Field | Assessment |
| --- | --- |
| **Original severity** | Medium (cross-tenant read) |
| **Original issue** | `_SAFE_PART` allowed `.`, so `_require_safe_tenant_key('..')` was accepted; `base = root/"outputs"/"reports"/tenant` then escaped the tenant directory. Verified: a session on tenant `..` listed **every** tenant's reports and read another tenant's HTML. |
| **Current status** | **CLOSED** |
| **Current evidence** | Single canonicaliser `local_store.canonical_tenant_key` (rejects leading/trailing dots, leading/trailing whitespace, out-of-charset keys), used by `_require_safe_tenant_key` (`private_workspace_app.py:28`), `_validate_tenant` (`private_workspace_access.py:141`), `import_asset_rows`, `accepted_assets`, `coarse_climate_assets` and `build_private_decision_workspace`. Both report sinks now use `tenant_report_dir`, which asserts `path.parent == outputs/reports`. `write_private_decision_workspace` adds a second `relative_to` check on the final output directory. |
| **Regression test / reproduction** | **Reproduced directly:** `"."`, `".."`, `"..."`, `"a."`, `"...a"`, `" TENANT_A"`, `"TENANT_A "` are all rejected; normal keys accepted. **Reproduced over HTTP:** tenant A requesting tenant B's report path → **404** (no leak); tenant B → own report **200**; tenant A's dashboard does not contain tenant B's subject; `../../etc/passwd` → 404; `outputs/reports/../../auth/audit_chain_secret.bin` → 404. Repo tests: `test_canonical_tenant_key_rejects_path_segments_and_keeps_normal_dots`, `test_adapter_rejects_successful_indicator_run_from_another_tenant`, `test_adapter_rejects_compound_run_from_another_tenant`. |
| **Residual risk** | Case-only tenant variants remain distinct keys and resolve to the same directory on a case-insensitive filesystem (L-01, Windows-hosted only). |
| **Pilot relevance** | Closed for the documented Linux host. |

### M-02 — Login username-enumeration oracle (timing)

| Field | Assessment |
| --- | --- |
| **Original severity** | Medium |
| **Original issue** | PBKDF2 ran only when a user row matched: `48 ms` unknown vs `185 ms` known, identical 401 body — a ~4× enumeration oracle. |
| **Current status** | **CLOSED** |
| **Current evidence** | `authenticate_user` reads `SELECT COALESCE(MAX(password_iterations), 310000)` and calls `_dummy_password_work` for unknown, inactive, invalid-format and over-long inputs, and tops up with `max_iterations - iterations` on the real path, so the total KDF work is equalised to the installation's maximum. `_dummy_password_work` executes outside the DB `with` block, so no connection is held during the KDF. |
| **Regression test / reproduction** | **Measured on a fresh server, 310 000 iterations: unknown username 672 ms, existing username 666 ms (median of 6, ~0.9 % apart)** — versus 48 ms vs 185 ms before. The mechanism is *deterministically* asserted by `tests/test_private_workspace_access.py::test_unknown_and_known_accounts_both_perform_password_hash_work`, which monkeypatches `_password_digest` and asserts `sum(iterations) == 100_000` for the missing-user, existing-user and invalid-format paths alike. |
| **Residual risk** | This is **not** constant-time and must not be described as such. Residual differences remain in branch structure, the extra DB query and the `compare_digest` target, all sub-millisecond against a 650 ms KDF. Note that equalisation *increases* the cost of an unknown-account attempt (previously free) — which is why the rate-limit calibration in H-01 matters. |
| **Pilot relevance** | Closed. |

### M-03 — SQLite write contention produces an unhandled exception and a dropped connection

| Field | Assessment |
| --- | --- |
| **Original severity** | Medium |
| **Original issue** | `verify_session` wrote `last_seen_at` on **every** authenticated request, making every request a writer. Under a held write lock the handler raised `sqlite3.OperationalError` and the client received **no HTTP response** after a 5.7 s stall. |
| **Current status** | **CLOSED** |
| **Current evidence** | `_sqlite_connection` sets `timeout` **and** `PRAGMA busy_timeout` (default 5000 ms). `verify_session` performs the session read only, then touches `last_seen_at` at most once per `SESSION_TOUCH_INTERVAL_MINUTES = 5`, on a separate connection with `busy_timeout_ms=50`, swallowing only `locked`/`busy`. `do_GET`/`do_POST` wrappers map a busy `OperationalError` to `_service_unavailable()` → **503 + `Retry-After: 1`**. |
| **Regression test / reproduction** | **Reproduced with a real lock, not a mock:** with a second connection holding `BEGIN IMMEDIATE`, `GET /report` returned **503 with `Retry-After: 1` in 5.5 s** (the busy timeout), instead of `RemoteDisconnected`. Also verified that a plain authenticated `GET /` under the same lock returns **200 in 0.0 s** — session verification no longer writes, which is the substantive fix. Repo test `test_sqlite_busy_returns_503_instead_of_dropping_request` (mocks `verify_session`; the real-lock path is verified here). |
| **Residual risk** | The wrapper catches only `sqlite3.OperationalError` with a locked/busy message; other SQLite error classes (`DatabaseError`, `IntegrityError`, `disk I/O error`) still escape and drop the connection. This is narrower than the original recommendation ("catch `sqlite3.Error` and, generally, `Exception`") and remains an availability edge case, not a correctness one. |
| **Pilot relevance** | Closed for the finding. |

### M-04 — SQLite connections were never closed

| Field | Assessment |
| --- | --- |
| **Original severity** | Medium |
| **Original issue** | `with sqlite3.connect(...) as conn:` commits but does **not** close; connections accumulated (20/20 live without GC; 24 live after 30 HTTP requests) and the restore rehearsal **failed on Windows** (`PermissionError` removing the temp directory) while passing on Linux for the wrong reason. |
| **Current status** | **CLOSED** |
| **Current evidence** | `local_store._ClosingConnection(sqlite3.Connection).__exit__` closes in a `finally`; `_sqlite_connection` is the single factory, used by `connect_catalog` and `initialize_workspace`. |
| **Regression test / reproduction** | **Reproduced:** after the `with` block the connection raises `ProgrammingError` on use (previously it stayed usable). **Verified no leak remains:** `grep -rn "sqlite3\.connect" src/clr/ scripts/` returns exactly one site — inside `_sqlite_connection`. The full suite now reports **236 passed, 0 failed**; the two tests that failed on Windows in the original audit (`test_backup_restore_rehearsal_is_non_destructive_and_verifies_audit`, `test_full_rehearsal_writes_private_qa_manifest`) pass. Repo tests: `test_connect_catalog_context_manager_closes_handle`, `test_connect_catalog_sets_busy_timeout`. |
| **Residual risk** | Behaviour change for callers that relied on post-block re-use. I checked the one in-tree case (`cur.lastrowid` after the block in `record_audit_event`) empirically: it still returns the correct id (`1`), because CPython stores `lastrowid` on the cursor. No other post-block use was found, and the suite is green. |
| **Pilot relevance** | Closed. |

### M-05 — `auth/`, `manifests/`, `normalized/`, `indicators/`, `tmp/` and the marker were neither gitignored nor covered

| Field | Assessment |
| --- | --- |
| **Original severity** | Medium (public/private boundary) |
| **Original issue** | The workspace layout has 9 top-level directories; `.gitignore` and the checker recognised 3. `manifests/plans/jrc_flood/asset_tile_plan.json` is written with full-precision `latitude`/`longitude` and the customer's `external_id`, and was committable under any non-standard workspace root. |
| **Current status** | **CLOSED** |
| **Current evidence** | **`initialize_workspace` now writes `<root>/.gitignore` containing `*`** (`local_store.py:134-153`), so any initialized workspace is self-protecting regardless of its directory name; it also refuses to initialize at a Git repository root. Repo `.gitignore` adds `**/.private-data-root`, `**/workspace_auth.json`, `**/audit_chain_secret.bin`, `**/audit_head_anchor.json`, `**/session_secret.bin`, `**/outputs/reports/`, `**/outputs/qa/`, `**/backups/catalog/`, `**/backups/recovery/`, `**/manifests/source_vintages/`, `**/manifests/plans/`, `**/normalized/`, `**/indicators/`, `**/tmp/clr-restore-rehearsal-*/`. The checker adds `FORBIDDEN_PATH_FRAGMENTS` matched at any depth and the workspace secret basenames. |
| **Regression test / reproduction** | **Reproduced in a real git repository:** `git init` at `tmp/fakerepo`, `initialize_workspace(fakerepo/"pilot_ws")`, then created `manifests/plans/jrc_flood/asset_tile_plan.json` (containing coordinates), `auth/audit_chain_secret.bin`, `auth/audit_head_anchor.json`, `.private-data-root`, `catalog/x.sqlite`, `outputs/reports/T/x.html` → **`git status --porcelain` returned empty**: every private file is ignored. `initialize_workspace(repo_root)` → refused with *"Refusing to initialize a private workspace at a Git repository root"*. Repo tests: `test_initialized_workspace_is_self_protecting_for_git`, `test_custom_workspace_is_ignored_inside_an_unrelated_git_repo`, `test_initialize_workspace_refuses_repository_root`. |
| **Residual risk** | The two guard **lists** are still hand-maintained and have already drifted (see M-09 residual and NEW-09). `git add -f` still bypasses everything (as it always did). The self-protecting root `.gitignore` is the load-bearing control and it works. |
| **Pilot relevance** | Closed. This was the only irreversible failure mode in the original audit; it is now fixed at the level where it cannot regress by omission. |

### M-06 — Backup/recovery was incomplete and its checks were tautological

| Field | Assessment |
| --- | --- |
| **Original severity** | Medium |
| **Original issue** | Catalog-only backup, no `auth/`; `backup_hash_matches_restore` compared the backup with its own copy; the rehearsal copied the live audit key in so the chain check could pass; no encryption; restore-without-key was never exercised. |
| **Current status** | **CLOSED** |
| **Current evidence** | `create_encrypted_recovery_bundle` produces a `.clrbackup` bundle = `AES-256-GCM(plaintext tar{catalog, auth/audit_chain_secret.bin, auth/audit_head_anchor.json, recovery_manifest.json})`, key = PBKDF2-HMAC-SHA256 (600 000 iterations, 16-byte random salt, 12-byte random nonce), header authenticated as AAD. `_read_encrypted_recovery_bundle` enforces an **exact allowlist** of member names, rejects non-file members, and reads via `extractfile` into memory — **no `extractall`, so no tar path traversal**. `restore_encrypted_recovery_bundle` requires an empty/non-existent target and verifies catalog SHA-256 + logical state fingerprint + secret SHA + anchor SHA + full chain + event count + head hash. `create_catalog_backup` replaces the tautological check with a **logical state fingerprint** (per-table row counts + audit count/max-id/head + `user_version`) compared across source-before, source-after and backup. `rehearse_backup_restore` now includes the negative control *"catalog-only restore fails without the audit key"*. |
| **Regression test / reproduction** | **Reproduced end-to-end:** bundle created (9,830 bytes for the fixture), `CLRRECOVERY1\n` magic present, **the passphrase does not appear in the bundle**; wrong passphrase → `Recovery bundle authentication failed`; **single-bit ciphertext flip → rejected**; correct restore → `status: PASS` with all 7 checks true, restoring the catalog, the 32-byte audit secret and the anchor; non-empty target → `Recovery target must be empty`. Catalog-only restore → `valid=False, reason=AUDIT_SECRET_MISSING`, and **verification did not mint a replacement key as a side effect** (`auth/audit_chain_secret.bin` absent afterwards). The snapshot fingerprint is meaningful, not tautological: deleting the audit rows in a copy changes `state_sha256`. Repo tests: `test_encrypted_recovery_bundle_round_trip_restores_key_anchor_and_catalog`, `test_transient_catalog_snapshot_has_meaningful_state_verification`, `test_backup_restore_rehearsal_has_negative_and_positive_controls`. |
| **Residual risk** | (a) `deployment_examples_valid` is still folded into the headline PASS and is still substring matching (I-05). (b) The rehearsal generates and consumes the passphrase inside one process, so it proves the code path, not independent key custody. (c) The transient plaintext catalog snapshot is written under `root/tmp/` during bundle construction (NEW-07 note; same trust domain). (d) An *older* bundle restores cleanly and rolls the whole workspace back — inherent to backups, but the manifest's audit head is only checked against the restored catalog, not against the live one. |
| **Pilot relevance** | Closed. The documented recovery path now actually recovers, and it now fails closed in the case that previously could not be tested. |

### M-07 — Portfolio share metrics lacked an explicit denominator

| Field | Assessment |
| --- | --- |
| **Original severity** | Medium (analytical governance) |
| **Original issue** | Portfolio shares carried `denominator_count` but `_validate_portfolio_metrics` did not require any denominator, and the client-facing HTML table had no denominator column while the section note claimed denominators were "shown explicitly". |
| **Current status** | **PARTIALLY CLOSED** |
| **Current evidence** | `decision_reports._validate_portfolio_metrics` now raises *"Portfolio share metrics require denominator_count"* when `unit == "share"` and the value is missing; `product_output.portfolio_intelligence_report` enforces the same rule at construction; `decision_report_html` adds `("denominator_count", "Denominator")` to the portfolio table, so the rendered report now shows it. `_optional_nonnegative_int` makes a `NaN` denominator behave as missing rather than raising `int(nan)`. The synthetic demo fixture was updated with `denominator_count: 4` so the demo still validates. |
| **Regression test / reproduction** | Repo tests `test_decision_reports.py` (portfolio share requires `denominator_count`) and `test_product_output.py` additions pass; `tests/test_private_decision_workspace.py:325-327` still asserts `share["denominator_count"] == 2`. The HTML column is verified by reading `decision_report_html.py:199` — and, per §14, that single line is a rendering change with no test asserting the rendered cell. |
| **Residual risk** | (a) The two metric families still use **different key names** (`denominator` for compound, `denominator_count` for portfolio), so the original recommendation "one validator covers all share metrics" was not achieved and the new rules are unit-string-keyed (`unit == "share"`; a future `unit="percentage"` share would not be caught). (b) No `denominator_basis` field explaining what the denominator counts. (c) The strong fail-closed variant (`n_valid == 0` → raise rather than flag `NO_VALID_HAZARD_LINKS`) was not adopted. |
| **Pilot relevance** | Not a blocker. The governance requirement — a *rendered* explicit denominator for every portfolio share — is satisfied; the residuals are schema hygiene. |

### M-08 — Legacy shared-password shell was a parallel authorization path

| Field | Assessment |
| --- | --- |
| **Original severity** | Medium |
| **Original issue** | `serve_private_workspace` could be started against the pilot's data plane with no per-user identity, no roles, no audit, and no per-tenant membership — one shared password opened every tenant. |
| **Current status** | **CLOSED** |
| **Current evidence** | `serve_private_workspace(..., allow_legacy_shared_password: bool = False)` raises `RuntimeError` unless the caller opts in; the banner prints *"LEGACY LOCAL-ONLY shared-password workspace"*. `scripts/run_private_workspace_app.py` requires `--allow-legacy-shared-password`. `Makefile.local` requires `ALLOW_LEGACY=1`. Docs: `docs/PRIVATE_WORKSPACE_APP.md:3` carries a legacy banner ("disabled by default and must not be used for the hosted pilot"), `docs/HOSTED_PRIVATE_PILOT_SECURITY.md:274-278` states it "must **never** be co-hosted with, proxied beside, or substituted for the named-user private pilot", and `deploy/private_pilot/README.md:28` says *"Do **not** run or proxy `scripts/run_private_workspace_app.py` on the host."* |
| **Regression test / reproduction** | **Reproduced:** calling `serve_private_workspace(root, host="127.0.0.1", port=8799)` without the flag raises `RuntimeError: Legacy shared-password workspace is disabled by default…`. Repo test `test_legacy_shared_password_server_requires_explicit_local_opt_in`. |
| **Residual risk** | One flag re-enables the whole shared-password surface, and there is no host-level interlock (e.g. refuse when `CLR_PRIVATE_DATA` points at the pilot workspace). The original regression-test suggestion — assert that a *legacy* session token is rejected by the *pilot* handler — was **not** added. Structurally the two mechanisms cannot interoperate (different cookie names, different token formats, and the pilot resolves sessions by DB hash), so this is a missing guard rather than a live weakness. |
| **Pilot relevance** | Closed. |

### M-09 — Boundary checker was a name predicate with narrower lists than `.gitignore`

| Field | Assessment |
| --- | --- |
| **Original severity** | Medium |
| **Original issue** | No content inspection; suffix list missed `.sqlite-wal`/`-shm`; basenames exact-matched 4 names; prefix matching was root-anchored; no `--recurse-submodules`; no pre-commit gate. |
| **Current status** | **PARTIALLY CLOSED** |
| **Current evidence** | `FORBIDDEN_SUFFIXES` adds `.db-wal`, `.db-shm`, `.sqlite-wal`, `.sqlite-shm`, `.sqlite3-wal`, `.sqlite3-shm`, `.clrbackup`. `FORBIDDEN_PATH_FRAGMENTS` matches generated-artefact paths **at any depth** (`/outputs/reports/`, `/outputs/qa/`, `/backups/catalog/`, `/backups/recovery/`, `/manifests/source_vintages/`, `/manifests/plans/`, each `normalized/` and `indicators/` child, `/tmp/clr-restore-rehearsal-`), which fixes the root-anchoring weakness that made the original probes slip through. `FORBIDDEN_BASENAMES` adds the workspace secrets, `workspace.json` and `.private-data-root`. A negative test (`test_boundary_guard_does_not_flag_public_methodology_names`) guards against over-blocking. |
| **Regression test / reproduction** | The extended list is verified by the repo's `test_boundary_guard_catches_forced_private_files`, which now feeds `pilot/manifests/…`, `pilot/outputs/reports/…`, `pilot/backups/catalog/…sqlite-wal` and `pilot/tmp/clr-restore-rehearsal-…/auth/audit_chain_secret.bin` and asserts all are flagged. Verified by reading that the fragment match is applied to `"/" + lower.lstrip("/")`. |
| **Residual risk** | (a) **No content inspection** — the single most likely real-world accident (real rows pasted into a permitted `*.csv`/`*.json`/`*.md`) remains undetectable. (b) `tracked_files()` still runs plain `git ls-files` (no `--recurse-submodules`). (c) No pre-commit/pre-push hook (no `.githooks/`, no `.pre-commit-config.yaml` — verified). (d) Basenames are still exact-match, so the original probes (`credentials.yml`, `.env.local`, `id_rsa`, `token.json`, `service-account.json`) are still missed. (e) The empty-line trap at `.gitignore:66` still makes `git check-ignore --no-index <dir>/` return a false "ignored" (verified: `auth/` → exit 0; `auth/x.json` → exit 1). (f) The directory list is an enumeration that has already drifted from `.gitignore`'s globs (NEW-09). |
| **Pilot relevance** | Not a blocker, because the workspace-level `*` `.gitignore` (M-05) is the control that actually prevents accidental commits. The checker is the second line of defence and remains materially weaker than it should be. |

### M-10 — Missing temperature evidence was counted as "not a hot day" with `quality_flag = "OK"`

| Field | Assessment |
| --- | --- |
| **Original severity** | Medium |
| **Original issue** | `(g["temp_c"] > 35.0).sum()` counted `NaN` as not-hot, and the quality flag tested only row *presence* (`unique_days == expected`), so an understated count shipped as `OK`. |
| **Current status** | **CLOSED** |
| **Current evidence** | `temp = pd.to_numeric(g["temp_c"], errors="coerce")`; `valid_days = g.loc[temp.notna(),"date"].dt.date.nunique()`; counts use `g.loc[temp.gt(35.0),"date"].dt.date.nunique()`; `monthly_max_tmax_c` is `None` when no valid temperatures exist; `heat_quality_flag = "OK" if valid_days == expected else "INCOMPLETE_HEAT_MONTH"`. Crucially the flag now propagates: `heat_drought_annual` sets `value=None` when the month quality is not `OK`, so the compound metric nulls out rather than publishing an understated number. |
| **Regression test / reproduction** | `tests/test_compound_local.py::test_missing_temperature_value_makes_month_incomplete` sets one of 31 days to `NaN` and asserts `heat_day_count == 30`, `expected_day_count == 31`, `heat_quality_flag == "INCOMPLETE_HEAT_MONTH"`, and — the decisive assertion — that the annual compound metric becomes `None` with `INCOMPLETE_YEAR_INPUT` for every row. The count change from `.sum()` to distinct-date `nunique()` also removes double-counting when a frame has duplicate rows per date. |
| **Residual risk** | (a) `heat_day_count` now means "days with a valid temperature" rather than "rows in the frame" — a semantics change in a *published* asset indicator; it should be noted for consumers. (b) The recommended `heat_valid_day_count` transparency field was not added, so a reader of the monthly indicator still cannot see the count's denominator directly (the quality flag is the signal). (c) For a fully-`NaN` month the two count fields still publish `0` (flagged `INCOMPLETE_HEAT_MONTH`) — see NEW-11. |
| **Pilot relevance** | Closed for the governance defect; residuals are transparency items. |

### M-11 — Absent shared-bottleneck input was published as three confident zeros flagged `OK`

| Field | Assessment |
| --- | --- |
| **Original severity** | Medium |
| **Original issue** | `if shared_edges.empty: shared_edge_count = 0` then three rows emitted with `quality_flag="OK"`, so "no shared exposed edges found" was indistinguishable from "no route-edge input at all". |
| **Current status** | **CLOSED** |
| **Current evidence** | A new keyword parameter `shared_edge_evidence_available` (default `True`) selects between `shared_quality="OK"` and `"NO_ROUTE_EDGE_EVIDENCE"`; when evidence is unavailable the three values become `None`. The production caller passes it correctly: `scripts/run_compound_cross_asset_local.py` line 130, `shared_edge_evidence_available=not route_edges.empty`. |
| **Regression test / reproduction** | **Reproduced both branches:** with `shared_edge_evidence_available=False` → `value=NaN`, `quality_flag=NO_ROUTE_EDGE_EVIDENCE`; with evidence available and an empty shared-edge frame → `value=0.0`, `quality_flag=OK` (a genuine, defensible zero). Repo test `test_shared_bottleneck_distinguishes_valid_zero_from_missing_edge_evidence`. |
| **Residual risk** | The flag **defaults to `True`**, i.e. to the optimistic branch: a future caller that omits the argument regresses to the original behaviour (three zeros at `OK`). The guard also cannot verify itself — it trusts a caller-supplied assertion rather than cross-checking `shared_edges`/`route_edges` (NEW-10). |
| **Pilot relevance** | Closed for the shipped path. |

### M-12 — Heat source lineage was silently dropped on any read failure

| Field | Assessment |
| --- | --- |
| **Original severity** | Medium |
| **Original issue** | A bare `except Exception: heat_sources = set()` swallowed any ERA5 lookup/read failure, and the metric was still written with its quality flag unchanged, so a metric with no verifiable lineage was indistinguishable from a fully lineaged one. |
| **Current status** | **CLOSED** |
| **Current evidence** | The `try/except` is removed entirely: `latest_parquet` / `pd.read_parquet` failures now propagate, and when the summary contains any `HEAT_DROUGHT` row the code raises `"Heat lineage unavailable for tenant …"` for empty heat **or** drought source sets. The gate is conditional on heat metrics existing, which is correct (no heat rows means nothing to lineage). |
| **Regression test / reproduction** | Repo test `test_heat_lineage_read_failure_propagates` monkeypatches `clr.compound_local.latest_parquet` to raise `OSError` and asserts the error propagates out of `insert_cross_asset_summary` — a genuine behavioural test of the removed swallow. |
| **Residual risk** | `.dropna()` on `source_artifact_id` still discards rows lacking an artefact id without a counter, so a partial-lineage frame can still lose rows silently (the original recommendation (b) was not implemented). |
| **Pilot relevance** | Closed. |

---

## 5. Low / Informational Finding Status

All 15 Low and 5 Informational findings, with verdicts. Evidence is abbreviated; the full reasoning for the ones that changed follows the table.

| ID | Original issue (one line) | Status | Evidence / residual |
| --- | --- | --- | --- |
| **L-01** | Report-directory confinement defeated by case-insensitive filesystem | **STILL OPEN** | **Reproduced on Windows:** `tenant_report_dir` accepts `TENANT_A`, `tenant_a`, `Tenant_A` as distinct tenants, and a file written under `TENANT_A` is readable via `tenant_a`. Nothing in the remediation case-folds tenant keys; `canonical_tenant_key` preserves case by design. Not reachable on the documented Linux host. |
| **L-02** | Audit `detail` redaction was top-level, exact-key, case-sensitive | **CLOSED** | `_sanitize_audit_value` is recursive (depth ≤ 3), lower-cases keys and substring-matches `password`, `token`, `secret`, `credential`, `api_key`, `apikey`, at every dict level; `_bounded_audit_detail` caps the encoded payload at 4096 bytes. Verified by the repo test asserting `"must-not-persist"` is absent and the row ≤ 4096 bytes. Residual: a secret embedded in a *value* (`{"note": "pw=…"}`) is truncated, not redacted; the denylist is substring-based, so a key like `passwords_disabled` is silently dropped. |
| **L-03** | No cap on the number of `indicator_run` values accepted by `/generate` | **STILL OPEN** | `grep` confirms no limit: `private_decision_workspace._require_runs` only checks for duplicates (`len(set(ids)) != len(ids)`). A 64 KiB form still yields thousands of runs → one query per run. Authenticated-only, so a resource-hygiene item. |
| **L-04** | `/login` had no CSRF token (login CSRF) | **PARTIALLY CLOSED** | `_login_origin_allowed` rejects a foreign `Origin` with 403 before authentication (verified by `test_cross_origin_browser_login_is_rejected_before_authentication`, which also asserts no audit row is written) and accepts same-origin (`test_same_origin_browser_login_is_accepted`). Residual: an absent `Origin` is accepted (`if not origin: return True`) and there is no `Referer` fallback and no pre-auth CSRF token, so the guard is a browser heuristic rather than a token. `SameSite=Strict` remains the primary control. |
| **L-05** | CSP uses `'unsafe-inline'` | **STILL OPEN** | `script-src 'unsafe-inline'` unchanged in both apps (verified by `grep`). Escaping in the report renderer remains the real defence; `default-src 'none'` still blocks `connect-src`/external images, so a hypothetical injection could not exfiltrate. |
| **L-06** | Contract JSON schemas never validated | **STILL OPEN** | No `jsonschema` import anywhere in `src/`, `scripts/` or `tests/`; no test references `contracts/`. `contracts/decision_workspace_report.schema.json` grew by ~420 lines but nothing enforces it. |
| **L-07** | No idle timeout; `last_seen_at` recorded, unused; no `__Host-` prefix | **PARTIALLY CLOSED** | `last_seen_at` writes are now throttled to once per 5 minutes and made best-effort. Expiry is still absolute-only (`if now >= expires_at`), so an idle session survives its full TTL, and the cookie is still `clr_pilot_session` (no `__Host-` prefix) — verified by `grep`. |
| **L-08** | Privileged CLI operations recorded a NULL actor | **CLOSED** | `_actor_user_id` requires an active ADMIN after bootstrap (`--actor-username`, `raise SystemExit("CLI actor must be an active ADMIN.")`), and every mutating subcommand passes `actor_user_id` through. Residuals: the first admin and the first `grant` are still recorded with a NULL actor (deliberate bootstrap), there is no `client_label` fallback identifying the OS user/host, the actor's admin membership is not scoped to the target's tenant (a global-admin model), and the actor is *named* rather than authenticated (anyone with shell access can attribute an action to any admin — they could equally edit the DB directly). Repo test: `test_cli_operator_identity_becomes_mandatory_after_admin_bootstrap`. |
| **L-09** | Global (`tenant_key IS NULL`) audit events visible to every tenant's ADMIN | **STILL OPEN** | The `/audit` query is unchanged: `WHERE tenant_key=? OR tenant_key IS NULL`. The new `_audit_tenant_or_none` returns `None` for *any* invalid tenant, so a failed login with a malformed tenant now writes a global event — i.e. the fix **increases** the volume of cross-tenant-visible events. Impact stays low: `render_audit` selects no `detail_json`, so only event IDs, action names, timestamps, target types and target IDs (user UUIDs) cross the boundary. |
| **L-10** | Docker build context could absorb private data | **PARTIALLY CLOSED** | `.dockerignore` added (verbatim: `private_data/**`, `local_data/**`, `data/**`, `raw/**`, `processed/**`, `private/**`, `customer_data/**`, `source_snapshots/**`, `outputs/**`, `backups/**`, `artifacts/**`, `cache/**`, the workspace secret basenames, `**/*.sqlite(-wal|-shm)`, `**/*.db(-wal|-shm)`, `**/*.parquet`, `**/*.feather`, `**/*.clrbackup`, `**/*.tif|tiff|nc|grib|grib2`, `.env`, `.env.*`, `**/*.pem`, `**/*.key`). The **default** root (`private_data/`) is fully excluded, which is what the documented live path uses. Residual: the bare patterns match only the context root, so for a *custom* in-repo root (e.g. `pilot/`) `pilot/manifests/**.json`, `pilot/normalized/**` and `pilot/outputs/reports/**.html` are **not** excluded by any pattern. Docker is not installed in this environment, so this is pattern analysis, not an executed build. `Dockerfile.live` still uses `COPY . .` (NEW-08). |
| **L-11** | `logistics.route_exposure` treats unknown hazard as not-exposed | **STILL OPEN** | `src/clr/logistics.py` is untouched by the remediation (`git diff --stat` shows no change). Latent: `route_exposure`/`shared_hazard_bottlenecks` are called only from tests; the production path uses the correct `route_flood_local.py:180-183` implementation. |
| **L-12** | `factory_attachment` coerces unknown flood depth to `0.0` | **STILL OPEN** | `src/clr/factory_attachment.py` untouched. Latent (tests-only caller). |
| **L-13** | `bounded_portfolio_findings` looks up keys the producer never emits | **STILL OPEN** | `src/clr/portfolio_intelligence.py` untouched; the producer key template at `private_decision_workspace.py:641` is also unchanged, so the mismatch remains. Latent (tests-only caller). |
| **L-14** | `edge_disjoint_count` saturates at `cap` and the clamped value ships un-flagged | **STILL OPEN** | `src/clr/logistics.py` untouched. On the production path with low impact. |
| **L-15** | `source_object_key` accepts `None` and embeds the literal `"None"` | **STILL OPEN** | `src/clr/private_plane.py` untouched. |
| **I-01** | `preflight` PASS over-reads as deployment assurance | **STILL OPEN** | `deployment_examples_valid` is still folded into the single headline `status`, and `validate_deployment_examples` now performs **more** substring checks (MemoryMax, TasksMax, LimitNOFILE, RestrictAddressFamilies, ProtectProc). The docs remain honest about what a rehearsal does not prove. |
| **I-02** | `.gitignore` empty line produces a false `git check-ignore` answer | **STILL OPEN** | **Reproduced:** the blank line moved to `.gitignore:66`; `git check-ignore --no-index -v auth/` → `.gitignore:66:\tauth/`, exit 0 ("ignored"), while `auth/x.json` → exit 1. A trap for exactly the verification step an operator or reviewer performs. |
| **I-03** | Full-precision coordinates in tests | **STILL OPEN** | Unchanged and still harmless (inputs to synthetic rasters / Plus-Code assertions; no entity identified). |
| **I-04** | Two documented authorization models in one tree | **CLOSED** | `docs/PRIVATE_WORKSPACE_APP.md` now opens with a legacy banner, `docs/HOSTED_PRIVATE_PILOT_SECURITY.md` has a "Legacy shared-password shell" section, and `deploy/private_pilot/README.md:28` explicitly forbids running or proxying it. |
| **I-05** | `Dockerfile.live` / `Makefile.live` reference non-existent scripts | **STILL OPEN** | **Reproduced:** `preflight_live_integration.py`, `run_era5_cds.py`, `run_live_profile.py` are all MISSING from `scripts/` while still referenced at `Dockerfile.live:8` and `Makefile.live:2,5,8`. |

### Summary of the Low/Informational set

| Status | Count | IDs |
| --- | --- | --- |
| Closed | 2 | L-02, L-08 (plus I-04) |
| Partially closed | 3 | L-04, L-07, L-10 |
| Still open | 10 | L-01, L-03, L-05, L-06, L-09, L-11, L-12, L-13, L-14, L-15 (plus I-01, I-02, I-03, I-05) |

**Why the many "still open" verdicts are not a bad result.** Six of the ten open Lows (L-11 … L-15) are defects in helper modules that **no production code path calls** — the original audit labelled them latent, and the remediation PRs correctly prioritised the findings that were reachable. Three more (L-05, L-09, and the L-01 Windows case) are hardening items that the original audit itself rated Low and that do not gate a 2–5 user pilot. The one that deserves attention soon is **L-03** (unbounded run selection) because it is the only open Low reachable from the authenticated HTTP surface, and **L-01** if a Windows host were ever used.

---

## 6. New Findings Introduced or Discovered

All new findings are second-order consequences of the audit-hardening work, and all fail closed. None is remotely triggerable. Each is classified per the project's own severity convention.

### NEW-01 — Crash or I/O error between the audit commit and the anchor write permanently stops all audited actions, and the only supported repair silently legitimises the database state

| Field | Value |
| --- | --- |
| **Severity** | **Medium** (availability + evidentiary integrity; not remotely triggerable) |
| **File / function** | `src/clr/private_workspace_access.py` — `record_audit_event` (commit at :401, `_write_audit_anchor` at :404) and `initialize_audit_anchor` (:507-534) |
| **Precondition** | The process dies (OOM kill, power loss, `systemctl restart`) or `_write_audit_anchor` fails (ENOSPC, read-only filesystem, EPERM on `auth/`) **after** `conn.commit()` and **before** `os.replace(tmp, anchor)` — a window of roughly the time to write a 265-byte file |
| **Failure path** | The DB has N+1 events, the anchor still says N. Every subsequent `record_audit_event` raises `ValueError("Audit database head no longer matches the external anchor")`. Because the pilot audits every login, every report view, every report generation and every audit view, the practical effect is: correct credentials produce `401 "Sign-in failed."`; `GET /report` returns a misleading 404 via the `except (ValueError, FileNotFoundError)` collision (see NEW-06); `/audit` raises. The service restarts into a permanently broken state (`Restart=on-failure` makes this a loop) and there is **no documented repair**. |
| **Reproduced** | Simulated the torn write (inserted an event directly, leaving the anchor one behind): `verify_audit_chain → valid=False, reason=EVENT_COUNT_MISMATCH`; next append → `ValueError: Audit database head no longer matches the external anchor`. Then reproduced the repair path: deleting `auth/audit_head_anchor.json` and re-running `initialize_audit_anchor` produced `bootstrapped=True, event_count=0` and `verify_audit_chain → valid=True` — **the truncation became invisible**. Note also that re-running `scripts/init_private_pilot_access.py` *without* deleting the anchor does nothing (it returns the existing, stale anchor), so the documented init step does not repair the condition. |
| **C/I/A impact** | Availability: total for authenticated use. Integrity: the anchor's evidentiary value is destroyed by the only available repair. Confidentiality: none. |
| **Reachability in the documented pilot** | Requires a crash or filesystem error in a narrow window. Not attacker-triggerable remotely. Probability is low per event but non-zero across a pilot's lifetime, and the *consequence* is an outage that looks like "authentication is broken". |
| **Concrete fix** | (1) Write the anchor **inside** the same logical step as the commit and make the mismatch recoverable: if the DB head is exactly one event ahead of the anchor (and that event's `prev_hash` equals the anchor's head), heal the anchor instead of raising, and record a `AUDIT_ANCHOR_REPAIRED` event. (2) Alternatively make the anchor derivable from the DB when the DB is *ahead* but not when it is *behind* — asymmetry encodes which side lost the race. (3) Provide an explicit, auditable operator tool (`--reanchor --reason`) that writes a `AUDIT_ANCHOR_RESET` event before re-anchoring, so a legitimate re-bootstrap can never be silent. (4) Document the repair procedure in `docs/HOSTED_PRIVATE_PILOT_SECURITY.md` and add it to the deployment runbook. |
| **Regression test to add** | Append a row directly (simulating the torn write), then assert that the *next* `record_audit_event` heals the anchor, that an `AUDIT_ANCHOR_REPAIRED` event exists, and that `verify_audit_chain` returns valid — and a negative test that a *behind* anchor (rows deleted) is never auto-healed. |
| **Blocks the small pilot?** | **Yes, in the sense that the runbook must address it.** Either implement auto-heal or document the repair. Leaving an undocumented total-outage state in a pilot whose value proposition includes an audit chain is not acceptable. |

### NEW-02 — Privileged CLI mutations are not atomic with their audit record: a change can take effect unaudited

| Field | Value |
| --- | --- |
| **Severity** | **Medium** (audit completeness) |
| **File / function** | `src/clr/private_workspace_access.py` — `create_user` (:558-589), `set_user_password` (:607-636), `set_user_active` (:648-669), `grant_membership` (:684-719), `revoke_membership` (:732-754). Each commits its mutation, then calls `record_audit_event` **outside** that transaction. |
| **Precondition** | Any failure of the audit append: a stale/torn anchor (NEW-01), a lock timeout, or ENOSPC. Newly *more* likely than before the remediation, because the anchor adds a failure mode that did not exist previously. |
| **Failure path** | **Reproduced:** with a corrupted anchor, `set_user_active(root, user_id=…, is_active=False)` raised `ValueError` from the audit append — and the user's `is_active` had already changed from `1` to `0`, while the count of `USER_DISABLED` audit rows remained **0**. The same applies to `revoke_membership` (access revocation without a record), `grant_membership` (privilege grant without a record), `create_user` and `set_user_password`. |
| **C/I/A impact** | Integrity of the audit record: the chain can be *complete and valid* while missing a privileged change entirely. This is the one property an evidentiary log must not have. Confidentiality/availability: none. |
| **Reachability in the documented pilot** | The CLI is the only access-management path, so it is in scope. Requires an audit-append failure first. |
| **Concrete fix** | Perform the mutation and the audit insert in **one** transaction: acquire `BEGIN IMMEDIATE`, verify the anchor inside it, insert the audit row, apply the mutation, commit, then update the anchor. Alternatively record the audit intent first (fails closed and leaves a visible orphan), or make the mutation conditional on the audit append succeeding by wrapping both in a single `with connect_catalog(...)` block. |
| **Regression test to add** | With a deliberately invalid anchor, assert that a privileged mutation raises **and** that the DB is unchanged (i.e. no unaudited `USER_DISABLED`/`MEMBERSHIP_REVOKED`). |
| **Blocks the small pilot?** | No, but it should be fixed alongside NEW-01, since both concern the same transaction boundary. |

### NEW-03 — The audit anchor protocol is not multi-process safe: concurrent appends spuriously fail

| Field | Value |
| --- | --- |
| **Severity** | **Medium** (availability; fails closed) |
| **File / function** | `src/clr/private_workspace_access.py` — `_AUDIT_APPEND_LOCK = threading.RLock()` (in-process only) + the read-anchor → `BEGIN IMMEDIATE` → count check → insert → commit → write-anchor sequence |
| **Precondition** | Two processes writing audit events against the same workspace. In the documented pilot: the web app plus any operator CLI command that mutates access state (each of those writes an audit event), or a second app worker. |
| **Failure path** | **Reproduced:** three processes × 6 appends each (18 attempts) → **6 succeeded, 12 raised** `ValueError("Audit database head no longer matches the external anchor")`. The `BEGIN IMMEDIATE` serialises the DB writes, so the chain stays consistent (final state: `valid=True, checked_events=7, anchor_event_count=7`) — the failure is a rejected append, not corruption. In the web app a rejected append on the login path becomes `401 "Sign-in failed."`, which an operator would misread as a credentials problem. **Correction to the external reviewer's analysis:** DeepSeek described this race as leaving the anchor "mismatched by one event"; the reproduced behaviour is that the second writer fails *before* inserting, so no desynchronisation occurs. |
| **C/I/A impact** | Availability: spurious failures of audited actions under concurrency. Integrity: none (verified). Confidentiality: none. |
| **Reachability in the documented pilot** | Real but low-frequency: the collision window is ~1–3 ms and requires an operator CLI action to overlap a web request. |
| **Concrete fix** | Serialise across processes — an OS-level lock file (`fcntl`/`msvcrt`) around the anchor read + append + anchor write, or derive the expected count from inside the transaction and only treat a *lower* DB count as tampering (a DB count **above** the anchor is the normal in-flight case and can be retried). A bounded retry (3 attempts) around the append would remove nearly all spurious failures. |
| **Regression test to add** | Two concurrent processes appending N events each; assert every append succeeds and the chain verifies. |
| **Blocks the small pilot?** | Only if the operator runs the CLI while users are active. Either add the retry or put "run access-management commands when the pilot is idle" in the runbook. |

### NEW-04 — The per-key login rate limit is bypassable by varying the tenant string

| Field | Value |
| --- | --- |
| **Severity** | **Low** (the global limiter still bounds total work) |
| **File / function** | `src/clr/private_workspace_pilot_app.py` — `_LoginRateLimiter.key(username, tenant)`: `raw = f"{str(username).strip().casefold()}\x00{str(tenant)}"` — the **tenant is not canonicalised**, while `authenticate_user` validates it through `canonical_tenant_key`. |
| **Precondition** | Network reachability to `/login`; no credentials. |
| **Failure path** | **Reproduced over HTTP** with `login_attempts_per_key=3`: four attempts against the *same account* `usera` using tenants `TENANT_A`, `TENANT_A `, `tenanT_A`, ` TENANT_A` returned **401, 401, 401, 401 — no 429**, because each spelling hashes to a different limiter key while every spelling still exercises the full PBKDF2 path (`canonical_tenant_key` rejects the malformed spellings only *after* the limiter is consulted, and `authenticate_user` then performs the dummy work). The effective per-account limit therefore collapses to the global limit (120/min instead of 8/5 min). Usernames *are* canonicalised (`.strip().casefold()`, matching the DB's `COLLATE NOCASE`), and the repo's test asserts that — it simply does not test the tenant half. |
| **C/I/A impact** | Weakens a brute-force control by ~75×; the global ceiling still bounds CPU (H-01 residual). Password space (12-char minimum, 310k PBKDF2) makes online guessing impractical either way. |
| **Reachability** | Yes, from the internet. |
| **Concrete fix** | Canonicalise the tenant inside the limiter key, and use a single constant bucket for tenants that fail validation: `try: t = canonical_tenant_key(tenant) except ValueError: t = "<invalid>"`. |
| **Regression test to add** | Assert `_LoginRateLimiter.key("u", "TENANT_A") == _LoginRateLimiter.key("u", " TENANT_A")`, and an HTTP test asserting that N attempts against one account with varying tenant spellings are throttled. |
| **Blocks the small pilot?** | No. Worth fixing because it is a security control that does not do what it appears to do. |

### NEW-05 — `set_user_password` has no upper length bound, and an over-long password locks the account out permanently

| Field | Value |
| --- | --- |
| **Severity** | **Low** |
| **File / function** | `src/clr/private_workspace_access.py` — `set_user_password` checks only `len(password) < 12` (:602-603) whereas `create_user` enforces `MAX_PASSWORD_CHARS = 1024` (:550-551), and `authenticate_user` rejects any input longer than `MAX_PASSWORD_CHARS` **before hashing** (:791-793). |
| **Precondition** | An operator sets a password longer than 1024 characters via `reset-password` (paste, or automation). |
| **Failure path** | **Reproduced:** `set_user_password(..., password="Z"*2000)` was accepted; thereafter `authenticate_user` with the exact 2000-character password **FAILS** and with its first 1024 characters **FAILS** — the account is unreachable by any password, with no error message explaining why. |
| **C/I/A impact** | Availability for that one account; no attacker control. |
| **Reachability** | Operator-only (CLI, hidden input prompt). |
| **Concrete fix** | Add the same `MAX_PASSWORD_CHARS` upper bound (and a clear message) to `set_user_password`, so the create and reset paths enforce the same contract. |
| **Regression test to add** | `pytest.raises(ValueError)` for a 1025-character password in `set_user_password`. |
| **Blocks the small pilot?** | No. |

### NEW-06 — A broken audit subsystem is misreported as "report file not available", and report delivery now depends on the audit append

| Field | Value |
| --- | --- |
| **Severity** | **Low** |
| **File / function** | `src/clr/private_workspace_pilot_app.py` — the `/report` branch: `record_audit_event(...)` now runs **before** `self._headers(200, …)`/`self.wfile.write(data)` inside a `try` whose handler is `except (ValueError, FileNotFoundError)`. |
| **Precondition** | The audit append raises a `ValueError` (stale/invalid anchor, NEW-01). |
| **Failure path** | The audit failure is caught as if it were a path error, the handler then calls `record_audit_event` **again** (which raises again), and that second exception escapes `_do_GET`, is not a busy `OperationalError`, and is re-raised — so the client gets no response at all while the app's error message would have said "report file not available". Two consequences: (a) misleading diagnosis; (b) a report that could previously be delivered even when auditing failed is now withheld (fail-closed, arguably intentional, but it couples report availability to audit availability). |
| **C/I/A impact** | Availability and diagnosability. No confidentiality impact. |
| **Reachability** | Requires an audit-append failure first. |
| **Concrete fix** | Narrow the handler to the file-resolution errors it means (`except FileNotFoundError` for the report path, plus an explicit `ReportPathError`), or move the audit append outside the file-resolution `try` and give the audit failure its own 503 path. |
| **Regression test to add** | With a deliberately invalid anchor, assert `GET /report` returns a 503-class response (or a 500 with a diagnostic), not a 404 and not a dropped connection. |
| **Blocks the small pilot?** | No; it compounds NEW-01. |

### NEW-07 — No size bound on recovery-bundle tar members

| Field | Value |
| --- | --- |
| **Severity** | **Low** |
| **File / function** | `src/clr/private_pilot_rehearsal.py` — `_read_encrypted_recovery_bundle` (:392-416): after `names != allowed` and `member.isfile()` checks, each member is read with `extracted.read()` and no size limit. |
| **Precondition** | An actor who knows the bundle passphrase (or a corrupted bundle that still authenticates, which is not possible) supplies a bundle to an operator who runs the restore. |
| **Failure path** | A member can declare an arbitrary `TarInfo.size`, so the restore host can be driven to memory exhaustion before the allowlist check has any effect on the read. Reachability is genuinely poor: the attacker must already hold the passphrase, and the restore is an operator-initiated action against a new empty directory — an actor with the passphrase has little to gain. |
| **C/I/A impact** | Availability of the recovery host. |
| **Reachability** | Low. |
| **Concrete fix** | Reject any member whose declared size exceeds a bound (e.g. 4 GiB or 2× the catalog size recorded in the manifest), and stream to disk instead of reading into memory. |
| **Regression test to add** | A crafted bundle with a member declaring an implausible size is rejected with a clear error. |
| **Blocks the small pilot?** | No. |

### NEW-08 — `.dockerignore` does not cover a custom-root workspace's text artefacts

| Field | Value |
| --- | --- |
| **Severity** | **Low** |
| **File** | `.dockerignore`; `Dockerfile.live:4` (`COPY . .`) |
| **Precondition** | A Docker build whose context contains an initialized workspace whose directory name is not one of the excluded names (e.g. `pilot/` — a root the documentation invites). |
| **Failure path** | The bare patterns (`private_data`, `outputs`, `raw`, …) match only the context root, so a custom-root workspace's `manifests/plans/*.json` (asset coordinates + `external_id`), `normalized/**` and `outputs/reports/**.html|json` are excluded only if their *extension* happens to be covered (`*.parquet`, `*.sqlite`, `*.tif` are; `.json`/`.html`/`.csv` are not). Those files would be baked into image layers. The default `private_data/` root — the documented Docker path — is fully covered. **Docker is not available in this environment, so this is pattern analysis, not an executed build.** |
| **C/I/A impact** | Confidentiality, if an image is pushed. |
| **Reachability** | Requires Docker plus a custom-root workspace inside the build context. The pilot's documented deployment is systemd, not Docker. |
| **Concrete fix** | Add `**/manifests/**`, `**/normalized/**`, `**/indicators/**`, `**/auth/**`, `**/outputs/**`, `**/tmp/**` and `**/backups/**` (or replace `COPY . .` with an explicit allow-list copy). |
| **Regression test to add** | Extend the repo's `.dockerignore` test from substring presence to a behavioural check — a helper that applies the patterns to a candidate path list, including a custom-root case. |
| **Blocks the small pilot?** | No. |

### NEW-09 — The boundary checker's directory list has already drifted from `.gitignore`'s globs

| Field | Value |
| --- | --- |
| **Severity** | **Low** |
| **File** | `src/clr/public_boundary.py` (`FORBIDDEN_PATH_FRAGMENTS`) vs `.gitignore` |
| **Precondition** | A future addition to `local_store.WORKSPACE_DIRS` under `normalized/` or `indicators/` (e.g. `normalized/foobar/`). |
| **Failure path** | `.gitignore` protects the *directory* (`**/normalized/`, `**/indicators/`) while the checker enumerates each **child** (`/normalized/assets/`, `/normalized/admin/`, … `/indicators/logistics/`). A new child directory is therefore gitignored but invisible to the checker — a silent regression of the M-05/M-09 recommendation to derive the guard from the layout. The original recommendation ("import `WORKSPACE_DIRS`") was not implemented; the list is now longer but still hand-copied. |
| **C/I/A impact** | None directly; it degrades the second line of defence. |
| **Reachability** | No attacker involvement. |
| **Concrete fix** | Derive the fragments from `local_store.WORKSPACE_DIRS` and add a test asserting every workspace directory is covered by both `.gitignore` and the checker. |
| **Regression test to add** | As above (this is the test the original audit recommended and which would have caught the original gap). |
| **Blocks the small pilot?** | No. |

### NEW-10 — `shared_edge_evidence_available` defaults to the optimistic branch

| Field | Value |
| --- | --- |
| **Severity** | **Low** |
| **File / function** | `src/clr/compound_local.py` — `cross_asset_summary(..., shared_edge_evidence_available: bool = True)` |
| **Precondition** | A future caller omits the argument while passing an empty `shared_edges` frame. |
| **Failure path** | With the default, empty edges plus `True` yields the *old* behaviour: three `0.0` values flagged `OK`. The guard cannot verify itself — it trusts a caller-supplied assertion rather than deriving availability from `shared_edges`/`route_edges`. The current production caller is correct (`shared_edge_evidence_available=not route_edges.empty`), so this is a latent footgun, not a live defect. |
| **C/I/A impact** | Integrity of interpretation, if triggered. |
| **Reachability** | No attacker involvement. |
| **Concrete fix** | Make the parameter required (no default), or default to the conservative `False`, or derive it internally. |
| **Regression test to add** | `pytest.raises(TypeError)` when the parameter is omitted, or an assertion that the default produces the conservative branch. |
| **Blocks the small pilot?** | No. |

### NEW-11 — A fully-`NaN` heat month still publishes `days_tmax_gt_35c = 0`

| Field | Value |
| --- | --- |
| **Severity** | **Informational** |
| **File / function** | `src/clr/compound_local.py` — heat-monthly aggregation |
| **Precondition** | A month in which every `temp_c` is null (partial extraction / grid gap). |
| **Failure path** | `g.loc[temp.gt(35.0),"date"].dt.date.nunique()` selects nothing and returns `0`, while `monthly_max_tmax_c` is correctly `None`. The row does carry `heat_quality_flag = "INCOMPLETE_HEAT_MONTH"`, and `heat_drought_annual` nulls the annual compound metric, so no *published compound metric* inherits the zero — which is why this is Informational rather than a governance failure. The monthly indicator as written to `asset_indicator`, however, pairs a concrete `0` with a non-OK flag. |
| **Concrete fix** | Emit `None` for the two count fields when `valid_days == 0` (or when the month is incomplete), matching the treatment of `monthly_max_tmax_c`. |
| **Regression test to add** | An all-`NaN` month asserts the count fields are null, not `0`. |
| **Blocks the small pilot?** | No. |

### NEW-12 — Upgrading an existing workspace requires re-running the init step, and a pre-existing dirty chain now hard-fails the schema application

| Field | Value |
| --- | --- |
| **Severity** | **Low** (deployment/documentation) |
| **File / function** | `src/clr/private_workspace_access.py` — `apply_access_schema` now calls `initialize_audit_anchor` (:161-162), which raises if an existing chain does not verify (:523-527); `record_audit_event` requires a valid anchor (:341-345). |
| **Precondition** | (a) A workspace created before this commit (no `auth/audit_head_anchor.json`) is served by the new code without re-running `scripts/init_private_pilot_access.py`; or (b) an existing workspace whose chain already fails verification is upgraded. |
| **Failure path** | (a) Every audited action fails — logins return `401 "Sign-in failed."` — until the operator re-runs the init step. The rehearsal's preflight *does* catch it (`audit_anchor_present: False` → `FAIL`, and it would report `AUDIT_RECOVERY_STATE_MISSING`), which is a decent safety net, but the requirement is not documented and the failure mode looks like an authentication problem. (b) `apply_access_schema` raises `"Cannot bootstrap audit anchor from invalid chain"`, aborting schema application — correct fail-closed behaviour, but an upgrade path that requires an explicit decision is better than one that aborts with no documented remedy. |
| **Concrete fix** | Document the upgrade step ("re-run `scripts/init_private_pilot_access.py`; the rehearsal will report `audit_anchor_present: false` until you do") and, for case (b), provide the explicit re-anchor tool from NEW-01's fix so the operator has a sanctioned path. |
| **Regression test to add** | A workspace with events and no anchor: assert the documented init step creates a bootstrapped anchor and that login then succeeds. |
| **Blocks the small pilot?** | No for a fresh install (the init step is already part of the documented sequence). Relevant only if an existing workspace is upgraded. |

### NEW-13 — The application access log loses the status code for any request with a query string

| Field | Value |
| --- | --- |
| **Severity** | **Informational** |
| **File / function** | `src/clr/private_workspace_pilot_app.py` — `log_message` does `message = (fmt % args).split("?", 1)[0]`. `BaseHTTPRequestHandler.log_request` passes `'"%s" %s %s'` (request line, status, size), so truncating at the first `?` also discards the status and size for every query-bearing request. |
| **Precondition** | Any request to `/report?path=…`, `/file?path=…` or `/_` with a query string. |
| **Failure path** | **Verified:** a real write lock produced `503` and the app logged exactly `[pilot] 127.0.0.1 "GET /report` — the `503` and the byte count were cut off. So failures on the report/audit paths are invisible in the application log; only Caddy's JSON log records them. `log_message` *is* called for the 503 path (contradicting the external reviewer's claim that it is not), but the status is stripped. |
| **C/I/A impact** | Observability only. The query-string stripping is otherwise a *good* privacy control (it keeps tenant/subject identifiers out of the log) and should be kept. |
| **Concrete fix** | Strip only the query portion of the request line, or log the status separately: e.g. take the message up to `?`, then append the status obtained from `args`. |
| **Regression test to add** | Assert that a 503 on a query-bearing path produces a log line containing the status. |
| **Blocks the small pilot?** | No, but the operator will be reading these logs during the pilot. |

### NEW-14 — The backup policy recommends a daily cadence while the CLI requires an interactive passphrase

| Field | Value |
| --- | --- |
| **Severity** | **Informational** (deployment/operations) |
| **Files** | `docs/LOCAL_BACKUP_POLICY.md:58-62` ("Recommended cadence: … at least daily while actively changing the private catalog"); `scripts/backup_private_catalog.py` (two `getpass` prompts, passphrase never accepted as an argument — correct). |
| **Precondition** | An operator tries to satisfy the cadence with cron/systemd-timer automation. |
| **Failure path** | `getpass` has no TTY under cron and the job fails or hangs, so the recommended cadence is not actually achievable without operator interaction. Nothing in the policy describes how to automate it (e.g. a secrets-store-fed wrapper, a systemd `LoadCredential=`, or an explicit "operator-run" statement). |
| **Concrete fix** | Either state that backups are operator-run with a defined cadence, or document a non-interactive path that reads the passphrase from an OS credential store rather than an argument. |
| **Blocks the small pilot?** | No, provided the operator commits to running backups interactively; add it to the host checklist. |

---

## 7. Public / Private Boundary Reassessment

**Verdict: the boundary is substantially stronger, and the fix was applied at the right level.**

The original finding's root cause was that the guard was a *name* list applied to a workspace whose location was an operator choice. The remediation changed the architecture of the control rather than extending the list: **`initialize_workspace` now writes `<root>/.gitignore` containing `*`, and refuses to initialize at a Git repository root.** Verified in a real git repository with coordinates, secrets and reports present inside the workspace: `git status --porcelain` is empty. Every workspace directory is therefore protected regardless of its name, and a future directory added to `WORKSPACE_DIRS` cannot open a hole — which is exactly the property that was missing.

Layered on top:

- `.gitignore` gained `**/…` patterns for the workspace marker, the three secret files, the marker-anchor file, and the reports/QA/backups/manifests/normalized/indicators/tmp paths — so a *non-initialized* stray copy is also covered.
- `public_boundary.py` gained `FORBIDDEN_PATH_FRAGMENTS` matched at any depth (fixing the root-anchoring weakness that made the original probes slip through), the `-wal`/`-shm`/`.clrbackup` suffixes, and the workspace secret basenames. A negative test guards against over-blocking legitimate methodology paths.
- `.dockerignore` was added; the default root is fully excluded from build contexts.
- `*.clrbackup` is both gitignored and flagged by the checker, and the recovery bundle contains no plaintext passphrase (verified).

**No real private data exists in the tree or in history.** The boundary sweep re-confirmed the original conclusion (242 tracked files; synthetic markers throughout; no credentials, coordinates tied to an entity, or absolute paths), and the four remediation commits add only code, tests and documentation. I spot-checked the new artefacts: `tests/test_private_workspace_user_cli.py` and the new pilot tests use `analyst@example.com`/`TENANT_A`/`synthetic-*` values only.

**Residual gaps** (all Low, none a leak today): the checker still performs no content inspection and still uses exact-match basenames (L-10/M-09); `tracked_files()` still does not recurse into submodules; there is still no pre-commit hook; the empty line at `.gitignore:66` still makes `git check-ignore --no-directory`-style verification return a false "ignored"; `.dockerignore` does not cover a custom-root workspace's text artefacts; and the checker's directory enumeration has already drifted from `.gitignore`'s globs (NEW-09). The load-bearing control is the workspace-level `.gitignore`, which is why none of these is a pilot blocker.

---

## 8. Authentication, Session and Authorization Reassessment

### Authentication

| Control | Status | Evidence |
| --- | --- | --- |
| Password hashing | Unchanged and sound | PBKDF2-HMAC-SHA256, 310 000 iterations, per-user 16-byte salt, per-user iteration count enforced ≥ 100 000 by schema `CHECK`. |
| Password length bounds | **Improved, one gap** | `create_user` now caps at 1024 (`MAX_PASSWORD_CHARS`) and rejects over-long input before hashing; `set_user_password` still lacks the cap (NEW-05, verified lockout). |
| Failed-attempt work parity | **Fixed** | Dummy KDF for unknown/inactive/invalid/over-long inputs and a top-up on the real path equalise total iterations; measured medians 672 ms vs 666 ms (was 48 ms vs 185 ms); deterministically asserted by the repo's iteration-count test. |
| Rate limiting | **New, partially effective** | Per-key 8/300 s, global 120/60 s, LRU-bounded key map, 429 + `Retry-After`. Global ceiling still permits ~66 % of a 2-vCPU host's CPU (H-01 residual); per-key bucket bypassable via tenant spelling (NEW-04); no proxy-level limit. |
| Username handling | **Improved** | Only `sha256(casefold(username))[:128]` is persisted for denied logins (verified: 86-byte rows, raw username absent); oversize usernames are rejected before any audit write. |
| Error behaviour | Unchanged and sound | Identical generic message for unknown user / wrong password / missing membership / inactive / invalid tenant. |
| Login CSRF | **Improved** | Foreign `Origin` → 403 before authentication (verified by test); absent `Origin` still accepted; no pre-auth token (L-04 residual). |

### Sessions

Unchanged in substance and still sound: opaque 384-bit `secrets.token_urlsafe(48)` tokens, only SHA-256 hashes stored, a new token per login (no fixation, previously verified), DB-backed verification joined live to `is_active` and the current membership role, and revocation on role change / membership revoke / disable / password change. Two improvements: session verification is now **read-mostly** (the `last_seen_at` write is throttled to once per 5 minutes on a separate short-timeout connection and its failure is tolerated), and the busy path returns 503 rather than dropping the connection.

Residual (L-07, unchanged): no idle timeout (`last_seen_at` is recorded but never used to expire), no `__Host-` cookie prefix, no re-authentication for sensitive actions.

### Authorization

Unchanged and verified again — the authorization core remains the strongest part of this system. Every cross-tenant path the review brief lists was attempted:

| Path attempted | Result |
| --- | --- |
| Report HTML path (`/report?path=…`) for another tenant | **404**, no leak (verified over HTTP) |
| JSON/manifest path (`/file?path=…`) for another tenant | 404 (same confinement function) |
| Asset / portfolio / indicator-run / compound-run / route-run selectors | Re-checked per-tenant inside the adapter SQL (`_require_indicator_runs_for_tenant`, `_require_compound_run_for_tenant`, `_require_route_run_for_tenant`, `_resolve_asset`, `_portfolio_rows`) — unchanged and still present |
| Generated-report listing | Tenant-scoped (verified: tenant A's dashboard does not contain tenant B's subject) |
| Dot-segment tenant keys | **Now rejected** before any path is built (verified) |
| Case-variant tenant keys | Still collide on a case-insensitive filesystem (L-01, Windows only) |
| Path traversal (`../../etc/passwd`) and `outputs/reports/../../auth/audit_chain_secret.bin` | Both **404** (verified) |
| Manually altered HTTP form/query values | Role check plus adapter tenant checks; VIEWER → `/generate` still 403 with a `DENIED` audit event |
| Stale session after role change / membership revoke / disable | Invalid; the rehearsal preflight **fails** if such a session is active |

**DeepSeek's verdict that M-01 is "closed only contractually" is overridden:** I executed the tenant canonicaliser, the confinement helper and the HTTP paths, so the closure is verified rather than assumed (see §4 M-01 and §14).

---

## 9. Audit Integrity Reassessment

### What the anchor does (verified)

| Property | Verified by |
| --- | --- |
| Detects tail truncation of the SQLite table | Deleting the newest event → `EVENT_COUNT_MISMATCH` (`checked_events=3`, `anchor_event_count=4`) |
| Detects head-hash drift with an intact count | Anchor `head_hash` compared to the recomputed chain head → `HEAD_HASH_MISMATCH` |
| Detects anchor modification without the HMAC key | Bumping `event_count` → `AUDIT_ANCHOR_MAC_MISMATCH` |
| Detects content modification of any non-tail event | `EVENT_HASH_MISMATCH` at the exact row (unchanged from the original audit) |
| Detects a mid-chain deletion | `PREVIOUS_HASH_MISMATCH` at the following row |
| Detects a stale anchor at append time | `record_audit_event` refuses to append: `"Audit database head no longer matches the external anchor"` |
| Does not mint a key during verification | Catalog-only restore → `AUDIT_SECRET_MISSING`, and no `auth/audit_chain_secret.bin` was created as a side effect |
| Survives the recovery path | The bundle carries the secret *and* the anchor; restore re-verifies the chain, event count and head against the manifest |
| Preflight fails closed without secret or anchor | `AUDIT_RECOVERY_STATE_MISSING` |

### What the anchor does not do (the precise security property)

This is **tamper-evident + truncation-evident against SQLite-only alteration, backed by an anchor inside the same host trust domain. It is not immutable logging.**

- An actor who can write `auth/` (the operator, a compromised service account) can read `audit_chain_secret.bin`, delete or rewrite `audit_head_anchor.json`, and re-MAC a consistent anchor over a truncated table. This is actor A5, and A5 is precisely the actor the original finding named. The control therefore raises the bar (two files must be changed consistently instead of one `DELETE`) rather than closing the class.
- Deleting the anchor and re-running the init step **silently legitimises** whatever the database contains (reproduced, §4 H-02).
- A crash between commit and anchor write produces a permanent, fail-closed outage with no documented repair (NEW-01).
- Append consistency is in-process only (NEW-03).
- Privileged mutations can land unaudited (NEW-02).
- Rows are still all loaded into memory for verification (`fetchall()`), so the ADMIN audit page scales linearly with table size (§12).

**Documentation quality.** The project documents the limitation accurately and prominently, including the exact sentence that a reviewer needs: the anchor "does not make the log immutable against an operator or attacker who can rewrite the database, anchor and audit key together." Combined with `deploy/private_pilot/README.md`'s instruction to ship audit logs to a separately protected destination for production, the claim and the implementation agree. **The correct forward step is not a redesign but an off-host anchor** (append the head hash to the proxy log, the systemd journal, or an operator-held file outside the workspace), which would move B from the same trust domain into a different one and would also give the operator the missing repair semantics.

---

## 10. Backup / Restore and Disaster-Recovery Reassessment

**Verdict: this is the remediation's most complete piece of work, and it removes the false-confidence conditions the original audit identified.**

Implemented and verified (details in §4 M-06):

- **Encryption.** `AES-256-GCM`, key from `PBKDF2-HMAC-SHA256` with 600 000 iterations, per-bundle random 16-byte salt and 12-byte nonce, header authenticated as AAD. A random nonce with a per-bundle key is the correct construction; no nonce reuse is possible across bundles.
- **Passphrase handling.** Interactive `getpass` with confirmation; never a CLI argument (verified in both scripts); never stored in the bundle (verified: the passphrase does not appear in the file bytes); minimum 16 characters enforced in `_derive_recovery_key`.
- **Allowlisted contents.** Exactly `catalog/climate_risk.sqlite`, `auth/audit_chain_secret.bin`, `auth/audit_head_anchor.json`, `recovery_manifest.json` — the name set is compared for equality, non-file members are rejected, and extraction uses `extractfile` rather than `extractall`, so tar path traversal is structurally impossible.
- **Meaningful verification.** Wrong passphrase → rejected; a single flipped bit → rejected; the restored catalog's SHA-256 **and** logical state fingerprint are checked against the AEAD-authenticated manifest; secret and anchor SHAs are checked; the chain, event count and head are re-verified. The tautological "backup equals its own copy" check is gone, replaced by a three-way logical fingerprint comparison.
- **Restore safety.** The target must be empty or absent, so the live workspace cannot be overwritten; the CLI additionally refuses a non-empty target before prompting.
- **Negative control in the automated rehearsal.** Catalog-only restore is *expected* to fail audit verification (`AUDIT_SECRET_MISSING`) and the rehearsal asserts it — the single most valuable addition, because it tests the scenario the old rehearsal silently designed around.
- **The 236-test suite passes**, including the two tests that failed on Windows before the connection-lifecycle fix.

**Residual gaps** (all Low/Informational, none blocking): `deployment_examples_valid` remains inside the headline PASS (I-05); the rehearsal generates and consumes its own passphrase in one process, so it proves the code path rather than independent key custody (a real off-host drill remains a host-side step); a transient plaintext catalog snapshot exists under `root/tmp/` during bundle construction; an older bundle restores cleanly and rolls the workspace back (inherent to backups); there is no size bound on tar members (NEW-07); and the backup CLI cannot run non-interactively while the policy recommends a daily cadence (NEW-14).

---

## 11. Analytical Governance Reassessment

**Verdict: governance is intact, and the three genuine defects found in the compound layer are fixed. No composite score or hazard-to-loss conversion was introduced by any remediation commit.**

Re-tested and confirmed:

| Rule | Status |
| --- | --- |
| No arbitrary composite climate-risk score | Intact. `FORBIDDEN_KEYS` recursive assertion still applied to the assembled report; keyword sweep of `src/` finds only prohibition sets, guardrail strings and labels. |
| Hazard distinct from loss / downtime / PD / LGD / ECL | Intact. `FORBIDDEN_METRIC_CLASSES` enforced in both `decision_reports.py` and `product_output.py`. |
| Portfolio shares require and render an explicit denominator | **Fixed** (M-07): enforced at construction and in the assembler, and rendered in the HTML table. Residual: two key names, no basis field. |
| Null metrics cannot appear as confident OK values | **Fixed for the compound layer** (M-11 verified both branches; M-12 raises on missing lineage; M-10's flag now propagates to a null annual metric). Residual: the `shared_edge_evidence_available` default (NEW-10) and fully-`NaN` month counts (NEW-11). |
| NaN denominator handling correct | **Fixed** (H-03 reproduced: 9/9 rows pass the guard) |
| Heat-drought invalid-evidence handling | **Fixed** (M-10, repo test asserts the annual metric nulls) |
| Heat lineage failures not silently converted into valid-looking results | **Fixed** (M-12; propagation test) |
| Empty shared-edge cases do not create confident zeros | **Fixed for the shipped caller** (M-11; verified both branches) |
| Evidence classes remain distinct | Intact (`value_class` `SOURCE`/`CALCULATED` with per-indicator `measurement_basis`; `contracts/risk_output.schema.json` enum). |
| Route exposure ≠ closure | Intact (`JRC_RP…_EXPOSURE_ONLY` scenario ids; `prune_hazard_edges` only on an explicit `hazard_blocked` attribute). |
| Population ≠ workforce; built-up ≠ property value | Intact (WorldPop/GHSL indicators and notes unchanged). |
| Compound evidence ≠ weighted index | Intact (co-occurrence and counts, with explicit valid-data denominators). |

**Can a normal compound/cross-asset run reach `SUCCESS`?** Yes. The crash that made this impossible is fixed; I reproduced the summary→guard path (9/9 rows) and the repository's own tests perform real `_insert_cross_metric` writes into `cross_asset_metric` with a `NaN` denominator and with full source lineage, both passing. The one path I could not execute end-to-end is the full `scripts/run_compound_cross_asset_local.py` against real ERA5/CHIRPS/route Parquet, because no real private data exists in this environment; that remains a host-side validation (§16).

**Still open and unaddressed (all Low, all latent):** `logistics.route_exposure` treating unknown hazard as not-exposed (L-11), `factory_attachment` coercing an unknown depth to `0.0` (L-12), `portfolio_intelligence` looking up metric keys the producer never emits (L-13), the un-flagged `edge_disjoint_count` cap (L-14), and the `"None"` object-key segment (L-15). None is called from production code; they should be fixed before any production caller adopts them.

---

## 12. SQLite and Concurrency Reassessment

| Aspect | Status | Evidence |
| --- | --- | --- |
| Context-managed connections actually close | **Fixed** | `_ClosingConnection`; verified `ProgrammingError` after the block; exactly one `sqlite3.connect` site remains in `src/`+`scripts/`. |
| Busy timeout | **Fixed** | `timeout` **and** `PRAGMA busy_timeout` (default 5 000 ms), set explicitly; a 50 ms variant for the best-effort session touch. |
| Session verification is read-mostly | **Fixed** | `last_seen_at` throttled to once per 5 minutes with a conditional `UPDATE … WHERE last_seen_at IS NULL OR last_seen_at < ?`. Verified: an authenticated `GET /` under a held write lock returns **200 in 0.0 s**. |
| Optional touch failure does not invalidate a session | **Fixed** | The touch is on a separate connection and swallows only locked/busy; a real `BEGIN IMMEDIATE` during `verify_session(now=+12 min)` still returns the identity (repo test). |
| Genuine busy/locked request → controlled 503 | **Fixed** | Verified with a real lock: `503` + `Retry-After: 1` after 5.5 s instead of a dropped connection. |
| Windows/file-handle assumptions | **Fixed** | The two previously failing rehearsal tests now pass; the temp restore directory is removed cleanly. |
| WAL | Already correct | `migrations/000_local_private_data_plane.sql:2` sets `journal_mode = WAL`, which removes reader/writer blocking. Note: WAL does **not** remove writer/writer blocking, which is why the busy-timeout and 503 work mattered. |
| Remaining narrowness | Noted | Only busy `OperationalError` is mapped to 503; other `sqlite3.Error` classes still escape and drop the connection (M-03 residual). |
| Audit-table scaling | Noted | `verify_audit_chain` still `fetchall()`s the entire table, and every `record_audit_event` issues a `SELECT count(*)` (O(n) in SQLite, which has no stored row count). With the audit table bounded to ~86 bytes/row and the login rate limited, the growth rate is modest (~35 MB/day at the 120/min ceiling if an attacker sustained it), but the ADMIN audit page would then build ~150–250 MB of Python objects for a day of flooding. Recommend paginated verification plus a retention policy. |

---

## 13. Deployment Configuration Reassessment

### Demonstrated in repository configuration (verified by reading the checked-in examples, and machine-checked at preflight)

| Control | `clr-private-pilot.service.example` |
| --- | --- |
| Loopback bind | `ExecStart=… --host 127.0.0.1 --port 8766` (asserted at preflight) |
| Dedicated account | `User=clrpilot` / `Group=clrpilot` |
| Filesystem | `ProtectSystem=strict`, `ProtectHome=true`, `ReadWritePaths=/srv/clr/private_data`, `UMask=0077` |
| Privilege | `NoNewPrivileges=true`, `RestrictSUIDSGID=true`, `LockPersonality=true`, `MemoryDenyWriteExecute=true` |
| Kernel/namespace | `ProtectKernelTunables`, `ProtectKernelModules`, `ProtectControlGroups`, `PrivateTmp=true` |
| **New in this remediation** | `ProtectProc=invisible`, `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`, **`MemoryMax=512M`**, **`TasksMax=64`**, **`LimitNOFILE=4096`** |
| Secrets | none in the unit; secrets live under `CLR_PRIVATE_DATA/auth/` |

Caddy example: `admin 127.0.0.1:2019` (loopback admin API), `reverse_proxy 127.0.0.1:8766`, HSTS + `X-Content-Type-Options` + `X-Frame-Options: DENY` + `Referrer-Policy: no-referrer` + `-Server`, JSON access log to `{$PILOT_ACCESS_LOG}`. Forwarded headers are set by the proxy and **never read** by the application, so no spoofable client identity enters logic or the audit trail. The example was **not changed** by this remediation: there is still **no proxy-level rate limit**, and the app-level limiter is now the only bound (H-01 residual).

Two new deployment risks introduced *by* the hardening:

1. **`MemoryMax=512M`** is a new hard cap and its adequacy is dataset-dependent: report generation loads pandas/pyarrow/Parquet for a portfolio. On the sample fixtures this is irrelevant; on a real portfolio it may not be. This must be validated during the host rehearsal (§16), with the value raised rather than the service OOM-killed.
2. **`TasksMax=64`** bounds threads, which is a useful backstop for the unbounded-thread model of `ThreadingHTTPServer`, but a burst past the cap fails connection creation rather than returning 503. Acceptable; worth knowing.

### Verifiable only on the real host

DNS and certificate issuance/renewal for `climate.mangroveintel.com`; firewall proof that 8766 and 2019 are unreachable from the internet (by test, not by assumption); ownership and mode of `/srv/clr/private_data`; the log destination; `systemd-analyze security` output; off-host encrypted backup and a restore drilled from it; host patching; and the interaction of `MemoryMax=512M` with real report generation. The intended deployment does **not** assume any of these already exist, and none is asserted here.

---

## 14. Test Quality and False-PASS Review

### What ran

| Command | Result |
| --- | --- |
| `python -m pytest -q` on `17fdcb5` | **236 passed, 0 failed, 41 warnings in 54.68 s** (baseline `80f640c`: 203 passed, **2 failed** on Windows) |
| `python -m pytest -q tests/test_compound_local.py tests/test_private_pilot_rehearsal.py -v` | 20 passed |
| `python scripts/check_public_boundary.py` | passed (also run on the report itself before committing) |

### False-positive review

The original audit named four false-confidence conditions. Each was re-examined:

| Original false positive | Now |
| --- | --- |
| `backup_hash_matches_restore` compared the backup with its own copy | **Removed.** Replaced by a three-way logical state fingerprint (`source_before == source_after == backup`) whose meaningfulness I verified by mutating a copy and observing a different `state_sha256`. The new test `test_transient_catalog_snapshot_has_meaningful_state_verification` asserts the fingerprint actually differs for a mutated catalog. |
| The temp-cleanup assertion passed on Linux despite open handles | **Fixed at the source.** Connections close; the two Windows tests now pass, so the cleanup assertion is now true for the right reason. |
| `deployment_examples_valid` is a substring lint | **Still a substring lint** (I-05), now with five more substring checks. It remains inside the headline PASS. This is the one original false-confidence condition that was not removed — and it is the one the project's own documentation already warns about. |
| `test_gitignore_explicitly_blocks_private_workspace` asserted substrings rather than coverage | **Improved.** New tests assert real behaviour: `test_initialized_workspace_is_self_protecting_for_git` writes private files and asserts `git` ignores them; `test_custom_workspace_is_ignored_inside_an_unrelated_git_repo` does the same inside a throwaway repository; `test_boundary_guard_catches_forced_private_files` feeds the exact generated-artefact paths including a custom root. |

**New false-positive candidates I examined and resolved:**

- `test_sqlite_busy_returns_503_instead_of_dropping_request` **monkeypatches `verify_session`** to raise `OperationalError("database is locked")` rather than taking a real lock — i.e. it tests the handler wrapper, not the failure. It is a legitimate unit test of the wrapper, but on its own it would not prove the user-visible behaviour. I therefore reproduced the real-lock case independently (503 + `Retry-After` after 5.5 s), which is what the verdict in §4 M-03 rests on.
- `tests/test_portfolio.py` was flagged in the original audit for hand-writing the metric keys that `bounded_portfolio_findings` looks up. **This remains true**, and it matters only as long as L-13 is open (that helper is still tests-only). It is a latent false-positive test.
- `test_heat_lineage_read_failure_propagates` monkeypatches `latest_parquet` to raise, verifying propagation of a *reader* failure. It does not cover the new "empty lineage set" guard. Both branches are now exercised in aggregate (the guard by reading; the propagation by the test), but a test for the empty-set branch would be better.
- `test_dockerignore_excludes_private_workspace_and_recovery_artifacts` asserts that **strings are present in `.dockerignore`**, not that the patterns exclude a path. That is exactly the "static substring presence rather than actual behaviour" class, and it is why NEW-08 could hide: `**/manifests/**` is absent, yet the test still passes.

**Test-quality strengths worth recording.** The new tests are overwhelmingly behavioural: they run the real HTTP handler, take real SQLite locks, perform real database inserts, compare real state fingerprints, and assert *negative* controls (catalog-only restore must fail; the boundary guard must not flag methodology names; a mutated catalog must produce a different fingerprint). The equalisation test asserts iteration counts rather than wall-clock time, which is the correct way to test that mechanism. The anchor tests assert the tampering *reason*, not merely `valid == False`.

---

## 15. Residual Risks Appropriate to Defer

The following are open in code or unaddressed in configuration and are, in my assessment, **proportionate deferrals for a 2–5 user pilot**. They are listed explicitly so that deferral is a decision rather than an oversight.

| Item | Why it is proportionate to defer |
| --- | --- |
| L-05 — CSP `'unsafe-inline'` | Escaping in the report renderer is verified and complete; `default-src 'none'` blocks exfiltration; there is no known injection. Fixing it requires nonces/hashes for a handful of inline handlers. |
| L-06 — contract schemas unvalidated | Documentation-grade gap; no drift was found in sampled output. |
| L-07 — no idle timeout / `__Host-` prefix | `SameSite=Strict`, `HttpOnly`, `Secure` and a 60-minute TTL already bound exposure; the pilot has few users on managed devices. |
| L-09 — global audit events visible to tenant ADMINs | Leaks only event IDs, action names, timestamps and target UUIDs (no `detail_json`); every tenant ADMIN is a named, trusted pilot participant. |
| L-11 … L-15 — latent analytical defects | No production caller exists; the correct implementations are used elsewhere. Must be fixed before any caller adopts them. |
| I-01, I-02, I-03, I-05 | Documentation/monitoring hygiene. I-02 (the `git check-ignore` trap) is worth a one-line deletion. |
| MFA / SSO, browser-based user administration, external session store, centralized log shipping, hardware-backed keys, portfolio-snapshot versioning | Explicitly deferred by the project's own pilot scope, and appropriately so for a named-user pilot. |
| NEW-07 (tar member size), NEW-11 (fully-`NaN` month counts), NEW-13 (log status), NEW-14 (non-interactive backups) | Low or informational; no reachable path from the internet; each is a small, well-scoped fix. |

**Not** appropriate to defer: NEW-01 (an outage state with no documented repair), NEW-02 (an unaudited privileged change), the H-01 rate-limit calibration, and the NEW-14 operator decision (either commit to manual backups or provide an automated path).

---

## 16. Host-Side Checks Still Required

Nothing in this list can be verified from the repository, and none of it is assumed to exist.

**Network and TLS**
1. `climate.mangroveintel.com` resolves to the pilot host; a valid certificate is issued **and auto-renewing**.
2. Only 443 is reachable from the internet; **8766 and 2019 are proven unreachable from an external host by test**, not by absence of a proxy rule.
3. Confirm the `includeSubDomains` HSTS commitment is intended for every subdomain of the pilot host.

**Filesystem and service**
4. Private workspace at `/srv/clr/private_data`, owned by `clrpilot`, mode 0700, **outside** the repository.
5. `journalctl`/`systemd-analyze security` review of the actual unit; confirm `ProtectProc`, `RestrictAddressFamilies`, `MemoryMax`, `TasksMax`, `LimitNOFILE` are active in the running unit.
6. **Validate `MemoryMax=512M` against a real report generation** (portfolio-scope report over the largest expected Parquet); raise it if the service is killed.
7. `PILOT_ACCESS_LOG` outside any web root, service-owned, rotating; confirm no secrets or coordinates appear in a sample of lines.

**Identity and data**
8. Create the named users per tenant; generate ≥16-character passwords in a password manager; verify each account's tenant membership by signing in.
9. **Re-run `scripts/init_private_pilot_access.py` if the workspace predates this commit** (it creates `auth/audit_head_anchor.json`); confirm `private-pilot-rehearse` reaches PASS.
10. Run `manage_private_workspace_users.py verify-audit` **after** setup and archive its output off-host.
11. Demonstrate tenant isolation live: cross-tenant report path, cross-tenant run ID, cross-tenant portfolio ID — each denied, each denial present in the audit log. Confirm M-01's fix by attempting a `.`/`..` tenant login (expect a generic failure).
12. Demonstrate roles: VIEWER cannot generate; ANALYST cannot see audit; ADMIN can. Confirm each denial is audited.

**Backup and recovery**
13. Decide and record the backup mechanism (operator-run interactive backups, or a secret-store-fed wrapper) — the policy's daily cadence is not achievable with the current interactive CLI.
14. Create an encrypted `.clrbackup` to an off-host destination; **restore it into a clean directory on a different host** and confirm `status: PASS` and a valid audit chain.
15. Drill the failure/repair behaviour: with the pilot stopped, corrupt or delete `auth/audit_head_anchor.json` on a *copy* and confirm the operator can follow the documented repair procedure (currently: delete the anchor and re-run init, accepting that this re-anchors to the current DB — see NEW-01).
16. Verify the audit chain **after** the restore drill, and re-verify a sample of registered raw artefact SHA-256 values.

**Operations**
17. Confirm DNS/firewall/log/patching ownership and an alerting path for disk space and for a service restart loop.
18. Review one day of Caddy logs for unexpected sensitive content (coordinates, tokens, tenant identifiers in URLs) — the application log strips query strings, but Caddy's does not.
19. Decide the compound-run validation: execute `make -f Makefile.local compound-run` against real data and confirm `SUCCESS` (H-03's fix is verified at the unit level; a full real-data run is the remaining end-to-end evidence).

---

## 17. Outside-Pilot Readiness Checklist

Every line is concrete and verifiable. Copy this into the runbook.

**Code / configuration (verifiable in this repository)**

- [ ] Login rate limit recalibrated: either lower `DEFAULT_LOGIN_GLOBAL_ATTEMPTS` so that `attempts × per-attempt seconds` is a small fraction of host CPU (today 120/min ≈ 79 CPU-seconds/min on this measurement host), or add a proxy-level per-IP limit with `trusted_proxies` configured.
- [ ] Audit-append failure has a documented, tested outcome: either auto-heal for the "DB one ahead" case (NEW-01) **or** a written repair procedure in the runbook, with the anchor-reset action itself audited.
- [ ] A test asserts that a privileged mutation cannot persist when its audit append fails (NEW-02).
- [ ] Cross-process audit appends are either serialised or retried (NEW-03), and the runbook says whether the CLI may be used while the pilot is live.
- [ ] `_LoginRateLimiter.key` canonicalises the tenant (NEW-04) and a test pins it.
- [ ] `set_user_password` enforces `MAX_PASSWORD_CHARS` (NEW-05).
- [ ] `.dockerignore` covers a custom-root workspace's `manifests/`, `normalized/`, `indicators/`, `auth/`, `outputs/`, `tmp/` (NEW-08), and the `.dockerignore` test asserts behaviour rather than substring presence.
- [ ] `FORBIDDEN_PATH_FRAGMENTS` is derived from `local_store.WORKSPACE_DIRS` with a test that fails when a workspace directory is uncovered (NEW-09).
- [ ] `.gitignore` blank line removed (I-02).
- [ ] `pytest -q` green on Linux (the target) **and** on the developer's Windows workstation.

**Host and infrastructure**

- [ ] Dedicated non-login `clrpilot` account; workspace at `/srv/clr/private_data`, 0700, outside the repository.
- [ ] 443 reachable; 8766 and 2019 proven unreachable from outside **by test**.
- [ ] `climate.mangroveintel.com` resolves; certificate valid and renewing; HSTS scope confirmed.
- [ ] Unit hardening active in the running service (verify, do not assume): `ProtectSystem=strict`, `ReadWritePaths=/srv/clr/private_data`, `NoNewPrivileges`, `PrivateTmp`, `ProtectProc=invisible`, `RestrictAddressFamilies`, `UMask=0077`, `MemoryMax`, `TasksMax`, `LimitNOFILE`.
- [ ] `MemoryMax` validated against a real report generation.
- [ ] Host clock synchronised (session expiry and audit timestamps depend on it); disk-space and restart-loop alerting configured.
- [ ] Host patched; dependency scan run against `pyproject.toml` / `requirements-local.txt`.

**Identity, audit and recovery**

- [ ] Named users created per tenant; passwords ≥16 characters, unique, stored in a password manager.
- [ ] `init_private_pilot_access.py` re-run (anchor present); `private-pilot-rehearse` reaches PASS; `verify-audit` archived off-host.
- [ ] Tenant-isolation demonstration (report path, run ID, portfolio ID, dot-segment tenant) with denials visible in the audit log.
- [ ] Role demonstration (VIEWER/ANALYST/ADMIN) with denials audited.
- [ ] One governed report generated end-to-end; selection/hash manifest checked.
- [ ] If compound evidence is in scope: a real `compound-run` reaches `SUCCESS` and the three shared-bottleneck metrics appear.
- [ ] Encrypted bundle created off-host; restore drilled on a clean host; `PASS` + valid chain; sample artefact hashes re-verified.
- [ ] Backup mechanism decided and written down (see NEW-14).
- [ ] Caddy and application logs reviewed for unexpected sensitive content.
- [ ] Material findings from this audit addressed or **explicitly accepted in writing** by the project owner, with the residual risk named.

---

## 18. Recommended Next Actions

Ordered by risk reduction, then dependency. **Nothing here proposes rebuilding correct architecture**; the first four items are small, well-scoped changes to code that is otherwise sound.

| Order | Action | Effort | Why this position |
| --- | --- | --- | --- |
| 1 | **Define and implement the anchor repair path (NEW-01)** — auto-heal the "DB one ahead" case inside `record_audit_event`, and provide an audited `--reanchor` operator action; document it in `HOSTED_PRIVATE_PILOT_SECURITY.md` and the runbook | ~3 h | The only new finding whose failure mode is a total, confusing outage; it also protects the evidentiary value of the chain from its own repair step |
| 2 | **Recalibrate the login rate limit (H-01 residual)** — set the global ceiling from measured per-attempt CPU (or add a proxy per-IP limit); consider a per-account short lockout rather than a hard 5-minute one | ~2 h | The single remaining unauthenticated resource control; 79 CPU-seconds/min ≈ 66 % of a 2-vCPU host |
| 3 | **Make privileged mutations atomic with their audit record (NEW-02)** — mutation + audit insert in one transaction | ~3 h | An unaudited privilege change is the one thing an evidentiary log must not permit |
| 4 | **Serialise or retry cross-process audit appends (NEW-03)** — file lock or bounded retry; state the CLI/live-pilot rule in the runbook | ~2 h | Removes spurious authentication failures during normal operator use |
| 5 | **Move the audit anchor off-host (H-02 residual)** — append `{event_count, head_hash}` to the proxy log, the journal, or an operator-held file outside the workspace, and make `verify-audit` consult it | ~4 h | Converts the anchor from "two files in one trust domain" into a genuine second medium; this is the step that would let H-02 be called closed |
| 6 | **Fix the small verified defects** — NEW-04 (limiter key), NEW-05 (password bound), NEW-06 (narrow the report-path exception), NEW-10 (conservative default), NEW-11 (null counts for an empty month), NEW-13 (log the status), I-02 (delete the blank line) | ~2 h total | Each is a one-line-to-one-function change with a clear test |
| 7 | **Derive the boundary guards from the layout** — `FORBIDDEN_PATH_FRAGMENTS` from `WORKSPACE_DIRS`; align `.dockerignore` and the basename lists; add the workspace-coverage test (NEW-08, NEW-09, M-09 residual) | ~3 h | Prevents the drift that has already started, and closes the last boundary gaps |
| 8 | **Add content inspection to the boundary checker** — flag ≥4-decimal coordinate pairs and non-`SYNTH*` values in tracked fixture/documentation paths | ~2 h | The only class of accident the name-based guard cannot see |
| 9 | **Add pagination/retention to audit verification** (H-01 residual, §12) | ~3 h | Keeps the ADMIN audit page bounded as the table grows |
| 10 | **Fix the latent analytical helpers (L-11 … L-15) before any production caller adopts them** | ~4 h | They are currently unreachable, which is exactly why they should be fixed while they are cheap |
| 11 | **L-03 (cap `indicator_run` count), L-04 (require an `Origin` or token on login), L-06 (schema validation), L-07 (idle timeout)** | ~4 h | Authenticated-surface hygiene and hardening |
| 12 | **Document the upgrade step for pre-anchor workspaces (NEW-12)** and decide the backup automation question (NEW-14) | ~1 h | Removes two operational traps before the host work begins |
| 13 | Complete §16 (host-side) and §17 (checklist), then invite the first outside user | as scheduled | The pilot gate itself |

**Deliberate non-actions.** No change is proposed to the analytical engine, the tenant/role model, the session design, the report contract, the encrypted-bundle format, or the loopback-plus-TLS topology. Those are correct as they stand, and the original audit's concern was never that the architecture was wrong — it was that specific guards were missing, bounded poorly, or unverified. The remediation closed most of them.

---

## Appendix A — Independent Model Review (DeepSeek): Verdicts, Challenges and Resolutions

The review brief asked for DeepSeek to act as the primary analysis agent with Claude Code orchestrating, verifying and challenging. That is how the review was conducted, and the disagreements are recorded here in full because they are part of the evidence.

### How DeepSeek was used

- **Model:** `deepseek-reasoner` for the first pass; `deepseek-chat` for the structured second pass (see the limitation below).
- **Inputs:** four prompt bundles, each containing the relevant remediation diff (`git diff 80f640c..17fdcb5 -- <paths>`, `+` lines being the new implementation) plus the verbatim text of the relevant original findings, with an explicit instruction to quote code, flag tautological guards, and assign one status per finding. Bundle A: auth/session/audit core (11 findings). Bundle B: boundary/backup/recovery (6). Bundle C: analytical governance (9). Bundle D: tenant isolation/legacy shell (3).
- **Verification:** every DeepSeek verdict and every new issue it raised was checked against the source and, where possible, by execution (the reproductions in §4, §6, §14 and the table below). Where DeepSeek lacked a file it said "not determinable from supplied diff", and I resolved those by supplying the evidence myself.

**Limitation, recorded honestly.** The first dispatch used `deepseek-reasoner` with `max_tokens: 8000`; the reasoning trace consumed the entire budget and **all four responses were returned with an empty final answer**. The reasoning traces were still usable and independently identified several items (the crash window, the anchor's co-location, the cross-process race), but no structured verdicts were produced. The second dispatch used `deepseek-chat` with a strict output contract and produced complete verdict tables. Anyone repeating this should use `deepseek-chat` for structured verdicts, or raise `max_tokens` substantially for the reasoner.

### Where DeepSeek's verdict was adopted

H-01 partial (with my stronger CPU quantification), M-03 partial, M-04 "not determinable" resolved in the project's favour by my grep, M-07 partial, M-09 partial, L-02 closed, L-03 open, L-04 partial, L-05 open, L-07 partial, L-09 open, L-10 partial, L-11/L-12/L-13 open, and its new issues NEW-01/NEW-03/NEW-07/NEW-08/NEW-09/NEW-10/NEW-12/NEW-13/NEW-14 (as renumbered here).

### Where DeepSeek's verdict or claim was overridden

| DeepSeek claim | Resolution (with evidence) |
| --- | --- |
| **H-02 = CLOSED** (bundle A/B/D) | **Overridden to PARTIALLY CLOSED.** DeepSeek's own GAP paragraph argues the anchor is co-located with the key and that the original recommendation asked for a separate medium — which is the definition of partial. My reproduction adds the decisive gap: deleting the anchor and re-running init re-bootstraps to the current DB state and makes the truncation invisible (`valid=True`, `event_count=0`). |
| **M-02 = PARTIALLY CLOSED**, because "No test in the diff asserts equal KDF call counts" | **Overridden to CLOSED.** The tests were not supplied to DeepSeek; `tests/test_private_workspace_access.py::test_unknown_and_known_accounts_both_perform_password_hash_work` asserts `sum(iterations) == 100_000` for all three paths, and I measured end-to-end parity (672 ms vs 666 ms). The residual (sub-millisecond branch differences) is real but far smaller than a "partial" verdict implies. |
| **M-10 = PARTIALLY CLOSED** (missing `heat_valid_day_count`, changed `heat_day_count` semantics) | **Overridden to CLOSED.** The finding's defect — an understated hot-day count published as `OK` — is fixed, and the repo's own test asserts the *decisive* downstream consequence: the annual compound metric becomes `None` with `INCOMPLETE_YEAR_INPUT`. The missing transparency field and the field-semantics change are real but are notes, not the finding. |
| **M-11 = CLOSED but "a tautology against the actual evidence"** | **Partially accepted.** The status is CLOSED (both branches verified, and the production caller passes the flag correctly — a fact DeepSeek could not see). The tautology criticism is fair as a *robustness* point and is carried as NEW-10 (optimistic default). |
| **M-01 = "closed only contractually, not verified"** | **Overridden to CLOSED (verified).** I executed the canonicaliser, the strict-child helper and the HTTP paths. |
| **M-08's documentation gap** ("deprecation notices are not present in the diff") | **Overridden.** `deploy/private_pilot/README.md:28`, `docs/PRIVATE_WORKSPACE_APP.md:3`, `docs/HOSTED_PRIVATE_PILOT_SECURITY.md:274-278` and `Makefile.local` all carry the prohibition; DeepSeek had only the code diff. The one surviving sub-item is the missing token-cross-acceptance test. |
| **NEW-DS-2 (bundle A): "anchor validation is skipped on failure paths … masks which invariant broke" — severity High** | **Dismissed.** The early returns still report `valid: False`; a chain-hash mismatch is a stronger signal than a count mismatch, and no caller's decision changes. Reporting it as High would have been inflation. |
| **NEW-DS-3 (bundle A): a corrupted anchor is "indistinguishable from a lost one"** | **Dismissed.** `record_audit_event` interpolates the reason into the message (`f"Audit anchor is not valid: {anchor.get('reason')}"`), and `_read_audit_anchor` returns distinct reasons (`AUDIT_ANCHOR_MISSING`, `AUDIT_ANCHOR_INVALID`, `AUDIT_ANCHOR_MAC_MISMATCH`). |
| **NEW-DS-4 (bundle A): oversized payloads bypass the rate limiter — Medium** | **Downgraded to part of the H-01 residual (Low).** Correct as a mechanism (the length check precedes `login_limiter.allow`), but on that path no PBKDF2 runs and no audit row is written, so the guard's purpose (bounding KDF work and audit growth) is not defeated — only connection churn is permitted, bounded by `TasksMax`. |
| **NEW-DS-8 (bundle A): truncating oversized audit detail is a "Medium data-retention regression"** | **Dismissed as unreachable.** `_sanitize_audit_value` caps lists at 20 items and strings at 256 characters *before* the 4096-byte test, so the largest realistic caller (`/generate` with many run IDs) produces well under 1 KB; I measured the largest row written during the entire review at 86 bytes. |
| **REGRESSION (bundle D): "`MAX_PASSWORD_CHARS` truncation is applied in `_dummy_password_work` but not in the real `_password_digest` call … an observed asymmetry"** | **Dismissed as unreachable.** `authenticate_user` returns early for any input longer than `MAX_PASSWORD_CHARS` (line 791), so the real path never sees a truncated-input mismatch. The *related* real defect (an over-long password being settable) is carried as NEW-05 — found from this thread. |
| **NEW-DS-7 (bundle D): the cross-process race "leaves `event_count`/`head_hash` mismatched by one event and brick[s] subsequent writes"** | **Impact corrected.** The second writer fails the in-transaction count/head check *before* inserting, so no desynchronisation occurs. Reproduced: 18 attempts across 3 processes → 12 rejected, and the final chain verified (`checked_events=7`, `anchor_event_count=7`, `valid=True`). Carried as NEW-03 with the corrected impact (spurious failures, not corruption). |
| **NEW-DS-5 (bundle D): the dummy-work restructuring leaves "a remote timing oracle"** | **Dismissed by measurement.** Medians 672 ms vs 666 ms. |

### Where DeepSeek found something I had not

- **NEW-02 was found by neither** — that one is mine, from tracing the mutation-then-audit ordering while verifying NEW-01.
- **NEW-09** (boundary guard drift: `.gitignore` globs vs the checker's child enumeration) came from DeepSeek bundle B and I verified it by reading both files.
- **NEW-07** (unbounded tar member size) came from DeepSeek bundle B; I confirmed the read-after-allowlist ordering in the source.
- **NEW-13**'s underlying claim ("the 503 branch is not logged") was **wrong**, but investigating it produced a real and more precise observation: the status code *is* emitted by `log_request` and then stripped by `log_message`'s query-string truncation, so failures on query-bearing paths are invisible in the application log. A wrong claim led to a correct finding, which is worth recording.

---

## Appendix B — Reproductions Performed (summary)

| # | Target | Method | Result |
| --- | --- | --- | --- |
| R1 | H-03 | `cross_asset_summary` with the original fixture shape, then the production denominator guard | 9/9 rows pass (was 3 failures) |
| R2 | M-11 | Both branches of `shared_edge_evidence_available` | Unavailable → `NaN` + `NO_ROUTE_EDGE_EVIDENCE`; available-and-empty → `0.0` + `OK` |
| R3 | M-01 | `canonical_tenant_key` over 9 candidate keys | `.`/`..`/`...`/`a.`/`...a`/padded keys rejected; normal keys accepted |
| R4 | M-04 | `with connect_catalog(...)` then reuse | `ProgrammingError` — connection closed |
| R5 | H-02 | Append 4 events, delete the newest, verify | `valid=False`, `EVENT_COUNT_MISMATCH`, `checked=3`, `anchored=4` |
| R6 | M-04 regression | `record_audit_event` return value after close | `audit_event_id = 1` — no regression |
| R7 | NEW-01 | Simulated torn write; then delete anchor + re-init | Append blocked (`ValueError`); re-init re-anchored to the current DB and reported `valid=True` |
| R8 | NEW-02 | Corrupt anchor, then `set_user_active(is_active=False)` | Mutation persisted (`1 → 0`) with **0** `USER_DISABLED` audit rows |
| R9 | Isolation | HTTP: 2 tenants, planted reports, traversal and secret paths | Cross-tenant 404; own 200; dashboard scoped; traversal 404; secret path 404 |
| R10 | NEW-04 | 4 login attempts against one account with tenant spelling variants (limit 3) | 401 ×4, **no 429** |
| R11 | M-03 | Real `BEGIN IMMEDIATE` then `GET /report` | **503 + `Retry-After: 1`** in 5.5 s |
| R11b | M-03 side-effect | Real lock then authenticated `GET /` | **200 in 0.0 s** — reads no longer write |
| R12 | H-01 | 129-char username login | 401, **no new audit row**; max observed `detail_json` = 86 bytes |
| R13 | M-02 | Fresh server, 310k iterations, unknown vs existing user | 672 ms vs 666 ms medians |
| R14 | M-06 | Bundle round-trip, wrong passphrase, bit-flip, non-empty target, catalog-only restore | PASS with all 7 checks; wrong passphrase and tamper rejected; target guard holds; `AUDIT_SECRET_MISSING` with no key minted |
| R15 | M-08 | `serve_private_workspace` without opt-in | `RuntimeError` |
| R16 | M-05 | Workspace inside a real git repo with private files present | `git status` empty; init at a repo root refused |
| R17 | L-01 | `tenant_report_dir` with case variants; file written under `TENANT_A` read via `tenant_a` | Readable — still open (Windows) |
| R18 | NEW-03 | 3 processes × 6 concurrent audit appends | 6 ok, 12 `ValueError`; chain remained valid |
| R19 | NEW-05 | `set_user_password` 2000 chars, then login | Accepted; login fails with the exact password **and** its 1024-char prefix |
| R20 | NEW-13 | 503 on a query-bearing path, app log captured | `[pilot] 127.0.0.1 "GET /report` — status stripped |
| R21 | H-01 calibration | 40 attempts, distinct usernames, shipped limits | 401 ×40, median 656 ms → ≈79 CPU-s/min |
| R22 | Test suite | `python -m pytest -q` | **236 passed, 0 failed** |

---

## Appendix C — Review Limitations

1. **Static review plus targeted dynamic reproduction, not a penetration test of a running pilot.** No host, DNS record, certificate or proxy exists to test; all dynamic work ran in-process on a Windows 11 / CPython 3.11 workstation against synthetic fixtures in OS temp directories.
2. **No real private data was available**, by design. Consequently the full `run_compound_cross_asset_local.py` pipeline could not be executed against real ERA5/CHIRPS/route Parquet; the H-03 fix is verified at the summary/insert level and by the repository's own integration-style tests, and the remaining end-to-end run is listed as a host-side check (§16 item 19).
3. **Absolute timing figures are host-dependent.** PBKDF2 at 310 000 iterations measured **349–632 ms** across runs on this machine, versus 140 ms during the original audit — a 4.5× spread that reflects machine load, not code change. The H-01 arithmetic is therefore stated as a *ratio* against host CPU capacity (~66 % of a 2-vCPU host at the shipped cap, from the 656 ms median), and the recommendation is to calibrate against the real host's measurement.
4. **Dependencies were not audited.** No CVE/SBOM scan was performed; `cryptography>=43` was confirmed as a declared dependency in `pyproject.toml` and is installed here, but its version provenance was not assessed.
5. **Docker was unavailable**, so the `.dockerignore` finding rests on pattern semantics rather than an executed build (stated explicitly in NEW-08).
6. **The DeepSeek first pass returned no final verdicts** (reasoning-token exhaustion, documented in Appendix A). The second pass produced complete verdicts. DeepSeek saw code diffs and finding text only — not the current full files, not the tests, and not the docs — which is the source of every "not determinable" caveat and of the four verdicts I overrode. Where I overrode it, the reason and the evidence are recorded.
7. **Scope:** the analytical science, the climate/hazard methodology and the geocoding quality were out of scope beyond the governance controls listed in §11; OSM/Geofabrik licensing, the GitHub Actions pinning strategy (`@v4` tags rather than SHAs) and the `Dockerfile.live` base image were not assessed.
8. **This report is not a certification.** It states what was verified, what was not, and what remains open; the project owner decides whether the residual risk is acceptable. Per the project's own review convention, no binary secure/not-secure judgement is offered.
