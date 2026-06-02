"""Engine tests for DeformRepairer and AssetDatabase — headless."""
from __future__ import annotations
import numpy as np
import pytest
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# DeformRepairer
# ---------------------------------------------------------------------------

class _FakeLayer:
    def __init__(self, w=32, h=32, alpha=200):
        data = np.zeros((h, w, 4), dtype=np.uint8)
        data[:, :, 3] = alpha
        self._image_data = data
        self.name = "test"
        self.opacity = 1.0
        self.visible = True
        self.size = (w, h)
        self.channel_map = {}


class TestDeformRepairerInit:
    def test_init_stores_layer(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = _FakeLayer()
        dr = DeformRepairer(layer)
        assert dr._layer is layer

    def test_init_no_original_alpha(self):
        from slappyengine.deform_repair import DeformRepairer
        dr = DeformRepairer(_FakeLayer())
        assert dr._original_alpha is None

    def test_pending_empty_initially(self):
        from slappyengine.deform_repair import DeformRepairer
        dr = DeformRepairer(_FakeLayer())
        assert dr._pending == []


class TestDeformRepairerQueue:
    def test_queue_radial_adds_event(self):
        from slappyengine.deform_repair import DeformRepairer
        dr = DeformRepairer(_FakeLayer())
        dr.queue_radial(16, 16, radius=8.0, rate=2.0)
        assert len(dr._pending) == 1
        assert dr._pending[0]["mode"] == 0  # falloff mode

    def test_queue_radial_no_falloff(self):
        from slappyengine.deform_repair import DeformRepairer
        dr = DeformRepairer(_FakeLayer())
        dr.queue_radial(16, 16, radius=8.0, rate=2.0, falloff=False)
        assert dr._pending[0]["mode"] == 1

    def test_queue_pixel(self):
        from slappyengine.deform_repair import DeformRepairer
        dr = DeformRepairer(_FakeLayer())
        dr.queue_pixel(5, 10, rate=5.0)
        assert len(dr._pending) == 1
        assert dr._pending[0]["center_x"] == 5.0
        assert dr._pending[0]["center_y"] == 10.0

    def test_queue_full(self):
        from slappyengine.deform_repair import DeformRepairer
        dr = DeformRepairer(_FakeLayer())
        dr.queue_full(rate=1.0)
        assert len(dr._pending) == 1
        assert dr._pending[0]["mode"] == 2

    def test_multiple_queues(self):
        from slappyengine.deform_repair import DeformRepairer
        dr = DeformRepairer(_FakeLayer())
        dr.queue_radial(8, 8, radius=4.0)
        dr.queue_pixel(2, 2)
        dr.queue_full()
        assert len(dr._pending) == 3


class TestDeformRepairerDispatch:
    def test_dispatch_clears_pending(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = _FakeLayer(alpha=100)
        dr = DeformRepairer(layer)
        dr.queue_full(rate=1.0)
        dr.dispatch()
        assert dr._pending == []

    def test_dispatch_empty_no_crash(self):
        from slappyengine.deform_repair import DeformRepairer
        dr = DeformRepairer(_FakeLayer())
        dr.dispatch()  # no pending — should not raise

    def test_full_repair_increases_alpha(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = _FakeLayer(alpha=100)
        dr = DeformRepairer(layer)
        dr.queue_full(rate=10.0)
        dr.dispatch()
        # All alpha values should have increased
        assert np.all(layer._image_data[:, :, 3] >= 100)
        assert np.any(layer._image_data[:, :, 3] > 100)

    def test_full_repair_capped_at_255(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = _FakeLayer(alpha=250)
        dr = DeformRepairer(layer)
        dr.queue_full(rate=100.0)
        dr.dispatch()
        assert np.all(layer._image_data[:, :, 3] <= 255)

    def test_full_repair_capped_at_original_alpha(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = _FakeLayer(alpha=50)
        original = np.full((32, 32), 150.0, dtype=np.float32)
        dr = DeformRepairer(layer, original_alpha=original)
        dr.queue_full(rate=200.0)
        dr.dispatch()
        assert np.all(layer._image_data[:, :, 3] <= 150)

    def test_radial_repair_heals_center_more_than_edge(self):
        from slappyengine.deform_repair import DeformRepairer
        h, w = 64, 64
        layer = _FakeLayer(w=w, h=h, alpha=0)
        dr = DeformRepairer(layer)
        dr.queue_radial(32, 32, radius=16.0, rate=100.0, falloff=True)
        dr.dispatch()
        center_alpha = int(layer._image_data[32, 32, 3])
        edge_alpha = int(layer._image_data[32, 47, 3])  # near radius edge
        assert center_alpha > edge_alpha

    def test_radial_no_falloff_uniform_within_radius(self):
        from slappyengine.deform_repair import DeformRepairer
        h, w = 64, 64
        layer = _FakeLayer(w=w, h=h, alpha=0)
        dr = DeformRepairer(layer)
        dr.queue_radial(32, 32, radius=10.0, rate=50.0, falloff=False)
        dr.dispatch()
        # Pixels inside radius should have alpha ≈ 50, outside should be 0
        inside = int(layer._image_data[32, 32, 3])
        outside = int(layer._image_data[32, 50, 3])  # > radius from center
        assert inside > 0
        assert outside == 0

    def test_dispatch_with_none_image_data_no_crash(self):
        from slappyengine.deform_repair import DeformRepairer

        class NoData:
            _image_data = None
        dr = DeformRepairer(NoData())
        dr.queue_full(rate=1.0)
        dr.dispatch()  # should not raise


# ---------------------------------------------------------------------------
# AssetDatabase
# ---------------------------------------------------------------------------

class TestAssetDatabase:
    def test_instance_singleton(self):
        from slappyengine.assets.database import AssetDatabase
        a = AssetDatabase.instance()
        b = AssetDatabase.instance()
        assert a is b

    def test_register_handler(self):
        from slappyengine.assets.database import AssetDatabase
        db = AssetDatabase()
        calls = []
        db.register_handler(".tst", lambda path: calls.append(path) or "loaded")
        assert ".tst" in db._handlers

    def test_no_handler_raises(self):
        from slappyengine.assets.database import AssetDatabase
        db = AssetDatabase()
        with pytest.raises(ValueError):
            db.load("nonexistent.xyz_unknown_ext")

    def test_load_yaml(self, tmp_path):
        from slappyengine.assets.database import AssetDatabase
        db = AssetDatabase()
        yf = tmp_path / "config.yml"
        yf.write_text("key: value\nnumber: 42\n", encoding="utf-8")
        result = db.load(str(yf))
        assert result["key"] == "value"
        assert result["number"] == 42

    def test_load_yaml_cached(self, tmp_path):
        from slappyengine.assets.database import AssetDatabase
        db = AssetDatabase()
        yf = tmp_path / "cached.yml"
        yf.write_text("a: 1\n", encoding="utf-8")
        r1 = db.load(str(yf))
        r2 = db.load(str(yf))
        assert r1 is r2

    def test_get_record_after_load(self, tmp_path):
        from slappyengine.assets.database import AssetDatabase
        db = AssetDatabase()
        yf = tmp_path / "rec.yml"
        yf.write_text("x: 1\n", encoding="utf-8")
        db.load(str(yf))
        rec = db.get_record(str(yf))
        assert rec is not None
        assert rec.asset_type == "yml"

    def test_get_record_none_when_not_loaded(self):
        from slappyengine.assets.database import AssetDatabase
        db = AssetDatabase()
        assert db.get_record("/nonexistent/path.yml") is None

    def test_all_records_returns_list(self, tmp_path):
        from slappyengine.assets.database import AssetDatabase
        db = AssetDatabase()
        yf = tmp_path / "list.yml"
        yf.write_text("n: 1\n", encoding="utf-8")
        db.load(str(yf))
        records = db.all_records()
        assert isinstance(records, list)
        assert len(records) >= 1

    def test_force_reload(self, tmp_path):
        from slappyengine.assets.database import AssetDatabase
        db = AssetDatabase()
        yf = tmp_path / "reload.yml"
        yf.write_text("v: 1\n", encoding="utf-8")
        r1 = db.load(str(yf))
        yf.write_text("v: 99\n", encoding="utf-8")
        r2 = db.load(str(yf), force_reload=True)
        assert r2["v"] == 99

    def test_load_custom_extension(self, tmp_path):
        from slappyengine.assets.database import AssetDatabase
        db = AssetDatabase()
        custom = tmp_path / "data.myext"
        custom.write_bytes(b"raw data")
        db.register_handler(".myext", lambda p: open(p, "rb").read())
        result = db.load(str(custom))
        assert result == b"raw data"
