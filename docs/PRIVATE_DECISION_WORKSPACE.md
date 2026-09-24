# Private Decision Workspace Adapter 0.1

This adapter connects the governed public report architecture to the gitignored local SQLite/Parquet data plane.

It is deliberately conservative. It does not choose the "latest" analytical run automatically.

## Purpose

The adapter can assemble either:

- one private asset report; or
- one private portfolio report.

It then optionally attaches:

- one explicit compound/cross-asset run;
- one explicit logistics run.

The resulting structured JSON, printable HTML and selection manifest are written only under the initialized private workspace:

`outputs/reports/{tenant}/{scope}/{subject}/`

Nothing in this workflow writes a real client report to public GitHub.

## Command

Asset example:

```bash
python scripts/run_private_decision_workspace.py \
  --scope ASSET \
  --tenant INTERNAL \
  --asset-location-id <PRIVATE_ASSET_LOCATION_ID> \
  --indicator-run <ERA5_OR_OTHER_RUN_ID> \
  --indicator-run <JRC_RUN_ID> \
  --compound-run <COMPOUND_RUN_ID> \
  --route-run <ROUTE_RUN_ID>
```

Portfolio example:

```bash
python scripts/run_private_decision_workspace.py \
  --scope PORTFOLIO \
  --tenant INTERNAL \
  --portfolio-id <PRIVATE_PORTFOLIO_ID> \
  --indicator-run <JRC_RUN_ID> \
  --compound-run <COMPOUND_RUN_ID>
```

The private workspace root defaults to `CLR_PRIVATE_DATA`, then to `private_data/`.

## Explicit run selection

At least one `--indicator-run` is required.

Every selected run must:

- exist in `processing_run`;
- have status `SUCCESS`.

The adapter rejects:

- `RUNNING`;
- `PARTIAL`;
- `FAILED`;
- unknown run IDs.

If two explicitly selected runs contain the same indicator for the same asset and period, the adapter fails rather than deciding silently which vintage to use.

Compound and logistics runs are also explicit.

A compound run must have a tenant compatible with the requested tenant and must carry positive `year` and `return_period` parameters.

## Asset resolution

Asset scope accepts either:

- `--asset-location-id`; or
- both `--external-system` and `--external-id`.

An ambiguous current asset match is blocked. The user must then provide the private `asset_location_id` explicitly.

Coordinates are used by upstream analytical pipelines but are not copied into the decision report.

## Source provenance

For every selected asset indicator the adapter retains:

- processing run ID;
- pipeline name/version;
- producing git commit where recorded;
- indicator method version;
- source ID/provider;
- provider version or retrieval vintage;
- source-artifact SHA-256;
- source role;
- quality flag;
- null reason.

If an indicator has no registered source lineage, it is not silently presented as fully valid. An otherwise-`OK` row is labelled `MISSING_SOURCE_LINEAGE` in the report.

## Compound / cross-asset evidence

The adapter reads `cross_asset_metric` only for the explicit compound run.

Share denominators are recovered from the governed input manifest.

For detailed shared bottlenecks, the adapter may read the registered private Parquet dataset:

`compound_shared_flood_route_edges`

Before reading it, the adapter verifies:

1. the registered path remains inside the private workspace;
2. the file exists;
3. its SHA-256 still matches the catalog.

No unregistered Parquet file is discovered or guessed.

## Portfolio arithmetic

Version 0.1 supports transparent footprint arithmetic for:

- EAD;
- collateral value;
- sum insured.

The selected hazard indicator defaults to:

`flood_rp100_depth_m`

The portfolio metric uses only exposure rows with both:

- a linked asset; and
- a valid selected hazard value.

Missing hazard evidence is not treated as zero exposure.

Financial aggregation is blocked if the same exposure type contains multiple currencies. Currency conversion must happen upstream with an explicit FX vintage.

The adapter does not calculate:

- PD;
- LGD;
- ECL;
- insurance loss;
- collateral haircut;
- downtime;
- production loss.

## Portfolio-data vintage limitation

The current `portfolio_exposure` table stores `valuation_date` but does not yet maintain a run-versioned history of portfolio snapshots.

The adapter therefore:

- preserves the valuation dates present in the selected portfolio;
- does not claim that it can reconstruct an earlier portfolio snapshot.

A future schema version can add explicit portfolio-snapshot versioning if customer workflows require it.

## Output safety

The writer requires the `.private-data-root` marker created by:

```bash
python scripts/init_private_workspace.py
```

If that marker is absent, report generation stops.

The report writer creates:

- `.json` structured decision workspace;
- `.html` printable decision report;
- `.manifest.json` selection and output-hash manifest.

The manifest records the exact selected run IDs and SHA-256 hashes of the generated JSON and HTML.

Paths returned to the command line are relative to the private workspace so workstation-specific absolute paths are not leaked in routine logs.

## Public/private boundary

Public GitHub contains only:

- adapter code;
- command wrapper;
- methodology;
- synthetic tests.

Private workspace contains:

- real asset identifiers and coordinates;
- portfolio records;
- selected analytical evidence;
- generated JSON/HTML reports;
- output manifests.

## Next step

After this adapter is proven on private local data, the next product layer can be a private authenticated workspace/app shell that calls the same adapter and renderer.

That interface should not bypass explicit run/vintage selection, tenant isolation, lineage checks, or the fail-closed rules.
