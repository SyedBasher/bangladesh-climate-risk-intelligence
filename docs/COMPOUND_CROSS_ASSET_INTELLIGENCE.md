# Compound Hazard & Cross-Asset Intelligence 0.1

This layer combines previously governed evidence streams without collapsing them into a composite climate-risk score.

It answers four distinct questions:

1. when did heat and meteorological drought occur in the same month?
2. is a site inside a modelled flood footprint, and are its explicit logistics routes also flood-exposed?
3. which flood-exposed road edges are shared by more than one distinct asset?
4. how many assets meet each transparent evidence condition, using an explicit valid-data denominator?

## 1. Same-month heat and drought

Inputs:
- ERA5-Land daily maximum temperature;
- CHIRPS SPI-3 and SPI-12.

The join is monthly and uses the same target year.

For each asset/month the workflow keeps:
- number of daily maxima above 35°C;
- number above 38°C;
- monthly maximum daily Tmax;
- SPI-3;
- SPI-12;
- data-quality states for heat and each SPI series.

### Co-occurrence definition

A heat–SPI-3 co-occurrence month requires:
- complete valid daily-maximum temperature coverage for the month;
- valid SPI-3;
- at least one day with Tmax >35°C;
- SPI-3 <= -1.

SPI-12 is handled separately using the same heat condition.

The output also counts the number of >35°C days that occurred inside months where SPI <= -1.

These thresholds are explicit analytical definitions. They are not weights in a score.

The annual outputs are:
- compound_heat_drought_spi3_cooccurrence_month_count
- compound_heat_days_gt35_during_spi3_le_minus1_months
- compound_heat_drought_spi12_cooccurrence_month_count
- compound_heat_days_gt35_during_spi12_le_minus1_months

If any month required for a scale is incomplete, including a calendar day whose temperature value is missing, the corresponding annual metric is null rather than extrapolated.

If a month contains **no valid temperature observations at all**, the monthly >35°C and >38°C day counts are also null rather than zero. The row remains flagged `INCOMPLETE_HEAT_MONTH`; absence of observations is not represented as absence of hot days.

## 2. What heat–drought co-occurrence does not mean

The calculation establishes temporal co-occurrence of two environmental conditions.

It does not establish:
- factory production loss;
- crop yield loss;
- water shortage;
- worker illness;
- electricity failure;
- causal interaction between heat and drought;
- an economic damage multiplier.

Those require additional operational or sector-specific evidence.

## 3. Site flood versus route flood

Inputs:
- latest asset-level JRC flood depth for the selected return period;
- route-flood summary from the matching route analysis.

The default comparison is RP100.

The evidence-state taxonomy is:

- SITE_AND_ROUTE_EXPOSED
- SITE_ONLY_EXPOSED
- ROUTE_ONLY_EXPOSED
- NEITHER_POINT_NOR_ROUTE_EXPOSED
- SITE_HAZARD_UNAVAILABLE
- NO_ROUTE_DEPENDENCY
- ROUTE_HAZARD_COVERAGE_INCOMPLETE

The first four states are produced only when site depth is available and every route dependency has complete route-hazard coverage.

A route is called exposed when its JRC overlay contains positive unmasked modelled depth.

**Exposed does not mean blocked.**

No detour, isolation, closure duration or delivery delay is inferred in this layer.

## 4. Shared flood-exposed bottlenecks

The route-edge layer is grouped by OSM physical edge.

An edge is a shared cross-asset bottleneck only when:
- the edge has positive JRC route-flood exposure; and
- more than one distinct asset uses that physical edge.

Multiple routes or endpoints from the same asset do not by themselves make an edge cross-asset.

For every shared edge the private detail table retains:
- physical edge key;
- OSM way ID;
- road class;
- bridge/ferry flag;
- edge length;
- maximum sampled unmasked JRC depth;
- distinct asset count;
- distinct route-dependency count;
- pseudonymous asset keys.

This is dependency concentration, not expected disruption or economic loss.

An empty shared-edge result has two distinct meanings and they are not collapsed:

- when tenant route-edge evidence exists and no qualifying shared exposed edge is found, the governed count is zero with quality `OK`;
- when no tenant route-edge evidence is available, shared-bottleneck metrics are null with quality `NO_ROUTE_EDGE_EVIDENCE`.

Missing route-edge evidence is therefore not treated as zero shared exposure.

The summary function requires the caller to state route-edge evidence availability explicitly; there is no optimistic default that can silently turn an empty evidence frame into a valid zero.

## 5. Cross-asset summaries

The first release provides transparent counts/shares such as:

- assets with at least one heat–SPI-3 co-occurrence month;
- share of assets with heat–SPI-3 co-occurrence;
- equivalent SPI-12 measures;
- RP100 assets with both site and route exposure;
- share of comparable assets with both site and route exposure;
- number of flood-exposed physical edges shared by multiple assets;
- number of distinct assets using those shared edges;
- maximum distinct assets using one flood-exposed edge.

Every share stores its denominator.

Assets with incomplete input evidence are excluded from the denominator rather than being treated as unexposed.

## 6. No multiplication or weighted index

Version 0.1 does not:
- add hazard indicators together;
- multiply probabilities;
- weight heat versus flood versus drought;
- convert counts into low/medium/high categories;
- create a composite risk score;
- rank assets from best to worst.

The user sees the evidence dimensions separately.

## 7. Single-tenant scope

A compound run is scoped to one tenant.

The default local tenant is INTERNAL.

Cross-asset metrics never combine unrelated customer portfolios or organisations.

## 8. Input-vintage matching

The workflow selects inputs by explicit partition:

- ERA5-Land daily maximum: requested year + daily_maximum;
- CHIRPS SPI: requested year;
- route flood: requested JRC return period.

The route-edge input must have the same processing run ID as the selected route-flood summary.

This prevents silent mixing of different route or hazard runs.

## 9. Lineage

Asset-level compound indicators retain both sides of the source chain:
- COMPOUND_HEAT;
- COMPOUND_DROUGHT;
- COMPOUND_SITE_FLOOD;
- COMPOUND_ROUTE_FLOOD.

Cross-asset metrics retain raw source-artifact lineage plus an input manifest containing:
- derived dataset name;
- private dataset ID;
- SHA-256;
- partition specification;
- producing run ID.

The detailed compound joins remain private Parquet.

Heat/drought cross-asset metrics fail closed when required heat or drought source lineage cannot be read or resolved. Provenance-read errors are not converted into empty source lists.

## 10. Private workflow

Run:

    python scripts/run_compound_cross_asset_local.py --year 2025 --return-period 100 --tenant INTERNAL

The command writes:
- monthly heat–drought evidence;
- annual heat–drought asset indicators;
- flood/route asset evidence states;
- shared flood-exposed cross-asset edges;
- cross-asset summary metrics.

## 11. Interpretation example

A defensible statement might say:

“Two of eight assets with complete 2025 heat/SPI evidence had at least one month with Tmax above 35°C and SPI-3 at or below −1. Separately, three of six assets with complete RP100 site and route evidence were exposed both at the site point and along at least one explicit logistics route.”

It should not say:

“These assets have twice the climate risk,” or “expected losses will double.”

The evidence does not establish either conclusion.
