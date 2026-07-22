"""Tests for pharos_engine.gpu.ibl_prefilter — KK5 Nova3D parity Sprint 12."""
from __future__ import annotations

import numpy as np
import pytest

from pharos_engine.gpu.ibl_prefilter import (
    PREFILTER_WGSL,
    PrefilterConfig,
    PrefilteredCubemap,
    WGSL_PATH,
    hammersley_samples,
    importance_sample_ggx,
    mip_roughness,
    prefilter_cubemap,
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def test_prefilter_config_defaults():
    cfg = PrefilterConfig()
    assert cfg.mip_count == 5
    assert cfg.base_resolution == 512
    assert cfg.sample_count == 512
    assert cfg.roughness_curve == "linear"


def test_prefilter_config_override():
    cfg = PrefilterConfig(mip_count=7, base_resolution=256, sample_count=64)
    assert cfg.mip_count == 7
    assert cfg.base_resolution == 256
    assert cfg.sample_count == 64


# ---------------------------------------------------------------------------
# mip_roughness curve
# ---------------------------------------------------------------------------

def test_mip_roughness_endpoints_five_mips():
    assert mip_roughness(0, 5) == pytest.approx(0.0)
    assert mip_roughness(4, 5) == pytest.approx(1.0)


def test_mip_roughness_monotonic():
    values = [mip_roughness(i, 5) for i in range(5)]
    assert values == sorted(values)
    for v in values:
        assert 0.0 <= v <= 1.0


def test_mip_roughness_single_mip():
    # Degenerate — a single mip must not divide by zero.
    assert mip_roughness(0, 1) == 0.0


# ---------------------------------------------------------------------------
# Hammersley sequence
# ---------------------------------------------------------------------------

def test_hammersley_shape():
    s = hammersley_samples(64)
    assert s.shape == (64, 2)
    assert s.dtype == np.float32


def test_hammersley_range():
    s = hammersley_samples(128)
    assert float(s.min()) >= 0.0
    assert float(s.max()) < 1.0


def test_hammersley_first_row_zero():
    # Index 0 always maps to (0, 0) — a nice regression sentinel.
    s = hammersley_samples(16)
    assert s[0, 0] == pytest.approx(0.0)
    assert s[0, 1] == pytest.approx(0.0)


def test_hammersley_zero_count():
    s = hammersley_samples(0)
    assert s.shape == (0, 2)


# ---------------------------------------------------------------------------
# GGX importance sampling
# ---------------------------------------------------------------------------

def test_importance_sample_ggx_returns_unit_vector():
    N = np.array([0.0, 0.0, 1.0])
    for u in (0.1, 0.3, 0.7):
        for v in (0.1, 0.5, 0.9):
            for r in (0.05, 0.4, 0.9):
                d = importance_sample_ggx(u, v, N, r)
                assert d.shape == (3,)
                assert np.linalg.norm(d) == pytest.approx(1.0, abs=1e-4)


def test_importance_sample_ggx_mirror_at_zero_roughness():
    # roughness ~0 must place the half-vector on the surface normal.
    N = np.array([0.0, 1.0, 0.0])
    d = importance_sample_ggx(0.25, 0.001, N, 0.001)
    # Very small roughness collapses the lobe onto N.
    assert float(np.dot(d, N)) > 0.99


def test_importance_sample_ggx_arbitrary_normal():
    # Random unit normal — output must still be unit length.
    N = np.array([1.0, 2.0, -3.0])
    N = N / np.linalg.norm(N)
    d = importance_sample_ggx(0.4, 0.6, N, 0.5)
    assert np.linalg.norm(d) == pytest.approx(1.0, abs=1e-4)


# ---------------------------------------------------------------------------
# Full CPU prefilter behaviour
# ---------------------------------------------------------------------------

def _constant_cube(color=(0.4, 0.6, 0.8), size=8):
    src = np.zeros((6, size, size, 3), dtype=np.float32)
    src[..., 0] = color[0]
    src[..., 1] = color[1]
    src[..., 2] = color[2]
    return src


def test_prefilter_constant_color_stays_constant():
    # A uniform environment must survive convolution at every mip.
    cfg = PrefilterConfig(mip_count=3, base_resolution=4, sample_count=32)
    src = _constant_cube(color=(0.25, 0.5, 0.75), size=8)
    chain = prefilter_cubemap(src, cfg)
    assert isinstance(chain, PrefilteredCubemap)
    assert len(chain.mip_levels) == 3
    for mip in chain.mip_levels:
        # Every texel in every face should equal the source colour.
        assert np.allclose(mip[..., 0], 0.25, atol=1e-2)
        assert np.allclose(mip[..., 1], 0.5, atol=1e-2)
        assert np.allclose(mip[..., 2], 0.75, atol=1e-2)


def test_prefilter_resolution_halves_per_mip():
    cfg = PrefilterConfig(mip_count=3, base_resolution=8, sample_count=16)
    src = _constant_cube(size=8)
    chain = prefilter_cubemap(src, cfg)
    resolutions = [m.shape[1] for m in chain.mip_levels]
    assert resolutions == [8, 4, 2]


def test_prefilter_roughness_ascends():
    cfg = PrefilterConfig(mip_count=5, base_resolution=4, sample_count=16)
    src = _constant_cube(size=8)
    chain = prefilter_cubemap(src, cfg)
    assert chain.roughness_per_mip == sorted(chain.roughness_per_mip)
    assert chain.roughness_per_mip[0] == pytest.approx(0.0)
    assert chain.roughness_per_mip[-1] == pytest.approx(1.0)


def test_prefilter_gradient_higher_mips_more_blurred():
    # A sharp bright spike on +X face should smear more as roughness rises.
    cfg = PrefilterConfig(mip_count=3, base_resolution=4, sample_count=64)
    src = np.zeros((6, 16, 16, 3), dtype=np.float32)
    src[0, 6:10, 6:10, :] = 4.0   # bright spike on +X
    chain = prefilter_cubemap(src, cfg)

    # Variance of +X face brightness should fall as roughness rises,
    # because the spike gets smeared into a broader lobe.
    variances = [float(np.var(m[0, ..., 0])) for m in chain.mip_levels]
    # Mip 0 is close-to-mirror; mip 2 is fully rough.
    assert variances[0] >= variances[-1] - 1e-6


def test_prefilter_alpha_is_one():
    cfg = PrefilterConfig(mip_count=2, base_resolution=4, sample_count=16)
    src = _constant_cube(size=8)
    chain = prefilter_cubemap(src, cfg)
    for mip in chain.mip_levels:
        assert np.allclose(mip[..., 3], 1.0)


def test_prefilter_rejects_wrong_shape():
    cfg = PrefilterConfig(mip_count=2, base_resolution=4, sample_count=16)
    bad = np.zeros((3, 4, 4, 3), dtype=np.float32)
    with pytest.raises(ValueError):
        prefilter_cubemap(bad, cfg)


# ---------------------------------------------------------------------------
# WGSL payload
# ---------------------------------------------------------------------------

def test_wgsl_shader_ships_as_file():
    assert WGSL_PATH.exists()
    assert WGSL_PATH.suffix == ".wgsl"


def test_wgsl_shader_has_compute_entry():
    assert "@compute" in PREFILTER_WGSL
    assert "fn main" in PREFILTER_WGSL


def test_wgsl_shader_declares_ggx_helpers():
    # The math must be present in the shader body so we catch drift
    # between the CPU + GPU implementations.
    assert "importance_sample_ggx" in PREFILTER_WGSL
    assert "hammersley" in PREFILTER_WGSL
    assert "radical_inverse_vdc" in PREFILTER_WGSL


def test_wgsl_byte_budget():
    # Sanity budget — keeps the shader honest without demanding
    # exact byte-perfection.  ~2000 target with headroom.
    n = len(PREFILTER_WGSL.encode("utf-8"))
    assert 1000 < n < 8192, f"shader is {n} bytes — outside budget"


def test_wgsl_matches_file_on_disk():
    on_disk = WGSL_PATH.read_text(encoding="utf-8")
    assert on_disk == PREFILTER_WGSL
