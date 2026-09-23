## What changed?

Describe the code, methodology, schema, source adapter, or documentation change.

## Data-boundary checklist

- [ ] No real customer/borrower/policy/portfolio data is included.
- [ ] No real factory/asset coordinate database or private geocoding evidence is included.
- [ ] No raw raster/PBF/NetCDF/GRIB/Parquet/database artifact is included.
- [ ] No credential, token, key, private URL, or secret-bearing config is included.
- [ ] Tests/examples use synthetic or explicitly public non-sensitive fixtures only.

## Methodology checklist

- [ ] Source and measurement basis remain explicit.
- [ ] Source vintage/provenance is preserved.
- [ ] Null/ambiguous cases fail closed.
- [ ] Hazard is not automatically converted to loss, PD/LGD, downtime, or pricing.
- [ ] No arbitrary composite risk score is introduced.

## QA

Describe tests run and any known limitations.
