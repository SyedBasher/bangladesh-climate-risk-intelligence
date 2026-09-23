# Intelligent Product Blueprint v0.1

The product should answer more than "what hazard is here?" while remaining auditable.

## Layer A — Direct physical evidence
Examples:
- RP10/RP50/RP100 modelled flood depth
- observed Sentinel-1 flood detections and observation denominator
- water-level anomaly
- extreme-heat days and heat trend
- extreme rainfall
- drought/soil-moisture anomaly
- cyclone proximity/wind layer when available
- elevation, river distance, surface water
- water stress / salinity where defensible

## Layer B — Exposure arithmetic
No damage functions are required:
- workers × heat days
- workers located inside return-period flood footprints
- population within exposed radius
- factory count and workforce inside hazard polygon
- EAD/collateral/sum-insured located inside a hazard footprint
- route length intersecting hazard
- built-up growth occurring inside a fixed hazard footprint

## Layer C — Operational transmission
Evidence-backed questions/signals:
- Is the plant accessible if its primary road floods?
- Do all alternative routes cross the same hazard footprint?
- Is the site water-dependent in a stressed basin?
- Does heat exposure coincide with a large shift workforce?
- Are multiple facilities dependent on the same substation/road/port?
- Does an acute event occur before recovery from a previous event?

These are analytical signals, not arbitrary scores.

## Layer D — Financial/network propagation
With customer or linked Mangrove data:
- bank EAD and collateral concentration by hazard
- insured accumulation by floodplain/cyclone corridor
- export production and buyer concentration in exposed clusters
- supplier/factory/warehouse network dependencies
- portfolio concentration where many borrowers share one physical bottleneck

## Layer E — Research-calibrated scenario models
Only later, where evidence is strong enough:
- downtime functions
- physical damage functions
- heat-productivity functions
- PD/LGD adjustments
- collateral valuation haircuts

Every model must identify evidence source, geography, sector, calibration sample, uncertainty,
validation status and version. No coefficient enters production merely because it appears in a paper.

## High-value intelligence features
1. **Level vs trend matrix** — distinguishes places that are already hazardous from places whose hazard is worsening fastest.
2. **Compound-event timelines** — measures sequential/coincident hazards rather than a generic compound score.
3. **Portfolio accumulation** — identifies many assets sharing the same floodplain, road corridor or cyclone footprint.
4. **Route redundancy** — asks whether a factory can still reach a highway/port under a hazard scenario.
5. **Hazard-development mismatch** — detects industrial/built-up expansion into hazard footprints.
6. **Pareto site comparison** — compares investment locations without arbitrary weighting.
7. **Research lineage** — each analytical statement links to supporting evidence and automatically warns when evidence is revised/retracted.
8. **What-data-would-change-the-answer** — the engine reports which missing customer variable would materially improve inference.

This is the distinction between a climate map and an intelligence product.
