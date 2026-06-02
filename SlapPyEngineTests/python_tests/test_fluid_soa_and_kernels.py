"""Direct unit tests for the fluid SoA + 2D PBF kernels.

Independent of the integrated PBF smoke tests — these pin the math of
the Macklin 2013 poly6 and spiky-gradient kernels at the 2D
normalisation we use.
"""
from __future__ import annotations

import warnings

import numpy as np
import pytest

from slappyengine.fluid import (
    LAVA,
    MATERIALS,
    SAND,
    WATER,
    FluidMaterial,
    ParticleSoA,
    poly6,
    poly6_coefficient,
    spiky_grad,
    spiky_grad_coefficient,
)


@pytest.fixture(autouse=True)
def _no_runtime_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=RuntimeWarning)
        yield


# ── 2D poly6 kernel ─────────────────────────────────────────────────────────


def test_poly6_zero_at_kernel_radius():
    h = 0.2
    r_sq = np.asarray([h * h], dtype=np.float32)
    assert float(poly6(r_sq, h)[0]) == 0.0


def test_poly6_zero_beyond_kernel_radius():
    h = 0.2
    r_sq = np.asarray([(h * 1.5) ** 2], dtype=np.float32)
    assert float(poly6(r_sq, h)[0]) == 0.0


def test_poly6_positive_inside_kernel_radius():
    h = 0.2
    r_sq = np.asarray([(h * 0.5) ** 2], dtype=np.float32)
    val = float(poly6(r_sq, h)[0])
    assert val > 0.0
    # Compare against the analytic value: 4/(π h⁸) · (h² - r²)³.
    expected = (4.0 / (np.pi * h ** 8)) * ((h * h - (h * 0.5) ** 2) ** 3)
    assert val == pytest.approx(expected, rel=1e-4)


def test_poly6_peaks_at_zero():
    """The peak value of poly6(0, h) = 4/(π·h²) — used as the self-weight."""
    h = 0.2
    val = float(poly6(np.asarray([0.0], dtype=np.float32), h)[0])
    expected = 4.0 / (np.pi * h * h)
    assert val == pytest.approx(expected, rel=1e-4)


def test_poly6_coefficient_matches_2d_normalisation():
    """The 2D normalisation we use is 4/(π·h⁸). Pin it explicitly."""
    h = 0.3
    assert poly6_coefficient(h) == pytest.approx(4.0 / (np.pi * h ** 8), rel=1e-7)


def test_poly6_scalar_matches_array_form():
    """The scalar convenience must give identical numbers to the array form."""
    from slappyengine.fluid.kernels import poly6_scalar
    h = 0.2
    for r in (0.0, 0.05, 0.1, h):
        scalar_val = poly6_scalar(r * r, h)
        array_val = float(poly6(np.asarray([r * r], dtype=np.float32), h)[0])
        assert scalar_val == pytest.approx(array_val, abs=1.0e-4)


def test_poly6_handles_negative_r_squared_defensively():
    h = 0.2
    r_sq = np.asarray([-0.01], dtype=np.float32)
    assert float(poly6(r_sq, h)[0]) == 0.0


# ── 2D spiky gradient ──────────────────────────────────────────────────────


def test_spiky_grad_zero_at_r_zero():
    h = 0.2
    delta = np.asarray([[0.0, 0.0]], dtype=np.float32)
    r = np.asarray([0.0], dtype=np.float32)
    out = spiky_grad(delta, r, h, eps=1e-9)
    # At r=0 the spiky kernel's gradient is undefined; we explicitly return 0.
    assert np.allclose(out, 0.0)


def test_spiky_grad_zero_beyond_kernel_radius():
    h = 0.2
    delta = np.asarray([[h * 1.5, 0.0]], dtype=np.float32)
    r = np.asarray([h * 1.5], dtype=np.float32)
    assert np.allclose(spiky_grad(delta, r, h, eps=1e-9), 0.0)


def test_spiky_grad_points_along_delta_inside():
    h = 0.2
    # A particle pair separated by 0.1 along +x.
    delta = np.asarray([[0.1, 0.0]], dtype=np.float32)
    r = np.asarray([0.1], dtype=np.float32)
    out = spiky_grad(delta, r, h, eps=1e-9)
    # x component should be non-zero, y component zero. Sign is negative
    # (-30 / πh⁵ coefficient).
    assert out[0, 0] < 0.0
    assert float(out[0, 1]) == 0.0


def test_spiky_grad_coefficient_matches_2d_normalisation():
    """The 2D spiky-gradient normalisation is -30/(π·h⁵)."""
    h = 0.3
    assert spiky_grad_coefficient(h) == pytest.approx(-30.0 / (np.pi * h ** 5), rel=1e-7)


def test_spiky_grad_magnitude_decreases_toward_kernel_edge():
    """The kernel's gradient magnitude should be largest near r→0 and
    fall to zero at r=h."""
    h = 0.2
    rs = np.asarray([0.02, 0.05, 0.10, 0.15, 0.19], dtype=np.float32)
    mags = []
    for r_val in rs:
        delta = np.asarray([[float(r_val), 0.0]], dtype=np.float32)
        r = np.asarray([float(r_val)], dtype=np.float32)
        out = spiky_grad(delta, r, h, eps=1e-9)
        mags.append(float(abs(out[0, 0])))
    # Magnitudes must be strictly decreasing.
    for i in range(len(mags) - 1):
        assert mags[i] > mags[i + 1], (
            f"spiky grad not monotonic at r={rs[i]}: {mags[i]} not > {mags[i+1]}"
        )


# ── ParticleSoA ─────────────────────────────────────────────────────────────


def test_empty_particle_soa_has_count_zero():
    p = ParticleSoA()
    assert p.count == 0
    assert p.temperature.shape == (0,)
    assert p.material_id.shape == (0,)


def test_particle_soa_append_default_temperature():
    p = ParticleSoA()
    pos = np.asarray([[0.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    p.append(pos=pos, mass=1.0, material_id=0)
    # Default temperature is 20°C.
    assert (p.temperature == 20.0).all()


def test_particle_soa_append_explicit_temperature():
    p = ParticleSoA()
    pos = np.asarray([[0.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    p.append(pos=pos, mass=1.0, material_id=0, temperature=1500.0)
    assert (p.temperature == 1500.0).all()


def test_particle_soa_inv_mass_reciprocal():
    p = ParticleSoA()
    pos = np.asarray([[0.0, 0.0]], dtype=np.float32)
    p.append(pos=pos, mass=4.0, material_id=0)
    assert p.inv_mass[0] == pytest.approx(0.25, rel=1e-5)


def test_particle_soa_velocity_broadcast():
    """A scalar velocity (1, 2) is broadcast across the appended block."""
    p = ParticleSoA()
    pos = np.zeros((3, 2), dtype=np.float32)
    vel = np.asarray([[2.0, -1.0]], dtype=np.float32)
    p.append(pos=pos, mass=1.0, vel=vel)
    assert np.allclose(p.vel, [[2.0, -1.0], [2.0, -1.0], [2.0, -1.0]])


def test_particle_soa_prev_pos_initialised_to_pos():
    p = ParticleSoA()
    pos = np.asarray([[3.0, 5.0]], dtype=np.float32)
    p.append(pos=pos, mass=1.0)
    assert np.allclose(p.prev_pos, pos)


# ── Fluid material catalog ──────────────────────────────────────────────────


def test_fluid_materials_canonical_set():
    expected = {"water", "sand", "gravel", "dust", "lava", "ice", "stone"}
    assert expected.issubset(set(MATERIALS.keys()))


def test_each_fluid_material_has_physical_fields():
    for name, mat in MATERIALS.items():
        assert isinstance(mat, FluidMaterial), f"{name} is not a FluidMaterial"
        assert mat.name == name
        assert mat.rest_density > 0
        assert mat.kernel_radius > 0
        assert mat.relaxation_eps > 0
        assert 0.0 <= mat.viscosity <= 1.0
        assert mat.surface_tension >= 0.0
        assert mat.particle_mass > 0
        assert 0.0 <= mat.friction_coef <= 2.0
        # If thermal coupling is enabled it must be non-negative.
        assert mat.thermal_conductivity >= 0.0


def test_water_freezes_to_ice():
    assert WATER.freeze_to == "ice"
    assert WATER.freeze_temperature == 0.0
    # The freeze target must exist in the catalog.
    assert WATER.freeze_to in MATERIALS


def test_lava_freezes_to_stone():
    assert LAVA.freeze_to == "stone"
    assert LAVA.freeze_to in MATERIALS


def test_sand_is_granular_but_water_is_not():
    assert SAND.is_granular
    assert SAND.friction_coef > 0.0
    assert not WATER.is_granular
    assert WATER.friction_coef == 0.0
