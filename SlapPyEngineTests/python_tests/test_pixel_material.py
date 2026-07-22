"""Engine tests for PixelMaterialMap — per-pixel material texture."""
from __future__ import annotations
import numpy as np
import pytest


class TestPixelMaterialMapConstruction:
    def test_default_shape(self):
        from pharos_engine.pixel_material import PixelMaterialMap
        m = PixelMaterialMap(32, 16)
        assert m.width == 32
        assert m.height == 16
        assert m._data.shape == (16, 32, 4)

    def test_default_dtype_float32(self):
        from pharos_engine.pixel_material import PixelMaterialMap
        m = PixelMaterialMap(8, 8)
        assert m._data.dtype == np.float32

    def test_default_strength_one(self):
        from pharos_engine.pixel_material import PixelMaterialMap
        m = PixelMaterialMap(8, 8)
        assert float(m._data[0, 0, 1]) == pytest.approx(1.0)

    def test_from_uniform_threshold_stored(self):
        from pharos_engine.pixel_material import PixelMaterialMap
        m = PixelMaterialMap.from_uniform(16, 16, elastic_threshold=80.0,
                                          threshold_range=(5.0, 200.0))
        props = m.sample(8, 8)
        assert props["elastic_threshold"] == pytest.approx(80.0, rel=0.02)

    def test_from_uniform_flags_stored(self):
        from pharos_engine.pixel_material import PixelMaterialMap, MaterialFlags
        m = PixelMaterialMap.from_uniform(8, 8, flags=MaterialFlags.STRUCTURAL)
        props = m.sample(0, 0)
        assert MaterialFlags.STRUCTURAL in props["flags"]

    def test_from_uniform_strength_stored(self):
        from pharos_engine.pixel_material import PixelMaterialMap
        m = PixelMaterialMap.from_uniform(8, 8, strength=0.5)
        props = m.sample(0, 0)
        assert props["strength"] == pytest.approx(0.5, abs=0.02)


class TestPixelMaterialMapSample:
    def test_sample_clamps_out_of_bounds(self):
        from pharos_engine.pixel_material import PixelMaterialMap
        m = PixelMaterialMap(8, 8)
        # Sampling out of bounds should not raise
        props = m.sample(-5, -5)
        assert isinstance(props, dict)
        props2 = m.sample(100, 100)
        assert isinstance(props2, dict)

    def test_sample_returns_required_keys(self):
        from pharos_engine.pixel_material import PixelMaterialMap
        m = PixelMaterialMap(8, 8)
        props = m.sample(0, 0)
        assert "elastic_threshold" in props
        assert "strength" in props
        assert "repair_rate" in props
        assert "flags" in props

    def test_sample_threshold_within_range(self):
        from pharos_engine.pixel_material import PixelMaterialMap
        m = PixelMaterialMap(8, 8, threshold_range=(5.0, 200.0))
        props = m.sample(0, 0)
        assert 5.0 <= props["elastic_threshold"] <= 200.0


class TestPixelMaterialMapPaintRect:
    def test_paint_rect_sets_threshold(self):
        from pharos_engine.pixel_material import PixelMaterialMap
        m = PixelMaterialMap(32, 32, threshold_range=(0.0, 100.0))
        m.paint_rect(0, 0, 10, 10, elastic_threshold=50.0)
        props = m.sample(5, 5)
        assert props["elastic_threshold"] == pytest.approx(50.0, abs=1.0)

    def test_paint_rect_sets_strength(self):
        from pharos_engine.pixel_material import PixelMaterialMap
        m = PixelMaterialMap(32, 32)
        m.paint_rect(0, 0, 16, 16, strength=0.2)
        props = m.sample(8, 8)
        assert props["strength"] == pytest.approx(0.2, abs=0.01)

    def test_paint_rect_out_of_bounds_no_crash(self):
        from pharos_engine.pixel_material import PixelMaterialMap
        m = PixelMaterialMap(32, 32)
        m.paint_rect(-10, -10, 5, 5, strength=0.5)
        m.paint_rect(100, 100, 10, 10, strength=0.5)

    def test_paint_rect_sets_flags(self):
        from pharos_engine.pixel_material import PixelMaterialMap, MaterialFlags
        m = PixelMaterialMap(16, 16)
        m.paint_rect(0, 0, 8, 8, flags=MaterialFlags.GLASS)
        props = m.sample(4, 4)
        assert MaterialFlags.GLASS in props["flags"]


class TestPixelMaterialMapPaintRadial:
    def test_paint_radial_centre_gets_value(self):
        from pharos_engine.pixel_material import PixelMaterialMap
        m = PixelMaterialMap(64, 64, threshold_range=(0.0, 100.0))
        m.paint_radial(32.0, 32.0, radius=10.0, elastic_threshold=20.0)
        props = m.sample(32, 32)
        assert props["elastic_threshold"] < 50.0  # painted toward 20

    def test_paint_radial_outside_unchanged(self):
        from pharos_engine.pixel_material import PixelMaterialMap
        m = PixelMaterialMap(64, 64)
        original_strength = m.sample(60, 60)["strength"]
        m.paint_radial(5.0, 5.0, radius=3.0, strength=0.1)
        assert m.sample(60, 60)["strength"] == pytest.approx(original_strength)

    def test_paint_radial_no_falloff_uniform(self):
        from pharos_engine.pixel_material import PixelMaterialMap
        m = PixelMaterialMap(64, 64)
        m.paint_radial(32.0, 32.0, radius=5.0, strength=0.1, falloff=False)
        # Centre and near-edge should be equally painted
        centre = m.sample(32, 32)["strength"]
        near_edge = m.sample(36, 32)["strength"]
        # Both should be painted uniformly (both < 1.0)
        assert centre < 1.0
        assert near_edge < 1.0


class TestPixelMaterialMapOutput:
    def test_as_uint8_rgba_shape(self):
        from pharos_engine.pixel_material import PixelMaterialMap
        m = PixelMaterialMap(16, 8)
        out = m.as_uint8_rgba()
        assert out.shape == (8, 16, 4)
        assert out.dtype == np.uint8

    def test_as_uint8_rgba_values_in_range(self):
        from pharos_engine.pixel_material import PixelMaterialMap
        m = PixelMaterialMap(8, 8)
        out = m.as_uint8_rgba()
        assert int(out.min()) >= 0
        assert int(out.max()) <= 255

    def test_data_property_returns_array(self):
        from pharos_engine.pixel_material import PixelMaterialMap
        m = PixelMaterialMap(8, 8)
        assert isinstance(m.data, np.ndarray)
        assert m.data.shape == (8, 8, 4)


class TestMaterialFlags:
    def test_structural_flag_value(self):
        from pharos_engine.pixel_material import MaterialFlags
        assert MaterialFlags.STRUCTURAL == 1

    def test_glass_flag_value(self):
        from pharos_engine.pixel_material import MaterialFlags
        assert MaterialFlags.GLASS == 2

    def test_combined_flags(self):
        from pharos_engine.pixel_material import MaterialFlags
        combined = MaterialFlags.STRUCTURAL | MaterialFlags.GLASS
        assert MaterialFlags.STRUCTURAL in combined
        assert MaterialFlags.GLASS in combined
