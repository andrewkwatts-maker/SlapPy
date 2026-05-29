# `slappyengine.telemetry` — Engine Event Bus

`slappyengine.telemetry` is a tiny, single-process publish/subscribe API for
engine events. It exists so games can hook into the engine for debugging,
profiling, and save-state diffing without engine code needing to know what the
game wants. Bullet Strata's reactive HUD dirty flag is the canonical example:
the game wants to redraw exactly when something changes, and telemetry events
are the cleanest way to learn that.

## Design goals

1. **`emit` is free when nobody is listening.** With zero subscribers and the
   history ring buffer disabled (`set_history_capacity(0)`), `emit` returns
   after two attribute lookups and a boolean check — no `TelemetryEvent`
   allocation, no dict copy.
2. **Glob patterns, not topic strings.** Subscribers say
   `subscribe("physics.*", cb)`, not `subscribe("physics.step", cb)` plus
   `subscribe("physics.collision", cb)`. Matching uses
   `fnmatch.fnmatchcase`.
3. **In-memory ring buffer for post-mortem queries.** Games can ask "what just
   happened?" without having pre-installed a subscriber — `get_event_history`
   reads the buffer.
4. **No global enable/disable flag.** The fast path is fast enough that gating
   it on a flag would be slower than always running it.

## Usage

```python
from slappyengine import telemetry

# --- Producer side (engine code) -----------------------------------------
def physics_step(dt: float) -> None:
    # ... do the step ...
    telemetry.emit("physics.step", dt=dt, body_count=len(world.bodies))

# --- Consumer side (game code) -------------------------------------------
def on_physics(event: telemetry.TelemetryEvent) -> None:
    print(f"{event.name} at {event.timestamp:.3f}s: {event.payload}")

handle = telemetry.subscribe("physics.*", on_physics)

# Later, when the game shuts down or changes scene:
telemetry.unsubscribe(handle)
```

### Post-mortem inspection

```python
# After a crash report comes in, dump the last 200 events.
for ev in telemetry.get_event_history("*", max_count=200):
    print(ev.name, ev.payload)
```

### Save-state diffing

```python
# Mark a checkpoint, do work, see what changed.
telemetry.clear_history()
run_one_simulation_tick()
changes = telemetry.get_event_history("state.*")
```

### Disabling the ring buffer for shipping builds

```python
telemetry.set_history_capacity(0)  # combined with zero subscribers = no-op emit
```

## Thread safety

A single `threading.Lock` guards subscribe/unsubscribe and history
mutations. `emit` briefly holds the lock to snapshot the subscriber list and
append to the history deque, then runs callbacks outside the lock. Concurrent
emits from multiple threads are safe; callback ordering across threads is not
guaranteed.

## What this is not

* Not cross-process. No IPC, no sockets, no shared memory.
* Not persistent. Events live only in the ring buffer.
* Not a UI. Games render telemetry however they want (the editor's profile
  overlay, an HTML page, stdout).
