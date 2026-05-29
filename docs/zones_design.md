# slappyengine.zones - Design Reference

`slappyengine.zones` is the canonical home for **named axis-aligned
rectangular regions** with optional enter/exit callbacks, material tags,
and scalar threshold events. The same primitive backs three game-logic
needs:

* **Damage zones** - threshold-based destruction (vehicle bumper, hood,
  windshield; enemy head/torso/legs).
* **Trigger volumes** - enter/exit events (pickups, region triggers,
  line-of-sight regions).
* **Spawn pads** - region anchors for entity spawning.

The data model is `RectZone` -> `ThresholdZone` (a `RectZone` plus a
scalar threshold and `on_threshold` callback) -> `ZoneManager` (the
collection that owns per-frame dispatch). See the module docstring in
`python/slappyengine/zones/__init__.py` for full API.

## Two independent update streams

`ZoneManager.update(positions)` is the **positional tracking** stream:
it consumes a dict (or iterable) of `(entity_id, (x, y))` per frame and
fires `on_enter` / `on_exit` for entities that have crossed a zone
boundary since the previous call.

`ZoneManager.update_threshold(name, value)` is the **scalar measurement**
stream: it consumes one zone-name + measurement per call and fires
`on_threshold` exactly once per downward crossing (re-arming when the
value recovers above `threshold + hysteresis`).

Splitting the two keeps a spawn pad enter/exit-only (no threshold cost)
and a damage zone threshold-only (no entity-tracking cost).

## Performance

### Spatial-hash acceleration

The naive implementation of `update(positions)` is
`O(zones x entities)` - every entity is tested against every zone via
`RectZone.contains_point`. At 1000 entities / 50 zones that is 50,000
predicate calls per frame, which sits around 3.5 ms on a typical desktop
CPU and pushes a 60-fps frame budget out of shape if zones are touched
more than once per tick.

`ZoneManager.update` therefore runs through a uniform-grid spatial hash
by default:

1. **Bucket entities** into `(cx, cy)` cells, where each cell is
   `cell_size` units on a side. Bucketing is a dict-of-list, allocated
   fresh per call - cheap, no fixed grid memory, and Python's `//`
   floor-division handles negative coordinates without special-casing.
2. **Per-zone candidate set**: precompute (once per zone-set edit) the
   inclusive cell range covering each zone's AABB. On update, iterate
   only those cells and test `contains_point` on their occupants.

Net complexity is roughly
`O(entities + sum_over_zones(cells_per_zone * avg_entities_per_cell))`.
For sparsely-distributed zones (each covering a few cells in a
populated world) the second term is much smaller than `zones x entities`
and the speedup grows with both N and Z.

### Cell-size policy

```text
cell_size = clamp(max_zone_dimension * 1.5, 4.0, 16.0)
```

* `1.5x` of the largest zone dimension keeps a typical zone in the
  range of 1 - 4 cells - enough that bucketing actually narrows the
  candidate list, but few enough that the per-zone outer loop stays
  cheap.
* Lower clamp `4.0` prevents pathological tiny cells (a zone of width
  0.1 would otherwise produce a near-empty cell at every entity
  position).
* Upper clamp `16.0` prevents pathological huge cells (one giant zone
  collapsing the grid to a single bucket, wiping out the speedup for
  every other zone).

The constants live on `ZoneManager._CELL_DIM_MULTIPLIER`, `_CELL_MIN`,
and `_CELL_MAX` if a future profiling pass surfaces a better default.

### Measured speedup

`tools/bench_zones.py` reports the median per-call wall-clock at four
scales. Numbers below are from a Windows desktop, Python 3.13, with the
worktree built locally:

| entities | zones | linear (us) | spatial-hash (us) | speedup |
|---------:|------:|------------:|------------------:|--------:|
| 100      | 10    | 72.0        | 24.6              | 2.93x   |
| 500      | 25    | 870.0       | 132.2             | 6.58x   |
| 1000     | 50    | 3564.3      | 327.6             | 10.88x  |
| 5000     | 100   | 36290.3     | 2476.4            | 14.65x  |

The 1000 / 50 row is the contract target for the perf sprint: the
spatial-hash path is required to be at least 3x faster than the linear
scan there, and ships at roughly 10x on this hardware.

### Index-rebuild policy

The per-zone cell ranges are cached in `_zone_cells` and rebuilt lazily
on the next `update` call whenever:

* a zone is added (`add`),
* a zone is removed (`remove`), or
* the spatial-hash flag is toggled (`enable_spatial_hash`).

Direct mutation of a zone's `rect` (or `x` / `y` / `w` / `h`) **does
not** mark the index dirty - it's a deliberate trade-off, because
re-detecting that would require dirty tracking inside the dataclass.
Callers that resize zones at runtime should re-add the zone, or call
`enable_spatial_hash(True)` to force a rebuild.

### Falling back to the linear scan

`ZoneManager.enable_spatial_hash(False)` flips the manager onto the
historical `O(zones x entities)` path. This exists for:

* parity tests (`tests/test_zones_spatial_hash.py::test_spatial_hash_events_match_linear_scan`),
* debugging suspected acceleration bugs in user code, and
* tiny-entity-count scenarios where the bucketing overhead might
  dominate.

Event semantics are byte-identical across both paths - the final
gating predicate is `RectZone.contains_point` either way, and the set
arithmetic over `prev` and `now` is order-independent.
