# Public repository data boundary

This repository is the public information and methodology layer for Bangladesh Climate & Location Risk Intelligence.

## Allowed here

- product description and public website/demo material;
- high-level methodology and research-governance documentation;
- public source catalogue;
- selected public-safe schemas/contracts;
- synthetic demonstrations;
- privacy and geocoding principles.

## Not allowed here

- analytical engine or proprietary implementation modules;
- SQL migrations or operational database code;
- authentication, tenant, deployment, recovery or audit implementation;
- real asset/factory coordinates or compiled establishment databases;
- customer bank/insurance/portfolio records;
- SQLite, Parquet, rasters, PBF, NetCDF/GRIB or raw source archives;
- private source snapshots;
- generated customer/production outputs;
- tenant/user/session/audit state;
- credentials, tokens, keys or secret-bearing configuration.

## Separation principle

Public GitHub explains the product and methodology.

The private core contains the deployable engine.

Private infrastructure contains real data and customer intelligence.
