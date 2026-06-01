<!-- handauthored: do not regenerate -->
# slappyengine.zones — API Reference

> Auto-generated. Re-run `python scripts/gen_subpackage_api_docs.py`.
> Do not hand-edit — every entry below comes from runtime introspection
> (`inspect.signature`, `inspect.getdoc`, `dataclasses.fields`).


slappyengine.zones — Generic zone primitives.

## Classes

### `RectZone`

_dataclass — defined in `slappyengine.zones`_

An axis-aligned rectangular zone with optional enter/exit callbacks.

#### Constructor signature

```python
RectZone(name: 'str', x: 'float', y: 'float', w: 'float', h: 'float', material: 'str | None' = None, on_enter: 'EnterExitCallback | None' = None, on_exit: 'EnterExitCallback | None' = None) -> None
```

#### Fields

- `h: float`
- `material: str | None` — default `None`
- `name: str`
- `on_enter: EnterExitCallback | None` — default `None`
- `on_exit: EnterExitCallback | None` — default `None`
- `w: float`
- `x: float`
- `y: float`

#### Methods

- `contains_point(self, px: 'float', py: 'float') -> 'bool'` — Return True iff ``(px, py)`` falls inside this zone's half-open rect.

#### Raises

- `TypeError` — If ``x`` / ``y`` / ``w`` / ``h`` are not real numbers.
- `ValueError` — If ``w`` or ``h`` is not strictly positive, or any coordinate is non-finite.

### `ThresholdZone`

_dataclass — defined in `slappyengine.zones`_

A :class:`RectZone` with a scalar measurement + threshold event.

#### Constructor signature

```python
ThresholdZone(name: 'str', x: 'float', y: 'float', w: 'float', h: 'float', material: 'str | None' = None, on_enter: 'EnterExitCallback | None' = None, on_exit: 'EnterExitCallback | None' = None, threshold: 'float' = 0.0, hysteresis: 'float' = 0.05, on_threshold: 'ThresholdCallback | None' = None, strength_scale: 'float' = 1.0, on_destroy_event: 'str' = 'Zone.Destroyed') -> None
```

#### Fields

- `h: float`
- `hysteresis: float` — default `0.05`
- `material: str | None` — default `None`
- `name: str`
- `on_destroy_event: str` — default `'Zone.Destroyed'`
- `on_enter: EnterExitCallback | None` — default `None`
- `on_exit: EnterExitCallback | None` — default `None`
- `on_threshold: ThresholdCallback | None` — default `None`
- `strength_scale: float` — default `1.0`
- `threshold: float` — default `0.0`
- `w: float`
- `x: float`
- `y: float`

#### Methods

- `contains_point(self, px: 'float', py: 'float') -> 'bool'` — Return True iff ``(px, py)`` falls inside this zone's half-open rect.

#### Raises

- `TypeError` — If ``threshold`` / ``hysteresis`` are not real numbers (in addition to the rect-geometry checks inherited from :class:`RectZone`).
- `ValueError` — If ``threshold`` is non-finite or ``hysteresis`` is negative.

### `ZoneManager`

_class — defined in `slappyengine.zones`_

Tracks a collection of zones and dispatches lifecycle events.

#### Constructor signature

```python
ZoneManager() -> 'None'
```

#### Methods

- `add(self, zone: 'RectZone') -> 'RectZone'` — Register *zone*. Returns the zone for chaining.
- `enable_spatial_hash(self, enabled: 'bool' = True) -> 'None'` — Enable (default) or disable the spatial-hash acceleration.
- `get(self, name: 'str') -> 'RectZone | None'` — Return the zone with this name, or ``None``.
- `is_fired(self, name: 'str') -> 'bool'` — Return True if a threshold zone has fired and not yet re-armed.
- `names(self) -> 'list[str]'`
- `occupancy(self, name: 'str') -> 'set[EntityId]'` — Return the set of entities currently inside the named zone.
- `remove(self, name: 'str') -> 'bool'` — Drop a zone by name. Returns True iff it was present.
- `reset(self) -> 'None'` — Clear all occupancy and re-arm every threshold zone.
- `update(self, positions: 'dict[EntityId, Position] | Iterable[tuple[EntityId, Position]]') -> 'None'` — Update entity occupancy across all rect zones.
- `update_threshold(self, name: 'str', value: 'float') -> 'None'` — Feed a scalar measurement to a :class:`ThresholdZone`.
- `zones(self) -> 'list[RectZone]'`

## Functions

_(none)_

## Constants

_(none)_

## Inner modules

_(none)_
