# Road blocking scenarios

A road intersecting a flood footprint is **exposed**, not automatically impassable.

Keep two fields separate:
- `hazard_exposed`
- `hazard_blocked`

`hazard_blocked` is a scenario variable and must state its rule, for example:
- observed closure from an authoritative incident feed;
- engineering rule based on road elevation and water depth;
- customer-selected screening threshold;
- scenario assumption used only for sensitivity analysis.

Mangrove must not infer road closure simply because JRC depth at/near the road is above zero.

Every connectivity result stores:
- hazard layer/version;
- blocking rule ID;
- graph vintage;
- endpoint ID/vintage;
- route algorithm/version.
