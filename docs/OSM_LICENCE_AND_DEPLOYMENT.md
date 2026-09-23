# OSM licensing and deployment notes

- OpenStreetMap data are licensed under ODbL 1.0 and commercial use is permitted subject to the licence.
- Published Produced Works require appropriate attribution.
- If Mangrove publicly distributes an OSM-derived database, share-alike/database obligations may apply.
- Keep the OSM road/geocoding/network database logically separated from proprietary customer and
  Mangrove analytical tables.
- Treat final route diagnostics as analytical outputs with explicit OSM attribution where required.
- Do not depend on OSMF public Nominatim, public tiles or public Overpass for recurring commercial workloads.
- Production should ingest a pinned Geofabrik extract into Mangrove-controlled infrastructure.

This file is an engineering/licence architecture note, not legal advice. Review the final commercial
distribution model against current OSMF licence guidance before launch.
