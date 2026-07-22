"""Engine tests for PixelStruct — typed GPU texel layout."""
from __future__ import annotations
import numpy as np
import pytest


class TestPixelStructConstruction:
    def test_single_f32_field(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"density": "f32"})
        assert ps.total_channels == 1

    def test_vec4_field_four_channels(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"albedo": "vec4"})
        assert ps.total_channels == 4

    def test_mixed_fields_channel_count(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"albedo": "vec4", "roughness": "f32", "puddle": "f32"})
        assert ps.total_channels == 6

    def test_field_names_ordered(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"a": "f32", "b": "vec2", "c": "f32"})
        assert ps.field_names == ["a", "b", "c"]

    def test_unknown_dtype_raises(self):
        from pharos_engine.pixel_struct import PixelStruct
        with pytest.raises(ValueError):
            PixelStruct({"x": "mat4"})

    def test_u32_field(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"flags": "u32"})
        assert ps.total_channels == 1

    def test_repr_contains_fields(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"density": "f32"})
        assert "density" in repr(ps)


class TestPixelStructEmptyArray:
    def test_shape_correct(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"albedo": "vec4", "density": "f32"})
        arr = ps.empty_array(height=32, width=64)
        assert arr.shape == (32, 64, 5)

    def test_all_zeros(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"x": "f32", "y": "f32"})
        arr = ps.empty_array(8, 8)
        assert float(arr.sum()) == pytest.approx(0.0)

    def test_dtype_float32(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"v": "vec3"})
        arr = ps.empty_array(4, 4)
        assert arr.dtype == np.float32


class TestPixelStructReadWrite:
    def test_read_scalar_field(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"density": "f32"})
        arr = ps.empty_array(8, 8)
        arr[3, 5, 0] = 0.75
        result = ps.read_pixel(arr, x=5, y=3)
        assert result["density"] == pytest.approx(0.75)

    def test_read_vec2_field(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"velocity": "vec2"})
        arr = ps.empty_array(8, 8)
        arr[2, 2, 0] = 1.0
        arr[2, 2, 1] = -0.5
        result = ps.read_pixel(arr, x=2, y=2)
        assert result["velocity"] == pytest.approx((1.0, -0.5))

    def test_read_vec4_field(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"color": "vec4"})
        arr = ps.empty_array(4, 4)
        arr[1, 1, :4] = [0.1, 0.2, 0.3, 1.0]
        result = ps.read_pixel(arr, x=1, y=1)
        assert result["color"] == pytest.approx((0.1, 0.2, 0.3, 1.0), abs=1e-5)

    def test_write_scalar_field(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"temp": "f32"})
        arr = ps.empty_array(8, 8)
        ps.write_pixel(arr, x=4, y=6, values={"temp": 0.9})
        assert arr[6, 4, 0] == pytest.approx(0.9)

    def test_write_vec2_field(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"vel": "vec2"})
        arr = ps.empty_array(8, 8)
        ps.write_pixel(arr, x=3, y=3, values={"vel": (2.0, -1.0)})
        assert arr[3, 3, 0] == pytest.approx(2.0)
        assert arr[3, 3, 1] == pytest.approx(-1.0)

    def test_write_unknown_field_ignored(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"x": "f32"})
        arr = ps.empty_array(4, 4)
        ps.write_pixel(arr, x=0, y=0, values={"unknown": 99.0})  # should not raise

    def test_roundtrip_multiple_fields(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"albedo": "vec4", "roughness": "f32", "wet": "f32"})
        arr = ps.empty_array(16, 16)
        ps.write_pixel(arr, x=8, y=8, values={
            "albedo": (0.8, 0.4, 0.2, 1.0),
            "roughness": 0.3,
            "wet": 0.7,
        })
        result = ps.read_pixel(arr, x=8, y=8)
        assert result["roughness"] == pytest.approx(0.3, abs=1e-5)
        assert result["wet"] == pytest.approx(0.7, abs=1e-5)
        assert result["albedo"] == pytest.approx((0.8, 0.4, 0.2, 1.0), abs=1e-5)


class TestPixelStructWGSL:
    def test_wgsl_contains_struct_name(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"density": "f32"})
        wgsl = ps.to_wgsl_struct("TrackPixel")
        assert "TrackPixel" in wgsl
        assert "struct" in wgsl

    def test_wgsl_contains_all_fields(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"albedo": "vec4", "roughness": "f32"})
        wgsl = ps.to_wgsl_struct()
        assert "albedo" in wgsl
        assert "roughness" in wgsl
        assert "vec4" in wgsl
        assert "f32" in wgsl

    def test_wgsl_default_name_pixel(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"x": "f32"})
        wgsl = ps.to_wgsl_struct()
        assert "Pixel" in wgsl


class TestPixelStructSliceField:
    def test_slice_scalar_returns_2d(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"a": "f32", "b": "f32"})
        arr = ps.empty_array(8, 8)
        arr[:, :, 1] = 5.0  # field "b" is at offset 1
        sliced = ps.slice_field(arr, "b")
        assert sliced.shape == (8, 8)
        assert float(sliced[0, 0]) == pytest.approx(5.0)

    def test_slice_vec2_returns_3d(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"vel": "vec2"})
        arr = ps.empty_array(4, 4)
        sliced = ps.slice_field(arr, "vel")
        assert sliced.shape == (4, 4, 2)

    def test_channel_offsets_correct_for_mixed_layout(self):
        from pharos_engine.pixel_struct import PixelStruct
        # albedo(4) + roughness(1) + wet(1) = 6 total channels
        # roughness is at offset 4
        ps = PixelStruct({"albedo": "vec4", "roughness": "f32", "wet": "f32"})
        arr = ps.empty_array(4, 4)
        arr[:, :, 4] = 0.3  # roughness channel
        sliced = ps.slice_field(arr, "roughness")
        assert float(sliced[0, 0]) == pytest.approx(0.3)
