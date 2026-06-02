"""Tests for slappyengine.pixel_material — PixelMaterialMap and MaterialFlags."""
from __future__ import annotations
import numpy as np
import pytest

from slappyengine.pixel_material import MaterialFlags, PixelMaterialMap


# ---------------------------------------------------------------------------
# Basic construction
# ---------------------------------------------------------------------------

def test_default_map_all_ones_strength():
    """Fresh map should have strength=1.0 across all pixels."""
    m = PixelMaterialMap(32, 16)
    assert m._data.shape == (16, 32, 4)
    assert np.allclose(m._data[:, :, 1], 1.0), "All strength values should be 1.0 by default"


# ---------------------------------------------------------------------------
# from_uniform
# ---------------------------------------------------------------------------

def test_from_uniform_sets_threshold():
    """threshold 80.0 with range (5, 200) should normalise to (80-5)/(200-5) ≈ 0.3846."""
    t_min, t_max = 5.0, 200.0
    m = PixelMaterialMap.from_uniform(8, 8, elastic_threshold=80.0, threshold_range=(t_min, t_max))
    expected_norm = (80.0 - t_min) / (t_max - t_min)
    assert np.allclose(m._data[:, :, 0], expected_norm, atol=1e-5)


# ---------------------------------------------------------------------------
# paint_rect
# ---------------------------------------------------------------------------

def test_paint_rect_modifies_region():
    """paint_rect should change strength inside rect and leave outside unchanged."""
    m = PixelMaterialMap(64, 64)
    # Paint a 10×10 block starting at (5, 5)
    m.paint_rect(5, 5, 10, 10, strength=0.25)
    # Inside: strength should be 0.25
    assert np.allclose(m._data[5:15, 5:15, 1], 0.25, atol=1e-6)
    # Outside (e.g., top-left corner): strength should still be 1.0
    assert np.allclose(m._data[0:5, 0:5, 1], 1.0, atol=1e-6)
    # Outside (bottom-right): strength should still be 1.0
    assert np.allclose(m._data[20:30, 20:30, 1], 1.0, atol=1e-6)


# ---------------------------------------------------------------------------
# paint_radial
# ---------------------------------------------------------------------------

def test_paint_radial_center_gets_full_value():
    """Center pixel of a radial paint should be very close to the target value."""
    m = PixelMaterialMap(64, 64)
    # Paint strength=0.1 at center (32, 32) with radius 10
    m.paint_radial(32, 32, 10, strength=0.1, falloff=True)
    # smoothstep at dist=0 → weight=1.0, so center should be ~0.1
    center_strength = m._data[32, 32, 1]
    assert abs(center_strength - 0.1) < 0.01, (
        f"Center pixel strength {center_strength:.4f} should be close to 0.1"
    )


def test_paint_radial_edge_gets_zero_falloff():
    """Pixels at exactly the radius edge should have near-zero weight applied."""
    m = PixelMaterialMap(64, 64)
    # Record original strength (1.0)
    original = m._data[32, 42, 1]  # pixel at distance ~10 from center
    m.paint_radial(32, 32, 10, strength=0.0, falloff=True)
    edge_strength = m._data[32, 42, 1]
    # dist=10, radius=10 → dist >= r → outside mask → weight=0 → unchanged
    assert abs(edge_strength - original) < 0.01, (
        f"Edge pixel at radius boundary should be nearly unchanged: {edge_strength:.4f}"
    )


# ---------------------------------------------------------------------------
# sample()
# ---------------------------------------------------------------------------

def test_sample_returns_correct_threshold():
    """Sampling a painted pixel should return the elastic_threshold in world units."""
    t_min, t_max = 5.0, 200.0
    m = PixelMaterialMap(32, 32, threshold_range=(t_min, t_max))
    # Paint a specific threshold value
    target = 150.0
    m.paint_rect(10, 10, 5, 5, elastic_threshold=target)
    result = m.sample(12, 12)
    assert abs(result["elastic_threshold"] - target) < 0.5, (
        f"Sampled elastic_threshold {result['elastic_threshold']:.2f} should be ~{target}"
    )


# ---------------------------------------------------------------------------
# Flags encode/decode
# ---------------------------------------------------------------------------

def test_flags_encode_decode():
    """Setting GLASS flag, then sampling should return flags containing GLASS."""
    m = PixelMaterialMap(16, 16)
    m.paint_rect(4, 4, 4, 4, flags=MaterialFlags.GLASS)
    result = m.sample(6, 6)
    flags = result["flags"]
    assert MaterialFlags.GLASS in flags, (
        f"GLASS flag should be set, got flags={flags!r}"
    )
    # Pixels outside the rect should have no flags
    outside = m.sample(0, 0)
    assert outside["flags"] == MaterialFlags.NONE


# ---------------------------------------------------------------------------
# as_uint8_rgba
# ---------------------------------------------------------------------------

def test_as_uint8_rgba_shape():
    """as_uint8_rgba should return correct shape and uint8 dtype."""
    m = PixelMaterialMap(20, 10)
    arr = m.as_uint8_rgba()
    assert arr.shape == (10, 20, 4), f"Expected (10, 20, 4), got {arr.shape}"
    assert arr.dtype == np.uint8, f"Expected uint8, got {arr.dtype}"
    # Values should be in valid range
    assert arr.min() >= 0
    assert arr.max() <= 255


# ---------------------------------------------------------------------------
# MaterialFlags enum
# ---------------------------------------------------------------------------

def test_material_flags_enum():
    """Check that flag values match the spec."""
    assert MaterialFlags.STRUCTURAL == 1
    assert MaterialFlags.GLASS == 2
    assert MaterialFlags.ORGANIC == 4
    assert MaterialFlags.NO_REPAIR == 8
    assert MaterialFlags.ARMOR == 16
    # Combination
    combined = MaterialFlags.STRUCTURAL | MaterialFlags.GLASS
    assert int(combined) == 3
    assert MaterialFlags.STRUCTURAL in combined
    assert MaterialFlags.GLASS in combined
    assert MaterialFlags.ARMOR not in combined
