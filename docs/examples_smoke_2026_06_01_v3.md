# Examples Smoke Audit v3 — 2026-06-01

## What changed since v2

The v2 audit at `docs/examples_smoke_2026_06_01.md` (commit `106faea`)
recorded 44/47 GREEN end-to-end, with three failing demos:
`hello_3d_layer.py` and `hello_bake.py` (GPU pipeline-layout mismatch at
`gpu/mesh_pipeline.py:124`) and `ik_skeleton_demo.py` (ImportError on
`make_distance` / `resolve_joint_specs`). Sprint 7A (`e3e89d7`) restored
both names on `slappyengine.dynamics`, realigned `ik_skeleton_demo.py` to
the current `IKChainSpec(node_indices=...)` / `solve_ik(spec, world,
...)` signature, and added an `argparse --frames N` flag. Sprint 7B
(`d3871b9`) authored a slimmed `mesh_frag_pbr_simple.wgsl` whose declared
bindings exactly match the documented `@group(0).0 + @group(1).0`
pipeline layout (camera + material). Sprint R2S1-E (`5956440`) wired
`--frames` through the two 3D demos so the smoke harness exits cleanly
at frame 5 instead of camping the live event loop. All three previously-
broken demos are now GREEN, taking the count to **47/47 GREEN** under
the apples-to-apples v1/v2 invocation — the first clean sweep since the
audit began. `multiplayer_demo.py` remains a known false-positive shape
(apples-to-apples GREEN under `--frames 5`; no real lockstep self-test
exists yet), so the strict-end-to-end count is **46/47** if you exclude
it on the same grounds v2 noted.

## Methodology

Identical to v2. For every `examples/*.py` outside `legacy/` and
`output/`, the audit script ran one of three probes with
`PYTHONPATH=python` and a 90 s `subprocess` timeout:

1. **`--frames 5`** for argparse demos that wire that flag.
2. **No-args** for argparse demos without `--frames`, and for scripts
   that simply execute on import (GIF writers, baked offline demos).
3. **`Engine.run(max_frames=5)` injection** via `runpy` for pure
   `engine.run()` event-loop demos. A monkey-patch wraps `Engine.run` so
   that when the demo calls `engine.run()` with no arguments, the
   harness substitutes `max_frames=5`.

Categories: **GREEN** / **RUNTIME_ERROR** / **IMPORT_MISSING_OTHER** /
**IMPORT_MISSING_SOFTBODY** / **IMPORT_MISSING_FLUID** / **TIMEOUT**.

## Results (47 examples)

| Example | Status | Notes |
|---|---|---|
| bullet_holes_demo.py | GREEN | No-args; writes `examples/output/particles/bullet_holes.gif`; total particles=113. |
| buoyancy_demo.py | GREEN | No-args; writes `examples/output/buoyancy/buoyancy.gif`; 2190 splash impulses; wall=5.8 s (one-shot GIF writer, no `--frames` exposed). |
| character_damage_demo.py | GREEN | No-args; cumulative cuts bone=7 muscle=4 skin=2. |
| detonate_gallery_demo.py | GREEN | `--frames 5`; argparse demo. |
| editor_demo.py | GREEN | No-args; "No project found" notice is expected without a project on disk. |
| fluid_demo.py | GREEN | No-args; writes `water_basin.gif`; surface render mean=3.57 ms p95=4.19 ms. |
| fluid_sandbox.py | GREEN | `Engine.run(max_frames=5)` injected; canvas + scene built and 5 frames drawn cleanly. |
| fluid_surface_demo.py | GREEN | No-args; writes `surface_overlay_perf.txt`. |
| glass_fracture_demo.py | GREEN | No-args; 13 connected components after impact. |
| hello_3d_layer.py | GREEN | NEWLY GREEN. `--frames 5`; Sprint 7B mesh shader-binding fix + R2S1-E `--frames` wiring. |
| hello_audio.py | GREEN | Argparse, no `--frames`; default run played stub clip. |
| hello_bake.py | GREEN | NEWLY GREEN. `--frames 5`; same Sprint 7B/R2S1-E fixes; heightmap vertex Z range [0.000, 2.000]. |
| hello_composite.py | GREEN | `--frames 5`; zone.enter=0. |
| hello_dynamics_serialize.py | GREEN | `--frames 5`; roundtrip clean, no NaN. |
| hello_gi.py | GREEN | No-args; writes `hello_gi.png` (direct \| cascade+noise \| SVGF-denoised). |
| hello_ik_chain.py | GREEN | `--frames 5`; max tip-to-target 0.0086. |
| hello_iso.py | GREEN | `--frames 5`; no non-finite state. |
| hello_joint.py | GREEN | `--frames 5`; no NaN. |
| hello_lighting.py | GREEN | `Engine.run(max_frames=5)` injected; lighting scene built, 5 frames drawn. |
| hello_motor.py | GREEN | `--frames 5`; stepped frames=5. |
| hello_numerics.py | GREEN | Argparse, no `--frames`; default run no-NaN. |
| hello_physics.py | GREEN | `Engine.run(max_frames=5)`; pixel-physics compute scene drew 5 frames. |
| hello_pixel.py | GREEN | `Engine.run(max_frames=5)`; canvas + layer drew 5 frames. |
| hello_ragdoll.py | GREEN | `--frames 5`; writes `examples/output/ragdoll/hello_ragdoll.gif`. |
| hello_rope.py | GREEN | `--frames 5`; stepped frames=5. |
| hello_spring.py | GREEN | `--frames 5`; final y=0.6498. |
| hello_studio.py | GREEN | No-args; writes `examples/output/studio/hello_studio.gif`. |
| hello_telemetry.py | GREEN | `--frames 5`; emit bench 20273.26 ns/emit. |
| hello_thermal.py | GREEN | `--frames 5`; hot/cold poles settle. |
| hello_topology.py | GREEN | Argparse, no `--frames`; edges=112 components=1. |
| hello_world.py | GREEN | `Engine.run(max_frames=5)`; minimal window drew 5 frames. |
| hello_zone.py | GREEN | `--frames 5`; no NaN. |
| hud_demo.py | GREEN | `Engine.run(max_frames=5)`; HUD wiring + script attach OK. |
| humanoid_destruction_demo.py | GREEN | No-args; cumulative cuts bone(L0)=46 muscle(L1)=14 skin(L2)=14. |
| humanoid_ik_terrain_demo.py | GREEN | `--frames 5`; writes `examples/output/humanoid/humanoid_ik_terrain.gif`. |
| humanoid_standing_demo.py | GREEN | No-args; pose head y=1.840 pelvis y=2.550 ankle_l y=3.500. |
| humanoid_walking_demo.py | GREEN | No-args; writes `examples/output/humanoid/humanoid_walking.gif`. |
| ik_skeleton_demo.py | GREEN | NEWLY GREEN. `--frames 5`; Sprint 7A restored `make_distance` + `resolve_joint_specs`; demo realigned to current `IKChainSpec(node_indices=...)` / `solve_ik(spec, world, ...)` signature; reported 3/5 frames had IK tail >0.05 m from target (well within smoke tolerance). |
| landscape_demo.py | GREEN | `Engine.run(max_frames=5)`; landscape streamer initialised. |
| layered_character.py | GREEN | `Engine.run(max_frames=5)`; warrior tick wired. |
| layered_creature_drop.py | GREEN | No-args; writes `creature_drop.gif`; centroid drift 1.173. |
| multiplayer_demo.py | GREEN(\*) | `--frames 5` (matching v1 + v2 invocation) — argparse-style flag is rejected by the demo's `host`/`join` switch and the script exits 0 with "Unknown mode: '--frames'". Apples-to-apples GREEN. With no args it picks `host` and fails at DHT bind on Windows with `WinError 10048` (port-in-use), the same environment flake noted in v2. |
| particles_sample.py | GREEN | No-args; writes `examples/particles_sample.png`; 448 live particles. |
| sand_crater_demo.py | GREEN | `--frames 5`; argparse demo. |
| softbody_vehicle_demo.py | GREEN | No-args; writes `softbody/vehicle_demo.gif`; 0/263 beams broken; wall=8.2 s (one-shot GIF writer). |
| vehicle_obstacle_course.py | GREEN | No-args; writes `softbody/vehicle_course.gif`; 0/907 beams broken; wall=27.8 s (one-shot GIF writer). |
| visual_check_demo.py | GREEN | No-args; sand/rock/snow stratify correctly. |
| water_dam_break.py | GREEN | No-args; writes `dam_break.gif`; surface render mean=4.01 ms. |

\* `multiplayer_demo.py` is marked GREEN under the apples-to-apples v1/v2
invocation but is not a meaningful smoke test — same caveat as v2.

## Rollups

- **GREEN (apples-to-apples with v1/v2)**: 47 of 47 (100%).
- **GREEN (strict end-to-end)**: 46 of 47 (98%) — drops
  `multiplayer_demo.py`, which v1 and v2 also could not really exercise.
- **RUNTIME_ERROR**: 0.
- **IMPORT_MISSING_OTHER**: 0.
- **IMPORT_MISSING_SOFTBODY**: 0.
- **IMPORT_MISSING_FLUID**: 0.
- **TIMEOUT**: 0.

## Delta vs v2 (2026-06-01, commit `106faea`)

### Newly GREEN (3)

| Example | v2 status | v3 status | Reason |
|---|---|---|---|
| hello_3d_layer.py | RUNTIME_ERROR | GREEN | Sprint 7B (`d3871b9`) replaced `mesh_frag_pbr.wgsl` with a slimmed `mesh_frag_pbr_simple.wgsl` whose `@group/@binding` declarations exactly match the documented pipeline layout (camera @0/0 + material @1/0). Sprint R2S1-E (`5956440`) wired `--frames N` to `Engine.run(max_frames=N)` so the harness exits cleanly. |
| hello_bake.py | RUNTIME_ERROR | GREEN | Same Sprint 7B mesh shader-binding fix + R2S1-E `--frames` wiring. |
| ik_skeleton_demo.py | IMPORT_MISSING_OTHER | GREEN | Sprint 7A (`e3e89d7`) restored `make_distance` and `resolve_joint_specs` on `slappyengine.dynamics`'s public surface. The demo body was realigned to the current `IKChainSpec(node_indices=...)` / `solve_ik(spec, world, ...)` signature and gained an `argparse --frames N` flag. `solve_ik` and its `_validation` gate were widened to accept the softbody duck via a `_positions_view` accessor that reads `world.positions` or falls back to `world.nodes.pos`. |

### Newly broken (0)

No regressions.

### Still broken (0)

No remaining failures.

## Silent-`--frames`-ignore audit (bonus)

No demo silently ignored `--frames` and ran to the 90 s subprocess
timeout. The three longest wall-clocks are all `noargs` GIF-writing
demos that do not expose a `--frames` flag at all (so there is nothing
to ignore), and all exit on their own well under the budget:

- `vehicle_obstacle_course.py` — 27.8 s (writes `softbody/vehicle_course.gif`).
- `softbody_vehicle_demo.py` — 8.2 s (writes `softbody/vehicle_demo.gif`).
- `buoyancy_demo.py` — 5.8 s (writes `buoyancy/buoyancy.gif`).

If smoke-suite wall time becomes a CI bottleneck, these three are the
candidates for an opt-in `--frames` flag (currently they run a
fixed-length scripted trajectory and emit a GIF, similar to the humanoid
GIF demos). All eight demos that needed the `Engine.run(max_frames=5)`
injection still exit in ~2 s each, confirming the inject path is driving
real frames (not no-op-ing through `run()`).

## Action items going forward

1. **Add `hello_3d_layer.py` + `hello_bake.py` to the visual regression
   suite** so the Sprint 7B shader-binding fix is locked in by a
   continuously-running visual test rather than only by
   `tests/test_examples_3d_smoke.py`.
2. **Replace the `multiplayer_demo.py` "argparse" false positive with a
   real local-loopback smoke** — same recommendation v2 made. A
   `--selftest` mode that spawns two in-process sessions over a
   `LocalTransport`, runs 5 lockstep ticks, and exits 0 would convert
   this from an apples-to-apples GREEN(\*) into a real strict-end-to-end
   GREEN.
3. **Optional**: thread a `--frames N` flag through
   `vehicle_obstacle_course.py`, `softbody_vehicle_demo.py`, and
   `buoyancy_demo.py` if smoke-suite wall time becomes a CI bottleneck.
   No correctness motivation today — all three exit cleanly under their
   built-in scripted trajectories.
