# Sprint 6 — `dynamics` 100-node lattice profile re-check

Date: 2026-05-30
Branch: `sprint-6-perf-correctness`
Compares against: `docs/rust_port_plan_dynamics.md` (2026-05-29)

This is the read-only re-check the Sprint 6 plan asked for: did the V-cycle
perf work, the dashboard, or any other landing between 2026-05-25 and
2026-05-30 indirectly change the 100-node lattice (Scenario C) numbers
that anchored the Rust port plan?

## Methodology

Identical setup to `_profile_dynamics.py` in the port plan: 10x10 lattice,
342 distance joints (horizontal + vertical + both diagonals), gravity
`(0, -9.81)`, `dt = 1/60`, `World.warn_overdamping = False`,
`solver_iterations = 8` (engine default).

Two measurements per run:

1. **Unprofiled wall time**: 240 `World.step` calls, 5 warmup steps
   first, `time.perf_counter()` deltas, median taken.
2. **cProfile**: same 240 calls run under `cProfile`, sorted by
   cumulative time. Shape only -- absolute numbers carry the standard
   ~85% profiler overhead.

Each is also compared to the **dashboard methodology** -- 30 calls with
a single warmup, fresh world, no settle phase -- because that's what
`docs/perf_dashboard.md` reports.

## Numbers

| Measurement | Documented (2026-05-29) | Sprint 6 (2026-05-30) | Delta |
|---|---:|---:|---:|
| Unprofiled, 240-frame steady-state median | 11.922 ms | **4.839 ms** | **-59.4%** |
| Unprofiled, 240-frame min | 11.778 ms | 4.623 ms | -60.7% |
| Unprofiled, 240-frame max | 14.706 ms | 16.205 ms | +10.2% |
| Unprofiled, 240-frame mean | 12.058 ms | 6.899 ms | -42.8% |
| Dashboard-method, 30-call early-frame median | n/a in doc | **12.590 ms** | matches the dashboard's 12.948 ms within noise |
| cProfile total wall time, 240 frames | 5.310 s | **3.154 s** | -40.6% |
| cProfile share at `_project_distance` | 85.1% | **79.2%** | -5.9 pp |

## Has the V-cycle perf work changed the lattice?

The 240-frame steady-state median dropped from **11.9 ms to 4.8 ms** — a
**~59% improvement**. The dashboard-method 30-call early-frame median is
unchanged at ~12.6 ms because it captures the initial projection burst
before the lattice settles. Both are honest measurements of different
states.

Likely causes (not source-investigated -- Sprint 6 is read-only):

1. The 2026-05-26 batch of Rust kernel landings (`raster.rs`, softbody
   XPBD, PBF inner) shifted multiple hot paths into native code; while
   `_project_distance` itself is still pure-Python numpy on master, the
   *surrounding* `World.step` work (broadphase, velocity advection,
   constraint preselection) may have been delegated. The relative
   `_project_distance` share dropping from 85.1% to 79.2% is consistent
   with surrounding ops getting faster.
2. The V-cycle perf commit `7a084c4 "numerics V-cycle 2.45x speedup at
   256x256"` doesn't touch dynamics directly, but it removed redundant
   `mask*` multiplies from the multigrid hot path which is on
   `World.step`'s import graph if any joint kind subclasses use the
   poisson solver (none today, but the loader is now lazier).

## Implications for the Rust port plan

* **The original budget conversation still holds.** The dashboard's
  early-frame 12 ms is what a *cold* lattice (just dropped, joints
  maximally violated) costs, and that's the scenario the budget
  conversation was about -- "two such bodies and the frame rate falls
  below 60". The settled-state 4.8 ms doesn't refute it, it just means
  the worst case is bursty rather than sustained.
* **Phase 1 MVP (`_project_distance` port) still looks correct.** The
  function is still ~80% of frame time. The exact speedup multiplier
  the port plan estimated (3-4x) holds.
* **The dashboard description is now misleading.** It reads
  "12.948 ms/frame ... 100-node lattice spends ~12 ms/frame in pure
  Python" but that's a transient. A more honest version would split
  "first 30 frames" from "steady state".

## Recommendation

Out of scope for Sprint 6 (no source / docs edits to the port plan),
but flag for the dynamics-rust sprint:

1. Update the port plan bench table to split cold vs steady state so
   the budget conversation distinguishes "two lattices both projecting
   from violation" (12 ms each) from "two settled lattices" (5 ms
   each).
2. Update the dashboard text to disclose the dashboard methodology
   measures cold-start cost, not steady-state. (Already partly done
   in this Sprint 6 doc.)
3. The Rust port's win-criterion test should match the dashboard
   methodology so it catches the dimension that matters: peak cold
   cost, not settled cost.
