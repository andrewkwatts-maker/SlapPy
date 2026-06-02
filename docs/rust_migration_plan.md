# Rust migration plan — path to 1000 fps

This document lays out the staged Rust-backed migration of the
SlapPyEngine hot paths. The renderer kernels (`src/raster.rs`) already
landed in May 2026, giving render-alone speeds of 275–386 fps. To hit
true 1000-fps end-to-end (1 ms total budget) the **step** side of every
subsystem must follow the same path.

Each step is intentionally small: one Rust module, one Python wrapper,
one acceptance test, one before/after timing measurement. Steps ship
independently; each one is reversible if precision regressions show up.

## Current baseline (post-renderer migration v2, 2026-05-26)

```
softbody step  (5 lattices 6×6, 780 beams)   :  9.69 ms
pbf step       (140 water particles)         :  3.61 ms
softbody render (320×240, full Rust pipe)    :  2.38 ms  →  420 fps
fluid render    (320×240, vectorised splat)  :  2.59 ms  →  386 fps
```

End-to-end:
- Softbody scene (3 lattices 4×4): 8.6 ms / 116 fps (step dominates)
- Fluid scene:                     5.6 ms / 178 fps (step dominates)

`src/raster.rs` shipped: `rasterize_lines`, `rasterize_circles`,
`box_blur_rgb`, `post_process_rgb`, `alpha_composite_rgb` (the
last one supersedes the original Step 6 scope).

## Target

End-to-end **1000 fps = 1 ms total**:
- Step:    0.5 ms (10× reduction softbody, 7× reduction PBF)
- Render:  0.5 ms (1.5× from current; mostly compositing overhead)

This is achievable with Rust SIMD kernels at the same algorithm.
Stretch: GPU compute path would push to 5000+ fps but is out of scope.

---

## Step 1 — Softbody XPBD distance + plasticity + break

**Why first:** `_project_distance_constraints` runs `iters × substeps`
= 32 times per frame on every beam. Combined with plasticity and
mark_breaks (which also iterate beams) it's ~30% of softbody step time.

**Files**
- New: `src/softbody_solver.rs`
- Modify: `src/lib.rs` (`mod softbody_solver; softbody_solver::register(m)?;`)
- Modify: `python/slappyengine/softbody/solver.py` —
  `_project_distance_constraints`, `_apply_plasticity`, `_mark_breaks`
  get `HAS_NATIVE` guards.

**Rust surface (proposed)**
```rust
#[pyfunction] fn project_distance_constraints(
    pos_xy: &PyAny,         // (N, 2) f32 read-write numpy
    inv_mass: &PyAny,       // (N,) f32 read
    node_a: &PyAny,         // (B,) u32
    node_b: &PyAny,         // (B,) u32
    rest_length: &PyAny,    // (B,) f32
    stiffness: &PyAny,      // (B,) f32
    broken: &PyAny,         // (B,) bool
    node_relax: &PyAny,     // (N,) f32
    sub_dt: f32,
    eps: f32,
) -> PyResult<()>

#[pyfunction] fn apply_plasticity(...) -> PyResult<()>
#[pyfunction] fn mark_breaks(...) -> PyResult<()>
```

**Risk:** medium. XPBD precision matters for stacked-block contact
resolution. The bincount substitution in pure Python REGRESSED
`test_block_on_block_stacks` because float-summation order differed.
Use the same iterate-and-add order as the original `np.add.at`:
beam-major iteration, write into node positions one beam at a time.

**Acceptance**
- `python/tests/test_softbody_*` all pass (41 tests)
- `SlapPyEngineTests/tests/visual/test_vis_softbody_vehicle.py` passes
- `test_block_on_block_stacks` penetration < 0.008
- `step()` time on the 5×6×6 baseline scene drops by ≥ 25%

**Expected:** 9.69 → ~7 ms (28% speedup)

---

## Step 2 — Softbody broadphase (`build_contact_pairs`)

**Why second:** still the biggest single cost in softbody step (~30%
of total even after the batched-numpy pass landed). Pure indexing
work — no float precision concerns.

**Files**
- Add to: `src/softbody_solver.rs` — `build_contact_pairs` function
- Modify: `python/slappyengine/softbody/collision.py`

**Rust surface**
```rust
#[pyfunction] fn build_contact_pairs(
    node_pos: &PyAny,       // (N, 2) f32
    body_id_n: &PyAny,      // (N,) u32
    beam_a: &PyAny,         // (B,) u32
    beam_b: &PyAny,         // (B,) u32
    beam_body: &PyAny,      // (B,) u32
    beam_rest: &PyAny,      // (B,) f32
    broken: &PyAny,         // (B,) bool
    thickness: f32,
    cell_factor: f32,
) -> PyResult<(PyObject, PyObject, PyObject, PyObject)> // P, B, NN_A, NN_B
```

Internally: build the spatial hash (cell key per node), sort by key,
do the 9-cell neighbour gather, dedupe via hash-set rather than the
`np.unique` Python call. Rust's `ahash` or `rustc_hash` makes this very
fast.

**Risk:** low — broadphase outputs candidate pairs that the XPBD
constraint solver then projects. Exact order doesn't matter as long
as the mask filters produce the same SET of pairs.

**Acceptance**
- Contact tests pass
- `build_contact_pairs` time on baseline scene drops by ≥ 50%

**Expected:** softbody step drops another 1.5-2 ms.

---

## Step 3 — Softbody contact projection (`project_contact_pairs`)

**Why third:** the XPBD projection that consumes the broadphase
output. ~15% of step time, runs `iters` times per substep.

**Files**
- Add to: `src/softbody_solver.rs` — `project_contact_pairs` function
- Modify: `python/slappyengine/softbody/collision.py`

**Rust surface**
```rust
#[pyfunction] fn project_contact_pairs(
    pos_xy: &PyAny,         // (N, 2) f32 read-write
    inv_mass: &PyAny,
    body_id: &PyAny,
    pair_node: &PyAny,      // (P,) u32  node-beam candidate nodes
    pair_beam: &PyAny,      // (P,) u32  node-beam candidate beams
    beam_a: &PyAny,
    beam_b: &PyAny,
    nn_a: &PyAny,           // (Q,) u32  node-node candidate As
    nn_b: &PyAny,           // (Q,) u32  node-node candidate Bs
    thickness: f32,
    stiffness: f32,
    sub_dt: f32,
    eps: f32,
) -> PyResult<()>
```

**Risk:** high — same precision concern as Step 1. Preserve the exact
projection order (process node-beam pairs first, then node-node).

**Acceptance**
- All contact + vehicle + render tests pass
- `test_block_on_block_stacks` penetration < 0.008
- Softbody step on baseline scene drops by ≥ 15%

**Expected:** softbody step drops another 1-1.5 ms.

---

## Step 4 — PBF neighbour table + density iteration

**Why fourth:** PBF's inner iteration loop runs `iters × substeps` =
32 times per frame on every particle pair. The `_build_neighbour_table`
+ the density / gradient / lambda / delta_p chain.

**Files**
- New: `src/pbf_solver.rs`
- Modify: `src/lib.rs`
- Modify: `python/slappyengine/fluid/solver.py`

**Rust surface**
```rust
#[pyfunction] fn build_neighbour_table(
    pos: &PyAny,            // (N, 2) f32
    h: f32,
) -> PyResult<(PyObject, PyObject)>   // i_idx, j_idx (u32)

#[pyfunction] fn pbf_iter(
    pos_xy: &PyAny,         // (N, 2) f32 read-write
    mass: &PyAny,
    i_idx: &PyAny,
    j_idx: &PyAny,
    h: f32, rho0: f32, relax: f32,
    eps: f32, density_floor: f32,
    cohesion_on: bool, k_corr: f32, n_corr: f32, dq_w: f32,
) -> PyResult<()>
```

`pbf_iter` does ONE iteration of the density-constraint projection
(was the body of the inner `for _it in range(iters)` loop).

**Risk:** medium — PBF tolerated bincount precision changes earlier
this session, so the float-order isn't as fragile as softbody. But
positions are persistent.

**Acceptance**
- All 168 fluid tests pass
- `pbf_step` on 140-particle scene drops by ≥ 40%

**Expected:** 3.61 → ~2 ms (45% speedup)

---

## Step 5 — PBF friction + thermal

**Why fifth:** the remaining PBF cost after Step 4. `friction_pass`
runs once per substep; `thermal_step` runs once per substep.

**Files**
- Add to: `src/pbf_solver.rs`
- Modify: `python/slappyengine/fluid/solver.py` + `thermal_step.py`

**Rust surface**
```rust
#[pyfunction] fn friction_pass_rs(...) -> PyResult<()>
#[pyfunction] fn thermal_step_rs(...) -> PyResult<()>
```

**Risk:** low — these are simpler than the iteration core.

**Acceptance**
- `test_fluid_granular.py` passes (friction)
- `test_fluid_thermal.py` passes (lava cooling, ice melting)
- PBF step drops another 0.5-1 ms

---

## Step 6 — Skin-fill compositing  ✅ DONE

Shipped 2026-05-26 alongside the initial raster.rs work — agent extended
the scope to include `alpha_composite_rgb` and wired it into
`_draw_skin_fills`. PIL still draws the polygons to a uint8 RGBA buffer
but the per-frame composite is now a single Rust SIMD call. Skin-fill
cost dropped from ~1.5 ms → ~0.3 ms.

---

## Step 7 — Final polish

After Steps 1-6 ship:
- Cache per-beam material lookups (LUT keyed by body_id × layer)
- Move `_per_beam_material` out of the hot path (rebuild only when
  material registry or body assignments change)
- Pre-compute the disk-pixel offsets at config-load time (currently
  rebuilt each `_draw_nodes` call)

**Expected end state:**
```
softbody step  :  1.5–2.0 ms  (~7× faster than today's 9.69 ms)
pbf step       :  0.8–1.2 ms  (~3-4× faster than today's 3.61 ms)
softbody render:  1.0–1.5 ms  (~2.5-3× faster than today's 3.64 ms)
fluid render   :  0.8–1.2 ms  (~2-3× faster than today's 2.59 ms)
```

End-to-end:
- Softbody: ~3 ms = **~333 fps**
- Fluid:    ~2 ms = **~500 fps**

True 1000 fps end-to-end requires moving to GPU compute (wgpu); that's
a separate roadmap.

---

## Build + dev workflow

Each step:
1. Write the Rust module under `src/`.
2. Register in `src/lib.rs`.
3. Run `maturin develop --release` to rebuild the extension in place.
4. Add the `HAS_NATIVE` switch to the Python wrapper.
5. Run the acceptance tests.
6. Measure before/after with the standard cProfile snippet.
7. Commit. Move to next step.

The Rust crate already has `pyo3`, `bytemuck`, `rayon`, and `numpy`
in `Cargo.toml`. No new deps needed for Steps 1-6.

## Risk register

- **Float-summation order regressions** — XPBD position updates are
  sensitive. Process beams in array order, never re-order via
  hash-set or unordered_map. Add a regression test on the FIRST step
  that drops a vehicle, runs 60 frames, and checks the chassis x
  position to 1e-3 tolerance.
- **maturin build failure on Windows** — the existing crate builds
  cleanly per the recent raster work. If a step fails to build,
  isolate by feature-gating the new module.
- **API drift** — keep all Rust → numpy plumbing via `bytemuck` +
  `bytearray` (the pattern raster.rs already uses). Don't introduce
  pyo3 numpy-extension dependencies mid-stream.
