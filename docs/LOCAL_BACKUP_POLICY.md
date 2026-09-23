# Local Private Data Backup & Versioning Policy

## Principle

Git is not the backup system for private data.

The local private workspace needs its own backup process because all real data are intentionally excluded from GitHub.

## SQLite catalog

Create a consistent catalog backup with:

```bash
python scripts/backup_private_catalog.py
```

The command uses SQLite's backup API and writes:

```
private_data/backups/catalog/climate_risk_<UTC_TIMESTAMP>.sqlite
private_data/backups/catalog/climate_risk_<UTC_TIMESTAMP>.manifest.json
```

The manifest includes SHA-256 and byte size.

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
