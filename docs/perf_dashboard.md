# SlapPyEngine perf dashboard -- 2026-05-29

## At a glance

| subsystem | scenario | median | bound |
|---|---|---|---|
| dynamics | World.step on 100-node lattice (~340 joints; cf. port plan Scenario C) | 12.032 ms/frame | Python-loop-bound (per-joint numpy.linalg.norm; see docs/rust_port_plan_dynamics.md) |
| numerics | vcycle_poisson on 64x64 grid (1 V-cycle) | 0.769 ms/call | allocation-bound (per-cycle restrict/prolong scratch arrays) |
| thermal | HeatField.step on 64x64 grid | 0.034 ms/step | memory-bound (numpy stencil on 32 KiB grid) |
| topology | connected_components on 1000-node graph (2000 edges) | 2.051 ms/call | Python loop-bound (union-find, no vectorisation) |
| telemetry | bench_telemetry.py | 29,638 ns/emit | allocation-bound (per-emit list / dict ops dominate) |
| zones | bench_zones.py | 9.07x speedup | uncategorised |

## Hot paths

* **Fastest inline subsystem:** `thermal` at 0.034 ms (memory-bound (numpy stencil on 32 KiB grid)).
* **Slowest inline subsystem:** `dynamics` at 12.032 ms (Python-loop-bound (per-joint numpy.linalg.norm; see docs/rust_port_plan_dynamics.md)).
* **Rust ports planned:** `dynamics.World.step` is the engine's current Python-loop hotspot (see `docs/rust_port_plan_dynamics.md` -- 100-node lattice spends ~12 ms/frame in pure Python, ~85% in `_project_distance`). Port lands as part of the dynamics Phase 1 MVP.

## Trend

_No previous dashboard at `docs/perf_dashboard_prev.md` -- skipping trend._
