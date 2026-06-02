"""Input-validation tests for the public ``slappyengine.thermal`` API."""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.thermal import HeatField


# ---------------------------------------------------------------------------
# HeatField.__init__
# ---------------------------------------------------------------------------


def test_heatfield_rejects_non_ndarray_grid():
    with pytest.raises(TypeError, match="HeatField: grid"):
        HeatField([[0.0, 1.0], [2.0, 3.0]])  # type: ignore[arg-type]


def test_heatfield_rejects_one_d_grid():
    with pytest.raises(ValueError, match="HeatField: grid"):
        HeatField(np.zeros(16, dtype=np.float32))


def test_heatfield_rejects_integer_grid():
    with pytest.raises(TypeError, match="HeatField: grid"):
        HeatField(np.zeros((4, 4), dtype=np.int32))


def test_heatfield_rejects_too_small_grid():
    with pytest.raises(ValueError, match="2x2"):
        HeatField(np.zeros((1, 4), dtype=np.float32))


def test_heatfield_rejects_negative_conductivity():
    with pytest.raises(ValueError, match="conductivity"):
        HeatField(np.zeros((4, 4), dtype=np.float32), conductivity=-1.0)


def test_heatfield_rejects_inf_conductivity():
    with pytest.raises(ValueError, match="conductivity"):
        HeatField(np.zeros((4, 4), dtype=np.float32), conductivity=float("inf"))


def test_heatfield_rejects_diffusivity_above_one():
    with pytest.raises(ValueError, match="diffusivity"):
        HeatField(np.zeros((4, 4), dtype=np.float32), diffusivity=1.5)


def test_heatfield_rejects_zero_diffusivity():
    with pytest.raises(ValueError, match="diffusivity"):
        HeatField(np.zeros((4, 4), dtype=np.float32), diffusivity=0.0)


def test_heatfield_rejects_negative_diffusivity():
    with pytest.raises(ValueError, match="diffusivity"):
        HeatField(np.zeros((4, 4), dtype=np.float32), diffusivity=-0.1)


# ---------------------------------------------------------------------------
# HeatField.step
# ---------------------------------------------------------------------------


def test_step_rejects_unknown_boundary():
    f = HeatField(np.zeros((4, 4), dtype=np.float32))
    with pytest.raises(ValueError, match="boundary"):
        f.step(0.1, boundary="wrap")


def test_step_rejects_non_string_boundary():
    f = HeatField(np.zeros((4, 4), dtype=np.float32))
    with pytest.raises(TypeError, match="boundary"):
        f.step(0.1, boundary=42)  # type: ignore[arg-type]


def test_step_rejects_negative_dt():
    f = HeatField(np.zeros((4, 4), dtype=np.float32))
    with pytest.raises(ValueError, match="dt"):
        f.step(-0.1)


def test_step_rejects_nan_dt():
    f = HeatField(np.zeros((4, 4), dtype=np.float32))
    with pytest.raises(ValueError, match="dt"):
        f.step(float("nan"))


def test_step_rejects_string_dt():
    f = HeatField(np.zeros((4, 4), dtype=np.float32))
    with pytest.raises(TypeError, match="dt"):
        f.step("fast")  # type: ignore[arg-type]


def test_step_rejects_zero_substeps():
    f = HeatField(np.zeros((4, 4), dtype=np.float32))
    with pytest.raises(ValueError, match="substeps"):
        f.step(0.1, substeps=0)


def test_step_rejects_float_substeps():
    f = HeatField(np.zeros((4, 4), dtype=np.float32))
    with pytest.raises(TypeError, match="substeps"):
        f.step(0.1, substeps=2.5)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# HeatField.exchange_with
# ---------------------------------------------------------------------------


def test_exchange_with_rejects_non_heatfield_other():
    f = HeatField(np.zeros((4, 4), dtype=np.float32))
    with pytest.raises(TypeError, match="other"):
        f.exchange_with("not-a-field", [((0, 0), (0, 0))])  # type: ignore[arg-type]


def test_exchange_with_rejects_scalar_contact_pairs():
    f = HeatField(np.zeros((4, 4), dtype=np.float32))
    g = HeatField(np.zeros((4, 4), dtype=np.float32))
    with pytest.raises(TypeError, match="contact_pairs"):
        f.exchange_with(g, 42)  # type: ignore[arg-type]


def test_exchange_with_rejects_negative_dt():
    f = HeatField(np.zeros((4, 4), dtype=np.float32))
    g = HeatField(np.zeros((4, 4), dtype=np.float32))
    with pytest.raises(ValueError, match="dt"):
        f.exchange_with(g, [((0, 0), (0, 0))], dt=-1.0)


def test_exchange_with_rejects_negative_conductivity():
    f = HeatField(np.zeros((4, 4), dtype=np.float32))
    g = HeatField(np.zeros((4, 4), dtype=np.float32))
    with pytest.raises(ValueError, match="conductivity"):
        f.exchange_with(g, [((0, 0), (0, 0))], dt=0.1, conductivity=-1.0)


# ---------------------------------------------------------------------------
# Positive sanity — valid construction + step + exchange still work.
# ---------------------------------------------------------------------------


def test_positive_construct_and_step():
    T = np.full((4, 4), 20.0, dtype=np.float32)
    T[1, 1] = 100.0
    f = HeatField(T, conductivity=1.0, diffusivity=0.1)
    f.step(0.05, boundary="clamp")
    assert float(T[1, 1]) < 100.0


def test_positive_zero_conductivity_is_legal():
    # k = 0 means no flux; constructor must allow it.
    f = HeatField(np.zeros((4, 4), dtype=np.float32), conductivity=0.0)
    assert f.conductivity == 0.0


def test_positive_diffusivity_at_one_accepted():
    # Boundary: diffusivity == 1.0 is the upper edge of the allowed range.
    f = HeatField(np.zeros((4, 4), dtype=np.float32), diffusivity=1.0)
    assert f.diffusivity == 1.0


def test_positive_step_with_zero_dt_is_noop():
    T = np.full((4, 4), 5.0, dtype=np.float32)
    T_ref = T.copy()
    f = HeatField(T)
    f.step(0.0)
    assert np.array_equal(T, T_ref)


def test_positive_exchange_with_runs():
    a = np.full((4, 4), 100.0, dtype=np.float64)
    b = np.zeros((4, 4), dtype=np.float64)
    fa = HeatField(a, conductivity=1.0)
    fb = HeatField(b, conductivity=1.0)
    pairs = [((0, 0), (0, 0))]
    q = fa.exchange_with(fb, pairs, dt=0.1)
    assert q > 0.0
    assert a[0, 0] < 100.0
    assert b[0, 0] > 0.0
