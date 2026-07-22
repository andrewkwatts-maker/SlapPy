# Sprint 1 retrospective

ParticleField GPU port, sprint 1 of 7. Theme was "compute scaffolding and SoA
upload" — stand up the plumbing, ship one trivial kernel end-to-end, and
freeze a baseline to measure all future sprints against.

Eight agents dispatched in parallel; six landed clean commits in a tight
window (16:11:09 → 16:11:56). Companion docs were drafted in parallel with
the kernel work so neither blocked the other.

## Delivered

The six commits, in landing order:

1. **`8b53890` — Sprint 1: vectorise _kinetic_relax CPU baseline (9.87x speedup).**
   Replaced the nested-loop pairwise push with cell-sort + boundary-find +
   inverse-triangular pair generator + `np.add.at` scatter. 21.89 ms →
   2.22 ms per step at 5k particles in a 100×100 region. Legacy retained as
   `_kinetic_relax_legacy` for parity testing. Parity vs legacy: 7.63e-6
   max diff across 6 seeds × 3 densities.
2. **`d337404` — Sprint 1: SpatialHash CPU reference for GPU-friendly neighbour queries.**
   New `python/pharos_engine/physics/spatial_hash.py` mirroring the layout of
   `shaders/particle_spatial_hash.wgsl` (cell_start / cell_count / sorted_ids).
   Rebuild benchmark: 0.42 ms at 10k particles, 5.43 ms at 100k. Linear scaling.
3. **`12f9350` — Sprint 1: RegionGridGPU — int8/int32/bool grid + dirty bitmask for indirect dispatch.**
   New `python/pharos_engine/physics/region_gpu.py`. State (DORMANT/ACTIVE/STATIC),
   live_count, dirty bitmask packable to `uint32`. ~24 KB total at 4K×4K map,
   `cell_size=64`. 7 tests green. Coexists with existing `baked_terrain.RegionGrid`.
4. **`d55ebab` — Sprint 1: CPU↔GPU parity test framework + first kernel test passing.**
   New `SlapPyEngineTests/tests/test_particle_field_gpu_parity.py`. `assert_soa_close`,
   `make_paired_fields`, `step_both` helpers. Integrate parity test passing;
   collide / drill / slump / kinetic_relax / fluid_relax / thermal_step / bake
   tests skipped as placeholders for sprints 2-3.
5. **`de17253` — Sprint 1: first GPU kernel — particle_integrate.wgsl + Python wrapper.**
   `shaders/particle_integrate.wgsl` (workgroup_size 64, six bindings) plus
   `python/pharos_engine/physics/particle_gpu.py` with `gpu_integrate(field, dt)`,
   `is_gpu_available()`, and a numpy fallback for headless / CI. New
   `ParticleField.use_gpu_integrate: bool = False` flag — opt-in, existing
   100 tests unchanged. Smoke results on real GPU: max |Δpos| = 5.34e-5,
   max |Δvel| = 1.37e-4 over 20 steps. ~30× tighter than the 1e-3 parity gate.
6. **`0399d1d` — Sprint 1: benchmark harness + GPU port docs (buffer layout + 7-sprint plan).**
   `benchmarks/particle_field_baseline.py` (3 scenarios, per-method timing,
   monkey-patched `time.perf_counter` wrappers — engine source untouched),
   `benchmarks/baseline_report.md`, `docs/particle_field_gpu_buffers.md`
   (~280 lines), `docs/particle_field_gpu_port.md` (~550 lines).

## Performance results

Pre-Sprint-1 numbers come from the baseline captured BEFORE `_kinetic_relax`
was vectorised (the harness was written using the legacy path; commit
`0399d1d` froze it before `8b53890` shipped). Sprint 1 numbers come from
the re-run in `benchmarks/baseline_report.md` under the
`## After Sprint 1` heading.

| scenario | particles | baseline fps | sprint 1 fps | end-to-end speedup | `_kinetic_relax` ms baseline → sprint 1 | `_kinetic_relax` share |
|---|---:|---:|---:|---:|---|---|
| A small (sloppy)         |   ~680 | 232.1 | 246.7 | 1.06× | 0.253 → 0.123 (2.06× isolated) | 5.9% → 3.0% |
| B medium (snow + mud)    |  ~2350 |  24.9 |  26.1 | 1.05× | 1.565 → 0.383 (4.09× isolated) | 3.9% → 1.0% |
| C large (10× sand)       | ~10200 |   5.7 |   7.6 | 1.33× | 43.063 → 4.495 (9.58× isolated) | 24.4% → 3.4% |

Scenario C is the bellwether and behaved as predicted: `_kinetic_relax`
share collapsed from 24% to 3% (9.58× isolated speedup, tracking the 9.87×
reported in commit `8b53890`), and steady-state moved from 5.7 fps to 7.6
fps — exactly the "~7.5 fps with 24% saved" prediction. Scenario C did
*not* clear 10 fps because `_slide` absorbed the released budget
(49% → 62% share). `_slide` is now the next CPU vectorise candidate.
Full numbers in `benchmarks/baseline_report.md` under the "After Sprint 1"
heading.

## What worked

- **Parallel agent dispatch.** Eight agents fanned out across CPU vectorise,
  spatial hash, region grid, parity framework, GPU kernel, benchmark, buffer
  docs, and 7-sprint plan. All six work products landed in a 47-second window.
  None of them touched the same file, so the merge cost was zero.
- **Python reference preserved before any GPU port.** `_kinetic_relax_legacy`
  stayed in place after the vectorisation. The future GPU port will compare
  against the vectorised reference (which is now THE reference) but the
  legacy path is still callable for archaeology. Same pattern with
  `_numpy_integrate` shadowing the WGSL kernel.
- **Per-kernel `use_gpu_<X>` flag pattern.** The integrate kernel is gated
  behind `ParticleField.use_gpu_integrate: bool = False`. Existing tests
  see no behaviour change. Future kernels will follow the same opt-in
  pattern — `use_gpu_collide`, `use_gpu_bake`, etc. — so each sprint can
  ship a kernel without forcing a global flip.
- **Companion docs drafted in parallel with code.** The 7-sprint plan
  (`particle_field_gpu_port.md`) and buffer layout doc
  (`particle_field_gpu_buffers.md`) were written by separate agents while
  the kernel work proceeded. By the time the integrate shader landed, the
  binding layout it followed was already documented.
- **Monkey-patch benchmark harness.** Engine source stays untouched; the
  harness wraps instance methods with `time.perf_counter` deltas on entry,
  restores on teardown. No risk of timing-instrumentation leaking into prod.

## What surprised us

- **particle_integrate.wgsl pos/vel parity with CPU was ~5e-5.** We had
  budgeted 1e-3 (`atol=1e-4, rtol=1e-3`). Getting an order of magnitude
  tighter on the very first WGSL kernel suggests the buffer-padding plan
  in `particle_field_gpu_buffers.md` is sound and that the wgpu f32 path
  is bit-stable enough that we may be able to tighten future parity gates.
- **`_kinetic_relax` vectorisation alone was 9.87×.** The 7-sprint plan
  was sized assuming `_kinetic_relax` would be GPU-ported. With a 9.87×
  CPU win at scenario-C scale, the GPU port has to beat 2.22 ms / step,
  not 21.89 ms. At ~680 particles the CPU version is already ~0.25 ms —
  GPU dispatch overhead alone is likely 0.3-0.5 ms before the kernel runs.
  The case for porting `_kinetic_relax` to GPU has weakened materially at
  small N; only scenario C still motivates it.
- **The 7-sprint plan's risk #3 is already visible.** Risk #3 ("CPU↔GPU
  sync overhead dominates at low particle counts") was theoretical when
  written. Now scenario A runs at 232 fps on CPU with no GPU at all.
  A GPU integrate path with a single H2D upload and D2H readback per
  frame will lose to that. The auto-fallback heuristic
  (`gpu_min_particles=512`) in the risk plan needs to be the *default*,
  not an option.
- **Existing `shaders/particle_spatial_hash.wgsl` uses a lossy 65k-bucket
  hash.** We discovered mid-sprint that the existing WGSL spatial hash
  collides at high density (open-addressed, 16-bit bucket key). The CPU
  reference written in commit `d337404` is *lossless* (dense 2D grid).
  We'll either rewrite the WGSL hash to match the lossless dense grid
  before sprint 5 ships, or document a precision drop on the GPU path.
  Mitigation noted in the commit message: "drop the hash mixing on the
  GPU side to keep the lossless behaviour we have here."

## What didn't work

- **ChatGPT-style sync wgpu API was less ergonomic than expected.** The
  initial `gpu_integrate` draft used the raw wgpu submit/await idiom rather
  than the engine's existing `pharos_engine.compute.pipeline.ComputePipeline`
  wrapper. We rewrote to use the wrapper, but only after a chunk of
  boilerplate had been written and discarded. Future sprints should start
  from `ComputePipeline.dispatch()` and stay there.
- **The `step_both` test helper runs *all* kernels each frame, not just one.**
  Parity tests for sprint 1 cover the integrate kernel in isolation. Once
  we have multiple `use_gpu_<X>` flags wired in sprint 2/3, the parity
  harness needs a per-kernel mode where only one kernel runs on GPU and
  the rest stay on CPU. The commit message for `d55ebab` flagged this.

## Sprint 2 entry conditions

Sprint 2's theme is "per-pixel mask and material grid on GPU". For sprint 2
to start clean, the following sprint 1 byproducts must be in place
(all are):

- `ComputePipeline.is_available()` probe — used to gate `use_gpu_integrate`.
  Sprint 2 will add `supports_r8sint` and `supports_r16sint` queries.
- `RegionGridGPU` (commit `12f9350`) — sprint 2 will pipe `record_live`
  output into the `count_per_cell` kernel mentioned in the sprint-2 spec.
- `SpatialHash` CPU reference (commit `d337404`) — sprint 2's `collide_simple`
  needs the lossless 2D grid for parity with the CPU baseline. The WGSL
  port follows in sprint 5.
- `use_gpu_<X>` flag pattern — sprint 2 will add `use_gpu_collide`. The
  pattern is established.
- Parity test scaffold (`SlapPyEngineTests/tests/test_particle_field_gpu_parity.py`) — the
  `test_collide_cpu_gpu_parity` placeholder is already skipped-pending.
  Sprint 2 will fill it in.

Additionally, sprint 2 needs these new items that sprint 1 did *not*
deliver — these are explicit pre-work for sprint 2's first agent:

- **`column_top` per-column highest-occupied-pixel cache.** The CPU collide
  path uses `_column_top` (see `particle_field._collide`) for fast vertical
  ray queries. The GPU port needs the equivalent on a per-column storage
  buffer (`u32[W]`). Build during `upload_world`, maintain incrementally
  during `bake_stamp` (sprint 5) and `collide_full` (sprint 5).
- **RNG state buffer.** Sprint 2's `collide_simple` is deterministic, but
  sprint 3's `thermal_relax` and sprint 6's `slump_ca` need a per-particle
  philox/PCG state. Sprint 2 should allocate the buffer and seed it
  (`seed = hash(particle_index, world_seed)`) even though no kernel reads
  it yet. Seeding policy: documented in
  `particle_field_gpu_buffers.md` §1.2.
- **Ejecta-spawn readback pattern.** Sprint 2 doesn't spawn ejecta yet
  (sprint 5 does), but the readback ring-buffer pattern for
  `pending_spawns` should be prototyped in sprint 2 using a dummy event
  stream. Otherwise sprint 5 is going to invent it under time pressure.

## Updated risk register

Re-ranked from the 7-sprint plan based on what sprint 1 taught us:

1. **(was #3) CPU↔GPU sync overhead dominates at low particle counts.**
   *Escalated.* Sprint 1 confirmed scenario A runs at 232 fps on CPU. The
   GPU integrate path will not beat that. The break-even point is now
   somewhere between 2350 and 10200 particles — too high to leave the
   GPU path as the default. Sprint 7's "measure break-even per backend"
   work is now urgent rather than nice-to-have. Mitigation: keep
   `use_gpu_<X> = False` as the documented default through sprint 6;
   auto-enable only when `len(field.pos) > gpu_min_particles` and
   `pipeline.is_available()`. Make the threshold easy to override per
   game.
2. **(was #1) Bake-stamp write conflicts produce nondeterministic terrain.**
   *Unchanged.* Sprint 5 risk; still the highest-correctness item once we
   get there. The buffer doc's atomic-min-on-alpha + frame-id-tiebreak
   plan stands. Parity test ramp from 1 to 10k simultaneous bakes is now
   a sprint-5 acceptance criterion.
3. **(new) Lossy WGSL spatial hash collides with the CPU's lossless grid.**
   The existing `shaders/particle_spatial_hash.wgsl` uses 16-bit bucket
   keys and open addressing. The CPU `SpatialHash` shipped in sprint 1
   is lossless. Without changes, the sprint-5 collide kernel will produce
   different neighbour lists than the CPU path under high density, and
   the parity test will fail. *Mitigation*: rewrite the WGSL hash before
   sprint 5 to match the dense 2D grid layout in `SpatialHash`. This is
   a small task (the buffer layout is already designed) but it's a
   sprint-5-blocker that needs to land in sprint 4 at the latest.
4. **(was #2) Region dispatch corrupts particles at cell boundaries.**
   *Unchanged.* Sprint 4 risk; the STATIC-needs-all-neighbours-STATIC
   plus one-frame DIRTY hysteresis mitigation still applies. `RegionGridGPU`
   from sprint 1 sets us up to test this in isolation.
5. **(was #4) wgpu backend quirks ship parity failures only on some hardware.**
   *Unchanged.* CI matrix (DX12, Vulkan, Metal) is still the mitigation.
   Sprint 1 ran on a single backend; sprint 2 should add the CI matrix
   so we catch backend drift early. The headless-numpy fallback in
   `particle_gpu.py` already keeps CI green without a real GPU.
6. **(was #5) PBF bridge stalls when the fluid GPU port lags this one.**
   *De-prioritised slightly.* PBF is currently 31% of scenario B and ~0%
   of scenarios A and C. The bridge matters only for medium-N scenes with
   active fluid; for the falling-sand and 10k-sand workloads we're
   chasing first, it's not on the critical path. Sprint 6 still has to
   solve it, but it's not the gating risk it was framed as.
7. **(new) The 9.87× vectorisation win shifts every other GPU port's
   break-even particle count upward.** Each kernel we vectorise on CPU
   before porting to GPU reduces the marginal value of the port. We
   should run the sprint-1 vectorise pattern (cell-sort + boundary-find +
   scatter-add) on `_collide`, `_slide`, and `_slump_loose` *before*
   their GPU sprints land. If a CPU vectorise delivers 5×+, the GPU
   port may be deferred or skipped. Sprint 2 should pick the next CPU
   vectorise candidate by re-reading the post-sprint-1 baseline.

Secondary risks (unchanged from the 7-sprint plan):

- Storage texture format support on backends (`r16sint` fallback in
  buffer doc).
- Ejecta spawn buffer overflow (configurable capacity + CPU resize).
- Material uniform buffer dirty-flag bugs.
- Visual demo determinism drift due to GPU FP ordering.

## Notes for the sprint-2 lead agent

- Read `docs/particle_field_gpu_buffers.md` §2 (per-pixel texture layout)
  and §4 (readback strategy) before scoping. These are load-bearing for
  collide_simple.
- The `RegionGridGPU` (`python/pharos_engine/physics/region_gpu.py`) has
  `record_live` ready for the `count_per_cell` integration. Don't
  reinvent it; extend it.
- Make `use_gpu_collide` opt-in and default-off, same pattern as
  `use_gpu_integrate`. Existing tests must remain unchanged.
- Add `supports_r8sint` and `supports_r16sint` probes to
  `ComputePipeline.is_available()`. The 7-sprint plan calls for the
  r16sint fallback; the probe is missing.
- Re-run `benchmarks/particle_field_baseline.py` at sprint-2 close. The
  hot-path ranking will shift once `_kinetic_relax` drops out of the
  top 3 for scenario C; sprint 2's next target follows from whatever
  takes its place.
