# Examples Smoke Audit — 2026-05-31

Read-only audit of every `SlapPyEngineExamples/examples/*.py` (excluding `SlapPyEngineExamples/examples/legacy/` and
`SlapPyEngineExamples/examples/output/`) in the committed worktree at
`H:\Github\SlapPyEngine`.

## Methodology

For each example, two probes were performed with `PYTHONPATH=python` and a
45-second `subprocess` timeout:

1. **Probe A — `<example> --help`.** Examples wired with `argparse` print
   usage and exit 0. Examples without `argparse` ignore the flag and run the
   whole demo (these typically write a GIF to `SlapPyEngineExamples/examples/output/` and exit 0
   when complete, or call `engine.run()` and enter an interactive event loop
   that the harness aborts with a timeout signal).
2. **Probe B — short headless run.** For `argparse` examples, retry with
   `--frames 5` (falling back to `--steps 5`, then no args) to confirm a
   short end-to-end pass. For interactive (`engine.run()`-only) examples,
   monkey-patch `Engine.run` to a no-op and re-execute via `runpy` to verify
   module-load + scene-build still succeeds.

## Status legend

- **GREEN** — example completes a short headless run, or in the case of pure
  `engine.run()` event-loop demos, imports and constructs scene successfully.
- **RUNTIME_ERROR** — imports fine but crashes during execution.
- **IMPORT_MISSING_OTHER** — an import from `slappyengine.*` no longer
  resolves on this branch.
- **IMPORT_MISSING_SOFTBODY** — refers to a missing `slappyengine.softbody`
  symbol. *(None observed — the package is present.)*
- **IMPORT_MISSING_FLUID** — refers to a missing `slappyengine.fluid`
  symbol. *(None observed — the package is present.)*

## Results (47 examples)

| Example | Status | Notes |
|---|---|---|
| bullet_holes_demo.py | GREEN | Writes `SlapPyEngineExamples/examples/output/particles/bullet_holes.gif`; 14 bullets, 352 wall pixels drilled. |
| buoyancy_demo.py | GREEN | Writes `SlapPyEngineExamples/examples/output/buoyancy/buoyancy.gif`; wood/steel stratify correctly, 2190 splash impulses. |
| character_damage_demo.py | GREEN | Writes `SlapPyEngineExamples/examples/output/character/character_damage.gif`; cumulative cuts bone=7 muscle=4 skin=2. |
| detonate_gallery_demo.py | GREEN | `--frames 5` passes; argparse demo. |
| editor_demo.py | GREEN | Launches editor shell; "No project found" notice expected without a project on disk. |
| fluid_demo.py | GREEN | Writes `SlapPyEngineExamples/examples/output/fluid/water_basin.gif`; 140 particles, mean surface ms=7.94. |
| fluid_sandbox.py | GREEN | Calls `engine.run()`; returns cleanly in headless mode. Scene/material wiring imports OK. |
| fluid_surface_demo.py | GREEN | Splat+surface stitched; perf log `SlapPyEngineExamples/examples/output/fluid/surface_overlay_perf.txt` written. |
| glass_fracture_demo.py | GREEN | Writes `SlapPyEngineExamples/examples/output/fracture/glass_fracture.gif`; 87/110 beams broken, 13 components. |
| hello_3d_layer.py | GREEN | Interactive `engine.run()` event-loop demo; module-load + scene-build verified. |
| hello_audio.py | GREEN | Argparse; default no-args run passes. |
| hello_bake.py | GREEN | Interactive `engine.run()`; baked layer + heightmap mesh apply correctly under no-op patch. |
| hello_composite.py | GREEN | `--frames 5` passes. |
| hello_dynamics_serialize.py | GREEN | `--frames 5` passes; tests dynamics save/load roundtrip. |
| hello_gi.py | RUNTIME_ERROR | `AttributeError: 'SVGFDenoiser' object has no attribute 'reset_history'` at `SlapPyEngineExamples/examples/hello_gi.py:86`. SVGFDenoiser API drifted from the demo. |
| hello_ik_chain.py | GREEN | `--frames 5` passes. |
| hello_iso.py | GREEN | `--frames 5` passes. |
| hello_joint.py | GREEN | `--frames 5` passes. |
| hello_lighting.py | GREEN | Interactive `engine.run()`; module-load + scene-build verified. |
| hello_motor.py | GREEN | `--frames 5` passes. |
| hello_numerics.py | GREEN | Argparse; default no-args run passes. |
| hello_physics.py | GREEN | Interactive `engine.run()`; pixel-physics compute scene constructed cleanly. |
| hello_pixel.py | GREEN | Interactive `engine.run()`; canvas built, layer painted. |
| hello_ragdoll.py | GREEN | `--frames 5` passes. |
| hello_rope.py | GREEN | `--frames 5` passes. |
| hello_spring.py | GREEN | `--frames 5` passes. |
| hello_telemetry.py | GREEN | `--frames 5` passes. |
| hello_thermal.py | GREEN | `--frames 5` passes. |
| hello_topology.py | GREEN | Argparse; default no-args run passes. |
| hello_world.py | GREEN | Minimal `engine.run()` window; constructor + load_scene OK. |
| hello_zone.py | GREEN | `--frames 5` passes. |
| hud_demo.py | GREEN | Interactive `engine.run()`; HUD wiring + script attach OK (deprecation warning about subclassing `Script`). |
| humanoid_destruction_demo.py | IMPORT_MISSING_OTHER | `ImportError: cannot import name 'make_humanoid' from 'slappyengine.dynamics'`. Also needs `wrap_in_flesh`. |
| humanoid_ik_terrain_demo.py | IMPORT_MISSING_OTHER | `ImportError: cannot import name 'make_humanoid' from 'slappyengine.dynamics'` (and `place_feet_on_terrain`). |
| humanoid_standing_demo.py | IMPORT_MISSING_OTHER | Same `make_humanoid` / `place_feet_on_terrain` missing in `slappyengine.dynamics`. |
| humanoid_walking_demo.py | IMPORT_MISSING_OTHER | Same `make_humanoid` / `place_feet_on_terrain` / `wrap_in_flesh` missing. |
| ik_skeleton_demo.py | RUNTIME_ERROR | `AttributeError: 'SoftBodyWorld' object has no attribute 'positions'` raised from `dynamics/joint.py:177` during distance-joint projection. Solver field drift. |
| landscape_demo.py | GREEN | Interactive `engine.run()`; landscape streaming dir created, 0 tiles initially visible. |
| layered_character.py | GREEN | Interactive `engine.run()`; warrior tick wired. |
| layered_creature_drop.py | GREEN | Writes `SlapPyEngineExamples/examples/output/softbody/creature_drop.gif`; 1/279 beams broken; centroid drift ~1.17. |
| multiplayer_demo.py | GREEN | `--frames 5` passes; argparse demo. |
| particles_sample.py | GREEN | Writes `SlapPyEngineExamples/examples/particles_sample.png`; 448 live particles. |
| sand_crater_demo.py | GREEN | `--frames 5` passes. |
| softbody_vehicle_demo.py | GREEN | Writes `SlapPyEngineExamples/examples/output/softbody/vehicle_demo.gif`; chassis settled at [-0.95, 4.55], 0/263 beams broken. |
| vehicle_obstacle_course.py | GREEN | Writes `SlapPyEngineExamples/examples/output/softbody/vehicle_course.gif`; final chassis x=-1.58, 0/907 beams broken. |
| visual_check_demo.py | GREEN | Material sandbox: sand 461 settled / pile_max 81, rock 461 / 87, snow 329 / pile_max 8. |
| water_dam_break.py | GREEN | Writes `SlapPyEngineExamples/examples/output/fluid/dam_break.gif`; 240 particles, peak |v|=0.326. |

## Rollups

- **GREEN**: 41 of 47 (87%).
- **RUNTIME_ERROR**: 2 (`hello_gi.py`, `ik_skeleton_demo.py`).
- **IMPORT_MISSING_OTHER**: 4 (all four `humanoid_*_demo.py`).
- **IMPORT_MISSING_SOFTBODY**: 0 — `slappyengine.softbody` is present and exposes
  `SoftBodyWorld`, `SoftBodyRenderer`, `BodyMeta`, `NodeSoA`, `BeamSoA`,
  `Material`, `MATERIALS`, `VehicleHandle`, etc.
- **IMPORT_MISSING_FLUID**: 0 — `slappyengine.fluid` exposes `FluidWorld`,
  `FluidRenderer`, `FluidMaterial`, and the `WATER/LAVA/GRAVEL/DUST/ICE` material
  presets.

## Failure breakdown

### Missing `make_humanoid` family (4 demos)

`slappyengine.dynamics.__init__` currently exports:

```
Body, BoneSpec, IKChainSpec, JointSpec, Material, MotorSpec, RagdollSpec,
RopeSpec, SoftBodyWorld, SpringSpec, World, build_ragdoll, build_rope,
make_distance, make_motor, make_spring, resolve_joint, resolve_joint_specs,
save_world, load_world, solve_ik, world_from_dict, world_to_dict, ...
```

but the four humanoid demos import `make_humanoid`, `place_feet_on_terrain`,
and `wrap_in_flesh`, which never made it into `dynamics/__init__.py` (or were
moved during the Phase D strip). All four demos die at import time.

### `SVGFDenoiser.reset_history` missing

`SlapPyEngineExamples/examples/hello_gi.py` constructs `SVGFDenoiser(W, H)` and calls
`reset_history()` immediately. The attribute is absent on the current
implementation — either it was renamed (e.g. `reset()`) or removed when SVGF
moved into `slappyengine.gi.svgf`. Demo crashes at line 86 before any frame
is produced.

### `SoftBodyWorld.positions` missing

`SlapPyEngineExamples/examples/ik_skeleton_demo.py` reaches
`dynamics/joint.py:177 _project_distance` which dereferences
`world.positions[a]`. The current `SoftBodyWorld` SoA likely exposes node
positions through `nodes.x` / `node_pos` / similar, but not `positions`.
This is a regression in `slappyengine.dynamics.joint`'s distance solver
relative to the worker `SoftBodyWorld` schema, not the example itself.

## Caveat on "interactive" demos

11 examples are pure `engine.run()` event-loop demos (`hello_world`,
`hello_pixel`, `hello_physics`, `hello_lighting`, `hello_3d_layer`,
`hello_bake`, `hud_demo`, `landscape_demo`, `layered_character`,
`fluid_sandbox`, `editor_demo`). The current `Engine.run()` signature takes
no `--frames` / `--max-frames` argument, so a fully unattended smoke test
cannot drive them to completion — they sit in the input loop until the user
closes the window. The audit verified the import + scene-build half by
monkey-patching `Engine.run` to a no-op and re-executing each via `runpy`;
all 11 reached the patched `engine.run()` call with no exception. A future
hardening pass should add an `Engine.run(max_frames=...)` keyword so these
demos can be exercised end-to-end in CI without window manipulation.

**Update 2026-05-31:** `Engine.run(max_frames=N)` has landed — when `N` is
given the engine drives the per-frame draw callback exactly `N` times
in-process and returns without entering the platform event loop, so all 11
demos above can now be smoke-tested end-to-end in CI without window
manipulation.  Regression test: `SlapPyEngineTests/tests/test_engine_max_frames.py`.
