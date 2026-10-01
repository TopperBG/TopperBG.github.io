# Individual wind turbines in Bulgaria

Snapshot: 2026-09-06, OpenStreetMap via Overpass API (timestamp in JSON).
484 individual positions: 482 nodes and two footprint centres from site relation 18622218 (Velga). Way 334704084 is excluded because it duplicates node 10704241478 within 8 metres. The site relation centre is never rendered as a turbine.

Query: Bulgaria administrative area, union of `generator:source=wind`, `generator:method=wind_turbine`, and `man_made=wind_turbine`; `out center tags`. Relation 18622218 members were fetched separately.

The HTML embeds the same records for immediate, network-independent rendering. The existing wind-farm summary points are no longer rendered. No wind farm capacity is assigned to an individual turbine. Unknown capacity and operator remain blank. Coordinates are OSM positions, not surveyed or independently satellite-verified coordinates. Presence in OSM is not proof of current operation. National completeness is not established; unmapped turbines may exist. Planned projects are not created from these records.

© OpenStreetMap contributors. Database license: ODbL 1.0 — https://www.openstreetmap.org/copyright
Each record links to its source OSM object. For the two member footprints, `parentRelation` records the source of wind-generation classification.
