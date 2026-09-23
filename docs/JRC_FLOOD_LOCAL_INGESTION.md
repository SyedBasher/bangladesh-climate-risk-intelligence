# JRC Flood Local Ingestion 0.1

This is the second authoritative live-source path for the local private data plane.

## Source

Production source:
- Copernicus Emergency Management Service / Joint Research Centre
- Global river flood hazard maps
- dataset version: 2.1.2
- horizontal resolution: 3 arc seconds, approximately 90 m
- units: metres
- model chain: LISFLOOD river flow + LISFLOOD-FP inundation
- return periods available from the source: 10, 20, 50, 75, 100, 200 and 500 years

MVP extraction uses RP10, RP50 and RP100.

Official source directory:
`https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/CEMS-GLOFAS/flood_hazard/`

## Interpretation

This is **modelled river-flood hazard**, not:
- an observed flood event;
- a flood forecast;
- a statement that a location will flood in a given year;
- a damage estimate.

The source README warns that very high depths can reflect modelling, DEM or tile-boundary artefacts.

## Mandatory masks

For each tile, production extraction downloads and records:

1. raw depth raster for each selected return period;
2. permanent-water raster;
3. spurious-depth raster;
4. `tile_extents.geojson`.

The masks are not optional in the production path.

### Permanent water

If an accepted asset coordinate falls on the permanent-water mask:
- the raw JRC depth remains preserved in normalized Parquet;
- the published asset indicator is set to null;
- `null_reason = PERMANENT_WATER_MASK`;
- the site/hazard alignment requires review.

### Spurious depth

If the spurious-depth mask is active:
- the raw depth remains preserved;
- the published asset indicator is set to null;
- `null_reason = SPURIOUS_DEPTH_MASK`.

The pipeline therefore does not silently convert a known artefact-prone depth into ordinary site intelligence.

## Multi-source lineage

Every published/null flood indicator records lineage to:
- the depth tile;
- permanent-water mask;
- spurious-depth mask;
- tile-extents GeoJSON.

This is stored in `asset_indicator_source`.

## Plan before downloading

```bash
python scripts/plan_jrc_flood_local.py
```

The planner downloads/registers only the small tile-extents metadata, resolves accepted assets to JRC tiles, and writes the required artifact list inside the gitignored private workspace.

## Run

```bash
python scripts/run_jrc_flood_local.py
```

Default return periods:

```
10 50 100
```

A custom subset can be requested:

```bash
python scripts/run_jrc_flood_local.py --return-periods 50 100
```

## Production sequence

```
accepted private assets
 -> tile_extents
 -> exact JRC tile resolution
 -> depth + permanent-water + spurious-depth download
 -> SHA-256 + request/source manifest
 -> point extraction
 -> mask QA
 -> normalized Parquet
 -> SQLite asset_indicator
 -> multi-source lineage
 -> processing run SUCCESS
```

Only `EXACT_SITE + RESOLVED` assets are eligible.
