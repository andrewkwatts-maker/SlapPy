"""Negative-path tests for :class:`ResidencyManager` public-boundary
validation (hardening round 5).

The positive paths (tier transitions, .slap round-trips, multi-entity
distance bucketing) are covered by ``test_residency.py``. This file only
exercises the rejection cases added by the new ``_validation.py`` module.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

# Some platforms (CI without wgpu.gui) can't import slappyengine.* eagerly.
# Mirror the gate used by tests/test_residency.py.
_SKIP = ""
try:
    import slappyengine  # noqa: F401
    _OK = True
except Exception as exc:
    _OK = False
    _SKIP = str(exc)

pytestmark = pytest.mark.skipif(not _OK, reason=f"slappyengine unavailable: {_SKIP}")


# ---------------------------------------------------------------------------
# Helpers (mirror test_residency.py)
# ---------------------------------------------------------------------------

def _make_asset(name="test", position=(0.0, 0.0), size=(16, 16)):
    from slappyengine.asset import Asset
    return Asset(name=name, position=position, size=size)


def _blank_layer(w, h, name="layer"):
    from slappyengine.layer import Layer
    return Layer.blank(w, h, name=name)


# ---------------------------------------------------------------------------
# __init__(save_dir=...)
# ---------------------------------------------------------------------------

def test_init_rejects_int_save_dir():
    from slappyengine.residency.manager import ResidencyManager
    with pytest.raises(TypeError, match="save_dir must be str or pathlib.Path"):
        ResidencyManager(save_dir=42)


def test_init_rejects_none_save_dir():
    from slappyengine.residency.manager import ResidencyManager
    with pytest.raises(TypeError, match="save_dir must be str or pathlib.Path"):
        ResidencyManager(save_dir=None)


def test_init_rejects_empty_save_dir():
    from slappyengine.residency.manager import ResidencyManager
    with pytest.raises(ValueError, match="save_dir must not be empty"):
        ResidencyManager(save_dir="")


def test_init_rejects_bool_save_dir():
    # bool is int subclass — would silently flow into Path(True).
    from slappyengine.residency.manager import ResidencyManager
    with pytest.raises(TypeError, match="save_dir must be str or pathlib.Path"):
        ResidencyManager(save_dir=True)


def test_init_accepts_path_object(tmp_path):
    """Positive sanity: pathlib.Path remains the canonical input."""
    from slappyengine.residency.manager import ResidencyManager
    mgr = ResidencyManager(save_dir=tmp_path)
    assert mgr._save_dir == tmp_path


# ---------------------------------------------------------------------------
# tier(entity)
# ---------------------------------------------------------------------------

def test_tier_rejects_none(tmp_path):
    from slappyengine.residency.manager import ResidencyManager
    mgr = ResidencyManager(save_dir=tmp_path)
    with pytest.raises(TypeError, match="entity must not be None"):
        mgr.tier(None)


def test_tier_rejects_plain_object(tmp_path):
    from slappyengine.residency.manager import ResidencyManager
    mgr = ResidencyManager(save_dir=tmp_path)
    with pytest.raises(TypeError, match="must have an 'id' attribute"):
        mgr.tier(object())


def test_tier_rejects_object_missing_layers(tmp_path):
    """Has .id but no .layers — would crash later inside evict_to_ram."""
    from slappyengine.residency.manager import ResidencyManager
    mgr = ResidencyManager(save_dir=tmp_path)

    class HalfEntity:
        id = "abc"

    with pytest.raises(TypeError, match="must have a 'layers' attribute"):
        mgr.tier(HalfEntity())


# ---------------------------------------------------------------------------
# update(camera_pos, entities)
# ---------------------------------------------------------------------------

def test_update_rejects_three_element_camera_pos(tmp_path):
    from slappyengine.residency.manager import ResidencyManager
    mgr = ResidencyManager(save_dir=tmp_path)
    with pytest.raises(ValueError, match="must have length 2"):
        mgr.update((0.0, 0.0, 0.0), [])


def test_update_rejects_string_camera_pos(tmp_path):
    from slappyengine.residency.manager import ResidencyManager
    mgr = ResidencyManager(save_dir=tmp_path)
    with pytest.raises(TypeError, match="camera_pos must be a 2-tuple"):
        mgr.update("origin", [])


def test_update_rejects_nan_camera_pos(tmp_path):
    """NaN distances would tier every entity to DISK on the next frame."""
    from slappyengine.residency.manager import ResidencyManager
    mgr = ResidencyManager(save_dir=tmp_path)
    with pytest.raises(ValueError, match=r"camera_pos\[0\] must be finite"):
        mgr.update((float("nan"), 0.0), [])


def test_update_rejects_inf_camera_pos(tmp_path):
    from slappyengine.residency.manager import ResidencyManager
    mgr = ResidencyManager(save_dir=tmp_path)
    with pytest.raises(ValueError, match=r"camera_pos\[1\] must be finite"):
        mgr.update((0.0, float("inf")), [])


def test_update_rejects_bool_camera_pos_member(tmp_path):
    from slappyengine.residency.manager import ResidencyManager
    mgr = ResidencyManager(save_dir=tmp_path)
    with pytest.raises(TypeError, match=r"camera_pos\[0\] must be a real number"):
        mgr.update((True, 0.0), [])


def test_update_rejects_string_entities(tmp_path):
    from slappyengine.residency.manager import ResidencyManager
    mgr = ResidencyManager(save_dir=tmp_path)
    with pytest.raises(TypeError, match="entities must be a list or tuple"):
        mgr.update((0.0, 0.0), "asset")


def test_update_rejects_dict_entities(tmp_path):
    """Common mistake: passing a dict instead of dict.values()."""
    from slappyengine.residency.manager import ResidencyManager
    mgr = ResidencyManager(save_dir=tmp_path)
    with pytest.raises(TypeError, match="entities must be a list or tuple"):
        mgr.update((0.0, 0.0), {"x": object()})


def test_update_accepts_empty_list(tmp_path):
    """Positive sanity: empty list is legitimately a no-op."""
    from slappyengine.residency.manager import ResidencyManager
    mgr = ResidencyManager(save_dir=tmp_path)
    mgr.update((0.0, 0.0), [])  # must not raise


# ---------------------------------------------------------------------------
# evict_to_ram / evict_to_disk / prefetch
# ---------------------------------------------------------------------------

def test_evict_to_ram_rejects_none(tmp_path):
    from slappyengine.residency.manager import ResidencyManager
    mgr = ResidencyManager(save_dir=tmp_path)
    with pytest.raises(TypeError, match="entity must not be None"):
        mgr.evict_to_ram(None)


def test_evict_to_ram_rejects_object_missing_layers(tmp_path):
    from slappyengine.residency.manager import ResidencyManager
    mgr = ResidencyManager(save_dir=tmp_path)

    class HalfEntity:
        id = "z"

    with pytest.raises(TypeError, match="must have a 'layers' attribute"):
        mgr.evict_to_ram(HalfEntity())


def test_evict_to_disk_rejects_none(tmp_path):
    from slappyengine.residency.manager import ResidencyManager
    mgr = ResidencyManager(save_dir=tmp_path)
    with pytest.raises(TypeError, match="entity must not be None"):
        mgr.evict_to_disk(None)


def test_evict_to_disk_rejects_plain_object(tmp_path):
    from slappyengine.residency.manager import ResidencyManager
    mgr = ResidencyManager(save_dir=tmp_path)
    with pytest.raises(TypeError, match="must have an 'id' attribute"):
        mgr.evict_to_disk(object())


def test_prefetch_rejects_none(tmp_path):
    from slappyengine.residency.manager import ResidencyManager
    mgr = ResidencyManager(save_dir=tmp_path)
    with pytest.raises(TypeError, match="entity must not be None"):
        mgr.prefetch(None)


def test_prefetch_rejects_string(tmp_path):
    from slappyengine.residency.manager import ResidencyManager
    mgr = ResidencyManager(save_dir=tmp_path)
    with pytest.raises(TypeError, match="must have an 'id' attribute"):
        mgr.prefetch("entity_id_lol")


def test_evict_to_ram_accepts_valid_asset(tmp_path):
    """Positive sanity: valid input still works through the new validators."""
    from slappyengine.residency.manager import ResidencyManager
    mgr = ResidencyManager(save_dir=tmp_path)
    asset = _make_asset("ok")
    asset.add_layer(_blank_layer(8, 8))
    mgr.evict_to_ram(asset)
    assert mgr.tier(asset) == ResidencyManager.TIER_RAM


# ---------------------------------------------------------------------------
# Round 13 — compression / slap_format / extra manager guards
#
# Silent-acceptance bugs caught here:
#   * compression.compress_array used to crash with a baffling
#     ``AttributeError: 'list' object has no attribute 'astype'`` when a
#     Python list was passed. Now refused at the boundary.
#   * slap_format.write_world_slap silently accepted ``None`` / non-list
#     for ``assets`` and then died with ``TypeError: object of type
#     'NoneType' has no len()``.
#   * slap_format.read_world_slap accepted ``""`` (Path('') -> '.') and
#     died with ``PermissionError`` rather than a clean ValueError.
# ---------------------------------------------------------------------------

import numpy as np


# --- compression.compress_array -------------------------------------------

def test_compress_array_rejects_list():
    """Silent-acceptance bug: list input died deep with AttributeError."""
    from slappyengine.residency.compression import compress_array
    with pytest.raises(TypeError, match="arr must be a numpy.ndarray"):
        compress_array([1.0, 2.0, 3.0])


def test_compress_array_rejects_none():
    from slappyengine.residency.compression import compress_array
    with pytest.raises(TypeError, match="arr must be a numpy.ndarray"):
        compress_array(None)


def test_compress_array_rejects_bytes():
    from slappyengine.residency.compression import compress_array
    with pytest.raises(TypeError, match="arr must be a numpy.ndarray"):
        compress_array(b"\x00\x00\x00\x00")


def test_compress_array_accepts_ndarray():
    """Positive sanity: round-trip via decompress_array."""
    from slappyengine.residency.compression import (
        compress_array, decompress_array,
    )
    arr = np.arange(6, dtype=np.float32).reshape(2, 3)
    blob = compress_array(arr)
    out = decompress_array(blob, (2, 3))
    assert np.array_equal(out, arr)


# --- compression.compress_raw / decompress_raw ----------------------------

def test_compress_raw_rejects_list():
    from slappyengine.residency.compression import compress_raw
    with pytest.raises(TypeError, match="data must be bytes-like"):
        compress_raw([1, 2, 3])


def test_compress_raw_rejects_str():
    """str.encode is the user's job — refuse silent UTF-8 coercion."""
    from slappyengine.residency.compression import compress_raw
    with pytest.raises(TypeError, match="data must be bytes-like"):
        compress_raw("hello")


def test_decompress_raw_rejects_list():
    from slappyengine.residency.compression import decompress_raw
    with pytest.raises(TypeError, match="data must be bytes-like"):
        decompress_raw([0, 1, 2])


def test_decompress_array_rejects_empty_shape():
    from slappyengine.residency.compression import decompress_array
    with pytest.raises(TypeError, match="shape must be a non-empty"):
        decompress_array(b"\x00" * 8, ())


# --- slap_format.write_world_slap -----------------------------------------

def test_write_world_slap_rejects_none_path():
    from slappyengine.residency.slap_format import write_world_slap
    with pytest.raises(TypeError, match="path must be str or pathlib.Path"):
        write_world_slap(None, [])


def test_write_world_slap_rejects_empty_path():
    from slappyengine.residency.slap_format import write_world_slap
    with pytest.raises(ValueError, match="path must not be empty"):
        write_world_slap("", [])


def test_write_world_slap_rejects_int_path():
    from slappyengine.residency.slap_format import write_world_slap
    with pytest.raises(TypeError, match="path must be str or pathlib.Path"):
        write_world_slap(42, [])


def test_write_world_slap_rejects_none_assets(tmp_path):
    """Silent-acceptance bug: None blew up inside ``len(assets)``."""
    from slappyengine.residency.slap_format import write_world_slap
    with pytest.raises(TypeError, match="assets must be a list or tuple"):
        write_world_slap(tmp_path / "x.slap", None)


def test_write_world_slap_rejects_dict_assets(tmp_path):
    from slappyengine.residency.slap_format import write_world_slap
    with pytest.raises(TypeError, match="assets must be a list or tuple"):
        write_world_slap(tmp_path / "x.slap", {"a": object()})


def test_write_world_slap_rejects_str_assets(tmp_path):
    """A str has len() but iterating it would write bogus per-char assets."""
    from slappyengine.residency.slap_format import write_world_slap
    with pytest.raises(TypeError, match="assets must be a list or tuple"):
        write_world_slap(tmp_path / "x.slap", "asset_name_lol")


# --- slap_format.read_world_slap ------------------------------------------

def test_read_world_slap_rejects_empty_path():
    """Silent-acceptance bug: Path('') -> '.' and PermissionError'd."""
    from slappyengine.residency.slap_format import read_world_slap
    with pytest.raises(ValueError, match="path must not be empty"):
        read_world_slap("")


def test_read_world_slap_rejects_none_path():
    from slappyengine.residency.slap_format import read_world_slap
    with pytest.raises(TypeError, match="path must be str or pathlib.Path"):
        read_world_slap(None)


def test_read_world_slap_rejects_bool_path():
    """bool is int subclass — was silently Path(True) = PosixPath('True')."""
    from slappyengine.residency.slap_format import read_world_slap
    with pytest.raises(TypeError, match="path must be str or pathlib.Path"):
        read_world_slap(True)


# --- slap_format.write_asset_to_slap / read_asset_from_slap ---------------

def test_write_asset_to_slap_rejects_none_asset(tmp_path):
    from slappyengine.residency.slap_format import write_asset_to_slap
    with pytest.raises(TypeError, match="asset must not be None"):
        write_asset_to_slap(tmp_path / "x.slap", None)


def test_read_asset_from_slap_rejects_none_path():
    from slappyengine.residency.slap_format import read_asset_from_slap
    with pytest.raises(TypeError, match="path must be str or pathlib.Path"):
        read_asset_from_slap(None)


def test_read_asset_from_slap_rejects_empty_path():
    from slappyengine.residency.slap_format import read_asset_from_slap
    with pytest.raises(ValueError, match="path must not be empty"):
        read_asset_from_slap("")
