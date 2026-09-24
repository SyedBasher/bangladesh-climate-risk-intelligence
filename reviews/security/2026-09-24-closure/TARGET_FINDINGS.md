# Closure Re-Audit Target Findings

Expected review SHA:

`23ee198ad2c6897d8fcc5ea451f3add91f4b2ea8`

This matrix defines the closure questions. The reviewer must verify current code and execution rather than repeat the remediation claim.

| ID | Previous issue | Remediation claim to verify | Closure evidence required |
| --- | --- | --- | --- |
| NEW-01 | Audit DB commit could succeed before external anchor write, leaving a permanent split-brain and unsafe repair path | Signed pending-anchor journal plus explicit ADMIN-attributed re-anchor | Simulated post-commit promotion failure recovers; pre-commit pending state is discarded; ambiguous state fails closed; missing anchor over non-empty history is not silently bootstrapped; explicit reset is audited |
| NEW-02 | Privileged access mutation could persist even if later audit append failed | Privileged mutation and audit insert share one SQLite transaction | Forced audit failure leaves user/membership/password/active state unchanged and no unaudited privileged mutation |
| NEW-03 | Thread lock did not serialize separate processes | OS file lock + SQLite transaction serialize audit writers | Real multi-process writers all succeed and final chain/anchor verify |
| NEW-06 | Audit failures could appear as login failure, report 404 or dropped response | `AuditStateError` reaches HTTP boundary and maps to controlled 503 | Broken audit state produces 503-class response on relevant request paths without false 401/404 diagnosis |
| H-01 residual | Global login ceiling allowed excessive PBKDF2 CPU consumption | Conservative 20/min process ceiling plus real-host benchmark/override | Default enforced before PBKDF2; host calibration tool uses current KDF parameters and sound arithmetic; final real-host calibration remains a host gate |
| NEW-04 | Per-account limiter could be bypassed by tenant case/whitespace variants | Tenant canonicalization/casefolding for limiter key; invalid tenant bucket | Original variants throttle the same account; malformed variants cannot mint unlimited buckets |
| NEW-05 | Password reset accepted >1024 chars, creating an account that could no longer authenticate | Reset path enforces same max as create/login | 1025-char reset rejected and prior valid password still authenticates |
| NEW-08 | Docker context could include text/HTML/JSON from a custom-root private workspace | Recursive custom-root workspace exclusions | Representative custom-root private paths are excluded under Docker-ignore semantics |
| NEW-09 | Boundary checker duplicated workspace child paths and could drift from canonical layout | Guard fragments derived from `WORKSPACE_DIRS` | Current canonical directories all covered; a synthetic future workspace directory is picked up from layout without second manual list |
| NEW-10 | Shared-edge evidence flag defaulted to optimistic `True` | Evidence availability is a required argument | Omitting it cannot produce valid zero metrics |
| NEW-11 | Fully null heat month emitted zero hot-day counts | Zero-valid-day month emits null hot-day counts | All-null month has null >35/>38/max fields, non-OK quality and fail-closed annual output |
| NEW-13 | Query redaction removed HTTP status from application logs | Redact request-target query only | Query identifiers absent while HTTP status remains |
| I-02 | Empty `.gitignore` line could make verbose verification look like an ignore match | No blank ignore rule; explicit custom-root rules | `git check-ignore -v` attributes private path to explicit rule |
| L-03 | Unlimited `indicator_run` values could fan out into thousands of DB lookups | Maximum 64 runs at HTTP and adapter layers | 65 runs rejected through both entry paths before expensive fanout |

## Regression checks

The closure reviewer should also re-verify that the two remediation tranches did not weaken:

- tenant isolation;
- path confinement;
- session revocation;
- loopback binding;
- secure-cookie defaults;
- public/private data boundary;
- explicit run/vintage selection;
- provenance and denominators;
- no composite score;
- no automatic hazard-to-loss inference.

## Explicitly host-dependent

The following should normally remain **HOST-DEPENDENT**, not be forced into CLOSED/STILL OPEN based only on the repository:

- real VPS PBKDF2 timing and final `CLR_LOGIN_GLOBAL_ATTEMPTS`;
- DNS/TLS certificate chain for `climate.mangroveintel.com`;
- firewall and cloud security-group exposure;
- Caddy process/log permissions;
- service-account filesystem ownership;
- off-host append-only audit evidence;
- encrypted off-host backup retention and clean-host restore;
- actual proxy/network rate limiting.

The review should identify a repository blocker only when current code/config/test evidence supports one.
