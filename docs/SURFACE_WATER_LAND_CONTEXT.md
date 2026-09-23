# Surface Water & Land Context 0.1

This layer adds two fine-resolution environmental context families around exact private asset locations:

1. long-run open-surface-water history from JRC Global Surface Water;
2. 10 m land-cover context from ESA WorldCover.

Neither source is converted into a composite score.

## 1. JRC Global Surface Water v1.5

Production source:
- European Commission Joint Research Centre
- Global Surface Water Explorer
- version 1.5
- 1984-2024 long-run aggregate products
- Landsat-derived
- 10° × 10° GeoTIFF tiles

Source catalogue:

https://global-surface-water.appspot.com/download

Version 0.1 uses:
- Occurrence
- annual Recurrence

Version 0.1 deliberately does **not** use Monthly Recurrence.

The JRC update notes identify a known issue in the long-term Monthly Recurrence layer that can lower values where observations are sparse. The correction is still pending.

### Why v1.5

The 2024 release extends the record through 2024.

The JRC also reports that occurrence values in versions 1.2-1.4 contained inconsistencies in the added post-v1.0 years. The v1.5 occurrence layer reprocesses those years against the original baseline and is therefore the preferred current long-run occurrence product.

The JRC notes a Collection 1 / Collection 2 transition after 2021. Residual co-registration offsets can be spatially variable and may approach or exceed one 30 m pixel in some Landsat path/rows.

This matters for exact-site interpretation near narrow water boundaries.

## 2. Occurrence and recurrence are not flood frequency

Surface Water Occurrence measures how often valid satellite observations at a pixel were classified as open water over the long-run record.

Annual Recurrence describes how consistently surface water returns from year to year.

These fields can include:
- rivers;
- lakes;
- reservoirs;
- wetlands/open water;
- irrigation/flooded agriculture;
- artificial water bodies;
- coastal water visible to Landsat.

They do not identify the physical cause of the water.

Therefore:

- occurrence ≠ river-flood frequency;
- recurrence ≠ annual probability of damaging flood;
- surface-water detection ≠ building inundation;
- water occurrence ≠ expected loss.

JRC river-flood return-period depth and GFM event flood detection remain separate evidence layers.

## 3. Point indicators

For each EXACT_SITE + RESOLVED asset:

- jrc_gsw15_occurrence_pct_at_site
- jrc_gsw15_recurrence_pct_at_site

Values remain the JRC 0-100 percentage fields.

Missing source pixels remain null.

## 4. Distance to high-occurrence surface water

Version 0.1 also calculates distance from the asset coordinate to the nearest GSW occurrence pixel meeting an explicit threshold.

Default:
- occurrence threshold: >=90%
- search radius: 20 km

Default indicator:

    jrc_gsw15_distance_to_occurrence_ge90pct_water_m

This is a Mangrove analytical definition.

It does **not** rename the JRC source pixel as officially “permanent water.” The wording used in methodology and output is **high-occurrence surface water**.

The threshold and search radius are retained in the method metadata.

If no qualifying pixel is found inside the search radius:
- value = null
- null reason = NO_HIGH_OCCURRENCE_WATER_WITHIN_SEARCH_RADIUS

The system does not store the search-radius boundary as the distance and does not claim that no qualifying water exists beyond it.

## 5. ESA WorldCover 2021 v200

Production source:
- ESA WorldCover consortium
- WorldCover 2021
- algorithm version v200
- 10 m global land-cover map
- Cloud-Optimized GeoTIFF
- EPSG:4326
- CC BY 4.0

Official data access:

https://esa-worldcover.org/en/data-access

The tiles are retrieved from the public ESA WorldCover AWS Open Data bucket.

Attribution:

© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium

## 6. WorldCover classes

Version 0.1 preserves the eleven source classes:

- 10 Tree cover
- 20 Shrubland
- 30 Grassland
- 40 Cropland
- 50 Built-up
- 60 Bare / sparse vegetation
- 70 Snow and ice
- 80 Permanent water bodies
- 90 Herbaceous wetland
- 95 Mangroves
- 100 Moss and lichen

The direct site class is stored as both code and label.

## 7. Surrounding land-cover composition

For each exact site, version 0.1 calculates class shares among valid WorldCover pixels inside:

- 250 m
- 1 km

Examples:

- worldcover2021_built_up_share_within_250m
- worldcover2021_cropland_share_within_1000m
- worldcover2021_permanent_water_bodies_share_within_1000m
- worldcover2021_mangroves_share_within_1000m

The workflow also stores the valid-pixel share for each radius.

If less than 95% of the selected pixels contain a recognised WorldCover class:
- land-cover class shares are null;
- quality flag = LOW_VALID_PIXEL_COVERAGE.

The valid-pixel-share diagnostic itself remains visible.

## 8. WorldCover is land cover, not cadastral land use

WorldCover can support environmental context such as:
- predominantly built-up surroundings;
- agricultural landscape;
- proximity to permanent-water/wetland landscapes;
- mangrove/coastal context;
- vegetation setting.

It does not establish:
- zoning;
- legal land use;
- industrial permit status;
- land ownership;
- parcel boundary;
- factory footprint;
- floor area;
- land or property value.

Those require cadastral, planning or asset-specific evidence.

## 9. No change detection from WorldCover 2020 versus 2021

WorldCover 2020 v100 and WorldCover 2021 v200 were produced with different algorithm versions.

The project therefore does not interpret differences between the two maps as land-cover change.

A governed change-detection module would need a temporally consistent source/method.

## 10. Geocoding rule

Both JRC GSW (~30 m) and ESA WorldCover (10 m) are fine-resolution context layers.

Version 0.1 requires:
- EXACT_SITE
- RESOLVED coordinate

PROBABLE_SITE is not sufficient.

## 11. Source lineage

JRC indicators retain exact v1.5 occurrence/recurrence tile source artifacts.

The distance calculation retains all occurrence tiles intersecting the configured search area.

WorldCover point and radius indicators retain every source tile contributing to the calculation.

All downloaded GeoTIFFs remain in private content-addressed source storage with SHA-256 provenance.

## 12. Private workflow

JRC Global Surface Water:

    python scripts/run_surface_water_context_local.py

WorldCover:

    python scripts/run_worldcover_land_context_local.py

Optional WorldCover radii:

    python scripts/run_worldcover_land_context_local.py --radii-m 250 1000

All downloaded source tiles, real asset coordinates, Parquet outputs, SQLite indicators and client outputs remain outside GitHub.

## 13. Interpretation example

A defensible statement might say:

“The exact asset coordinate has low long-run JRC surface-water occurrence, while high-occurrence surface water lies approximately X metres away. ESA WorldCover 2021 classifies the site pixel as built-up, with Y% built-up and Z% cropland pixels within 1 km.”

It should not say:

“The site floods every X years,” or “the factory is legally zoned industrial.”

Those conclusions are not established by these sources.
