"""Bench :func:`pharos_engine.numerics.vcycle_poisson` under realistic load.

Scenarios (grid, n_cycles, iters_per_level):

    * 16x16,   1 cycle,  2 iters/level
    * 64x64,   1 cycle,  2 iters/level
    * 64x64,   5 cycles, 4 iters/level  (the "real" use case)
    * 128x128, 5 cycles, 4 iters/level
    * 256x256, 5 cycles, 4 iters/level

For each scenario: build a Gaussian-bump RHS plus a roughly-circular fluid
mask, call :func:`vcycle_poisson` 30 times, report the median wall-clock.

Usage
-----
    cd <worktree-root>
    PYTHONPATH=python python tools/bench_numerics.py

Output is a markdown table on stdout, ready to drop into the perf notes.
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

from pharos_engine.numerics import vcycle_poisson  # noqa: E402


REPEATS = 30
WARMUP = 3

# (label, grid_side, n_cycles, iters_per_level)
SCENARIOS = [
    ("16x16,  1 cycle,  2 iters/level", 16, 1, 2),
    ("64x64,  1 cycle,  2 iters/level", 64, 1, 2),
    ("64x64,  5 cycles, 4 iters/level", 64, 5, 4),
    ("128x128, 5 cycles, 4 iters/level", 128, 5, 4),
    ("256x256, 5 cycles, 4 iters/level", 256, 5, 4),
]


def build_inputs(N: int) -> tuple[np.ndarray, np.ndarray]:
    """Build a Gaussian-bump RHS and a circular fluid mask on an ``N``-grid.

    The mask is the disc of radius ``0.45 N`` centred on the grid, which
    keeps a sliver of vacuum cells around the boundary so the no-flux
    enforcement actually does work each call.
    """
    yy, xx = np.indices((N, N), dtype=np.float32)
    cy = cx = (N - 1) * 0.5
    r2 = (yy - cy) ** 2 + (xx - cx) ** 2
    sigma = max(N * 0.15, 1.0)
    rhs = np.exp(-r2 / (2.0 * sigma * sigma)).astype(np.float32)
    mask = (r2 <= (0.45 * N) ** 2).astype(np.float32)
    return rhs, mask


def median_ms(N: int, n_cycles: int, iters_per_level: int) -> float:
    """Return the median wall-clock per :func:`vcycle_poisson` call in ms."""
    rhs, mask = build_inputs(N)

    # Warm-up: cache JIT-like numpy code paths and let any one-time
    # allocations settle so the first measured call isn't a fluke.
    for _ in range(WARMUP):
        vcycle_poisson(
            rhs, mask,
            iters_per_level=iters_per_level,
            n_cycles=n_cycles,
        )

    samples: list[float] = []
    gc.collect()
    gc.disable()
    try:
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            vcycle_poisson(
                rhs, mask,
                iters_per_level=iters_per_level,
                n_cycles=n_cycles,
            )
            samples.append((time.perf_counter() - t0) * 1000.0)
    finally:
        gc.enable()
    return statistics.median(samples)


def main() -> int:
    rows: list[tuple[str, float]] = []
    for label, N, n_cycles, iters in SCENARIOS:
        ms = median_ms(N, n_cycles, iters)
        rows.append((label, ms))

    # Markdown table.
    print()
    print("| Scenario | Median wall-clock (ms) |")
    print("| --- | ---: |")
    for label, ms in rows:
        print(f"| {label} | {ms:.3f} |")
    print()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
