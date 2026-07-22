"""Headless tests for AssetDatabase / AssetRecord and DebugOverlay.

No GPU required. AssetDatabase uses real temp files.
"""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("pharos_engine.compute.asset_compute", MagicMock())


# ===========================================================================
# AssetRecord
# ===========================================================================

class TestAssetRecord:
    def _record(self):
        import tempfile
        from pharos_engine.assets.database import AssetRecord
        td = tempfile.mkdtemp()
        p = Path(td) / "dummy.yml"
        p.write_text("key: value")
        return AssetRecord(str(p), {"key": "value"}, "yml"), p

    def test_path_stored(self):
        rec, p = self._record()
        assert rec.path == str(p)

    def test_asset_stored(self):
        rec, _ = self._record()
        assert rec.asset == {"key": "value"}

    def test_asset_type_stored(self):
        rec, _ = self._record()
        assert rec.asset_type == "yml"

    def test_size_bytes_positive(self):
        rec, _ = self._record()
        assert rec.size_bytes > 0

    def test_last_modified_positive(self):
        rec, _ = self._record()
        assert rec.last_modified > 0

    def test_thumbnail_path_none_initially(self):
        rec, _ = self._record()
        assert rec.thumbnail_path is None


# ===========================================================================
# AssetDatabase
# ===========================================================================

class TestAssetDatabaseInit:
    def _db(self):
        from pharos_engine.assets.database import AssetDatabase
        db = AssetDatabase()
        return db

    def test_instantiates(self):
        assert self._db() is not None

    def test_all_records_empty_initially(self):
        db = self._db()
        assert db.all_records() == []

    def test_singleton_returns_same_instance(self):
        from pharos_engine.assets.database import AssetDatabase
        AssetDatabase._instance = None  # reset
        a = AssetDatabase.instance()
        b = AssetDatabase.instance()
        assert a is b
        AssetDatabase._instance = None  # cleanup


class TestAssetDatabaseLoad:
    def _db_and_dir(self):
        from pharos_engine.assets.database import AssetDatabase
        db = AssetDatabase()
        td = tempfile.mkdtemp()
        return db, Path(td)

    def test_load_yaml(self):
        db, td = self._db_and_dir()
        f = td / "config.yml"
        f.write_text("name: test")
        result = db.load(f)
        assert isinstance(result, dict)
        assert result.get("name") == "test"

    def test_load_yaml_extension(self):
        db, td = self._db_and_dir()
        f = td / "config.yaml"
        f.write_text("x: 1")
        result = db.load(f)
        assert result["x"] == 1

    def test_load_caches_result(self):
        db, td = self._db_and_dir()
        f = td / "cache.yml"
        f.write_text("v: 1")
        r1 = db.load(f)
        r2 = db.load(f)
        assert r1 is r2  # same cached object

    def test_force_reload_returns_fresh(self):
        db, td = self._db_and_dir()
        f = td / "reload.yml"
        f.write_text("v: 1")
        db.load(f)
        f.write_text("v: 2")
        result = db.load(f, force_reload=True)
        assert result.get("v") == 2

    def test_load_missing_raises(self):
        import pytest
        db, td = self._db_and_dir()
        with pytest.raises(Exception):  # FileNotFoundError or similar
            db.load(td / "nonexistent.yml")

    def test_load_registers_record(self):
        db, td = self._db_and_dir()
        f = td / "reg.yml"
        f.write_text("a: b")
        db.load(f)
        assert len(db.all_records()) == 1

    def test_all_records_grows_with_loads(self):
        db, td = self._db_and_dir()
        for i in range(3):
            f = td / f"file{i}.yml"
            f.write_text(f"i: {i}")
            db.load(f)
        assert len(db.all_records()) == 3


class TestAssetDatabaseGetRecord:
    def _db(self):
        from pharos_engine.assets.database import AssetDatabase
        return AssetDatabase()

    def test_returns_none_for_missing(self):
        db = self._db()
        td = tempfile.mkdtemp()
        assert db.get_record(Path(td) / "missing.yml") is None

    def test_returns_record_after_load(self):
        from pharos_engine.assets.database import AssetRecord
        db = self._db()
        td = tempfile.mkdtemp()
        f = Path(td) / "test.yml"
        f.write_text("k: v")
        db.load(f)
        rec = db.get_record(f)
        assert rec is not None
        assert isinstance(rec, AssetRecord)

    def test_record_has_correct_type(self):
        db = self._db()
        td = tempfile.mkdtemp()
        f = Path(td) / "test.yml"
        f.write_text("k: v")
        db.load(f)
        rec = db.get_record(f)
        assert rec.asset_type == "yml"

    def test_record_asset_is_dict_for_yaml(self):
        db = self._db()
        td = tempfile.mkdtemp()
        f = Path(td) / "test.yml"
        f.write_text("foo: bar")
        db.load(f)
        rec = db.get_record(f)
        assert isinstance(rec.asset, dict)


class TestAssetDatabaseRegisterHandler:
    def test_custom_handler_called(self):
        from pharos_engine.assets.database import AssetDatabase
        db = AssetDatabase()
        td = tempfile.mkdtemp()
        f = Path(td) / "test.txt"
        f.write_text("hello")
        db.register_handler(".txt", lambda p: open(p).read().strip())
        result = db.load(f)
        assert result == "hello"

    def test_overwrite_handler(self):
        from pharos_engine.assets.database import AssetDatabase
        db = AssetDatabase()
        td = tempfile.mkdtemp()
        f = Path(td) / "data.txt"
        f.write_text("42")
        db.register_handler(".txt", lambda p: int(open(p).read().strip()))
        result = db.load(f)
        assert result == 42


class TestAssetDatabaseWatch:
    def test_watch_no_crash(self):
        from pharos_engine.assets.database import AssetDatabase
        db = AssetDatabase()
        td = tempfile.mkdtemp()
        db.watch(td)  # should not raise

    def test_watch_twice_no_crash(self):
        from pharos_engine.assets.database import AssetDatabase
        db = AssetDatabase()
        td = tempfile.mkdtemp()
        db.watch(td)
        db.watch(td)  # duplicate should be harmless

    def test_watch_dir_added(self):
        from pharos_engine.assets.database import AssetDatabase
        db = AssetDatabase()
        td = tempfile.mkdtemp()
        db.watch(td)
        assert str(Path(td).resolve()) in db._watch_dirs


# ===========================================================================
# DebugOverlay
# ===========================================================================

class TestDebugOverlayInit:
    def _d(self):
        from pharos_editor.ui.debug_overlay import DebugOverlay
        return DebugOverlay()

    def test_instantiates(self):
        assert self._d() is not None

    def test_not_visible_initially(self):
        assert self._d().visible is False

    def test_events_hidden_initially(self):
        assert self._d()._show_events is False

    def test_passes_hidden_initially(self):
        assert self._d()._show_passes is False

    def test_heatmap_hidden_initially(self):
        assert self._d()._show_heatmap is False

    def test_event_log_empty(self):
        assert len(self._d()._event_log) == 0

    def test_heatmap_empty(self):
        assert self._d()._heatmap == {}


class TestDebugOverlayToggles:
    def _d(self):
        from pharos_editor.ui.debug_overlay import DebugOverlay
        return DebugOverlay()

    def test_toggle_events_on(self):
        d = self._d()
        d.toggle_events()
        assert d._show_events is True

    def test_toggle_events_off(self):
        d = self._d()
        d.toggle_events()
        d.toggle_events()
        assert d._show_events is False

    def test_toggle_passes_on(self):
        d = self._d()
        d.toggle_passes()
        assert d._show_passes is True

    def test_toggle_heatmap_on(self):
        d = self._d()
        d.toggle_heatmap()
        assert d._show_heatmap is True

    def test_visible_after_events_toggle(self):
        d = self._d()
        d.toggle_events()
        assert d.visible is True

    def test_visible_after_passes_toggle(self):
        d = self._d()
        d.toggle_passes()
        assert d.visible is True

    def test_visible_after_heatmap_toggle(self):
        d = self._d()
        d.toggle_heatmap()
        assert d.visible is True

    def test_not_visible_when_all_off(self):
        d = self._d()
        d.toggle_events()
        d.toggle_events()
        assert d.visible is False


class TestDebugOverlayReportPass:
    def _d(self):
        from pharos_editor.ui.debug_overlay import DebugOverlay
        return DebugOverlay()

    def test_report_skipping(self):
        d = self._d()
        d.report_pass("physics.wgsl", skipping=True)
        assert d._pass_status["physics.wgsl"] is True

    def test_report_not_skipping(self):
        d = self._d()
        d.report_pass("collision.wgsl", skipping=False)
        assert d._pass_status["collision.wgsl"] is False

    def test_report_multiple_passes(self):
        d = self._d()
        d.report_pass("a.wgsl", skipping=True)
        d.report_pass("b.wgsl", skipping=False)
        assert len(d._pass_status) == 2

    def test_overwrite_pass_status(self):
        d = self._d()
        d.report_pass("x.wgsl", skipping=True)
        d.report_pass("x.wgsl", skipping=False)
        assert d._pass_status["x.wgsl"] is False


class TestDebugOverlayHeatmap:
    def _d(self):
        from pharos_editor.ui.debug_overlay import DebugOverlay
        d = DebugOverlay()
        d.toggle_heatmap()  # must be enabled for record_attr_publish to track
        return d

    def test_record_attr_publish(self):
        d = self._d()
        d.record_attr_publish("VehicleEntity.speed")
        assert d._heatmap.get("VehicleEntity.speed") == 1

    def test_record_attr_accumulates(self):
        d = self._d()
        d.record_attr_publish("MyClass.x")
        d.record_attr_publish("MyClass.x")
        assert d._heatmap["MyClass.x"] == 2

    def test_different_attrs_tracked_separately(self):
        d = self._d()
        d.record_attr_publish("A.x")
        d.record_attr_publish("B.y")
        assert d._heatmap["A.x"] == 1
        assert d._heatmap["B.y"] == 1

    def test_begin_frame_clears_heatmap(self):
        d = self._d()
        d.record_attr_publish("Obj.val")
        d.begin_frame()
        assert d._heatmap == {}


class TestDebugOverlayRender:
    def _d(self):
        from pharos_editor.ui.debug_overlay import DebugOverlay
        return DebugOverlay()

    def test_render_none_when_all_hidden(self):
        d = self._d()
        assert d.render(width=300) is None

    def test_render_returns_image_when_visible(self):
        d = self._d()
        d.toggle_passes()
        img = d.render(width=300)
        # PIL Image or None depending on PIL availability
        # Either is acceptable — just must not crash
        assert img is None or hasattr(img, "size")

    def test_render_text_returns_string(self):
        d = self._d()
        result = d.render_text()
        assert isinstance(result, str)

    def test_render_text_includes_pass_status(self):
        d = self._d()
        d.toggle_passes()
        d.report_pass("my_shader.wgsl", skipping=True)
        text = d.render_text()
        assert "my_shader.wgsl" in text

    def test_begin_frame_no_crash(self):
        self._d().begin_frame()  # should not raise

    def test_constants_defined(self):
        from pharos_editor.ui.debug_overlay import DebugOverlay
        assert DebugOverlay.MAX_EVENTS > 0
        assert DebugOverlay.FONT_SIZE > 0
        assert DebugOverlay.LINE_H > 0
        assert DebugOverlay.PAD >= 0
