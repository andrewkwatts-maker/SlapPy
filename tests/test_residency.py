"""
Tests for the residency sub-system — compression, .slap I/O, ResidencyManager,
and Scene save/load.  All tests are pure-Python; no GPU or compiled Rust
extension is required.

If the full engine package cannot be imported (e.g. wgpu.gui is absent) the
tests that depend on it are skipped automatically.
"""
import pytest
import numpy as np
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Detect whether playslap is importable (wgpu.gui may be absent in CI).
# Compression tests only use numpy, so they always run.
# Everything else is gated on this flag.
# ---------------------------------------------------------------------------
_ENGINE_SKIP_REASON = ""
try:
    import playslap  # noqa: F401 — triggers __init__ (Engine import)
    _ENGINE_AVAILABLE = True
except Exception as _exc:
    _ENGINE_AVAILABLE = False
    _ENGINE_SKIP_REASON = str(_exc)

_requires_engine = pytest.mark.skipif(
    not _ENGINE_AVAILABLE,
    reason=f"playslap not importable: {_ENGINE_SKIP_REASON}",
)

# ---------------------------------------------------------------------------
# Helpers — imported lazily inside each function to avoid collection errors
# ---------------------------------------------------------------------------

def _make_asset(name="test", position=(0.0, 0.0), size=(16, 16)):
    """Return a bare Asset with no layers."""
    from playslap.asset import Asset
    return Asset(name=name, position=position, size=size)


def _blank_layer(w, h, name="layer", fill=None):
    """Return a Layer with image data; optionally flood-fill with *fill* rgba."""
    from playslap.layer import Layer
    layer = Layer.blank(w, h, name=name)
    if fill is not None:
        layer._image_data[:] = fill
    return layer


# ===========================================================================
# Compression
# (These only depend on numpy + lz4/zlib — no GPU stack needed.)
# ===========================================================================

class TestCompression:
    def test_compress_decompress_array(self):
        from playslap.residency.compression import compress_array, decompress_array
        arr = np.arange(100, dtype=np.float32)
        data = compress_array(arr)
        assert isinstance(data, bytes)
        assert len(data) > 0
        restored = decompress_array(data, (100,))
        np.testing.assert_array_almost_equal(arr, restored)

    def test_compress_decompress_raw(self):
        from playslap.residency.compression import compress_raw, decompress_raw
        raw = b"hello world" * 1000
        compressed = compress_raw(raw)
        assert isinstance(compressed, bytes)
        assert decompress_raw(compressed) == raw

    def test_compress_raw_small(self):
        from playslap.residency.compression import compress_raw, decompress_raw
        for payload in (b"", b"x", b"\x00" * 4):
            assert decompress_raw(compress_raw(payload)) == payload

    def test_compress_empty_array(self):
        from playslap.residency.compression import compress_array, decompress_array
        arr = np.array([], dtype=np.float32)
        data = compress_array(arr)
        restored = decompress_array(data, (0,))
        assert restored.size == 0

    def test_compress_2d_array(self):
        from playslap.residency.compression import compress_array, decompress_array
        arr = np.random.rand(8, 7).astype(np.float32)
        data = compress_array(arr)
        flat = decompress_array(data, (56,))
        np.testing.assert_array_almost_equal(arr.flatten(), flat)

    def test_compress_preserves_dtype(self):
        from playslap.residency.compression import compress_array, decompress_array
        arr = np.array([1.5, -2.5, 0.0, 1e10], dtype=np.float32)
        restored = decompress_array(compress_array(arr), (4,))
        assert restored.dtype == np.float32
        np.testing.assert_array_almost_equal(arr, restored)


# ===========================================================================
# .slap format — single-asset round-trip
# ===========================================================================

@_requires_engine
class TestSlapFormat:
    def test_write_creates_file(self, tmp_path):
        from playslap.residency.slap_format import write_asset_to_slap
        asset = _make_asset("hero", size=(32, 32))
        asset.add_layer(_blank_layer(32, 32, "skin", fill=[200, 150, 100, 255]))
        path = tmp_path / "hero.slap"
        write_asset_to_slap(path, asset)
        assert path.exists()
        assert path.stat().st_size > 0

    def test_read_returns_name(self, tmp_path):
        from playslap.residency.slap_format import write_asset_to_slap, read_asset_from_slap
        asset = _make_asset("warrior", size=(32, 64))
        asset.add_layer(_blank_layer(32, 64, "skin", fill=[200, 150, 100, 255]))
        path = tmp_path / "warrior.slap"
        write_asset_to_slap(path, asset)
        data = read_asset_from_slap(path)
        assert data["name"] == "warrior"

    def test_read_returns_layer_image(self, tmp_path):
        from playslap.residency.slap_format import write_asset_to_slap, read_asset_from_slap
        asset = _make_asset("img_test", size=(32, 64))
        asset.add_layer(_blank_layer(32, 64, "skin", fill=[200, 150, 100, 255]))
        path = tmp_path / "img.slap"
        write_asset_to_slap(path, asset)
        data = read_asset_from_slap(path)
        assert len(data["layers"]) == 1
        img = data["layers"][0]["image_data"]
        assert img is not None
        assert img.shape == (64, 32, 4)

    def test_image_pixel_values_preserved(self, tmp_path):
        from playslap.residency.slap_format import write_asset_to_slap, read_asset_from_slap
        fill = [123, 45, 67, 200]
        asset = _make_asset("colours", size=(8, 8))
        asset.add_layer(_blank_layer(8, 8, "c", fill=fill))
        path = tmp_path / "colours.slap"
        write_asset_to_slap(path, asset)
        data = read_asset_from_slap(path)
        img = data["layers"][0]["image_data"]
        np.testing.assert_array_equal(img[0, 0], fill)

    def test_position_and_size_preserved(self, tmp_path):
        from playslap.residency.slap_format import write_asset_to_slap, read_asset_from_slap
        asset = _make_asset("pos_test", position=(123.0, 456.0), size=(48, 96))
        asset.add_layer(_blank_layer(48, 96, "base"))
        path = tmp_path / "pos.slap"
        write_asset_to_slap(path, asset)
        data = read_asset_from_slap(path)
        assert data["position"] == [123.0, 456.0]
        assert data["size"] == [48, 96]

    def test_layer_metadata_preserved(self, tmp_path):
        from playslap.residency.slap_format import write_asset_to_slap, read_asset_from_slap
        from playslap.layer import Layer
        asset = _make_asset("meta_test", size=(16, 16))
        layer = Layer.blank(16, 16, name="details")
        layer.opacity = 0.75
        layer.visible = False
        asset.add_layer(layer)
        path = tmp_path / "meta.slap"
        write_asset_to_slap(path, asset)
        data = read_asset_from_slap(path)
        ldata = data["layers"][0]
        assert ldata["opacity"] == pytest.approx(0.75, abs=1e-5)
        assert ldata["visible"] is False

    def test_multiple_layers_preserved(self, tmp_path):
        from playslap.residency.slap_format import write_asset_to_slap, read_asset_from_slap
        asset = _make_asset("multi", size=(16, 16))
        for i in range(3):
            asset.add_layer(_blank_layer(16, 16, name=f"layer_{i}", fill=[i * 40, 0, 0, 255]))
        path = tmp_path / "multi.slap"
        write_asset_to_slap(path, asset)
        data = read_asset_from_slap(path)
        assert len(data["layers"]) == 3

    def test_no_asset_raises(self, tmp_path):
        from playslap.residency.slap_format import write_world_slap, read_asset_from_slap
        path = tmp_path / "empty.slap"
        write_world_slap(path, [])
        with pytest.raises(ValueError, match="No assets"):
            read_asset_from_slap(path)

    # ── struct / pixel data ──────────────────────────────────────────────────

    def test_struct_data_preserved(self, tmp_path):
        """Layers with _data_array (struct floats) survive a slap round-trip.

        _encode_layer reads `layer._pixel_data` then falls back to
        `layer._data_array`; the decoded dict uses the key "pixel_data".
        """
        from playslap.residency.slap_format import write_asset_to_slap, read_asset_from_slap
        from playslap.layer import Layer
        asset = _make_asset("phys", size=(4, 4))
        layer = Layer.blank(4, 4, name="data")
        # Use _data_array — the attribute that _encode_layer actually reads.
        layer._data_array = np.arange(16 * 7, dtype=np.float32).reshape(16, 7)
        asset.add_layer(layer)
        path = tmp_path / "phys.slap"
        write_asset_to_slap(path, asset)
        data = read_asset_from_slap(path)
        # _decode_layer returns "pixel_data" (not "struct_data").
        pixel_data = data["layers"][0].get("pixel_data")
        assert pixel_data is not None
        np.testing.assert_array_almost_equal(
            pixel_data.flatten(), layer._data_array.flatten()
        )

    def test_no_struct_data_returns_none(self, tmp_path):
        from playslap.residency.slap_format import write_asset_to_slap, read_asset_from_slap
        asset = _make_asset("simple", size=(8, 8))
        asset.add_layer(_blank_layer(8, 8, "plain"))
        path = tmp_path / "simple.slap"
        write_asset_to_slap(path, asset)
        data = read_asset_from_slap(path)
        assert data["layers"][0].get("pixel_data") is None


# ===========================================================================
# .slap format — world (multi-asset) round-trip
# ===========================================================================

@_requires_engine
class TestWorldSlap:
    def test_write_read_world(self, tmp_path):
        from playslap.residency.slap_format import write_world_slap, read_world_slap
        assets = []
        for i in range(3):
            a = _make_asset(f"asset_{i}", position=(float(i * 100), 0.0), size=(16, 16))
            a.add_layer(_blank_layer(16, 16, "base"))
            assets.append(a)
        path = tmp_path / "world.slap"
        write_world_slap(path, assets)
        records = read_world_slap(path)
        assert len(records) == 3
        names = {r["name"] for r in records}
        assert names == {"asset_0", "asset_1", "asset_2"}

    def test_world_positions_preserved(self, tmp_path):
        from playslap.residency.slap_format import write_world_slap, read_world_slap
        positions = [(0.0, 0.0), (50.0, 100.0), (-30.0, 75.5)]
        assets = []
        for i, pos in enumerate(positions):
            a = _make_asset(f"e{i}", position=pos, size=(8, 8))
            a.add_layer(_blank_layer(8, 8, "base"))
            assets.append(a)
        path = tmp_path / "pos_world.slap"
        write_world_slap(path, assets)
        records = read_world_slap(path)
        by_name = {r["name"]: r for r in records}
        for i, pos in enumerate(positions):
            assert by_name[f"e{i}"]["position"] == list(pos)

    def test_bad_magic_raises(self, tmp_path):
        from playslap.residency.slap_format import read_world_slap
        bad = tmp_path / "bad.slap"
        bad.write_bytes(b"NOPE" + b"\x00" * 20)
        with pytest.raises(ValueError, match="bad magic"):
            read_world_slap(bad)

    def test_empty_world(self, tmp_path):
        from playslap.residency.slap_format import write_world_slap, read_world_slap
        path = tmp_path / "empty.slap"
        write_world_slap(path, [])
        records = read_world_slap(path)
        assert records == []

    def test_single_asset_world(self, tmp_path):
        from playslap.residency.slap_format import write_world_slap, read_world_slap
        a = _make_asset("solo", size=(32, 32))
        a.add_layer(_blank_layer(32, 32, "body"))
        path = tmp_path / "solo.slap"
        write_world_slap(path, [a])
        records = read_world_slap(path)
        assert len(records) == 1
        assert records[0]["name"] == "solo"


# ===========================================================================
# ResidencyManager
# ===========================================================================

@_requires_engine
class TestResidencyManager:
    def test_default_tier_is_gpu(self):
        from playslap.residency.manager import ResidencyManager
        mgr = ResidencyManager()
        asset = _make_asset("a")
        assert mgr.tier(asset) == ResidencyManager.TIER_GPU

    def test_near_entity_stays_gpu(self, tmp_path):
        from playslap.residency.manager import ResidencyManager
        mgr = ResidencyManager(save_dir=tmp_path)
        asset = _make_asset("near", position=(10.0, 0.0))
        asset.add_layer(_blank_layer(16, 16))
        mgr.update((0.0, 0.0), [asset])
        assert mgr.tier(asset) == ResidencyManager.TIER_GPU

    def test_far_entity_moves_off_gpu(self, tmp_path):
        from playslap.residency.manager import ResidencyManager
        mgr = ResidencyManager(save_dir=tmp_path)
        asset = _make_asset("far", position=(10_000.0, 0.0))
        asset.add_layer(_blank_layer(16, 16))
        mgr.update((0.0, 0.0), [asset])
        assert mgr.tier(asset) in (
            ResidencyManager.TIER_DISK, ResidencyManager.TIER_RAM
        )

    def test_far_entity_slap_written_to_disk(self, tmp_path):
        from playslap.residency.manager import ResidencyManager
        mgr = ResidencyManager(save_dir=tmp_path)
        asset = _make_asset("persist", position=(10_000.0, 0.0))
        asset.add_layer(_blank_layer(16, 16))
        mgr.update((0.0, 0.0), [asset])
        if mgr.tier(asset) == ResidencyManager.TIER_DISK:
            slap_path = tmp_path / f"{asset.id}.slap"
            assert slap_path.exists(), "Expected .slap file on disk for TIER_DISK entity"

    def test_update_non_asset_entity_ignored(self, tmp_path):
        """Non-Asset entities must not raise or affect tiers."""
        from playslap.residency.manager import ResidencyManager
        from playslap.entity import Entity
        mgr = ResidencyManager(save_dir=tmp_path)
        e = Entity(name="not_an_asset")
        mgr.update((0.0, 0.0), [e])   # must not raise

    def test_tier_constants_are_distinct_strings(self):
        from playslap.residency.manager import ResidencyManager
        tiers = {ResidencyManager.TIER_GPU, ResidencyManager.TIER_RAM, ResidencyManager.TIER_DISK}
        assert len(tiers) == 3
        assert all(isinstance(t, str) for t in tiers)

    def test_evict_to_ram_no_gpu_context(self, tmp_path):
        """evict_to_ram without a GPU context must not raise."""
        from playslap.residency.manager import ResidencyManager
        mgr = ResidencyManager(save_dir=tmp_path)
        asset = _make_asset("evict_test")
        asset.add_layer(_blank_layer(8, 8))
        mgr.evict_to_ram(asset)   # ctx=None, buf_mgr=None, tex_mgr=None
        assert mgr.tier(asset) == ResidencyManager.TIER_RAM

    def test_evict_to_disk_writes_file(self, tmp_path):
        from playslap.residency.manager import ResidencyManager
        mgr = ResidencyManager(save_dir=tmp_path)
        asset = _make_asset("to_disk")
        asset.add_layer(_blank_layer(8, 8, fill=[1, 2, 3, 255]))
        mgr.evict_to_disk(asset)
        assert mgr.tier(asset) == ResidencyManager.TIER_DISK
        slap_path = tmp_path / f"{asset.id}.slap"
        assert slap_path.exists()

    def test_multiple_entities_independent_tiers(self, tmp_path):
        from playslap.residency.manager import ResidencyManager
        mgr = ResidencyManager(save_dir=tmp_path)
        near = _make_asset("near2", position=(5.0, 5.0))
        near.add_layer(_blank_layer(8, 8))
        far = _make_asset("far2", position=(10_000.0, 10_000.0))
        far.add_layer(_blank_layer(8, 8))
        mgr.update((0.0, 0.0), [near, far])
        assert mgr.tier(near) == ResidencyManager.TIER_GPU
        assert mgr.tier(far) != ResidencyManager.TIER_GPU


# ===========================================================================
# Scene save / load
# ===========================================================================

@_requires_engine
class TestSceneSaveLoad:
    def _build_scene(self):
        from playslap.scene import Scene
        from playslap.asset import Asset
        from playslap.layer import Layer
        scene = Scene(name="TestScene")
        a = Asset(name="hero", position=(50.0, 75.0), size=(32, 32))
        layer = Layer.blank(32, 32, name="body")
        layer._image_data = np.full((32, 32, 4), [100, 150, 200, 255], dtype=np.uint8)
        a.add_layer(layer)
        scene.add(a)
        return scene

    def test_save_creates_file(self, tmp_path):
        scene = self._build_scene()
        path = tmp_path / "scene.slap"
        scene.save(str(path))
        assert path.exists()
        assert path.stat().st_size > 0

    def test_load_restores_entity_count(self, tmp_path):
        from playslap.scene import Scene
        scene = self._build_scene()
        path = tmp_path / "scene.slap"
        scene.save(str(path))

        scene2 = Scene(name="Loaded")
        scene2.load(str(path))
        assert len(scene2.entities) == 1

    def test_load_restores_entity_name(self, tmp_path):
        from playslap.scene import Scene
        scene = self._build_scene()
        path = tmp_path / "scene.slap"
        scene.save(str(path))

        scene2 = Scene(name="Loaded")
        scene2.load(str(path))
        assert scene2.entities[0].name == "hero"

    def test_load_restores_layer_image_shape(self, tmp_path):
        from playslap.scene import Scene
        scene = self._build_scene()
        path = tmp_path / "scene.slap"
        scene.save(str(path))

        scene2 = Scene(name="Loaded")
        scene2.load(str(path))
        layer = scene2.entities[0].layers[0]
        assert layer._image_data is not None
        assert layer._image_data.shape == (32, 32, 4)

    def test_load_restores_layer_pixel_values(self, tmp_path):
        from playslap.scene import Scene
        scene = self._build_scene()
        path = tmp_path / "scene.slap"
        scene.save(str(path))

        scene2 = Scene(name="Loaded")
        scene2.load(str(path))
        img = scene2.entities[0].layers[0]._image_data
        np.testing.assert_array_equal(img[0, 0], [100, 150, 200, 255])

    def test_load_clear_replaces_existing_entities(self, tmp_path):
        from playslap.scene import Scene
        from playslap.entity import Entity
        scene = self._build_scene()
        path = tmp_path / "scene.slap"
        scene.save(str(path))

        scene2 = Scene(name="Fresh")
        scene2.add(Entity(name="old_entity"))
        scene2.load(str(path), clear=True)
        assert len(scene2.entities) == 1
        assert scene2.entities[0].name == "hero"

    def test_load_no_clear_appends(self, tmp_path):
        from playslap.scene import Scene
        from playslap.entity import Entity
        scene = self._build_scene()
        path = tmp_path / "scene.slap"
        scene.save(str(path))

        scene2 = Scene(name="Accumulate")
        scene2.add(Entity(name="existing"))
        scene2.load(str(path), clear=False)
        assert len(scene2.entities) == 2

    def test_save_load_multiple_assets(self, tmp_path):
        from playslap.scene import Scene
        from playslap.asset import Asset
        scene = Scene(name="Multi")
        for i in range(4):
            a = Asset(name=f"entity_{i}", position=(float(i * 50), 0.0), size=(16, 16))
            a.add_layer(_blank_layer(16, 16, "base"))
            scene.add(a)
        path = tmp_path / "multi_scene.slap"
        scene.save(str(path))

        scene2 = Scene(name="Loaded")
        scene2.load(str(path))
        assert len(scene2.entities) == 4
        names = {e.name for e in scene2.entities}
        assert names == {f"entity_{i}" for i in range(4)}

    def test_load_restores_position(self, tmp_path):
        from playslap.scene import Scene
        scene = self._build_scene()
        path = tmp_path / "pos_scene.slap"
        scene.save(str(path))

        scene2 = Scene(name="Loaded")
        scene2.load(str(path))
        pos = scene2.entities[0].position
        assert pos[0] == pytest.approx(50.0)
        assert pos[1] == pytest.approx(75.0)
