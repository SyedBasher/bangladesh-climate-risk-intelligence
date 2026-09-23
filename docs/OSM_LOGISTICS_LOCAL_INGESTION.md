# OSM Logistics & Route Resilience Local Ingestion 0.1

## Source

The production network is pinned to the dated Geofabrik Bangladesh extract:

- file: `bangladesh-260919.osm.pbf`
- OSM data timestamp: 2026-09-19T20:22:34Z
- publisher: Geofabrik, derived from OpenStreetMap
- public source page: https://download.geofabrik.de/asia/bangladesh.html

The pipeline deliberately uses a dated PBF rather than the moving `bangladesh-latest.osm.pbf`.

At download time it verifies the publisher MD5 and then records its own SHA-256 for long-run provenance.

## License boundary

OpenStreetMap data are available under the Open Database License (ODbL) 1.0.

Required attribution for maps/outputs using OSM data:
`© OpenStreetMap contributors`

The OSM-derived road network is kept logically separate from proprietary factory, borrower, portfolio and customer data. Public use of a derivative OSM database may trigger ODbL share-alike obligations, so the project does not merge proprietary customer tables into the OSM-derived network database.

This architecture is a data-governance precaution, not legal advice.

## No public routing APIs

Production routing does not depend on:
- public Overpass;
- public Nominatim;
- external consumer routing APIs.

The country network is built locally from the pinned PBF.

## Drivable network profile

The first freight-oriented profile includes:
- motorway/trunk/primary/secondary/tertiary and link classes;
- unclassified/residential/service/living-street/road;
- way-tagged ferry routes.

It excludes pedestrian-only roads and ways explicitly tagged private/no for access, vehicle or motor_vehicle.

OSM one-way rules, roundabouts and the implied one-way direction of motorways are respected.

Relation-only ferry routes may require additional handling in a later version.

## Distance rather than assumed travel time

Baseline routes minimize edge length in metres.

Version 0.1 does not invent truck speeds from road class. Travel-time routing can be added later using a governed speed model or observed travel-time data.

## Endpoint rule

The system never assumes that every factory uses Chattogram Port or any other destination.

A route exists only when the private data plane contains:
1. an explicit endpoint;
2. an explicit asset-to-endpoint dependency.

Endpoint types can include port, depot, warehouse, border crossing, airport or another user-defined destination.

## Snap QA

Assets and endpoints are snapped to the nearest routable OSM node.

Default QA:
- <=100 m: GOOD
- >100 m and <=500 m: REVIEW
- >500 m: REJECTED

The 500 m threshold is configurable and is a routing-data QA rule, not a risk threshold.

A rejected snap produces no route.

## Baseline route outputs

For each explicit dependency the pipeline stores:
- asset and endpoint snap distance;
- directed shortest-route distance;
- edge-disjoint route count;
- ordered OSM route edges;
- road class, bridge/ferry flags and OSM way ID;
- shared physical-edge counts across multiple dependencies.

Shared route usage allows identification of common logistics bottlenecks without using a composite score.

## JRC route exposure

The baseline route can be sampled against JRC river-flood RP depth.

Default:
- RP100
- sample spacing: 100 m along each OSM segment

For every sample:
- permanent-water mask is checked;
- spurious-depth mask is checked;
- unmasked JRC depth is sampled.

An edge is:
- EXPOSED when at least one valid unmasked sample has positive depth;
- NO_POSITIVE_DEPTH_SAMPLED when all samples are valid and none has positive depth;
- UNKNOWN_MASKED_OR_NODATA when no positive depth is found but at least one sample is masked or missing.

If any route length remains unknown, the route-level flood-exposed share is withheld rather than treating unknown road as safe.

## Exposure is not blockage

Version 0.1 does **not** infer road closure from JRC depth.

Therefore it does not publish:
- hazard-conditioned detour ratio;
- hazard-conditioned isolation;
- post-hazard route redundancy.

Those require an explicit and governed road-passability scenario applied to the full candidate routing graph, not only the baseline route.

This distinction is intentional:
`hazard_exposed != hazard_blocked`.

## Shared exposed bottlenecks

If an OSM physical edge:
- appears on more than one private asset route; and
- has valid JRC flood exposure,

it is written to the shared-hazard-bottleneck Parquet output with the number of route dependencies using that edge.

This is a transparent third-order concentration diagnostic.

## Workflow

Prepare the pinned local network:

    python scripts/prepare_osm_network_local.py

Import private endpoints:

    python scripts/import_route_endpoints.py --csv /secure/path/endpoints.csv

Import explicit asset-to-endpoint links:

    python scripts/import_route_dependencies.py --csv /secure/path/dependencies.csv

Calculate baseline routes:

    python scripts/run_osm_routes_local.py

Overlay RP100 JRC flood exposure:

    python scripts/run_route_flood_exposure_local.py --return-period 100

All real endpoints, routes, network Parquet, PBF data and customer linkages remain outside GitHub.
