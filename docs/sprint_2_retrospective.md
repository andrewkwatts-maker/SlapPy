# Sprint 2 retrospective — Per-particle GPU kernels

ParticleField GPU port, sprint 2 of 7. Theme was "land every per-particle
kernel on the real GPU backend behind opt-in flags". Five kernels shipped
in a 4-commit window plus the retrospective + benchmark refresh.

Sprint 1 ended with 1 kernel on GPU (integrate) and a CPU baseline.
Sprint 2 closes with 6 kernels on GPU (integrate + collide + drill +
slide + kinetic_relax + thermal_step), all default-OFF, all parity-tested
against the canonical CPU reference.

## Delivered

The five commits, in landing order:

1. **`f751fa8` — Sprint 2 GPU: `_collide` kernel — bit-exact parity with CPU.**
   `shaders/particle_collide.wgsl` (workgroup 64, 10 bindings). Per-particle
   swept-xy DDA from previous-frame pos to current pos; on hit, stamp
   position one pixel above, capture impact_vel, set phase to LANDED.
   Fluid materials pop back to AIRBORNE with vy=0. Drill materials route
   back to CPU (handled by `_drill_through` separately). Parity test:
   max |Δpos| = max |Δvel| = max |Δimpact| = 0.0 — bit-exact.
2. **`1690de8` — Sprint 2 GPU: `_drill_through` kernel — DDA + entry crater + ejecta readback.**
   `shaders/particle_drill.wgsl` (workgroup 64, 13 bindings). Per-particle
   entry crater clearing with per-pixel velocity cost, drill walk along
   velocity direction, KE check, lodge on stop (stamp into mask + BAKED).
   Ejecta capture via atomic counter into output buffers (max 4096 per
   dispatch). Mask + material_grid + loose readback per frame is the perf
   killer at small N — flagged for Sprint 6+ persistent residency. Parity
   test passes: exact mask alpha + tol on pos.
3. **`3cca2c6` — Sprint 2 GPU: `_slide` kernel + column_top precompute pass.**
   `shaders/particle_column_top.wgsl` (1 thread/column, first-solid-y
   scan) + `shaders/particle_slide.wgsl` (1 thread/landed-particle,
   friction + snap + downhill redirect + tumble kick + settle jitter).
   Per-particle PCG32 RNG state added to the SoA (u32 array). Numpy
   fallback mirrors the GPU PCG path so toggling the flag without wgpu
   still matches the GPU branch. Parity is intentionally loose
   (1 px pos / 2 px·s⁻¹ vel) because CPU uses `field._rng` in iteration
   order; GPU runs per-particle PCG32 in parallel.
4. **`f43e67c` — Sprint 2 GPU: `_kinetic_relax` kernel — 6× at 10k particles.**
   `shaders/particle_kinetic_relax.wgsl` (workgroup 64). Per-thread reads
   own cell from `cell_id[i]`, iterates same cell via cell_start /
   cell_count / sorted_ids, accumulates push from in-cell pairs within
   `rest_distance` into a local vec2f, writes to `push[i]`. NO ATOMICS
   NEEDED — pair (i, j) is visited twice producing equal-and-opposite
   contributions to own slots. Reuses Sprint 1's CPU SpatialHash for the
   counting-sort. Per-step push parity: 1.5e-5.
5. **`2db3bcd` — Sprint 2 GPU: `_thermal_step` kernel — phase change works end-to-end on GPU.**
   `shaders/particle_thermal.wgsl` (workgroup 64, 5 bindings). Per-particle
   relax T toward ambient, check melt_at then freeze_at, write back T,
   material_id, and packed rgba8 colour. Thermal profile uniform array
   (48 B per material × 64 max = 3 KB). Parity: temperatures within
   atol=1e-4 °C, material_id exact, colour exact across snow → water test.

A sixth commit (`4bd64cd` — Sprint 1 retrospective + post-vectorisation
benchmark) landed in this window but belongs to Sprint 1's wrap-up.

## Parity results table

| kernel | parity | notes |
|---|---|---|
| `_integrate` (Sprint 1) | 5e-5 drift | done |
| `_collide` | bit-exact | NEW |
| `_drill_through` | exact mask alpha + tol pos | NEW |
| `_slide` | 1 px / 2 px·s⁻¹ | per-particle RNG diverges by design |
| `_kinetic_relax` | 1.5e-5 push parity | NEW |
| `_thermal_step` | atol 1e-4 °C, exact mid + colour | NEW |

## Performance — kinetic_relax benchmark

From commit `f43e67c` (real GPU, dev machine):

| N | CPU kinetic ms | hash rebuild ms | GPU total ms | speedup |
|---:|---:|---:|---:|---:|
|    100 |  0.10 | 0.014 | 1.03 | 0.09× |
|    500 |  0.41 | 0.023 | 1.12 | 0.37× |
|   1000 |  0.82 | 0.035 | 1.13 | 0.73× |
|   2000 |  1.76 | 0.273 | 1.50 | **1.18×** ← break-even |
|   5000 |  5.22 | 0.164 | 1.91 | 2.73× |
|  10000 |  9.09 | 0.334 | 1.48 | 6.13× |
|  20000 | 19.83 | 0.720 | 2.01 | 9.86× |

GPU bottleneck at low N is wgpu round-trip (~1 ms command encoding +
queue submit + push-buffer readback). Default keeps
`use_gpu_kinetic_relax=False` — opt-in for large-N scenes.

## What worked

- **All 5 kernels landed on the real GPU backend.** Not a single
  numpy-only fallback shipped in production. Every one of `collide`,
  `drill`, `slide`, `kinetic_relax`, `thermal` was validated against
  the wgpu Vulkan/DX12 path on the dev box.
- **The `use_gpu_<kernel>: bool` flag pattern keeps the CPU path as the
  canonical reference.** Every parity test reads CPU as ground truth.
  When the GPU kernel's behaviour drifts (slide's RNG, drill's atomic
  ejecta), it's the GPU that has to document the divergence, not the
  CPU. This is the right asymmetry for a CPU-first engine that grew a
  GPU port.
- **Parity test framework caught the `column_top` + `py_floordiv`
  subtleties early.** The collide kernel needed a custom `py_floordiv`
  helper because Python's floor-division and WGSL's truncate-toward-zero
  diverge on negative DDA stepping. The parity test failed on the very
  first dispatch, the fix was a 6-line shader helper, total cost was
  one debug cycle. Without the parity harness this would have been a
  silent visual bug.
- **Drill ejecta readback works.** 4096 max ejecta per dispatch via
  atomic counter + indirect-style packing. Overflow path warns and
  clamps (heavy overdrill is visually unstable anyway). For sustained
  combat workloads this is enough headroom.
- **Thermal phase change end-to-end on GPU.** Snow → water in a single
  dispatch — material_id flip, colour flip, temperature update all
  atomic with no readback inside the step. The thermal profile uniform
  buffer pattern is reusable for the next material-property kernel.

## What surprised us

- **`_collide` was bit-exact.** Sprint 1's integrate kernel had 5e-5
  drift, which we read as a sign that DDA-style logic might trend
  similarly. Wrong: collide's DDA produced zero diff on pos / vel /
  impact across the entire parity suite. The drift in integrate
  was specifically the gravity multiply-accumulate ordering — DDA
  iteration order is deterministic across CPU and GPU when the loop
  bound and step calculation match exactly.
- **`_kinetic_relax` break-even is ~2000 particles.** Sprint 1's vectorise
  win (9.87× CPU) raised the floor. At 1k particles, the kernel takes
  0.82 ms on CPU; the GPU round-trip is 1.13 ms. The GPU only starts
  winning when the CPU kernel costs > the wgpu submit overhead, which
  is around 1.5-2 ms — i.e. ~2k particles. Small scenes actively
  regress on GPU.
- **`_drill_through` readback dominates the kernel cost.** The shader
  itself is fast; per-frame readback of mask + material_grid + loose
  is the real bill. At small particle counts the readback is the same
  cost as a CPU drill. Persistent GPU residency for those three arrays
  is the architectural fix — likely Sprint 6+.
- **`_slide` needed a per-particle `rng_state` (u32 array) added to the
  SoA.** Small change — one column in the struct — but a real API
  surface change. Anyone reading `field.__dict__` now sees `rng_state`.
  Spawn helpers needed to seed it. Buffer growth (`spawn_batch`) needed
  to vectorise the seeding. The change is contained, but it's the first
  Sprint 2 commit that wasn't purely additive on the GPU side.

## What didn't work / still TODO

- **Drill ejecta readback round-trip is the elephant in the room.**
  Reading mask + material_grid + loose every frame after `gpu_drill`
  costs as much as the kernel itself at small N. The architectural fix
  is persistent GPU residency for those three textures: only SoA +
  ejecta cross the bus, the world stays resident. Likely Sprint 6+
  (the buffer doc has the storage texture layouts ready).
- **Splat deformation NOT yet ported.** Bake stamps currently use a
  uniform polygon per particle. Sprint 3's bake kernel will need to
  skip splat (uniform shapes only); Sprint 4 will add splat-aware bake
  with a shape atlas pre-rasterised per family.
- **`_fluid_relax` not yet GPU-ported.** Sprint 4's PBF bridge wraps
  the existing `pbf_step` Rust kernel rather than porting it. Less
  Python work, more bridge work — the bridge has to keep the fluid
  subset of `pos`/`vel` synchronised between the CPU PBF and the GPU
  ParticleField without copying the world every frame.

## Sprint 3 entry conditions

Sprint 3's theme is "per-pixel kernels": shape_atlas pre-rasterisation,
detach-isolated-pixels GPU port, slump CA GPU port. Pre-conditions:

- **shape_atlas pre-rasterisation needs to be designed.** Per-family at
  multiple scales / rotations. Storage: r8unorm 2D array, ~4 MB per
  family × 8 families ≈ 32 MB resident. Index by family_id +
  scale_bucket + rotation_bucket.
- **detach-isolated-pixels CPU implementation already vectorised** (numpy
  shift-and-sum). GPU port should beat it at 1920×1080 because the CPU
  vectorised version is still 4 ms at full screen; a 16×16 workgroup
  on GPU should clear it in <0.5 ms.
- **slump CA needs per-pixel `rng_state` buffer (~256 KB for 256×256)**.
  Same PCG32 pattern as Sprint 2's slide kernel — pre-seed at world
  upload, advance per-tick. Red/black checkerboard sweep so no
  within-pass conflicts.

## Updated risk register

Re-ranked from Sprint 1's register based on Sprint 2 findings:

1. **(was #3 in Sprint 1) CPU↔GPU sync overhead dominates at low
   particle counts.** *Confirmed real.* Sprint 2's kinetic_relax
   break-even is ~2000 particles; collide + thermal hurts even at
   10200 particles on the benchmark. Mitigation: keep flags default-OFF
   through Sprint 6; auto-enable per kernel above the threshold table
   in `benchmarks/baseline_report.md`. Sprint 7 wires the auto-enable
   into a `GpuPolicy` helper.
2. **(NEW) Per-frame mask / grid / loose readback in drill is bigger
   than expected.** The drill kernel runs fast; the readback eats the
   savings. Mitigation: persistent GPU mask state by Sprint 6 — only
   SoA + ejecta cross the bus per frame; mask/grid/loose stay resident
   and are only read back when the renderer or a CPU consumer asks
   for them (and even then only the dirty rect).
3. **(NEW) Splat deformation can't go through the atlas-shape path
   easily.** Sprint 3's bake kernel needs uniform polygon stamps; splat
   needs per-particle pre-deformation. Two-stage plan: Sprint 3 ships
   the uniform-stamp bake, Sprint 4 layers splat-aware bake on top.
4. **(was #1 in Sprint 1, down) Bake-stamp write conflicts produce
   nondeterministic terrain.** *Unchanged severity, lower priority.*
   We accept non-determinism within a frame; the CPU bake has the
   same property under multi-particle co-stamps. Tiebreak rules from
   the buffer doc stand.
5. **(NEW) Per-particle `rng_state` buffer means SoA growth needs to
   handle `u32` too.** *Already done in Sprint 2.* `spawn_batch` now
   vectorises the seeding; buffer growth in `_grow_to` extends the u32
   array. Documented as a known SoA shape change for any external
   tooling that introspects the field struct.

Secondary risks (unchanged from Sprint 1):

- Lossy WGSL spatial hash collides with the lossless CPU grid (Sprint 5
  rewrite still scheduled).
- Region dispatch corrupts particles at cell boundaries (Sprint 4
  risk).
- wgpu backend quirks ship parity failures only on some hardware
  (CI matrix still pending).
- PBF bridge stalls (Sprint 6 risk).
- Storage texture format support varies across backends (mitigated
  in buffer doc).

## Notes for the sprint-3 lead agent

- The `column_top` precompute pass from `3cca2c6` is the prototype for
  Sprint 3's per-pixel passes. 1 thread per column, single-shot scan,
  no atomics. Slump's red/black checkerboard should follow the same
  shape.
- The PCG32 numpy mirror in `particle_gpu.py` (added for slide) is
  reusable for slump and detach. Don't reinvent; import.
- `use_gpu_<kernel>` opt-in pattern is non-negotiable. Sprint 3's
  three kernels will add `use_gpu_slump`, `use_gpu_detach`,
  `use_gpu_bake_uniform`. Existing tests must remain unchanged with
  flags off.
- Re-run `benchmarks/particle_field_baseline.py` at sprint-3 close.
  Watch `_slump_loose` share on scenario A — that's the kernel Sprint 3
  is gunning for. Expect the share to drop from 31% to <5% if the GPU
  port is the win we think it is.
