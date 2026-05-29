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

## Performance

The no-subscriber fast path is ~70 ns/emit on CPython 3.13 (Windows, hot
loop) — the original 86 ns target plus a tiny attribute lookup. Once any
subscriber is registered, `emit` must build a `TelemetryEvent` and walk
the subscriber list, and that walk is linear in the total subscriber
count regardless of how many subscribers actually match the event.

`tools/bench_telemetry.py` captured the following numbers on Python
3.13.13 / Windows:

| Scenario | Subs | Emits | Elapsed (s) | ns/emit | callbacks/s |
|---|---:|---:|---:|---:|---:|
| 1 sub on `physics.step`, 100k emits | 1 | 100,000 | 0.0953 | 953 | 1,048,789 |
| 100 subs on `*` (catch-all), 10k emits | 100 | 10,000 | 0.2743 | 27,426 | 3,646,130 |
| 100 subs on `physics.*`, 10k emits | 100 | 10,000 | 0.2838 | 28,381 | 3,523,469 |
| 1000 subs / 10 patterns, 10k emits (INDEX OFF) | 1000 | 10,000 | 1.9262 | 192,622 | 519,153 |
| 1000 subs / 10 patterns, 10k emits (INDEX ON) | 1000 | 10,000 | 0.3003 | 30,026 | 3,330,455 |
| 0 subs, history capacity 0, 100k emits (no-op fast path) | 0 | 100,000 | 0.0070 | 70 | — |
| 0 subs, history capacity 1000, 100k emits (ring buffer only) | 0 | 100,000 | 0.1120 | 1,120 | — |

Reading the table:

* **The hot path scales linearly with total subscriber count** when the
  default unindexed dispatch is used. Going from 100 `physics.*` subs to
  1000 mixed subs is ~7x slower (28 us -> 193 us) — and only 100 of those
  1000 subs actually match a `physics.step` emit.
* **The ring buffer alone costs ~1 us per emit.** That's why
  `set_history_capacity(0)` is a real lever for shipping builds.
* **Catch-all and same-bucket dispatch cost the same** at 100 subs (27 us
  vs 28 us) — the per-emit work is dominated by `fnmatch.fnmatchcase`
  plus the dict snapshot, not by which pattern is used.

### Opt-in pattern index

Once the subscriber count climbs past a few hundred the linear walk
becomes the dominant cost. `enable_pattern_index(True)` switches `emit`
to a bucketed dispatch:

1. Subscribers are grouped by the **first dotted segment** of their
   pattern. `"physics.step"`, `"physics.*"`, `"physics.collision"` all
   land in the `physics` bucket. `"*"` and any pattern whose first
   segment contains a glob metachar (e.g. `"*.step"`) land in the `*`
   bucket.
2. On emit, we look up `bucket[first_segment(event.name)]` plus
   `bucket["*"]`. Only those subscribers run.

For the 1000-subscribers / 10-buckets workload above, this is a **6.4x
speedup** (193 us -> 30 us per emit). At that point indexed dispatch is
the same cost as the unindexed 100-subscriber case, because only ~100
subscribers actually match each emit.

```python
from slappyengine import telemetry

telemetry.enable_pattern_index(True)   # opt-in; default is OFF
assert telemetry.is_pattern_index_enabled()
```

#### Limitations of the first-segment bucket

The index is a coarse approximation, not a perfect dispatch table:

* Patterns whose first segment is a glob (`"*.step"`, `"?hysics.*"`)
  land in the `*` bucket and are checked against every emit. They get
  no speedup, but correctness is preserved.
* The catch-all `*` bucket is always walked. If most of your subscribers
  are `"*"`-pattern listeners, the index won't help.
* Within a bucket, subscribers fire in subscription order. Across
  buckets the relative order between a bucket-X subscriber and a `*`
  subscriber depends on bucket iteration order, not on subscription
  time. The **set** of deliveries is identical to the unindexed path —
  only cross-bucket relative ordering can differ. This is enforced by
  `test_pattern_index_delivers_same_events_as_unindexed`.

#### Why not a trie?

A trie keyed on dotted segments would handle deeper patterns (e.g.
distinguishing `physics.collision.*` from `physics.step`) and would
correctly bucket `"*.step"` against `*.step`-shaped event names.
We deliberately stopped at the first-segment bucket because:

* Event names in the engine today are uniformly `"<subsystem>.<event>"`
  (two segments). A deeper trie spends per-subscribe work that the
  current event taxonomy does not exercise.
* The simple bucket already collapses the 1000-subscriber bench from
  193 us to 30 us. Diminishing returns vs. complexity.
* The simple bucket is opt-in, so it costs zero for the
  Bullet-Strata-style game with a single HUD-dirty subscriber.

If/when event names grow to three or more segments and the catch-all
bucket starts dominating again, a trie keyed on the dotted segments is
the natural next step. The internal representation (`_bucket_index:
Dict[str, List[...]]`) leaves room to swap in a nested dict without
changing the public surface.

### Lock contention

The opt-in index does not add a separate lock. `subscribe` /
`unsubscribe` already hold `_lock`; they now also mutate the bucket
list under the same critical section. `emit` snapshots the relevant
bucket(s) under the lock (a single `list(bucket)` per bucket — read-only
on the bucket dict itself) and then runs callbacks lock-free, mirroring
the unindexed path. Hot-path lock duration is unchanged.

## What this is not

* Not cross-process. No IPC, no sockets, no shared memory.
* Not persistent. Events live only in the ring buffer.
* Not a UI. Games render telemetry however they want (the editor's profile
  overlay, an HTML page, stdout).
