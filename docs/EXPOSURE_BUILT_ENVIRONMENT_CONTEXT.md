# Exposure & Built Environment Context 0.1

This layer adds surrounding human-settlement context to private asset locations.

It deliberately separates two questions:

1. **How many people are estimated to live around the asset?**
2. **How much built-up surface exists around the asset, and how much is classified as predominantly non-residential?**

Neither question identifies the factory workforce, property value or asset replacement cost.

## 1. WorldPop Global2 population context

Production interface:
- WorldPop API v2
- WorldPop Global2 population data
- current Global2 release family: R2025A v1
- 100 m population data
- annual years available from 2015 to 2030

Version 0.1 uses **2025** by default.

### Radius method

For every eligible private asset, the pipeline constructs geodesic circular polygons at:

- 1 km
- 5 km
- 10 km

The circles are generated on the WGS84 ellipsoid rather than by adding fixed latitude/longitude offsets.

Each polygon is submitted to the official WorldPop API v2 at 100 m resolution.

The provider response is stored as an immutable private JSON snapshot with:
- exact request geometry;
- asset/radius request metadata;
- WorldPop task ID;
- provider response;
- returned population total;
- provider-reported polygon area;
- provider-reported or calculated population density;
- SHA-256.

Each asset/radius request is cached independently, so interrupted runs can resume without repeating completed WorldPop tasks.

### Indicators

For each radius:

- worldpop_population_within_1km / 5km / 10km
- worldpop_population_density_within_1km / 5km / 10km

These are modeled residential-population context.

They are **not**:
- factory employment;
- labour-force availability;
- daytime population;
- commuters;
- customers;
- people exposed inside the factory.

Any workforce analysis must use establishment-specific employment evidence.

## 2. GHSL GHS-BUILT-S R2023A

Production source:
- European Commission Joint Research Centre
- Global Human Settlement Layer
- GHS-BUILT-S R2023A
- 2020 historical epoch
- 100 m Mollweide grid
- total built-up surface
- non-residential (NRES) built-up surface

The source values are square metres of built-up surface within each grid cell.

Version 0.1 deliberately uses the **2020 epoch** rather than the 2025/2030 forward epochs in the R2023A release. This prevents a pre-existing projection epoch from being presented as an observed 2025 built environment.

### Source acquisition

GHSL publishes the 100 m global product as tiled ZIP archives.

For the private workflow, the operator downloads the required official 2020 tile ZIPs from the JRC/GHSL directory:
- TOTAL built surface;
- matching NRES built surface.

The pipeline requires paired TOTAL/NRES tile IDs.

For every ZIP it:
1. validates the official GHSL filename pattern;
2. reconstructs and records the official JRC source URL;
3. stores the exact ZIP in content-addressed private storage;
4. records SHA-256;
5. extracts the single TIFF member unchanged;
6. hashes/registers the TIFF separately;
7. records the package-to-raster provenance.

No GHSL raster or ZIP is committed to GitHub.

## 3. Built-environment radius calculations

The same 1 km, 5 km and 10 km radii are evaluated around each asset.

Asset coordinates are transformed from WGS84 into the GHSL raster CRS.

For each radius the system calculates:

- total built-up surface, m²;
- NRES built-up surface, m²;
- built-up surface as a share of circular buffer area;
- NRES share of total built-up surface.

Indicators are named explicitly with the 2020 source epoch, for example:

- ghsl2020_total_built_surface_within_5km_m2
- ghsl2020_nres_built_surface_within_5km_m2
- ghsl2020_built_surface_fraction_within_5km
- ghsl2020_nres_share_of_built_surface_within_5km

## 4. Tile coverage QA

The workflow does not silently interpret a missing neighbouring GHSL tile as zero built surface.

For each radius it checks geometric coverage of the circular buffer by the supplied tile set.

If coverage is below 99.5%:
- calculated built-surface indicators are null;
- quality flag = INCOMPLETE_TILE_COVERAGE.

If more than 1% of sampled cells are source NoData:
- indicators are null;
- quality flag = SOURCE_NODATA_WITHIN_BUFFER.

TOTAL and NRES tile footprints must match.

Overlapping tiles fail closed rather than being double-counted.

## 5. NRES interpretation

GHSL NRES identifies built-up surface allocated to dominant non-residential uses.

It is useful context for questions such as:
- is the asset embedded in a predominantly built-up setting?
- is there substantial non-residential development around the location?
- are multiple hazard-exposed assets concentrated inside a dense industrial/commercial landscape?

It does **not** establish:
- the asset’s own building footprint;
- factory floor area;
- industrial output;
- machinery;
- property value;
- collateral value;
- replacement cost.

Those require asset-specific records.

## 6. Geocode rule

WorldPop and GHSL are contextual neighborhood layers.

Eligible coordinates:
- EXACT_SITE + RESOLVED
- PROBABLE_SITE + RESOLVED

This differs from fine-resolution JRC/GFM point attachment.

## 7. Provenance

WorldPop indicators retain the exact provider request/response JSON through:
- WORLDPOP_POPULATION lineage.

GHSL indicators retain:
- GHSL_BUILT_TOTAL raster lineage;
- GHSL_BUILT_NRES raster lineage where relevant.

Each GHSL raster artifact also records the parent official ZIP package.

## 8. Private workflow

WorldPop:

    python scripts/run_worldpop_population_context_local.py --year 2025

GHSL:

    python scripts/run_ghsl_built_context_local.py --tile-dir /secure/path/ghsl_tiles

A valid GHSL tile directory contains paired files such as:

    GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100_V1_0_Rx_Cy.zip
    GHS_BUILT_S_NRES_E2020_GLOBE_R2023A_54009_100_V1_0_Rx_Cy.zip

The actual row/column identifiers must come from the official GHSL download interface.

## 9. Interpretation boundary

A defensible statement might say:

“WorldPop estimates approximately X residents within 5 km of the asset. GHSL 2020 shows Y square metres of built-up surface in the same radius, of which Z% is classified as predominantly non-residential.”

It should not say:

“The factory has X workers nearby,” or “the surrounding property is worth Y.”

Those conclusions require different data and models.
