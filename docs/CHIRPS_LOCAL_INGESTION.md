# CHIRPS Rainfall Local Ingestion 0.1

## Source

Production source:
- UCSB Climate Hazards Center
- CHIRPS v3 final
- daily reanalysis-based (rnl) disaggregation
- 0.05 x 0.05 degree global land grid
- 1981 to near-present

CHIRPS v3 combines satellite-based rainfall estimates with station observations. The daily rnl product disaggregates CHIRPS pentadal precipitation totals using ERA5 daily precipitation.

Mangrove therefore classifies the daily values as SATELLITE_GAUGE_BLEND_WITH_REANALYSIS_DAILY_DISAGGREGATION. They are not rain-gauge observations at a factory.

## Source-subset snapshots

The full daily archive is large. For asset intelligence the default production mode is to open the official cloud-optimized GeoTIFF for each day, read only the required 0.05-degree grid cell values, preserve those values without transformation, record the exact official source URL plus grid row/column/centre, and write an immutable yearly Parquet source-subset snapshot.

The local source-subset snapshot is content-addressed with SHA-256 and registered in SQLite. It is a reproducible extraction from the official source, not a mirror of the full global archive.

Full-source mirroring can be added later if archival requirements justify the storage cost.

## Geocode rule

Because CHIRPS is approximately a 5 km grid, both EXACT_SITE + RESOLVED and PROBABLE_SITE + RESOLVED may be used. This differs from fine-resolution JRC flood depth, which requires EXACT_SITE.

## Baseline

Mangrove uses 1991-2020 as the initial precipitation-percentile baseline. This is explicit rather than silently inheriting the traditional 1961-1990 ETCCDI base period, which is unavailable in CHIRPS because the dataset begins in 1981.

## Indicators

rx1day_mm: maximum daily precipitation in the target calendar year.

rx5day_mm: maximum consecutive five-day precipitation total in the target calendar year.

r50mm_days: number of target-year days with precipitation at least 50 mm. This is a user-defined Rnnmm-style threshold, not a universal core threshold.

prcptot_mm: total target-year precipitation on wet days, where wet day means at least 1 mm.

r95_threshold_mm: site/grid-cell 95th percentile of wet-day precipitation during 1991-2020. The percentile estimator follows RClimDex/Climpact Hyndman-Fan type 8, implemented as NumPy median_unbiased.

r95p_mm: annual precipitation from target-year days above the baseline wet-day 95th percentile.

r95p_share_pct: 100 times r95p_mm divided by prcptot_mm.

r95p_days: supplementary count of target-year days above the same R95 threshold. This count is useful operationally but is not itself the standard R95p amount indicator.

calendar_cdd_days: longest run within the target calendar year with precipitation below 1 mm.

calendar_cwd_days: longest run within the target calendar year with precipitation at least 1 mm.

The last two IDs deliberately say calendar because formal spell implementations can allow spells to span year boundaries. Mangrove does not claim full spanning-year ETCCDI equivalence yet.

## Completeness

Production calculation requires every day in every baseline year, every day in the target year, and no missing rainfall values. A partial source extraction therefore cannot be interpreted as low rainfall.

## Target years inside the baseline

R95 production calculation is blocked when the target year lies inside the percentile baseline. Formal bootstrap treatment for in-base percentile indices will be implemented before historical R95 trend series are produced.

## Workflow

Plan the extraction:

    python scripts/plan_chirps_local.py --year 2025

Build the 1991-2020 baseline, resumably one year at a time:

    python scripts/extract_chirps_baseline_local.py

Extract the target year:

    python scripts/extract_chirps_year_local.py --year 2025

Calculate and publish private indicators:

    python scripts/run_chirps_rainfall_local.py --year 2025

No source-subset Parquet, private coordinates, SQLite database, private manifest, or production output enters GitHub.
