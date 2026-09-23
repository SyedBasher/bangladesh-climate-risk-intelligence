# Water Stress & Drought 0.1

This layer separates three different questions that are often incorrectly collapsed into one “water risk” score:

1. **meteorological drought** — has precipitation been unusually low?
2. **soil-moisture anomaly** — is the land-surface water state unusually dry for that calendar month?
3. **structural basin water stress** — is long-run human water demand high relative to available renewable supply?

The first two are time-varying climate indicators. The third is a structural WRI basin context. None of them, alone, is a factory water-shortage estimate.

## 1. CHIRPS SPI-3 and SPI-12

Source:
- CHIRPS v3 final RNL daily precipitation
- UCSB Climate Hazards Center
- 0.05 degree grid
- satellite/gauge blended precipitation with ERA5-based daily disaggregation

Baseline:
- 1991-2020

Accumulation windows:
- SPI-3: three-month precipitation accumulation
- SPI-12: twelve-month precipitation accumulation

### Method

For each grid cell and calendar month:

1. daily CHIRPS is aggregated to monthly precipitation;
2. rolling 3-month or 12-month precipitation is calculated;
3. the 1991-2020 calibration sample is selected for the same ending calendar month;
4. a gamma distribution is fitted to positive calibration values with location fixed at zero;
5. the empirical zero-precipitation probability is retained separately;
6. the mixed cumulative probability is transformed through the standard normal inverse CDF.

The calibration chunk includes 1990 so early 1991 twelve-month accumulations are complete.

A later target such as 2025 needs only 2024 as its target lead year. Years between the calibration endpoint and target lead are not required.

### Stored SPI outputs

Monthly:
- spi3
- spi12

Annual transparent summaries:
- spi3_min_year
- spi3_months_le_minus1
- spi12_min_year
- spi12_months_le_minus1

The threshold -1.0 is reported literally as one standardized unit below the calibrated distribution. Mangrove does not relabel these values into an opaque drought-risk score.

### Interpretation

SPI is meteorological drought evidence.

It does not directly establish:
- river flow;
- groundwater availability;
- municipal or industrial water supply;
- factory water shortage;
- crop loss;
- economic loss.

## 2. ERA5-Land soil-moisture anomalies

Production source:
- Copernicus Climate Data Store / ECMWF
- ERA5-Land monthly averaged data
- 0.1 degree CDS grid
- reanalysis
- monthly means

Layers retained separately:
- layer 1: 0-7 cm
- layer 2: 7-28 cm

Mangrove deliberately does not create an invented “root-zone” combination in version 0.1.

### Anomaly method

For each asset grid cell, soil layer and calendar month:

- baseline mean = 1991-2020 mean for that calendar month;
- baseline standard deviation = 1991-2020 sample standard deviation;
- anomaly z = (target monthly value - baseline calendar-month mean) / baseline standard deviation.

This calendar-month standardization preserves seasonality.

Monthly indicators:
- soil_moisture_l1_anomaly_z
- soil_moisture_l2_anomaly_z

Annual summaries:
- soil_moisture_l1_min_z_year
- soil_moisture_l1_months_le_minus1
- soil_moisture_l2_min_z_year
- soil_moisture_l2_months_le_minus1

ERA5-Land soil moisture is model/reanalysis grid-cell context, not an in-situ reading at the asset.

## 3. WRI Aqueduct 4.0 baseline water stress

Source:
- World Resources Institute
- Aqueduct 4.0 Current and Future Global Maps Data
- baseline annual spatial dataset
- CC BY 4.0

Aqueduct baseline water stress indicates how much water is being used relative to how much is naturally available. Higher values indicate greater competition for available water.

Mangrove stores the WRI source fields without rescaling:

- wri_aqueduct4_bws_raw
- wri_aqueduct4_bws_score
- wri_aqueduct4_bws_cat
- wri_aqueduct4_bws_label

The 0-5 score and category remain explicitly WRI fields. They are not a Mangrove score.

Mangrove does **not** ingest or calculate WRI’s overall composite water-risk score in this layer.

### Spatial matching

The official WRI spatial snapshot is stored privately with SHA-256 provenance.

Accepted source formats:
- GeoPackage
- GeoJSON
- ZIP-readable spatial archive

If the source contains more than one spatial layer, the operator must name the baseline annual layer explicitly.

Asset coordinates are matched with a point-in-polygon rule.

- exactly one polygon: MATCHED
- no polygon: NO_MATCH
- more than one covering polygon: AMBIGUOUS and fail closed

No nearest-basin substitution is performed.

## 4. Geocode rule

CHIRPS, ERA5-Land monthly soil moisture and Aqueduct are coarse contextual layers.

Eligible assets:
- EXACT_SITE + RESOLVED
- PROBABLE_SITE + RESOLVED

This differs from fine-resolution JRC/GFM attachment.

## 5. Source lineage

SPI indicators retain:
- baseline CHIRPS yearly source subsets;
- target-lead and target-year CHIRPS source subsets.

Soil-moisture anomaly indicators retain:
- each 1991-2020 ERA5-Land yearly baseline artifact;
- the target-year ERA5-Land artifact.

Aqueduct fields retain:
- the exact official WRI spatial snapshot as PRIMARY source lineage.

## 6. Private workflow

### CHIRPS SPI

    python scripts/run_chirps_spi_local.py --year 2025

### ERA5-Land soil moisture plan

    python scripts/plan_era5_soil_moisture_local.py --year 2025

### ERA5-Land soil moisture run

    python scripts/run_era5_soil_moisture_local.py --year 2025

### WRI Aqueduct 4.0

    python scripts/run_aqueduct4_baseline_local.py \
        --file /secure/path/aqueduct4_spatial.zip \
        --source-url https://datasets.wri.org/... \
        --layer BASELINE_ANNUAL_LAYER_NAME

The layer argument can be omitted if the file exposes only one spatial layer.

## 7. Operational water dependence remains separate

Version 0.1 does not infer factory water use from sector averages.

A later private operational-water module can add evidence such as:
- groundwater dependence;
- municipal-water dependence;
- surface-water dependence;
- daily withdrawal or process-water requirement;
- on-site storage;
- recycling/reuse;
- backup water source;
- treatment constraints.

Those asset-specific fields should then be combined analytically with drought and basin context, not hidden inside a composite score.

## 8. Interpretation boundary

A defensible statement might say:

“Precipitation over the preceding three months was unusually low relative to the 1991-2020 distribution, shallow ERA5-Land soil moisture was also below its seasonal baseline, and the asset lies in a basin that WRI Aqueduct classifies as structurally water-stressed.”

It should not say:

“The factory has a 70% chance of water shortage.”

The latter would require asset water-source, infrastructure, management and supply data that these climate/context layers do not provide.
