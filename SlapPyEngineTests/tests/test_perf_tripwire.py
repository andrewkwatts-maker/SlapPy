"""Tests for :mod:`slappyengine.perf.tripwire` — the ragdoll perf tripwire.

These tests pin the tripwire's contract without depending on absolute
wall-clock numbers (which drift on shared CI runners). They cover:

1. ``run_ragdoll_bench`` returns a fully-populated :class:`PerfResult`.
2. Warmup steps are excluded from the returned stats.
3. YAML baseline round-trip (write + read reproduces the record).
4. Comparison: identical stats → passes.
5. Comparison: 20% slower → fails at the default 15% tolerance.
6. Comparison: 5% slower → passes at the default 15% tolerance.
7. Comparison: 8% faster → marked as improvement.
8. Missing baseline → :class:`FileNotFoundError` from ``read_baseline``.
9. CLI ``main`` returns 0 on the shipped baseline (regenerating first
   so the check is hardware-independent).
10. CLI ``--write-baseline`` writes a file and exits 0.
11. Percentile helper matches expected values on a small sample.
12. Zero-baseline degenerate case is treated as a pass.
13. ``PerfResult.from_dict`` rejects missing keys.
14. ``ComparisonReport.format_table`` includes verdict + tolerance.
15. Empty regression list is treated as passed even with tiny deltas.
16. ``run_ragdoll_bench`` rejects non-positive ``steps`` / ``trials``.
17. Improvement threshold is 5 % (a 4 % speedup is *not* an improvement).
18. The shipped ``baseline_ragdoll.yaml`` decodes into a valid
    :class:`PerfResult`.
"""
from __future__ import annotations

import copy
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from slappyengine.perf import (
    DEFAULT_BASELINE_PATH,
    ComparisonReport,
    PerfResult,
    PerfTripwire,
)
from slappyengine.perf import cli as perf_cli
from slappyengine.perf import tripwire as tripwire_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tripwire() -> PerfTripwire:
    return PerfTripwire()


@pytest.fixture(scope="module")
def fresh_result(tripwire: PerfTripwire) -> PerfResult:
    """Run the bench once for the whole module — real timings are slow."""
    return tripwire.run_ragdoll_bench(steps=15, warmup=3, trials=2)


def _sample_result(**overrides: object) -> PerfResult:
    """Build a synthetic :class:`PerfResult` for comparison tests."""
    defaults = dict(
        demo="hello_ragdoll",
        steps=60,
        trials=3,
        mean_ms=1.0,
        median_ms=0.95,
        p95_ms=1.4,
        p99_ms=1.6,
        total_ms=180.0,
        commit_sha="abcdef1",
        timestamp="2026-07-05T00:00:00+00:00",
    )
    defaults.update(overrides)
    return PerfResult(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. run_ragdoll_bench populates the result
# ---------------------------------------------------------------------------

def test_run_ragdoll_bench_populates_result(fresh_result: PerfResult) -> None:
    r = fresh_result
    assert r.demo == "hello_ragdoll"
    assert r.steps == 15
    assert r.trials == 2
    assert r.mean_ms > 0.0
    assert r.median_ms > 0.0
    assert r.p95_ms >= r.median_ms  # by construction
    assert r.p99_ms >= r.p95_ms
    assert r.total_ms > 0.0
    assert isinstance(r.commit_sha, str) and r.commit_sha
    assert isinstance(r.timestamp, str) and "T" in r.timestamp


# ---------------------------------------------------------------------------
# 2. warmup steps are excluded from stats
# ---------------------------------------------------------------------------

def test_warmup_not_reflected_in_step_count(tripwire: PerfTripwire) -> None:
    """The returned ``steps`` field must ignore warmup.

    ``steps=8`` + ``warmup=5`` still reports ``steps==8``; the internal
    per-frame list also has exactly ``steps * trials`` samples.
    """
    result = tripwire.run_ragdoll_bench(steps=8, warmup=5, trials=2)
    assert result.steps == 8
    # ``total_ms`` sums exactly ``steps * trials`` measured frames; the
    # mean * count must line up with total to within FP slop.
    n = result.steps * result.trials
    assert abs(result.mean_ms * n - result.total_ms) < 1e-6


# ---------------------------------------------------------------------------
# 3. YAML round-trip
# ---------------------------------------------------------------------------

def test_baseline_round_trip(tripwire: PerfTripwire, tmp_path: Path) -> None:
    """Writing then reading a baseline reproduces the record exactly."""
    original = _sample_result(mean_ms=2.5, median_ms=2.4)
    path = tmp_path / "baseline.yaml"
    tripwire.write_baseline(original, path)
    assert path.exists()
    loaded = tripwire.read_baseline(path)
    assert loaded == original


# ---------------------------------------------------------------------------
# 4. Comparison: identical → passes
# ---------------------------------------------------------------------------

def test_compare_identical_passes(tripwire: PerfTripwire) -> None:
    baseline = _sample_result()
    current = copy.deepcopy(baseline)
    report = tripwire.compare(current, baseline)
    assert isinstance(report, ComparisonReport)
    assert report.passed is True
    assert report.regressed_metrics == []
    for delta in report.deltas.values():
        assert abs(delta) < 1e-9


# ---------------------------------------------------------------------------
# 5. Comparison: 20% slower → fails at 15% tolerance
# ---------------------------------------------------------------------------

def test_compare_20pct_slower_fails(tripwire: PerfTripwire) -> None:
    baseline = _sample_result(mean_ms=1.0, median_ms=1.0, p95_ms=1.0, p99_ms=1.0)
    current = replace(
        baseline,
        mean_ms=1.20, median_ms=1.20, p95_ms=1.20, p99_ms=1.20,
    )
    report = tripwire.compare(current, baseline, tolerance_pct=15.0)
    assert report.passed is False
    assert set(report.regressed_metrics) == {"mean_ms", "median_ms", "p95_ms", "p99_ms"}


# ---------------------------------------------------------------------------
# 6. Comparison: 5% slower → passes at 15% tolerance
# ---------------------------------------------------------------------------

def test_compare_5pct_slower_passes(tripwire: PerfTripwire) -> None:
    baseline = _sample_result(mean_ms=1.0, median_ms=1.0, p95_ms=1.0, p99_ms=1.0)
    current = replace(
        baseline,
        mean_ms=1.05, median_ms=1.05, p95_ms=1.05, p99_ms=1.05,
    )
    report = tripwire.compare(current, baseline, tolerance_pct=15.0)
    assert report.passed is True
    assert report.regressed_metrics == []
    # 5% slower is *below* the 5% improvement threshold — no field should
    # be flagged as an improvement either.
    assert report.improvements == []


# ---------------------------------------------------------------------------
# 7. Comparison: 8% faster → improvement flagged
# ---------------------------------------------------------------------------

def test_compare_improvement_flagged(tripwire: PerfTripwire) -> None:
    baseline = _sample_result(mean_ms=1.0, median_ms=1.0, p95_ms=1.0, p99_ms=1.0)
    current = replace(
        baseline,
        mean_ms=0.92, median_ms=0.92, p95_ms=0.92, p99_ms=0.92,
    )
    report = tripwire.compare(current, baseline)
    assert report.passed is True
    assert set(report.improvements) == {"mean_ms", "median_ms", "p95_ms", "p99_ms"}


# ---------------------------------------------------------------------------
# 8. Missing baseline
# ---------------------------------------------------------------------------

def test_missing_baseline_raises(tripwire: PerfTripwire, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        tripwire.read_baseline(tmp_path / "does_not_exist.yaml")


# ---------------------------------------------------------------------------
# 9. CLI main returns 0 vs a freshly-written baseline
# ---------------------------------------------------------------------------

def test_cli_main_pass(tmp_path: Path) -> None:
    """A CLI run compared to a baseline captured moments earlier must pass.

    Rewriting the baseline in-test means we never depend on absolute
    hardware-dependent timings — we're testing the wiring, not the
    engine's steady-state performance.
    """
    baseline = tmp_path / "baseline.yaml"
    # 1) capture
    rc_capture = perf_cli.main([
        "--steps", "10", "--warmup", "2", "--trials", "1",
        "--baseline", str(baseline), "--write-baseline",
    ])
    assert rc_capture == 0
    assert baseline.exists()
    # 2) compare with a generous tolerance — first-run jitter can be
    # substantial on the first bench under cold Python state.
    rc_compare = perf_cli.main([
        "--steps", "10", "--warmup", "2", "--trials", "1",
        "--baseline", str(baseline), "--tolerance", "500",
    ])
    assert rc_compare == 0


# ---------------------------------------------------------------------------
# 10. CLI --write-baseline writes a fresh file
# ---------------------------------------------------------------------------

def test_cli_write_baseline(tmp_path: Path) -> None:
    baseline = tmp_path / "sub" / "new_baseline.yaml"
    rc = perf_cli.main([
        "--steps", "5", "--warmup", "1", "--trials", "1",
        "--baseline", str(baseline), "--write-baseline",
    ])
    assert rc == 0
    assert baseline.exists()
    text = baseline.read_text(encoding="utf-8")
    assert "hello_ragdoll" in text
    assert "mean_ms:" in text


# ---------------------------------------------------------------------------
# 11. Percentile helper
# ---------------------------------------------------------------------------

def test_percentile_matches_expected() -> None:
    samples = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    # Linear interpolation between rank 8 and 9: (10 - 1) * 0.95 = 8.55.
    assert tripwire_mod._percentile(samples, 0.95) == pytest.approx(9.55, abs=1e-9)
    assert tripwire_mod._percentile(samples, 0.5) == pytest.approx(5.5, abs=1e-9)
    assert tripwire_mod._percentile(samples, 0.0) == 1.0
    assert tripwire_mod._percentile(samples, 1.0) == 10.0
    with pytest.raises(ValueError):
        tripwire_mod._percentile([], 0.5)


# ---------------------------------------------------------------------------
# 12. Zero-baseline degenerate case
# ---------------------------------------------------------------------------

def test_compare_zero_baseline_is_pass(tripwire: PerfTripwire) -> None:
    """A zeroed baseline means the tripwire can't compute a ratio.

    Rather than div-by-zero we treat every metric as "no delta" and
    let the run pass — the alternative (fail every run against a
    broken baseline) is unhelpful noise.
    """
    baseline = _sample_result(
        mean_ms=0.0, median_ms=0.0, p95_ms=0.0, p99_ms=0.0,
    )
    current = _sample_result(mean_ms=1.5, median_ms=1.5, p95_ms=1.5, p99_ms=1.5)
    report = tripwire.compare(current, baseline)
    assert report.passed is True
    assert report.regressed_metrics == []
    for delta in report.deltas.values():
        assert delta == 0.0


# ---------------------------------------------------------------------------
# 13. from_dict rejects missing keys
# ---------------------------------------------------------------------------

def test_from_dict_missing_key_raises() -> None:
    good = _sample_result().to_dict()
    good.pop("mean_ms")
    with pytest.raises(KeyError):
        PerfResult.from_dict(good)


# ---------------------------------------------------------------------------
# 14. format_table includes verdict + tolerance
# ---------------------------------------------------------------------------

def test_format_table_contains_verdict_and_tolerance(tripwire: PerfTripwire) -> None:
    baseline = _sample_result()
    current = _sample_result()
    report = tripwire.compare(current, baseline, tolerance_pct=12.5)
    table = report.format_table()
    assert "PASS" in table
    assert "12.5" in table
    assert "metric" in table
    assert "mean_ms" in table


# ---------------------------------------------------------------------------
# 15. Empty regression list ⇒ passed
# ---------------------------------------------------------------------------

def test_tiny_delta_is_still_pass(tripwire: PerfTripwire) -> None:
    baseline = _sample_result(mean_ms=1.0, median_ms=1.0, p95_ms=1.0, p99_ms=1.0)
    current = replace(
        baseline,
        mean_ms=1.001, median_ms=1.001, p95_ms=1.001, p99_ms=1.001,
    )
    report = tripwire.compare(current, baseline)
    assert report.passed is True
    assert report.regressed_metrics == []
    # Delta ~0.1 %, well below the improvement threshold of 5 %.
    assert report.improvements == []


# ---------------------------------------------------------------------------
# 16. run_ragdoll_bench parameter validation
# ---------------------------------------------------------------------------

def test_run_bench_rejects_bad_params(tripwire: PerfTripwire) -> None:
    with pytest.raises(ValueError):
        tripwire.run_ragdoll_bench(steps=0, warmup=1, trials=1)
    with pytest.raises(ValueError):
        tripwire.run_ragdoll_bench(steps=1, warmup=-1, trials=1)
    with pytest.raises(ValueError):
        tripwire.run_ragdoll_bench(steps=1, warmup=0, trials=0)


# ---------------------------------------------------------------------------
# 17. 4 % speedup does NOT count as an improvement
# ---------------------------------------------------------------------------

def test_4pct_speedup_is_not_improvement(tripwire: PerfTripwire) -> None:
    baseline = _sample_result(mean_ms=1.0, median_ms=1.0, p95_ms=1.0, p99_ms=1.0)
    current = replace(
        baseline,
        mean_ms=0.96, median_ms=0.96, p95_ms=0.96, p99_ms=0.96,
    )
    report = tripwire.compare(current, baseline)
    assert report.passed is True
    assert report.improvements == []
    # Every field must still be recorded in the delta table.
    assert set(report.deltas) == {"mean_ms", "median_ms", "p95_ms", "p99_ms"}


# ---------------------------------------------------------------------------
# 18. Shipped baseline is loadable
# ---------------------------------------------------------------------------

def test_shipped_baseline_loads(tripwire: PerfTripwire) -> None:
    result = tripwire.read_baseline(DEFAULT_BASELINE_PATH)
    assert result.demo == "hello_ragdoll"
    assert result.mean_ms > 0.0
    assert result.trials >= 1
    assert result.steps >= 1
    assert result.commit_sha != ""


# ---------------------------------------------------------------------------
# 19. Bench respects a custom dt (belt-and-braces: no crash on non-default dt)
# ---------------------------------------------------------------------------

def test_run_bench_accepts_custom_dt(tripwire: PerfTripwire) -> None:
    result = tripwire.run_ragdoll_bench(
        steps=6, warmup=2, trials=1, dt=1.0 / 120.0,
    )
    assert result.steps == 6
    assert result.trials == 1
    assert result.mean_ms > 0.0


# ---------------------------------------------------------------------------
# 20. `python -m slappyengine.perf.tripwire --write-baseline` works end-to-end
# ---------------------------------------------------------------------------

def test_module_cli_write_baseline(tmp_path: Path) -> None:
    """Exercise the actual ``python -m`` entry point in a subprocess.

    Kept as the last test so the slower subprocess spin-up runs once at
    the tail of the file instead of blocking earlier tests.
    """
    baseline = tmp_path / "module_cli.yaml"
    proc = subprocess.run(
        [
            sys.executable, "-m", "slappyengine.perf.tripwire",
            "--steps", "3", "--warmup", "1", "--trials", "1",
            "--baseline", str(baseline), "--write-baseline",
        ],
        cwd=str(Path(__file__).resolve().parents[2]),
        env={**__import__("os").environ, "PYTHONPATH": "python"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert baseline.exists()
