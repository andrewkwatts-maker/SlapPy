"""Input-validation tests for the public ``slappyengine.numerics`` API."""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.numerics import (
    compute_residual,
    sor_smooth,
    vcycle_poisson,
)


# ---------------------------------------------------------------------------
# vcycle_poisson — array shape / type
# ---------------------------------------------------------------------------


def test_vcycle_rejects_non_ndarray_rhs():
    with pytest.raises(TypeError, match="vcycle_poisson: rhs"):
        vcycle_poisson([[1.0, 2.0], [3.0, 4.0]])  # type: ignore[arg-type]


def test_vcycle_rejects_one_d_rhs():
    rhs = np.zeros(16, dtype=np.float32)
    with pytest.raises(ValueError, match="vcycle_poisson: rhs"):
        vcycle_poisson(rhs)


def test_vcycle_rejects_three_d_rhs():
    rhs = np.zeros((4, 4, 4), dtype=np.float32)
    with pytest.raises(ValueError, match="vcycle_poisson: rhs"):
        vcycle_poisson(rhs)


def test_vcycle_rejects_mask_shape_mismatch():
    rhs = np.zeros((8, 8), dtype=np.float32)
    mask = np.ones((4, 4), dtype=np.float32)
    with pytest.raises(ValueError, match="mask"):
        vcycle_poisson(rhs, mask=mask)


def test_vcycle_rejects_initial_shape_mismatch():
    rhs = np.zeros((8, 8), dtype=np.float32)
    initial = np.zeros((4, 4), dtype=np.float32)
    with pytest.raises(ValueError, match="initial"):
        vcycle_poisson(rhs, initial=initial)


# ---------------------------------------------------------------------------
# vcycle_poisson — integer / range controls
# ---------------------------------------------------------------------------


def test_vcycle_rejects_float_iters_per_level():
    rhs = np.zeros((8, 8), dtype=np.float32)
    with pytest.raises(TypeError, match="iters_per_level"):
        vcycle_poisson(rhs, iters_per_level=2.5)  # type: ignore[arg-type]


def test_vcycle_rejects_zero_levels():
    rhs = np.zeros((8, 8), dtype=np.float32)
    with pytest.raises(ValueError, match="levels"):
        vcycle_poisson(rhs, levels=0)


def test_vcycle_rejects_zero_n_cycles():
    rhs = np.zeros((8, 8), dtype=np.float32)
    with pytest.raises(ValueError, match="n_cycles"):
        vcycle_poisson(rhs, n_cycles=0)


def test_vcycle_rejects_negative_n_cycles():
    rhs = np.zeros((8, 8), dtype=np.float32)
    with pytest.raises(ValueError, match="n_cycles"):
        vcycle_poisson(rhs, n_cycles=-3)


def test_vcycle_rejects_omega_at_zero():
    rhs = np.zeros((8, 8), dtype=np.float32)
    with pytest.raises(ValueError, match="omega"):
        vcycle_poisson(rhs, omega=0.0)


def test_vcycle_rejects_omega_at_two():
    rhs = np.zeros((8, 8), dtype=np.float32)
    with pytest.raises(ValueError, match="omega"):
        vcycle_poisson(rhs, omega=2.0)


def test_vcycle_rejects_negative_omega():
    rhs = np.zeros((8, 8), dtype=np.float32)
    with pytest.raises(ValueError, match="omega"):
        vcycle_poisson(rhs, omega=-1.0)


def test_vcycle_rejects_nan_omega():
    rhs = np.zeros((8, 8), dtype=np.float32)
    with pytest.raises(ValueError, match="omega"):
        vcycle_poisson(rhs, omega=float("nan"))


# ---------------------------------------------------------------------------
# sor_smooth
# ---------------------------------------------------------------------------


def test_sor_smooth_rejects_shape_mismatch():
    p = np.zeros((8, 8), dtype=np.float32)
    rhs = np.zeros((4, 4), dtype=np.float32)
    with pytest.raises(ValueError, match="rhs"):
        sor_smooth(p, rhs)


def test_sor_smooth_rejects_zero_iters():
    p = np.zeros((8, 8), dtype=np.float32)
    rhs = np.zeros((8, 8), dtype=np.float32)
    with pytest.raises(ValueError, match="iters"):
        sor_smooth(p, rhs, iters=0)


def test_sor_smooth_rejects_omega_out_of_range():
    p = np.zeros((8, 8), dtype=np.float32)
    rhs = np.zeros((8, 8), dtype=np.float32)
    with pytest.raises(ValueError, match="omega"):
        sor_smooth(p, rhs, omega=3.0)


def test_sor_smooth_rejects_non_ndarray_p():
    rhs = np.zeros((8, 8), dtype=np.float32)
    with pytest.raises(TypeError, match="sor_smooth: p"):
        sor_smooth([[0.0]], rhs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# compute_residual
# ---------------------------------------------------------------------------


def test_compute_residual_rejects_shape_mismatch():
    p = np.zeros((8, 8), dtype=np.float32)
    rhs = np.zeros((4, 4), dtype=np.float32)
    with pytest.raises(ValueError, match="rhs"):
        compute_residual(p, rhs)


def test_compute_residual_rejects_non_ndarray_rhs():
    p = np.zeros((8, 8), dtype=np.float32)
    with pytest.raises(TypeError, match="rhs"):
        compute_residual(p, [[0.0]])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Positive sanity
# ---------------------------------------------------------------------------


def test_positive_vcycle_default_mask_runs():
    rhs = np.zeros((8, 8), dtype=np.float32)
    out = vcycle_poisson(rhs)
    assert out.shape == (8, 8)
    assert out.dtype == np.float32


def test_positive_vcycle_omega_at_one_runs():
    rhs = np.zeros((8, 8), dtype=np.float32)
    out = vcycle_poisson(rhs, omega=1.0)
    assert out.shape == (8, 8)


def test_positive_sor_smooth_runs():
    p = np.ones((8, 8), dtype=np.float32)
    rhs = np.zeros((8, 8), dtype=np.float32)
    out = sor_smooth(p, rhs, iters=3, omega=1.5)
    assert out.shape == (8, 8)


def test_positive_compute_residual_zero_pressure_returns_rhs_in_mask():
    p = np.zeros((8, 8), dtype=np.float32)
    rhs = np.ones((8, 8), dtype=np.float32)
    res = compute_residual(p, rhs)
    # With p=0 the residual equals rhs over the masked cells.
    assert res.shape == (8, 8)
    assert np.allclose(res, 1.0)


def test_positive_vcycle_with_explicit_mask():
    rhs = np.zeros((8, 8), dtype=np.float32)
    mask = np.ones((8, 8), dtype=np.float32)
    out = vcycle_poisson(rhs, mask=mask)
    assert out.shape == (8, 8)
