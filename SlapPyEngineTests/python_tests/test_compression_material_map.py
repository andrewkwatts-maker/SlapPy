"""Engine tests for residency/compression.py and material/map.py.
All headless — no GPU, no YAML file I/O required.
"""
from __future__ import annotations
import pytest
import numpy as np


# ---------------------------------------------------------------------------
# residency/compression.py
# ---------------------------------------------------------------------------

class TestCompressArray:
    def test_compress_returns_bytes(self):
        from slappyengine.residency.compression import compress_array
        arr = np.zeros((4, 4), dtype=np.float32)
        result = compress_array(arr)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_roundtrip(self):
        from slappyengine.residency.compression import compress_array, decompress_array
        arr = np.random.rand(16, 16).astype(np.float32)
        compressed = compress_array(arr)
        recovered = decompress_array(compressed, shape=(16, 16))
        assert np.allclose(arr, recovered)

    def test_roundtrip_3d_array(self):
        from slappyengine.residency.compression import compress_array, decompress_array
        arr = np.ones((8, 8, 4), dtype=np.float32)
        compressed = compress_array(arr)
        recovered = decompress_array(compressed, shape=(8, 8, 4))
        assert np.allclose(arr, recovered)

    def test_compressed_smaller_than_raw_for_constant(self):
        from slappyengine.residency.compression import compress_array
        arr = np.zeros((64, 64), dtype=np.float32)
        compressed = compress_array(arr)
        raw_size = arr.nbytes
        assert len(compressed) < raw_size

    def test_different_arrays_different_bytes(self):
        from slappyengine.residency.compression import compress_array
        a = np.zeros((8, 8), dtype=np.float32)
        b = np.ones((8, 8), dtype=np.float32)
        ca = compress_array(a)
        cb = compress_array(b)
        assert ca != cb


class TestCompressRaw:
    def test_compress_raw_returns_bytes(self):
        from slappyengine.residency.compression import compress_raw
        data = b"hello world " * 100
        result = compress_raw(data)
        assert isinstance(result, bytes)

    def test_roundtrip_raw(self):
        from slappyengine.residency.compression import compress_raw, decompress_raw
        original = b"test data " * 50
        compressed = compress_raw(original)
        recovered = decompress_raw(compressed)
        assert recovered == original

    def test_empty_bytes(self):
        from slappyengine.residency.compression import compress_raw, decompress_raw
        compressed = compress_raw(b"")
        recovered = decompress_raw(compressed)
        assert recovered == b""

    def test_compresses_repetitive_data(self):
        from slappyengine.residency.compression import compress_raw
        data = b"\x00" * 10000
        compressed = compress_raw(data)
        assert len(compressed) < len(data)


# ---------------------------------------------------------------------------
# material/map.py — ColorRange, MaterialDef, MaterialMap
# ---------------------------------------------------------------------------

class TestColorRange:
    def test_instantiates(self):
        from slappyengine.material.map import ColorRange
        cr = ColorRange()
        assert cr is not None

    def test_defaults(self):
        from slappyengine.material.map import ColorRange
        cr = ColorRange()
        assert cr.r == (0, 255)
        assert cr.g == (0, 255)
        assert cr.b == (0, 255)

    def test_matches_full_range(self):
        from slappyengine.material.map import ColorRange
        cr = ColorRange()
        assert cr.matches(128, 64, 200) is True

    def test_matches_exact_bounds(self):
        from slappyengine.material.map import ColorRange
        cr = ColorRange(r=(100, 150), g=(0, 255), b=(0, 255))
        assert cr.matches(100, 0, 0) is True
        assert cr.matches(150, 0, 0) is True

    def test_does_not_match_outside(self):
        from slappyengine.material.map import ColorRange
        cr = ColorRange(r=(100, 150), g=(0, 255), b=(0, 255))
        assert cr.matches(99, 0, 0) is False
        assert cr.matches(151, 0, 0) is False

    def test_narrow_range(self):
        from slappyengine.material.map import ColorRange
        cr = ColorRange(r=(200, 210), g=(100, 110), b=(50, 60))
        assert cr.matches(205, 105, 55) is True
        assert cr.matches(195, 105, 55) is False


class TestMaterialDef:
    def test_instantiates(self):
        from slappyengine.material.map import MaterialDef, ColorRange
        md = MaterialDef(name="rock", color_range=ColorRange(r=(50, 80)))
        assert md is not None

    def test_name_stored(self):
        from slappyengine.material.map import MaterialDef, ColorRange
        md = MaterialDef(name="wood", color_range=ColorRange())
        assert md.name == "wood"

    def test_default_alpha_opacity(self):
        from slappyengine.material.map import MaterialDef, ColorRange
        md = MaterialDef(name="x", color_range=ColorRange())
        assert md.alpha_meaning == "opacity"

    def test_behaviors_empty_by_default(self):
        from slappyengine.material.map import MaterialDef, ColorRange
        md = MaterialDef(name="x", color_range=ColorRange())
        assert md.behaviors == []

    def test_params_empty_by_default(self):
        from slappyengine.material.map import MaterialDef, ColorRange
        md = MaterialDef(name="x", color_range=ColorRange())
        assert md.params == {}


class TestMaterialMap:
    def test_instantiates(self):
        from slappyengine.material.map import MaterialMap
        mm = MaterialMap()
        assert mm is not None

    def test_add_material(self):
        from slappyengine.material.map import MaterialMap, ColorRange
        mm = MaterialMap()
        result = mm.add("grass", ColorRange(r=(0, 100), g=(100, 200), b=(0, 50)))
        assert result.name == "grass"

    def test_match_finds_material(self):
        from slappyengine.material.map import MaterialMap, ColorRange
        mm = MaterialMap()
        mm.add("water", ColorRange(r=(0, 50), g=(0, 100), b=(150, 255)))
        found = mm.match(20, 50, 200)
        assert found is not None
        assert found.name == "water"

    def test_match_returns_none_no_match(self):
        from slappyengine.material.map import MaterialMap, ColorRange
        mm = MaterialMap()
        mm.add("rock", ColorRange(r=(100, 150), g=(100, 150), b=(100, 150)))
        result = mm.match(0, 0, 255)
        assert result is None

    def test_match_first_wins(self):
        from slappyengine.material.map import MaterialMap, ColorRange
        mm = MaterialMap()
        mm.add("first", ColorRange())   # matches everything
        mm.add("second", ColorRange())  # also matches everything
        found = mm.match(128, 128, 128)
        assert found.name == "first"

    def test_multiple_materials(self):
        from slappyengine.material.map import MaterialMap, ColorRange
        mm = MaterialMap()
        mm.add("sand", ColorRange(r=(200, 255), g=(150, 200), b=(0, 100)))
        mm.add("rock", ColorRange(r=(100, 150), g=(100, 150), b=(100, 150)))
        assert mm.match(225, 175, 50).name == "sand"
        assert mm.match(125, 125, 125).name == "rock"

    def test_add_returns_material_def(self):
        from slappyengine.material.map import MaterialMap, ColorRange, MaterialDef
        mm = MaterialMap()
        result = mm.add("x", ColorRange())
        assert isinstance(result, MaterialDef)

    def test_load_defaults_no_crash(self):
        from slappyengine.material.map import MaterialMap
        mm = MaterialMap.load_defaults()
        assert isinstance(mm, MaterialMap)

    def test_add_with_behaviors(self):
        from slappyengine.material.map import MaterialMap, ColorRange
        mm = MaterialMap()
        md = mm.add("lava", ColorRange(r=(200, 255), g=(0, 80), b=(0, 30)),
                    behaviors=["damage", "hot"])
        assert "damage" in md.behaviors
        assert "hot" in md.behaviors

    def test_add_with_params(self):
        from slappyengine.material.map import MaterialMap, ColorRange
        mm = MaterialMap()
        md = mm.add("metal", ColorRange(), params={"conductivity": 0.9})
        assert md.params["conductivity"] == pytest.approx(0.9)
