# Bangladesh Climate & Location Risk Intelligence

A Mangrove Intelligence product for location-level climate and operational-risk intelligence in Bangladesh.

This public repository now contains the **public product shell** only: product information, methodology, selected public-safe contracts, source documentation and synthetic demonstrations.

The deployable analytical engine and operational application are maintained separately in a private core repository.

## Product scope

The platform is designed to support location-level analysis for:

- factories and industrial sites;
- warehouses and logistics assets;
- banks and collateral portfolios;
- insurers;
- infrastructure;
- commercial property;
- agriculture and supply chains.

The analytical design separates:

1. direct physical climate evidence;
2. second-order operational and logistics exposure;
3. cross-asset and portfolio concentration;
4. evidence quality, provenance and missing-data limitations.

The product intentionally avoids a single opaque climate-risk score.

## Public / private architecture

```
PUBLIC GITHUB
product information
methodology and governance
source catalogue
selected safe schemas/contracts
synthetic demonstrations

        ↓

PRIVATE CORE
analytical engine
source ingestion/parsers
SQL and migrations
authentication/tenant logic
reporting
security/recovery
deployment code
full private tests

        ↓

PRIVATE DATA
SQLite / Parquet
raw snapshots / rasters
real assets and coordinates
tenant/user data
private reports
audit/recovery material

        ↓

PRIVATE HOST
climate.mangroveintel.com
```

No automatic GitHub Actions are used in this public shell.

## Public material in this repository

- `index.html` — public product/demo page
- `docs/ARCHITECTURE.md` — high-level architecture
- `docs/SOURCE_CATALOGUE.md` — source families
- `docs/PRODUCT_OUTPUT_UX.md` — public product-output principles
- `docs/PORTFOLIO_PRIVACY_ARCHITECTURE.md` — privacy principles
- `geocoding/ACCEPTANCE_RULES.md` — public geocoding evidence rules
- `intelligence/RESEARCH_GOVERNANCE.md` — research/evidence governance
- selected public-safe JSON schemas under `contracts/`
- synthetic HTML demonstrations under `examples/synthetic/`

## Data boundary

This repository must not contain:

- real asset/factory/customer coordinates or records;
- customer bank/insurance/portfolio data;
- SQLite, Parquet, rasters, NetCDF/GRIB, PBFs or raw source archives;
- private source snapshots;
- generated customer reports;
- tenant/user/session/audit state;
- credentials, API keys, tokens or recovery secrets.

See `docs/PUBLIC_DATA_BOUNDARY.md`.

## Development model

Proprietary development now occurs in the private core. The public repository is intentionally lightweight and should not be treated as the deployable application.

Earlier versions of the engine existed in this repository's Git history. The current tree is the public-shell boundary for future development.
