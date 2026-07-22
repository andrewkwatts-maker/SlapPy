import pytest
import numpy as np
from pharos_engine.pixel_struct import PixelStruct


def test_basic_struct():
    ps = PixelStruct({"albedo": "vec4", "roughness": "f32", "puddle": "f32"})
    assert ps.total_channels == 6
    assert ps.field_names == ["albedo", "roughness", "puddle"]


def test_empty_array_shape():
    ps = PixelStruct({"color": "vec4", "depth": "f32"})
    arr = ps.empty_array(32, 64)
    assert arr.shape == (32, 64, 5)
    assert arr.dtype == np.float32


def test_read_write_roundtrip():
    ps = PixelStruct({"color": "vec4", "heat": "f32"})
    arr = ps.empty_array(10, 10)
    ps.write_pixel(arr, 5, 5, {"color": (1.0, 0.5, 0.0, 1.0), "heat": 0.75})
    result = ps.read_pixel(arr, 5, 5)
    assert result["heat"] == pytest.approx(0.75)
    assert result["color"] == pytest.approx((1.0, 0.5, 0.0, 1.0))


def test_wgsl_struct_output():
    ps = PixelStruct({"albedo": "vec4", "roughness": "f32"})
    wgsl = ps.to_wgsl_struct("TrackPixel")
    assert "struct TrackPixel" in wgsl
    assert "albedo: vec4" in wgsl
    assert "roughness: f32" in wgsl


def test_slice_field_scalar():
    ps = PixelStruct({"color": "vec4", "heat": "f32"})
    arr = ps.empty_array(8, 8)
    arr[:, :, 4] = 0.5  # heat is at offset 4
    heat = ps.slice_field(arr, "heat")
    assert heat.shape == (8, 8)
    assert np.allclose(heat, 0.5)


def test_slice_field_vec():
    ps = PixelStruct({"color": "vec4", "heat": "f32"})
    arr = ps.empty_array(8, 8)
    color = ps.slice_field(arr, "color")
    assert color.shape == (8, 8, 4)


def test_unknown_dtype_raises():
    with pytest.raises(ValueError):
        PixelStruct({"bad": "float16"})


def test_offsets_are_sequential():
    ps = PixelStruct({"a": "f32", "b": "vec2", "c": "vec4"})
    assert ps._fields[0].offset == 0
    assert ps._fields[1].offset == 1  # after f32
    assert ps._fields[2].offset == 3  # after f32 + vec2
    assert ps.total_channels == 7
