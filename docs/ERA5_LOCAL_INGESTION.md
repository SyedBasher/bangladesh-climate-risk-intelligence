# ERA5-Land Local Ingestion 0.1

This is the first authoritative live-source path for the local private data plane.

## Source

Production source:
- Copernicus Climate Data Store
- dataset: `derived-era5-land-daily-statistics`
- variable: 2 m temperature
- daily maximum and daily minimum
- local daily aggregation: `UTC+06:00`
- sampling frequency: 1-hourly
- native daily-product grid: 0.1 degrees

Official documentation:
- https://cds.climate.copernicus.eu/datasets/derived-era5-land-daily-statistics
- https://confluence.ecmwf.int/pages/viewpage.action?pageId=505385718

The daily statistics are calculated during retrieval rather than being a permanently archived daily product. For that reason, Mangrove preserves:
- exact CDS request parameters;
- returned ZIP bytes;
- SHA-256;
- retrieval date;
- processing run and Git commit.

## Why the first run is 2025

Start with the latest complete calendar year before attempting the historical backfill.

This validates:
- CDS credentials;
- request semantics;
- local-day aggregation;
- immutable raw storage;
- SQLite source registration;
- NetCDF extraction;
- Parquet output;
- asset-level indicator insertion.

After this passes, backfill 1991 onward for long-run heat trends.

## Setup

Install local-only dependencies:

```bash
pip install -r requirements-local.txt
```

Configure CDS credentials outside Git. The repository already ignores `.cdsapirc`.

Initialize the private workspace:

```bash
python scripts/init_private_workspace.py
```

## Import private assets

The import file itself remains outside GitHub.

Required columns:
- external_system
- external_id
- asset_type
- latitude
- longitude
- coordinate_source
- site_identity_grade
- coordinate_status

Example structure is shown only with synthetic rows in:
`examples/synthetic/private_asset_import.csv`.

Import:

```bash
python scripts/import_private_assets.py --csv /secure/path/assets.csv
```

Only `EXACT_SITE + RESOLVED` assets enter the ERA5 extraction set.

## Inspect the request before downloading

```bash
python scripts/plan_era5_local.py --year 2025
```

The plan is written inside the gitignored private workspace under:
`manifests/plans/era5_land/`.

## Run the first authoritative heat ingestion

```bash
python scripts/run_era5_local.py --year 2025
```

The run:

1. selects accepted private assets;
2. requests daily maximum temperature;
3. requests daily minimum temperature;
4. saves each download to a temporary private file;
5. hashes the bytes;
6. moves the file into content-addressed immutable raw storage;
7. registers source artifact + exact request in SQLite/manifests;
8. extracts nearest ERA5-Land grid-cell daily values for each asset;
9. writes normalized Parquet;
10. calculates:
   - days with Tmax > 35 C;
   - days with Tmax > 38 C;
   - warm nights with Tmin > 28 C;
11. inserts the calculated indicators with source/run lineage;
12. marks the processing run SUCCESS only if the full chain completes.

## Interpretation

ERA5-Land is reanalysis, not a factory indoor-temperature measurement.

These outputs describe outdoor/grid-cell heat conditions near a site. Indoor worker thermal conditions require separate building/workplace information such as roof design, ventilation, fans, hydration, operating hours and shift structure.

No productivity-loss coefficient or composite heat-risk score is created by this pipeline.
