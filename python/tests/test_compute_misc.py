"""Engine tests for AABB, EffectShader, and residency compression — headless."""
from __future__ import annotations
import numpy as np
import pytest


class TestAABB:
    def test_width(self):
        from slappyengine.compute.spatial import AABB
        aabb = AABB(10.0, 20.0, 50.0, 80.0)
        assert aabb.width() == pytest.approx(40.0)

    def test_height(self):
        from slappyengine.compute.spatial import AABB
        aabb = AABB(10.0, 20.0, 50.0, 80.0)
        assert aabb.height() == pytest.approx(60.0)

    def test_center(self):
        from slappyengine.compute.spatial import AABB
        aabb = AABB(0.0, 0.0, 100.0, 80.0)
        cx, cy = aabb.center()
        assert cx == pytest.approx(50.0)
        assert cy == pytest.approx(40.0)

    def test_contains_inside(self):
        from slappyengine.compute.spatial import AABB
        aabb = AABB(0.0, 0.0, 100.0, 100.0)
        assert aabb.contains(50.0, 50.0) is True

    def test_contains_on_edge(self):
        from slappyengine.compute.spatial import AABB
        aabb = AABB(0.0, 0.0, 100.0, 100.0)
        assert aabb.contains(0.0, 0.0) is True
        assert aabb.contains(100.0, 100.0) is True

    def test_contains_outside(self):
        from slappyengine.compute.spatial import AABB
        aabb = AABB(0.0, 0.0, 100.0, 100.0)
        assert aabb.contains(-1.0, 50.0) is False
        assert aabb.contains(50.0, 101.0) is False

    def test_zero_size_aabb(self):
        from slappyengine.compute.spatial import AABB
        aabb = AABB(5.0, 5.0, 5.0, 5.0)
        assert aabb.width() == pytest.approx(0.0)
        assert aabb.height() == pytest.approx(0.0)
        assert aabb.contains(5.0, 5.0) is True
        assert aabb.contains(6.0, 5.0) is False


class TestEffectShader:
    def test_init_stores_wgsl(self):
        from slappyengine.compute.effect import EffectShader
        es = EffectShader("@compute fn main() {}", blend="additive", label="test")
        assert "main" in es.wgsl

    def test_default_blend_normal(self):
        from slappyengine.compute.effect import EffectShader
        es = EffectShader("")
        assert es.blend == "normal"

    def test_default_label(self):
        from slappyengine.compute.effect import EffectShader
        es = EffectShader("")
        assert es.label == "effect"

    def test_pipeline_initially_none(self):
        from slappyengine.compute.effect import EffectShader
        es = EffectShader("")
        assert es._pipeline is None


class TestResidencyCompression:
    def test_compress_array_returns_bytes(self):
        from slappyengine.residency.compression import compress_array
        arr = np.random.rand(4, 4).astype(np.float32)
        result = compress_array(arr)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_decompress_array_roundtrip(self):
        from slappyengine.residency.compression import compress_array, decompress_array
        original = np.random.rand(8, 8).astype(np.float32)
        compressed = compress_array(original)
        restored = decompress_array(compressed, original.shape)
        np.testing.assert_allclose(restored, original, atol=1e-6)

    def test_compress_reduces_size_for_zeros(self):
        from slappyengine.residency.compression import compress_array
        zeros = np.zeros((64, 64), dtype=np.float32)
        compressed = compress_array(zeros)
        raw_size = zeros.nbytes
        assert len(compressed) < raw_size

    def test_decompress_array_correct_shape(self):
        from slappyengine.residency.compression import compress_array, decompress_array
        original = np.ones((3, 4), dtype=np.float32)
        compressed = compress_array(original)
        restored = decompress_array(compressed, (3, 4))
        assert restored.shape == (3, 4)

    def test_compress_raw_returns_bytes(self):
        from slappyengine.residency.compression import compress_raw
        data = b"hello world" * 100
        result = compress_raw(data)
        assert isinstance(result, bytes)

    def test_decompress_raw_roundtrip(self):
        from slappyengine.residency.compression import compress_raw, decompress_raw
        original = b"test data " * 50
        compressed = compress_raw(original)
        restored = decompress_raw(compressed)
        assert restored == original

    def test_compress_raw_smaller_than_input_for_repeated(self):
        from slappyengine.residency.compression import compress_raw
        data = b"\x00" * 1000
        compressed = compress_raw(data)
        assert len(compressed) < len(data)
