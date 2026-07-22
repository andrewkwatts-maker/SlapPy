# Tier 11 — GPU Compute Migration (deferred 2026-05-26)

**Status:** Deferred per user decision after Tiers 1-10 landed. The
engine hit 1176 fps fluid / 544 fps softbody end-to-end on CPU Rust;
shipping that. This document is a self-contained "how to do Tier 11
if we ever come back" reference.

## Why we'd come back

Re-open this doc when ONE of these is true:

1. **A real scene needs >5000 active physics bodies** and the CPU
   solver chokes. Today we don't have such a scene.
2. **Per-frame budget exceeded** on a target device. Today we have
   ~3 ms / frame end-to-end with ~13 ms headroom against 60Hz.
3. **A user-visible feature** explicitly needs GPU-resident physics
   buffers (e.g., realtime GI fed by the fluid density grid, or
   GPU-driven instancing of softbody silhouettes).

Don't re-open this just to chase more fps. The diminishing returns
are real and the complexity is non-trivial.

## What "Tier 11" actually is

Move the per-frame solver hot-paths from CPU Rust (current state) to
GPU compute shaders (WGSL via wgpu). Keep buffers GPU-resident across
substeps + iters so the per-frame readback is minimised. Optionally,
render directly from the compute output (no readback at all).

Three phases, listed in execution order.

---

## Phase 11.A — POC on PBF density iter (~1-2 days)

**Goal:** validate the dispatch-overhead-vs-throughput trade-off on
real hardware BEFORE committing further. One kernel only.

Why PBF density iter:
- Pure data-parallel per particle (no precision-sensitive scatter
  ordering like XPBD).
- Already proven Rust-idiomatic in `src/pbf_solver.rs::pbf_iter`.
- Small surface: pos + mass + i_idx + j_idx → density + delta_p.

### Steps

1. **Add wgpu compute pipeline scaffold.** wgpu is already in the
   workspace (used by the renderer for shader compilation). Wire a
   new `src/gpu_compute.rs` module that:
   - Creates a `wgpu::Device` + `wgpu::Queue` (offscreen, headless OK)
   - Owns GPU buffer handles keyed by `(name, byte_len)`
   - Provides `upload(name, &[u8])`, `download(name) -> Vec<u8>`,
     `dispatch(pipeline_name, workgroup_count)`
   - Caches `wgpu::ComputePipeline` per shader (mirror the lighting
     pipeline cache pattern in `gi/cascade.py`)

2. **Write the WGSL.** `shaders/pbf_density_iter.wgsl` with the
   same math as the Rust implementation:
   ```wgsl
   struct Params {
       n_particles: u32,
       h: f32, rho0: f32, relax: f32,
       eps: f32, density_floor: f32,
       k_corr: f32, n_corr: f32, dq_w: f32,
       _pad: f32,
   };
   @group(0) @binding(0) var<uniform> params : Params;
   @group(0) @binding(1) var<storage, read_write> pos     : array<vec2<f32>>;
   @group(0) @binding(2) var<storage, read>       mass    : array<f32>;
   @group(0) @binding(3) var<storage, read>       i_idx   : array<u32>;
   @group(0) @binding(4) var<storage, read>       j_idx   : array<u32>;
   @group(0) @binding(5) var<storage, read_write> density : array<f32>;
   ...
   ```
   Use 64-thread workgroups. Pair-wise compute is over `array<u32>`
   indices; scatter is via atomic adds or a serial reduce step.

3. **Wire `_HAS_NATIVE_GPU` switch** in `python/pharos_engine/fluid/solver.py`:
   ```python
   if _HAS_NATIVE_GPU and p.count > GPU_THRESHOLD:
       _core.pbf_iter_gpu(...)
   elif _HAS_NATIVE_PBF:
       _core.pbf_iter(...)  # CPU Rust
   else:
       # numpy fallback
   ```
   GPU_THRESHOLD probably ~500 particles — below that, dispatch
   overhead wins. Measure to confirm.

4. **Verify precision.** WGSL f32 IEEE-754 but the optimizer may
   reorder ops. `test_block_buries_in_sand` may need a tolerance
   bump on the GPU path — that's expected and documented.

5. **Measure:**
   - PBF iter @ 140 particles: CPU 0.39 ms vs GPU ??? (likely
     CPU faster due to dispatch overhead)
   - PBF iter @ 2000 particles: CPU ??? vs GPU ???
   - PBF iter @ 10000 particles: CPU 60+ ms vs GPU ??? (likely
     5-10× GPU win)
   - PCIe / unified-memory readback cost — measure roundtrip

   **Decision gate:** does the GPU win at the scene sizes we
   actually need? If yes, proceed to Phase 11.B. If no, stop here
   and revisit only when scene size grows.

### Acceptance for Phase 11.A
- Build: `maturin develop --release` clean
- `test_fluid_*` all pass (with a documented tolerance bump on the
  precision test if needed)
- Measured GPU vs CPU on three scene sizes
- One-page report comparing GPU vs CPU breakeven point

---

## Phase 11.B — Full solver port (~3-5 days, only if 11.A wins)

**Goal:** every solver kernel runs on GPU when the scene is big enough.

### Steps

1. Port each kernel one at a time:
   - `build_neighbour_table` → WGSL (spatial hash + 9-cell gather)
   - `pbf_iter` → already done in 11.A
   - `friction_pass_rs` → WGSL (precision-sensitive — scatter via
     atomic adds OR serial reduce in compute)
   - `thermal_step_rs` → WGSL (precision-sensitive — same)
   - `project_distance_constraints` → WGSL (XPBD beams — same
     precision concern; expect tolerance bumps)
   - `apply_plasticity` → WGSL
   - `mark_breaks` → WGSL
   - `build_contact_pairs` → WGSL (broadphase — heavy parallel)
   - `project_node_beam_contacts` + `project_node_node_pairs` → WGSL
     (precision-sensitive scatter)

2. **Keep buffers GPU-resident** across all kernels within a single
   `pharos_engine_step` / `pbf_step_full` call. Upload pos/mass/idx
   ONCE per frame. Readback ONCE per frame (or never — see 11.C).

3. **Persistent storage buffers** for all SoA arrays. Resize lazily
   when n_nodes / n_particles changes.

4. **Switch the existing `pharos_engine_step` and `pbf_step_full`**
   to dispatch the GPU pipelines when `_HAS_NATIVE_GPU` is True and
   N exceeds threshold. Keep the CPU Rust path for small N.

5. **Per-kernel precision contract:** document expected tolerance
   bumps for the GPU path. The CPU path remains bit-exact; the GPU
   path is "physically equivalent within ε".

### Risks to mitigate during 11.B
- **WGSL atomic adds on f32** aren't supported on all backends.
  May need integer-quantised accumulators or per-thread local
  accumulation + workgroup reduce.
- **Pair iteration order** is non-deterministic across GPU
  threads — expect drift on stacked-block contact resolution.
- **Cross-platform GPU testing.** Run on at least Vulkan,
  D3D12, Metal. wgpu abstracts but each has subtle differences
  in compute capabilities.

---

## Phase 11.C — Render integration (~1-2 days, optional)

**Goal:** render directly from GPU-resident physics buffers — zero
readback.

Currently `src/raster.rs` is CPU SIMD reading from numpy arrays. With
GPU-resident buffers we have two choices:

### Option C.1 — Keep CPU raster, read back each frame
- Simpler. Per-frame readback ~50-200 µs on typical PCIe.
- Existing raster.rs untouched.
- Loses some of the GPU win.

### Option C.2 — Port raster to WGSL too
- Render directly from the same buffers the compute pipeline wrote.
- Zero readback per frame.
- Pure AAA path.
- Significantly more work — every raster kernel needs a WGSL
  twin (`rasterize_lines_gpu`, `rasterize_circles_gpu`,
  `box_blur_gpu`, `post_process_gpu`, `rasterize_textured_triangles_gpu`).

**Recommendation when revisiting:** start with C.1. Only commit C.2
if profile shows readback is a real bottleneck.

---

## Build / dependency impact

- `wgpu = "..."` already in the workspace. Possibly need to enable
  the `compute` feature explicitly.
- `pollster = "..."` for sync `block_on` if running compute outside
  the Python event loop.
- No new big deps.

## Files to touch when Tier 11 starts

New:
- `src/gpu_compute.rs` — device + buffer management
- `src/pbf_gpu.rs` (Phase 11.A); later expanded to softbody_gpu.rs
- `shaders/pbf_density_iter.wgsl` etc.
- `python/tests/test_gpu_kernel_precision.py` — regression on
  CPU-vs-GPU diff

Modified:
- `src/lib.rs` — register new modules
- `python/pharos_engine/fluid/solver.py` — `_HAS_NATIVE_GPU` switch
- `python/pharos_engine/softbody/solver.py` — same
- `Cargo.toml` — wgpu features

## Pre-Tier-11 baseline (snapshot 2026-05-26)

For comparing later:
```
softbody step (5x6x6):  0.91 ms
softbody step (20x8x8): 7.53 ms
pbf step (140 part):    0.39 ms
pbf step (600 part):    2.17 ms
softbody render basic:  ~2.0 ms
fluid render basic:     0.53 ms
fluid render watery:    2.30 ms

softbody end-to-end:    1.84 ms (544 fps)
fluid end-to-end basic: 0.85 ms (1176 fps)
fluid end-to-end watery: 2.62 ms (382 fps)
```

## Pre-commit checklist (when restarting Tier 11)

- [ ] Identify the scene that needs >5000 bodies (or other trigger)
- [ ] Re-read this doc
- [ ] Re-read `memory/project_architecture_pattern.md`
- [ ] Re-read `docs/tier_11_gpu_compute_discussion.md` (the original
      trade-off analysis)
- [ ] Start with Phase 11.A POC; stop if it doesn't win at our N
- [ ] Document precision tolerances explicitly for the GPU path
- [ ] Add CI to run cross-platform GPU tests before merging

---

**Decision recorded 2026-05-26:** chose Option 1 (ship now, defer
Tier 11). Current CPU Rust state ships as `pharos-engine v1.0`-ish
on PyPI; Tier 11 reopens only when scene demands or feature explicitly
requires GPU-resident buffers.
