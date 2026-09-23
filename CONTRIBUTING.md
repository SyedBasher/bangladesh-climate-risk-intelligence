# Contributing

Changes are welcome, but this repository has a strict public/private boundary.

## Before opening a pull request

Do not commit:

- real factory, warehouse, collateral, borrower or customer coordinates;
- DIFE/EPB/BGMEA or other compiled establishment datasets;
- customer, bank, insurer, loan, policy or portfolio records;
- raw or cached source rasters, PBFs, NetCDF/GRIB, Parquet or database files;
- source snapshots that are maintained privately;
- credentials, tokens, API keys, private URLs or secret-bearing configuration;
- generated production/client outputs.

Use synthetic fixtures for tests and examples.

## Methodological rules

- Keep observed, satellite-observed, reanalysis, modelled and calculated values distinct.
- Preserve source vintage and provenance.
- Do not convert hazard exposure into damage, downtime, PD/LGD, collateral haircut or insurance loss without an explicitly governed model.
- Do not add opaque composite climate-risk scores.
- Fine-resolution hazard attachment requires evidence-grade site identity and resolved coordinates.
- Fail closed when source, geocoding or linkage evidence is ambiguous.

## Pull requests

Each pull request should state:

1. what changed;
2. which source/method is affected;
3. whether any new external data dependency is introduced;
4. how provenance and null handling are preserved;
5. which tests were added or updated.

All tests should pass before merge.
