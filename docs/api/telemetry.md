# slappyengine.telemetry — API Reference

> Auto-generated. Re-run `python scripts/gen_subpackage_api_docs.py`.
> Do not hand-edit — every entry below comes from runtime introspection
> (`inspect.signature`, `inspect.getdoc`, `dataclasses.fields`).


slappyengine.telemetry ======================

## Classes

### `TelemetryEvent`

_dataclass — defined in `slappyengine.telemetry`_

A single telemetry event published via :func:`emit`.

#### Constructor signature

```python
TelemetryEvent(name: 'str', timestamp: 'float', payload: 'Dict[str, Any]' = <factory>, source: 'Optional[str]' = None) -> None
```

#### Fields

- `name: str`
- `payload: Dict[str, Any]` — default factory
- `source: Optional[str]` — default `None`
- `timestamp: float`

## Functions

### `clear_history() -> 'None'`

_defined in `slappyengine.telemetry`_

Drop every event in the ring buffer.

### `emit(name: 'str', **payload: 'Any') -> 'None'`

_defined in `slappyengine.telemetry`_

Publish a telemetry event.

#### Raises

- `TypeError` — If ``name`` is not a ``str``.
- `ValueError` — If ``name`` is the empty string.

### `enable_pattern_index(enabled: 'bool' = True) -> 'None'`

_defined in `slappyengine.telemetry`_

Toggle the opt-in first-segment pattern index for :func:`emit`.

#### Raises

- `TypeError` — If ``enabled`` is not a ``bool``.

### `get_event_history(name_pattern: 'str' = '*', max_count: 'int' = 1000) -> 'List[TelemetryEvent]'`

_defined in `slappyengine.telemetry`_

Return up to *max_count* recent events whose name matches *name_pattern*.

### `is_pattern_index_enabled() -> 'bool'`

_defined in `slappyengine.telemetry`_

Return whether the pattern index is currently enabled.

### `set_history_capacity(capacity: 'int') -> 'None'`

_defined in `slappyengine.telemetry`_

Resize the ring buffer.

#### Raises

- `TypeError` — If ``capacity`` is not a plain ``int`` (floats/bools refused).
- `ValueError` — If ``capacity < 0``.

### `subscribe(name_pattern: 'str', callback: 'Callable[[TelemetryEvent], None]') -> 'int'`

_defined in `slappyengine.telemetry`_

Register *callback* for events whose name matches *name_pattern*.

#### Raises

- `TypeError` — If ``name_pattern`` is not a ``str`` or ``callback`` is not callable.

### `unsubscribe(handle: 'int') -> 'None'`

_defined in `slappyengine.telemetry`_

Drop a subscription previously returned by :func:`subscribe`.

## Constants

_(none)_

## Inner modules

_(none)_
