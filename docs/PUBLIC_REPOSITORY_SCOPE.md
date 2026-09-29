# Public repository scope

This repository is the public companion to the private Mangrove Climate Risk core.

## Public

- product overview and public website;
- high-level architecture and methodology;
- source catalogue;
- research-governance principles;
- selected public-safe input/output schemas;
- synthetic demonstrations;
- privacy and geocoding evidence principles.

## Private core

The following are intentionally maintained outside this public repository:

- analytical engine and source-ingestion implementation;
- SQL and migrations;
- private workspace/data-plane implementation;
- authentication and tenant isolation;
- audit/recovery code;
- deployment configuration;
- full regression/security tests;
- operational scripts.

## Private data

Real data is outside GitHub entirely, including SQLite/Parquet stores, rasters/raw snapshots, real assets, customer portfolios, tenant/user state, private reports and backup/recovery material.

## Git history

Earlier versions of this repository contained more implementation code. The current tree defines the public/private boundary for future development.
