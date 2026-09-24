# External Review Prompt — Private Climate Intelligence Pilot

Review the repository as a security auditor. Do not redesign the analytical product and do not make broad style comments unless they affect security.

The system is a private climate/location-risk intelligence pilot. Public GitHub contains code, schemas, methodology, tests and synthetic examples. Real assets, coordinates, portfolios, raw data, credentials, access records and generated client reports remain in a gitignored private workspace.

The intended hosted topology is:

```
Internet client
  -> HTTPS/TLS reverse proxy
  -> loopback-only backend at 127.0.0.1:8766
  -> private SQLite/Parquet workspace
```

The backend is not intended to bind directly to a public interface.

Named users have tenant-specific roles:

- VIEWER: view existing tenant reports;
- ANALYST: view and generate tenant reports;
- ADMIN: analyst permissions plus tenant audit visibility; access administration is currently CLI-only.

Sessions are opaque random tokens; only token hashes are stored server-side. Password/role/membership changes revoke affected sessions. Audit events are HMAC chained and should be described as tamper-evident, not immutable.

Please read `docs/EXTERNAL_SECURITY_REVIEW.md` first and use it as the review scope.

Important constraints:

- Do not recommend moving real/private data into GitHub.
- Do not weaken tenant, run/vintage, lineage, denominator, geocoding or fail-closed controls.
- Do not introduce automatic composite climate-risk scores or hazard-to-loss inference.
- Treat the checked-in Caddy/systemd files as examples; identify assumptions that must be verified on the real host.
- Distinguish exploitable findings from defense-in-depth recommendations.
- For every finding, provide file/function/location, attack precondition, exploitation path, impact, deployment reachability, specific fix, and regression test.

Return a full Markdown report, not a summary.

Use severity levels Critical / High / Medium / Low / Informational as defined in `docs/EXTERNAL_SECURITY_REVIEW.md`.

Also report controls you reviewed that appear sound, so the audit does not become a list of speculative problems only.
