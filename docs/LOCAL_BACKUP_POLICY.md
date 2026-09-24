# Local Private Data Backup & Versioning Policy

## Principle

Git is not the backup system for private data.

The local private workspace needs its own backup process because all real data are intentionally excluded from GitHub.

## Hosted-pilot recovery bundle

The operational private-pilot backup is **not** a bare SQLite file.

Create an encrypted recovery bundle with:

```bash
python scripts/backup_private_catalog.py
```

The command prompts twice for a recovery passphrase and writes a `.clrbackup` file. It does not accept the passphrase as a command-line argument.

The authenticated encrypted bundle contains:

- a consistent SQLite catalog snapshot;
- `auth/audit_chain_secret.bin`;
- `auth/audit_head_anchor.json`;
- a recovery manifest containing the governed catalog-state fingerprint and audit head/count.

Encryption is AES-256-GCM. The encryption key is derived from the supplied passphrase using PBKDF2-HMAC-SHA256 with a per-bundle random salt.

The passphrase is **not** stored in the bundle, repository, SQLite catalog, or manifest.

For an off-host destination:

```bash
python scripts/backup_private_catalog.py --destination /secure/off-host/location
```

A raw SQLite snapshot still exists internally as a transient implementation step during backup/rehearsal, but the operational CLI does not leave that snapshot behind.

Restore only into a new empty directory:

```bash
python scripts/restore_private_pilot_backup.py \
  --bundle /secure/off-host/private_pilot_<timestamp>.clrbackup \
  --target /secure/empty/recovery-test
```

The restore verifies:

- AES-GCM authentication;
- SQLite integrity and foreign keys;
- catalog snapshot fingerprint;
- audit-key hash;
- audit-anchor hash;
- audit event count and head;
- complete audit-chain verification against the restored anchor.

Recommended cadence:
- before/after schema migrations;
- before a major source refresh;
- after a successful production ingestion batch;
- at least daily while actively changing the private catalog.


## Raw snapshots

Registered raw snapshots are immutable.

A raw file should never be edited in place after its SHA-256 has been registered. If the provider republishes or changes the file, store the new bytes as a new artifact/vintage.

## Parquet

Derived Parquet should be reproducible from:
- source-artifact hashes;
- processing-run ID;
- pipeline version/Git commit;
- method parameters.

Do not manually edit production Parquet files.

## Hosted-pilot access and audit state

The SQLite catalog contains named-user password hashes/salts, tenant roles, session hashes/revocation state, and the audit-event chain.

Two files outside SQLite are required to recover the evidentiary audit state:

- `auth/audit_chain_secret.bin`;
- `auth/audit_head_anchor.json`.

The operational encrypted recovery bundle includes both.

A catalog-only restore is intentionally treated as incomplete: audit verification must fail without the matching audit key. The automated rehearsal tests that negative control before testing a successful encrypted-bundle restore.

The audit-head anchor detects SQLite-only tail truncation by comparing the current database event count and head hash with a separately HMAC-protected file. It improves tamper evidence but is not immutable logging. An operator with write access to both the database and the audit key/anchor remains inside the same trust domain.

For a production service, additionally retain audit records or head anchors in a separately protected append-only/off-host destination.

Do not back up plaintext session tokens because the server never stores them.


## Second copy

Maintain at least one additional encrypted copy of the private workspace outside the primary working disk.

Suitable later options include:
- encrypted external drive;
- private S3-compatible object storage;
- encrypted cloud backup.

Customer/confidential data should follow the relevant agreement and retention rules.

## Restore test

Periodically test:
1. restoring the SQLite backup;
2. resolving relative raw/Parquet paths;
3. verifying a sample of stored SHA-256 values;
4. rerunning at least one indicator from its recorded source artifact and method version.

A backup that has never been restored is not considered validated.
