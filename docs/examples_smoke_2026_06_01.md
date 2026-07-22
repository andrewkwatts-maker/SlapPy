# Examples Smoke Audit v2 — 2026-06-01

## What changed since 2026-05-31

The v1 audit at `docs/examples_smoke_2026_05_31.md` (commit `8bc56fd`) recorded
41/47 GREEN with 4 humanoid demos blocked at import time and 2 demos
(`hello_gi.py`, `ik_skeleton_demo.py`) failing at runtime. Since then,
Sprint 2A (`f0facb9`) restored `make_humanoid` / `wrap_in_flesh` /
`place_feet_on_terrain` in `pharos_engine.dynamics`, Sprint 2B (`4edb294`)
restored `SVGFDenoiser.reset_history`, Sprint 2C (`f0e9a40`) added
`Engine.run(max_frames=N)` so pure event-loop demos can now be driven end-to-end
in-process, Sprint 4G (`2f7028d`) polished `hello_ragdoll`, and Sprint 5G
(`66e7e61`) polished `humanoid_ik_terrain_demo`. The v2 run shows 5 of the
6 previously-broken demos now pass, but two pre-existing latent GPU
pipeline bugs (`hello_3d_layer.py`, `hello_bake.py`) that were masked by
v1's no-op `Engine.run` patch are now visible under the real
`max_frames=5` execution path, and `ik_skeleton_demo.py` regressed to a
different failure mode (now import-time instead of runtime). Net
delta: **43/47 GREEN end-to-end**, plus **1 v1-style apples-to-apples
GREEN** (`multiplayer_demo.py` under `--frames 5` exits 0 just as it did
in v1), giving an apples-to-apples count of **44/47** vs the v1 baseline
of 41/47.

## Methodology

For every `SlapPyEngineExamples/examples/*.py` outside `legacy/` and `output/`, the audit
script ran one of three probes with `PYTHONPATH=python` and a 90 s
`subprocess` timeout:

1. **`--frames 5`** for argparse demos that wire that flag.
2. **No-args** for argparse demos without `--frames`, and for scripts
   that simply execute on import (GIF writers, baked offline demos).
3. **`Engine.run(max_frames=5)` injection** via `runpy` for pure
   `engine.run()` event-loop demos. A monkey-patch wraps `Engine.run` so
   that when the demo calls `engine.run()` with no arguments, the
   harness substitutes `max_frames=5`, which Sprint 2C wired to drive
   the per-frame draw callback exactly 5 times and return without
   entering the platform event loop. This is a real end-to-end test —
   GPU pipelines are created and the draw closure is invoked — unlike
   v1's no-op patch which short-circuited the body of `run()` entirely.

Categories: **GREEN** / **RUNTIME_ERROR** / **IMPORT_MISSING_OTHER** /
**IMPORT_MISSING_SOFTBODY** / **IMPORT_MISSING_FLUID** / **TIMEOUT**.

## Results (47 examples)

| Example | Status | Notes |
|---|---|---|
| bullet_holes_demo.py | GREEN | No-args; writes `SlapPyEngineExamples/examples/output/particles/bullet_holes.gif`; total particles=113. |
| buoyancy_demo.py | GREEN | No-args; writes `SlapPyEngineExamples/examples/output/buoyancy/buoyancy.gif`; 2190 splash impulses. |
| character_damage_demo.py | GREEN | No-args; cumulative cuts bone=7 muscle=4 skin=2. |
| detonate_gallery_demo.py | GREEN | `--frames 5`; argparse demo. |
| editor_demo.py | GREEN | No-args; "No project found" notice is expected without a project on disk. |
| fluid_demo.py | GREEN | No-args; writes `water_basin.gif`; surface render mean=4.27 ms p95=5.11 ms. |
| fluid_sandbox.py | GREEN | `Engine.run(max_frames=5)` injected; canvas + scene built and 5 frames drawn cleanly. |
| fluid_surface_demo.py | GREEN | No-args; writes `surface_overlay_perf.txt`. |
| glass_fracture_demo.py | GREEN | No-args; 13 connected components after impact. |
| hello_3d_layer.py | RUNTIME_ERROR | NEWLY VISIBLE. `Engine.run(max_frames=5)` builds the real GPU mesh pipeline and trips `wgpu.GPUValidationError: Shader global ResourceBinding { group: 1, binding: 1 } is not available in the pipeline layout` at `gpu/mesh_pipeline.py:124`. v1 patched `Engine.run` to a no-op so the pipeline was never built. |
| hello_audio.py | GREEN | Argparse, no `--frames`; default run played stub clip. |
| hello_bake.py | RUNTIME_ERROR | NEWLY VISIBLE. Same `mesh_pipeline.py:124` shader-binding mismatch as `hello_3d_layer.py` — bake demo also instantiates the 3D mesh pipeline once the draw callback fires. v1 missed this for the same no-op-patch reason. |
| hello_composite.py | GREEN | `--frames 5`; zone.enter=0. |
| hello_dynamics_serialize.py | GREEN | `--frames 5`; roundtrip clean, no NaN. |
| hello_gi.py | GREEN | NEWLY GREEN. No-args; writes `hello_gi.png` (direct \| cascade+noise \| SVGF-denoised). Fixed by Sprint 2B `SVGFDenoiser.reset_history`. |
| hello_ik_chain.py | GREEN | `--frames 5`; max tip-to-target 0.0086. |
| hello_iso.py | GREEN | `--frames 5`; no non-finite state. |
| hello_joint.py | GREEN | `--frames 5`; no NaN. |
| hello_lighting.py | GREEN | `Engine.run(max_frames=5)` injected; lighting scene built, 5 frames drawn. |
| hello_motor.py | GREEN | `--frames 5`; stepped frames=5. |
| hello_numerics.py | GREEN | Argparse, no `--frames`; default run no-NaN. |
| hello_physics.py | GREEN | `Engine.run(max_frames=5)`; pixel-physics compute scene drew 5 frames. |
| hello_pixel.py | GREEN | `Engine.run(max_frames=5)`; canvas + layer drew 5 frames. |
| hello_ragdoll.py | GREEN | `--frames 5`; writes `SlapPyEngineExamples/examples/output/ragdoll/hello_ragdoll.gif` (Sprint 4G). |
| hello_rope.py | GREEN | `--frames 5`; stepped frames=5. |
| hello_spring.py | GREEN | `--frames 5`; final y=0.6498. |
| hello_telemetry.py | GREEN | `--frames 5`; emit bench 20937.60 ns/emit. |
| hello_thermal.py | GREEN | `--frames 5`; hot/cold poles settle. |
| hello_topology.py | GREEN | Argparse, no `--frames`; edges=112 components=1. |
| hello_world.py | GREEN | `Engine.run(max_frames=5)`; minimal window drew 5 frames. |
| hello_zone.py | GREEN | `--frames 5`; no NaN. |
| hud_demo.py | GREEN | `Engine.run(max_frames=5)`; HUD wiring + script attach OK. |
| humanoid_destruction_demo.py | GREEN | NEWLY GREEN. No-args; cumulative cuts bone(L0)=46 muscle(L1)=14 skin(L2)=14. Fixed by Sprint 2A `make_humanoid` + `wrap_in_flesh`. |
| humanoid_ik_terrain_demo.py | GREEN | NEWLY GREEN. `--frames 5`; writes `SlapPyEngineExamples/examples/output/humanoid/humanoid_ik_terrain.gif` (Sprint 5G polish). Fixed by Sprint 2A `place_feet_on_terrain`. |
| humanoid_standing_demo.py | GREEN | NEWLY GREEN. No-args; pose head y=1.840 pelvis y=2.550 ankle_l y=3.500. Fixed by Sprint 2A `make_humanoid` + `place_feet_on_terrain`. |
| humanoid_walking_demo.py | GREEN | NEWLY GREEN. No-args; writes `SlapPyEngineExamples/examples/output/humanoid/humanoid_walking.gif`. Fixed by Sprint 2A. |
| ik_skeleton_demo.py | IMPORT_MISSING_OTHER | STILL BROKEN, NEW FAILURE MODE. `ImportError: cannot import name 'make_distance' from 'pharos_engine.dynamics'` at `ik_skeleton_demo.py:23`. Also imports `resolve_joint_specs`, also absent. In v1 the demo got past import but died at runtime on `SoftBodyWorld.positions`; the public `pharos_engine.dynamics` surface has since been narrowed (current public names: `Body, BoneSpec, Humanoid, IKChainSpec, JointSpec, Material, MotorSpec, RagdollSpec, RopeSpec, SoftBodyWorld, SpringSpec, World, build_ragdoll, build_rope, make_humanoid, make_motor, make_spring, place_feet_on_terrain, resolve_joint, save_world, load_world, solve_ik, wrap_in_flesh, world_from_dict, world_to_dict`). Re-export `make_distance` and `resolve_joint_specs` to land this demo. |
| landscape_demo.py | GREEN | `Engine.run(max_frames=5)`; landscape streamer initialised. |
| layered_character.py | GREEN | `Engine.run(max_frames=5)`; warrior tick wired. |
| layered_creature_drop.py | GREEN | No-args; writes `creature_drop.gif`; centroid drift 1.173. |
| multiplayer_demo.py | GREEN(\*) | `--frames 5` (matching v1 invocation) — argparse-style flag is rejected by the demo's `host`/`join` switch and the script exits 0 with "Unknown mode: '--frames'". This is the same false-positive shape that v1 recorded; the demo cannot actually be smoke-tested without two cooperating processes and a UDP bind. With no args it picks `host` and fails at DHT bind on Windows with `WinError 10048` (port-in-use), which is an environment flake rather than a code regression. |
| particles_sample.py | GREEN | No-args; writes `SlapPyEngineExamples/examples/particles_sample.png`; 448 live particles. |
| sand_crater_demo.py | GREEN | `--frames 5`; argparse demo. |
| softbody_vehicle_demo.py | GREEN | No-args; writes `softbody/vehicle_demo.gif`; 0/263 beams broken. |
| vehicle_obstacle_course.py | GREEN | No-args; writes `softbody/vehicle_course.gif`; 0/907 beams broken. |
| visual_check_demo.py | GREEN | No-args; sand/rock/snow stratify correctly. |
| water_dam_break.py | GREEN | No-args; writes `dam_break.gif`; surface render mean=3.83 ms. |

\* `multiplayer_demo.py` is marked GREEN under the apples-to-apples
v1 invocation but is not a meaningful smoke test — see the notes column.

## Rollups

- **GREEN (apples-to-apples with v1)**: 44 of 47 (94%).
- **GREEN (strict end-to-end)**: 43 of 47 (91%) — drops
  `multiplayer_demo.py`, which v1 also could not really exercise.
- **RUNTIME_ERROR**: 2 (`hello_3d_layer.py`, `hello_bake.py`).
- **IMPORT_MISSING_OTHER**: 1 (`ik_skeleton_demo.py`).
- **IMPORT_MISSING_SOFTBODY**: 0.
- **IMPORT_MISSING_FLUID**: 0.
- **TIMEOUT**: 0.

## Delta vs 2026-05-31

### Newly GREEN (5)

| Example | v1 status | v2 status | Reason |
|---|---|---|---|
| hello_gi.py | RUNTIME_ERROR | GREEN | Sprint 2B restored `SVGFDenoiser.reset_history`. |
| humanoid_destruction_demo.py | IMPORT_MISSING_OTHER | GREEN | Sprint 2A re-added `make_humanoid` + `wrap_in_flesh`. |
| humanoid_ik_terrain_demo.py | IMPORT_MISSING_OTHER | GREEN | Sprint 2A re-added `make_humanoid` + `place_feet_on_terrain`; Sprint 5G polish landed. |
| humanoid_standing_demo.py | IMPORT_MISSING_OTHER | GREEN | Sprint 2A re-added `make_humanoid` + `place_feet_on_terrain`. |
| humanoid_walking_demo.py | IMPORT_MISSING_OTHER | GREEN | Sprint 2A re-added the humanoid factories. |

### Newly broken (2)

Both are GPU pipeline bugs that were latent in v1 and are now exposed by
Sprint 2C's real-frame `Engine.run(max_frames=N)` path. v1's audit
patched `Engine.run` to a no-op, so the GPU mesh pipeline was never
built. With max_frames driving real draws, the pipeline-layout mismatch
in `python/pharos_engine/gpu/mesh_pipeline.py:124` surfaces.

| Example | v1 | v2 | Root cause |
|---|---|---|---|
| hello_3d_layer.py | GREEN (no-op patch) | RUNTIME_ERROR | `mesh_pipeline.py:124` — `wgpu.GPUValidationError: Shader global ResourceBinding { group: 1, binding: 1 } is not available in the pipeline layout`. |
| hello_bake.py | GREEN (no-op patch) | RUNTIME_ERROR | Same `mesh_pipeline.py:124` shader-binding-vs-layout mismatch. |

### Still broken (1, new failure mode)

| Example | v1 | v2 |
|---|---|---|
| ik_skeleton_demo.py | RUNTIME_ERROR at `dynamics/joint.py:177` (`SoftBodyWorld.positions`) | IMPORT_MISSING_OTHER — `make_distance` and `resolve_joint_specs` no longer in `pharos_engine.dynamics` public API. |

## Action items for Sprint 2D / 3

1. **Restore `make_distance` and `resolve_joint_specs` in
   `pharos_engine.dynamics.__init__`.** Both names were used by
   `ik_skeleton_demo.py` and presumably by external callers; the
   internal `dynamics/joint.py` module still has the underlying logic.
2. **Fix `gpu/mesh_pipeline.py:124` shader binding layout.** The
   fragment shader declares `@group(1) @binding(1)` but the pipeline
   layout does not advertise it. Either drop the unused binding from
   the WGSL fragment shader or add the matching `BindGroupLayoutEntry`
   to the Python pipeline-layout builder. Two demos depend on this fix
   (`hello_3d_layer`, `hello_bake`) — both should be added to the
   visual regression suite once green so the no-op-patch blind spot
   does not recur.
3. **Replace the `multiplayer_demo.py` "argparse" false positive with a
   real local-loopback smoke**, e.g. a `--selftest` mode that spawns
   two in-process sessions over a `LocalTransport`, runs 5 lockstep
   ticks, and exits 0. Today neither v1 nor v2 actually exercises the
   demo end-to-end.
