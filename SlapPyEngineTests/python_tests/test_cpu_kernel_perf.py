"""Perf regression guard rails for ``PhysicsWorld._cpu_kernel``.

The kernel is the numpy reference solver that mirrors ``per_pixel_sim.wgsl``;
the ``fluid_pool`` benchmark spends the majority of its wall-clock budget
inside this function because every active T2 hull traverses it once per
CFL substep.  The kernel was rewritten to drop ``np.roll``-driven
allocator pressure (slice-shifts on zero-padded scratch buffers),
hoist material attribute reads out of inner expressions, and prefer
in-place ``np.clip(..., out=...)`` / ``np.nan_to_num(copy=False, ...)``
over the allocate-and-return spellings.

This module pins those wins so a future allocator regression — e.g.
re-introducing ``np.roll`` or a fresh ``astype`` inside the hot path —
fails here loudly rather than silently bleeding 20-30 ms back into the
``fluid_pool`` budget tracked by
``test_phase_c_fluid_perf.test_fluid_pool_under_perf_budget``.

Tests
-----
* ``test_kernel_substep_under_5ms_for_single_steel_body`` —
  steel ball, one substep, median over 10 runs < 5 ms.
* ``test_kernel_substep_under_50ms_for_3_water_bodies`` —
  three water rectangles with injected divergence; one
  ``_cpu_substep`` call hits all three; median < 50 ms.
* ``test_kernel_cpu_gpu_parity_preserved`` —
  re-runs ``test_gpu_matches_cpu_on_one_substep`` programmatically
  to confirm the optimisations did not change per-cell state.
* ``test_kernel_no_warnings_with_filter`` — runs the
  ``fluid_pool`` scenario for 60 frames with
  ``-W error::RuntimeWarning:pharos_engine.physics`` semantics enforced
  via ``warnings.catch_warnings``; no warning may be raised.
"""
from __future__ import annotations

import time
import warnings

import numpy as np
import pytest

from pharos_engine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)
from pharos_engine.physics.world import PhysicsWorld as _PW


# --- helpers ----------------------------------------------------------------


def _median_substep_ms(world: PhysicsWorld, runs: int = 10, dt: float = 1.0 / 240.0,
                       reactivator=None) -> float:
    """Run ``_cpu_substep`` ``runs`` times and return the median wall-time.

    ``reactivator`` (optional) is invoked between runs to re-mark hulls hot;
    ``_cpu_substep`` early-outs if the hot-flag has expired, so for kernel
    timing we must keep the bodies in the active set.
    """
    # Warm the import/dispatch path so the first call's cold-cache cost does
    # not skew the median.
    for _ in range(3):
        if reactivator is not None:
            reactivator()
        world._cpu_substep(dt)
    times_ms: list[float] = []
    for _ in range(runs):
        if reactivator is not None:
            reactivator()
        t0 = time.perf_counter()
        world._cpu_substep(dt)
        times_ms.append((time.perf_counter() - t0) * 1000.0)
    return float(np.median(times_ms))


def _stamp_divergence(body) -> None:
    """Inject a smooth radially-outward velocity into a body's cell grid.

    Mirrors the helper in ``test_phase_c_gpu``.  Used to drive the
    projection through the SOR sweeps instead of letting the
    near-zero-divergence early-out short-circuit.
    """
    cells = body.cells
    if cells is None:
        return
    H, W = cells.shape[0], cells.shape[1]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    cx, cy = (W - 1) * 0.5, (H - 1) * 0.5
    dx = xx - cx
    dy = yy - cy
    sigma = 6.0
    g = np.exp(-(dx * dx + dy * dy) / (2.0 * sigma * sigma))
    cells[..., 2] = dx * g * 0.2  # v_x
    cells[..., 3] = dy * g * 0.2  # v_y


# --- tests ------------------------------------------------------------------


_SINGLE_STEEL_BUDGET_MS = 5.0
_THREE_WATER_BUDGET_MS = 50.0


def test_kernel_substep_under_5ms_for_single_steel_body():
    """A lone steel ball substep must finish in < 5 ms median.

    Steel is the simplest path through the kernel: no fluid pressure /
    projection branch, no fracture (steel's brittle modulus is gated
    out), no remold.  This is the tightest possible budget — if the
    elasticity Laplacian or the input cleaning ever regresses, this
    fires first.
    """
    w = PhysicsWorld(world_bounds=(-200.0, -100.0, 200.0, 250.0))
    body = w.create_body(
        make_circle_silhouette(24), material="steel", position=(0.0, 0.0),
    )

    def reactivate() -> None:
        w._mark_active(body.root_hull_id)

    median_ms = _median_substep_ms(w, runs=10, reactivator=reactivate)
    assert median_ms < _SINGLE_STEEL_BUDGET_MS, (
        f"Single steel body kernel substep regressed: "
        f"median {median_ms:.2f} ms exceeds {_SINGLE_STEEL_BUDGET_MS:.1f} ms budget. "
        "Check for newly-introduced np.roll / per-substep astype copies."
    )


def test_kernel_substep_under_50ms_for_3_water_bodies():
    """Three water rectangles with divergent velocity: one substep < 50 ms.

    Water is the heaviest path — every fluid branch runs (pressure
    smoothing, divergence-free projection).  Three bodies × 10-iter SOR
    × full kernel landed around 4-6 ms median post-optimisation; the
    50 ms cap leaves plenty of CI slack while still trapping a
    10× regression.
    """
    w = PhysicsWorld(world_bounds=(-300.0, -200.0, 300.0, 250.0))
    bodies = []
    for x in (-150.0, 0.0, 150.0):
        b = w.create_body(
            make_rect_silhouette(48, 32), material="water",
            position=(x, 100.0), fixed=False,
        )
        bodies.append(b)
    for b in bodies:
        _stamp_divergence(b)

    def reactivate() -> None:
        for b in bodies:
            w._mark_active(b.root_hull_id)

    median_ms = _median_substep_ms(w, runs=10, reactivator=reactivate)
    assert median_ms < _THREE_WATER_BUDGET_MS, (
        f"Three water bodies kernel substep regressed: "
        f"median {median_ms:.2f} ms exceeds {_THREE_WATER_BUDGET_MS:.1f} ms budget."
    )


def test_kernel_cpu_gpu_parity_preserved():
    """Re-runs the steel-ball CPU/GPU parity check programmatically.

    Imports and runs ``test_gpu_matches_cpu_on_one_substep`` from the
    sibling ``test_gpu_kernel`` module.  If a wgpu adapter isn't
    available the test is skipped (consistent with the upstream
    skipif).  This is the perf-module's own contract that the
    optimisation work did not bend cell state away from the GPU.
    """
    try:
        from python.tests import test_gpu_kernel  # type: ignore[import-untyped]
    except ImportError:
        # Repo-relative path: tests live in ``python/tests`` but the
        # collected import root is usually ``python/`` so plain
        # ``import test_gpu_kernel`` is the conventional spelling.
        try:
            import test_gpu_kernel  # type: ignore[import-not-found]
        except ImportError:
            pytest.skip("Could not import sibling test_gpu_kernel module")
            return

    # Probe for GPU availability via the same helper the sibling uses.
    gpu_available = getattr(test_gpu_kernel, "_gpu_available", None)
    if callable(gpu_available) and not gpu_available():
        pytest.skip("No wgpu adapter present.")

    # Delegate — any AssertionError surfaces here.
    test_gpu_kernel.test_gpu_matches_cpu_on_one_substep()


def test_kernel_no_warnings_with_filter():
    """60 ``fluid_pool``-style frames must not raise a RuntimeWarning.

    Activates a filter that promotes every ``RuntimeWarning`` from
    ``pharos_engine.physics`` to an error — the same semantics as
    ``pytest -W error::RuntimeWarning:pharos_engine.physics``.  Catches
    regressions like an in-place ``np.clip(..., out=...)`` accidentally
    being called with an integer ``out`` or a float64 ``out`` against a
    float32 input, both of which numpy 1.24+ flags as a RuntimeWarning.
    """
    w = PhysicsWorld(world_bounds=(-160.0, -200.0, 160.0, 64.0))
    # A short, mixed scene: water pool below, steel impactor above.  The
    # steel ball drops into the pool over the 60 frames so every branch
    # of the kernel — elasticity, fluid, projection, write-back — is
    # exercised at least once.
    w.create_body(
        make_rect_silhouette(192, 24), material="water",
        position=(0.0, 30.0), fixed=False,
    )
    w.create_body(
        make_circle_silhouette(24), material="steel",
        position=(0.0, -20.0),
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        # Restrict to the pharos_engine.physics module so unrelated
        # third-party warnings (e.g. tracemalloc) don't fire.
        warnings.filterwarnings(
            "error", category=RuntimeWarning, module=r"pharos_engine\.physics.*",
        )
        for _ in range(60):
            w.step()
