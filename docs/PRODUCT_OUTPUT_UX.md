# Product Output & User Experience 0.1

The product interface should preserve the analytical hierarchy rather than compressing everything into one score.

## Asset screen

Recommended order:

1. **Asset identity and data quality**
   - asset type and sector
   - site-identity grade
   - coordinate status/precision
   - data freshness

2. **Direct physical evidence**
   - flood depth by return period
   - observed flood history where available
   - heat level, warm nights and trend
   - rainfall extremes
   - elevation/terrain
   - water stress/salinity/cyclone context where defensible

   Every value displays measurement basis, source, vintage, period and quality flag.

3. **Second-order exposure**
   - workers × heat days
   - workers/machines/capacity located in an inundation footprint
   - exposed route share
   - route redundancy loss
   - development occurring inside hazard footprints

4. **Third-order intelligence**
   - logistics bottlenecks
   - shared infrastructure dependence
   - bank/collateral exposure concentration
   - insured accumulation
   - correlated portfolio exposure

5. **Evidence panel**
   - research item
   - geography/sector transferability
   - permitted use
   - guardrail

6. **What data would change the answer?**
   - floor/equipment elevation
   - shift workers and operating hours
   - cooling/backup power
   - water source/use
   - route/port dependency
   - EAD/collateral/sum insured

## Compound / cross-asset screen

Recommended order:

1. **Input completeness and scope**
   - tenant scope
   - target year
   - return period
   - matched input vintages/runs

2. **Temporal co-occurrence**
   - heat + SPI-3 monthly evidence
   - heat + SPI-12 monthly evidence
   - complete-month and complete-year status

3. **Site + logistics evidence**
   - site-only, route-only, both, neither
   - incomplete route coverage shown separately
   - route exposure never labelled as closure

4. **Shared bottlenecks**
   - flood-exposed physical edges used by multiple distinct assets
   - distinct asset and route-dependency counts
   - no economic-loss weighting unless separately governed

5. **Cross-asset metrics**
   - counts and shares
   - denominator shown next to every share
   - incomplete assets excluded from denominators, not treated as unexposed

6. **Input manifest and guardrails**
   - source/dataset hashes
   - processing-run IDs
   - method versions
   - what the evidence does and does not establish

## Portfolio screen

Recommended order:

1. portfolio coverage/readiness;
2. EAD/collateral/sum-insured by hazard footprint;
3. borrower/sector/geographic concentration;
4. shared hazard-cell and route-bottleneck accumulation;
5. regulatory scenarios shown separately;
6. missing-data priorities.

## Presentation rules

- No overall climate-risk score.
- Do not use red/amber/green labels unless a customer explicitly defines a governed threshold scheme.
- Show nulls and blocked values explicitly rather than hiding them.
- Distinguish observed, modelled, reanalysis and calculated values visually and textually.
- Findings should say what the evidence establishes and what it does not establish.
- Regulatory sensitivity scenarios must not look like Mangrove forecasts.

## Public demo

Public examples use synthetic assets and synthetic values only. Production screens are populated from private infrastructure and never require the public repository to contain the underlying asset database.
