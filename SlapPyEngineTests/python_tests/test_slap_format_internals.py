"""Headless tests for slap_format internals — _pack_u32/_pack_u64 and _encode_layer/_decode_layer roundtrip."""
from __future__ import annotations
import io
import struct
import numpy as np
import pytest


class _FakeLayer:
    def __init__(self, name="layer", w=8, h=8, visible=True, channel_map=None):
        data = np.zeros((h, w, 4), dtype=np.uint8)
        data[:, :, 0] = 100
        data[:, :, 1] = 150
        data[:, :, 2] = 200
        data[:, :, 3] = 255
        self._image_data = data
        self._pixel_data = None
        self.name = name
        self.opacity = 1.0
        self.visible = visible
        self.size = (w, h)
        self.channel_map = channel_map or {}


# =============================================================================
# _pack_u32
# =============================================================================

class TestPackU32:
    def test_zero(self):
        from pharos_engine.residency.slap_format import _pack_u32
        assert _pack_u32(0) == b'\x00\x00\x00\x00'

    def test_one(self):
        from pharos_engine.residency.slap_format import _pack_u32
        assert _pack_u32(1) == b'\x01\x00\x00\x00'

    def test_255(self):
        from pharos_engine.residency.slap_format import _pack_u32
        assert _pack_u32(255) == b'\xff\x00\x00\x00'

    def test_max_value(self):
        from pharos_engine.residency.slap_format import _pack_u32
        assert _pack_u32(2**32 - 1) == b'\xff\xff\xff\xff'

    def test_produces_four_bytes(self):
        from pharos_engine.residency.slap_format import _pack_u32
        assert len(_pack_u32(12345)) == 4

    def test_little_endian(self):
        from pharos_engine.residency.slap_format import _pack_u32
        result = _pack_u32(0x01020304)
        assert result == b'\x04\x03\x02\x01'

    def test_roundtrip_unpack(self):
        from pharos_engine.residency.slap_format import _pack_u32
        v = 987654321
        assert struct.unpack("<I", _pack_u32(v))[0] == v


# =============================================================================
# _pack_u64
# =============================================================================

class TestPackU64:
    def test_zero(self):
        from pharos_engine.residency.slap_format import _pack_u64
        assert _pack_u64(0) == b'\x00\x00\x00\x00\x00\x00\x00\x00'

    def test_one(self):
        from pharos_engine.residency.slap_format import _pack_u64
        assert _pack_u64(1) == b'\x01\x00\x00\x00\x00\x00\x00\x00'

    def test_max_value(self):
        from pharos_engine.residency.slap_format import _pack_u64
        assert _pack_u64(2**64 - 1) == b'\xff\xff\xff\xff\xff\xff\xff\xff'

    def test_produces_eight_bytes(self):
        from pharos_engine.residency.slap_format import _pack_u64
        assert len(_pack_u64(99999)) == 8

    def test_little_endian(self):
        from pharos_engine.residency.slap_format import _pack_u64
        result = _pack_u64(0x0102030405060708)
        assert result == b'\x08\x07\x06\x05\x04\x03\x02\x01'

    def test_roundtrip_unpack(self):
        from pharos_engine.residency.slap_format import _pack_u64
        v = 1234567890123
        assert struct.unpack("<Q", _pack_u64(v))[0] == v

    def test_wider_than_u32(self):
        from pharos_engine.residency.slap_format import _pack_u64
        v = 2**33
        assert struct.unpack("<Q", _pack_u64(v))[0] == v


# =============================================================================
# _encode_layer / _decode_layer roundtrip
# =============================================================================

class TestEncodeDecodeLayerRoundtrip:
    def _roundtrip(self, layer):
        from pharos_engine.residency.slap_format import _encode_layer, _decode_layer
        encoded = _encode_layer(layer)
        return _decode_layer(io.BytesIO(encoded))

    def test_encode_returns_bytes(self):
        from pharos_engine.residency.slap_format import _encode_layer
        result = _encode_layer(_FakeLayer())
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_name_roundtrip(self):
        layer = _FakeLayer(name="body_layer")
        decoded = self._roundtrip(layer)
        assert decoded["name"] == "body_layer"

    def test_name_with_spaces_roundtrip(self):
        layer = _FakeLayer(name="my fancy layer")
        decoded = self._roundtrip(layer)
        assert decoded["name"] == "my fancy layer"

    def test_opacity_roundtrip(self):
        layer = _FakeLayer()
        layer.opacity = 0.42
        decoded = self._roundtrip(layer)
        assert decoded["opacity"] == pytest.approx(0.42)

    def test_opacity_zero_roundtrip(self):
        layer = _FakeLayer()
        layer.opacity = 0.0
        decoded = self._roundtrip(layer)
        assert decoded["opacity"] == pytest.approx(0.0)

    def test_visible_true_roundtrip(self):
        layer = _FakeLayer(visible=True)
        decoded = self._roundtrip(layer)
        assert decoded["visible"] is True

    def test_visible_false_roundtrip(self):
        layer = _FakeLayer(visible=False)
        decoded = self._roundtrip(layer)
        assert decoded["visible"] is False

    def test_size_roundtrip(self):
        layer = _FakeLayer(w=32, h=24)
        decoded = self._roundtrip(layer)
        assert decoded["size"] == [32, 24]

    def test_size_non_square(self):
        layer = _FakeLayer(w=64, h=16)
        decoded = self._roundtrip(layer)
        assert decoded["size"] == [64, 16]

    def test_channel_map_roundtrip(self):
        layer = _FakeLayer(channel_map={"density": 0, "velocity": 1})
        decoded = self._roundtrip(layer)
        assert decoded["channel_map"] == {"density": 0, "velocity": 1}

    def test_empty_channel_map_roundtrip(self):
        layer = _FakeLayer(channel_map={})
        decoded = self._roundtrip(layer)
        assert decoded["channel_map"] == {}

    def test_image_data_shape_roundtrip(self):
        layer = _FakeLayer(w=16, h=8)
        decoded = self._roundtrip(layer)
        assert decoded["image_data"] is not None
        assert decoded["image_data"].shape == (8, 16, 4)

    def test_no_image_data_returns_none(self):
        from pharos_engine.residency.slap_format import _encode_layer, _decode_layer
        layer = _FakeLayer()
        layer._image_data = None
        encoded = _encode_layer(layer)
        decoded = _decode_layer(io.BytesIO(encoded))
        assert decoded["image_data"] is None

    def test_empty_image_array_returns_none(self):
        from pharos_engine.residency.slap_format import _encode_layer, _decode_layer
        layer = _FakeLayer()
        layer._image_data = np.zeros((0, 0, 4), dtype=np.uint8)
        encoded = _encode_layer(layer)
        decoded = _decode_layer(io.BytesIO(encoded))
        assert decoded["image_data"] is None

    def test_pixel_data_roundtrip_shape(self):
        from pharos_engine.residency.slap_format import _encode_layer, _decode_layer
        layer = _FakeLayer(w=4, h=4)
        layer._image_data = None
        layer._pixel_data = np.arange(32, dtype=np.float32)  # 4*4*2 = 32
        encoded = _encode_layer(layer)
        decoded = _decode_layer(io.BytesIO(encoded))
        assert decoded["pixel_data"] is not None
        assert decoded["pixel_data"].shape == (4, 4, 2)

    def test_pixel_data_roundtrip_values(self):
        from pharos_engine.residency.slap_format import _encode_layer, _decode_layer
        layer = _FakeLayer(w=4, h=4)
        layer._image_data = None
        arr = np.arange(32, dtype=np.float32)
        layer._pixel_data = arr
        encoded = _encode_layer(layer)
        decoded = _decode_layer(io.BytesIO(encoded))
        flat = decoded["pixel_data"].flatten()
        assert flat[0] == pytest.approx(0.0)
        assert flat[1] == pytest.approx(1.0)
        assert flat[31] == pytest.approx(31.0)

    def test_no_pixel_data_returns_none(self):
        layer = _FakeLayer()
        layer._pixel_data = None
        decoded = self._roundtrip(layer)
        assert decoded["pixel_data"] is None

    def test_decoded_result_is_dict(self):
        decoded = self._roundtrip(_FakeLayer())
        assert isinstance(decoded, dict)

    def test_decoded_has_all_keys(self):
        decoded = self._roundtrip(_FakeLayer())
        for key in ("name", "opacity", "visible", "size", "channel_map", "image_data", "pixel_data"):
            assert key in decoded


# =============================================================================
# Bad version in file header
# =============================================================================

class TestBadVersionRaises:
    def test_bad_version_raises_valueerror(self, tmp_path):
        from pharos_engine.residency.slap_format import read_world_slap, SLAP_MAGIC, _HDR_FMT
        bad_file = tmp_path / "bad_ver.slap"
        bad_file.write_bytes(struct.pack(_HDR_FMT, SLAP_MAGIC, 99, 0))
        with pytest.raises(ValueError, match="version"):
            read_world_slap(bad_file)

    def test_version_zero_raises(self, tmp_path):
        from pharos_engine.residency.slap_format import read_world_slap, SLAP_MAGIC, _HDR_FMT
        bad_file = tmp_path / "ver0.slap"
        bad_file.write_bytes(struct.pack(_HDR_FMT, SLAP_MAGIC, 0, 0))
        with pytest.raises(ValueError, match="version"):
            read_world_slap(bad_file)
