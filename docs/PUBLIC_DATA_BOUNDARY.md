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


## Derived workspace guards

The second-line public-boundary checker derives private directory fragments from `local_store.WORKSPACE_DIRS` rather than maintaining a separate copy of the workspace layout.

The repository-level `.gitignore` and `.dockerignore` also protect private workspace subtrees under arbitrary custom roots, including `auth`, `catalog`, `raw`, `normalized`, `indicators`, `manifests`, `outputs`, `tmp` and `backups`.

Every initialized private workspace still creates its own root `.gitignore` containing `*`; that remains the load-bearing protection if the workspace lives inside a larger Git checkout.
