"""Engine tests for collision_pixel.py — headless (GPU degrades gracefully)."""
from __future__ import annotations
import pytest


class TestPixelContactResult:
    def test_hit_false(self):
        from slappyengine.collision_pixel import PixelContactResult
        r = PixelContactResult(hit=False, contact_pixels=0, normal=(0.0, 0.0))
        assert r.hit is False
        assert r.contact_pixels == 0
        assert r.normal == (0.0, 0.0)

    def test_hit_true(self):
        from slappyengine.collision_pixel import PixelContactResult
        r = PixelContactResult(hit=True, contact_pixels=42, normal=(0.7, 0.3))
        assert r.hit is True
        assert r.contact_pixels == 42
        assert r.normal[0] == pytest.approx(0.7)
        assert r.normal[1] == pytest.approx(0.3)

    def test_dataclass_fields(self):
        import dataclasses
        from slappyengine.collision_pixel import PixelContactResult
        assert dataclasses.is_dataclass(PixelContactResult)

    def test_no_contact_sentinel(self):
        from slappyengine.collision_pixel import _NO_CONTACT
        assert _NO_CONTACT.hit is False
        assert _NO_CONTACT.contact_pixels == 0
        assert _NO_CONTACT.normal == (0.0, 0.0)


class TestPixelCollisionPassInit:
    def test_instantiation_does_not_raise(self):
        from slappyengine.collision_pixel import PixelCollisionPass
        p = PixelCollisionPass()
        assert p is not None

    def test_pipeline_initially_none(self):
        from slappyengine.collision_pixel import PixelCollisionPass
        p = PixelCollisionPass()
        assert p._pipeline is None

    def test_ready_state(self):
        from slappyengine.collision_pixel import PixelCollisionPass, _WGPU_OK, _SHADER_PATH
        p = PixelCollisionPass()
        if _WGPU_OK and _SHADER_PATH.exists():
            assert p._ready is True
        else:
            assert p._ready is False


class TestPixelCollisionPassTestMethod:
    def test_returns_no_contact_when_not_ready(self):
        from slappyengine.collision_pixel import PixelCollisionPass, _NO_CONTACT
        p = PixelCollisionPass()
        if p._ready:
            pytest.skip("GPU context available — headless path not exercised")
        # No gpu context needed — returns no-contact immediately
        result = p.test(None, None, (0, 0, 32, 32), None, (0, 0, 32, 32))
        assert result.hit is False
        assert result.contact_pixels == 0

    def test_test_with_none_gpu_no_raise(self):
        from slappyengine.collision_pixel import PixelCollisionPass
        p = PixelCollisionPass()
        # Must not raise regardless of readiness
        try:
            result = p.test(None, None, (0, 0, 10, 10), None, (0, 0, 10, 10))
            assert isinstance(result.hit, bool)
        except Exception as exc:
            pytest.fail(f"test() raised unexpectedly: {exc}")

    def test_result_has_correct_types(self):
        from slappyengine.collision_pixel import PixelCollisionPass
        p = PixelCollisionPass()
        result = p.test(None, None, (0, 0, 16, 16), None, (0, 0, 16, 16))
        assert isinstance(result.hit, bool)
        assert isinstance(result.contact_pixels, int)
        assert isinstance(result.normal, tuple)
        assert len(result.normal) == 2


class TestParamsLayout:
    def test_params_format_size(self):
        """Verify the CollisionParams struct is 48 bytes (12 unsigned ints)."""
        import struct
        from slappyengine.collision_pixel import _PARAMS_FORMAT, _PARAMS_SIZE
        assert struct.calcsize(_PARAMS_FORMAT) == _PARAMS_SIZE
        assert _PARAMS_SIZE == 48

    def test_result_format_size(self):
        """Verify the CollisionResult struct is 16 bytes."""
        import struct
        from slappyengine.collision_pixel import _RESULT_FORMAT, _RESULT_SIZE
        assert struct.calcsize(_RESULT_FORMAT) == _RESULT_SIZE
        assert _RESULT_SIZE == 16

    def test_params_pack_unpack_roundtrip(self):
        """Pack and unpack a params struct to verify byte layout."""
        import struct
        from slappyengine.collision_pixel import _PARAMS_FORMAT
        values = (10, 20, 32, 32,   # a rect
                  50, 60, 32, 32,   # b rect
                  128, 0, 0, 0)     # threshold + pad
        packed = struct.pack(_PARAMS_FORMAT, *values)
        unpacked = struct.unpack(_PARAMS_FORMAT, packed)
        assert unpacked[0] == 10
        assert unpacked[8] == 128  # alpha_threshold
