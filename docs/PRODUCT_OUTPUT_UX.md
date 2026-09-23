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
