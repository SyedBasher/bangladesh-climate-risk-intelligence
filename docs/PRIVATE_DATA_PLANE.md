# Private Data Plane

The project uses a staged data architecture.

## Current stage

```
PUBLIC GITHUB
code + parsers + tests + schemas + methodology + CI
        |
        v
PRIVATE LOCAL DATA
SQLite + Parquet + raw source snapshots
        |
        v later
HOSTED DATABASE
Supabase / Neon / another PostgreSQL provider
```

The hosted database is deliberately deferred until the product/API requires it.

## Public GitHub

Contains:
- code
- schemas and migrations
- methodology
- source adapters
- tests
- synthetic examples
- CI

Never contains:
- real factory/asset coordinate databases
- compiled DIFE/EPB/BGMEA data
- bank/insurer/customer portfolios
- raw source rasters/PBF/NetCDF
- production Parquet
- credentials or private outputs

## Private local layer

SQLite stores relational state and provenance:

- source-artifact registry
- SHA-256 and source vintages
- processing runs
- private asset coordinates
- asset-indicator lineage
- portfolio links
- route dependencies
- Parquet dataset registry

Parquet stores larger normalized/calculated analytical tables.

Raw directories store immutable source snapshots.

See `docs/LOCAL_PRIVATE_DATA_PLANE.md`.

## Future hosted layer

`migrations/001_private_data_plane.sql` remains the future PostgreSQL/PostGIS deployment schema.

When hosted deployment becomes useful:

- SQLite relational tables migrate to PostgreSQL;
- only interactive/API-relevant Parquet tables need move into PostgreSQL;
- heavy climate matrices and raw source snapshots can remain object-backed;
- browser/client access should use narrow APIs/views rather than exposing private schemas directly.

## Publication rule

`retrieve -> raw snapshot -> SHA-256 -> source manifest -> SQLite registration -> QA -> processing run -> Parquet/indicator calculation -> QA -> private output`

No real asset-level value is production-ready unless its exact source artifact and processing run are recorded.
