# slappyengine.zones — API Reference

> Hand-written Phase B subpackage reference. Source of truth for the
> public surface lives in `python/slappyengine/zones/__init__.py`. Do
> NOT regenerate via `scripts/gen_subpackage_api_docs.py` — the prose,
> examples, and complexity annotations below are hand-curated.

## Overview

`slappyengine.zones` is the canonical primitive for any named axis-aligned
rectangle the engine needs to test points against: vehicle damage zones,
enemy hitbox sub-regions, pickup volumes, spawn pads, line-of-sight
regions, region triggers. The Phase B repackage extracts the rect +
threshold + material data model from the legacy
`physics.deform_zones.ZoneMap` and exposes three composable classes —
`RectZone`, `ThresholdZone`, `ZoneManager` — without the per-pixel-alpha
integrity update path (which stays in `deform_zones.ZoneMap` until Phase
D folds it in). The manager runs through a uniform-grid spatial hash by
default, dropping the naive `O(zones × entities)` cost to roughly
`O(entities + zones × cells_per_zone)`; an `enable_spatial_hash(False)`
escape hatch preserves the original linear scan for parity tests.

## Classes

### `RectZone`

_dataclass — defined in `slappyengine.zones`_

An axis-aligned rectangular zone with optional enter/exit callbacks.
Coordinates are unit-agnostic; the manager makes no assumption about
world vs. pixel vs. screen space — callers must keep one consistent
space across every zone in a given `ZoneManager`.

#### Constructor signature

```python
RectZone(name: str, x: float, y: float, w: float, h: float,
         material: str | None = None,
         on_enter: Callable[[Hashable], None] | None = None,
         on_exit:  Callable[[Hashable], None] | None = None)
```

#### Parameters

- `name` — stable string identifier; used as the key in `ZoneManager`.
- `x`, `y`, `w`, `h` — rect corner + size. Half-open: a point at
  `(x+w, y+h)` is *outside* the zone.
- `material` — free-form tag (e.g. `"glass"`, `"metal"`). The manager
  does not interpret it; consumer code looks it up for impact effects,
  damage multipliers, sound presets.
- `on_enter(entity_id)` / `on_exit(entity_id)` — fired by
  `ZoneManager.update` on the corresponding transition.

#### Methods

- `contains_point(px, py) -> bool` — half-open rect test. **O(1)**.
- `rect` property — returns `(x, y, w, h)` for serialisation / UI binding.

#### Raises

- `TypeError` — if `x`/`y`/`w`/`h` are not real numbers.
- `ValueError` — if `w`/`h` ≤ 0 or any coordinate is non-finite.

#### Example

```python
from slappyengine.zones import RectZone, ZoneManager

mgr = ZoneManager()
zone = RectZone(
    name="pickup_pad",
    x=0.0, y=0.0, w=10.0, h=10.0,
    material="energy",
    on_enter=lambda eid: print(f"{eid} grabbed pickup"),
    on_exit=lambda eid: print(f"{eid} left pad"),
)
mgr.add(zone)
mgr.update({"player": (5.0, 5.0)})  # prints "player grabbed pickup"
```

### `ThresholdZone`

_dataclass — defined in `slappyengine.zones`_

A `RectZone` plus a scalar threshold + hysteresis. Used for damage,
integrity, fill-level zones — anywhere the owner repeatedly feeds a
measurement and wants a single event on the downward crossing.

#### Constructor signature

```python
ThresholdZone(name, x, y, w, h,
              material=None, on_enter=None, on_exit=None,
              threshold: float = 0.0,
              hysteresis: float = 0.05,
              on_threshold: Callable[[float], None] | None = None,
              strength_scale: float = 1.0,
              on_destroy_event: str = "Zone.Destroyed")
```

#### Parameters

- `threshold` — trigger value. A downward crossing
  (`value ≤ threshold` while the zone is armed) fires `on_threshold`.
- `hysteresis` — re-arm margin. Default `0.05` matches the legacy
  `deform_zones.ZoneMap` policy. The zone re-arms once the measurement
  rises above `threshold + hysteresis`.
- `on_threshold(value)` — direct callback path. Canonical.
- `strength_scale` — damage-zone multiplier consumer code uses to
  attenuate a parent layer's elastic threshold (e.g. windshield breaks
  before steel chassis). The manager does not interpret it.
- `on_destroy_event` — EventBus topic stored alongside the zone for
  callers that prefer pub-sub over direct callbacks. The manager does
  not publish; bridging code reads the field.

#### Raises

- `TypeError` — if `threshold` or `hysteresis` are not real numbers
  (in addition to the geometry checks inherited from `RectZone`).
- `ValueError` — if `threshold` is non-finite or `hysteresis < 0`.

#### Example

```python
from slappyengine.zones import ThresholdZone, ZoneManager

mgr = ZoneManager()
mgr.add(ThresholdZone(
    name="windshield",
    x=0.0, y=2.0, w=4.0, h=1.0,
    threshold=0.3, hysteresis=0.1,
    strength_scale=0.4,        # breaks at 40% the chassis' force
    on_threshold=lambda v: print(f"windshield shattered at integrity={v}"),
))
for integrity in (1.0, 0.6, 0.25, 0.1, 0.5, 0.9, 0.2):
    mgr.update_threshold("windshield", integrity)
```

### `ZoneManager`

_class — defined in `slappyengine.zones`_

Tracks a collection of zones and dispatches enter/exit + threshold
events. Owns two independent update streams so positional tracking and
integrity tracking stay decoupled.

#### Constructor signature

```python
ZoneManager()  # zero config; spatial hash on by default
```

#### Methods

| Method | Complexity | Purpose |
| --- | --- | --- |
| `add(zone)` | O(1) | Register a `RectZone` (or `ThresholdZone`); raises on duplicate name. |
| `remove(name)` | O(1) | Drop a zone; returns `True` iff present. |
| `get(name)` | O(1) | Lookup, or `None`. |
| `names() / zones()` | O(zones) | Listing. |
| `update(positions)` | O(entities + zones × cells_per_zone) hashed, O(zones × entities) linear | Per-frame enter/exit dispatch. |
| `update_threshold(name, value)` | O(1) | Feed a scalar; no-op on non-`ThresholdZone`. |
| `occupancy(name)` | O(occupants) | Snapshot of entities currently inside `name`. |
| `is_fired(name)` | O(1) | Latched threshold-state query. |
| `enable_spatial_hash(enabled)` | O(1) | Toggle the acceleration path; rebuilds on the next `update`. |
| `reset()` | O(zones) | Clear all occupancy and re-arm every threshold zone. |

`update` accepts either a `dict[entity_id, (x, y)]` or an iterable of
`(entity_id, (x, y))` pairs. Strings/bytes/scalars raise `TypeError`.
The spatial-hash path produces byte-identical enter/exit events to the
linear scan (the final gating predicate is `contains_point` in both
paths, and set construction is order-independent).

#### Example

```python
from slappyengine.zones import RectZone, ThresholdZone, ZoneManager

mgr = ZoneManager()
mgr.add(RectZone("safe",   x=1.0, y=1.0, w=3.0, h=3.0,
                 on_enter=lambda e: print("safe", e)))
mgr.add(RectZone("danger", x=6.0, y=1.0, w=3.0, h=3.0,
                 on_enter=lambda e: print("danger", e)))
mgr.add(ThresholdZone("hull", x=0.0, y=0.0, w=10.0, h=10.0,
                      threshold=0.3, on_threshold=lambda v: print("hull", v)))

for frame in range(60):
    mgr.update({"player": (2.0 + 0.1 * frame, 2.0)})
    mgr.update_threshold("hull", 1.0 - frame / 60.0)
```

## Editor integration

The engine editor binds `ThresholdZone` through
`python/slappyengine/ui/editor/deform_panel.py:ZoneEditorPanel`. The
panel lists every zone attached to the selected `DeformableLayer`
component, exposes rect / threshold / hysteresis / material fields for
inline editing, and on **Add zone** instantiates a fresh
`slappyengine.zones.ThresholdZone` (replacing the legacy
`deform_modes.ZoneConfig`). The Phase B repackage commit kept the
on-disk field names compatible so existing scene serialisations
round-trip unchanged.

## Consumer tests

- `tests/test_hardening_zones.py` — input-validation matrix for
  `RectZone`, `ThresholdZone`, and `ZoneManager`.
- `tests/test_zones_spatial_hash.py` — acceleration parity + ≥3× speedup
  regression at 1000 entities / 50 zones.
- `tests/test_demo_hello_zone.py` — smoke test wrapping
  `examples/hello_zone.py`.

## Inner modules

- `slappyengine.zones._validation` — internal O(1) numeric checks.
