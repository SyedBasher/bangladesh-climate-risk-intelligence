# Observed Flood & Event Validation 0.1

This layer adds event evidence to the static/modelled physical-risk stack.

It does not replace the JRC return-period flood model. Instead it asks a different question: **what observed flood evidence was available around this asset during a defined event window?**

## 1. Global Flood Monitoring (GFM)

Production source:
- Copernicus Emergency Management Service
- Global Flood Monitoring
- Sentinel-1 SAR-based flood detection
- final ensemble flood extent and supporting quality/mask layers
- 20 m processing resolution
- archive from 2015 onward
- official STAC catalogue at https://stac.eodc.eu/api/v1

### GFM is acquisition-based evidence

GFM is not a daily rain gauge or continuous camera.

A site can only be evaluated when an eligible Sentinel-1 acquisition covers it. The product therefore stores matched STAC item count, covered acquisition count, eligible acquisition count, flood-positive acquisition count, advisory-flagged eligible acquisition count, and flood-positive acquisition rate.

The denominator of the detection rate is **eligible acquisitions**, never calendar days.

The rate is not annual flood probability, return period, percentage of days flooded, or expected annual loss.

### Eligibility

For each acquisition the pipeline samples ensemble flood extent, exclusion mask, reference-water mask, ensemble likelihood, and advisory flags where available.

A point is eligible only when flood extent has source coverage, the exclusion mask is zero, and the reference-water mask is zero.

A nonzero advisory flag does not automatically remove the acquisition. It is retained as an explicit caution flag.

### Non-detection

No GFM detection during an event window does **not** prove the site did not flood.

Possible reasons include no eligible Sentinel-1 acquisition during the critical hours, flood duration shorter than revisit timing, source exclusions, sensor/algorithm sensitivity, or mismatch between the event window and actual inundation timing.

The system therefore reports eligible acquisition counts alongside every detection result.

## 2. JRC model versus GFM event evidence

The event layer compares the latest available JRC point-depth indicator with GFM observations without treating one as a substitute for the other.

Possible evidence relations include:
- MODELLED_AND_OBSERVED
- OBSERVED_FLOOD_REVIEW_MODELLED_POINT_HAZARD
- MODELLED_NO_GFM_DETECTION_IN_WINDOW
- NO_GFM_DETECTION_AND_NO_MODELLED_POINT_DEPTH
- OBSERVED_FLOOD_MODELLED_POINT_VALUE_UNAVAILABLE
- NO_GFM_DETECTION_MODELLED_POINT_VALUE_UNAVAILABLE
- NO_ELIGIBLE_GFM_EVIDENCE
- NO_COMPARABLE_EVENT_EVIDENCE

These are evidence states, not model-accuracy scores.

In particular, MODELLED_NO_GFM_DETECTION_IN_WINDOW does not mean the return-period model is wrong. JRC and GFM differ in time concept, model/observation basis, spatial support and event timing.

The event-comparison indicator inherits the complete JRC source lineage, including depth and relevant mask/tile artifacts, plus the GFM event-source subset.

## 3. FFWC / BWDB official water-level context

Bangladesh Flood Forecasting & Warning Centre water-level observations provide official gauge context for flood events.

A nearby river station is not the same thing as the factory site.

The pipeline therefore stores the exact official station metadata snapshot, exact official observation snapshot, station coordinate, asset-to-station distance, observation count within the event window, maximum observed station water level, and maximum amount above the station danger level where a danger level is available.

The output is named **station context** rather than site water depth. No spatial interpolation from river gauge to factory is performed.

## 4. FFWC ingestion contract

The current official FFWC browser interface is dynamic. A stable, documented production API contract has not yet been adopted by this repository.

Version 0.1 therefore does **not** scrape an undocumented endpoint.

Instead the operator supplies an exact official CSV export/snapshot plus its official source URL. The local pipeline then copies the exact snapshot into private content-addressed storage, calculates SHA-256, records the official URL and retrieval provenance, imports station/observation fields into SQLite, and links private assets to the nearest imported stations.

When a stable documented API is verified, it can replace the snapshot acquisition step without changing the downstream schema.

## 5. Asset geocode rules

GFM point sampling uses only EXACT_SITE + RESOLVED because the flood extent layer is fine-resolution and asset-specific.

FFWC station context can use EXACT_SITE + RESOLVED or PROBABLE_SITE + RESOLVED because the output is explicitly a distance-based regional gauge context, not a point flood-depth estimate.

## 6. FFWC station linkage

Default linkage stores the three nearest official stations by straight-line distance. Event reporting uses the nearest station by default.

This is a transparent geographic context rule. It does not claim the nearest station is hydrologically representative of the asset. A later version can add basin/river-network compatibility where the necessary official geometry is available.

## 7. Private workflow

GFM event:

    python scripts/run_gfm_event_local.py --start 2025-07-15T00:00:00Z --end 2025-07-20T23:59:59Z

FFWC stations:

    python scripts/import_ffwc_stations.py --csv /secure/path/ffwc_stations.csv --source-url https://official-ffwc-source/...

FFWC observations:

    python scripts/import_ffwc_observations.py --csv /secure/path/ffwc_observations.csv --source-url https://official-ffwc-source/...

Link assets:

    python scripts/link_assets_ffwc.py --top-k 3

Event station context:

    python scripts/run_ffwc_event_context_local.py --start 2025-07-15T00:00:00+06:00 --end 2025-07-20T23:59:59+06:00

## 8. Interpretation boundary

This layer can support statements such as:
- an eligible Sentinel-1 acquisition detected flood at the asset coordinate;
- no eligible acquisition detected flood during the specified window;
- the nearest imported FFWC station exceeded its official danger level during the event;
- JRC modelled hazard and observed event evidence point in the same or different directions.

It cannot by itself establish building inundation depth, duration of site shutdown, damage, worker impact, default probability, insurance loss, or causal attribution to climate change.

Those require additional evidence and separately governed methods.
