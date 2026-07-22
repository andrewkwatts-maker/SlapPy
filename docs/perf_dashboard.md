# Pharos Engine perf dashboard -- 2026-05-30

## At a glance

| subsystem | scenario | median | bound |
|---|---|---|---|
| dynamics | World.step on 100-node lattice (~340 joints; cf. port plan Scenario C) | 12.948 ms/frame | Python-loop-bound (per-joint numpy.linalg.norm; see docs/rust_port_plan_dynamics.md) |
| numerics | vcycle_poisson on 64x64 grid (1 V-cycle) | 0.437 ms/call | allocation-bound (per-cycle restrict/prolong scratch arrays) |
| thermal | HeatField.step on 64x64 grid | 0.033 ms/step | memory-bound (numpy stencil on 32 KiB grid) |
| topology | connected_components on 1000-node graph (2000 edges) | 2.314 ms/call | Python loop-bound (union-find, no vectorisation) |
| numerics | bench_numerics.py | 64.00x speedup | uncategorised |
| telemetry | bench_telemetry.py | 33,370 ns/emit | allocation-bound (per-emit list / dict ops dominate) |
| zones | bench_zones.py | 8.85x speedup | uncategorised |

## Hot paths

* **Fastest inline subsystem:** `thermal` at 0.033 ms (memory-bound (numpy stencil on 32 KiB grid)).
* **Slowest inline subsystem:** `dynamics` at 12.948 ms (Python-loop-bound (per-joint numpy.linalg.norm; see docs/rust_port_plan_dynamics.md)).
* **Rust ports planned:** `dynamics.World.step` is the engine's current Python-loop hotspot (see `docs/rust_port_plan_dynamics.md` -- 100-node lattice spends ~12 ms/frame in pure Python, ~85% in `_project_distance`). Port lands as part of the dynamics Phase 1 MVP.

## Trend

**Regressions (>10% slower):**
* `topology`: 2.051 ms/call -> 2.314 ms/call (+12.8%)
* `numerics`: 0.769 ms/call -> 64.00x speedup (+8222.5%)
* `telemetry`: 29,638 ns/emit -> 33,370 ns/emit (+12.6%)

**Improvements (>10% faster):**
* `numerics`: 0.769 ms/call -> 0.437 ms/call (-43.2%)

**Unchanged (within +/-10%):**
* `dynamics`: 12.032 ms/frame -> 12.948 ms/frame (+7.6%)
* `thermal`: 0.034 ms/step -> 0.033 ms/step (-2.9%)
* `zones`: 9.07x speedup -> 8.85x speedup (-2.4%)
