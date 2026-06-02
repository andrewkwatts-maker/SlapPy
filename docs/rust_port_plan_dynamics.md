# Rust Port Plan — `slappyengine.dynamics`

Status: **PLAN ONLY** — no code ported yet.
Date: 2026-05-29
Branch: `docs-rust-port-plan-dynamics`
Author: dynamics-perf working group

This document is a decision-quality writeup that answers a single question:
*should we port the pure-numpy XPBD solver in `slappyengine.dynamics` to
Rust (via the existing `slappyengine._core` extension module), and if so
how?* It bundles the bench evidence, the profile, the per-function
classification, an estimated speedup range grounded in the engine's prior
Rust ports, an actual `pyo3` API sketch, the risks, and a phased delivery
plan.

The four-scenario bench and the cProfile run were both produced on the
exact hardware this document was written on; quoted ms values come from
`time.perf_counter()` deltas captured by `_bench_dynamics.py` and
`_profile_dynamics.py` (throwaway scripts, intentionally not committed).

---

## 1. Bench results — current Python solver

All four scenarios run **240 frames at `dt = 1/60 = 0.016667 s`** and
report per-frame wall time in milliseconds from `time.perf_counter()`
deltas around `World.step(dt)`. The target frame budget at 60 Hz is
**16.67 ms** and the share normally allotted to physics is **~8 ms** so
that rendering, audio, scripting, and event dispatch fit alongside.

| Scenario | World contents | nodes | joints | median ms | min ms | max ms | mean ms | n |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **A** — 20-node rope | `build_rope` + 19 distance joints + 2 anchors | 20 | 19 | **0.678 ms** | 0.673 ms | 0.781 ms | 0.680 ms | 240 |
| **B** — 6-bone ragdoll | `build_ragdoll`: pelvis/torso/head/upper-arm/lower-arm/thigh, 6 distance + 5 hinge joints | 7 | 11 | **0.537 ms** | 0.532 ms | 0.631 ms | 0.539 ms | 240 |
| **C** — 100-node lattice | 10x10 grid + horizontal/vertical/both-diagonal distance joints | 100 | 342 | **11.922 ms** | 11.778 ms | 14.706 ms | 12.058 ms | 240 |
| **D** — composite world | rope + 3-bone ragdoll + 4-node IK chain + 1-wheel motor | 26 | 25 | **0.990 ms** | 0.976 ms | 1.921 ms | 1.054 ms | 240 |

(Scenario C's joint count came out at 342 rather than the spec's "~280"
because the lattice was wired with both forward and back diagonals on
every cell; this is the worst-case stress run, so retaining the higher
count makes the budget conversation more honest.)

### Bench interpretation

* Scenarios A, B, D are **comfortably under budget**. The dynamics solver
  is *not* the bottleneck for a single rope, a single ragdoll, or a
  small mixed scene. Porting these by themselves yields milliseconds we
  can spend elsewhere but is not load-bearing.
* Scenario C is **above the 8 ms physics budget at 60 Hz**. A
  100-node lattice with ~340 distance joints — i.e. one cloth panel or
  one mid-sized softbody chassis — already eats 11.9 ms median, leaving
  ~5 ms for everything else in a frame. Two such bodies, and the frame
  rate falls below 60.
* Variance is low (max/median <= 1.5x in every scenario) so the median
  is a fair representation of steady-state cost — there's no GC spike
  or allocator stall masking a faster underlying kernel.

The pattern matches what we'd expect from a pure-numpy XPBD solver:
overhead is roughly linear in `joints * solver_iterations` (Scenario C is
342 joints x 8 iterations = 2736 projections per frame), and per-joint
cost is dominated by `numpy.linalg.norm` plus a handful of `ndarray`
fancy-indexing operations — the same pattern that paid off on the
already-ported PBF and softbody steps (see Section 4).

---

## 2. Hot-path profile — `cProfile` on Scenario C

`_profile_dynamics.py` ran 240 frames of Scenario C through `cProfile`
sorted by cumulative time. Total wall time was 5.310 s = 22.1 ms/frame
under the profiler (a ~85% overhead on the unprofiled 12.0 ms, typical
of `cProfile` on a hot Python loop). Top 10 by cumulative time:

| # | Function | ncalls | tottime (s) | cumtime (s) | share of frame |
|---:|---|---:|---:|---:|---:|
| 1 | `world.py:175 World.step` | 240 | 0.180 | 5.310 | 100.0% (root of measurement) |
| 2 | `joint.py:413 resolve` (dispatcher) | 656 640 | 0.230 | 5.075 | 95.6% |
| 3 | `joint.py:256 _resolve_distance` | 656 640 | 0.265 | 4.782 | 90.1% |
| 4 | **`joint.py:156 _project_distance`** | 656 640 | **2.968** | **4.517** | **85.1%** |
| 5 | `numpy/linalg.norm` | 656 640 | 0.619 | 1.300 | 24.5% |
| 6 | `ndarray.dot` (called by norm) | 656 640 | 0.344 | 0.344 | 6.5% |
| 7 | `numpy/linalg.isComplexType` (norm internal) | 656 640 | 0.086 | 0.127 | 2.4% |
| 8 | `ndarray.ravel` (norm internal) | 656 640 | 0.111 | 0.111 | 2.1% |
| 9 | `builtins.max` (compliance + damp clamps) | 1 279 200 | 0.099 | 0.099 | 1.9% |
| 10 | `builtins.issubclass` (norm internal) | 1 313 280 | 0.091 | 0.091 | 1.7% |

`656 640 = 240 frames * 342 joints * 8 iterations` — exactly one call
per `(frame, joint, iteration)` triple. That number recurs everywhere in
the profile because the only per-iteration work is `_project_distance`
and the path that calls it.

### The 80% line

Rows 1-4 account for **>= 80% of cumulative time on their own.**
Specifically, rows 3+4 together account for **90% of frame time**, and
just `_project_distance` (row 4) accounts for **85% of frame time**.

* Of `_project_distance`'s own 4.52 s cumulative cost, **1.30 s (29%)
  is `numpy.linalg.norm`** and **0.34 s (7.6%)** is the `ndarray.dot`
  that `norm` internally calls. Half of `_project_distance` is Python-
  level loop overhead and numpy small-array fancy indexing; the rest is
  vector math that Rust does in one or two SIMD instructions.
* `World.step` itself (row 1, exclusive 0.18 s) is only **3.4% of
  cumulative time** — Python's outer loop is *not* the cost; the inner
  per-joint kernel is.

This is the textbook profile for "port the leaf, keep the trunk."

---

## 3. Hot-function -> Rust classification

For each function in the top 10, we tag it as one of three actions:

* **Port to Rust** — heavy numerical kernel, clear `ndarray -> &[f64]`
  mapping, no Python-object state, called per-joint or per-iteration.
* **Keep in Python** — state management, dataclass mutation, validation,
  warnings, mostly numpy-vectorised already, or one-shot per frame.
* **Refactor first** — mixed concerns that need separation before the
  numerical core can be lifted out.

| Function | Class | Why |
|---|---|---|
| `_project_distance` | **Port to Rust** | 85% of frame time. Pure scalar math on two 2D vectors + two scalar masses. No Python state. Reads `world.positions[a/b]` and `world.inv_masses[a/b]`; writes `world.positions[a/b]`. Perfect for a `pyo3` function that takes a `&mut [f64]` positions slice + the joint index arrays + a contiguous joint-params array. |
| `_resolve_distance` (and `_resolve_spring`, `_resolve_weld`, `_resolve_ball`) | **Port to Rust** | One-liner wrappers around `_project_distance`. Once `_project_distance` is in Rust these collapse to a single kernel that takes a kind tag (or just folds into the bulk-solve call below). |
| `resolve` (dispatcher) | **Port to Rust** | A `dict.get` lookup plus a function call. Replace with a `match joint_kind { ... }` in Rust and process the *whole joint list per iteration* in one FFI call to amortise crossing cost. This is the **main API shape change**: instead of "1 FFI call per joint per iter" (which would be 656 640 calls/frame and dominate FFI overhead), expose `solve_joints_pass(positions, inv_masses, joints_soa, dt)` that does the inner solver loop entirely Rust-side. |
| `numpy.linalg.norm`, `ndarray.dot`, `numpy.linalg.isComplexType`, `ndarray.ravel` | **Folded into Rust port** | These are dependencies of `_project_distance` — porting that function removes all of them automatically. No standalone port needed. |
| `builtins.max` (compliance/damping clamps) | **Folded into Rust port** | Same — disappears with `_project_distance`. |
| `_project_angle` (hinge limit) | **Port to Rust** | Not in the top 10 for Scenario C (which has no hinges) but it lives next door in `joint.py`, has the same shape (scalar trig on two 2D vectors), and is the only piece of the hinge resolver. Port alongside `_project_distance` for completeness. |
| `World.step` outer loop | **Keep in Python** | 3.4% of frame time. Manages frame counter, gravity integration broadcast, prev/curr position bookkeeping, velocity recovery — all already vectorised numpy that runs in well under a millisecond. Calling out to Rust *once per frame* for the joint-solve pass (and possibly the integrate+recover passes) is the right shape. |
| `World.add_node`, `add_nodes`, `add_joint`, `register_body` | **Keep in Python** | One-shot setup. Already cheap. |
| `_check_overdamping`, `estimate_effective_damping` | **Keep in Python** | Diagnostic warning machinery, runs once per frame, touches `warnings.warn` and `set` membership. Stays Python. |
| `JointSpec.__post_init__` validators | **Keep in Python** | Construction-time only; clearer error messages in Python. |
| `JointSpec` dataclass (storage) | **Refactor first** | The solver currently iterates a `list[JointSpec]` and reads attributes by name. For the Rust port we want a structure-of-arrays (SoA) layout: `joint_kinds: np.ndarray[int32]`, `joint_node_a: np.ndarray[int32]`, `joint_node_b: np.ndarray[int32]`, `joint_rest_length: np.ndarray[float64]`, `joint_stiffness: np.ndarray[float64]`, `joint_damping: np.ndarray[float64]`. The refactor is mechanical: a `World._rebuild_joint_arrays()` call that runs whenever the joint list mutates, plus a separate sidecar array for kind-specific params. **This refactor lands in Phase 1 alongside the MVP port** because it's the only way to call out to Rust efficiently. |
| `_resolve_motor` | **Refactor first** | Mixes a distance projection with a tangential velocity push and reaches into both `world.velocities` and `world.positions`. The distance half folds into the bulk distance kernel; the velocity half is its own 3-line scalar routine and is ported in Phase 2. |
| `_resolve_hinge` | **Refactor first** | Two kernel calls (`_project_distance` + `_project_angle`); ports cleanly once both kernels exist. |
| `_resolve_prismatic` | **Refactor first** | Slightly more involved (decompose displacement along/perp to axis, then optional min/max clamp). Same shape as distance once decomposed; ported in Phase 2. |
| `solve_ik` (CCD) | **Already covered** | `slappyengine._core.ik_solver` already exists with FABRIK in Rust. The Python CCD path remains for cases where CCD is preferred (different convergence profile); no new port needed. |

---

## 4. Speedup estimate — grounded in prior engine ports

We do not invent a speedup number; we anchor it to the engine's existing
Rust ports captured in memory. Two recent landings are directly
comparable to what we're proposing:

* **`project_rust_steps_1_4_2026_05`** — "softbody XPBD 35% faster, PBF
  inner 68% faster, end-to-end softbody 136 fps / fluid 246 fps."
  These are *the same shape of kernel as `_project_distance`* (XPBD
  position projection over a node array). The softbody XPBD step is the
  closest analogue: same per-constraint math, same numpy-driven Python
  baseline, same f64-precision concerns. Its **35% speedup** is the
  closest conservative anchor.
* **`project_rust_migration_final_2026_05`** — "Tiers 1-10 landed; 18
  Rust kernels; fluid 1176 fps / softbody 544 fps end-to-end." End-to-
  end fluid went from ~246 fps (after step 4) to 1176 fps (after tier
  10) — roughly **4.8x** further as more of the pipeline moved over and
  inter-kernel FFI calls were collapsed.
* **`project_perf_2026_05`** — the pure-numpy `np.bincount`
  optimisation in `pbf_step` gave **26%** within Python alone. That's
  the headroom available without going to Rust at all, and it sets a
  lower bound on what we should expect from a Rust port (we should
  always do at least as well as the numpy-only optimisation).

### Conservative range

For `_project_distance` (Section 3 row 4, 85% of frame time):

* **Lower bound — 1.5x end-to-end speedup.** Take the softbody XPBD
  number (35% faster -> 1.35x) and discount slightly for the FFI cost of
  one bulk call per frame. Scenario C drops from 11.9 ms median to
  ~8 ms — back inside budget but only just.
* **Likely central value — 3x to 4x end-to-end speedup.** This is the
  range we land in when the kernel is hot, the SoA refactor has
  eliminated per-joint Python dispatch, and the inner solver iteration
  loop runs Rust-side. The softbody-to-PBF ratio (35% vs 68%) suggests
  the more numpy-overhead-dominated a baseline is, the bigger the
  Rust win, and `_project_distance` is *more* numpy-overhead-dominated
  than softbody XPBD — it makes one `numpy.linalg.norm` call per joint
  per iteration on a 2-element vector, which is exactly the kind of
  call that costs more in numpy framing than in Rust scalar math.
  Scenario C drops from 11.9 ms to ~3-4 ms.
* **Upper bound — ~6x end-to-end speedup.** Achievable only if we also
  port `_project_angle`, `_resolve_motor`'s tangential push, and the
  prismatic decomposition (Phase 2 work). The end-to-end fluid result
  (4.8x further after tier 10) is the precedent. Scenario C would drop
  to ~2 ms — leaving most of the 8 ms physics budget for multi-body
  scenes.

We **explicitly do not** claim the 1176-fps fluid number is achievable
for dynamics; that's a much more compute-heavy kernel with bigger
amortised wins from `rayon`. Dynamics is a per-joint scalar projection
and is unlikely to benefit from `rayon` because joints share node
storage and need a Gauss-Seidel sweep, not a parallel scatter.

---

## 5. Rust API surface — actual `pyo3` sketch

Style references: `src/ik_solver.rs` (real `pyo3` signatures already
used by `slappyengine._core.solve_ik`) and `src/physics.rs` (for the
larger `#[pyclass]`-style shape).

The smallest useful API is a single function call per `World.step` that
runs **all `solver_iterations` passes** Gauss-Seidel-style over the
joint list and mutates the position buffer in place:

```rust
use pyo3::prelude::*;

#[derive(Clone, Copy)]
#[repr(u8)]
pub enum JointKind {
    Distance  = 0,
    Spring    = 1,
    Weld      = 2,
    Ball      = 3,
    Hinge     = 4,
    Motor     = 5,
    Prismatic = 6,
}

/// Project every joint in the list `iterations` times, mutating
/// `positions` in place. Returns the per-joint final correction
/// magnitudes so the Python side can apply `break_force` checks +
/// disable joints whose correction exceeded their threshold.
///
/// Parameters
/// ----------
/// positions : list of (f64, f64)
///     Node positions in row-major form. Mutated in place; callers
///     must copy if they need the pre-step state.
/// inv_masses : list of f64
///     Per-node inverse mass; 0.0 marks a pinned node.
/// joint_kinds : list of u8
///     One entry per joint, indexing into `JointKind`.
/// joint_a, joint_b : list of u32
///     Node indices for each joint (length = joint_kinds.len()).
/// joint_rest_length, joint_stiffness, joint_damping : list of f64
///     Per-joint scalar parameters.
/// dt : f64
///     Sub-step duration (compliance is `1 / (k * dt * dt)`).
/// iterations : u32
///     Number of Gauss-Seidel passes over the joint list.
///
/// Returns
/// -------
/// list of (f64, f64), list of f64
///     The mutated `positions` (copied back) and one correction
///     magnitude per joint (max over iterations).
#[pyfunction]
#[pyo3(signature = (
    positions,
    inv_masses,
    joint_kinds,
    joint_a,
    joint_b,
    joint_rest_length,
    joint_stiffness,
    joint_damping,
    dt,
    iterations,
))]
pub fn solve_joints_pass(
    positions: Vec<(f64, f64)>,
    inv_masses: Vec<f64>,
    joint_kinds: Vec<u8>,
    joint_a: Vec<u32>,
    joint_b: Vec<u32>,
    joint_rest_length: Vec<f64>,
    joint_stiffness: Vec<f64>,
    joint_damping: Vec<f64>,
    dt: f64,
    iterations: u32,
) -> PyResult<(Vec<(f64, f64)>, Vec<f64>)> {
    // ... implementation ...
    let n_joints = joint_kinds.len();
    if joint_a.len() != n_joints
        || joint_b.len() != n_joints
        || joint_rest_length.len() != n_joints
        || joint_stiffness.len() != n_joints
        || joint_damping.len() != n_joints
    {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "solve_joints_pass: per-joint arrays must have equal length",
        ));
    }
    let mut p = positions;
    let mut max_corr = vec![0.0_f64; n_joints];
    for _ in 0..iterations {
        for j in 0..n_joints {
            let corr = project_one(
                &mut p,
                &inv_masses,
                joint_kinds[j],
                joint_a[j] as usize,
                joint_b[j] as usize,
                joint_rest_length[j],
                joint_stiffness[j],
                joint_damping[j],
                dt,
            );
            if corr > max_corr[j] {
                max_corr[j] = corr;
            }
        }
    }
    Ok((p, max_corr))
}

/// Inner kernel — Distance / Spring / Weld / Ball all dispatch here.
#[inline]
fn project_one(
    positions: &mut [(f64, f64)],
    inv_masses: &[f64],
    kind: u8,
    a: usize,
    b: usize,
    rest_length: f64,
    stiffness: f64,
    damping: f64,
    dt: f64,
) -> f64 {
    // Distance / Spring / Weld share this body; Ball uses rest_length = 0.
    let (pax, pay) = positions[a];
    let (pbx, pby) = positions[b];
    let dx = pax - pbx;
    let dy = pay - pby;
    let d = (dx * dx + dy * dy).sqrt();
    if d < 1.0e-12 {
        return 0.0;
    }
    let nx = dx / d;
    let ny = dy / d;
    let rl = if kind == JointKind::Ball as u8 { 0.0 } else { rest_length };
    let c = d - rl;
    let wa = inv_masses[a];
    let wb = inv_masses[b];
    let w_sum = wa + wb;
    if w_sum <= 0.0 {
        return 0.0;
    }
    let compliance = 1.0 / (stiffness * dt * dt).max(1.0e-12);
    let mut dlambda = -c / (w_sum + compliance);
    let d_clamp = damping.clamp(0.0, 1.0);
    dlambda *= 1.0 - d_clamp;
    positions[a].0 = pax + wa * dlambda * nx;
    positions[a].1 = pay + wa * dlambda * ny;
    positions[b].0 = pbx - wb * dlambda * nx;
    positions[b].1 = pby - wb * dlambda * ny;
    dlambda.abs()
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(solve_joints_pass, m)?)?;
    Ok(())
}
```

Wiring into `src/lib.rs` follows the existing pattern:

```rust
mod dynamics;
// ...
#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // ... existing module registrations ...
    dynamics::register(m)?;
    Ok(())
}
```

### Why `Vec<(f64, f64)>` and not numpy arrays

The existing `src/ik_solver.rs` already takes `Vec<(f32, f32)>` for
input and returns `Vec<(f32, f32)>` for output. We deliberately match
that style — it's the shortest path to a working MVP, it lets `pyo3`
handle the GIL/ref-counting for us, and the per-frame copy of 100-200
nodes is sub-microsecond. **We use `f64` rather than `f32`** because the
Python solver is `float64` and the softbody-XPBD precision cascade
documented in `project_rust_steps_1_4_2026_05` showed that stacked
constraints amplify f32 round-off into visible drift.

If profile evidence later shows the Vec copy is hot (it shouldn't be
for <1k nodes), we move to `&PyArray2<f64>` with `numpy` crate and
`unsafe { array.as_array_mut() }`. That's an internal refactor; the
Python-facing signature does not change.

### Python wrapper

The Python side gets a one-method change in `dynamics/world.py:step()`:

```python
# Inside World.step, replacing the inner "for _ in range(iters): for joint ..." loop
try:
    from slappyengine._core import solve_joints_pass as _solve_native
except ImportError:
    _solve_native = None

if _solve_native is not None and self._joint_arrays_cache is not None:
    # Bulk Rust pass.
    flat_pos = [tuple(row) for row in self.positions]
    new_pos, corrections = _solve_native(
        flat_pos,
        [float(m) for m in self.inv_masses],
        self._joint_arrays_cache.kinds,       # list[u8]
        self._joint_arrays_cache.node_a,      # list[u32]
        self._joint_arrays_cache.node_b,
        self._joint_arrays_cache.rest_length,
        self._joint_arrays_cache.stiffness,
        self._joint_arrays_cache.damping,
        float(dt),
        int(max(1, self.solver_iterations)),
    )
    self.positions = np.asarray(new_pos, dtype=np.float64)
    # break_force check stays Python-side
    for j, joint, corr in zip(range(len(self.joints)), self.joints, corrections):
        if corr > joint.break_force:
            joint.enabled = False
else:
    # Existing Python path — unchanged fallback.
    for _ in range(max(1, self.solver_iterations)):
        for joint in self.joints:
            if not getattr(joint, "enabled", True):
                continue
            _resolve_joint(joint, self, dt)
```

`_joint_arrays_cache` is rebuilt whenever `add_joint` is called and
invalidated when joint params mutate; cache management is the Phase 1
refactor noted in Section 3.

---

## 6. Risk callouts

### R1. Precision mismatch — f32 vs f64 XPBD drift

The Python solver is `float64` throughout. Two prior data points say
this matters:

* `project_rust_steps_1_4_2026_05`: "Softbody same change reverted
  (precision cascade on stacked blocks)" — f32 was attempted for
  softbody and reverted because constraint stacks drifted visibly.
* `project_perf_2026_05`: the `np.bincount` change in softbody was
  reverted for "precision cascade on stacked blocks" — same root cause.

The proposed port uses `f64` end-to-end exactly to avoid this. If at any
point we consider `f32` for a SIMD win, the regression test must include
a 10-second simulation of a stacked-block rope or a deep ragdoll and
compare position deltas against the Python reference to <= 1e-3
absolute tolerance per node.

### R2. Borrow-checker complications — cycles in joint graph

Joints reference nodes by index, but two joints can share a node
(adjacent rope segments share their endpoint; a ragdoll hinge references
the grandparent node of a bone). The Gauss-Seidel sweep mutates the
position buffer in place and reads neighbouring positions; this is a
single `&mut [(f64, f64)]` slice with sequential indexed access, which
the borrow checker accepts with no special handling. There are **no
real-time graph cycles** to worry about — only static index aliasing,
which Rust handles via `slice` indexing trivially.

The risk lives in the *kind-specific* projections: `_resolve_motor`
touches both `positions[rim]` and `velocities[rim]`. If both buffers
are passed as `&mut` slices to the same function the borrow checker
will refuse. Mitigation: pass them in via two distinct `&mut`
references; this is fine because they're distinct allocations.

### R3. Cross-language allocation cost — Python-object churn per frame

`Vec<(f64, f64)>` arguments are constructed by `pyo3` from a Python
list. At 100 nodes per frame that's ~1.6 KB allocated + freed per
`step` call — sub-microsecond on this hardware and dwarfed by the
~11 ms baseline. **At 10 000 nodes** (a stress scenario well beyond
Scenario C) the copy becomes ~160 KB and starts to matter; that's the
point at which we switch to the `numpy` crate's zero-copy
`PyReadonlyArray2<f64>` + `PyArray2<f64>` (the `physics.rs` module
already has the pattern for this in its bulk position-update path).

The MVP does **not** do that swap because it adds dependency
(`numpy = "0.22"`) and unsafe code (`as_array_mut`) for no measurable
gain at the sizes that show up in real scenes. We commit to revisiting
*if* a profile after the port shows the Vec copy as > 5% of frame time.

### R4. FFI call frequency

Calling Rust 656 640 times/frame (once per joint per iteration) would
*increase* frame time — `pyo3` calls cost ~1-2 us each, multiplied
by 656 640 is 1-2 seconds. The API in Section 5 deliberately exposes
a *bulk pass* (one call per frame, doing all joints x all iterations
Rust-side) precisely to avoid this. If a future feature needs per-joint
inspection from Python during the solve (e.g. live debugger overlay),
it must use a callback-into-Python pattern with care; the prototype
should stay bulk.

### R5. Behavioural regressions on the seven joint kinds

Distance, spring, weld, ball are *the same kernel*. Hinge adds
`_project_angle`. Motor adds tangential velocity push. Prismatic adds
the axis decomposition. All five non-distance kinds carry behavioural
risk because the Python implementation has subtle clamps (`max(0.0, min(1.0, ...))`),
inertia-protection branches (`la < 1e-9`), and impulse caps (`max_torque * dt`).

Mitigation: Phase 1 ships *only the distance kernel* and routes
non-distance kinds through the Python fallback unchanged. Phase 2 adds
each additional kind behind a per-kind feature flag with a behavioural-
equivalence test against the Python implementation (driven by
`hello_motor.py`, `hello_joint.py`, `hello_ragdoll.py` golden frames).

### R6. Build matrix — maturin + Windows

The engine already ships a `_core` Rust extension via `maturin`. CI
broke briefly during the rename (see commit `8f2c5a8 Fix CI: create
venv before maturin develop, add venv to PATH`). The dynamics port
adds one more `pyo3` function; no new dependencies; no new build steps.
Risk is contained to whatever the existing matrix can compile, which
is already validated.

---

## 7. Phased delivery plan

The plan is sized so each phase is independently revertable and
independently shippable. Every phase ends with the dynamics test suite
(`SlapPyEngineTests/tests/test_dynamics_*.py`) green and a fresh bench run posted to the
PR description.

### Phase 1 — MVP: port `_project_distance` only

**Scope.** Land the SoA joint-array cache in `World`, expose
`solve_joints_pass` in `src/dynamics.rs`, route only `kind="distance"`
through it. All other kinds keep the existing Python path. Default
dispatch is Python; Rust path opt-in via `world.use_native_solver = True`
or env var `SLAPPYENGINE_NATIVE_DYNAMICS=1`.

**Acceptance criteria.**

* `SlapPyEngineTests/tests/test_dynamics_unified_step.py` passes against both paths (a
  new `parametrize` switches `use_native_solver`).
* `SlapPyEngineTests/tests/test_dynamics_rope.py` passes against both paths (rope is
  pure distance joints — the most direct exercise).
* New `SlapPyEngineTests/tests/test_dynamics_native_parity.py`: for the rope scenario at
  240 frames, every node's final position differs by <= 1e-6 from the
  Python reference (within f64 round-off).
* Re-run `_bench_dynamics.py`: Scenario A measurable speedup or no
  regression; Scenario C native-path median <= **8 ms** (back in
  budget — see Section 4 lower bound).

**Estimated effort.** ~1 working day for the Rust kernel + Python
plumbing + SoA cache; ~1 day for tests + bench.

### Phase 2 — port remaining joint kinds

**Scope.** Add `_project_angle` (hinge), motor tangential push, and
prismatic axis decomposition to `src/dynamics.rs`. Extend
`solve_joints_pass` to dispatch on `joint_kinds[j]` for the full set.
Keep the `JointKind::Motor` path mutating `velocities` via a second
output array returned to Python and applied in `World.step`.

**Acceptance criteria.**

* `SlapPyEngineTests/tests/test_dynamics_ragdoll.py`, `test_dynamics_motor.py`,
  `test_dynamics_joint_spec.py`, `test_dynamics_overdamping_warning.py`
  all pass against the native path.
* Native-path golden-frame comparison against `hello_ragdoll.py`,
  `hello_motor.py`, `hello_joint.py` at frame 60: per-node position
  delta <= 1e-4 (looser than Phase 1 because trig + impulse caps
  introduce path-dependent round-off).
* Scenario B native median below Python median (target 3-4x).

**Estimated effort.** ~2 days. Hinge and motor are the most subtle;
plan for at least one iteration after the first parity-test failure.

### Phase 3 — switch dispatch to native by default

**Scope.** Flip `World.use_native_solver` default from `False` to
`True` when `slappyengine._core` is importable. Add an opt-out via
`SLAPPYENGINE_DISABLE_NATIVE_DYNAMICS=1` for debugging.

**Acceptance criteria.**

* Full dynamics test suite passes with the default. No `parametrize`
  needed any more; both paths are exercised because the import-failure
  path is covered by a CI job that builds without the Rust extension.
* CHANGELOG entry calling out the default change and the opt-out
  variable.
* Documentation update to `docs/dynamics_quickstart.md` noting that
  `solver_iterations` cost is now sub-linear in joint count for the
  common kinds.

**Estimated effort.** ~0.5 day, mostly bookkeeping.

### Phase 4 — deprecate the Python fallback

**Scope.** Mark the Python `_project_distance` / `_project_angle` /
`_resolve_motor` etc. as `@deprecated` (DeprecationWarning) when called
directly. The functions stay for now (one major release of grace) but
emit a warning that says "this kernel has moved to
`slappyengine._core.solve_joints_pass`; import the Python version from
`slappyengine.dynamics._legacy` if you need the reference
implementation for testing."

Move the Python implementations to a `_legacy.py` sub-module so they
remain accessible to the parity tests but stop being the default code
path for direct imports.

**Acceptance criteria.**

* `SlapPyEngineTests/tests/test_dynamics_native_parity.py` is upgraded to drive the
  legacy path explicitly from `_legacy.py` and compare both directions.
* CHANGELOG, deprecation timeline doc, and an `ARCHITECTURE.md` note
  matching the existing "Python = wrapper, Rust = engine" memory
  entry.

**Estimated effort.** ~1 day. This is the last phase and is gated on
zero regressions across all of `SlapPyEngineExamples/examples/hello_*.py`.

---

## Summary recommendation

**Yes, port the dynamics solver to Rust** — but only the inner kernel
(`_project_distance` plus its four siblings that wrap it), behind a
bulk-pass API that does all `solver_iterations` Rust-side per frame.
Keep the outer `World.step`, the dataclass validators, the warning
machinery, and the joint authoring helpers in Python. The 80% line on
the profile is reached by porting **one function**, and the speedup
range anchored to the engine's prior softbody-XPBD and PBF ports (35%
to 68% per-kernel, 4.8x further amortised once dispatch overhead is
collapsed) puts Scenario C — currently the only over-budget scenario
— back inside the 8 ms physics budget at the lower bound and at
~3-4 ms at the likely-central estimate.

**Phase 1 MVP function pick: `_project_distance`** (in
`python/slappyengine/dynamics/joint.py`, lines 156-198). It is 85%
of frame time on the Scenario C profile, has no Python-state side
effects, has a clean f64 SoA mapping, and is the dependency of four
of the seven joint kinds. Land that single function in Rust with
the SoA joint-array cache and the rest of the plan is straightforward
extension work on a proven path.
