# Decision Reports & Portfolio Workspace 0.1

This layer assembles the already-governed asset, compound/cross-asset, and portfolio outputs into a decision-facing report object.

It does not replace the analytical engine and it does not introduce an overall climate-risk score.

## Purpose

The workspace is designed to answer, in one auditable object:

1. what is directly known;
2. what is calculated;
3. what compound or cross-asset evidence exists;
4. what operational transmission channels may matter;
5. where evidence is incomplete;
6. what additional data would materially change the analysis;
7. where each claim or metric came from.

The same structured object can later support a private web application, printable HTML report, or database-backed workspace without rewriting the underlying hazard and portfolio methods.

## Architecture

The first decision-workspace assembler is implemented in:

- `src/clr/decision_reports.py`

The public contract is:

- `contracts/decision_workspace_report.schema.json`

The assembler consumes existing governed report payloads:

- `ASSET_INTELLIGENCE`
- `COMPOUND_CROSS_ASSET_INTELLIGENCE`
- `PORTFOLIO_INTELLIGENCE`

These remain separate source modules. The workspace does not silently recompute their hazard metrics.

## Report hierarchy

The top-level object contains:

1. **Executive evidence summary**
   - short evidence statements;
   - every non-missing-data statement requires explicit `source_refs`;
   - the assembler does not auto-generate narrative conclusions.

2. **Data readiness**
   - site-identity grade and coordinate status when an asset report is present;
   - additional completeness or vintage fields may be supplied explicitly.

3. **Direct physical evidence**
   - copied from the governed asset report;
   - source/provider identifiers, source vintage, measurement basis, value class, quality flag and null reason are preserved.

4. **Second-order exposure**
   - findings already classified as `SECOND_ORDER...` by the asset intelligence layer.

5. **Compound evidence**
   - asset-level compound evidence already produced by the compound module.

6. **Operational transmission**
   - non-second-order governed findings plus explicitly supplied operational evidence;
   - this section can later carry cooling, backup power, workforce, water-source, elevation or other customer-supplied operational evidence.

7. **Logistics dependencies**
   - explicit route, port or infrastructure dependencies supplied to the workspace;
   - route hazard exposure is never interpreted as closure.

8. **Cross-asset / portfolio**
   - compound cross-asset metrics;
   - shared bottlenecks;
   - portfolio exposure/concentration metrics.

9. **Evidence provenance**
   - explicit provenance records;
   - compound input manifests are retained.

10. **What data would change the answer?**
    - structured data requests;
    - fields include the missing data item, why it matters, the decision question and the source module where applicable.

11. **Guardrails**
    - inherited module guardrails plus workspace-level guardrails.

## Fail-closed rules

The workspace rejects:

- empty tenant or subject identifiers;
- unsupported scope types;
- direct-evidence rows missing required provenance;
- null direct evidence without a null reason;
- share metrics without an explicit denominator;
- null cross-asset metrics marked `OK`;
- ungoverned `EXPECTED_LOSS`, `PREDICTED_PD` or `PREDICTED_LGD` portfolio classifications;
- score fields such as `risk_score`, `climate_risk_score`, `composite_score` or `composite_risk_score`.

These checks apply at assembly time so an interface cannot silently turn incomplete evidence into a complete-looking report.

## Executive evidence summary

Version 0.1 deliberately does not write executive conclusions automatically.

Every evidence statement must specify:

- a statement ID;
- plain-language text;
- an evidence class;
- source references, except for a missing-data statement;
- an optional guardrail.

Permitted evidence classes are:

- `DIRECT`
- `CALCULATED`
- `COMPOUND`
- `OPERATIONAL`
- `CROSS_ASSET`
- `MISSING_DATA`

This keeps the distinction between source evidence, calculations, compound evidence and decision questions visible.

## Explicit denominators

Any compound cross-asset metric with `unit = "share"` must carry a denominator.

An incomplete asset is excluded from the governed denominator rather than counted as unexposed.

## Financial outputs

The base workspace may display governed exposure and concentration quantities such as EAD or collateral exposure when supplied by the customer portfolio layer.

It does not infer:

- probability of default;
- loss given default;
- expected credit loss;
- insurance loss;
- collateral haircut;
- downtime;
- production loss.

Those require separately governed models and additional evidence.

## Public/private boundary

Public GitHub may contain:

- the assembler;
- the report contract;
- methodology;
- tests;
- synthetic examples.

Public GitHub must not contain:

- real asset coordinates;
- real factory or borrower identities;
- customer portfolio records;
- private SQLite or Parquet outputs;
- source rasters or snapshots;
- generated client reports.

## Next implementation step

The next component should be a printable HTML renderer and synthetic public demonstration generated from the structured workspace object.

The renderer should remain a pure presentation layer: it must not calculate new hazard values, invent narrative conclusions, or add hidden scoring.
