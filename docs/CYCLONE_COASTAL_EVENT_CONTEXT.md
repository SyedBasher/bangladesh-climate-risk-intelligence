# Cyclone & Coastal Event Context 0.1

This layer adds historical tropical-cyclone track context to private assets.

It is deliberately **not** a site-wind, storm-surge, inundation-depth, damage or loss model.

## 1. Source

Production source:
- NOAA National Centers for Environmental Information
- International Best Track Archive for Climate Stewardship (IBTrACS)
- Version 4r01
- North Indian basin subset
- official CSV distribution

Source URL:

https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.NI.list.v04r01.csv

The North Indian basin subset is used rather than the global file. IBTrACS includes systems that occur within the basin, even when they originated elsewhere.

Default historical window:
- 1980 onward

This starting point is explicit because the modern satellite era has much more consistent observational coverage than earlier decades.

## 2. Source refresh and provenance

The official NI CSV is downloaded into the private local workspace.

The pipeline records:
- source URL;
- IBTrACS release;
- HTTP Last-Modified where available;
- ETag where available;
- file size where available;
- SHA-256;
- retrieval time.

The exact downloaded CSV remains outside GitHub.

## 3. Track position

The IBTrACS latitude/longitude fields are used as historical best-track positions.

For each asset and storm, version 0.1 calculates:

- closest **track-point** distance in kilometres;
- time of that closest track point;
- storm name and SID;
- storm nature;
- track type;
- track-point coordinates.

The metric is explicitly called **closest track-point distance**.

It is not a continuous-track minimum-distance calculation between reported best-track points.

## 4. Intensity fields remain source-specific

IBTrACS can provide intensity information from different agencies.

Version 0.1 preserves separately:

- WMO wind at the closest track point;
- WMO central pressure;
- WMO agency;
- USA/JTWC-selected wind at the closest track point;
- USA/JTWC-selected central pressure;
- USA agency.

Mangrove does not automatically average or harmonize these wind values.

Wind averaging periods and operational practices can differ by agency, so combining them into a single value would imply comparability that is not always present.

## 5. Historical asset summaries

For the selected historical period, the pipeline calculates:

- nearest track-point distance among storms inside the configured analysis radius;
- number of storms with at least one track point within 100 km;
- number of storms with at least one track point within 250 km.

These are literal historical counts.

They are not:
- annual probabilities;
- return periods;
- exceedance probabilities;
- expected annual losses;
- climate-trend estimates.

A user changing the start year changes the observation period and therefore the meaning of the counts.

## 6. Event timeline

For every storm that comes within the configured analysis radius, the private event Parquet preserves all reported track points inside that radius with:

- timestamp;
- distance from asset;
- track coordinates;
- nature;
- track type;
- WMO wind/pressure;
- USA wind/pressure.

This allows later event-by-event review without reducing the storm to one summary number.

## 7. Track type and provisional data

IBTrACS TRACK_TYPE is preserved.

Recent storms may contain provisional information before later best-track updates.

The system therefore preserves the source snapshot and track type rather than silently treating every recent record as a final historical value.

## 8. Landfall-related IBTrACS fields

IBTrACS fields such as DIST2LAND and LANDFALL are preserved only as source metadata around the closest track point where available.

They do **not** establish Bangladesh landfall.

In IBTrACS, LANDFALL refers to minimum distance to land over the next three hours. It is not a Bangladesh-specific coast-crossing classification.

## 9. Geocode rule

Cyclone-track proximity is a relatively coarse historical context layer.

Eligible private assets:
- EXACT_SITE + RESOLVED
- PROBABLE_SITE + RESOLVED

This is intentionally different from fine-resolution GFM/JRC point attachment.

## 10. Interpretation boundary

A defensible statement might say:

“Since 1980, the asset location had three IBTrACS storms with a reported track point within 250 km; the nearest reported track point was 68 km away. At that track point the responsible WMO agency reported a maximum sustained wind of X knots.”

It should not say:

“The asset experienced X-knot wind.”

Track-center intensity is not site wind.

Likewise, track proximity does not establish:
- storm surge depth;
- wave conditions;
- local wind gusts;
- rainfall at the asset;
- building damage;
- downtime;
- insured loss;
- default probability.

## 11. Coastal interpretation

Version 0.1 does not generate a storm-surge or coastal-inundation hazard surface.

“Coastal event context” means the cyclone-track history can be attached to coastal or near-coastal assets.

A later storm-surge module must use a separate, physically appropriate coastal inundation model and should not infer surge from IBTrACS track data alone.

## 12. Private workflow

Run the historical context:

    python scripts/run_ibtracs_cyclone_context_local.py

Choose another start year:

    python scripts/run_ibtracs_cyclone_context_local.py --start-year 1990

Refresh the official NOAA source snapshot:

    python scripts/run_ibtracs_cyclone_context_local.py --refresh-source

Change the analysis radius:

    python scripts/run_ibtracs_cyclone_context_local.py --max-distance-km 750

All real asset coordinates, downloaded IBTrACS snapshots, event Parquet, SQLite indicators and customer outputs remain outside GitHub.
