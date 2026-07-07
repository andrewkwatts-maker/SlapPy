<!-- handauthored: do not regenerate -->
# slappyengine.perf — API Reference

> Hand-written reference for the `perf` subpackage — a
> dependency-free perf regression tripwire around the
> `hello_ragdoll` demo. Owns the run-bench + baseline-YAML + compare
> pipeline that gates every perf sprint. Does **not** own runtime
> profiling (see `slappyengine.diagnostics` for the App-lifecycle
> aggregator sibling reference at [`diagnostics.md`](diagnostics.md))
> or the six-hot-path perf dashboard doc (see
> [`../perf_dashboard.md`](../perf_dashboard.md) for the tripwire's
> narrative companion).

## Overview

`slappyengine.perf` benches exactly one demo — `hello_ragdoll` —
with a fixed load (`world.step` at `dt = 1/60 s`, per-frame timing
via `time.perf_counter_ns`) and compares the summary statistics
against a YAML baseline that ships alongside the module at
`baseline_ragdoll.yaml`. The design is deliberately narrow: one
demo, one solver step per frame, `time.perf_counter_ns` only, YAML
only. Every richer perf story — the six-hot-path dashboard, the
Rust-migration ROI ranking, the SS4 re-baseline — layers on top by
consuming a :class:`PerfResult`, not by extending :class:`PerfTripwire`.

Every trial rebuilds the demo world from scratch so cache effects
never compound across trials; the warmup phase runs the exact same
inner loop as the measured phase so JIT / numpy allocator warmup is
symmetric. The comparison step scores four metrics
(`mean_ms`, `median_ms`, `p95_ms`, `p99_ms`) against a ±15%
default tolerance band, tagging faster-than-baseline drops beyond
−5% as improvements.

Public symbols are re-exported lazily via a module-level
`__getattr__` — `python -m slappyengine.perf.tripwire` does not trip
Python's "module found in `sys.modules` before execution"
`RuntimeWarning`.

## Public surface

```python
from slappyengine.perf import (
    ComparisonReport,
    DEFAULT_BASELINE_PATH,
    PerfResult,
    PerfTripwire,
)
```

| Symbol | Role |
|---|---|
| `PerfTripwire` | Runner + YAML I/O + comparison. Stateless — share one instance. |
| `PerfResult` | Dataclass summary of one bench run (`mean_ms` / `p95_ms` / …). |
| `ComparisonReport` | Pass/fail verdict + per-metric deltas + printable table. |
| `DEFAULT_BASELINE_PATH` | On-disk YAML shipped with the module. |

## Classes

### `PerfResult`

_dataclass — defined in `slappyengine.perf.tripwire`_

One bench run's summary statistics. Every duration field is
milliseconds; every counter field is an integer.

| Field | Type | Notes |
|---|---|---|
| `demo` | `str` | Always `"hello_ragdoll"` for the shipping runner. |
| `steps` | `int` | Measured `world.step` calls per trial (warmup excluded). |
| `trials` | `int` | Independent trial count; each rebuilds the world. |
| `mean_ms` | `float` | Arithmetic mean across every measured frame. |
| `median_ms` | `float` | Median across every measured frame. |
| `p95_ms` | `float` | 95th percentile with linear interpolation (no numpy). |
| `p99_ms` | `float` | 99th percentile with linear interpolation. |
| `total_ms` | `float` | Wall-clock time in the measured phase. |
| `commit_sha` | `str` | `git rev-parse --short HEAD` or `"unknown"`. |
| `timestamp` | `str` | UTC ISO-8601 to second precision. |

#### Methods

- `to_dict(self) -> dict` — plain-dict form for YAML serialisation.
- `from_dict(cls, data) -> PerfResult` — reconstruct from a
  `to_dict` payload. Extra keys are ignored (schema-forward-compat);
  missing keys raise `KeyError` naming the specific field.

Private class attribute `_METRIC_FIELDS` fixes the four metric
names compared field-by-field in :meth:`PerfTripwire.compare`.

### `ComparisonReport`

_dataclass — defined in `slappyengine.perf.tripwire`_

Outcome of comparing a fresh :class:`PerfResult` to a baseline.

| Field | Type | Notes |
|---|---|---|
| `passed` | `bool` | `True` iff every metric stayed inside the band. |
| `deltas` | `dict[str, float]` | Signed relative delta per metric (`cur/base − 1`). |
| `regressed_metrics` | `list[str]` | Metrics whose delta exceeded `tolerance_pct`. |
| `improvements` | `list[str]` | Metrics whose speedup exceeded 5%. |
| `tolerance_pct` | `float` | Band recorded for the "within ±X%" banner (default 15). |

#### Methods

- `format_table(self) -> str` — monospace pass/fail table. Column
  widths are fixed so the block aligns even under redirected output;
  no ANSI colour so the CLI can wrap it in its own banner.

### `PerfTripwire`

_class — defined in `slappyengine.perf.tripwire`_

Runs the `hello_ragdoll` bench and manages baseline comparisons.
Intentionally stateless — every entry point takes the parameters it
needs so one instance can be shared between the CLI, the pytest
suite, and an ad-hoc REPL.

Two class-level tunables:

- `DEFAULT_TOLERANCE_PCT = 15.0` — used by :meth:`compare` when the
  caller does not pass `tolerance_pct` explicitly.
- `IMPROVEMENT_THRESHOLD_PCT = 5.0` — negative deltas below this
  count as "improvement" (surfaced in the table + report list).

#### Methods

- `run_ragdoll_bench(self, *, steps=60, warmup=10, trials=3,
  dt=DEFAULT_DT) -> PerfResult` — build the demo world, warm up,
  measure, aggregate. Raises `ValueError` when `steps < 1`,
  `warmup < 0`, or `trials < 1`.
- `write_baseline(self, result, path=DEFAULT_BASELINE_PATH) -> Path`
  — persist as YAML with a banner comment + stable key order.
  Creates parent directories on demand.
- `read_baseline(self, path=DEFAULT_BASELINE_PATH) -> PerfResult` —
  round-trip a YAML baseline back into a :class:`PerfResult`. Raises
  `FileNotFoundError` when the file is absent so the CLI can surface
  a specific "missing baseline" error.
- `compare(self, current, baseline, tolerance_pct=DEFAULT_TOLERANCE_PCT)
  -> ComparisonReport` — score every field in
  `PerfResult._METRIC_FIELDS`. A degenerate baseline (metric `<= 0`)
  is treated as a pass to avoid false fails on a broken record.

## Constants

### `DEFAULT_BASELINE_PATH`

_`pathlib.Path` — defined in `slappyengine.perf`_

Ships as `baseline_ragdoll.yaml` alongside `tripwire.py` inside the
wheel. Read-only unless the caller passes `--write-baseline` on the
CLI.

## Inner modules

- `slappyengine.perf.tripwire` — the runner, the dataclasses, and the
  compare logic.
- `slappyengine.perf.cli` — argparse wrapper. Exits `0` on pass /
  when `--write-baseline` succeeds with no prior baseline; `1`
  otherwise. Invoked via `python -m slappyengine.perf.tripwire`.

## Usage

```python
from slappyengine.perf import PerfTripwire, DEFAULT_BASELINE_PATH

tw = PerfTripwire()

# 1. Run the bench (30 measured steps × 2 trials for a quick check).
current = tw.run_ragdoll_bench(steps=30, warmup=5, trials=2)
print(f"{current.mean_ms:.3f} ms/frame @ {current.commit_sha}")

# 2. Compare against the shipped baseline.
baseline = tw.read_baseline(DEFAULT_BASELINE_PATH)
report = tw.compare(current, baseline, tolerance_pct=15.0)
print(report.format_table())
if not report.passed:
    raise SystemExit(1)

# 3. Refresh the baseline after a landed speedup:
#    tw.write_baseline(current)
```

## Skip the wrapper

`slappyengine.perf` is pure Python + `pyyaml` — no runtime work
lives in Rust. Grep of `slappyengine._core_facade.RUST_MODULE_MAP`
shows **no** `perf` entry. The demo the tripwire loads
(`hello_ragdoll`) *does* transitively call into Rust via the
softbody / dynamics solver kernels (`softbody_solver` +
`pbf_solver` — see [`../rust_bypass_2026_07_05.md`](../rust_bypass_2026_07_05.md)),
so the timings measured here reflect that. There is no CPU-only
fallback to skip — the tripwire is the fallback.

Callers who want to bench something other than `hello_ragdoll`
should call `PerfTripwire.run_ragdoll_bench` for the reference load
and layer their own bench on top; the module deliberately does
**not** parametrise the demo.

## Conventions

- **Nanosecond timing.** Always `time.perf_counter_ns` — monotonic
  on every supported platform, no `time.perf_counter` float drift.
- **Fresh world per trial.** Every trial rebuilds the world so
  cache effects never compound across trials.
- **Symmetric warmup.** The warmup loop runs the exact same
  `world.step(dt); demo._ground_clamp(world)` pair as the measured
  loop so JIT / allocator warmup is representative.
- **YAML only, `sort_keys=True`.** Baselines are human-diffable.
- **Never raises on git.** `_git_sha` catches every exception and
  falls back to `"unknown"` so the tripwire survives a
  detached-worktree / non-git deploy.

## See also

- [`diagnostics.md`](diagnostics.md) — runtime diagnostics
  aggregator sibling; different problem (in-flight logging warnings
  vs. per-frame timing regression).
- [`../perf_dashboard.md`](../perf_dashboard.md) — one-page perf
  tripwire narrative across the six v0.3 hot paths (dynamics /
  numerics / thermal / topology / telemetry / zones).
- [`../perf_baseline_2026_07_07.md`](../perf_baseline_2026_07_07.md)
  — SS4 re-baseline landing that closes v0.4 ship gate #13.
- [`../rust_migration_audit_2026_07_05.md`](../rust_migration_audit_2026_07_05.md)
  — Rust-migration ROI ranking that consumes tripwire output.
