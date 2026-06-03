<!-- handauthored: do not regenerate -->
# slappyengine.telemetry — API Reference

> Hand-curated reference for the telemetry subpackage. The auto-generator
> (`scripts/gen_subpackage_api_docs.py`) skips files carrying the
> `<!-- handauthored: do not regenerate -->` marker above.
> Companion design notes live in
> [`telemetry_design.md`](../telemetry_design.md).

```python
from slappyengine.telemetry import (
    TelemetryEvent,
    emit,
    subscribe,
    unsubscribe,
    get_event_history,
    clear_history,
    set_history_capacity,
    enable_pattern_index,
    is_pattern_index_enabled,
)
```

## Overview

`slappyengine.telemetry` is the engine's instrumentation bus: a single
process-wide event sink that games, editor panels, profilers, and
save-state diffs all subscribe to. The pattern was promoted out of
Bullet Strata's reactive-HUD dirty flag after every game we shipped
ended up re-implementing the same hook.

The Sprint 7E surface audit lists **26 public attributes** on the
module. The nine load-bearing symbols are in the import block above;
the remaining seventeen are re-exported stdlib aliases (`fnmatch`,
`threading`, `time`, `dataclass`, `field`, `deque`, eight `typing`
shims, four `_validation` helpers) — byproducts of the flat `from …
import *` layout, documented here only so callers know what
`dir(slappyengine.telemetry)` will show.

## Event record — `TelemetryEvent`

A dataclass that carries everything a subscriber needs to react.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `name` | `str` | required | Dotted event name, e.g. `"physics.step"`. |
| `timestamp` | `float` | required | `time.perf_counter()` at emit time — monotonic, fractional seconds. |
| `payload` | `Dict[str, Any]` | `field(default_factory=dict)` | Shallow copy of the kwargs passed to `emit`. |
| `source` | `Optional[str]` | `None` | Auto-extracted from `payload["source"]` for convenience. |

```python
TelemetryEvent(name="physics.step", timestamp=2034.81, payload={"dt": 1/60}, source="softbody")
```

## Hot path — `emit`

```python
emit(name: str, **payload: Any) -> None
```

Publishes an event. Three properties matter:

1. **Free when idle.** When `len(_subscribers) == 0` *and* the ring
   buffer is disabled (`set_history_capacity(0)`), `emit` short-
   circuits before allocating a `TelemetryEvent`. Measured cost on the
   Sprint 4 hardware: ~86 ns per call, dominated by attribute lookup.
2. **Per-call lock window is bounded.** The subscriber dict is
   snapshotted under `_lock` and then released before any user callback
   runs. Subscribers can `subscribe` / `unsubscribe` from inside their
   own callbacks without deadlock.
3. **Subscriber exceptions never escape.** Every callback is wrapped in
   `try/except Exception` and routed to `logging.getLogger(__name__)`.
   This means a buggy HUD overlay cannot crash the physics step that
   produced its data — the failure shows up in the log, not in your
   render loop.

Raises `TypeError` if `name` is not a `str`, `ValueError` if `name` is
the empty string.

## Subscription primitives

### `subscribe(name_pattern, callback) -> int`

Registers a glob-pattern subscription. Pattern semantics come from
`fnmatch.fnmatchcase`:

| Pattern | Matches |
|---------|---------|
| `"physics.step"` | exact name only |
| `"physics.*"` | every `physics.something` event |
| `"*"` | every event |
| `"*.collision"` | every event whose name ends in `.collision` |

Returns an opaque integer **handle**. Hand it to `unsubscribe` later.
Raises `TypeError` if `name_pattern` is not a `str` or `callback` is
not callable.

### `unsubscribe(handle: int) -> None`

Drops a subscription. Unknown handles are silently ignored — calling
`unsubscribe` twice with the same handle is safe.

## History ring buffer

`slappyengine.telemetry` keeps a process-wide `collections.deque` of
recent events so a debugger / save-state diff / post-mortem panel can
look at what happened without having to subscribe ahead of time.

### `get_event_history(name_pattern="*", max_count=1000) -> List[TelemetryEvent]`

Returns recent events that match `name_pattern`, oldest first, capped
at `max_count`. The buffer is snapshotted under the lock so a
concurrent `emit` cannot wedge the iterator.

### `clear_history() -> None`

Drops every event in the buffer. Cheap; useful between scenes so a
post-mortem query never returns stale data from the previous level.

### `set_history_capacity(capacity: int) -> None`

Resizes the ring buffer. Pass `0` to disable history entirely —
combined with zero subscribers that activates the fully allocation-
free fast path in `emit`. Reducing capacity drops the oldest entries;
increasing capacity preserves everything currently buffered.

Raises `TypeError` if `capacity` is not a plain `int`
(floats / bools refused), `ValueError` if `capacity < 0`.

## Pattern index (opt-in)

By default `emit` walks every registered subscriber and runs
`fnmatch.fnmatchcase` on each pattern. That's O(subscribers) per emit
and is fine for the ~dozen subscribers a typical game registers.

Tools that hang a panel off every subsystem (the editor, the profiler,
the perf dashboard) can hit hundreds of subscribers. The opt-in
**pattern index** buckets subscribers by the first dotted segment of
their pattern (`"physics.step"` → bucket `"physics"`, `"*"` → bucket
`"*"`), and `emit` then walks only the bucket that matches the event
plus the catch-all bucket — O(matching) per emit. The Sprint 4 round-2
microbenchmark recorded a 6.42x dispatch speedup at 256 subscribers.

### `enable_pattern_index(enabled: bool = True) -> None`

Toggles indexed dispatch. The index is rebuilt from the canonical
subscriber dict, so toggling never loses subscriptions. Off by default
for backward compatibility — the unindexed dispatch path is unchanged
when this is never called. Raises `TypeError` if `enabled` is not a
`bool`.

### `is_pattern_index_enabled() -> bool`

Returns the current toggle state. Cheap; safe to call from inside a
hot loop.

### Sharp edge: cross-bucket dispatch order

Within a bucket subscribers fire in subscription order (matching the
legacy dispatch path). Across buckets the order can differ — a
catch-all `"*"` subscriber registered between two `"physics.*"`
subscribers will be delivered *after* both physics subscribers under
the indexed path, even though it was registered between them. The set
of deliveries is unchanged. Documented in
[`telemetry_design.md`](../telemetry_design.md) for callers that depend
on ordering.

## Output adapters

`slappyengine.telemetry` ships **no** wire-format adapters — that is
deliberate. Subscribers are plain Python callables, so games typically
write their own ~10-line forwarder for whatever backend they need:

```python
import json
from slappyengine.telemetry import subscribe

def log_to_jsonl(event):
    with open("run.jsonl", "a") as f:
        f.write(json.dumps({
            "name": event.name,
            "t": event.timestamp,
            "payload": event.payload,
        }) + "\n")

handle = subscribe("*", log_to_jsonl)
```

The same pattern works for an in-editor panel
(`subscribe("physics.*", panel.push_row)`), an OpenTelemetry exporter,
or a Prometheus counter. Keep the callback fast — every microsecond
multiplied by the emit rate is wall time the producer pays.

### Counter / gauge / histogram patterns

There are no built-in counter / gauge / histogram primitives. The
convention is:

- **Counter** — emit one event per increment (`emit("hit.spawned")`)
  and aggregate in the subscriber.
- **Gauge** — emit on change with the current value
  (`emit("hp.player", value=42)`).
- **Histogram / timing** — emit the duration as a payload field
  (`emit("frame.physics_ms", ms=elapsed)`).

This keeps the producer side allocation-free in the idle case and
leaves bucketing / EWMA / quantile estimation to the consumer, where
the policy belongs.

### Perf timing utility

For ad-hoc block timing the idiomatic helper is a `contextlib`
context manager built on top of `emit`:

```python
from contextlib import contextmanager
import time
from slappyengine.telemetry import emit

@contextmanager
def measure(name):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        emit(name, ms=(time.perf_counter() - t0) * 1000.0)

with measure("frame.physics_ms"):
    world.step(dt)
```

Three lines, no allocation when nothing is subscribed (the underlying
`emit` early-outs).

## Threading model

A single `threading.Lock` guards `_subscribers`, `_history`, and (when
enabled) `_bucket_index`. Subscriber callbacks run *outside* the lock,
so a slow consumer cannot block concurrent producers. The model is
correct under both CPython GIL and PEP 703 (no-GIL) builds — the
subscriber list is explicitly copied into a local before iteration.

## Inner module surface

- `slappyengine.telemetry.TelemetryEvent` — public dataclass.
- `slappyengine.telemetry.emit` / `subscribe` / `unsubscribe` —
  producer / consumer entry points.
- `slappyengine.telemetry.get_event_history` / `clear_history` /
  `set_history_capacity` — ring buffer.
- `slappyengine.telemetry.enable_pattern_index` /
  `is_pattern_index_enabled` — opt-in O(matching) dispatch.
- `slappyengine.telemetry._validation` — private input-validation
  helpers. Not part of the contract; reach into them at your own risk.

## Protocols

- `EventEmitterProtocol` — structural Protocol for anything that emits
  telemetry events. Requires `emit(name: str, **payload) -> None`.
  Runtime-checkable.
- `EventSubscriberProtocol` — structural Protocol for subscribers.
  Requires `__call__(event) -> None`. Runtime-checkable; any plain
  function satisfies this implicitly.

## See also

- [`audio_runtime.md`](audio_runtime.md) — companion soft-fail backend
  shim that subscribers can hook for muted-audio diagnostics.
