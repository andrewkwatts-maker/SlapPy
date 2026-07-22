# Pharos Engine Lifecycle Contract

This document formalises the lifecycle hooks honoured by the engine and
its subpackages. The hooks predate the v0.3 surface freeze (they were
introduced as part of the Engine-Usability sprint that also landed
`AssetManifest`, `SceneManifest`, and `ScriptBinding`); this page
captures the existing contract so plug-in authors, mod tooling, and
generated bindings can rely on a single source of truth.

## The three call-sites

Every Pharos Engine lifecycle hook fires at one of three points:

| Phase    | When                                         | Reentrant?         |
|----------|----------------------------------------------|--------------------|
| start    | Once, after the engine has bound its scene   | No                 |
| step     | Every simulation tick, with `dt: float`      | Yes (every frame)  |
| shutdown | Once, before the run loop exits              | No                 |

The three phases are stable: any future surface additions slot into the
existing trichotomy rather than introducing a fourth lifecycle moment.

## Entity / Script hooks

Entity scripts are the canonical user-authored hook target. Both the
class-based (`Script`) and module-based (`AssetManifest` / `ScriptBinding`)
forms map onto the same three phases.

| Phase    | `Script` method                  | YAML script function          |
|----------|----------------------------------|-------------------------------|
| start    | `on_start(self, entity)`         | `on_launch(entity)`           |
| step     | `on_update(self, entity, dt)`    | `on_tick(entity, dt)`         |
| shutdown | `on_destroy(self, entity)`       | `on_end(entity)`              |

The dual naming is historical: `on_launch / on_tick / on_end` predates
the typed `Script` class. Both forms remain supported; new code should
prefer the typed `Script` API.

Additional optional hooks:

* `Script.on_event(self, entity, event)` — fired when
  `scene.events.emit()` matches.
* `Script.on_collision(self, entity, other)` — fired by
  `CollisionManager` per contact.
* `Entity.on_create()` / `Entity.on_destroy()` — engine-owned entry
  points that delegate to attached scripts.

## Engine-level hooks

The `Engine` class exposes module-decorator-style hooks for
non-entity systems (HUD overlays, telemetry pumps, post-process
chains):

```python
@engine.on_tick
def hud_update(dt: float) -> None:
    ...
```

The convention is documented in `docs/getting_started.md` and the
`docs_gen` generator. Engine-level hooks have no "per-entity" parameter
because they are scene-global.

## Subpackage hooks

The Protocols added in F5 + F6 (`WorldLike`, `DynamicsWorldLike`,
`Renderable`, `PostProcessParams`, `ZoneProtocol`, `HeatSourceProtocol`,
`NodeProtocol`, `PostProcessPassProtocol`, `EventEmitterProtocol`,
`EventSubscriberProtocol`, `ComputeKernelProtocol`, `LLMBackendProtocol`)
formalise the *structural* shape required to plug into each subpackage.
None of them mandate `on_engine_*` hooks directly — instead, the engine
drives them through their existing per-subpackage step methods:

| Subpackage     | Per-step entry point                       |
|----------------|--------------------------------------------|
| `dynamics`     | `World.step(dt)`                           |
| `thermal`      | `HeatField.step(dt)`                       |
| `fluid`        | `GlobalFluidSim.step(dt)` (Rust-backed)    |
| `softbody`     | `pharos_engine.softbody.step(world)`        |
| `zones`        | `ZoneManager.update(positions)`            |
| `post_process` | `PostProcessExecutor.run(...)`             |
| `compute`      | `ComputePipeline.dispatch(pass_)`          |
| `telemetry`    | `emit(name, **payload)`                    |

A custom system that wants to ride the engine clock implements
`Script.on_update` (per-entity) or registers via
`Engine.on_tick` (global), then calls its subpackage entry point
inside that hook. This keeps the engine's run loop single-threaded and
deterministic — every per-frame call originates from one of the two
known dispatch sites.

## Contract guarantees

1. **Start happens exactly once.** If your hook keeps mutable state, it
   is safe to initialise it in `on_start`. The engine never re-calls
   start without a corresponding shutdown.
2. **Step is monotonic in `dt`.** `dt` is always > 0 and finite. The
   engine clamps degenerate values (NaN, negative) before dispatch.
3. **Shutdown always pairs with start.** Even when the run loop crashes
   mid-frame, the engine drains the shutdown queue before exiting so
   resource handles (GPU buffers, file locks, network sessions) get a
   chance to clean up.
4. **Hook exceptions are isolated.** Telemetry's `emit` and the entity
   `tick` loop wrap each subscriber in try/except so a buggy hook does
   not break the producer. Hooks should still raise on programming
   errors — they will be logged via `logging.getLogger(__name__)`.
5. **Hook ordering within a phase is insertion order.** Subscribers
   added first run first. The opt-in `enable_pattern_index` on
   `telemetry` documents the one exception (cross-bucket order may
   differ).

## Hot-reload semantics

When a script module is hot-reloaded via the manifest watcher
(`AssetManifest` + watcher callback), the engine:

1. Calls `on_end` / `on_destroy` on the old module for every bound
   entity.
2. Re-imports the module.
3. Calls `on_launch` / `on_start` on the new module for every still-
   alive entity.

This preserves the start-before-step contract across reloads. Scripts
that hold per-frame state in module globals must re-initialise inside
`on_launch` to survive a reload.

## See also

* `docs/engine_surface_v030.md` — full public-surface reference.
* `docs/getting_started.md` — first-run scaffold + script tutorial.
* `python/pharos_engine/script.py` — `Script` base class.
* `python/pharos_engine/asset_manifest.py` — `ScriptBinding`.
* `PharosEngineTests/tests/test_protocols.py` — Round 3 Protocols.
* `PharosEngineTests/tests/test_subpackage_protocols.py` — F6
  per-subpackage Protocols.
