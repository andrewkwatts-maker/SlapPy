# Sprint 4 — Serialization gap analysis

**Status:** authored 2026-05-30 during Sprint 4 (demo & integration sweep).
**Companion test:** `SlapPyEngineTests/tests/test_composite_serialize_roundtrip.py`.
**Driver demo:** `SlapPyEngineExamples/examples/hello_composite.py`.

The composite-scene round-trip test surfaces a Phase-C-like
disagreement between the engine's subsystems: some of them have a
first-class JSON serializer that lets a game persist state across a
process restart, and some do not. This doc enumerates the gaps so a
caller writing a save/load pipeline knows exactly what it has to
hand-roll on top of what the engine already gives it.

## What IS serialisable today

| Subsystem                   | API                                          | Notes |
| --------------------------- | -------------------------------------------- | ----- |
| `pharos_engine.dynamics`     | `dynamics.serialize.save_world` / `load_world` | JSON round-trip for `World`: positions, prev_positions, velocities, inv_masses, every joint (`JointSpec`), every body (`Body`), gravity, solver_iterations, warn_overdamping flag, current frame counter. Schema is versioned (`SCHEMA_VERSION`). Determinism contract: one `step(dt)` on a reloaded world matches the original next-frame positions within 1e-9. |

Empirical numbers from the round-trip test against the composite demo
(`DEFAULT_FRAMES=180`, 16-node rope, 15-joint chain, 1 rope body):

* save file size: **4 413 bytes** of JSON.
* `world_to_dict` payload has the 11 required top-level keys
  (`schema_version`, `positions`, `prev_positions`, `velocities`,
  `inv_masses`, `bodies`, `joints`, `gravity`, `solver_iterations`,
  `warn_overdamping`, `frame`).
* numpy arrays travel as `{"_dtype", "_shape", "_b64"}` blobs so float64
  precision is preserved without lossy decimal stringification.

## What is NOT serialisable today

Everything else the composite demo touches is **not** round-trippable
through any engine-shipped API. The companion test pins this by probing
for the *absence* of `to_dict` / `from_dict` / `save_*` / `load_*`
methods. Any new serializer that fills a gap will trip the
corresponding probe and force this doc to be updated.

### 1. `pharos_engine.thermal.HeatField`

* No `to_dict`, no `from_dict`, no `save` / `load`.
* The temperature grid is just a numpy array on the field instance; a
  caller can pickle the `.temperature` attribute manually, but the
  engine offers no help with the diffusivity / conductivity scalars or
  with framing it inside the same JSON envelope as a dynamics world.
* Composite-demo impact: the foundry hot spots (clamped each frame to
  `DEFENDER_TEMP=300`) and the diffusion bulk would both reset to
  ambient `T=20` on reload.

### 2. `pharos_engine.zones.ZoneManager` + `RectZone`

* Zone *definitions* (rect bounds, name, material) live as plain
  dataclass fields and are technically reachable for hand-rolled JSON,
  but there is no save/load round-trip — *and* the live occupancy state
  (which entities are inside which zone) is held in a `set[str]` per
  zone that the public API never exposes for serialisation.
* The `on_enter` / `on_exit` callbacks are Python functions captured by
  closure and are not serialisable at all.
* Composite-demo impact: foundry crossings are recounted from scratch
  on reload; an attacker mid-crossing would not re-fire `on_enter`.

### 3. `pharos_engine.iso.combat`

* `Attacker`, `Defender`, `WaveSpec`, `WaveSchedule` are all bare
  dataclasses with no serialisation API.
* `WaveSchedule._elapsed` is private; a save/load pair would need to
  reach into module-private state to restore the in-flight timer.
* Composite-demo impact: a save-mid-wave reload restarts the wave from
  `elapsed=0`, re-emits already-emitted spawns, and corrupts the
  `total_spawns` / `attackers_killed` accounting.

### 4. `pharos_engine.telemetry`

* History is an in-process `deque` (`telemetry._history`); the module
  exposes `get_event_history` / `clear_history` /
  `set_history_capacity` but no `save_history` / `load_history`.
* Subscriber handles are integers tied to the live `_subscribers` dict —
  they cannot be persisted across processes (any reload has to
  re-subscribe its own listeners).
* Composite-demo impact: the demo always reattaches its physics /
  combat / zone counters at the top of `step_scene`, so a save/load
  cycle naturally loses the running counts. Test coverage:
  `SlapPyEngineTests/tests/test_composite_serialize_roundtrip.py::test_composite_world_serialize_roundtrip`
  observes 180 `physics.step` events plus ≥1 `combat.hit` and ≥1
  `zone.enter` event from a fresh subscriber attached at run start.

### 5. Cross-cutting orchestration

The composite demo's own `Scene` dataclass (defenders / attackers /
zone records / topology history / nan-watch flag) is **not**
serialisable — neither by `dynamics.serialize` nor by any
purpose-built subsystem API. Any production game build that wants a
true checkpoint will have to combine:

1. `dynamics.serialize.save_world` for the rope `World`.
2. Hand-rolled JSON for the iso-combat objects (`Defender.hp`,
   `Defender.pos`, `WaveSchedule._elapsed`).
3. Hand-rolled JSON for the heat field's temperature grid +
   diffusivity / conductivity scalars.
4. Hand-rolled JSON for live zone occupancy (the set of entity ids
   inside each zone).
5. A re-subscribe pass on telemetry listeners after the load.

## Recommended next steps (not in Sprint 4 scope)

* Promote `HeatField` to_dict / from_dict (just the temperature array
  + the two scalars).
* Add a `ZoneManager.to_dict` that captures rect definitions + the
  current occupancy `set[str]`; document that `on_enter` / `on_exit`
  remain caller-owned and must be re-attached after a load.
* Add `WaveSchedule.to_dict` exposing `_elapsed` as a public field so
  the in-flight wave timer survives.
* Optional: a `telemetry.save_history(path)` that JSON-encodes the
  current ring buffer for offline analysis. Subscribers stay
  in-process — they are intentionally not persisted.
