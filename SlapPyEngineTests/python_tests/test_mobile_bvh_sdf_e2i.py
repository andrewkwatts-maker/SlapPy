"""Sprint E2 — work package E2-I: mobile-skip flags for BVH + SDF.

Verifies that flipping :data:`slappyengine.config.MOBILE_DISABLE_BVH` /
:data:`MOBILE_DISABLE_SDF` causes the corresponding construction paths to
short-circuit to ``None`` (BVH builder, SDF scene factory, SdfExtruder)
or no-op (``Engine.enable_sdf``).

No GPU paths are exercised — the flags must take effect on the pure-Python
gate ahead of any wgpu calls.
"""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine import config as cfg
from slappyengine.bvh_factory import build_bvh, make_sdf_scene
from slappyengine.gpu.sdf_extruder import SdfExtruder


# ---------------------------------------------------------------------------
# Fixture — always restore the flags so other tests aren't poisoned
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _restore_mobile_flags():
    """Snapshot and restore both mobile flags around every test."""
    saved_bvh = cfg.MOBILE_DISABLE_BVH
    saved_sdf = cfg.MOBILE_DISABLE_SDF
    try:
        yield
    finally:
        cfg.MOBILE_DISABLE_BVH = saved_bvh
        cfg.MOBILE_DISABLE_SDF = saved_sdf


# ---------------------------------------------------------------------------
# Defaults — flags are off out of the box
# ---------------------------------------------------------------------------

def test_default_flags_are_false():
    """MOBILE_DISABLE_BVH / _SDF default to False so desktop builds aren't
    affected by the gate."""
    assert cfg.MOBILE_DISABLE_BVH is False
    assert cfg.MOBILE_DISABLE_SDF is False


# ---------------------------------------------------------------------------
# BVH gate
# ---------------------------------------------------------------------------

def test_build_bvh_returns_object_when_flag_off():
    """With the flag off, build_bvh returns a non-None structure."""
    cfg.MOBILE_DISABLE_BVH = False
    result = build_bvh([{"min": [0, 0, 0], "max": [1, 1, 1]}])
    assert result is not None


def test_build_bvh_returns_none_when_flag_on():
    """Flipping MOBILE_DISABLE_BVH short-circuits the builder to None."""
    cfg.MOBILE_DISABLE_BVH = True
    assert build_bvh([{"min": [0, 0, 0], "max": [1, 1, 1]}]) is None


def test_build_bvh_empty_list_still_gated():
    """The gate runs before the input is materialised — empty input is fine."""
    cfg.MOBILE_DISABLE_BVH = True
    assert build_bvh([]) is None


# ---------------------------------------------------------------------------
# SDF scene factory gate
# ---------------------------------------------------------------------------

def test_make_sdf_scene_returns_none_when_flag_on():
    """make_sdf_scene short-circuits to None on the mobile profile."""
    cfg.MOBILE_DISABLE_SDF = True
    assert make_sdf_scene() is None


# ---------------------------------------------------------------------------
# SdfExtruder gate
# ---------------------------------------------------------------------------

def test_sdf_extruder_returns_none_when_flag_on():
    """SdfExtruder.extrude returns None on the mobile profile."""
    cfg.MOBILE_DISABLE_SDF = True
    ext = SdfExtruder()
    mask = np.ones((4, 4), dtype=np.uint8) * 255
    assert ext.extrude(mask) is None


def test_sdf_extruder_returns_mesh_when_flag_off():
    """Flag off → extrude produces a real GpuMesh (CPU fallback path)."""
    cfg.MOBILE_DISABLE_SDF = False
    ext = SdfExtruder()
    mask = np.ones((2, 2), dtype=np.uint8) * 255
    mesh = ext.extrude(mask)
    assert mesh is not None
    # CPU fallback emits 6 quads × 4 verts per solid cell.
    assert len(mesh.vertices) > 0


def test_sdf_extruder_from_layer_returns_none_when_flag_on():
    """SdfExtruder.from_layer also short-circuits on the mobile profile."""
    cfg.MOBILE_DISABLE_SDF = True

    class _Layer:
        _image_data = np.ones((4, 4, 4), dtype=np.uint8) * 255

    assert SdfExtruder.from_layer(_Layer()) is None


# ---------------------------------------------------------------------------
# Engine.enable_sdf gate
# ---------------------------------------------------------------------------

def test_engine_enable_sdf_is_noop_when_flag_on():
    """Engine.enable_sdf leaves the renderer as None on the mobile profile."""
    cfg.MOBILE_DISABLE_SDF = True

    # Build a stub Engine *without* triggering __init__ side effects (no
    # window, no wgpu device).  We only need _sdf_renderer + _gpu + _cfg.
    from slappyengine.engine import Engine

    eng = object.__new__(Engine)
    eng._sdf_renderer = None
    eng._gpu = None
    eng._cfg = cfg.engine_config()
    Engine.enable_sdf(eng)

    assert eng._sdf_renderer is None
    assert eng.sdf is None
