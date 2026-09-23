# Public repository data boundary

This repository is intentionally code-first.

## Allowed in GitHub
- source code
- schemas and empty templates
- methodological documentation
- public-source endpoint definitions
- synthetic QA fixtures
- tests and CI configuration

## Never commit
- real asset/factory coordinates or geocoding evidence tables
- DIFE/EPB/BGMEA/other compiled establishment databases
- customer bank/insurance/portfolio data
- source rasters, PBFs, NetCDF/GRIB, Parquet or database files
- private source snapshots or historical crawls
- generated customer/production outputs
- secrets or credentials

## Separation principle
GitHub stores the software and public methodology. Private infrastructure stores source data, curated databases, customer overlays, and production intelligence.
