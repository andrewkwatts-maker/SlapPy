"""Engine tests for residency/slap_format.py — headless (PIL + numpy only)."""
from __future__ import annotations
import numpy as np
import pytest
from pathlib import Path


class _FakeLayer:
    def __init__(self, name="layer", w=16, h=16, alpha=200):
        data = np.zeros((h, w, 4), dtype=np.uint8)
        data[:, :, 0] = 100
        data[:, :, 1] = 150
        data[:, :, 2] = 200
        data[:, :, 3] = alpha
        self._image_data = data
        self._pixel_data = None
        self.name = name
        self.opacity = 1.0
        self.visible = True
        self.size = (w, h)
        self.channel_map = {}


class _FakeAsset:
    def __init__(self, name="Asset", layers=None):
        self.name = name
        self.position = (10.0, 20.0)
        self.size = (64, 64)
        self.z_order = 0
        self.layers = layers or [_FakeLayer()]


class TestSlapFormat:
    def test_write_creates_file(self, tmp_path):
        from pharos_engine.residency.slap_format import write_world_slap
        out = tmp_path / "world.slap"
        assets = [_FakeAsset("Car")]
        write_world_slap(out, assets)
        assert out.exists()

    def test_roundtrip_single_asset(self, tmp_path):
        from pharos_engine.residency.slap_format import write_world_slap, read_world_slap
        out = tmp_path / "world.slap"
        assets = [_FakeAsset("Tank")]
        write_world_slap(out, assets)
        results = read_world_slap(out)
        assert len(results) == 1
        assert results[0]["name"] == "Tank"

    def test_roundtrip_multiple_assets(self, tmp_path):
        from pharos_engine.residency.slap_format import write_world_slap, read_world_slap
        out = tmp_path / "world.slap"
        assets = [_FakeAsset("A"), _FakeAsset("B"), _FakeAsset("C")]
        write_world_slap(out, assets)
        results = read_world_slap(out)
        assert len(results) == 3
        names = [r["name"] for r in results]
        assert "A" in names
        assert "B" in names
        assert "C" in names

    def test_bad_magic_raises(self, tmp_path):
        from pharos_engine.residency.slap_format import read_world_slap
        bad_file = tmp_path / "bad.slap"
        bad_file.write_bytes(b"XXXX\x01\x00\x00\x00\x00\x00\x00\x00")
        with pytest.raises(ValueError, match="bad magic"):
            read_world_slap(bad_file)

    def test_position_preserved(self, tmp_path):
        from pharos_engine.residency.slap_format import write_world_slap, read_world_slap
        out = tmp_path / "world.slap"
        asset = _FakeAsset("Pos")
        asset.position = (42.5, 99.0)
        write_world_slap(out, [asset])
        result = read_world_slap(out)[0]
        pos = result["position"]
        assert abs(pos[0] - 42.5) < 0.01
        assert abs(pos[1] - 99.0) < 0.01

    def test_layer_count_preserved(self, tmp_path):
        from pharos_engine.residency.slap_format import write_world_slap, read_world_slap
        out = tmp_path / "world.slap"
        asset = _FakeAsset("Multi", layers=[_FakeLayer("a"), _FakeLayer("b")])
        write_world_slap(out, [asset])
        result = read_world_slap(out)[0]
        assert len(result["layers"]) == 2

    def test_layer_name_preserved(self, tmp_path):
        from pharos_engine.residency.slap_format import write_world_slap, read_world_slap
        out = tmp_path / "world.slap"
        asset = _FakeAsset("X", layers=[_FakeLayer("body_layer")])
        write_world_slap(out, [asset])
        result = read_world_slap(out)[0]
        assert result["layers"][0]["name"] == "body_layer"

    def test_layer_opacity_preserved(self, tmp_path):
        from pharos_engine.residency.slap_format import write_world_slap, read_world_slap
        out = tmp_path / "world.slap"
        layer = _FakeLayer("shade")
        layer.opacity = 0.75
        asset = _FakeAsset("Faded", layers=[layer])
        write_world_slap(out, [asset])
        result = read_world_slap(out)[0]
        assert abs(result["layers"][0]["opacity"] - 0.75) < 0.01

    def test_write_asset_to_slap_shorthand(self, tmp_path):
        from pharos_engine.residency.slap_format import write_asset_to_slap, read_asset_from_slap
        out = tmp_path / "single.slap"
        asset = _FakeAsset("Solo")
        write_asset_to_slap(out, asset)
        result = read_asset_from_slap(out)
        assert result["name"] == "Solo"

    def test_read_asset_from_slap_single(self, tmp_path):
        from pharos_engine.residency.slap_format import write_asset_to_slap, read_asset_from_slap
        out = tmp_path / "one.slap"
        asset = _FakeAsset("OnlyOne")
        write_asset_to_slap(out, asset)
        result = read_asset_from_slap(out)
        assert isinstance(result, dict)
        assert result["name"] == "OnlyOne"

    def test_empty_assets_list(self, tmp_path):
        from pharos_engine.residency.slap_format import write_world_slap, read_world_slap
        out = tmp_path / "empty.slap"
        write_world_slap(out, [])
        results = read_world_slap(out)
        assert results == []

    def test_z_order_preserved(self, tmp_path):
        from pharos_engine.residency.slap_format import write_world_slap, read_world_slap
        out = tmp_path / "world.slap"
        asset = _FakeAsset("Z")
        asset.z_order = 5
        write_world_slap(out, [asset])
        result = read_world_slap(out)[0]
        assert result["z_order"] == 5

    def test_file_is_binary(self, tmp_path):
        from pharos_engine.residency.slap_format import write_world_slap
        out = tmp_path / "world.slap"
        write_world_slap(out, [_FakeAsset("A")])
        raw = out.read_bytes()
        assert raw[:4] == b"SLAP"

    def test_no_layers_asset(self, tmp_path):
        from pharos_engine.residency.slap_format import write_world_slap, read_world_slap
        out = tmp_path / "world.slap"
        asset = _FakeAsset("Empty")
        asset.layers = []  # bypass the __init__ default
        write_world_slap(out, [asset])
        result = read_world_slap(out)[0]
        assert result["layers"] == []
