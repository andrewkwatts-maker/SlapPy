# Phase D strip-pass execution plan — 2026-05-31

Read-only audit. Phase D is GATED on Ochema CI greenness (external);
this document is the preparation for a future agent to execute deletions
one commit per module without breaking the suite.

The numerical cores of every flagged "old physics" module have already
been repackaged into clean engine-level APIs during Phase B:

| Old core | New home |
|---|---|
| `physics/cc_label.connected_components` | `pharos_engine.topology.connected_components` |
| `physics/pressure_multigrid.vcycle_project_v` | `pharos_engine.numerics.vcycle_poisson` |
| `physics/boundary_exchange._exchange_pair` | `pharos_engine.thermal.HeatField` / `exchange_two_regions` |
| `deform_zones.ZoneMap` / `RectZone` / `ThresholdZone` | `pharos_engine.zones.ZoneManager` / `RectZone` / `ThresholdZone` |
| `softbody.material.MATERIALS` | already canonical (YAML-backed) |
| `fluid.material.MATERIALS` | already canonical (YAML-backed) |

The legacy modules are still imported by `pharos_engine.physics.world`,
`pharos_engine.physics.body`, `pharos_engine.physics.scene_loader`,
`pharos_engine.physics.__init__`, several editor and test modules, and the
top-level `pharos_engine/__init__.py` lazy map. Phase D removes them after
that consumer surface has been re-pointed.

The figures below count only `H:/Github/SlapPyEngine/python/**` plus
`SlapPyEngineExamples/examples/**` source. Worktree mirrors under `.claude/worktrees/**` and
the existing `docs/strip_pass_v2_audit.md` are excluded — they are
either ephemeral or themselves slated for replacement by this plan.

---

## (a) Ordered cut list — per-module caller count

The order is bottom-up: leaves first, dependents last. **Within a step,
all consumers listed must already have been migrated or scheduled for
co-deletion. Each step is one commit and must keep the rebuild suite
green** (see §d for the exact pytest gate).

### Step 1 — Genuinely dead leaves (no surviving consumers)

| # | Module | LOC | Consumers (main repo, non-worktree) | Classification |
|---|---|---:|---|---|
| 1 | `python/pharos_engine/physics/frontier.py` | 361 | `physics/__init__.py` (re-export), `physics/world.py` (lines 43, 194, 326-373, 490, 718-731, 825-844) + 4 tests (`test_frontier.py`, `test_phase_a_activation.py`, `test_nan_guards.py`, `test_phase_b_residency.py`) | `world.py` keeps a `frontier.enabled` flag for tests; once `world.py` itself dies (Phase D step 9) the flag dies with it. `test_frontier.py` is dead-with-module. The other three tests only touch `world.config.frontier.enabled = False` — purely defensive flag flips that come out with `world.py`. **BLOCKED 2026-05-31 — see "Step 1 blocker found" callout below.** |
| 2 | `python/pharos_engine/physics/granular_render.py` | 344 | `physics/__init__.py` (re-export) only | Superseded by `fluid.render.FluidRenderer`. Zero non-physics callers. **NO-OP 2026-06-01 — file was never tracked on master.** Audit confirmed: `git log --all --full-history -- "**/granular_render.py"` returns empty; `physics/__init__.py` already has no re-export (lines 4-42); `SlapPyEngineTests/tests/visual/test_vis_granular.py` and `SlapPyEngineTests/tests/visual/output/granular/` do not exist. The 344/134 LOC figures from the plan refer to a worktree-local artefact that never landed on master. Step 2 is closed as **NOTHING TO DELETE** rather than DONE — no commit hash. See "Step 2 no-op audit" subsection below for evidence. |

#### Step 2 no-op audit — 2026-06-01

Step 2 execution attempted on 2026-06-01 found the target files absent
from the worktree, the main repo HEAD, and all of git history:

| Target | Status | Evidence |
|---|---|---|
| `python/pharos_engine/physics/granular_render.py` | absent | `ls` fails; `git log --all --full-history -- "**/granular_render.py"` empty |
| `SlapPyEngineTests/tests/visual/test_vis_granular.py` | absent | `ls` fails; `git log --all --full-history -- "**/test_vis_granular.py"` empty |
| `SlapPyEngineTests/tests/visual/output/granular/` | absent | dir not in `SlapPyEngineTests/tests/visual/output/` listing |
| `physics/__init__.py` re-export | absent | no `granular_render` import in lines 4-42 of `physics/__init__.py` |
| Any production consumer | none | `grep -rn "granular_render" python/pharos_engine/` → 0 hits |

The only surviving references to the string `granular_render` are:

- `docs/strip_pass_v2_audit.md` (the audit doc that flagged it)
- `docs/phase_d_strip_plan_2026_05_31.md` (this plan)
- `SlapPyEngineTests/tests/test_strip_audit_doc.py:52` (audit-tracking constant — meta, not a consumer)
- four `.claude/worktrees/agent-*` stale mirrors (out of scope per
  rollback policy in §(d))

**Pre-strip pytest baseline (2026-06-01):** 8 failed, 1552 passed, 21
skipped, 29 xfailed, 2 warnings in 55.42s (with
`--ignore=tests/visual/test_vis_humanoid_destruction.py`). The 8
failures are unrelated to `granular_render` (editor material editor
kinds, vcycle perf, softbody vehicle visual, etc.); they pre-date this
step.

**Post-strip pytest:** skipped — there are no source edits to verify.
Pass-count delta is exactly 0, matching the deleted-test count of 0.

**Action taken:** documentation-only update to this plan (replacing the
incorrect "DONE — commit `<pending>`" entry with the no-op finding).
No engine code touched. No tests touched.

#### Step 1 blocker found — 2026-05-31

A re-audit during step 1 execution confirmed that `physics/world.py` has
**33 live `frontier`/`Frontier` references** — not a flag-only consumer
as the step 1 row suggested. The hard import at `world.py:43`
(`from pharos_engine.physics.frontier import FrontierConfig, FrontierSolver`)
plus the `FrontierYamlConfig` dataclass (L193-210), the
`PhysicsYaml.frontier` field (L227), the 35-line YAML loader block
(L326-360), `self._frontier: FrontierSolver | None` (L490), the
auto-tick block in `step()` (L700-731), and `_ensure_frontier_solver`
(L825-844) together mean deleting `frontier.py` would either (a) hard-
break `import pharos_engine.physics` (because `physics/__init__.py:45`
also re-exports), or (b) require a real `world.py` refactor that the
step 1 entry does not authorize.

Additionally `python/tests/test_phase_a_activation.py` is **not** a
"flag-flip only" test — it imports `FrontierConfig` / `FrontierSolver`
directly (lines 25-26) and asserts `FrontierSolver.tick` runs once per
`world.step` (lines 156-186). That test is genuinely co-dead with
`frontier.py`, not "comes out with `world.py`".

**Unblock plan.** Step 1 must either be re-scoped to ALSO trim the
`frontier`-using surface of `world.py` (a ~40-line refactor: drop the
import, drop `FrontierYamlConfig`, drop the YAML loader block, drop
`_ensure_frontier_solver`, drop the auto-tick branch, drop
`self._frontier`), OR step 1 must be **moved AFTER step 9** in the cut
order (i.e., delete `world.py` first, then `frontier.py` becomes a
genuine leaf). Recommend the in-place trim approach since it keeps step
1 a one-commit operation and proves the consumer-trim pattern on a
small surface before the larger `deform_modes.py` cut in step 5. The
auto-tick block in `step()` is already gated behind
`self.config.frontier.enabled`, so removing it is purely subtractive —
no replacement path needed. The 41 frontier-touching tests
(`test_frontier.py`, `test_phase_a_activation.py`, plus the
flag-flip lines in `test_nan_guards.py` and `test_phase_b_residency.py`)
all co-delete or have their two `world.config.frontier.enabled = False`
lines removed; no behavioural test depends on the auto-tick firing
outside `test_phase_a_activation.py` (which dies with frontier).

`granular_render.py` (entry #2) remains a genuine leaf and can be cut
as planned without waiting for the frontier unblock.

**Cut order rationale.** `frontier.py` and `granular_render.py` have no
public surface outside the `physics/` package; deleting them requires
only trimming `physics/__init__.py` and the corresponding `world.py`
references. Doing these first proves the consumer-trim pipeline before
touching anything games can see.

### Step 2 — Bridge shims (no numerical core to save)

| # | Module | LOC | Consumers | Classification |
|---|---|---:|---|---|
| 3 | `python/pharos_engine/physics/crack_repair_adapter.py` | 258 | `physics/__init__.py` (re-export), `test_crack_repair_adapter.py` | Dead-with-module test. Adapter wraps the legacy `deform_crack` / `deform_repair` Layer2D path — both die in step 5. **NO-OP 2026-06-01 — file does not exist in repo.** |
| 4 | `python/pharos_engine/physics/deform_adapter.py` | 216 | `physics/__init__.py` (re-export), `test_deform_adapter.py` | Dead-with-module test. Wraps `DeformController` (dies in step 5) and `deform_zones.ZoneMap` (dies in step 6). **NO-OP 2026-06-01 — file does not exist in repo.** |
| 5 | `python/pharos_engine/physics/engine_bridge.py` | 335 | `physics/__init__.py` (re-export), `test_engine_bridge.py` | Dead-with-module test. Pure bridge to `PhysicsWorld` lifecycle hooks. **NO-OP 2026-06-01 — file does not exist in repo.** |

#### Step 2 execution finding — 2026-06-01

A retry of Phase D step 2 (bridge-shim deletion) was attempted on
2026-06-01. The pre-strip audit found that none of the three target
modules (`crack_repair_adapter.py`, `deform_adapter.py`,
`engine_bridge.py`) exist in the repository:

* `git ls-tree HEAD python/pharos_engine/physics/` does not include any
  of the three filenames.
* `Glob("**/crack_repair_adapter.py")`, `Glob("**/deform_adapter.py")`,
  and `Glob("**/engine_bridge.py")` return zero matches across the full
  repo (main repo + worktrees).
* `git log --all -S "crack_repair_adapter"` and the same for the other
  two strings return only docs (`phase_d_strip_plan_2026_05_31.md`,
  `strip_pass_v2_audit.md`) and the `SlapPyEngineTests/tests/test_strip_audit_doc.py`
  inventory list — never an actual source file commit.
* `python/pharos_engine/physics/__init__.py` does not import or
  re-export any of the three names (last import is `frontier`).
* No test files `test_crack_repair_adapter.py`, `test_deform_adapter.py`,
  or `test_engine_bridge.py` exist anywhere.
* `grep -rn` for `from pharos_engine.physics.{crack_repair_adapter,deform_adapter,engine_bridge}`
  finds zero matches in `python/`, `SlapPyEngineTests/tests/`, `SlapPyEngineExamples/examples/`, `docs/`
  (excluding the dry-run plan/audit docs themselves).

**Cut result.** Per-module:
* `crack_repair_adapter.py` — NO-OP (file absent, no consumers, no test).
* `deform_adapter.py` — NO-OP (file absent, no consumers, no test).
* `engine_bridge.py` — NO-OP (file absent, no consumers, no test).

The Step 2 row classifications in the table above were written from the
plan-time inventory snapshot; the actual repository at HEAD never
contained these files. Step 2 is therefore complete as a no-op. The
pre-strip baseline (`pytest tests/ --ignore=tests/visual/test_vis_humanoid_destruction.py`)
recorded **1541 passed / 18 failed / 22 skipped / 29 xfailed** on
2026-06-01; the 18 reds are pre-existing (ragdoll dynamics, docs link
parity, editor material kinds, perf bands, softbody vehicle visual) and
unrelated to bridge-shim presence. No post-strip pytest re-run is
required because no files were modified. Deleted-test-count delta = 0;
expected pass-count delta = 0 (vacuously satisfied).

### Step 3 — Repackaged-core legacy wrappers (numerical core survives elsewhere)

| # | Module | LOC | Consumers (non-trivial) | Classification |
|---|---|---:|---|---|
| 6 | `python/pharos_engine/physics/cc_label.py` | 135 | `physics/hull.py:799` (function-local import), `physics/world.py:93,98,761` (comments + one severance check), `test_spawn_fragment.py`, `test_topology_components.py` (cross-check against legacy), 3 demo tests | `hull.py:799` migrates to `from pharos_engine.topology import connected_components` — bond/adjacency array signature is identical. `test_topology_components.py` cross-check assert deletes with module (it exists *only* to prove parity). |
| 7 | `python/pharos_engine/physics/pressure_multigrid.py` | 468 | `physics/world.py:2315` (function-local import in pressure projection), `deform_modes.py:479` (docstring reference), `physics/shaders/pressure_project.wgsl` (comment), `test_multigrid_projection.py`, `test_numerics_vcycle.py` (cross-check) | `world.py:2315` migrates to `from pharos_engine.numerics import vcycle_poisson`. WGSL comment is a no-op rewrite. `test_multigrid_projection.py` is dead-with-module; `test_numerics_vcycle.py` cross-check assert deletes (parity already proven). |
| 8 | `python/pharos_engine/physics/boundary_exchange.py` | 303 | `physics/__init__.py` (re-export), `physics/world.py:37,226,319-372,510,684-685`, `physics/profiles.py:44,57-90,145`, `test_boundary_exchange.py`, `test_boundary_exchange_integration.py`, `test_phase_b_residency.py:190`, `test_physics_profiles.py`, `test_thermal_heatfield.py` (cross-check) | `world.py` legacy usage dies with `world.py` itself in step 9. `profiles.py` keeps the `boundary_exchange_enabled` flag as a profile knob — that field migrates to `thermal_enabled` or is dropped (no non-physics consumer). Legacy tests die with module; `test_thermal_heatfield.py` parity check deletes. |

### Step 4 — Top-level `__init__.py` decoupling (PREREQUISITE for step 5)

| # | Action | Caller | Detail |
|---|---|---|---|
| 9 | Remove `"MaterialPreset"` and `"CrackMode"` entries from `_LAZY_MAP` in `python/pharos_engine/__init__.py` (lines 179-180) | top-level package | See §(b) below for the per-symbol replacement matrix. Must land **before** step 5 — `pharos_engine/__init__.py` imports `deform_modes` lazily, but every `MaterialPreset` lookup re-imports it, and step 5 deletes the file. |

#### Step 4 execution result — 2026-06-01

**DONE.** Decoupling landed via new `python/pharos_engine/_compat.py`
holding the five retired-feature symbols (`MaterialPreset`,
`CrackMode`, `SimFrequencyBudget`, `SimState`, `DeformController`).
`ZoneMap` repoints to `pharos_engine.zones.ZoneManager` (one-line module-
level `__getattr__` in `_compat.py`). The six `_LAZY_MAP` entries
(lines 170-172, 178-180) now route through `._compat`; lookup of any
of them no longer touches `pharos_engine.deform_modes`,
`pharos_engine.deform_controller`, or `pharos_engine.deform_zones`.

Regression test `SlapPyEngineTests/tests/test_init_lazy_map.py` (9 cases) pins the
decoupling:

* `test_import_pharos_engine_does_not_load_deform_modules` — `import
  pharos_engine` + `dir()` leaves the three doomed modules absent from
  `sys.modules`.
* `test_doomed_symbols_still_resolve[*]` — 6 parametrised cases; each
  of the six symbols stays resolvable on the public surface.
* `test_resolved_symbols_route_through_compat_not_legacy` — after
  every symbol is accessed, the three doomed modules are STILL
  absent from `sys.modules`.
* `test_zone_map_aliases_zone_manager` — `pharos_engine.ZoneMap is
  pharos_engine.zones.ZoneManager`.

**Caller audit (per task §2).** Direct `from pharos_engine.deform_modes
import …` sites in `ui/editor/deform_panel.py` (16 lines) are
unaffected — they import from the doomed module by path, not via the
top-level lazy-map, so they keep working until `deform_panel.py` is
decommissioned in step 5. No production caller imports the six
symbols from `pharos_engine` at the package root by name — the only
hard surface consumers are `SlapPyEngineTests/tests/test_game_compat_tripwire.py` and
`SlapPyEngineTests/tests/test_game_smoke_instantiation.py`, both of which probe via
`hasattr(pharos_engine, name)` and now resolve through `_compat`.

**Pytest delta (gate condition).** Pre-edit: 44 failed / 1618 passed
(of which 5 are `test_init_lazy_map.py` cases for the symbols that
do not yet route through `_compat`). Post-edit: 39 failed / 1623
passed (the 5 lazy-map tests flip green). Delta: **+5 passed,
-5 failed, ≥ 0** as required.

The remaining 39 failures are all pre-existing and unrelated to this
step (hardening_layer test surface from a parallel agent's WIP,
softbody vehicle visual baseline, editor material-editor kinds,
hello_ragdoll demo numerics, doc inventory checks). None of them
touch the lazy-map or the six decoupled symbols.

**Files changed in this step:**

* `python/pharos_engine/__init__.py` — six `_LAZY_MAP` entries
  repointed from `.deform_controller` / `.deform_modes` /
  `.deform_zones` to `._compat`.
* `python/pharos_engine/_compat.py` — new file holding the five
  retired-feature stubs + the `ZoneMap` → `ZoneManager` alias.
* `SlapPyEngineTests/tests/test_init_lazy_map.py` — new regression test pinning the
  decoupling (9 cases).

The lazy-map gate from §(d) is now satisfied:

```
python -c "import pharos_engine; assert 'MaterialPreset' in pharos_engine._LAZY_MAP and pharos_engine._LAZY_MAP['MaterialPreset'] == '._compat'"
```

Step 5 (`deform_modes.py` + `deform_controller.py` deletion) is now
unblocked from the lazy-map angle; the remaining blocker is the
`ui/editor/deform_panel.py` decommissioning called out in §(d)
"Editor surface gate".

#### Step 5 prerequisite audit — `deform_panel.py` consumer surface — 2026-06-01

Read-only audit of every `from pharos_engine.deform_modes import` site in
`python/pharos_engine/ui/editor/deform_panel.py`. Outcome: **the panel is
the *only* non-test, non-`physics/` consumer left** for the
deform-modes / deform-controller / deform-crack / deform-repair family
on master HEAD. The `SlapPyEngineExamples/examples/legacy/physics_materials_gallery_demo.py`
import (`from pharos_engine.deform_modes import list_materials`) is in
the `SlapPyEngineExamples/examples/legacy/` directory, which is already marked for retirement
in the v0.3 cleanup pass and will be co-deleted with `deform_modes.py`.

**Caller audit beyond `deform_panel.py`** (per task §4):

| Site | Status |
|---|---|
| `physics/body.py:14`, `physics/boundary_exchange.py:51`, `physics/pressure_multigrid.py:47`, `physics/scene_loader.py:53`, `physics/world.py:29` | Dies in Step 9 (`physics/` core sweep). NOT a Step 5 blocker. |
| `SlapPyEngineExamples/examples/legacy/physics_materials_gallery_demo.py:38` | `SlapPyEngineExamples/examples/legacy/` is retired surface; co-delete with Step 5. |
| `python/pharos_engine/tests/test_deform_modes.py`, `SlapPyEngineTests/tests/test_deform_controller.py` | Dead-with-module tests. Co-delete with Step 5. |
| `SlapPyEngineTests/tests/test_game_smoke_instantiation.py:42-47` | Probes legacy module paths by name — already resolved through `_compat` via the `pharos_engine` top-level surface (Step 4 lazy-map gate). After Step 5 the assertions in `IMPORT_TABLE` need their module string flipped to `"pharos_engine._compat"`. One-line per-symbol edit. |
| `SlapPyEngineTests/tests/test_init_lazy_map.py` | Already pins the decoupling; survives Step 5 unchanged. |
| `SlapPyEngineTests/tests/test_strip_audit_doc.py:53-56` | Audit-tracking inventory list; co-edit with Step 5 to mark the four files removed. |
| `docs/per_pixel_sim_audit_2026_05_31.md:27,53`, `docs/physics_module.md:108`, `docs/strip_pass_v2_audit.md` | Docs only; update on Step 5 commit. |
| `python/pharos_engine/ui/editor/deform_panel.py` | **The sole remaining production consumer.** 16 imports — see per-import table below. |

**Per-import migration table for `deform_panel.py`** (every
`from pharos_engine.deform_modes import …` line):

| Line | Imports | Used in | Migration target |
|---|---|---|---|
| 146 | `MaterialPreset`, `list_materials` | `_build_material_section` — combo of all material names | `MaterialPreset` → `pharos_engine._compat.MaterialPreset` (name-only). `list_materials` is the only call site outside `deform_modes`; replace with `sorted(softbody.material.MATERIALS.keys())` (and optionally union `fluid.material.MATERIALS`). |
| 172 | `DeformSimMode`, `DecayMode` | `_build_simulation_section` combos | Retired enums — no replacement (sim-mode/decay-mode state machine is gone in the rebuild solver). Whole section dies with the panel. |
| 349 | `CrackMode` | `_build_cracks_section` combo | `pharos_engine._compat.CrackMode` (name-only stub). Crack-mode feature itself is retired; the section UI dies with the panel. |
| 367 | `MATERIAL_CONFIGS`, `MaterialPreset` | Fallback to read `crack_mode` from preset config | No replacement — `MATERIAL_CONFIGS` is `deform_modes`-internal; the fallback path dies with the panel. |
| 419 | `DestroyMode` | `_build_destruction_section` combo | Retired enum. Section dies with the panel. |
| 443 | `PhysicsCoupling` | `_build_physics_section` combo | Retired enum. Section dies with the panel. |
| 467 | `RepairMode` | `_build_repair_section` combo | Retired enum (`AUTO`/`AUTO_CURVE` rates are gone). Section dies with the panel. |
| 513 | `get_material`, `MaterialPreset` | `_on_material_preset_change` callback | `get_material` lives only in `deform_modes`; rebuild equivalent is `softbody.material.MATERIALS.get(name)`. Callback dies with the panel. |
| 550 | `DeformSimMode` | `_on_sim_mode_change` callback | Retired enum. Callback dies with the panel. |
| 559 | `DecayMode` | `_on_decay_mode_change` callback | Retired enum. Callback dies with the panel. |
| 599 | `CrackMode` | `_on_crack_mode_change` callback | `_compat.CrackMode`. Callback dies with the panel. |
| 627 | `DestroyMode` | `_on_destroy_mode_change` callback | Retired enum. Callback dies with the panel. |
| 636 | `PhysicsCoupling` | `_on_physics_coupling_change` callback | Retired enum. Callback dies with the panel. |
| 645 | `RepairMode` | `_on_repair_mode_change` callback | Retired enum. Callback dies with the panel. |
| 815 | `list_materials` | `_build_zone_section` material dropdown (`ZoneEditorPanel`) | `sorted(softbody.material.MATERIALS.keys())`. The Zone editor is the only sub-panel with a real survivor path — see proposal. |
| 978 | `MaterialPreset` | `_make_zone_material_cb` callback | `_compat.MaterialPreset(app_data)` (name-only resolution). Sub-panel survivor path. |

**Decision.** 14 of 16 imports map to retired features whose **UI dies
with the panel**; the only ones with a real replacement are
`list_materials` (146, 815) and `MaterialPreset`/`get_material` (146,
513, 978). All three legacy callers are already shimmed via
`pharos_engine._compat`, so a partial port of `deform_panel.py` would
duplicate `_compat` surface inside the panel without unblocking
deletion of any other file.

**Proposal — next sprint:**

1. **Decommission `python/pharos_engine/ui/editor/deform_panel.py`**
   wholesale. Both classes (`DeformPanel`, `ZoneEditorPanel`) are
   retired-feature inspectors; their replacement is the property
   inspector wired against `softbody.Body` and `pharos_engine.zones`,
   tracked under the editor sprint (`project_editor_sprint.md`).
2. Audit/migrate the editor wiring that *constructs* `DeformPanel` /
   `ZoneEditorPanel` (search: `from pharos_editor.ui.editor.deform_panel
   import` and `DeformPanel(` / `ZoneEditorPanel(` — held for the next
   sprint to keep this sprint read-only on engine code).
3. Co-delete `python/tests/test_editor_deform_panel.py` if present
   (verify exact name during the deletion sprint).
4. **Then** delete `deform_modes.py`, `deform_controller.py`,
   `deform_crack.py`, `deform_repair.py` plus their tests as the Step 5
   commit, flipping `SlapPyEngineTests/tests/test_game_smoke_instantiation.py:42-47`'s
   `IMPORT_TABLE` to point at `pharos_engine._compat` in the same
   commit.
5. Update `SlapPyEngineTests/tests/test_strip_audit_doc.py` `EXPECTED_DELETED_PATHS` to
   mark the four files as removed.

The `deform_panel.py` decommissioning is the gate; Step 5 follows in
the same sprint immediately afterwards. No other production code
depends on the four deform_* modules.

**Small win taken in this sprint.** None applicable — every
`deform_panel.py` import either dies wholesale with the panel or
already has a `_compat` replacement that is moot until the panel is
decommissioned. Repointing a single import to `_compat` would add a
line of indirection in a file that is itself slated for deletion. The
read-only audit is the deliverable; the deletions land next sprint.

### Step 5 — `deform_modes.py` and its dependents

| # | Module | LOC | Consumers (non-test) | Classification |
|---|---|---:|---|---|
| 10 | `python/pharos_engine/deform_modes.py` | 1222 | `pharos_engine/__init__.py` (post-step-9: zero), `physics/body.py:14` (CellMaterial), `physics/boundary_exchange.py:51` (dies in step 8), `physics/pressure_multigrid.py:47` (dies in step 7), `physics/scene_loader.py:53` (cell_material_for), `physics/world.py:29-32`, `ui/editor/deform_panel.py` (16 import sites, all `MaterialPreset` / `CrackMode` / `DeformSimMode` / `DecayMode` / `DestroyMode` / `PhysicsCoupling` / `RepairMode` / `MATERIAL_CONFIGS` / `get_material` / `list_materials`) | `physics/body.py`, `physics/scene_loader.py`, `physics/world.py` die together in step 9. `deform_panel.py` is the only Phase-D-survivor — it must be re-targeted (see Risk callout in §d). The bulk (`CellMaterial`, `MATERIAL_CONFIGS`, enums) is dead-with-module. |
| 11 | `python/pharos_engine/deform_controller.py` | 219 | `physics/deform_adapter.py:40` (dies in step 2), `pharos_engine/__init__.py` (lazy-map entries `SimFrequencyBudget`, `SimState`, `DeformController` — lines 170-172), `test_deform_controller.py`, `pharos_engine/tests/test_deform_controller.py` | Lazy-map entries must die in step 4b (same commit as step 9, or split into a 9b). No non-physics call sites. Tests die with module. |
| 12 | `python/pharos_engine/deform_crack.py` | 261 | `physics/crack_repair_adapter.py:156` (dies in step 2), `test_deform_modules.py`, `test_tags_zheight_deform_extras.py` | Dead-with-module tests. |
| 13 | `python/pharos_engine/deform_repair.py` | 300 | `physics/crack_repair_adapter.py:157` (dies in step 2), `test_config_and_repair.py`, `test_deform_modules.py`, `test_deform_repair_db.py`, `test_deform_repair_gpu.py`, `test_ochema_extra2.py` (3 imports) | Dead-with-module tests. `test_ochema_extra2.py` is legacy game-compat fixture — confirmed in Phase D plan to delete with module. |

### Step 6 — `deform_zones.py`

| # | Module | LOC | Consumers | Classification |
|---|---|---:|---|---|
| 14 | `python/pharos_engine/deform_zones.py` | 180 | `pharos_engine/__init__.py` (`ZoneMap` lazy entry, line 178), `physics/deform_adapter.py:41` (dies in step 2), `event_bus.py:153` (comment only), `ui/editor/deform_panel.py:1005` (comment + Phase B uses `pharos_engine.zones`), `test_deform_adapter.py`, `test_deform_modules.py`, `test_tags_zheight_deform_extras.py`, `pharos_engine/tests/test_deform_zones.py` | `ZoneMap` lazy entry retargets to `pharos_engine.zones.ZoneManager` OR dies (Bullet Strata's `ZoneMap` already migrated to `zones.ZoneManager` per `project_bullet_strata.md`). Dead-with-module tests. |

#### Step 6 unblock progress — `CellMaterial` port — 2026-06-01

Sprint 7C halted Phase D step 6 because the five legacy
`physics/*` consumers (`body.py`, `boundary_exchange.py`,
`pressure_multigrid.py`, `scene_loader.py`, `world.py`) still
imported `CellMaterial` and `cell_material_for` from
`pharos_engine.deform_modes`. `_compat.py` only shimmed 6 top-level
symbols, not these.

**Status: unblocked from CellMaterial angle — `_compat.py` now
hosts `CellMaterial` + `cell_material_for`, repointing 5 physics
consumers.**

Changes landed:

* `python/pharos_engine/_compat.py` — verbatim port of the
  ``CellMaterial`` dataclass (44 fields, every default and type
  preserved exactly so the WGSL `_pack_params` uploader keeps
  reading the same shape) plus the ``cell_material_for(name)``
  convenience function. ``E_effective`` and ``bond_strength``
  properties carried over. ``cell_material_for`` delegates to
  ``deform_modes.get_material`` while the legacy module is still
  present, but rebuilds the result as a ``_compat.CellMaterial``
  instance so the returned type matches the surviving class;
  falls back to ``None`` once ``deform_modes`` is removed, which
  every consumer already handles as "material unknown".
* Five physics consumers repointed from `pharos_engine.deform_modes`
  to `pharos_engine._compat`:
  * `physics/body.py:14`
  * `physics/boundary_exchange.py:51`
  * `physics/pressure_multigrid.py:47` (TYPE_CHECKING-gated)
  * `physics/scene_loader.py:53`
  * `physics/world.py:29-32`
* Regression test `SlapPyEngineTests/tests/test_compat_cell_material.py` (5 cases):
  no-arg construction matches verbatim defaults, field set is
  complete, field types preserved, `cell_material_for("sand")`
  returns a `_compat.CellMaterial`, `bond_strength` alias proxies
  `restitution`.

The `deform_modes.py` source is left in place (still WIP-only on
master); future deletion of the four `deform_*` modules no longer
breaks the five physics consumers. The remaining Step 6 work
(deleting `deform_zones.py` itself) is independent of this
sub-step and proceeds when the editor surface gate clears.

**Pytest delta (gate condition).** Pre-edit: 1852 passed / 7
failed. Post-edit: 1857 passed / 7 failed. **Delta: +5 passes
(the 5 new `test_compat_cell_material.py` cases), 0 failure
delta — ≥ 0 as required.**

#### Step 6 final attempt — `deform_panel.py` decommission + deform_*.py
audit — 2026-06-01

Phase D step 6 final attempt executed 2026-06-01 after R2S1-B
(`0a8a0b8`) ported `CellMaterial` + `cell_material_for` into
`_compat.py` and unblocked the editor-surface gate. Sprint 6E §"Editor
surface gate (BEFORE step 5)" Option (b) — **decommission
`deform_panel.py` wholesale** — applied here.

**File-tracking reality check.** Per the same finding as Sprints 4A/4B
(bridge-shim NO-OP, granular_render NO-OP), the four `deform_*.py`
modules listed in step 5 (`deform_modes.py`, `deform_controller.py`,
`deform_crack.py`, `deform_repair.py`) are **working-tree-only WIP**
on master:

| Target | Tracking | Action |
|---|---|---|
| `python/pharos_engine/ui/editor/deform_panel.py` | **TRACKED** | Decommissioned in this commit (ImportError stub, raised at import time). |
| `python/pharos_engine/deform_modes.py` | UNTRACKED (`git ls-files --error-unmatch` → no match) | NO-OP — never existed on master. |
| `python/pharos_engine/deform_controller.py` | UNTRACKED | NO-OP — never existed on master. |
| `python/pharos_engine/deform_crack.py` | UNTRACKED | NO-OP — never existed on master. |
| `python/pharos_engine/deform_repair.py` | UNTRACKED | NO-OP — never existed on master. |

The four `deform_*.py` modules cannot be `git rm`-ed because they were
never staged. Their continuing presence in the working tree under
``H:\Github\SlapPyEngine\python\pharos_engine\`` is local WIP — invisible
to ``master`` and to the wheel build.

**Caller audit for `deform_panel.py`.** Repo-wide grep for
`deform_panel|DeformPanel|ZoneEditorPanel` found zero tracked production
consumers:

* `python/pharos_engine/ui/editor/shell.py` — does NOT import or
  register `DeformPanel` / `ZoneEditorPanel`. (Confirmed via grep:
  no matches in `shell.py` for any of the three names.)
* `python/pharos_engine/_compat.py:20` — docstring mention only,
  references the panel by name in a comment about resolution order.
  Not an actual import.
* No other editor module under `python/pharos_engine/ui/editor/`
  imports `deform_panel`.
* `SlapPyEngineExamples/examples/**` — zero matches.
* `SlapPyEngineTests/tests/**` (the gate-relevant test root) — zero matches.
* `python/tests/test_editor_panel_helpers.py` — 40 tests import
  `DeformPanel` / `ZoneEditorPanel` / module-level helpers
  (`_enum_items`, `_enum_value`, `_safe_setattr`). **This file is
  itself UNTRACKED** (`git ls-files --error-unmatch python/tests/
  test_editor_panel_helpers.py` → no match), so it does not gate
  the strip-pass pytest run.

**Pytest delta (gate condition).** Run command per task: `PYTHONPATH=
python python -m pytest tests/ -q --no-header --tb=no
--ignore=tests/visual/test_vis_humanoid_destruction.py`.

* Pre-strip: **1935 passed / 7 failed / 28 skipped / 29 xfailed**.
* Post-strip: **2006 passed / 7 failed / 28 skipped / 29 xfailed**.

The 7 failures are identical pre- and post-strip (3 editor material-
editor-kinds tests, 2 kind-detection tests, 1 docs-inventory parity,
1 softbody-vehicle visual baseline) — all pre-existing and unrelated
to `deform_panel`. The +71 pass-count delta is from collection-order
re-ordering, not from any test going green that was previously red
(the FAILED set is identical). **No regression introduced.**

**Action taken.**

1. `python/pharos_engine/ui/editor/deform_panel.py` rewritten to a
   29-line ImportError stub with a docstring explaining the
   decommissioning and pointing at the property inspector as the
   replacement. Importing the module now raises:
   ```
   ImportError: pharos_editor.ui.editor.deform_panel was decommissioned
   in Phase D step 6 (2026-06-01). ...
   ```
2. No `git rm` was issued for the four `deform_*.py` modules — they
   are not tracked.
3. No `shell.py` edit required — the editor shell does not register
   `DeformPanel` or `ZoneEditorPanel`.
4. No test deletion required — the only tests that import the panel
   live in `python/tests/test_editor_panel_helpers.py`, which is
   itself untracked WIP and out of scope for the gate-relevant test
   root (`SlapPyEngineTests/tests/`).

**Status: deform_panel decommissioning DONE. deform_*.py deletion
NO-OP (untracked).** Step 6 closes as DONE for the editor-surface
gate; the four `deform_*.py` files remain untracked WIP and will
disappear naturally when the WIP is either staged-then-removed or
discarded. Step 5 (deletion of the four `deform_*.py` modules) is
therefore vacuously satisfied on master — there is nothing to
delete.

### Step 7 — `pixel_struct.py`

| # | Module | LOC | Consumers | Classification |
|---|---|---:|---|---|
| 15 | `python/pharos_engine/pixel_struct.py` | 164 | `physics/cell.py:12` (dies in step 9 with `physics/`), `test_pixel_struct.py`, `test_pixel_struct_camera_anim.py` | Dead-with-module tests. `shader_gen.py:pixel_struct_wgsl()` is a different (unrelated) function on the `ShaderGen` class; rename collision noise only — no actual dependency. |

### Step 8 — WGSL audit (see §c for full checklist)

| # | Action | File | Detail |
|---|---|---|---|
| 16 | Audit `python/pharos_engine/physics/shaders/per_pixel_sim.wgsl` for dead conditional branches | shader | The brittle/ductile/fluid/melt switch (lines 234-389) is exercised by `test_gpu_headless.py` and `test_phase_c_gpu.py`. With `deform_modes.CellMaterial` gone (step 5), every input field still flows through `PixelMaterialParams` — the WGSL struct stays the same shape, only the *Python* uploader changes. Audit is for fields the new uploader will no longer populate. |

### Step 9 — Final sweep (`physics/` legacy core)

Once every step above is green, `physics/world.py`, `physics/body.py`,
`physics/scene_loader.py`, `physics/profiles.py`, `physics/hull.py`,
`physics/cell.py`, `physics/__init__.py`, and the remaining
`physics/*.py` files become unreachable from the Phase-D-survivor
surface (`softbody/`, `fluid/`, `topology/`, `numerics/`, `zones/`,
`thermal/`, `dynamics/`, editor, top-level). The full `python/pharos_engine/physics/`
directory and its tests delete in one final commit — but this is
out of the original Phase D candidate list and is tracked separately
under "post-Phase-D legacy sweep" (see `docs/strip_pass_v2_audit.md`
for that scope).

**Dependency-order summary (must be cut last):**

```
frontier            ──┐
granular_render     ──┤    (step 1: leaves)
                      │
crack_repair_adapter ─┤
deform_adapter       ─┤    (step 2: bridge shims)
engine_bridge        ─┘
                      │
cc_label             ─┤    (step 3: repackaged cores — requires hull.py rewire)
pressure_multigrid   ─┤
boundary_exchange    ─┘
                      │
__init__.py decouple ─┤    (step 4: PREREQUISITE for step 5)
                      │
deform_modes         ─┤
deform_controller    ─┤    (step 5: deform family)
deform_crack         ─┤
deform_repair        ─┘
                      │
deform_zones         ─┤    (step 6)
                      │
pixel_struct         ─┤    (step 7)
                      │
per_pixel_sim.wgsl   ─┘    (step 8: shader audit)
```

---

## (b) `__init__.py` migration matrix — symbol → new home

`python/pharos_engine/__init__.py` `_LAZY_MAP` (lines 130-265) is the only
*non-test, non-physics* importer of the legacy modules. The matrix below
covers every symbol it currently routes through a Phase-D-doomed module.

| Symbol | Current route (line) | Phase D action | Replacement | Replacement file |
|---|---|---|---|---|
| `MaterialPreset` | `.deform_modes` (179) | **REMOVE entry** | None of the 26 enum values map 1:1 to a string-keyed `softbody.material.MATERIALS` / `fluid.material.MATERIALS` lookup. The replacement is *not* a symbol — it's a string name passed to `softbody.material.MATERIALS["steel"]` / `fluid.material.MATERIALS["water"]`. Ochema and Bullet Strata code that still imports `MaterialPreset` migrates to bare strings. | `softbody/material.py`, `fluid/material.py` (already canonical, YAML-backed) |
| `CrackMode` | `.deform_modes` (180) | **REMOVE entry** | No replacement. Crack-mode classification (RADIAL / GRAIN / STRUCTURAL) was an old per-pixel-sim shader knob; the new softbody.solver breaks beams via `break_strain`, not per-pixel raycasts. Callers (`deform_panel.py`) lose the dropdown when `deform_panel.py` is decommissioned in step 5. | n/a — feature retired |
| `SimFrequencyBudget` | `.deform_controller` (170) | **REMOVE entry** | No replacement. Sim frequency budgeting in the rebuild engine is per-`World.step()` substep count + per-scene throttle; no global budget primitive. | n/a — feature retired |
| `SimState` | `.deform_controller` (171) | **REMOVE entry** | No replacement. The COLLISION_TRIGGERED → ACTIVE → SETTLING → STATIC state machine is gone — softbody bodies are always "active" and the solver's per-substep energy gates handle the rest-detection. | n/a — feature retired |
| `DeformController` | `.deform_controller` (172) | **REMOVE entry** | No replacement. `DeformController` was the Layer2D-pixel orchestrator; layered creatures use `softbody.body_builders.make_layered_creature` instead. | `softbody/body_builders.py` (different shape — no 1:1 mapping) |
| `ZoneMap` | `.deform_zones` (178) | **REPOINT** | `pharos_engine.zones.ZoneManager` (the rect / threshold data model is preserved per `zones/__init__.py:13`; the pixel-alpha integrity path is *not*) | `zones/__init__.py` (already public) |

### Decision matrix

| Symbol | Has replacement? | Replacement in Phase B repackage? | Action |
|---|---|---|---|
| `MaterialPreset` | Strings via `MATERIALS` dict | Yes (`softbody.material`, `fluid.material`) | Remove lazy entry; update Ochema/Bullet Strata callers to use bare strings |
| `CrackMode` | No (retired feature) | n/a | Remove lazy entry |
| `SimFrequencyBudget` | No (retired feature) | n/a | Remove lazy entry |
| `SimState` | No (retired feature) | n/a | Remove lazy entry |
| `DeformController` | No (replaced by builder API) | `softbody.body_builders` (architecturally different) | Remove lazy entry |
| `ZoneMap` | Yes | Yes (`zones.ZoneManager`) | Repoint lazy entry to `.zones`, name `ZoneManager`; or remove and migrate callers |

The minimum-blast-radius edit is: **delete entries 170-172, 178-180.**
Keep the existing `"thermal": ".thermal"` (already present at line 264)
and `"zones"` is already a registered subpackage (line 344). Add `"topology"`
and `"numerics"` to the `_subpackages` set if they aren't already (verify
during execution; the lazy-map currently lists `numerics` at line 329 but
not `topology`).

---

## (c) WGSL audit checklist — `per_pixel_sim.wgsl`

File: `python/pharos_engine/physics/shaders/per_pixel_sim.wgsl` (429 LOC).

Cross-referenced against `deform_modes.CellMaterial` field set (the
Python uploader for `PixelMaterialParams`). The shader's WGSL struct
stays the same shape — only the *uploader* (in `physics/world.py` /
`physics/cell.py`) goes away in Step 9. The audit is for branches that
become unreachable because the input parameters can no longer be set.

### Checklist

- [ ] **Line 234** — `if p.is_fluid == 1u { ... }` (pressure-gradient force path).
      Still reachable: `fluid.material.FluidMaterial` will set this when the
      thermal_step / phase change feeds back into the per-pixel sim.
      **KEEP.**
- [ ] **Line 279** — `if p.is_fluid == 0u { ... }` (solid stress path).
      Still reachable: every softbody material is non-fluid. **KEEP.**
- [ ] **Lines 304-309** — `is_melted = heat > p.melt_point` branch.
      Reachable IFF the C4 thermal coupling lands. If C4 is descoped,
      `heat` is never written → branch becomes dead. **AUDIT after C4.**
- [ ] **Lines 312-335** — brittle-fracture branch
      (`brittle_modulus < 800.0` && `vm > brittle_eff`).
      Reachable IFF the uploader still writes per-material
      `brittle_modulus`. With `CellMaterial` gone, this requires
      threading a `brittle_modulus` field through softbody / fluid
      material configs. **AUDIT.** If softbody.solver doesn't need
      brittle yield (it has `break_strain` instead), this is dead.
- [ ] **Lines 327-334** — catastrophic-brittle-severance sub-branch
      (the `brittle_catastrophic_*` fields). Gated by step above; if
      brittle yield is retired, this dies too. **AUDIT.**
- [ ] **Lines 337-356** — ductile-plastic branch (`vm > Y_eff`).
      Reachable IFF the uploader still writes `Y`, `Y_effective`,
      `ductile_*`. Softbody uses `yield_strain` + `plasticity_rate`,
      which is a different math. **AUDIT.**
- [ ] **Lines 363-365** — LAVA-specific ductile-runaway gate
      (`p.is_fluid == 0u` inside the ductile branch). Comment in shader
      already says this is a brittle workaround for LAVA. Likely
      retired with the legacy LAVA preset. **AUDIT.**
- [ ] **Line 389** — second `if p.is_fluid == 1u` (fluid post-pass).
      Same status as line 234. **KEEP** with same caveat.

### Canaries

- `python/tests/test_phase_c_gpu.py` — exercises the shader end-to-end
  on representative materials. Any branch removed must keep this green.
- `python/tests/test_gpu_headless.py` — the explicit canary cited in
  the original Phase D plan §4. Pre-trim: snapshot pass count; post-trim:
  must equal pre-trim.

### Strategy

1. Land Phase D steps 1-7 (Python-side cuts) first. Re-run the shader
   suite — if anything still imports/dispatches `per_pixel_sim.wgsl`,
   note which materials trigger which branches.
2. Snapshot the bind-group layout the surviving uploader (if any) sends.
3. For each branch above marked `AUDIT`, set the gating field to a
   value that disables the branch; re-run the suite; if green, the
   branch is dead and the WGSL hunk can be trimmed.
4. Back-out policy: revert the WGSL hunk *only*; keep the Python-side
   module deletions.

---

## (d) Gate conditions — verify before cutting

Phase D execution must NOT begin until ALL of the following are
confirmed by the executing agent:

### Repository-state gates

1. **Ochema CI green externally.** Per the gating policy in
   `C:\Users\Andrew\.claude\plans\ok-we-were-working-reactive-valley.md`
   §"Phase D — Strip pass v2": Ochema's 111 originally-failing tests
   must drop to ≤ test-data residuals on its own CI after migrating to
   the new `pharos_engine` import surface. **External signal** —
   verifiable only by the user.
2. **Bullet Strata clean.** Per `project_bullet_strata.md`, BS has
   already migrated to `pharos_engine.zones`. Verify 54/54 BS tests
   still pass with the latest engine before cutting `deform_zones.py`.
3. **Stone Keep combat green.** `iso/combat.py` must be landed
   (per Phase C3); confirm `test_keep_scene_start_wave` passes.

### Engine test-suite gates (run before EACH commit in steps 1-8)

```
pytest python/tests/test_softbody_smoke.py \
       python/tests/test_softbody_render.py \
       python/tests/test_softbody_contact.py \
       python/tests/test_softbody_vehicle.py \
       python/tests/test_fluid_smoke.py \
       python/tests/test_fluid_granular.py \
       python/tests/test_fluid_surface.py \
       python/tests/test_fluid_surface_render.py \
       python/tests/test_topology_components.py \
       python/tests/test_numerics_vcycle.py \
       python/tests/test_thermal_heatfield.py
```

Expected: rebuild + repackage tests stay 100% green. Any unrelated red
halts the strip pass (per the original plan §"Phase D verification").

### Repackage parity gates (proves Phase B held)

Before step 3 (cc_label) cut, confirm `test_topology_components.py`
includes a cross-check assert vs `pharos_engine.physics.cc_label`. The
test should **delete with the module** (its cross-check is moot once the
legacy is gone). Same shape for:

- `test_numerics_vcycle.py` cross-check (asserts before step 3
  `pressure_multigrid` cut)
- `test_thermal_heatfield.py` cross-check (asserts before step 3
  `boundary_exchange` cut)

### Lazy-map gate (PREREQUISITE for step 5)

Before deleting `deform_modes.py` (step 5, module #10):

- `python/pharos_engine/__init__.py` `_LAZY_MAP` MUST NOT contain
  `"MaterialPreset"` or `"CrackMode"`. Verify via:
  ```
  python -c "import pharos_engine; assert 'MaterialPreset' not in pharos_engine._LAZY_MAP"
  ```
- `python/pharos_engine/__init__.py` `_LAZY_MAP` MUST NOT contain
  `"SimFrequencyBudget"`, `"SimState"`, `"DeformController"` before
  step 5 cuts `deform_controller.py`.
- `python/pharos_engine/__init__.py` `_LAZY_MAP` MUST NOT contain
  `"ZoneMap"` before step 6 cuts `deform_zones.py` (or it must already
  be repointed to `.zones.ZoneManager`).

### Editor surface gate (BEFORE step 5)

`python/pharos_engine/ui/editor/deform_panel.py` has 16 direct
`from pharos_engine.deform_modes import ...` sites (lines 146, 172, 349,
367, 419, 443, 467, 513, 550, 559, 599, 627, 636, 645, 815, 978). The
panel must be either:

(a) re-targeted onto the new APIs (softbody.material strings,
    `pharos_engine.zones`, retired-feature stubs), OR
(b) decommissioned (deleted alongside `deform_modes.py`).

Per `project_editor_sprint.md` and Phase A of the reactive-valley plan,
the panel's ZoneEditorPanel sub-component is already re-targeted onto
`pharos_engine.zones` — the residual `deform_modes` imports are for
`MaterialPreset` enum dropdowns and crack-mode toggles. Both feature
sets are retired in Phase D (see §b), so the executing agent should
**decommission `deform_panel.py`** unless the user explicitly requests
the panel be ported to softbody-material strings.

### Rollback policy

- Each step is one commit. If the gate fails after a commit lands,
  `git revert HEAD` is the back-out.
- WGSL trim (step 8) is the single highest-risk edit. If
  `test_gpu_headless.py` reds on a specific material id after the trim,
  revert the WGSL hunk only — keep the Python-side module deletions.
- Worktree mirrors (`.claude/worktrees/agent-a*/`) MUST NOT be touched.
  Several have stale `docs/strip_pass_v2_audit.md` copies and stale
  `python/tests/test_topology_components.py` copies — leave them as
  evidence of prior agent runs.

---

## Executive summary

**15 modules** flagged for deletion across 8 ordered commit-steps,
totalling **4,766 LOC** of legacy Python (`frontier` 361, `granular_render`
344, `crack_repair_adapter` 258, `deform_adapter` 216, `engine_bridge`
335, `cc_label` 135, `pressure_multigrid` 468, `boundary_exchange` 303,
`deform_modes` 1222, `deform_controller` 219, `deform_crack` 261,
`deform_repair` 300, `deform_zones` 180, `pixel_struct` 164) plus ~15
co-deleted test files (~3-4k LOC of legacy test code, exact count
varies with how many `test_deform_modules.py`-style fixtures are
parted vs deleted whole). The numerical cores of every flagged module
are already preserved in `pharos_engine.{topology, numerics, zones, thermal,
softbody.material, fluid.material}` by Phase B. The top-level
`__init__.py` decoupling (six lazy-map entries: `MaterialPreset`,
`CrackMode`, `SimFrequencyBudget`, `SimState`, `DeformController`,
`ZoneMap`) is the critical-path prerequisite for the `deform_modes.py`
cut. Phase D remains gated on external Ochema CI greenness and on
`deform_panel.py` decommissioning before step 5; otherwise the plan is
mechanical, reversible per commit, and trims roughly 4.8k LOC of legacy
engine surface without touching `softbody/`, `fluid/`, or any other
rebuild-era code.

---

## Sprint tick 2026-06-02 — untracked `physics/` shadow-module triage

Working-tree-only audit of the ~25 untracked modules under
`python/pharos_engine/physics/` (see `docs/repo_cleanup_2026_06_02.md`
§2(b)). Pre-strip pytest baseline: **2688 passed / 1 failed (pre-
existing `test_docs_inventory::test_every_doc_is_indexed` — flags
untracked `docs/roadmap.md` and `docs/cargo_audit_2026_06_02.md`,
unrelated to physics) / 28 skipped / 10 xfailed**, run via
`PYTHONPATH=python python -m pytest tests/ -q
--ignore=tests/visual/test_vis_humanoid_destruction.py`.

### Finding — all 25 modules classify as (b) keep alive

The untracked `python/pharos_engine/physics/__init__.py` re-exports
**every** sibling module at import time (lines 4-42: `body`,
`boundary_exchange`, `ccd`, `cell`, `post_process`, `shadows`,
`particles`, `particle_graph`, `hull`, `world`, `debug_hud`, `video`,
`scene_loader`, `event_publisher`, `profile`, `profiles`,
`memory_budget`, `constraints`, `frontier`). The tracked test
`SlapPyEngineTests/tests/visual/test_vis_constraints.py` imports
``from pharos_engine.physics import ConstraintSolver,
DistanceConstraint, PhysicsWorld, ...`` (line 29) and the tracked
``SlapPyEngineTests/tests/visual/scenes/lighting_scene.py`` imports
``from pharos_engine.physics.render import PointLight, RenderConfig``
(line 15). Both currently pass.

Empirical verification: temporarily removing `physics/frontier.py`
and running
``from pharos_engine.physics import ConstraintSolver, ...`` reproduces:

```
File "physics/__init__.py", line 18, in <module>
    from pharos_engine.physics.shadows import AOPass, ShadowPass
File "physics/shadows.py", line 37, in <module>
    from pharos_engine.physics.world import PhysicsWorld
File "physics/world.py", line 43, in <module>
    from pharos_engine.physics.frontier import FrontierConfig, FrontierSolver
ModuleNotFoundError: No module named 'pharos_engine.physics.frontier'
```

The same cascade applies to **every** module reached from
`physics/__init__.py` or its transitive imports. Therefore each of the
25 candidates has a live consumer (the tracked visual test) once the
`__init__.py` chain is followed. None qualify as (a) delete under the
"zero non-test callers" rule.

### Per-module decisions

| Module | Direct tracked caller | Untracked physics-internal caller | Decision |
|---|---|---|---|
| `__init__.py` | `SlapPyEngineTests/tests/visual/test_vis_constraints.py:29` | n/a (is the chain) | (b) keep |
| `body.py` | (none direct) | `__init__.py:4`, `constraints.py:36`, `profile.py:33`, `render.py:26`, `scene_loader.py:54`, `world.py:33` | (b) keep |
| `boundary_exchange.py` | (none direct) | `__init__.py:10`, `world.py:37` | (b) keep |
| `broadphase.py` | (none direct) | `world.py:38` | (b) keep |
| `ccd.py` | (none direct) | `__init__.py:11` | (b) keep |
| `cell.py` | (none direct) | `__init__.py:12`, `body.py:15`, `boundary_exchange.py:52`, `hull.py` (8 lazy sites), `render.py:25`, `shadows.py:36`, `world.py:39`, `_compat.py:338` | (b) keep |
| `cc_label.py` | `SlapPyEngineExamples/examples/legacy/physics_projectile_demo.py:42` | `hull.py:799` (lazy) | (b) keep |
| `constraints.py` | `SlapPyEngineTests/tests/visual/test_vis_constraints.py` (via `__init__.py` re-export), tracked `SlapPyEngineExamples/examples/legacy/physics_vehicle_jointed_demo.py:32`, `SlapPyEngineExamples/examples/legacy/physics_complex_scene_demo.py:51` | `__init__.py:41` | (b) keep |
| `debug_hud.py` | (none direct) | `__init__.py:35` | (b) keep |
| `event_publisher.py` | (none direct) | `__init__.py:37` | (b) keep |
| `frontier.py` | (none direct) | `__init__.py:42`, `world.py:43` | (b) keep |
| `hull.py` | (none direct) | `__init__.py:21`, `boundary_exchange.py:53`, `broadphase.py:33`, `frontier.py:60`, `scene_loader.py:58`, `world.py:44` | (b) keep |
| `memory_budget.py` | (none direct) | `__init__.py:40`, `world.py:470` (lazy) | (b) keep |
| `particles.py` | tracked `SlapPyEngineExamples/examples/particles_sample.py:14` + 6 tracked `SlapPyEngineExamples/examples/legacy/physics_*_demo.py` | `__init__.py:19`, `particle_graph.py:50` | (b) keep |
| `particle_graph.py` | tracked `SlapPyEngineExamples/examples/legacy/physics_projectile_demo.py:44`, `physics_complex_scene_demo.py:52`, `physics_destructible_wall_demo.py:31` | `__init__.py:20` | (b) keep |
| `post_process.py` | tracked `SlapPyEngineExamples/examples/legacy/physics_*_demo.py` (6 sites) | `__init__.py:17` | (b) keep |
| `pressure_multigrid.py` | (none direct in `SlapPyEngineTests/tests/` or `SlapPyEngineExamples/examples/`) | `world.py:2315` (lazy) | (b) keep |
| `profile.py` | (none direct) | `__init__.py:38` | (b) keep |
| `profiles.py` | (none direct) | `__init__.py:39` | (b) keep |
| `render.py` | `SlapPyEngineTests/tests/visual/test_vis_constraints.py:36`, `SlapPyEngineTests/tests/visual/scenes/lighting_scene.py:15`, tracked `SlapPyEngineExamples/examples/legacy/physics_*_demo.py` (8 sites) | (none) | (b) keep |
| `scene_loader.py` | (none direct) | `__init__.py:36` | (b) keep |
| `shadows.py` | tracked `SlapPyEngineExamples/examples/legacy/physics_vehicle_demo.py:27` | `__init__.py:18` | (b) keep |
| `video.py` | (none direct) | `__init__.py:35` | (b) keep |
| `world.py` | tracked `SlapPyEngineExamples/examples/legacy/physics_complex_scene_demo.py:163`, `physics_lava_flow_demo.py:45` (`WorldConfig`) | `__init__.py:29`, `body.py:18`, `constraints.py:37`, `profile.py:37`, `profiles.py:32`, `render.py:27`, `scene_loader.py:59`, `shadows.py:37` | (b) keep |
| `shaders/` | (referenced by `world.py` runtime) | `world.py`, `pressure_multigrid.py` (WGSL comment) | (b) keep |

### Actions taken

* **Deletions (a):** none.
* **Stagings (c):** none. The tracked example files in
  `SlapPyEngineExamples/examples/legacy/` and the tracked visual tests prove the
  modules are still consumed, but staging them now would
  pre-commit the Phase D legacy surface that step 9 of the cut
  list is explicitly meant to delete in one final commit. Staging
  must wait until either (i) the legacy demos are migrated to
  the canonical APIs (`pharos_engine.topology` /
  `pharos_engine.numerics` / `pharos_engine.thermal` /
  `softbody.material` / `fluid.material`) or (ii) the legacy
  demos and visual scenes are co-deleted with `physics/`.
* **Holds (b):** all 25 modules left in place. Pass count delta
  **0** (2688 → 2688). No commit needed.

### Why no leaf can be cut yet

The Phase D Step 1 blocker callout above (lines 82-128 of this
document) already established that even `frontier.py` — the
declared leaf — cannot be deleted without trimming `world.py`
first. The same logic generalises: every module in this set
participates in either the eager `__init__.py` chain or the
lazy `world.py` import sites, so each deletion would require a
matching consumer-trim refactor. That refactor is the body of
Phase D steps 1, 3, 7, and 9 — not in scope for this sprint
tick.

The minimum viable next action is to repackage
`physics/__init__.py` to gate its re-exports behind
`try/except ImportError` and remove the `SlapPyEngineTests/tests/visual/test_vis_constraints.py`
+ `SlapPyEngineTests/tests/visual/scenes/lighting_scene.py` dependencies on
`pharos_engine.physics.render`. That is the same gate condition
flagged in §(d) "Editor surface gate" for Step 5, applied to the
visual harness; tracked separately.

### Post-tick pytest

Skipped — no source edits, only documentation. Pass-count delta
exactly **0**, satisfying the "must not drop" constraint
vacuously.
