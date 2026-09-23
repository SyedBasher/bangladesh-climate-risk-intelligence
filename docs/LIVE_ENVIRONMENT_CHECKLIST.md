# Live environment checklist

Required for core factory production:
- outbound HTTPS;
- persistent raw-data storage;
- PostgreSQL/PostGIS;
- Copernicus CDS account/key;
- Copernicus Data Space access for GLO-30;
- enough disk for source vintages and PBF/raster cache;
- secrets supplied by environment/secret manager, never repository files.

Recommended:
- containerized pipeline;
- scheduled source refresh;
- immutable object storage or versioned filesystem;
- source-vintage table in PostGIS;
- separate raw / normalized / indicators / customer-overlay schemas;
- job logs and failure alerts;
- backup of source hashes and request manifests.

Publication rule:
`raw source -> hash -> QA -> source_vintage COMPLETE -> extraction -> calculation QA -> atomic publish`.
