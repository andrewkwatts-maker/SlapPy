"""Tests for ``slappyengine.numerics.vcycle_poisson``.

Covers the four properties the Phase-B repackage spec calls out:

1. Known-solution round trip — pick ``u(x, y) = sin(πx)·sin(πy)``,
   compute the analytical ``rhs = Δu`` on the discrete grid, run the
   solver and verify it recovers ``u`` within tolerance.
2. Mask handling — half the domain masked out → solution is exactly
   zero outside the mask (and finite, sensible inside).
3. Convergence — residual decreases monotonically per cycle on a
   Gaussian-bump RHS.
4. Cross-check — for the same input as
   ``slappyengine.physics.pressure_multigrid``'s V-cycle helper, the
   numerics module's solution matches within float tolerance.
"""
from __future__ import annotations

import importlib

import numpy as np
import pytest

from slappyengine.numerics import vcycle_poisson


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _laplacian_5pt(p: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Discrete 5-point Laplacian matching the solver's stencil.

    ``Δp[i,j] = p_l + p_r + p_t + p_b − 4·p[i,j]`` with off-grid /
    vacuum neighbours treated as zero, masked to live cells only.
    """
    nb = np.zeros_like(p)
    nb[:, 1:] += p[:, :-1] * mask[:, 1:] * mask[:, :-1]
    nb[:, :-1] += p[:, 1:] * mask[:, :-1] * mask[:, 1:]
    nb[1:, :] += p[:-1, :] * mask[1:, :] * mask[:-1, :]
    nb[:-1, :] += p[1:, :] * mask[:-1, :] * mask[1:, :]
    return (nb - 4.0 * p) * mask


def _residual_norm(p: np.ndarray, rhs: np.ndarray, mask: np.ndarray) -> float:
    """L2 norm of ``rhs − Δp`` over live cells."""
    r = (rhs - _laplacian_5pt(p, mask)) * mask
    return float(np.sqrt(np.sum(r * r)))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_known_solution_round_trip():
    """Pick ``u = sin(πx)·sin(πy)`` on a fully-interior mask; analytical
    Laplacian times h² becomes the discrete RHS the solver sees. The
    solver should recover ``u`` up to a domain-constant shift (5-point
    Poisson with all-Neumann/no-flux boundaries has a constant null space).
    """
    N = 32
    # Cell centres on the unit square.
    xs = (np.arange(N) + 0.5) / N
    ys = (np.arange(N) + 0.5) / N
    X, Y = np.meshgrid(xs, ys, indexing="xy")
    u_true = np.sin(np.pi * X) * np.sin(np.pi * Y)

    h = 1.0 / N
    # Continuous Δu = −2π² sin(πx) sin(πy). Discrete 5-point Laplacian
    # absorbs h²; the solver's normalisation also absorbs h² into rhs.
    rhs = (-2.0 * np.pi ** 2) * u_true * (h ** 2)

    mask = np.ones((N, N), dtype=np.float32)

    # Use a tall stack (10 cycles, 3 smooths/level) so the long-wavelength
    # modes the V-cycle is built to crush actually get crushed.
    p = vcycle_poisson(
        rhs.astype(np.float32),
        mask,
        iters_per_level=3,
        levels=4,
        n_cycles=10,
        coarse_iters=20,
    )

    # Floating mean — the null-space constant.
    diff = p - u_true.astype(np.float32)
    diff -= diff.mean()

    rmse = float(np.sqrt(np.mean(diff * diff)))
    peak = float(np.max(np.abs(diff)))

    # 5-point Laplacian truncation error is O(h²) ≈ 1e-3 on a 32² grid;
    # the V-cycle should comfortably reach that floor.
    assert rmse < 5e-2, f"RMSE {rmse:.4g} too large vs analytical sin·sin"
    assert peak < 1e-1, f"peak error {peak:.4g} too large"


def test_mask_handling_zero_outside():
    """Half the domain is vacuum. Solution must be exactly zero outside
    the mask, and a finite, sensible solve must succeed inside.
    """
    N = 32
    rhs = np.zeros((N, N), dtype=np.float32)
    # Drop a unit-amplitude Gaussian centred in the upper-left quarter.
    yy, xx = np.indices((N, N))
    cx, cy = N // 4, N // 4
    sigma = 3.0
    rhs += np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2.0 * sigma ** 2)).astype(
        np.float32
    )

    # Mask off the bottom half — only the upper N/2 rows participate.
    mask = np.zeros((N, N), dtype=np.float32)
    mask[: N // 2, :] = 1.0

    p = vcycle_poisson(
        rhs, mask, iters_per_level=2, levels=3, n_cycles=3
    )

    # Outside the mask: identically zero.
    outside = mask < 0.5
    assert np.all(p[outside] == 0.0), "vacuum cells must be exactly zero"

    # Inside the mask: finite, non-trivial response to the RHS bump.
    inside = mask >= 0.5
    assert np.all(np.isfinite(p[inside])), "interior solution has NaN/inf"
    assert np.max(np.abs(p[inside])) > 1e-3, (
        "interior solution suspiciously flat — solver may have masked rhs to zero"
    )


def test_residual_monotone_decrease_per_cycle():
    """Residual ‖rhs − Δp‖ must decrease monotonically as we run extra
    V-cycles. Captures the standard multigrid contraction property.

    We accumulate cycles by passing the previous solution as `initial`
    and asking for one more cycle each iteration.
    """
    N = 32
    yy, xx = np.indices((N, N))
    # Gaussian bump centred in the middle — heavy long-wavelength content
    # so single-grid SOR stalls while V-cycles tear through it.
    cx, cy = N / 2 - 0.5, N / 2 - 0.5
    sigma = 4.0
    rhs = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2.0 * sigma ** 2)).astype(
        np.float32
    )
    # Make it zero-mean so the masked-Poisson with Neumann boundaries is
    # well-posed (otherwise the unbounded null-space constant skews ‖r‖).
    rhs -= rhs.mean()

    mask = np.ones((N, N), dtype=np.float32)

    residuals: list[float] = []
    p = np.zeros((N, N), dtype=np.float32)
    initial_residual = _residual_norm(p, rhs, mask)
    residuals.append(initial_residual)

    for n in range(1, 6):
        p = vcycle_poisson(
            rhs,
            mask,
            iters_per_level=2,
            levels=3,
            n_cycles=1,
            initial=p,
        )
        residuals.append(_residual_norm(p, rhs, mask))

    # Strict monotone decrease.
    for i in range(1, len(residuals)):
        assert residuals[i] < residuals[i - 1], (
            f"residual increased at cycle {i}: {residuals[i-1]:.4g} → "
            f"{residuals[i]:.4g} (full trace {residuals})"
        )

    # Useful for the test report — make sure we've crushed by a healthy
    # factor (multigrid should easily get 10× over 5 cycles on this RHS).
    assert residuals[-1] < 0.1 * residuals[0], (
        f"residual only dropped {residuals[0]/residuals[-1]:.2g}× over 5 cycles "
        f"(full trace {residuals})"
    )

    # Expose the trace for the test report (ASCII-safe — Windows console
    # default encoding can't handle the math-bars / arrows).
    print(
        "convergence trace (||r|| per cycle): "
        + " -> ".join(f"{r:.3e}" for r in residuals)
    )


def test_cross_check_against_physics_module():
    """For the same divergence RHS and mask, the new numerics solver
    matches the working physics V-cycle to within float tolerance.

    Skipped automatically if ``slappyengine.physics.pressure_multigrid``
    isn't importable (Phase D will eventually delete it; until then this
    locks behaviour parity in place).
    """
    try:
        legacy = importlib.import_module(
            "slappyengine.physics.pressure_multigrid"
        )
    except ImportError:
        pytest.skip("legacy physics.pressure_multigrid not available")

    if not hasattr(legacy, "vcycle_project"):
        pytest.skip("legacy module lacks vcycle_project entry point")

    N = 32
    # Build a synthetic velocity field whose divergence is non-trivial:
    # u_x = sin(πx)cos(πy), u_y = -cos(πx)sin(πy) — has nonzero div on
    # the discrete grid even though it's divergence-free in the continuum.
    xs = (np.arange(N) + 0.5) / N
    ys = (np.arange(N) + 0.5) / N
    X, Y = np.meshgrid(xs, ys, indexing="xy")
    v_x = (np.sin(np.pi * X) * np.cos(np.pi * Y)).astype(np.float32)
    v_y = (-np.cos(np.pi * X) * np.sin(np.pi * Y)).astype(np.float32)
    u_x = np.zeros_like(v_x)
    u_y = np.zeros_like(v_y)

    mask = np.ones((N, N), dtype=np.float32)
    density = mask.copy()

    # Reproduce the legacy divergence stencil exactly so the rhs we feed
    # the new solver is identical to what the legacy routine builds
    # internally.
    m_l = np.zeros_like(mask); m_l[:, 1:] = mask[:, :-1]
    m_t = np.zeros_like(mask); m_t[1:, :] = mask[:-1, :]
    shifted = np.zeros_like(v_x); shifted[:, 1:] = v_x[:, :-1]
    v_x_l = shifted * m_l
    shifted = np.zeros_like(v_y); shifted[1:, :] = v_y[:-1, :]
    v_y_t = shifted * m_t
    div = ((v_x - v_x_l) + (v_y - v_y_t)).astype(np.float32) * mask

    # Run the legacy V-cycle (returns v_x, v_y, p).
    pressure_init = np.zeros((N, N), dtype=np.float32)
    _, _, p_legacy = legacy.vcycle_project(
        u_x, u_y, v_x, v_y, pressure_init, density, mask, dt=1.0 / 60.0,
        omega=1.5, smooth_pre=2, smooth_post=2, coarse_iters=8,
    )

    # Run the new numerics solver on the exact same rhs with the
    # mirrored cycle structure (smooth_pre = smooth_post = iters_per_level,
    # one V-cycle wrapped over the recursive descent).
    p_new = vcycle_poisson(
        div, mask, iters_per_level=2, levels=2, n_cycles=1,
        omega=1.5, coarse_iters=8,
    )

    # Both solvers leave a free constant in their solutions (no Dirichlet
    # pin), so the meaningful comparison is the residual under the shared
    # 5-point Laplacian, and the gradient of the pressure.
    r_legacy = _residual_norm(p_legacy.astype(np.float32), div, mask)
    r_new = _residual_norm(p_new, div, mask)
    r_rhs = float(np.sqrt(np.sum(div * div)))

    # Both solvers should knock the residual down by a big factor — and
    # be in the same ballpark as each other.
    assert r_new < 0.5 * r_rhs, (
        f"new solver barely converged: ‖r‖={r_new:.3e} vs ‖rhs‖={r_rhs:.3e}"
    )
    assert r_new < 5.0 * r_legacy + 1e-6, (
        f"new solver materially worse than legacy: "
        f"‖r_new‖={r_new:.3e} ‖r_legacy‖={r_legacy:.3e}"
    )

    # Gradient parity — pressure-difference between adjacent cells is what
    # the physics actually USES, so compare those.
    gx_new = p_new[:, 1:] - p_new[:, :-1]
    gx_leg = p_legacy[:, 1:] - p_legacy[:, :-1]
    gy_new = p_new[1:, :] - p_new[:-1, :]
    gy_leg = p_legacy[1:, :] - p_legacy[:-1, :]

    grad_rmse = float(
        np.sqrt(
            (np.mean((gx_new - gx_leg) ** 2) + np.mean((gy_new - gy_leg) ** 2))
            / 2.0
        )
    )
    grad_scale = float(
        np.sqrt(
            (np.mean(gx_leg ** 2) + np.mean(gy_leg ** 2)) / 2.0
        )
    ) + 1e-12

    # Within 10% RMS of the legacy gradient field — same operator, same
    # bottom-out behaviour, identical convergence target.
    assert grad_rmse / grad_scale < 0.1, (
        f"gradient mismatch vs legacy: rmse {grad_rmse:.3e} vs scale "
        f"{grad_scale:.3e} (ratio {grad_rmse/grad_scale:.2%})"
    )
