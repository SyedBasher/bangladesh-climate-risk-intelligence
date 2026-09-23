# Bangladesh Climate & Location Risk Intelligence

Public code, schemas, and methodology for a location-level physical climate and operational-risk intelligence engine for Bangladesh.

The project is designed to connect geocoded assets with transparent hazard, exposure, logistics, and portfolio diagnostics while preserving source provenance and avoiding opaque composite risk scores.

## What is public here

- processing and analytical code
- input/output schemas
- source-adapter logic
- geocoding and QA rules
- flood, rainfall, heat, terrain, logistics, and portfolio methods
- research-governance methodology
- synthetic examples and automated tests

## What is **not** in this repository

The repository intentionally excludes:

- real factory/asset coordinate databases
- DIFE-enriched establishment records and matching evidence
- raw or cached source datasets and raster files
- customer, bank, insurer, collateral, or portfolio data
- proprietary derived databases and production analytical outputs
- credentials, API keys, tokens, and private source snapshots

Those components are maintained outside GitHub in controlled data/storage infrastructure.

## Core design principles

1. **Hazard is not loss.** Physical exposure is kept separate from damage, downtime, PD/LGD, and insurance-loss models.
2. **No arbitrary composite score.** Indicators remain interpretable by dimension.
3. **Evidence-grade geocoding.** Fine-resolution hazard attachment requires a defensible exact site, not a locality centroid or company head office.
4. **Observed, modelled, and reanalysis data stay distinct.** Measurement basis and source vintage are stored explicitly.
5. **Second- and third-order effects are traceable.** Operational, logistics, and financial transmission mechanisms are linked to their required evidence and guardrails.
6. **Fail closed.** Missing or ambiguous source evidence produces a null/blocked state, never a fabricated value.
7. **Data minimisation.** Portfolio workflows are designed around pseudonymous IDs and minimum necessary fields.

## Main modules

- `src/clr/jrc_flood.py` — modelled river-flood depth extraction
- `src/clr/chirps.py` — rainfall metrics
- `src/clr/era5_land.py` — heat metrics from reanalysis
- `src/clr/geocoding.py` — conservative site matching
- `src/clr/logistics.py` — route redundancy and hazard-conditioned connectivity
- `src/clr/intelligence.py` — transparent second-/third-order exposure logic
- `src/clr/portfolio.py` — bank/insurer portfolio accumulation and concentration
- `src/clr/live_integration.py` — production source gates and provenance controls

## Data boundary

See [`docs/PUBLIC_DATA_BOUNDARY.md`](docs/PUBLIC_DATA_BOUNDARY.md).

## Status

The public repository contains the software/methodology baseline. Production databases and live asset intelligence are maintained separately.

## License

No open-source license has been granted at this time. The repository is publicly viewable, but reuse rights are not granted merely by publication.
