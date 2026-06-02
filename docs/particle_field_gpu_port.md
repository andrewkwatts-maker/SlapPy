# ParticleField GPU port — 7-sprint architecture

Authoritative design for migrating `slappyengine.physics.particle_field` from
its NumPy/Rust hybrid CPU implementation onto WGSL compute shaders running
through the existing `slappyengine.compute.pipeline.ComputePipeline`.

Companion docs (written in parallel):

- `docs/particle_field_gpu_buffers.md` — per-buffer wire layout, padding,
  alignment, and the exact storage-buffer struct definitions.
- `benchmarks/baseline_report.md` — current CPU baselines plus the
  target curves this port must hit.

## Goals

- All hot paths on GPU compute shaders by sprint 7. By "hot path" we mean
  any per-particle or per-pixel loop that currently runs through NumPy
  or the existing Rust kernels in `raster.rs` / `pbf_step`.
- Region-based dispatch so only dirty cells get worked. The existing
  `RegionGrid` (sprint 0 leftover from the CPU port) becomes the
  indirect-dispatch argument source.
- CPU↔GPU parity within float tolerance (`atol=1e-4`, `rtol=1e-3`) for
  every ported kernel. Parity is enforced by a generated pytest fixture
  that runs both paths on identical seeds and diffs the result buffers.
- Graceful fallback when wgpu isn't available (e.g. CI without GPU, or
  users on a headless server). The public `ParticleField` API never
  changes; the dispatcher transparently routes to CPU kernels when
  `ComputePipeline.is_available()` returns False.

## Non-goals

- Replacing the high-level Python API. `ParticleField` stays as the
  public surface — same `step()`, same `spawn()`, same `render()`. All
  the SoA arrays remain valid CPU mirrors so user code can keep reading
  `field.pos`, `field.vel`, etc. (readback cadence configurable).
- Re-architecting the fluid solver. PBF density relaxation is already
  Rust-accelerated through `fluid_bridge`; the GPU port consumes it as
  a black box for now. A future sprint may inline a WGSL PBF, but it's
  out of scope here.
- Custom shader language. Everything is WGSL targeting the same wgpu
  device the engine's renderer already owns. No SPIR-V hand-rolling,
  no GLSL, no MSL fallbacks.
- Multi-GPU or async-compute overlap with the main renderer. Single
  device, single queue, single command encoder per `step()`.

## Sprint plan

The plan is staged so every sprint ships a green build with parity
tests passing. Bake events, the visual demo, and the example games all
keep running between sprints — sprint N never breaks what sprint N-1
delivered.

### Sprint 1 — Compute scaffolding and SoA upload

**Theme.** Stand up the plumbing without porting any physics.

**Kernels in scope.**

- `upload_particles` — H2D copy of `pos`, `vel`, `material_id`,
  `radius`, `bake_radius`, `phase`, `phase_age`, `kinetic_age`,
  `rigidify_at`, `temperature`, `impact_vel` into mirrored storage
  buffers.
- `readback_particles` — D2H copy back into the same SoA arrays.
- `integrate_gravity` — single trivial kernel (apply
  `vel.y += gravity * dt`, `pos += vel * dt`) used purely to validate
  the round trip.

**Acceptance criteria.**

- A new `ParticleFieldGPU` wrapper (sibling to `ParticleField`) can
  spawn 10k particles, run 60 frames of pure ballistic motion, and
  match the CPU reference to `atol=1e-4` on `pos` and `vel`.
- `ComputePipeline` exposes `bind_particle_field(field)` to allocate
  the mirrored storage buffers up front (we size to
  `max_particles=200000` by default; growable via reallocate).
- Parity test infrastructure committed: `SlapPyEngineTests/tests/gpu/parity_fixture.py`
  with `assert_field_parity(cpu, gpu, channels=...)`.

**Risk callouts.**

- wgpu validation overhead on small batches makes the round trip
  slower than CPU at 10k particles. Acceptable — we're not measuring
  perf yet, only correctness.
- SoA growth via `np.vstack` in `spawn()` is incompatible with fixed
  GPU buffers. Sprint 1 introduces a `capacity` + `count` split and a
  `grow_to(n)` helper that reallocates both CPU SoA and GPU buffers.

**Backout plan.** Delete the `ParticleFieldGPU` wrapper, leave the
capacity split in `ParticleField` (it's a benign refactor that helps
the CPU path too). No other code touched.

### Sprint 2 — Per-pixel mask and material grid on GPU

**Theme.** Move the world (`mask`, `material_grid`, `loose`,
`_fixed_mask`) onto GPU storage textures, plus the simplest kernels
that read them.

**Kernels in scope.**

- `upload_world` / `readback_world` — H2D and D2H for the four
  per-pixel arrays. RGBA mask is a `rgba8unorm` storage texture;
  `material_grid` is an `r8sint`; `loose` and `_fixed_mask` pack
  into a single `r8uint` with bit lanes (bit 0 = loose, bit 1 = fixed).
- `collide_simple` — air-mask collision: each airborne particle
  samples `mask.alpha` at its current pixel; on hit, mark `phase = LANDED`
  and zero `vel`. This is the dumb collide; the drill path comes in
  sprint 5.

**Acceptance criteria.**

- Falling-sand demo (sand-only, no drill) renders identically on
  CPU and GPU after 120 frames.
- Parity test on the post-step `mask.alpha` channel across 30
  seeded scenarios.
- `RegionGrid.record_live` can ingest GPU-side particle positions
  via a small `count_per_cell` kernel; we still mark static cells
  on CPU for now (the indirect-dispatch path comes in sprint 6).

**Risk callouts.**

- Mask is `(H, W, 4) uint8`. At 4096×4096 the upload is 64 MB —
  acceptable one-shot, untenable per frame. Sprint 2 introduces a
  dirty-rect tracker so only modified scanlines copy back. CI runs
  at 512×512 to keep memory in budget on integrated GPUs.
- `r8sint` storage textures need feature flags on some backends. The
  pipeline `is_available()` probe gains a `supports_r8sint` query;
  fallback is `r16sint` (twice the memory, same correctness).

**Backout plan.** Revert `collide_simple` to its CPU counterpart while
leaving the world textures uploaded. The render path can still sample
them; only the collision step routes back to NumPy. Zero behaviour
change for users.

### Sprint 3 — Integration, drag, thermal step

**Theme.** Port the per-particle integration kernels — the easy
embarrassingly-parallel ones — so the airborne loop fully runs on GPU.

**Kernels in scope.**

- `integrate_full` — gravity + per-material `air_drag` lookup +
  position update. Reads `material_id`, indexes a uniform buffer of
  per-material physics constants (uploaded once, dirty on
  `register_material`).
- `thermal_relax` — port of `_thermal_step`. Per-particle temperature
  relaxation toward ambient, then `detect_phase_changes` flips
  `material_id` on crossings. Output: a small `phase_change_events`
  buffer streamed back to CPU for any caller subscribed to the bake
  event (snow→water etc).
- `kinetic_age_tick` — trivial, but isolated so it can fuse with
  `integrate_full` later.

**Acceptance criteria.**

- Snow-to-water mid-flight scenario (the `visual_check.gif` snow row)
  parity-passes within `atol=1e-3` on `temperature` and exact match
  on `material_id`.
- `step()` no longer touches the CPU SoA for any airborne particle
  except at readback time.
- Visual demo `visual_check_demo.py` runs identically on CPU and GPU.

**Risk callouts.**

- Per-material constants change at runtime via `register_material`.
  Sprint 3 introduces a versioned uniform buffer with a `dirty` flag
  on the field; re-upload happens at the start of any `step()` that
  follows a register call. Forgetting to dirty-flag is the
  most-likely bug.
- Thermal phase changes mutate `material_id`. That feeds back into
  every subsequent kernel's material lookups within the same frame.
  Order matters: `thermal_relax` must dispatch before `integrate_full`
  in the encoder.

**Backout plan.** Keep `integrate_full` and roll back `thermal_relax`.
The thermal port is the riskier of the two — losing it costs us no
shippable feature, just a perf regression on snow scenes.

### Sprint 4 — Region grid, dirty cells, indirect dispatch

**Theme.** Stop paying for empty regions of the world. This is the
single biggest perf lever.

**Kernels in scope.**

- `region_classify` — per-cell scan: count live particles in cell,
  mark STATIC / ACTIVE / DIRTY. Writes a `region_state` buffer
  indexed by cell.
- `build_indirect_args` — convert `region_state` into a packed list
  of active cells, then into `wgpu::DispatchIndirect` arg buffers.
- Refactor of all sprint-2/3 kernels to consume the indirect-dispatch
  buffer (workgroup-per-cell instead of workgroup-per-particle).

**Acceptance criteria.**

- 100k particles where 95% are settled-and-static: GPU `step()` time
  scales with the 5% active count, not the 100%. Parity preserved.
- A mostly-static scene (10k settled, 100 active) runs at ≥10× the
  cost of the 100-particle baseline, not 100×.
- `region_grid.mark_static_when_idle` runs entirely on GPU; CPU only
  reads back the count of active cells for stats display.

**Risk callouts.**

- Indirect dispatch on wgpu has per-backend quirks. The DX12 backend
  enforces a 65535 workgroup-count cap per dimension; we plan for a
  two-level dispatch (outer cell index → inner workgroup) up front.
- Cell boundaries split particles. A particle straddling a cell wall
  could be skipped if both cells are STATIC. Mitigation: STATIC
  classification requires *all neighbours* to also be STATIC, plus a
  one-frame DIRTY hysteresis after any boundary crossing.

**Backout plan.** All sprint-4 kernels are wrapped in a
`use_region_dispatch` flag (default True after sprint 4 ships). Flip
to False to fall back to dense per-particle dispatch — same
correctness, sprint-3 performance. Zero user-visible change.

### Sprint 5 — Collision, drill, slide, bake stamps

**Theme.** Port the contact path. This is the conceptually hardest
sprint because of write-conflict avoidance during the bake stamp.

**Kernels in scope.**

- `collide_full` — drill-aware collision. DDA-walks along velocity
  vector, atomically clears `mask.alpha` per pixel, decrements
  particle KE per pixel, spawns ejecta on `drill_eject_gain` hits.
  Ejecta spawn writes into a `pending_spawns` buffer compacted by a
  prefix-sum pass.
- `slide_kernel` — port of `_slide`. Per-landed-particle friction +
  surface-following step. Reads `mask` to find the slope direction.
- `bake_stamp` — rasterise per-particle polygon stamps into `mask`
  and `material_grid`. Uses one workgroup per particle, atomic min on
  alpha (so overlapping stamps merge predictably).

**Acceptance criteria.**

- Bullet drilling through layered mud-over-rock terrain produces the
  same crater geometry as the CPU path (parity on `mask` and
  `material_grid` after impact).
- Ejecta count, colour sampling, and material assignment match
  bit-exact between CPU and GPU.
- 10k-particle settling scenario: 60 fps GPU vs ~12 fps CPU baseline.

**Risk callouts.**

- Bake-stamp write conflicts. Two particles baking into the same
  pixel on the same frame must produce a deterministic result. We
  use `atomicMin` on alpha (first writer wins on the lower-alpha
  side) plus a `frame_id` tiebreak in `material_grid`. The
  alternative — partition particles spatially so no two share a
  pixel — adds latency without obvious benefit.
- Ejecta spawning grows `count`. If the spawn buffer overflows the
  pre-allocated capacity, we must either reject ejecta (lossy) or
  defer to next frame (latency). Sprint 5 ships with a configurable
  `ejecta_capacity` and CPU-side resize on overflow.
- DDA on GPU is awkward — variable-iteration loops kill occupancy.
  We cap at `drill_max_px` per particle per frame (matches CPU
  behaviour) and unroll partially.

**Backout plan.** Per-kernel rollback: each of the three new kernels
sits behind its own flag (`gpu_collide`, `gpu_slide`, `gpu_bake`).
Bake is the most likely to bounce. Falling back means a readback
before the bake step (cheap because only the settled subset matters)
and a CPU stamp loop.

### Sprint 6 — Slump CA, PBF bridge integration

**Theme.** Move the per-pixel cellular-automaton pass and bridge the
PBF fluid solver into the GPU-resident world.

**Kernels in scope.**

- `slump_ca` — per-loose-pixel CA. Iterates bottom-up via a
  red/black checkerboard sweep so no within-pass conflicts arise.
  Reads `loose`, `_fixed_mask`, `mask`; writes the same. Two passes
  per frame (red then black) for diagonal slumps.
- `mark_newly_baked_loose` — trivial OR of `mask.alpha > 0` into
  `loose` excluding `_fixed_mask`.
- `pbf_bridge_gpu` — synchronise the fluid subset between
  `ParticleFieldGPU` and the existing GPU-resident PBF buffer (if the
  fluid solver is on GPU) or trampoline through pinned host memory
  (if PBF is CPU-only). The bridge keeps PBF positions/velocities
  authoritative for fluid particles.

**Acceptance criteria.**

- Sand/mud pile slump matches CPU within `atol=1` on `mask.alpha`
  after 600 frames (deterministic, not stochastic — slump uses a
  seeded `philox4x32` PRNG mirroring the CPU `np.random.Generator`).
- Water pooling demo (1000 fluid particles + sand walls) matches the
  CPU PBF-bridge output within fluid-particle `atol=1e-2` on pos.
- `step()` requires no CPU↔GPU sync inside the frame; the only
  readback is at frame end, and only for the channels the caller
  asked for via `field.readback(channels=...)`.

**Risk callouts.**

- The slump CA must match the CPU randomness exactly or visual diff
  tests will fail every frame. Solution: deterministic per-pixel
  PRNG seeded as `hash(frame_id, x, y, slump_seed)`. CPU side is
  refactored in sprint 6 to use the same hash. This is a *visible*
  CPU-side change (small) — flagged for review.
- PBF bridge is the only kernel that can't be parity-tested in
  isolation; it depends on whichever PBF backend is live. We accept
  a looser parity (`atol=1e-2`) and gate it behind a feature flag
  while the fluid GPU port lands.

**Backout plan.** Slump can fall back to CPU at the cost of a full
`mask` readback per frame (~16 MB at 2k×2k). PBF bridge can be
disabled entirely (`use_pbf_bridge=False`), which we already support
on the CPU path.

### Sprint 7 — Hardening, perf tuning, render path

**Theme.** No new physics; everything is polish.

**Kernels in scope.**

- `render_particles_direct` — optional: feed GPU-resident
  `pos`/`color`/`radius` straight into the disc-rasteriser without a
  round trip. Saves the per-frame upload on the render side.
- Profile-guided fusion of `integrate_full` + `kinetic_age_tick` +
  `thermal_relax` into a single mega-kernel where the parity tests
  still pass.

**Acceptance criteria.**

- 10k particles at 60 fps end-to-end (step + render), measured by
  `benchmarks/particle_field_gpu_bench.py` on the reference RTX 4060
  CI runner.
- 100k particles at 30 fps end-to-end.
- All parity tests still pass; no kernel regresses beyond
  `atol=1e-3`.
- `SlapPyEngineExamples/examples/visual_check_demo.py` renders within 1% of CPU baseline
  pixel-similarity (LPIPS or simple per-channel L1).

**Risk callouts.**

- Mega-kernel fusion can pessimise register usage and tank occupancy.
  Each fusion gate is benchmarked individually; any kernel that
  doesn't gain ≥10% stays split.
- The render path bypass touches the public renderer interface. If
  it complicates user game code, it ships behind a
  `direct_render=True` flag, default off.

**Backout plan.** Sprint 7 is opt-in tuning. Reverting any individual
fusion is a one-line change. The render bypass is fully optional.

## Data flow architecture

```
                ┌──────────────────────────────────────────────┐
                │              Python (CPU side)                │
                │                                               │
                │  ParticleField                                │
                │   ├── SoA arrays (pos, vel, …)  ◀──── readback│
                │   ├── mask (H,W,4) uint8         ◀── dirty-rect│
                │   ├── material_grid              ◀── dirty-rect│
                │   ├── loose, _fixed_mask         ◀── dirty-rect│
                │   ├── RegionGrid                              │
                │   └── spawn() / step() / render()             │
                │                                               │
                │            │   upload                  ▲      │
                │            ▼                           │      │
                │  ┌──────────────────────────────────┐  │      │
                │  │  ComputePipeline.dispatch(...)   │  │      │
                │  └──────────────────────────────────┘  │      │
                └──────────────│─────────────────────────│──────┘
                               │  H2D                D2H │
                               ▼                         │
                ┌──────────────────────────────────────────────┐
                │                  GPU (wgpu device)            │
                │                                               │
                │  Storage buffers (SoA mirrors)                │
                │   ├── pos[max_capacity] vec2<f32>             │
                │   ├── vel[max_capacity] vec2<f32>             │
                │   ├── material_id, phase, phase_age, …        │
                │   └── temperature, impact_vel, …              │
                │                                               │
                │  Storage textures (per-pixel world)           │
                │   ├── mask_tex          rgba8unorm            │
                │   ├── material_grid_tex r8sint                │
                │   └── flags_tex         r8uint (loose|fixed)  │
                │                                               │
                │  Region buffers                               │
                │   ├── region_state[num_cells] u32             │
                │   ├── active_cells[num_cells] u32 (compacted) │
                │   └── indirect_args[num_active] u32×3         │
                │                                               │
                │  Event buffers                                │
                │   ├── phase_change_events                     │
                │   ├── ejecta_spawns                           │
                │   └── bake_events                             │
                │                                               │
                │  Material uniforms                            │
                │   └── per_material_constants[num_materials]   │
                └──────────────────────────────────────────────┘

                CPU fallback path (no wgpu, or is_available()=False):
                ┌──────────────────────────────────────────────┐
                │  ParticleField.step()                         │
                │    if not pipeline.is_available():            │
                │        legacy_cpu_step(dt)   ◀── current code │
                │    else:                                      │
                │        gpu_step(dt)                           │
                └──────────────────────────────────────────────┘
```

The key invariant: the CPU SoA mirrors and the GPU buffers are both
*authoritative*. Only one side mutates per frame (GPU during `step()`,
CPU during `spawn()` / `register_material()` / external writes), and a
single staged sync point synchronises them at frame boundaries.

## Buffer layout summary

See `docs/particle_field_gpu_buffers.md` for the exact WGSL struct
layouts, padding rules, alignment notes (vec3 → vec4 padding, std140-
equivalent rules), and the host-side `numpy.dtype` mirrors used to
ensure zero-copy uploads.

Headline numbers at default capacity (`max_particles=200000`,
world=2048×2048):

- Particle SoA storage: ~14 MB across ~12 buffers.
- World textures: ~22 MB (rgba8 mask 16 MB + r8sint material grid
  4 MB + r8uint flags 4 MB; CI 512×512 build uses ~1.4 MB).
- Region buffers (`cell_size=64`): 32×32 = 1024 cells, ~12 KB.
- Per-frame staging upload: ≤ dirty-rect size (typically <1 MB).

## Kernel inventory (target state after sprint 7)

| kernel                  | shader file                       | workgroup | reads                                         | writes                                          | invariant                                                                  |
|-------------------------|-----------------------------------|-----------|-----------------------------------------------|-------------------------------------------------|----------------------------------------------------------------------------|
| integrate_full          | shaders/particles/integrate.wgsl  | 64,1,1    | pos, vel, material_id, mat_const              | pos, vel                                        | airborne only; idempotent for `dt=0`                                       |
| thermal_relax           | shaders/particles/thermal.wgsl    | 64,1,1    | temperature, material_id, mat_const           | temperature, material_id, phase_change_events   | monotone toward ambient; material_id only flips on threshold cross         |
| kinetic_age_tick        | shaders/particles/age.wgsl        | 64,1,1    | phase, bake_flag                              | kinetic_age, phase_age                          | trivial: live particles ++; never decremented                              |
| collide_full            | shaders/particles/collide.wgsl    | 64,1,1    | pos, vel, mask_tex, material_grid, mat_const  | mask_tex, material_grid, vel, phase, impact_vel | DDA bounded by drill_max_px; atomic alpha clears                           |
| slide_kernel            | shaders/particles/slide.wgsl      | 64,1,1    | pos, vel, mask_tex, mat_const                 | pos, vel                                        | landed-not-settled only                                                    |
| bake_stamp              | shaders/particles/bake.wgsl       | 64,1,1    | pos, shape masks, material_id, impact_vel     | mask_tex, material_grid, bake_flag              | one workgroup per settled particle; atomicMin on alpha                     |
| slump_ca                | shaders/particles/slump.wgsl      | 16,16,1   | mask_tex, loose, _fixed_mask, mat_const       | mask_tex, loose                                 | red/black checkerboard; deterministic philox PRNG                          |
| mark_newly_baked_loose  | shaders/particles/loose.wgsl      | 16,16,1   | mask_tex, _fixed_mask                         | loose                                           | trivial OR                                                                 |
| region_classify         | shaders/particles/region.wgsl     | 8,8,1     | pos, region_state, phase                      | region_state                                    | STATIC requires neighbours also STATIC + 1-frame hysteresis                |
| build_indirect_args     | shaders/particles/region.wgsl     | 64,1,1    | region_state                                  | active_cells, indirect_args                     | compacts active cells; single-pass prefix sum                              |
| pbf_bridge_sync         | shaders/particles/pbf_bridge.wgsl | 64,1,1    | pos, vel, material_id, fluid PBF buffer       | fluid PBF buffer (or pos/vel for fluid subset)  | bidirectional; conservative — fluid solver is authoritative for its subset |
| render_particles_direct | shaders/particles/render.wgsl     | 64,1,1    | pos, color, radius, phase                     | accumulation framebuffer                        | airborne + landed particles only; settled particles render via mask        |

## Performance targets

Baseline numbers from `benchmarks/baseline_report.md` (CPU, NumPy +
Rust kernels on the reference Ryzen 7 7700X / RTX 4060 box):

- 1k particles: 240 fps step-only, 180 fps end-to-end.
- 10k particles: 12-18 fps step-only, 10 fps end-to-end.
- 100k particles: ~1 fps step-only, currently unusable.

Targets after sprint 7:

- 10k particles at 60 fps end-to-end (≥5× current).
- 100k particles at 30 fps end-to-end (from "impossible" to playable).
- Mostly-static scenes (95%+ settled): regional dispatch achieves
  ≥100× speedup vs dense dispatch on the same scene.
- Upload/readback overhead: ≤2 ms per frame at 100k particles with
  dirty-rect tracking.

Sprint-by-sprint perf checkpoints:

- After sprint 3: 10k particles at ≥30 fps (integration + thermal
  alone is the big win).
- After sprint 4: 95%-static 10k particles at ≥120 fps.
- After sprint 5: 10k full-physics at ≥60 fps.
- After sprint 7: targets above.

## Testing strategy

- **Parity tests.** Every kernel ships with a paired test in
  `SlapPyEngineTests/tests/gpu/parity/test_<kernel>_parity.py`. Each test runs the same
  scenario through both backends and asserts field-level equality on
  the affected channels. Tests are parametrised over 30 seeded
  scenarios (varied particle counts, materials, world sizes,
  collision densities).
- **Visual regression.** `SlapPyEngineExamples/examples/visual_check_demo.py` runs at the
  end of each sprint and the resulting GIF gets diffed against the
  sprint-N-1 baseline. We use simple per-pixel L1 with a 1% tolerance
  band; out-of-band frames fail the sprint sign-off.
- **Benchmark suite.** `benchmarks/particle_field_gpu_bench.py` runs
  at sprint start to catch regressions early. Results commit into
  `docs/perf_dashboard.md` so progress is visible.
- **Fallback test matrix.** CI runs the entire test suite twice: once
  with the GPU backend forced on, once with it forced off via
  `SLAPPY_DISABLE_GPU=1`. Both must pass.
- **Smoke tests on integrated GPUs.** A weekly CI job runs on an
  Intel UHD 770 box to catch backend-specific WGSL issues (DX12 vs
  Vulkan).

## Risk register

Five risks plus mitigations. Ordered by perceived severity.

1. **Bake-stamp write conflicts produce nondeterministic terrain.**
   - *Why it matters*: visual regression tests fail every frame, and
     user-visible "the same scenario looks different each run" is the
     worst class of bug.
   - *Mitigation*: `atomicMin` on alpha plus a frame-id tiebreak in
     `material_grid` (sprint 5). Parity test ramps from 1 to 10k
     simultaneous bakes and asserts identical output across 10 runs.
     Fallback to spatial-partition bake if atomic path proves
     too slow or too racy.

2. **Region dispatch corrupts particles at cell boundaries.**
   - *Why it matters*: a single dropped particle every 100 frames is
     enough to break long-running game sessions.
   - *Mitigation*: STATIC classification requires all 8 neighbours
     also STATIC; one-frame DIRTY hysteresis after any pos crossing;
     dedicated stress test seeds 1000 particles straddling cell
     walls and runs 10k frames with parity checks every 100.

3. **CPU↔GPU sync overhead dominates at low particle counts.**
   - *Why it matters*: small games (<1k particles) regress in perf
     and we lose the "always-on" property. Users may need to opt out.
   - *Mitigation*: heuristic auto-fallback below
     `gpu_min_particles=512` (configurable). Sprint 7 measures the
     break-even point per backend and bakes it into the default.

4. **wgpu backend quirks ship parity failures only on some hardware.**
   - *Why it matters*: passes on the dev box, fails on the user box.
   - *Mitigation*: CI runs on three backends (DX12, Vulkan, Metal
     via macOS runner); WGSL is written conservatively (no opt-in
     features without a probe); per-backend skip lists in tests are
     forbidden — any failure on any backend blocks the merge.

5. **PBF bridge stalls when the fluid GPU port lags this one.**
   - *Why it matters*: every step that crosses the PBF bridge stalls
     waiting for either the CPU PBF kernel or a sync barrier. The
     bridge becomes the perf floor.
   - *Mitigation*: sprint 6 ships the bridge in "async" mode by
     default — fluid particles run one frame behind, results
     reconciled at frame start. For deterministic builds, sync mode
     is available behind `pbf_async=False`. Long-term fix is the
     fluid GPU port (out of scope here).

Secondary risks logged but not in the top five:

- Storage texture format support varies across backends (mitigated
  in sprint 2 with the `r16sint` fallback).
- Ejecta spawn buffer overflow under pathological bullet drilling
  (mitigated in sprint 5 with configurable capacity + resize).
- Material uniform buffer dirty-flag bugs (mitigated by a
  one-test-per-register-call paranoid suite).
- Visual demo determinism drift due to GPU FP ordering (mitigated by
  the seeded philox PRNG and per-channel tolerance bands in the
  visual diff).
