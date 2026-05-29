"""Perf-regression tripwire for :func:`slappyengine.numerics.vcycle_poisson`.

Catches accidental Python-level regressions in the V-cycle hot path
(``_sor_sweep``, ``_restrict_2x2``, ``_restrict_mask``, ``_v_cycle``).

Scenario
--------
64x64 grid, 5 V-cycles, 4 iters/level, Gaussian-bump RHS + circular mask.
This is the "real" use case the bench script tracks. On the dev box
post-optimization (Phase B + redundant-mask-mul removal + ufunc-strided
restrictions) the median wall-clock is ~3 ms. We assert < 50 ms — loose
enough to survive shared CI runners and warm-cache jitter, tight enough
that a 2× Python-level regression (e.g. a re-introduced per-iter
allocation in the smoother) fails the build.
"""
from __future__ import annotations

import gc
import statistics
import sys
import time
from pathlib import Path

import numpy as np

# Allow running from repo root without installing the package.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_PY_SRC = _REPO_ROOT / "python"
if str(_PY_SRC) not in sys.path:
    sys.path.insert(0, str(_PY_SRC))

from slappyengine.numerics import vcycle_poisson  # noqa: E402


# Loose enough for CI noise; tight enough to flag a 2x regression on the
# ~3 ms post-optimization median.
PERF_BUDGET_MS = 50.0
REPEATS = 30
WARMUP = 3


def _build_inputs(n: int) -> tuple[np.ndarray, np.ndarray]:
    yy, xx = np.indices((n, n), dtype=np.float32)
    cy = cx = (n - 1) * 0.5
    r2 = (yy - cy) ** 2 + (xx - cx) ** 2
    sigma = max(n * 0.15, 1.0)
    rhs = np.exp(-r2 / (2.0 * sigma * sigma)).astype(np.float32)
    mask = (r2 <= (0.45 * n) ** 2).astype(np.float32)
    return rhs, mask


def test_vcycle_64_5cycles_under_budget():
    """64² @ 5 cycles / 4 iters-per-level must finish under ``PERF_BUDGET_MS``.

    Builds a fixed Gaussian-bump RHS + circular mask once, runs
    ``vcycle_poisson`` ``REPEATS`` times after a short warm-up, and
    asserts on the median (robust against single-frame stalls).
    """
    rhs, mask = _build_inputs(64)

    for _ in range(WARMUP):
        vcycle_poisson(rhs, mask, iters_per_level=4, n_cycles=5)

    samples: list[float] = []
    gc.collect()
    gc.disable()
    try:
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            vcycle_poisson(rhs, mask, iters_per_level=4, n_cycles=5)
            samples.append((time.perf_counter() - t0) * 1000.0)
    finally:
        gc.enable()

    median_ms = statistics.median(samples)
    assert median_ms < PERF_BUDGET_MS, (
        f"vcycle_poisson 64² / 5-cycles regression: "
        f"median {median_ms:.2f} ms exceeds {PERF_BUDGET_MS:.1f} ms budget"
    )
