"""Engine tests for assets/database.py — AssetDatabase, AssetRecord.
All headless — no GPU required.
"""
from __future__ import annotations
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_db():
    """Return a new AssetDatabase instance, bypassing the singleton."""
    from pharos_engine.assets.database import AssetDatabase
    return AssetDatabase()  # direct __init__, not .instance()


# ---------------------------------------------------------------------------
# AssetRecord
# ---------------------------------------------------------------------------

class TestAssetRecord:
    def test_instantiates(self, tmp_path):
        from pharos_engine.assets.database import AssetRecord
        f = tmp_path / "test.txt"
        f.write_text("data")
        rec = AssetRecord(str(f), asset="hello", asset_type="txt")
        assert rec is not None

    def test_path_stored(self, tmp_path):
        from pharos_engine.assets.database import AssetRecord
        f = tmp_path / "a.txt"
        f.write_text("x")
        rec = AssetRecord(str(f), asset=None, asset_type="txt")
        assert rec.path == str(f)

    def test_asset_stored(self, tmp_path):
        from pharos_engine.assets.database import AssetRecord
        f = tmp_path / "b.txt"
        f.write_text("y")
        sentinel = object()
        rec = AssetRecord(str(f), asset=sentinel, asset_type="txt")
        assert rec.asset is sentinel

    def test_size_bytes(self, tmp_path):
        from pharos_engine.assets.database import AssetRecord
        f = tmp_path / "sized.txt"
        f.write_bytes(b"1234567890")
        rec = AssetRecord(str(f), asset=None, asset_type="txt")
        assert rec.size_bytes == 10

    def test_last_modified_positive(self, tmp_path):
        from pharos_engine.assets.database import AssetRecord
        f = tmp_path / "ts.txt"
        f.write_text("time")
        rec = AssetRecord(str(f), asset=None, asset_type="txt")
        assert rec.last_modified > 0

    def test_thumbnail_path_initially_none(self, tmp_path):
        from pharos_engine.assets.database import AssetRecord
        f = tmp_path / "img.png"
        f.write_bytes(b"\x89PNG")
        rec = AssetRecord(str(f), asset=None, asset_type="png")
        assert rec.thumbnail_path is None


# ---------------------------------------------------------------------------
# AssetDatabase init
# ---------------------------------------------------------------------------

class TestAssetDatabaseInit:
    def test_instantiates(self):
        db = _fresh_db()
        assert db is not None

    def test_registry_initially_empty(self):
        db = _fresh_db()
        assert db.all_records() == []

    def test_default_handlers_for_images(self):
        db = _fresh_db()
        for ext in (".png", ".jpg", ".jpeg", ".bmp"):
            assert ext in db._handlers

    def test_default_handler_for_yaml(self):
        db = _fresh_db()
        assert ".yml" in db._handlers
        assert ".yaml" in db._handlers

    def test_default_handler_for_slap(self):
        db = _fresh_db()
        assert ".slap" in db._handlers


# ---------------------------------------------------------------------------
# AssetDatabase.instance() singleton
# ---------------------------------------------------------------------------

class TestAssetDatabaseSingleton:
    def test_instance_returns_same_object(self):
        from pharos_engine.assets.database import AssetDatabase
        a = AssetDatabase.instance()
        b = AssetDatabase.instance()
        assert a is b

    def test_instance_is_asset_database(self):
        from pharos_engine.assets.database import AssetDatabase
        assert isinstance(AssetDatabase.instance(), AssetDatabase)


# ---------------------------------------------------------------------------
# AssetDatabase.register_handler
# ---------------------------------------------------------------------------

class TestAssetDatabaseRegisterHandler:
    def test_register_custom_extension(self):
        db = _fresh_db()
        db.register_handler(".tmx", lambda p: {"tilemap": True})
        assert ".tmx" in db._handlers

    def test_custom_handler_lowercase_normalised(self):
        db = _fresh_db()
        db.register_handler(".TMX", lambda p: {})
        assert ".tmx" in db._handlers

    def test_register_overrides_existing(self):
        db = _fresh_db()
        sentinel = lambda p: "custom"
        db.register_handler(".png", sentinel)
        assert db._handlers[".png"] is sentinel


# ---------------------------------------------------------------------------
# AssetDatabase.load — custom handler path
# ---------------------------------------------------------------------------

class TestAssetDatabaseLoad:
    def test_load_with_custom_handler(self, tmp_path):
        db = _fresh_db()
        f = tmp_path / "level.bin"
        f.write_bytes(b"LEVELDATA")
        db.register_handler(".bin", lambda p: {"raw": open(p, "rb").read()})
        result = db.load(str(f))
        assert result["raw"] == b"LEVELDATA"

    def test_load_caches_result(self, tmp_path):
        db = _fresh_db()
        f = tmp_path / "data.bin"
        f.write_bytes(b"abc")
        call_count = [0]
        def loader(p):
            call_count[0] += 1
            return call_count[0]
        db.register_handler(".bin", loader)
        r1 = db.load(str(f))
        r2 = db.load(str(f))
        assert r1 == r2
        assert call_count[0] == 1  # loaded once

    def test_force_reload_bypasses_cache(self, tmp_path):
        db = _fresh_db()
        f = tmp_path / "data.bin"
        f.write_bytes(b"x")
        call_count = [0]
        def loader(p):
            call_count[0] += 1
            return call_count[0]
        db.register_handler(".bin", loader)
        db.load(str(f))
        db.load(str(f), force_reload=True)
        assert call_count[0] == 2

    def test_load_unknown_extension_raises(self, tmp_path):
        db = _fresh_db()
        f = tmp_path / "weird.zzz"
        f.write_bytes(b"data")
        with pytest.raises(ValueError, match="No asset handler"):
            db.load(str(f))

    def test_load_yaml(self, tmp_path):
        db = _fresh_db()
        f = tmp_path / "config.yml"
        f.write_text("key: value\nnum: 42\n")
        result = db.load(str(f))
        assert result["key"] == "value"
        assert result["num"] == 42

    def test_load_yaml_empty_file(self, tmp_path):
        db = _fresh_db()
        f = tmp_path / "empty.yml"
        f.write_text("")
        result = db.load(str(f))
        assert result == {}


# ---------------------------------------------------------------------------
# AssetDatabase.all_records / get_record
# ---------------------------------------------------------------------------

class TestAssetDatabaseRecords:
    def test_all_records_empty_initially(self):
        db = _fresh_db()
        assert db.all_records() == []

    def test_all_records_after_load(self, tmp_path):
        db = _fresh_db()
        f = tmp_path / "asset.bin"
        f.write_bytes(b"data")
        db.register_handler(".bin", lambda p: "loaded")
        db.load(str(f))
        records = db.all_records()
        assert len(records) == 1

    def test_get_record_after_load(self, tmp_path):
        db = _fresh_db()
        f = tmp_path / "item.bin"
        f.write_bytes(b"xyz")
        db.register_handler(".bin", lambda p: "ok")
        db.load(str(f))
        rec = db.get_record(str(f))
        assert rec is not None
        assert rec.asset == "ok"

    def test_get_record_missing_returns_none(self):
        db = _fresh_db()
        assert db.get_record("nonexistent/path.bin") is None

    def test_record_asset_type_from_extension(self, tmp_path):
        db = _fresh_db()
        f = tmp_path / "sprite.png_"
        f.write_bytes(b"content")
        db.register_handler(".png_", lambda p: None)
        db.load(str(f))
        rec = db.get_record(str(f))
        assert rec.asset_type == "png_"

    def test_multiple_loads_multiple_records(self, tmp_path):
        db = _fresh_db()
        db.register_handler(".bin", lambda p: None)
        for i in range(3):
            f = tmp_path / f"file{i}.bin"
            f.write_bytes(b"x")
            db.load(str(f))
        assert len(db.all_records()) == 3
