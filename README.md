# Bangladesh Climate & Location Risk Intelligence

Public code, schemas, and methodology for a location-level physical climate and operational-risk intelligence engine for Bangladesh.

The project is designed to connect geocoded assets with transparent hazard, exposure, logistics, and portfolio diagnostics while preserving source provenance and avoiding opaque composite risk scores.

## Operating architecture

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

The current operational data layer is local/private. Hosted PostgreSQL is a later deployment step, not a prerequisite.

## What is public here

- processing and analytical code
- input/output schemas
- source-adapter logic
- geocoding and QA rules
- flood, rainfall, heat, terrain, logistics, and portfolio methods
- research-governance methodology
- synthetic examples and automated tests

## What is **not** in this repository

The repository intentionally excludes:

- real factory/asset coordinate databases
- DIFE-enriched establishment records and matching evidence
- raw or cached source datasets and raster files
- customer, bank, insurer, collateral, or portfolio data
- proprietary derived databases and production analytical outputs
- credentials, API keys, tokens, and private source snapshots

Those components are maintained outside GitHub.

## Local private workspace

Initialize the gitignored private workspace with:

```bash
python scripts/init_private_workspace.py
```

The local catalog uses SQLite; larger analytical tables use Parquet; source snapshots remain immutable files with registered SHA-256 provenance.

See:
- `docs/LOCAL_PRIVATE_DATA_PLANE.md`
- `docs/LOCAL_BACKUP_POLICY.md`
- `docs/PRIVATE_DECISION_WORKSPACE.md`
- `docs/PRIVATE_WORKSPACE_APP.md`
- `docs/HOSTED_PRIVATE_PILOT_SECURITY.md`
- `docs/PRIVATE_PILOT_DEPLOYMENT_REHEARSAL.md`
- `docs/EXTERNAL_SECURITY_REVIEW.md`
- `docs/EXTERNAL_SECURITY_REVIEW_PROMPT.md`
- `deploy/private_pilot/README.md`

## Core design principles

1. **Hazard is not loss.** Physical exposure is kept separate from damage, downtime, PD/LGD, and insurance-loss models.
2. **No arbitrary composite score.** Indicators remain interpretable by dimension.
3. **Evidence-grade geocoding.** Fine-resolution hazard attachment requires a defensible exact site, not a locality centroid or company head office.
4. **Observed, modelled, and reanalysis data stay distinct.** Measurement basis and source vintage are stored explicitly.
5. **Second- and third-order effects are traceable.** Operational, logistics, and financial transmission mechanisms are linked to their required evidence and guardrails.
6. **Fail closed.** Missing or ambiguous source evidence produces a null/blocked state, never a fabricated value.
7. **Data minimisation.** Portfolio workflows are designed around pseudonymous IDs and minimum necessary fields.

## Main modules

- `src/clr/jrc_flood.py` — modelled river-flood depth extraction
- `src/clr/chirps.py` — rainfall metrics
- `src/clr/era5_land.py` — heat metrics from reanalysis
- `src/clr/geocoding.py` — conservative site matching
- `src/clr/logistics.py` — route redundancy and hazard-conditioned connectivity
- `src/clr/osm_local.py` — pinned Geofabrik/OSM road-network ingestion and private endpoint linkage
- `src/clr/logistics_local.py` — baseline private route analysis and shared bottlenecks
- `src/clr/route_flood_local.py` — JRC flood exposure overlay for baseline routes
- `src/clr/gfm_local.py` — Sentinel-1 GFM observed-flood event evidence and JRC comparison
- `src/clr/ffwc_local.py` — official FFWC/BWDB station snapshot ingestion and nearest-gauge event context
- `src/clr/drought.py` — transparent SPI-3/SPI-12 precipitation-drought calculations
- `src/clr/drought_local.py` — CHIRPS drought production and source lineage
- `src/clr/era5_soil_moisture_local.py` — ERA5-Land seasonal soil-moisture anomalies
- `src/clr/aqueduct_local.py` — WRI Aqueduct 4.0 basin water-stress context
- `src/clr/ibtracs_local.py` — NOAA IBTrACS cyclone-track proximity, intensity context, and event timelines
- `src/clr/worldpop_local.py` — WorldPop Global2 population context around asset radii
- `src/clr/ghsl_built_local.py` — GHSL total/non-residential built-environment context
- `src/clr/surface_water_local.py` — JRC Global Surface Water v1.5 occurrence, recurrence, and high-occurrence-water distance
- `src/clr/worldcover_local.py` — ESA WorldCover 2021 v200 site class and surrounding land-cover composition
- `src/clr/compound_local.py` — same-month heat–drought joins, flood/route evidence states, and cross-asset bottleneck metrics
- `src/clr/decision_reports.py` — governed decision-facing assembly of asset, compound, logistics, and portfolio evidence
- `src/clr/decision_report_html.py` — standalone printable HTML rendering of governed decision-workspace objects
- `src/clr/private_decision_workspace.py` — explicit-run adapter from the private SQLite/Parquet data plane to JSON/HTML decision reports
- `src/clr/private_workspace_auth.py` — local password hashing and signed tenant-bound sessions
- `src/clr/private_workspace_app.py` — legacy local-only shared-password compatibility shell; disabled by default
- `src/clr/private_workspace_access.py` — named users, tenant roles, revocable opaque sessions, HMAC audit chain, and authenticated audit-head anchoring
- `src/clr/private_workspace_pilot_app.py` — loopback-only named-user backend intended to sit behind a TLS reverse proxy
- `src/clr/private_pilot_rehearsal.py` — non-destructive preflight, encrypted recovery-bundle rehearsal, anchored audit verification, and deployment-example checks
- `src/clr/synthetic_decision_demo.py` — reproducible synthetic public workspace fixture
- `src/clr/intelligence.py` — transparent second-/third-order exposure logic
- `src/clr/portfolio.py` — bank/insurer portfolio accumulation and concentration
- `src/clr/live_integration.py` — production source gates and provenance controls
- `src/clr/local_store.py` — local SQLite/Parquet private-data layer

## Synthetic decision-report demonstration

A fully synthetic structured workspace and printable HTML example are available at:

- `examples/synthetic/decision_workspace_demo.json`
- `examples/synthetic/decision_workspace_demo.html`

Regenerate them with:

```bash
python scripts/build_synthetic_decision_report.py
```

The HTML renderer is presentation-only: it does not calculate new hazards, scores, losses, or findings.

## Data boundary

See `docs/PUBLIC_DATA_BOUNDARY.md`.

## Status

The public repository contains the software/methodology baseline plus a hosted-private-pilot security foundation. Real data, credentials, access-control records, audit secrets, generated client reports, and production intelligence remain private.

## License

No open-source license has been granted at this time. The repository is publicly viewable, but reuse rights are not granted merely by publication.
