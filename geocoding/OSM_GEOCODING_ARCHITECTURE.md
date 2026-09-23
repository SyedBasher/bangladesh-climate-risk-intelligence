# OSM geocoding architecture

## Pilot
A one-time 15-record benchmark may use the public OSMF Nominatim endpoint only under its usage
policy: one thread, at most one request per second, descriptive User-Agent and cached results.

## Production
Do not build recurring DIFE/customer portfolio geocoding on the public OSMF service.

Preferred production design:
1. download the Bangladesh `.osm.pbf` extract from Geofabrik;
2. pin and hash the extract/vintage;
3. run a self-hosted Nominatim instance for deterministic geocoding;
4. periodically refresh the PBF/index;
5. store OSM object ID/type and OSM vintage with each coordinate;
6. keep the OSM-derived geocoding database logically separated for ODbL compliance.

At the September 2026 audit, the Bangladesh PBF is roughly 338 MB, making country-specific
self-hosting operationally plausible. The public Nominatim policy explicitly discourages regular
bulk geocoding and warns commercial applications not to rely on the donated public service.
