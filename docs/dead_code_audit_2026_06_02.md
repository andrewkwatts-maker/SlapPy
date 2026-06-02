# Dead-Code & Duplicate-Symbol Audit — 2026-06-02

Sweep of the tracked SlapPyEngine codebase for dead exports, duplicate
symbols, and stale `xfail`s. Captures the deferred-removal candidates; the
safe fixes have already landed in the companion commit.

## Safe fixes landed in this sweep

1. **Duplicate `_LAZY_MAP["CacheMode"]` key removed.** `python/slappyengine/__init__.py`
   had `"CacheMode": ".residency.manager"` mapped at both line 246
   (under `# input + collision`) and line 286 (under `# residency`). Both
   pointed to the same module; the second binding silently won. Kept the
   first (semantic group is correct for Ochema Circuit's race scene
   chain-import order), removed the duplicate, left a one-line comment
   pointer.
2. **`SlapPyEngineTests/tests/test_game_compat_tripwire.py::_KNOWN_BROKEN` zeroed.** All 18
   entries (Ochema Circuit: `build_vehicle`, `VehicleSpec`, `WheelSpec`,
   `apply_drivetrain_torque`, `CatmullRomSpline`, `SplineTrack`,
   `PlayerInputProvider`, `PixelCollisionPass`, `MotionBlurPass`,
   `SimFrequencyBudget`, `SimState`, `DeformController`; Bullet Strata:
   `TriggerSystem`, `TriggerVolume`, `MaterialPreset`, `ZoneMap`,
   `CrackMode`, `PixelMaterialMap`, `DeformController`,
   `SimFrequencyBudget`) now resolve through `_LAZY_MAP`. Each was an
   `XFAIL` that should have been a real assertion. Flipped to hard asserts
   and dropped `_KNOWN_BROKEN_MAX` from 20 → 0. Net suite delta: 20
   xfailed → 20 passed.

Confirmed `pytest -rXp` finds zero `XPASS` post-flip; remaining 9
xfaileds (`test_all_demos_smoke[hello_rope|hello_ragdoll|...]`) still
genuinely fail under `--runxfail` (subprocess-rendered frames diverge
from in-process baselines — not flippable today).

## Task 1 — deprecated alias internal callers

Sprint R-D shipped `make_humanoid` / `wrap_in_flesh` as deprecated
aliases of `build_humanoid` / `build_flesh_wrap`. Internal callers still
exist; migration is **deferred** (would touch 4 examples + 4 tests in a
single sweep):

- `SlapPyEngineExamples/examples/humanoid_walking_demo.py`
- `SlapPyEngineExamples/examples/humanoid_standing_demo.py`
- `SlapPyEngineExamples/examples/humanoid_ik_terrain_demo.py`
- `SlapPyEngineExamples/examples/humanoid_destruction_demo.py`
- `SlapPyEngineTests/tests/visual/test_vis_humanoid_ik_terrain.py`
- `SlapPyEngineTests/tests/visual/test_vis_humanoid_destruction.py`
- `python/tests/test_humanoid_flesh_layers.py`
- `python/tests/test_toplevel_rebuild_surface.py`
- `SlapPyEngineTests/tests/test_editor_dynamics_spawn.py` (comment-only)

`SlapPyEngineTests/tests/test_dynamics_builder_conventions.py` deliberately calls the
deprecated names to assert the `DeprecationWarning` — keep as-is.

The IK terrain visual test currently emits a `DeprecationWarning` in
CI output. Suggested follow-up: migrate the four examples + two visual
tests + `test_humanoid_flesh_layers.py` in one commit, then verify the
warning disappears from CI.

## Task 3 — dead `__all__` exports (deferred — no removal yet)

Subpackage `__all__` entries with **zero** observed callers in
`python/`, `SlapPyEngineTests/tests/`, `SlapPyEngineExamples/examples/` (after excluding the subpackage's own
`__init__.py` *and* top-level `slappyengine` re-exports). These are
candidates only — downstream games (Ochema Circuit, Bullet Strata,
Stone Keep, periodica-app) may still import them, so removal must wait
for a compat-tripwire sweep against the game repos.

- `slappyengine.dynamics` — 38 candidates, mostly serialiser pairs
  (`*_to_dict` / `*_from_dict`, `world_to_dict`, etc.). These are the
  documented `save_world` / `load_world` surface — keep.
- `slappyengine.numerics` — `compute_residual`, `sor_smooth` (used
  internally by `vcycle_poisson`; promote to private or document).
- `slappyengine.topology` — `BACKGROUND_LABEL`,
  `connected_components_grid`.
- `slappyengine.material` — `KNOWN_NODE_TYPES`, `KNOWN_PORT_TYPES`,
  `validate_node_graph`.
- `slappyengine.post_process` — `ContactShadowsPass`, `GTAOPass`,
  `PostProcessExecutor`, `PostProcessPassBase`, `ShadowCSM`, `TAAPass`,
  `VolumetricFog`, `arcade_chain`, `cinematic_chain`,
  `iso_strategy_chain` (mostly preset chains and pass base classes —
  legit public surface).
- `slappyengine.compute` — 10 candidates (`AABB`, `AssetComputeAPI`,
  `ComputePass`, `ComputePipeline`, `PixelAPI`, `PixelMutator`,
  `ReadbackBuffer`, `SpatialCompute`, `StatsCompute`, `StatsResult`).
- `slappyengine.gi` — `RadianceCascadeSystem`, `ReSTIRSystem`,
  `SVGFDenoiser`.
- `slappyengine.iso` — `IsoCamera`, `IsoCell`, `IsoViewpoint`.
- `slappyengine.residency` — `SLAP_MAGIC`, `SLAP_VERSION`,
  `compress_array`, `compress_raw`, `decompress_array`,
  `decompress_raw`, `read_asset_from_slap`, `read_world_slap`,
  `write_asset_to_slap`, `write_world_slap` (the `.slap` format
  surface — public API by design).
- `slappyengine.testing` — `DIFF_DIR`, `render_scene_to_png`.
- `slappyengine.physics` — 12 candidates including `PhysicsBody`,
  `PhysicsYaml`, `TIER_T1`, `TIER_T2`, `CellGridPool`, etc.
- `slappyengine.gpu` — 14 candidates including `BufferManager`,
  `Cluster3DSystem`, `GPUContext`, `MeshPipeline`, `TextureManager`.

Triage: most of these are reasonable public surface (serialisers,
format constants, format read/write helpers, GPU pipeline classes). A
follow-up audit should cross-check against the three flagship game
repos (Ochema, Bullet Strata, Stone Keep) before any removal.

## Task 4 — duplicate top-level function definitions

Distinct implementations sharing a top-level name across modules:

- `validate_bool` — shared `slappyengine._validation` + intentional
  legacy-message twin in `slappyengine/assets/_validation.py`
  (docstring already explains the divergence; keep).
- `validate_layer_arg` — `_asset_validation.py` + `_layer_validation.py`.
- `validate_name` — `_asset_validation.py` +
  `material/_node_validation.py`.
- `validate_positive_int` — shared `_validation.py` +
  `material/_node_validation.py` twin.
- `validate_rgba_tuple` — `_strata_validation.py` +
  `tools/_sprite_audit_validation.py`.
- `cell_material_for` — `_compat.py` + `deform_modes.py` (both retired-
  feature stubs; `_compat.py` is the live one per Phase D §(b)).
- `connected_components` — `physics/cc_label.py` +
  `topology/__init__.py` (legacy + canonical; topology is the new home).
- `is_gpu_available` — `physics/particle_gpu.py` +
  `physics/particle_gpu_drill.py` (both legacy hierarchical-hull GPU
  drivers — out of scope for this sweep).
- `subscribe` / `unsubscribe` — `event_bus.py` (typed event bus) +
  `telemetry/__init__.py` (pattern bus). Different surfaces, same names
  intentional; documented in both module docstrings.

Recommended follow-up: consolidate the four `validate_*` twins into
`slappyengine._validation` (the `material/_node_validation.py` pair is
the easiest — same signatures, shared message format). Defer
`connected_components` migration until the physics legacy stack is
formally retired.

## Verification

Pre-sweep:  7 failed, 2567 passed, 28 skipped, 29 xfailed.
Post-sweep: 6 failed, 2661 passed, 28 skipped,  9 xfailed.

The 6 remaining fails (`test_editor_material_editor_kinds` x5 + the
softbody vehicle visual) pre-date this sweep and were already on the
ignore list. `test_residency::test_compress_raw_small` and
`test_perf_no_regression` flake intermittently under load but pass
solo; not regressions.
