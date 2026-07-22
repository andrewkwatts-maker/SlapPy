# Phase D Strip Pass v2 — Dry-Run Audit

**Status:** DRY-RUN. No files have been deleted. Phase D deletions are
externally gated on Ochema Circuit CI going green after its import
migration to the new `pharos_engine` surface. See the plan at
`C:/Users/Andrew/.claude/plans/ok-we-were-working-reactive-valley.md`,
Phase D "Gating policy".

This audit enumerates each candidate module from Phase D step 3,
counts engine/test/game consumers, and classifies each as:

- **safe to delete** — zero consumers outside the candidate set itself
- **safe-after-migrating-X** — consumers exist but only inside the
  engine, and a documented migration to the repackaged surface
  (`pharos_engine.{topology,numerics,zones,thermal}`) clears them
- **blocked-on-Y** — game-side consumers exist; deletion would break
  out-of-repo tests until those games migrate

Phase B has already landed the repackaged numerical cores:
- `pharos_engine.topology.connected_components` (union-find on a bond
  graph) — covers `physics/cc_label.py`'s entire surface
- `pharos_engine.numerics.vcycle_poisson` — covers
  `physics/pressure_multigrid.py`'s Poisson solver
- `pharos_engine.zones.ZoneManager` / `RectZone` / `ThresholdZone` —
  covers `deform_zones.py`'s zone data model
- `pharos_engine.thermal.HeatField` — covers
  `physics/boundary_exchange.py`'s heat-Laplacian math

All four repackaged modules exist on `master` today (zones 305 LOC,
numerics 421 LOC, topology 198 LOC, thermal 388 LOC).

---

## `__init__.py` deform_modes coupling audit

**The plan flagged the top-level `pharos_engine/__init__.py` as importing
`deform_modes` at module load (line 20 in the older state). That direct
coupling has already been resolved on master** — `__init__.py` uses
PEP 562 lazy attribute loading (`__getattr__`), and no top-level
`from pharos_engine.deform_modes ...` line remains in
`python/pharos_engine/__init__.py`.

**However, the coupling has moved one hop in** — to
`python/pharos_engine/components.py` line 26:

```python
from pharos_engine.deform_modes import (
    DeformSimMode, DecayMode, DestroyMode, MaterialPreset, resolve_material,
)
```

`components.py` is the module that holds `Component`, `ComponentBase`,
`PhysicsComponent`, `CollisionComponent`, `DeformableLayerComponent`,
and is registered in `__init__.py._LAZY_MAP` for lazy access. The
first `from pharos_engine import Component` (or any of the other
component names) triggers `components.py` import, which fires the
`deform_modes` import.

### Symbols imported from deform_modes by components.py
| Symbol | Type | Used in components.py |
| --- | --- | --- |
| `DeformSimMode` | enum | `DeformableLayerComponent.sim_mode` field (default `COLLISION_TRIGGERED`); checked in `update()` per-frame |
| `DecayMode` | enum | `DeformableLayerComponent.decay_mode` field (default `CONSTANT`) |
| `DestroyMode` | enum | `DeformableLayerComponent.destroy_mode` field (default `PERSIST`); branched in `update()` for `FRAGMENT` and `REMOVE` |
| `MaterialPreset` | enum | `DeformableLayerComponent.material_preset` field; checked against `MaterialPreset.CUSTOM` sentinel |
| `resolve_material` | function | called when `material_preset is not None and is not CUSTOM` to populate `_mat_cfg` |

### Other engine modules that import from deform_modes (top-level)
| Module | Line | Symbols |
| --- | --- | --- |
| `physics/boundary_exchange.py` | 51 | `CellMaterial` |
| `physics/body.py` | 14 | `CellMaterial` |
| `physics/pressure_multigrid.py` | 47 | `CellMaterial` (under `TYPE_CHECKING`) |
| `physics/scene_loader.py` | 53 | `cell_material_for` |
| `physics/world.py` | 29 | (multiple — full deform_modes surface) |
| `ui/editor/deform_panel.py` | 146,172,349,367,419,443,467,513,550,559,599,627,636,645,815,978 | lazy imports inside methods — `MaterialPreset`, `list_materials`, `DeformSimMode`, `DecayMode`, `CrackMode`, `MATERIAL_CONFIGS`, `DestroyMode`, `PhysicsCoupling`, `RepairMode`, `get_material` |

### Decoupling sequence required before `deform_modes.py` can be deleted
1. **`components.py`** — replace the 5 imported symbols with their
   equivalents in `softbody.material.MATERIALS` /
   `fluid.material.MATERIALS`. `DeformableLayerComponent` itself may
   need to be retired or rewritten against the unified
   `pharos_engine.dynamics.Body` (`kind="lattice"`).
2. **All five `physics/*.py` modules** that import from `deform_modes`
   are themselves on the Phase D cut list (boundary_exchange, body via
   physics.world chain, pressure_multigrid, scene_loader, world).
   They die together; no separate migration needed.
3. **`ui/editor/deform_panel.py`** — the plan calls for retargeting
   this onto `pharos_engine.zones`. Material/mode dropdowns must be
   rebuilt against `softbody.material` + `fluid.material` enums.

Until step 1 is done, `from pharos_engine import Component` will
ImportError if `deform_modes.py` is removed. **This blocks every
test in the suite that touches the component layer.**

---

## Per-module audit

### `python/pharos_engine/physics/frontier.py`
- **LOC:** 361
- **Repackaged-as:** *(none — genuinely dead per plan; hull-A* prioritisation, not generic pathfinding)*
- **Consumers in engine:**
  - `python/pharos_engine/physics/__init__.py:45` — `from pharos_engine.physics.frontier import FrontierConfig, FrontierSolver`
  - `python/pharos_engine/physics/world.py:43` — `from pharos_engine.physics.frontier import FrontierConfig, FrontierSolver`
- **Consumers in tests:**
  - `python/tests/test_frontier.py:19` — `from pharos_engine.physics.frontier import (...)`
- **Consumers in games:** none in Ochema Circuit / Bullet Strata / Stone Keep
- **Strip status:** safe-after-migrating-world.py-and-physics-init
- **Action required before delete:** delete `physics/__init__.py` re-export, delete `physics/world.py` import + every `FrontierSolver` call site (world.py itself is on the cut list — they die together), delete `test_frontier.py`.

### `python/pharos_engine/physics/boundary_exchange.py`
- **LOC:** 303
- **Repackaged-as:** `pharos_engine.thermal.HeatField` (`exchange_two_regions`, conservative heat-Laplacian — same formula proven correct by WP-O fix)
- **Consumers in engine:**
  - `python/pharos_engine/physics/__init__.py:10` — `from pharos_engine.physics.boundary_exchange import BoundaryExchange`
  - `python/pharos_engine/physics/world.py:37` — same
- **Consumers in tests:**
  - `python/tests/test_boundary_exchange.py` — direct
  - `python/tests/test_boundary_exchange_integration.py:4` — references the unit suite by name
  - `python/tests/test_phase_b_residency.py:190` — `def test_boundary_exchange_marks_contact_slots_dirty` (touches the wrapper through residency)
- **Consumers in games:** none
- **Strip status:** safe-after-migrating-world.py-and-physics-init
- **Action required before delete:** confirm `thermal.HeatField` round-trip parity (mass-conservation invariant + Laplacian numerical equality on the existing fixtures); delete `test_boundary_exchange*.py`; drop the residency dirty-flag test in `test_phase_b_residency.py` (or re-target onto thermal).

### `python/pharos_engine/physics/cc_label.py`
- **LOC:** 135
- **Repackaged-as:** `pharos_engine.topology.connected_components` (weighted union-find with path compression; also `connected_components_grid` for the 2D cell-bond legacy compat path)
- **Consumers in engine:**
  - `python/pharos_engine/physics/hull.py:799` — lazy `from pharos_engine.physics.cc_label import connected_components` inside a method
- **Consumers in tests:**
  - `python/tests/test_spawn_fragment.py:23` — `from pharos_engine.physics.cc_label import connected_components`
- **Consumers in games:** none (Ochema/Strata/Keep all clean)
- **Other call sites:** `SlapPyEngineExamples/examples/legacy/physics_projectile_demo.py:42` — legacy example, dies with the demo cleanup
- **Strip status:** safe-after-migrating-hull.py-import
- **Action required before delete:** flip `physics/hull.py:799` to `from pharos_engine.topology import connected_components` (signatures match — same `bond_bits` + `neighbour_indices` contract). Retarget `test_spawn_fragment.py` onto topology, or delete it once `hull.py` itself is deleted as part of the broader physics cut.

### `python/pharos_engine/physics/pressure_multigrid.py`
- **LOC:** 468
- **Repackaged-as:** `pharos_engine.numerics.vcycle_poisson` (multigrid V-cycle, SOR sweeps + restriction/prolongation operators)
- **Consumers in engine:**
  - `python/pharos_engine/physics/world.py:2315` — lazy `from pharos_engine.physics.pressure_multigrid import vcycle_project_v` inside `_solve_pressure`
- **Consumers in tests:**
  - `python/tests/test_multigrid_projection.py:24` — direct
  - `python/tests/test_phase_c_projection.py:18` — `from pharos_engine.physics import (...)` (re-exported surface)
  - `python/tests/test_phase_c_gpu.py:27` — same
  - `python/tests/test_phase_c_fluid_perf.py:28` — same
- **Consumers in games:** none
- **Strip status:** safe-after-migrating-world.py-projection-call
- **Action required before delete:** world.py's `_solve_pressure` either gets retargeted onto `numerics.vcycle_poisson` (matching signature `(rhs, mask, iters_per_level, levels) -> solution`), or world.py itself goes away in the broader physics cut. Drop all four test files; the new fluid surface owns pressure-projection verification.

### `python/pharos_engine/physics/crack_repair_adapter.py`
- **LOC:** 258
- **Repackaged-as:** *(no numerical core to save — bridge shim only, per plan)*
- **Consumers in engine:**
  - `python/pharos_engine/physics/__init__.py:39` — re-export
  - internal lazy imports of `deform_crack` (line 156) and `deform_repair` (line 157)
- **Consumers in tests:**
  - `python/tests/test_crack_repair_adapter.py:18` — direct
- **Consumers in games:** none direct (Ochema/Strata use `deform_crack` and `deform_repair` directly, not through this adapter)
- **Strip status:** safe to delete
- **Action required before delete:** drop the re-export from `physics/__init__.py`; delete `test_crack_repair_adapter.py`. No game-side surface lost. (Bridge shim is genuinely dead.)

### `python/pharos_engine/physics/deform_adapter.py`
- **LOC:** 216
- **Repackaged-as:** *(no numerical core to save — bridge shim only)*
- **Consumers in engine:**
  - `python/pharos_engine/physics/__init__.py:36` — re-export of `PhysicsBodyDeformAdapter`
  - internal eager imports `from pharos_engine.deform_controller import DeformController` (line 40) and `from pharos_engine.deform_zones import ZoneMap` (line 41)
- **Consumers in tests:** none directly; covered transitively by `test_deform_adapter.py` which imports `deform_controller` + `deform_zones` directly
- **Consumers in games:** none
- **Strip status:** safe to delete
- **Action required before delete:** drop the re-export from `physics/__init__.py`. Nothing else needs touching.

### `python/pharos_engine/physics/engine_bridge.py`
- **LOC:** 335
- **Repackaged-as:** *(no replacement planned — bridge shim, per plan "no numerical core to save")*
- **Consumers in engine:**
  - `python/pharos_engine/physics/__init__.py:37` — re-export
  - referenced from `python/pharos_engine/physics/world.py:215` (docstring of `BridgeConfig`)
- **Consumers in tests:**
  - `python/tests/test_engine_bridge.py` — direct (dedicated unit suite)
  - `python/tests/test_engine_physics_integration.py:21,67,82,98,113,133,186` — uses `PhysicsEngineBridge` to assert `Physics.Contact/Impact/Fragment/Settled` events fan-out
- **Consumers in games:** none directly; games consume events from `pharos_engine.event_bus` instead
- **CI references:**
  - `.github/workflows/physics-tests.yml:51` — selects `python/tests/test_engine_bridge.py`
  - `.github/workflows/physics-coverage.yml:55` — same
- **Strip status:** safe-after-migrating-test-suite-and-CI-yml
- **Action required before delete:** delete both test files; drop the CI workflow lines that select them. The "auto-publish contacts to EventBus" behaviour is no longer needed once the old physics/world.py contacts pathway is gone — the new softbody/fluid surfaces publish their own events.

### `python/pharos_engine/physics/granular_render.py`
- **LOC:** 344
- **Repackaged-as:** **superseded** by `fluid.render.FluidRenderer` (marching-squares surface render of granular materials, faster + already in production)
- **Consumers in engine:**
  - `python/pharos_engine/physics/__init__.py:46` — re-export of `GranularComposite`
- **Consumers in tests:**
  - `python/tests/test_granular_render.py` — direct (dedicated unit suite, ~7 tests)
  - `SlapPyEngineTests/tests/visual/test_vis_granular.py` — visual regression
- **Consumers in games:** none
- **Other call sites:** `SlapPyEngineExamples/examples/legacy/physics_sand_pile_demo.py:25` — legacy example
- **Strip status:** safe-after-deleting-tests
- **Action required before delete:** delete `test_granular_render.py` + `test_vis_granular.py`; drop the re-export. The fluid renderer already has full visual regression coverage; nothing is lost.

### `python/pharos_engine/deform_modes.py`
- **LOC:** 1222 (largest single file in the cut list)
- **Repackaged-as:** partial — `MATERIAL_CONFIGS` maps onto `softbody.material.MATERIALS` + `fluid.material.MATERIALS`; the mode enums (`DeformSimMode`, `DecayMode`, `DestroyMode`, `CrackMode`, `RepairMode`, `PhysicsCoupling`) are mostly unused after the rebuild
- **Consumers in engine:**
  - `python/pharos_engine/components.py:26` — **top-level eager import** (see "deform_modes coupling audit" above); pulls `DeformSimMode`, `DecayMode`, `DestroyMode`, `MaterialPreset`, `resolve_material` into `DeformableLayerComponent`
  - `python/pharos_engine/physics/boundary_exchange.py:51` — `CellMaterial`
  - `python/pharos_engine/physics/body.py:14` — `CellMaterial`
  - `python/pharos_engine/physics/pressure_multigrid.py:47` — `CellMaterial` (TYPE_CHECKING)
  - `python/pharos_engine/physics/scene_loader.py:53` — `cell_material_for`
  - `python/pharos_engine/physics/world.py:29` — full surface
  - `python/pharos_engine/ui/editor/deform_panel.py` — 16 lazy method-level imports (line numbers in coupling audit above)
- **Consumers in tests:**
  - `python/pharos_engine/tests/test_deform_modes.py:6` — dedicated unit suite
  - `python/tests/test_phase_c_projection.py:17` — `CellMaterial, cell_material_for`
  - `python/tests/test_phase_c_gpu.py:26` — `cell_material_for`
  - `python/tests/test_phase_c_fluid_perf.py:27` — `cell_material_for`
- **Consumers in games:**
  - **Ochema Circuit** — `entities/vehicle.py:23` (multi-symbol import), `systems/collision_system.py:15` (`DeformSimMode` under TYPE_CHECKING)
  - **Bullet Strata** — `entities/cover.py:13` (`MaterialPreset, CrackMode, resolve_material`), `entities/enemy.py:12` (`MaterialPreset, resolve_material`), `TODO_ENGINE_FEATURES.md` references 7 distinct symbols
  - **Stone Keep** — none
- **Strip status:** **blocked-on-game-migrations** (Ochema + Bullet Strata)
- **Action required before delete:**
  1. Migrate `components.py:26` off `deform_modes`. Decide: retire `DeformableLayerComponent` (covered by `softbody.Body(kind="lattice")`) or rewrite it against `softbody.material`.
  2. Ochema Circuit migrates `entities/vehicle.py` and `systems/collision_system.py` to the new surfaces, then their CI confirms green.
  3. Bullet Strata migrates `entities/cover.py` and `entities/enemy.py` and updates `TODO_ENGINE_FEATURES.md`.
  4. Physics modules listed above are all on the cut list — they die together with `deform_modes`. No separate decoupling needed for them.
  5. `ui/editor/deform_panel.py` is retargeted onto `pharos_engine.zones` + `softbody.material` + `fluid.material`.

### `python/pharos_engine/deform_controller.py`
- **LOC:** 219
- **Repackaged-as:** *(no replacement planned per plan — "pure old-physics; die together")*
- **Consumers in engine:**
  - `python/pharos_engine/physics/deform_adapter.py:40` — top-level import of `DeformController` (deform_adapter is itself on the cut list)
- **Consumers in tests:**
  - `python/pharos_engine/tests/test_deform_controller.py` — dedicated unit suite
  - `python/tests/test_deform_controller.py` — 21 in-method imports of `DeformController`, `SimState`, `SimFrequencyBudget`
  - `python/tests/test_deform_adapter.py:11` — `DeformController, SimState`
- **Consumers in games:**
  - **Bullet Strata** — `entities/cover.py:12`, `entities/enemy.py:11`, `scenes/arena.py:85`, `TODO_ENGINE_FEATURES.md` (3 references including `SimFrequencyBudget`)
  - **Ochema Circuit** — none
  - **Stone Keep** — none
- **Strip status:** **blocked-on-Bullet-Strata-migration**
- **Action required before delete:** Bullet Strata migrates `entities/cover.py`, `entities/enemy.py`, `scenes/arena.py` onto whatever replaces the simulation budget pattern (likely `pharos_engine.zones` + the unified `dynamics.World.step()` substep cadence). Engine-side deletion is straightforward once games are off it.

### `python/pharos_engine/deform_crack.py`
- **LOC:** 261
- **Repackaged-as:** *(no replacement planned)*
- **Consumers in engine:**
  - `python/pharos_engine/physics/crack_repair_adapter.py:156` — lazy import inside method (adapter is itself on the cut list)
- **Consumers in tests:**
  - `python/tests/test_deform_modules.py` — 10 in-method imports (`CrackPass`, `CRACK_RADIAL`, `CRACK_NONE`, `CRACK_GRAIN`)
  - `python/tests/test_tags_zheight_deform_extras.py` — 13 in-method imports
- **Consumers in games:**
  - **Ochema Circuit** — `systems/collision_system.py:13` — `from pharos_engine.deform_crack import CrackPass, CRACK_NONE, CRACK_RADIAL`
- **Strip status:** **blocked-on-Ochema-migration**
- **Action required before delete:** Ochema Circuit migrates `systems/collision_system.py` off `CrackPass`. The closest replacement in the rebuild is `softbody.solver` beam-break events; the "crack pattern" semantics may need to be rebuilt as a presentation layer over breakage events.

### `python/pharos_engine/deform_repair.py`
- **LOC:** 300
- **Repackaged-as:** *(no replacement planned)*
- **Consumers in engine:**
  - `python/pharos_engine/physics/crack_repair_adapter.py:157` — lazy import (adapter on cut list)
- **Consumers in tests:**
  - `python/tests/test_config_and_repair.py` — 13 in-method imports of `DeformRepairer`
  - `python/tests/test_deform_repair_gpu.py` — 5 in-method imports
  - `python/tests/test_deform_repair_db.py` — 15 in-method imports
  - `python/tests/test_deform_modules.py` — 11 in-method imports
  - `python/tests/test_ochema_extra2.py` — 3 in-method imports
- **Consumers in games:**
  - **Ochema Circuit** — `systems/repair_system.py:8` (top-level), `SlapPyEngineTests/tests/test_repair_system.py` (5 in-method imports of `DeformRepairer`)
- **Strip status:** **blocked-on-Ochema-migration**
- **Action required before delete:** Ochema Circuit migrates `systems/repair_system.py` off `DeformRepairer`. No direct engine replacement is planned; the repair semantics likely become game-side logic over softbody beam-rebind events.

### `python/pharos_engine/deform_zones.py`
- **LOC:** 180
- **Repackaged-as:** `pharos_engine.zones.ZoneManager` + `RectZone` + `ThresholdZone` (data model preserved: rect / threshold / material tag — per-pixel-physics-only callbacks trimmed)
- **Consumers in engine:**
  - `python/pharos_engine/physics/deform_adapter.py:41` — top-level import of `ZoneMap` (adapter on cut list)
- **Consumers in tests:**
  - `python/pharos_engine/tests/test_deform_zones.py:8` — direct
  - `python/tests/test_deform_modules.py` — 10 in-method imports of `ZoneMap`
  - `python/tests/test_deform_adapter.py:12` — `ZoneMap`
  - `python/tests/test_tags_zheight_deform_extras.py` — 13 in-method imports of `ZoneMap` / `ZoneDef`
- **Consumers in games:**
  - **Ochema Circuit** — `entities/vehicle.py:473` — `from pharos_engine.deform_zones import ZoneMap`
  - **Bullet Strata** — `entities/enemy.py:13` — `from pharos_engine.deform_zones import ZoneMap`, `TODO_ENGINE_FEATURES.md` (2 references)
- **Strip status:** **blocked-on-game-migrations** (Ochema + Bullet Strata) — but the migration target is **already shipped** at `pharos_engine.zones`
- **Action required before delete:** point games at `pharos_engine.zones` instead (signatures should map cleanly because the data model was preserved). Verify `ZoneMap` → `ZoneManager` and `ZoneDef` → `RectZone`/`ThresholdZone` semantics match in the games' specific usage. Once games migrate, retarget `ui/editor/deform_panel.py`'s `ZoneEditorPanel` (already planned by Phase B), then delete.

### `python/pharos_engine/pixel_struct.py`
- **LOC:** 164
- **Repackaged-as:** *(no replacement — "dies with `physics/cell.py`" per plan)*
- **Consumers in engine:**
  - `python/pharos_engine/physics/cell.py:12` — top-level import (cell.py is implicitly on the cut list per plan)
  - `python/pharos_engine/material/node_material.py:66` — docstring reference only ("Read a named PixelStruct field at the current texel position"); no code import
- **Consumers in tests:**
  - `SlapPyEngineTests/tests/test_pixel_struct.py:3` — top-level import
  - `python/tests/test_pixel_struct.py` — 22 in-method imports
  - `python/tests/test_pixel_struct_camera_anim.py` — 13 in-method imports
- **Consumers in games:** none
- **Strip status:** safe-after-deleting-cell.py-and-tests
- **Action required before delete:** delete `physics/cell.py` (already on the cut list — implicit, follows from physics/world deletion), delete the three test files. Audit the `node_material.py:66` docstring; replace the term with whatever the rebuild's equivalent is (or drop the line).

---

## Demo tests on the cut list

Per plan Phase D step 1, these are not deleted — they are **replaced** by
softbody/fluid-flavoured equivalents that test the same behaviour through
the new surfaces.

| File | LOC | Replacement | Status |
| --- | --- | --- | --- |
| `python/tests/test_demo_destructible_wall.py` | 109 | `test_softbody_destructible_wall.py` (write new) | rewrite |
| `python/tests/test_demo_water_container.py` | 140 | already covered by `test_fluid_smoke.py::test_water_drops_into_basin_and_pools` | delete |
| `python/tests/test_demo_sand_pile.py` | 84 | already covered by `test_fluid_granular.py` | delete |
| `python/tests/test_demo_vehicle.py` | 72 | already covered by `test_softbody_vehicle.py` | delete |
| `python/tests/test_demo_vehicle_jointed.py` | 108 | folded into `test_softbody_vehicle.py` | delete |
| `python/tests/test_demo_projectile.py` | 121 | `test_softbody_projectile.py` (write new) | rewrite |
| `python/tests/test_demo_complex_scene.py` | 124 | `test_softbody_complex_scene.py` (write new) | rewrite |
| `python/tests/test_demo_lava_flow.py` | 106 | `test_fluid_thermal_flow.py` using Phase C4 thermal field + `LAVA`/`ICE` materials | rewrite (not delete) |
| `python/tests/test_demo_materials_gallery.py` | 203 | redistributed across `test_softbody_material.py` + `test_fluid_material.py` | rewrite |

**Total demo-test LOC reclaimed across pure-delete entries** (those already
covered): 140 + 84 + 72 + 108 = **404 LOC**.

---

## LOC summary

### Safe to delete (zero consumers outside cut list)
| File | LOC |
| --- | --- |
| `physics/crack_repair_adapter.py` | 258 |
| `physics/deform_adapter.py` | 216 |
| **Subtotal** | **474 LOC** |

### Safe after intra-engine migrations (no game-side blockers)
| File | LOC | Migration |
| --- | --- | --- |
| `physics/frontier.py` | 361 | rewire `physics/world.py` + `physics/__init__.py`; delete test |
| `physics/boundary_exchange.py` | 303 | retarget to `thermal.HeatField`; delete tests |
| `physics/cc_label.py` | 135 | flip `physics/hull.py:799` to `topology.connected_components` |
| `physics/pressure_multigrid.py` | 468 | retarget `physics/world.py:2315` to `numerics.vcycle_poisson` |
| `physics/engine_bridge.py` | 335 | delete tests + CI yml lines |
| `physics/granular_render.py` | 344 | delete tests; fluid renderer supersedes |
| `pixel_struct.py` | 164 | delete with `physics/cell.py`; audit `node_material.py:66` docstring |
| **Subtotal** | **2110 LOC** | |

### Blocked on game migrations (Ochema + Bullet Strata)
| File | LOC | Blocking games |
| --- | --- | --- |
| `deform_modes.py` | 1222 | Ochema + Bullet Strata |
| `deform_controller.py` | 219 | Bullet Strata only |
| `deform_crack.py` | 261 | Ochema only |
| `deform_repair.py` | 300 | Ochema only |
| `deform_zones.py` | 180 | Ochema + Bullet Strata |
| **Subtotal** | **2182 LOC** | |

### Demo tests (pure delete — already covered by softbody/fluid tests)
- 404 LOC (4 files)

### Demo tests (rewrite — behaviour preserved, written against new surfaces)
- 663 LOC (5 files, code rewritten not deleted)

### Grand totals
- **Safe to delete today** (zero migrations needed): **474 LOC** (2 files)
- **Safe to delete after intra-engine migrations** (no external blockers):
  **2,584 LOC** (`474 + 2110`, 9 files)
- **Safe after games migrate**: **+ 2,182 LOC** = **4,766 LOC** total
  across all 14 source modules
- **Plus demo tests**: **+ 1,067 LOC** total demo coverage
- **Plus repackaged-module replacement code**: −1,312 LOC of net new
  surface in `topology/numerics/zones/thermal` (offset; this is added not
  removed, but is the price of preserving the numerical cores)

**Plan's headline estimate of ~4,800 LOC removed is supported by this
audit** (4,766 source + ~404 pure-delete demo tests = ~5,170 LOC raw
removed, less the ~1,312 LOC repackaged surface added back, net
~3,860 LOC down).

---

## Suggested order of operations

Each step takes a green suite to a green suite. Order is critical
because several modules import each other; the wrong order red-bricks
the whole suite.

### Step 1 — `physics/engine_bridge.py` (335 LOC)
**Why first:** zero game consumers, zero engine consumers outside the
two dedicated test files, no numerical core to preserve. Pure shim
deletion. Lowest risk in the entire cut list.

**Risks:**
- `.github/workflows/physics-tests.yml:51` and
  `.github/workflows/physics-coverage.yml:55` need editing in the same
  commit, or CI red.
- `test_engine_physics_integration.py` is 7-call-site, has to be
  removed entirely or rewritten against the new event surface — the
  rewrite is straightforward because the events are still published.

### Step 2 — `physics/crack_repair_adapter.py` (258 LOC)
**Why second:** zero game consumers, only the dedicated unit test
imports it. Bridge shim, no numerical core.

**Risks:**
- Confirm no test_deform_modules.py path runs through the adapter
  before deleting.

### Step 3 — `physics/deform_adapter.py` (216 LOC)
**Why third:** also zero game consumers; coupled to `deform_controller`
+ `deform_zones` only via top-level imports. Safe.

**Risks:**
- `test_deform_adapter.py:11-12` imports `DeformController` + `ZoneMap`
  but does NOT import `PhysicsBodyDeformAdapter` itself by name in
  every call site — verify before deleting.

### Step 4 — `physics/granular_render.py` (344 LOC)
**Why fourth:** superseded by `fluid.render.FluidRenderer`; delete the
two test files, drop the re-export. No engine wiring beyond
`physics/__init__.py`.

**Risks:**
- `SlapPyEngineTests/tests/visual/test_vis_granular.py` is a visual regression — verify
  there is fluid-renderer visual coverage of equivalent scenes before
  deleting.

### Step 5 — `physics/cc_label.py` (135 LOC)
**Why fifth:** smallest of the intra-engine retargets. One-line
`physics/hull.py:799` flip to `pharos_engine.topology.connected_components`.
Run `test_spawn_fragment.py` against the new path; if green, delete.

**Risks:**
- Signature mismatch in the legacy 2D grid mode — `topology` exports
  both `connected_components` (edge-list) and `connected_components_grid`
  (legacy compat helper). Use the grid variant if `hull.py:799` passes
  a 2D bond array.

### Step 6 — `physics/boundary_exchange.py` (303 LOC)
**Why sixth:** retarget to `thermal.HeatField`. Run the existing
`test_boundary_exchange*.py` against the new path as a parity check
(same inputs → same outputs ± float tolerance); if parity holds, the
heat-Laplacian conservation invariant migration is proven. Then delete
the wrapper + its tests.

**Risks:**
- The WP-O fix that made the original formula conservative has to be
  in the `HeatField.exchange_with` implementation. Verify the
  conservation invariant test fixture (`test_boundary_exchange.py`'s
  energy-budget assertion) ports over and passes.

### Step 7 — `physics/pressure_multigrid.py` (468 LOC)
**Why seventh:** retarget `physics/world.py:2315` `_solve_pressure`'s
lazy import to `numerics.vcycle_poisson`. Run
`test_multigrid_projection.py` against the new path; if green, drop
the wrapper + all four test files.

**Risks:**
- `test_phase_c_projection.py`, `test_phase_c_gpu.py`,
  `test_phase_c_fluid_perf.py` all import multiple `physics`
  re-exports — they may depend on more than just `vcycle_project_v`.
  Audit each before deleting.
- The GPU path in `test_phase_c_gpu.py` exercises a WGSL shader that
  may need updating in lockstep.

### Step 8 — `physics/frontier.py` (361 LOC)
**Why eighth:** genuinely dead per plan. Delete `physics/__init__.py`
re-export + `physics/world.py:43` import + every `FrontierSolver` call
site in `physics/world.py`. Frontier is hull-A* pathfinding — there is
NO consumer using it for actual pathfinding (only the unit test).
Drop `test_frontier.py`.

**Risks:**
- `physics/world.py` is itself slated for deletion eventually; if
  the broader world.py cut is sequenced before frontier is excised,
  this step folds in. Check sequence.

### Step 9 — Game gating point: WAIT for Ochema CI green
**Do not proceed below this line until Ochema's CI is green on its
new-surface migration.** Per plan Phase D gating policy.

### Step 10 — `deform_zones.py` (180 LOC)
**Why first after gating:** target already shipped at
`pharos_engine.zones`. Games migrate `ZoneMap` → `ZoneManager`; engine
deletes the legacy file. Retarget `ui/editor/deform_panel.py`
ZoneEditorPanel onto `pharos_engine.zones` (already planned by Phase B).
Drop `test_deform_zones.py` + `test_deform_modules.py` zone hunks +
`test_tags_zheight_deform_extras.py` zone hunks.

### Step 11 — `deform_controller.py` (219 LOC)
**Why eleventh:** Bullet Strata is the only game blocker. Once Strata
migrates `entities/cover.py`, `entities/enemy.py`, `scenes/arena.py`,
delete the file + all controller tests.

### Step 12 — `deform_crack.py` + `deform_repair.py` (561 LOC combined)
**Why twelfth:** Ochema blockers. Once Ochema migrates
`systems/collision_system.py` (crack) + `systems/repair_system.py`
(repair), delete both files + their test fan-out
(`test_config_and_repair.py`, `test_deform_repair_gpu.py`,
`test_deform_repair_db.py`, `test_deform_modules.py`,
`test_ochema_extra2.py` partials).

### Step 13 — `deform_modes.py` (1222 LOC, **largest**, **last**)
**Why last:** this is the load-bearing module. Even after step 10-12,
`components.py:26` still pulls 5 symbols from it for
`DeformableLayerComponent`. The decoupling sequence is:
1. Migrate `components.py` off the 5 symbols (decide:
   retire `DeformableLayerComponent` or rewrite against
   `softbody.material`).
2. Retarget `ui/editor/deform_panel.py`'s 16 lazy imports onto the
   new material surfaces.
3. Confirm all `physics/*.py` modules listed in the coupling audit
   have been deleted in earlier steps (they import `CellMaterial` /
   `cell_material_for` from this file).
4. Delete `test_phase_c_*.py` if not already deleted with step 7.
5. Delete `deform_modes.py` + `test_deform_modes.py`.

**Risk:** if any step in the decoupling sequence is skipped,
`from pharos_engine import Component` ImportErrors and the entire suite
red-bricks. This is the single highest-risk deletion in the cut list.

### Step 14 — `physics/{body,cell,hull,world,...}` and `pixel_struct.py`
**Why last:** the rest of the `physics/` tree falls together with the
deletions above. `pixel_struct.py` dies with `physics/cell.py`.
This is the broader physics-module cut and falls outside this audit's
narrow scope, but is implied by the dependency graph collapse after
step 13.

---

## Recommended FIRST module to cut when Phase D actually fires

**`python/pharos_engine/physics/engine_bridge.py`** (335 LOC).

Rationale:
1. **Zero game consumers** — Ochema, Bullet Strata, Stone Keep all
   consume engine events via `pharos_engine.event_bus` directly, not via
   `PhysicsEngineBridge`. No external migration required.
2. **No numerical core to preserve** — pure bridge shim wiring contacts
   to events. Phase B did not repackage it because there was nothing
   numerical to save.
3. **Isolated test surface** — `test_engine_bridge.py` is dedicated;
   `test_engine_physics_integration.py` is removable as its event
   semantics are covered by the new softbody/fluid surfaces' own
   event publication.
4. **Largest LOC win among the "safe to delete today" group** (335 vs.
   258 for `crack_repair_adapter.py`, 216 for `deform_adapter.py`).
5. **Smallest blast radius** — only one upstream consumer (`physics/__init__.py`
   re-export) outside its own test files.

The two CI workflow files (`.github/workflows/physics-tests.yml` and
`physics-coverage.yml`) need their test-selector lines updated in the
same commit; that is the only non-obvious step.

After step 1 (`engine_bridge`), the natural follow-ups are
`crack_repair_adapter.py` (step 2) and `deform_adapter.py` (step 3) —
same "shim, zero game consumers" profile. Together those three commits
remove **809 LOC** with no game-side coordination required.
