# Repository Split Plan

## Objective

Move Bangladesh Climate & Location Risk Intelligence from a single public code repository to a three-layer architecture:

1. a **public GitHub shell** for product information, methodology, safe documentation, selected schemas/contracts and synthetic examples;
2. a **private core repository** for the analytical engine, source ingestion, SQL/migrations, authentication/tenant logic, private tests, deployment and recovery implementation;
3. **private data outside GitHub** for SQLite, Parquet, rasters/raw snapshots, real assets/coordinates, tenant/user data, generated reports, audit material and backups.

The purpose is both product protection and operational simplicity. Routine development/testing should no longer depend on automatic GitHub Actions.

## Current public baseline

Before the split, the verified public implementation baseline is:

`27b2e31cf4d7f587a616c13a4df1168a35d6c541`

That commit includes the post-security-review session-revocation atomicity fix.

## Non-negotiable migration order

Do **not** delete or thin the public repository first.

The order is:

1. disable automatic GitHub Actions;
2. create the empty private core repository;
3. copy the complete current codebase into the private core;
4. run the full test suite and public/private boundary checks locally against the private core;
5. verify the private core contains every engine, migration, test, deployment and recovery file required for host provisioning;
6. only then create a public-shell branch that removes proprietary/private-core implementation from the public repository;
7. review the public-shell diff for accidental secrets/private data;
8. merge the public-shell change;
9. continue all proprietary development in the private core.

## Public repository target

The public repository should eventually contain only material safe and useful to publish, such as:

- README / product description;
- methodology and evidence principles;
- source catalogue;
- public data dictionary / selected indicator definitions;
- selected public-safe schemas/contracts;
- synthetic examples that contain no real asset/customer/tenant data;
- public website/demo shell;
- public governance documentation.

No automatic `push` or `pull_request` GitHub Actions should be required.

## Private core target

The private core should hold the complete deployable application and analytical implementation, including as applicable:

- `src/clr/` analytical and operational modules;
- source ingestion/parsers;
- SQL migrations;
- private workspace/data-plane code;
- authentication, tenant isolation and audit/recovery code;
- deployment configuration;
- private operational documentation;
- full test suite;
- scripts required to ingest, analyse, report, back up, restore and deploy;
- local test commands and pre-deploy checklists.

The core repository must still contain **no real customer/asset/private datasets** unless a future explicit decision changes this rule.

## Private data remains outside GitHub

Do not move these into either GitHub repository:

- SQLite catalogs;
- Parquet tables;
- raw/cache source snapshots;
- rasters;
- real factory/asset coordinates;
- real customer/bank/insurer/portfolio data;
- tenant/user/session/audit state;
- generated private reports;
- private recovery material;
- encrypted operational backup bundles;
- secrets or credentials.

## CI / testing policy after split

Automatic GitHub Actions are intentionally not part of the normal development loop.

Before deployment or material merges, run locally:

```bash
python scripts/check_public_boundary.py
python -m pytest -q
```

Additional targeted security/recovery/deployment checks remain required where relevant.

A manual-only GitHub Actions workflow may remain in the public shell for occasional use, but it must not trigger on every push or pull request.

## Historical-public-code caveat

Moving future development to a private repository does **not** erase versions of the engine that were already published in this repository's Git history.

The first migration goal is therefore:

> stop future proprietary development from being published.

History rewriting, repository replacement or archival of the old public history is a separate decision and should not be mixed into the initial split.

## Naming

Recommended private-core repository:

`SyedBasher/mangrove-climate-risk-core`

Visibility:

`Private`

Do not initialize it with a README, license or .gitignore if GitHub offers those options; an empty repository is easier to populate from the verified climate baseline.
