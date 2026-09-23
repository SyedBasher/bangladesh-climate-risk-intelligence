# Bangladesh OSM road graph build

## Production source
Use a **dated** Geofabrik Bangladesh `.osm.pbf`, never only the mutable `latest` file.

Pinned pilot target:
- `bangladesh-260919.osm.pbf`
- index size: 354,702,917 bytes
- source page verified 2026-09-23

After download:
1. calculate SHA-256 and retain source MD5 if supplied;
2. store PBF in the OSM/ODbL-controlled raw layer;
3. parse routable highway ways and nodes;
4. retain OSM way/node IDs and relevant tags;
5. build topology;
6. project geometries to a suitable metric CRS for spatial calculations;
7. create directed edges where one-way restrictions require it;
8. preserve bridge/tunnel/ferry/access/maxweight/maxheight/surface tags where available;
9. derive a separate freight-routing graph;
10. keep OSM attribution and licence metadata with any published Produced Work.

The current runtime does not contain `osmium`, `pyrosm` or `osmnx`, and the external PBF download
was blocked. Route analysis code is therefore tested against deterministic graph fixtures rather
than pretending that a national OSM graph was built here.

## Parser choice
Production options:
- `osmium-tool` + custom/PostGIS loading;
- self-managed `osm2pgsql`;
- a pinned `pyrosm`/OSM parser environment.

Do not make the public Overpass or Nominatim services part of recurring production ingestion.

## Separation
Keep OSM-derived network tables logically separate from proprietary customer exposure tables.
Join through internal edge/node identifiers and asset-route result tables.
