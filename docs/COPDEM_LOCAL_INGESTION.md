# Copernicus DEM Local Ingestion 0.1

## Source

Production source:
- Copernicus Data Space Ecosystem
- Copernicus DEM GLO-30
- DGED / GeoTIFF instance
- global coverage
- 1 arc-second latitude grid spacing, commonly described as approximately 30 m
- 1 degree x 1 degree delivery tiles
- horizontal reference: WGS84-G1150 / EPSG:4326
- vertical reference: EGM2008 / EPSG:3855
- vertical unit: metres

Dataset family: COP-DEM_GLO-30-DGED.
Current CDSE product type used by the pipeline: SAR_DGE_30_A4AD.

## DSM, not bare-earth terrain

Copernicus DEM is a Digital Surface Model. It represents the Earth's surface including buildings, infrastructure and vegetation. The pipeline therefore never renames the source value as ground elevation or bare-earth terrain.

The public indicator is named `elevation_dsm_m`.

Calculated terrain-context indicators also retain `dsm` in their IDs.

## Temporal interpretation

The underlying TanDEM-X / WorldDEM observations were primarily acquired during 2011-2015. Older elevation models can be used to fill gaps. A newly downloaded delivery is therefore a newer product delivery, not a new 2026 terrain observation.

This matters for rapidly changing reclaimed land, large new infrastructure, excavation, embankments and urban construction.

## Access

GLO-30 metadata can be searched through the CDSE OData catalogue. Product download requires an authenticated CDSE token and appropriate Copernicus Contributing Missions registration/license acceptance.

The local pipeline accepts either:
- `CDSE_ACCESS_TOKEN`, or
- `CDSE_USERNAME` + `CDSE_PASSWORD`, with optional `CDSE_TOTP` when 2FA is enabled.

Credentials are never written to the repository or local source manifests.

## Product selection

For each accepted asset the pipeline derives the 1-degree `gridId`, for example `N23_E090`.

It queries the catalogue using:
- collection: CCM
- gridId
- product type: SAR_DGE_30_A4AD

If multiple historical deliveries are present, the pipeline selects the highest explicit dataset release suffix, such as `2024_1`. If more than one product remains at that latest release, it fails closed rather than choosing arbitrarily.

## Raw-source preservation

For every required tile the local workflow preserves:
1. the authenticated official product package ZIP;
2. its SHA-256 and OData metadata;
3. the unmodified `_DEM.tif` member extracted from that package;
4. a second SHA-256 for the DEM raster;
5. parent-package lineage.

Both the package and DEM raster remain private and gitignored.

## Indicators

### `elevation_dsm_m`
The source DSM height at the accepted asset coordinate, in metres relative to EGM2008.

Classification:
- value class: SOURCE
- measurement basis: STATIC_DIGITAL_SURFACE_MODEL

### `dsm_relative_elevation_500m_m`
Asset DSM elevation minus the median DSM elevation inside a 500 m circular neighbourhood.

A negative number means the sampled surface is below the local DSM median. It does **not** by itself mean the site is flood-prone.

### `dsm_local_relief_p90_p10_500m_m`
90th percentile minus 10th percentile of valid DSM heights inside the same 500 m circular neighbourhood.

This is a robust local surface-relief descriptor. Buildings and vegetation can contribute to it, so it is not treated as pure geomorphology.

## Neighbourhood QA

Calculated 500 m context values require at least 80% valid DEM pixels inside the circular neighbourhood. If coverage is poorer:
- the point DSM value may still be published if valid;
- the context indicators are null;
- `INSUFFICIENT_NEIGHBORHOOD_COVERAGE` is recorded.

This threshold is a data-completeness rule, not a risk threshold.

## Fine-resolution geocode rule

Only `EXACT_SITE + RESOLVED` asset coordinates are eligible for GLO-30 extraction.

## Provenance

Every DEM indicator retains lineage to:
- `DEM_RASTER`
- `SOURCE_PACKAGE`

The package manifest records the CDSE product ID, product name, grid ID, dataset/delivery, catalogue metadata and required attribution.

## Required source notice

When Copernicus GLO-30 is communicated to the public, outputs must carry the source notice required by the provider:

© DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved

Derived/modified presentations should follow the corresponding provider attribution requirement.

## Workflow

Plan metadata only:

    python scripts/plan_copdem_local.py

Run authenticated download and extraction:

    python scripts/run_copdem_local.py

The run produces private source snapshots, normalized Parquet and SQLite indicators. None of those private files enters GitHub.

## Analytical use

The DSM layer can later be combined with JRC flood exposure to answer bounded questions such as:
- is the asset surface lower or higher than its immediate surroundings?
- are multiple flood-exposed assets concentrated in locally low surface positions?
- do route segments cross locally low DSM corridors?

It must not be used alone to infer flood probability, drainage capacity, floor elevation, protection-standard adequacy or expected damage.
