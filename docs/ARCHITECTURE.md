# Architecture overview

The engine separates four layers:

1. **Source layer** — observed, satellite, reanalysis, modelled and mapping datasets with immutable provenance.
2. **Asset layer** — external asset identifiers and defensible coordinates; the climate engine does not own customer/entity master records.
3. **Indicator layer** — direct physical indicators plus transparent calculated exposure measures.
4. **Intelligence layer** — operational, logistics and portfolio transmission diagnostics with explicit research/evidence guardrails.

Large rasters and source archives live outside GitHub. PostgreSQL/PostGIS can hold metadata, asset links and extracted indicators; object storage holds large source artifacts.
