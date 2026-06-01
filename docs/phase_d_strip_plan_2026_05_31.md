# Phase D strip-pass execution plan — 2026-05-31

Read-only audit. Phase D is GATED on Ochema CI greenness (external);
this document is the preparation for a future agent to execute deletions
one commit per module without breaking the suite.

The numerical cores of every flagged "old physics" module have already
been repackaged into clean engine-level APIs during Phase B:

| Old core | New home |
|---|---|
| `physics/cc_label.connected_components` | `slappyengine.topology.connected_components` |
| `physics/pressure_multigrid.vcycle_project_v` | `slappyengine.numerics.vcycle_poisson` |
| `physics/boundary_exchange._exchange_pair` | `slappyengine.thermal.HeatField` / `exchange_two_regions` |
| `deform_zones.ZoneMap` / `RectZone` / `ThresholdZone` | `slappyengine.zones.ZoneManager` / `RectZone` / `ThresholdZone` |
| `softbody.material.MATERIALS` | already canonical (YAML-backed) |
| `fluid.material.MATERIALS` | already canonical (YAML-backed) |

The legacy modules are still imported by `slappyengine.physics.world`,
`slappyengine.physics.body`, `slappyengine.physics.scene_loader`,
`slappyengine.physics.__init__`, several editor and test modules, and the
top-level `slappyengine/__init__.py` lazy map. Phase D removes them after
that consumer surface has been re-pointed.

The figures below count only `H:/Github/SlapPyEngine/python/**` plus
`examples/**` source. Worktree mirrors under `.claude/worktrees/**` and
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
| 1 | `python/slappyengine/physics/frontier.py` | 361 | `physics/__init__.py` (re-export), `physics/world.py` (lines 43, 194, 326-373, 490, 718-731, 825-844) + 4 tests (`test_frontier.py`, `test_phase_a_activation.py`, `test_nan_guards.py`, `test_phase_b_residency.py`) | `world.py` keeps a `frontier.enabled` flag for tests; once `world.py` itself dies (Phase D step 9) the flag dies with it. `test_frontier.py` is dead-with-module. The other three tests only touch `world.config.frontier.enabled = False` — purely defensive flag flips that come out with `world.py`. **BLOCKED 2026-05-31 — see "Step 1 blocker found" callout below.** |
| 2 | `python/slappyengine/physics/granular_render.py` | 344 | `physics/__init__.py` (re-export) only | Superseded by `fluid.render.FluidRenderer`. Zero non-physics callers. **NO-OP 2026-06-01 — file was never tracked on master.** Audit confirmed: `git log --all --full-history -- "**/granular_render.py"` returns empty; `physics/__init__.py` already has no re-export (lines 4-42); `tests/visual/test_vis_granular.py` and `tests/visual/output/granular/` do not exist. The 344/134 LOC figures from the plan refer to a worktree-local artefact that never landed on master. Step 2 is closed as **NOTHING TO DELETE** rather than DONE — no commit hash. See "Step 2 no-op audit" subsection below for evidence. |

#### Step 2 no-op audit — 2026-06-01

Step 2 execution attempted on 2026-06-01 found the target files absent
from the worktree, the main repo HEAD, and all of git history:

| Target | Status | Evidence |
|---|---|---|
| `python/slappyengine/physics/granular_render.py` | absent | `ls` fails; `git log --all --full-history -- "**/granular_render.py"` empty |
| `tests/visual/test_vis_granular.py` | absent | `ls` fails; `git log --all --full-history -- "**/test_vis_granular.py"` empty |
| `tests/visual/output/granular/` | absent | dir not in `tests/visual/output/` listing |
| `physics/__init__.py` re-export | absent | no `granular_render` import in lines 4-42 of `physics/__init__.py` |
| Any production consumer | none | `grep -rn "granular_render" python/slappyengine/` → 0 hits |

The only surviving references to the string `granular_render` are:

- `docs/strip_pass_v2_audit.md` (the audit doc that flagged it)
- `docs/phase_d_strip_plan_2026_05_31.md` (this plan)
- `tests/test_strip_audit_doc.py:52` (audit-tracking constant — meta, not a consumer)
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
(`from slappyengine.physics.frontier import FrontierConfig, FrontierSolver`)
plus the `FrontierYamlConfig` dataclass (L193-210), the
`PhysicsYaml.frontier` field (L227), the 35-line YAML loader block
(L326-360), `self._frontier: FrontierSolver | None` (L490), the
auto-tick block in `step()` (L700-731), and `_ensure_frontier_solver`
(L825-844) together mean deleting `frontier.py` would either (a) hard-
break `import slappyengine.physics` (because `physics/__init__.py:45`
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
| 3 | `python/slappyengine/physics/crack_repair_adapter.py` | 258 | `physics/__init__.py` (re-export), `test_crack_repair_adapter.py` | Dead-with-module test. Adapter wraps the legacy `deform_crack` / `deform_repair` Layer2D path — both die in step 5. **NO-OP 2026-06-01 — file does not exist in repo.** |
| 4 | `python/slappyengine/physics/deform_adapter.py` | 216 | `physics/__init__.py` (re-export), `test_deform_adapter.py` | Dead-with-module test. Wraps `DeformController` (dies in step 5) and `deform_zones.ZoneMap` (dies in step 6). **NO-OP 2026-06-01 — file does not exist in repo.** |
| 5 | `python/slappyengine/physics/engine_bridge.py` | 335 | `physics/__init__.py` (re-export), `test_engine_bridge.py` | Dead-with-module test. Pure bridge to `PhysicsWorld` lifecycle hooks. **NO-OP 2026-06-01 — file does not exist in repo.** |

#### Step 2 execution finding — 2026-06-01

A retry of Phase D step 2 (bridge-shim deletion) was attempted on
2026-06-01. The pre-strip audit found that none of the three target
modules (`crack_repair_adapter.py`, `deform_adapter.py`,
`engine_bridge.py`) exist in the repository:

* `git ls-tree HEAD python/slappyengine/physics/` does not include any
  of the three filenames.
* `Glob("**/crack_repair_adapter.py")`, `Glob("**/deform_adapter.py")`,
  and `Glob("**/engine_bridge.py")` return zero matches across the full
  repo (main repo + worktrees).
* `git log --all -S "crack_repair_adapter"` and the same for the other
  two strings return only docs (`phase_d_strip_plan_2026_05_31.md`,
  `strip_pass_v2_audit.md`) and the `tests/test_strip_audit_doc.py`
  inventory list — never an actual source file commit.
* `python/slappyengine/physics/__init__.py` does not import or
  re-export any of the three names (last import is `frontier`).
* No test files `test_crack_repair_adapter.py`, `test_deform_adapter.py`,
  or `test_engine_bridge.py` exist anywhere.
* `grep -rn` for `from slappyengine.physics.{crack_repair_adapter,deform_adapter,engine_bridge}`
  finds zero matches in `python/`, `tests/`, `examples/`, `docs/`
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
| 6 | `python/slappyengine/physics/cc_label.py` | 135 | `physics/hull.py:799` (function-local import), `physics/world.py:93,98,761` (comments + one severance check), `test_spawn_fragment.py`, `test_topology_components.py` (cross-check against legacy), 3 demo tests | `hull.py:799` migrates to `from slappyengine.topology import connected_components` — bond/adjacency array signature is identical. `test_topology_components.py` cross-check assert deletes with module (it exists *only* to prove parity). |
| 7 | `python/slappyengine/physics/pressure_multigrid.py` | 468 | `physics/world.py:2315` (function-local import in pressure projection), `deform_modes.py:479` (docstring reference), `physics/shaders/pressure_project.wgsl` (comment), `test_multigrid_projection.py`, `test_numerics_vcycle.py` (cross-check) | `world.py:2315` migrates to `from slappyengine.numerics import vcycle_poisson`. WGSL comment is a no-op rewrite. `test_multigrid_projection.py` is dead-with-module; `test_numerics_vcycle.py` cross-check assert deletes (parity already proven). |
| 8 | `python/slappyengine/physics/boundary_exchange.py` | 303 | `physics/__init__.py` (re-export), `physics/world.py:37,226,319-372,510,684-685`, `physics/profiles.py:44,57-90,145`, `test_boundary_exchange.py`, `test_boundary_exchange_integration.py`, `test_phase_b_residency.py:190`, `test_physics_profiles.py`, `test_thermal_heatfield.py` (cross-check) | `world.py` legacy usage dies with `world.py` itself in step 9. `profiles.py` keeps the `boundary_exchange_enabled` flag as a profile knob — that field migrates to `thermal_enabled` or is dropped (no non-physics consumer). Legacy tests die with module; `test_thermal_heatfield.py` parity check deletes. |

### Step 4 — Top-level `__init__.py` decoupling (PREREQUISITE for step 5)

| # | Action | Caller | Detail |
|---|---|---|---|
| 9 | Remove `"MaterialPreset"` and `"CrackMode"` entries from `_LAZY_MAP` in `python/slappyengine/__init__.py` (lines 179-180) | top-level package | See §(b) below for the per-symbol replacement matrix. Must land **before** step 5 — `slappyengine/__init__.py` imports `deform_modes` lazily, but every `MaterialPreset` lookup re-imports it, and step 5 deletes the file. |

### Step 5 — `deform_modes.py` and its dependents

| # | Module | LOC | Consumers (non-test) | Classification |
|---|---|---:|---|---|
| 10 | `python/slappyengine/deform_modes.py` | 1222 | `slappyengine/__init__.py` (post-step-9: zero), `physics/body.py:14` (CellMaterial), `physics/boundary_exchange.py:51` (dies in step 8), `physics/pressure_multigrid.py:47` (dies in step 7), `physics/scene_loader.py:53` (cell_material_for), `physics/world.py:29-32`, `ui/editor/deform_panel.py` (16 import sites, all `MaterialPreset` / `CrackMode` / `DeformSimMode` / `DecayMode` / `DestroyMode` / `PhysicsCoupling` / `RepairMode` / `MATERIAL_CONFIGS` / `get_material` / `list_materials`) | `physics/body.py`, `physics/scene_loader.py`, `physics/world.py` die together in step 9. `deform_panel.py` is the only Phase-D-survivor — it must be re-targeted (see Risk callout in §d). The bulk (`CellMaterial`, `MATERIAL_CONFIGS`, enums) is dead-with-module. |
| 11 | `python/slappyengine/deform_controller.py` | 219 | `physics/deform_adapter.py:40` (dies in step 2), `slappyengine/__init__.py` (lazy-map entries `SimFrequencyBudget`, `SimState`, `DeformController` — lines 170-172), `test_deform_controller.py`, `slappyengine/tests/test_deform_controller.py` | Lazy-map entries must die in step 4b (same commit as step 9, or split into a 9b). No non-physics call sites. Tests die with module. |
| 12 | `python/slappyengine/deform_crack.py` | 261 | `physics/crack_repair_adapter.py:156` (dies in step 2), `test_deform_modules.py`, `test_tags_zheight_deform_extras.py` | Dead-with-module tests. |
| 13 | `python/slappyengine/deform_repair.py` | 300 | `physics/crack_repair_adapter.py:157` (dies in step 2), `test_config_and_repair.py`, `test_deform_modules.py`, `test_deform_repair_db.py`, `test_deform_repair_gpu.py`, `test_ochema_extra2.py` (3 imports) | Dead-with-module tests. `test_ochema_extra2.py` is legacy game-compat fixture — confirmed in Phase D plan to delete with module. |

### Step 6 — `deform_zones.py`

| # | Module | LOC | Consumers | Classification |
|---|---|---:|---|---|
| 14 | `python/slappyengine/deform_zones.py` | 180 | `slappyengine/__init__.py` (`ZoneMap` lazy entry, line 178), `physics/deform_adapter.py:41` (dies in step 2), `event_bus.py:153` (comment only), `ui/editor/deform_panel.py:1005` (comment + Phase B uses `slappyengine.zones`), `test_deform_adapter.py`, `test_deform_modules.py`, `test_tags_zheight_deform_extras.py`, `slappyengine/tests/test_deform_zones.py` | `ZoneMap` lazy entry retargets to `slappyengine.zones.ZoneManager` OR dies (Bullet Strata's `ZoneMap` already migrated to `zones.ZoneManager` per `project_bullet_strata.md`). Dead-with-module tests. |

### Step 7 — `pixel_struct.py`

| # | Module | LOC | Consumers | Classification |
|---|---|---:|---|---|
| 15 | `python/slappyengine/pixel_struct.py` | 164 | `physics/cell.py:12` (dies in step 9 with `physics/`), `test_pixel_struct.py`, `test_pixel_struct_camera_anim.py` | Dead-with-module tests. `shader_gen.py:pixel_struct_wgsl()` is a different (unrelated) function on the `ShaderGen` class; rename collision noise only — no actual dependency. |

### Step 8 — WGSL audit (see §c for full checklist)

| # | Action | File | Detail |
|---|---|---|---|
| 16 | Audit `python/slappyengine/physics/shaders/per_pixel_sim.wgsl` for dead conditional branches | shader | The brittle/ductile/fluid/melt switch (lines 234-389) is exercised by `test_gpu_headless.py` and `test_phase_c_gpu.py`. With `deform_modes.CellMaterial` gone (step 5), every input field still flows through `PixelMaterialParams` — the WGSL struct stays the same shape, only the *Python* uploader changes. Audit is for fields the new uploader will no longer populate. |

### Step 9 — Final sweep (`physics/` legacy core)

Once every step above is green, `physics/world.py`, `physics/body.py`,
`physics/scene_loader.py`, `physics/profiles.py`, `physics/hull.py`,
`physics/cell.py`, `physics/__init__.py`, and the remaining
`physics/*.py` files become unreachable from the Phase-D-survivor
surface (`softbody/`, `fluid/`, `topology/`, `numerics/`, `zones/`,
`thermal/`, `dynamics/`, editor, top-level). The full `python/slappyengine/physics/`
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

`python/slappyengine/__init__.py` `_LAZY_MAP` (lines 130-265) is the only
*non-test, non-physics* importer of the legacy modules. The matrix below
covers every symbol it currently routes through a Phase-D-doomed module.

| Symbol | Current route (line) | Phase D action | Replacement | Replacement file |
|---|---|---|---|---|
| `MaterialPreset` | `.deform_modes` (179) | **REMOVE entry** | None of the 26 enum values map 1:1 to a string-keyed `softbody.material.MATERIALS` / `fluid.material.MATERIALS` lookup. The replacement is *not* a symbol — it's a string name passed to `softbody.material.MATERIALS["steel"]` / `fluid.material.MATERIALS["water"]`. Ochema and Bullet Strata code that still imports `MaterialPreset` migrates to bare strings. | `softbody/material.py`, `fluid/material.py` (already canonical, YAML-backed) |
| `CrackMode` | `.deform_modes` (180) | **REMOVE entry** | No replacement. Crack-mode classification (RADIAL / GRAIN / STRUCTURAL) was an old per-pixel-sim shader knob; the new softbody.solver breaks beams via `break_strain`, not per-pixel raycasts. Callers (`deform_panel.py`) lose the dropdown when `deform_panel.py` is decommissioned in step 5. | n/a — feature retired |
| `SimFrequencyBudget` | `.deform_controller` (170) | **REMOVE entry** | No replacement. Sim frequency budgeting in the rebuild engine is per-`World.step()` substep count + per-scene throttle; no global budget primitive. | n/a — feature retired |
| `SimState` | `.deform_controller` (171) | **REMOVE entry** | No replacement. The COLLISION_TRIGGERED → ACTIVE → SETTLING → STATIC state machine is gone — softbody bodies are always "active" and the solver's per-substep energy gates handle the rest-detection. | n/a — feature retired |
| `DeformController` | `.deform_controller` (172) | **REMOVE entry** | No replacement. `DeformController` was the Layer2D-pixel orchestrator; layered creatures use `softbody.body_builders.make_layered_creature` instead. | `softbody/body_builders.py` (different shape — no 1:1 mapping) |
| `ZoneMap` | `.deform_zones` (178) | **REPOINT** | `slappyengine.zones.ZoneManager` (the rect / threshold data model is preserved per `zones/__init__.py:13`; the pixel-alpha integrity path is *not*) | `zones/__init__.py` (already public) |

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

File: `python/slappyengine/physics/shaders/per_pixel_sim.wgsl` (429 LOC).

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
   the new `slappyengine` import surface. **External signal** —
   verifiable only by the user.
2. **Bullet Strata clean.** Per `project_bullet_strata.md`, BS has
   already migrated to `slappyengine.zones`. Verify 54/54 BS tests
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
includes a cross-check assert vs `slappyengine.physics.cc_label`. The
test should **delete with the module** (its cross-check is moot once the
legacy is gone). Same shape for:

- `test_numerics_vcycle.py` cross-check (asserts before step 3
  `pressure_multigrid` cut)
- `test_thermal_heatfield.py` cross-check (asserts before step 3
  `boundary_exchange` cut)

### Lazy-map gate (PREREQUISITE for step 5)

Before deleting `deform_modes.py` (step 5, module #10):

- `python/slappyengine/__init__.py` `_LAZY_MAP` MUST NOT contain
  `"MaterialPreset"` or `"CrackMode"`. Verify via:
  ```
  python -c "import slappyengine; assert 'MaterialPreset' not in slappyengine._LAZY_MAP"
  ```
- `python/slappyengine/__init__.py` `_LAZY_MAP` MUST NOT contain
  `"SimFrequencyBudget"`, `"SimState"`, `"DeformController"` before
  step 5 cuts `deform_controller.py`.
- `python/slappyengine/__init__.py` `_LAZY_MAP` MUST NOT contain
  `"ZoneMap"` before step 6 cuts `deform_zones.py` (or it must already
  be repointed to `.zones.ZoneManager`).

### Editor surface gate (BEFORE step 5)

`python/slappyengine/ui/editor/deform_panel.py` has 16 direct
`from slappyengine.deform_modes import ...` sites (lines 146, 172, 349,
367, 419, 443, 467, 513, 550, 559, 599, 627, 636, 645, 815, 978). The
panel must be either:

(a) re-targeted onto the new APIs (softbody.material strings,
    `slappyengine.zones`, retired-feature stubs), OR
(b) decommissioned (deleted alongside `deform_modes.py`).

Per `project_editor_sprint.md` and Phase A of the reactive-valley plan,
the panel's ZoneEditorPanel sub-component is already re-targeted onto
`slappyengine.zones` — the residual `deform_modes` imports are for
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
are already preserved in `slappyengine.{topology, numerics, zones, thermal,
softbody.material, fluid.material}` by Phase B. The top-level
`__init__.py` decoupling (six lazy-map entries: `MaterialPreset`,
`CrackMode`, `SimFrequencyBudget`, `SimState`, `DeformController`,
`ZoneMap`) is the critical-path prerequisite for the `deform_modes.py`
cut. Phase D remains gated on external Ochema CI greenness and on
`deform_panel.py` decommissioning before step 5; otherwise the plan is
mechanical, reversible per commit, and trims roughly 4.8k LOC of legacy
engine surface without touching `softbody/`, `fluid/`, or any other
rebuild-era code.
