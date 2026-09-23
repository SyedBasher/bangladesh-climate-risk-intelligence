# Asset Geocoding Acceptance Rules v0.1

## Principle
Geocoding is an evidence-matching problem, not a name-search problem. No single opaque confidence
score determines acceptance.

## Grades

### EXACT_SITE
All required:
1. candidate district is consistent with DIFE;
2. candidate locality/upazila is consistent or the returned site address is more specific and compatible;
3. candidate identifies a building, industrial premises, establishment or named site rather than an admin centroid;
4. name/site evidence is consistent with the DIFE establishment, not merely the parent organization;
5. no competing candidate with comparable evidence remains unresolved.

Use:
- all point-level climate indicators, subject to raster/source resolution.

### PROBABLE_SITE
Required:
- district and locality are consistent;
- establishment name or independently corroborated site address strongly agrees;
- coordinate is a plausible named premises/site;
- exact building/site identity is not fully demonstrated.

Use:
- coarse climate indicators may be attached with `PROBABLE_SITE` flag;
- do NOT attach 20–100 m site-sensitive flood/terrain indicators as if exact.

### LOCALITY_ONLY
Returned feature is a road, village, post office, industrial area, upazila, town or similar locality
without evidence of the establishment premises.

Use:
- administrative/contextual linkage only;
- never site-level flood depth, DEM, distance-to-river, or observed-flood history.

### AMBIGUOUS
Two or more plausible site candidates remain. No climate point extraction.

### NO_MATCH
No acceptable site candidate.

### REJECTED_ADMIN_MISMATCH
Candidate district/upazila contradicts DIFE. Hard reject even if organization name is identical.

## Additional guardrails
- Corporate/head-office coordinates must never be substituted for a DIFE plant/site.
- A company with multiple DIFE establishments requires site-level disambiguation.
- DIFE `বাণিজ্য প্রতিষ্ঠান` / delivery establishment remains that asset type; do not relabel it a factory.
- Admin centroids are not site coordinates.
- Geocoder returned `importance` or provider ranking is not Mangrove confidence.
- Every accepted coordinate stores provider, provider object ID, query, returned label, retrieval time,
  OSM/data vintage where available, and candidate evidence.
