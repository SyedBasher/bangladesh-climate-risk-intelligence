# Private Data Plane & Live Source Activation 0.3

## Separation

**Public GitHub**
- code
- schemas/migrations
- methodology
- source adapters
- tests
- synthetic examples

**Private relational database**
- real asset/site links
- private coordinates and geocoding outcomes
- extracted asset indicators
- processing-run metadata
- portfolio exposure links
- customer route/end-point relationships

**Private object storage**
- raw/versioned rasters
- PBFs
- NetCDF/GRIB/COGs
- source manifests
- retrieval responses
- derived private Parquet/GeoParquet
- private report artifacts

## Recommended split

Use PostgreSQL/PostGIS (for example Supabase) for relational/geospatial metadata and extracted values.

Use a private S3-compatible object store for large immutable source artifacts. Store only the object URI, SHA-256, byte size, provider/version and temporal support in PostgreSQL.

Small controlled files can also use a private Supabase Storage bucket. Supabase Storage buckets are private by default; access should be controlled through Storage RLS/API. Do not edit the internal `storage` schema directly.

## Object key convention

```
raw/{provider}/{dataset}/{provider_version}/{sha256}/{filename}
manifests/{provider}/{dataset}/{retrieval_date}/{request_sha256}.json
derived/{pipeline_version}/{run_id}/{artifact_name}
customer/{tenant_id}/{ingest_id}/{artifact_name}
```

Never put a real customer name, borrower name or confidential identifier in an object key.

## Database boundary

The migration creates `clr_private`, revokes access from `anon` and `authenticated`, enables RLS on every table, and grants server-side access to `service_role`.

The private schema should not be added to the browser-facing API schema list. Customer-facing APIs should expose narrowly scoped views or server endpoints later.

## Source activation sequence

1. Create/assign a dedicated Supabase project for Climate Risk.
2. Apply `migrations/001_private_data_plane.sql`.
3. Confirm PostGIS and private-schema grants.
4. Configure a private object-store bucket.
5. Activate ERA5-Land daily production retrieval.
6. Hash/register returned artifacts.
7. Attach heat indicators to accepted private assets.
8. Add JRC RP10/RP50/RP100 + masks.
9. Add CHIRPS final.
10. Add Copernicus DEM.
11. Add pinned OSM Bangladesh PBF and route graph.
12. Add GFM/FFWC event enrichments.

## Publication rule

`download -> hash -> register source_artifact -> QA -> processing_run -> indicator extraction -> QA -> private publish`

No asset-level value should be treated as production-ready unless the exact source artifact and processing run are recorded.
