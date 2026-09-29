# Architecture overview

Bangladesh Climate & Location Risk Intelligence uses four conceptual layers:

1. **Source evidence** — observed, satellite-observed, reanalysis, modelled and mapping datasets with provenance and vintage.
2. **Location/asset linkage** — defensible site identity and coordinates, with explicit quality grades.
3. **Indicators** — direct physical climate indicators and transparent exposure measures.
4. **Decision intelligence** — operational, logistics and portfolio diagnostics with explicit evidence guardrails.

The implementation is separated operationally:

- the **public repository** contains product information and public methodology;
- the **private core** contains the deployable analytical/application engine;
- **private infrastructure** contains real datasets, customer overlays and generated reports.

The product does not automatically convert hazard exposure into damage, downtime, PD/LGD, ECL, collateral haircuts or insurance loss, and it does not use a hidden composite climate-risk score.
