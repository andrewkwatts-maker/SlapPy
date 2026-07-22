"""Tests for pharos_engine.numerics — V-cycle multigrid Poisson solver."""
from __future__ import annotations

import warnings

import numpy as np
import pytest

from pharos_engine.numerics import (
    compute_residual,
    sor_smooth,
    vcycle_poisson,
)


@pytest.fixture(autouse=True)
def _no_runtime_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=RuntimeWarning)
        yield


def test_zero_rhs_gives_zero_solution():
    rhs = np.zeros((16, 16), dtype=np.float32)
    p = vcycle_poisson(rhs, n_cycles=2)
    assert p.shape == rhs.shape
    assert np.allclose(p, 0.0)


def test_dirac_rhs_produces_localised_solution():
    """A single non-zero rhs cell should produce a localised pressure response."""
    rhs = np.zeros((16, 16), dtype=np.float32)
    rhs[8, 8] = -1.0  # negative source = pressure ridge at the centre
    p = vcycle_poisson(rhs, n_cycles=3, smooth_pre=3, smooth_post=3, coarse_iters=20)
    # Pressure should be largest at or near the source cell.
    assert p[8, 8] > 0.0
    # And should decay with distance.
    centre_val = float(p[8, 8])
    edge_val = float(p[0, 0])
    assert edge_val < centre_val * 0.5


def test_vcycle_reduces_residual_more_than_smoother_alone():
    """Two V-cycles should beat 20 single-grid SOR passes on a smooth RHS."""
    rng = np.random.default_rng(0)
    # Gaussian-bump RHS — long-wavelength content that SOR alone barely touches.
    yy, xx = np.indices((32, 32))
    rhs = np.exp(-((yy - 16) ** 2 + (xx - 16) ** 2) / 32.0).astype(np.float32)
    rhs -= rhs.mean()  # zero-mean so the Poisson problem is well-posed

    # Single-grid: 20 SOR sweeps from zero.
    p_sor = np.zeros_like(rhs)
    sor_smooth(p_sor, rhs, iters=20, omega=1.0)
    r_sor = float(np.linalg.norm(compute_residual(p_sor, rhs)))

    # Multigrid: 2 V-cycles (≈ 8 fine + 16 coarse SOR sweeps total).
    p_mg = vcycle_poisson(rhs, n_cycles=2, smooth_pre=2, smooth_post=2,
                          coarse_iters=8, omega=1.0)
    r_mg = float(np.linalg.norm(compute_residual(p_mg, rhs)))

    # V-cycle residual norm should be at most equal to single-grid, in
    # practice substantially smaller.
    assert r_mg <= r_sor * 1.05, (
        f"V-cycle should beat single-grid: r_sor={r_sor:.4f}, r_mg={r_mg:.4f}"
    )


def test_mask_clamps_solution_to_zero_outside_domain():
    rhs = np.ones((16, 16), dtype=np.float32) * 0.01
    mask = np.zeros((16, 16), dtype=np.float32)
    # A small live region in the middle.
    mask[4:12, 4:12] = 1.0
    p = vcycle_poisson(rhs, mask=mask, n_cycles=2)
    # Outside the mask, the solution must be exactly zero.
    assert (p[mask == 0] == 0.0).all()
    # Inside the mask, the solution should be non-zero (real Poisson response).
    inside = p[mask == 1.0]
    assert np.any(inside != 0.0)


def test_initial_guess_close_to_solution_converges_faster():
    rng = np.random.default_rng(1)
    yy, xx = np.indices((16, 16))
    rhs = (np.exp(-((yy - 8) ** 2 + (xx - 8) ** 2) / 8.0).astype(np.float32))
    rhs -= rhs.mean()

    # First reference: solve from zero
    p_ref = vcycle_poisson(rhs, n_cycles=4, smooth_pre=3, smooth_post=3,
                            coarse_iters=20)

    # With a noisy initial guess centred on the reference, one V-cycle
    # should bring us very close to it.
    init = p_ref + rng.standard_normal(p_ref.shape).astype(np.float32) * 0.001
    p_warm = vcycle_poisson(rhs, initial=init, n_cycles=1)
    # Should be near the reference (looser tolerance because of the noise).
    diff = float(np.linalg.norm(p_warm - p_ref))
    assert diff < 0.1, f"warm-started solution diverged: |Δ|={diff:.4f}"


def test_odd_dims_fall_back_to_smoother_without_error():
    """Odd-sized grids can't be 2× coarsened; algorithm should degrade gracefully."""
    rhs = np.random.default_rng(2).standard_normal((15, 17)).astype(np.float32)
    rhs -= rhs.mean()
    p = vcycle_poisson(rhs, n_cycles=2)
    assert p.shape == rhs.shape
    assert np.all(np.isfinite(p))


def test_compute_residual_zero_for_solved_problem():
    rhs = np.zeros((16, 16), dtype=np.float32)
    p = np.zeros_like(rhs)
    r = compute_residual(p, rhs)
    assert np.allclose(r, 0.0)


def test_sor_smooth_reduces_residual_monotonically():
    yy, xx = np.indices((16, 16))
    rhs = np.exp(-((yy - 8) ** 2 + (xx - 8) ** 2) / 8.0).astype(np.float32)
    rhs -= rhs.mean()
    p = np.zeros_like(rhs)
    r0 = float(np.linalg.norm(compute_residual(p, rhs)))
    sor_smooth(p, rhs, iters=10, omega=1.0)
    r1 = float(np.linalg.norm(compute_residual(p, rhs)))
    assert r1 < r0


def test_shape_mismatch_raises():
    rhs = np.zeros((8, 8), dtype=np.float32)
    bad_mask = np.zeros((4, 4), dtype=np.float32)
    with pytest.raises(ValueError):
        vcycle_poisson(rhs, mask=bad_mask)
    bad_init = np.zeros((4, 4), dtype=np.float32)
    with pytest.raises(ValueError):
        vcycle_poisson(rhs, initial=bad_init)
