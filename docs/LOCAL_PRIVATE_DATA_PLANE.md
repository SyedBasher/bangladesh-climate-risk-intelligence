# Local Private Data Plane 0.1

The current operating protocol is:

```
PUBLIC GITHUB
code + parsers + tests + schemas + methodology + CI
        |
        v
PRIVATE LOCAL DATA
SQLite + Parquet + immutable/raw source snapshots
        |
        v later
HOSTED DATABASE
Supabase / Neon / another PostgreSQL provider
```

The hosted database is a later deployment layer, not a prerequisite for research and pipeline development.

## Workspace

Initialize:

```bash
python scripts/init_private_workspace.py
```

or choose another private root:

```bash
python scripts/init_private_workspace.py --root /secure/path/climate-risk
```

The environment variable `CLR_PRIVATE_DATA` may also define the root.

Default layout:

```
private_data/
├── auth/
│   ├── workspace_auth.json
│   └── session_secret.bin
├── catalog/
│   └── climate_risk.sqlite
├── raw/
│   ├── era5_land/
│   ├── chirps/
│   ├── jrc_flood/
│   ├── gfm/
│   ├── ffwc/
│   ├── dem/
│   └── osm/
├── normalized/
│   ├── assets/
│   ├── admin/
│   ├── climate/
│   ├── roads/
│   └── events/
├── indicators/
│   ├── asset/
│   ├── admin/
│   ├── portfolio/
│   └── logistics/
├── manifests/
│   └── source_vintages/
├── outputs/
│   ├── reports/
│   └── qa/
├── backups/
│   └── catalog/
└── tmp/
```

The entire workspace is gitignored.

## SQLite responsibilities

Authentication secrets used by the local-only workspace remain under `private_data/auth/` and are never stored in SQLite or GitHub.

SQLite stores compact relational/operational state:

- source-artifact registry and SHA-256
- retrieval/vintage metadata
- processing-run ledger
- real private asset coordinates
- asset-to-indicator lineage
- portfolio exposure links
- route endpoint/dependency links
- Parquet dataset registry

SQLite should not store large climate arrays or road networks as blobs.

## Parquet responsibilities

Parquet stores larger normalized and calculated analytical tables.

Partition convention:

```
normalized/{dataset}/key=value/key=value/part-*.parquet
indicators/{dataset}/key=value/key=value/part-*.parquet
```

Examples:

```
normalized/climate/source=ERA5L_DAILY/year=2025/part-000.parquet
indicators/asset/indicator=days_tmax_gt_35c/year=2025/part-000.parquet
indicators/portfolio/hazard=JRC_RP100/as_of=2026-09-30/part-000.parquet
```

Partition fields must be stable, low-cardinality analytical dimensions. Do not partition by borrower ID, factory ID or other high-cardinality/customer identifiers.

## Raw-source responsibilities

Raw source snapshots are immutable after registration.

Every registered source file records:

- source ID
- provider
- provider version/vintage
- relative local path
- SHA-256
- byte size
- retrieval time
- valid-time support where known
- retrieval status
- manifest path/hash

Never overwrite a registered raw snapshot. A changed upstream file is a new source artifact.

## Path rule

SQLite stores **relative paths**, not workstation-specific absolute paths. This keeps the workspace portable across disks/machines.

## Production sequence

```
retrieve
 -> save raw snapshot
 -> hash
 -> write source manifest
 -> register in SQLite
 -> QA
 -> start processing run
 -> normalize / extract
 -> write Parquet
 -> register Parquet
 -> calculate indicators
 -> QA
 -> publish private outputs
 -> finish processing run
```

## First live source

ERA5-Land daily statistics remains the first planned live source because it can immediately produce real heat-level and heat-trend indicators for accepted private assets.

JRC flood, CHIRPS, DEM and OSM follow after the local workspace has passed QA.
