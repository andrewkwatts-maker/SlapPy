"""Negative-path tests for :class:`AssetDatabase` public-boundary validation
(hardening round 5).

The positive paths (image loading via ``load``, default handlers, watch
on a real directory) are exercised implicitly by the editor and demo
suites. This file only covers the rejection cases added by the new
``_validation.py`` helpers.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "python"))

from pharos_engine.assets.database import AssetDatabase  # noqa: E402


@pytest.fixture
def db() -> AssetDatabase:
    """Fresh DB instance — not the singleton, to avoid leaking handlers
    between tests."""
    return AssetDatabase()


# ---------------------------------------------------------------------------
# load(path, force_reload)
# ---------------------------------------------------------------------------

def test_load_rejects_int_path(db):
    with pytest.raises(TypeError, match="path must be str or pathlib.Path"):
        db.load(123)


def test_load_rejects_none_path(db):
    with pytest.raises(TypeError, match="path must be str or pathlib.Path"):
        db.load(None)


def test_load_rejects_bytes_path(db):
    # Path(b'x') is platform-dependent on Windows and a known footgun.
    with pytest.raises(TypeError, match="path must be str or pathlib.Path"):
        db.load(b"sprite.png")


def test_load_rejects_empty_string_path(db):
    with pytest.raises(ValueError, match="path must not be empty"):
        db.load("")


def test_load_rejects_bool_path(db):
    # bool is an int subclass — would silently resolve to "True" path otherwise.
    with pytest.raises(TypeError, match="path must be str or pathlib.Path"):
        db.load(True)


def test_load_rejects_int_force_reload(db, tmp_path):
    # Truthy int silently widens the contract: force_reload=1 used to "work".
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    with pytest.raises(TypeError, match="force_reload must be bool"):
        db.load(img, force_reload=1)


def test_load_rejects_string_force_reload(db, tmp_path):
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    with pytest.raises(TypeError, match="force_reload must be bool"):
        db.load(img, force_reload="yes")


# ---------------------------------------------------------------------------
# register_handler(ext, loader)
# ---------------------------------------------------------------------------

def test_register_handler_rejects_non_string_ext(db):
    with pytest.raises(TypeError, match="ext must be a str"):
        db.register_handler(123, lambda p: None)


def test_register_handler_rejects_extension_without_dot(db):
    with pytest.raises(ValueError, match=r"ext must start with '\.'"):
        db.register_handler("tmx", lambda p: None)


def test_register_handler_rejects_empty_extension(db):
    with pytest.raises(ValueError, match="ext must not be empty"):
        db.register_handler("", lambda p: None)


def test_register_handler_rejects_bare_dot(db):
    with pytest.raises(ValueError, match="must include at least one char"):
        db.register_handler(".", lambda p: None)


def test_register_handler_rejects_extension_with_separator(db):
    with pytest.raises(ValueError, match="must be a bare extension"):
        db.register_handler(".foo/bar", lambda p: None)


def test_register_handler_rejects_extension_with_whitespace(db):
    with pytest.raises(ValueError, match="must not contain whitespace"):
        db.register_handler(".tm x", lambda p: None)


def test_register_handler_rejects_non_callable_loader(db):
    with pytest.raises(TypeError, match="loader must be callable"):
        db.register_handler(".tmx", "not a function")


def test_register_handler_rejects_none_loader(db):
    with pytest.raises(TypeError, match="loader must be callable"):
        db.register_handler(".tmx", None)


def test_register_handler_normalises_case(db):
    """Positive sanity: validator round-trips and stores lower-cased ext."""
    sentinel = lambda p: ("loaded", p)
    db.register_handler(".TMX", sentinel)
    assert db._handlers[".tmx"] is sentinel


# ---------------------------------------------------------------------------
# watch(directory)
# ---------------------------------------------------------------------------

def test_watch_rejects_int_directory(db):
    with pytest.raises(TypeError, match="directory must be str or pathlib.Path"):
        db.watch(42)


def test_watch_rejects_empty_directory(db):
    with pytest.raises(ValueError, match="directory must not be empty"):
        db.watch("")


def test_watch_rejects_none_directory(db):
    with pytest.raises(TypeError, match="directory must be str or pathlib.Path"):
        db.watch(None)


# ---------------------------------------------------------------------------
# get_record(path)
# ---------------------------------------------------------------------------

def test_get_record_rejects_int_path(db):
    with pytest.raises(TypeError, match="path must be str or pathlib.Path"):
        db.get_record(7)


def test_get_record_rejects_empty_string_path(db):
    with pytest.raises(ValueError, match="path must not be empty"):
        db.get_record("")


def test_get_record_missing_returns_none(db, tmp_path):
    """Positive sanity: validator doesn't break the documented contract."""
    assert db.get_record(tmp_path / "never_loaded.png") is None
