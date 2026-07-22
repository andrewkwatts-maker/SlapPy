"""Headless tests for pharos_engine.visibility — VisibilityField and VisibilityObserver.

All methods are pure-Python / numpy; no GPU required.
"""
from __future__ import annotations
import sys
import math
from unittest.mock import MagicMock

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("pharos_engine.compute.asset_compute", MagicMock())

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _field(w=200, h=200, blend_radius=0.0, overlap_mode="max", decay_rate=0.0):
    from pharos_engine.visibility import VisibilityField
    return VisibilityField((w, h), blend_radius=blend_radius,
                           overlap_mode=overlap_mode, decay_rate=decay_rate)


def _obs(entity, range_=80.0, mode="circle", cone_angle=360.0):
    from pharos_engine.visibility import VisibilityObserver
    return VisibilityObserver(entity=entity, range=range_,
                              mode=mode, cone_angle=cone_angle)


class _Ent:
    def __init__(self, x=100.0, y=100.0, rotation=0.0):
        self.position = (x, y)
        self.rotation = rotation


# =============================================================================
# VisibilityField construction
# =============================================================================

class TestVisibilityFieldInit:
    def test_instantiates(self):
        assert _field() is not None

    def test_field_shape(self):
        vf = _field(w=80, h=60)
        assert vf._field.shape == (60, 80)

    def test_field_starts_at_zero(self):
        vf = _field()
        assert vf._field.max() == 0.0

    def test_no_observers_initially(self):
        vf = _field()
        assert len(vf._observers) == 0

    def test_blend_radius_stored(self):
        vf = _field(blend_radius=15.0)
        assert vf.blend_radius == 15.0

    def test_overlap_mode_stored(self):
        vf = _field(overlap_mode="add")
        assert vf.overlap_mode == "add"

    def test_decay_rate_stored(self):
        vf = _field(decay_rate=0.3)
        assert vf.decay_rate == 0.3


# =============================================================================
# add_observer / remove_observer
# =============================================================================

class TestObserverManagement:
    def test_add_returns_int_handle(self):
        vf = _field()
        obs = _obs(_Ent())
        handle = vf.add_observer(obs)
        assert isinstance(handle, int)

    def test_add_two_returns_different_handles(self):
        vf = _field()
        h1 = vf.add_observer(_obs(_Ent(10, 10)))
        h2 = vf.add_observer(_obs(_Ent(50, 50)))
        assert h1 != h2

    def test_add_increases_observer_count(self):
        vf = _field()
        vf.add_observer(_obs(_Ent()))
        assert len(vf._observers) == 1

    def test_remove_decreases_count(self):
        vf = _field()
        h = vf.add_observer(_obs(_Ent()))
        vf.remove_observer(h)
        assert len(vf._observers) == 0

    def test_remove_unknown_handle_no_crash(self):
        vf = _field()
        vf.remove_observer(9999)  # should not raise

    def test_remove_only_target(self):
        vf = _field()
        h1 = vf.add_observer(_obs(_Ent(10, 10)))
        h2 = vf.add_observer(_obs(_Ent(50, 50)))
        vf.remove_observer(h1)
        assert h2 in vf._observers
        assert h1 not in vf._observers


# =============================================================================
# sample — boundary and basic access
# =============================================================================

class TestSample:
    def test_empty_field_zero(self):
        vf = _field()
        assert vf.sample((50.0, 50.0)) == 0.0

    def test_returns_float(self):
        vf = _field()
        assert isinstance(vf.sample((10.0, 10.0)), float)

    def test_wraps_around_width(self):
        vf = _field(w=100, h=100)
        vf._field[5, 5] = 1.0
        # x=205 → 205 % 100 = 5
        assert vf.sample((205.0, 5.0)) == pytest.approx(1.0)

    def test_written_pixel_readable(self):
        vf = _field(w=50, h=50)
        vf._field[20, 30] = 0.75
        assert vf.sample((30.0, 20.0)) == pytest.approx(0.75)


# =============================================================================
# update — circle mode
# =============================================================================

class TestUpdateCircle:
    def test_no_observers_stays_zero(self):
        vf = _field(w=100, h=100)
        vf.update()
        assert vf._field.max() == 0.0

    def test_circle_observer_illuminates_centre(self):
        vf = _field(w=200, h=200, blend_radius=0.0)
        ent = _Ent(x=100.0, y=100.0)
        vf.add_observer(_obs(ent, range_=40.0, mode="circle"))
        vf.update()
        assert vf.sample((100.0, 100.0)) > 0.5

    def test_circle_doesnt_illuminate_far_away(self):
        vf = _field(w=200, h=200, blend_radius=0.0)
        ent = _Ent(x=20.0, y=20.0)
        vf.add_observer(_obs(ent, range_=10.0, mode="circle"))
        vf.update()
        assert vf.sample((180.0, 180.0)) == pytest.approx(0.0)

    def test_circle_range_boundary(self):
        vf = _field(w=200, h=200, blend_radius=0.0)
        ent = _Ent(x=100.0, y=100.0)
        vf.add_observer(_obs(ent, range_=30.0, mode="circle"))
        vf.update()
        # Point at exactly range should be 0 or near 0
        assert vf.sample((100.0 + 31.0, 100.0)) < 0.1

    def test_two_observers_max_mode(self):
        vf = _field(w=200, h=200, overlap_mode="max", blend_radius=0.0)
        vf.add_observer(_obs(_Ent(50, 100), range_=30.0))
        vf.add_observer(_obs(_Ent(150, 100), range_=30.0))
        vf.update()
        # Both centres visible
        assert vf.sample((50.0, 100.0)) > 0.5
        assert vf.sample((150.0, 100.0)) > 0.5

    def test_add_overlap_mode_clips_to_one(self):
        vf = _field(w=200, h=200, overlap_mode="add", blend_radius=0.0)
        vf.add_observer(_obs(_Ent(100, 100), range_=50.0))
        vf.add_observer(_obs(_Ent(100, 100), range_=50.0))
        vf.update()
        # centre should be capped at 1.0
        assert vf.sample((100.0, 100.0)) <= 1.0

    def test_intersect_both_invisible(self):
        vf = _field(w=200, h=200, overlap_mode="intersect", blend_radius=0.0)
        # Two non-overlapping observers — intersect → everything 0
        vf.add_observer(_obs(_Ent(10, 10), range_=20.0))
        vf.add_observer(_obs(_Ent(190, 190), range_=20.0))
        vf.update()
        # centre unseen by both → 0
        assert vf.sample((100.0, 100.0)) == pytest.approx(0.0)


# =============================================================================
# update — cone mode
# =============================================================================

class TestUpdateCone:
    def test_cone_illuminates_forward(self):
        vf = _field(w=200, h=200, blend_radius=0.0)
        # Entity at (100,100) facing east (rotation=0), 90° cone
        ent = _Ent(x=100.0, y=100.0, rotation=0.0)
        obs = _obs(ent, range_=60.0, mode="cone", cone_angle=90.0)
        vf.add_observer(obs)
        vf.update()
        # east should be visible
        assert vf.sample((140.0, 100.0)) > 0.0

    def test_cone_doesnt_illuminate_behind(self):
        vf = _field(w=200, h=200, blend_radius=0.0)
        ent = _Ent(x=100.0, y=100.0, rotation=0.0)  # facing east
        obs = _obs(ent, range_=50.0, mode="cone", cone_angle=60.0)
        vf.add_observer(obs)
        vf.update()
        # west should be in shadow
        assert vf.sample((50.0, 100.0)) == pytest.approx(0.0)


# =============================================================================
# decay_rate — field fades when no observer
# =============================================================================

class TestDecay:
    def test_no_decay_reveals_permanently(self):
        vf = _field(w=100, h=100, decay_rate=0.0, blend_radius=0.0)
        ent = _Ent(50, 50)
        h = vf.add_observer(_obs(ent, range_=20.0))
        vf.update()  # reveal
        vf.remove_observer(h)
        vf.update()  # no observers — should stay revealed
        assert vf.sample((50.0, 50.0)) > 0.0

    def test_decay_reduces_over_time(self):
        vf = _field(w=100, h=100, decay_rate=0.5, blend_radius=0.0)
        ent = _Ent(50, 50)
        h = vf.add_observer(_obs(ent, range_=20.0))
        vf.update()  # reveal
        val_after_reveal = vf.sample((50.0, 50.0))
        vf.remove_observer(h)
        vf.update()  # decay step
        val_after_decay = vf.sample((50.0, 50.0))
        assert val_after_decay < val_after_reveal


# =============================================================================
# _draw_circle_mask — direct unit test
# =============================================================================

class TestDrawCircleMask:
    def test_centre_pixel_high(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((100, 100), blend_radius=0.0)
        mask = np.zeros((100, 100), dtype=np.float32)
        ent = _Ent(50, 50)
        obs = VisibilityObserver(entity=ent, range=20.0)
        vf._draw_circle_mask(mask, 50.0, 50.0, 20.0, obs)
        assert mask[50, 50] > 0.8

    def test_outside_range_zero(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((100, 100), blend_radius=0.0)
        mask = np.zeros((100, 100), dtype=np.float32)
        ent = _Ent(10, 10)
        obs = VisibilityObserver(entity=ent, range=5.0)
        vf._draw_circle_mask(mask, 10.0, 10.0, 5.0, obs)
        assert mask[90, 90] == 0.0

    def test_falloff_decreases_with_distance(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((200, 200), blend_radius=0.0)
        mask = np.zeros((200, 200), dtype=np.float32)
        ent = _Ent(100, 100)
        obs = VisibilityObserver(entity=ent, range=50.0)
        vf._draw_circle_mask(mask, 100.0, 100.0, 50.0, obs)
        assert mask[100, 100] > mask[100, 120]  # centre > offset


# =============================================================================
# _draw_cone_mask — direct unit test
# =============================================================================

class TestDrawConeMask:
    def test_cone_hit_forward(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((200, 200), blend_radius=0.0)
        mask = np.zeros((200, 200), dtype=np.float32)
        ent = _Ent(100, 100, rotation=0.0)  # facing east (0 rad)
        obs = VisibilityObserver(entity=ent, range=50.0, mode="cone", cone_angle=90.0)
        vf._draw_cone_mask(mask, 100.0, 100.0, 50.0, 0.0, 90.0, obs)
        assert mask[100, 130] > 0.0  # east

    def test_cone_miss_behind(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((200, 200), blend_radius=0.0)
        mask = np.zeros((200, 200), dtype=np.float32)
        ent = _Ent(100, 100, rotation=0.0)  # facing east
        obs = VisibilityObserver(entity=ent, range=40.0, mode="cone", cone_angle=60.0)
        vf._draw_cone_mask(mask, 100.0, 100.0, 40.0, 0.0, 60.0, obs)
        assert mask[100, 60] == 0.0   # west — behind


# =============================================================================
# _feather — soft edge
# =============================================================================

class TestFeather:
    def test_feather_returns_same_shape(self):
        from pharos_engine.visibility import VisibilityField
        vf = VisibilityField((100, 100), blend_radius=10.0)
        mask = np.ones((100, 100), dtype=np.float32)
        result = vf._feather(mask, 50.0, 50.0, 30.0)
        assert result.shape == mask.shape

    def test_feather_zero_blend_returns_unchanged(self):
        from pharos_engine.visibility import VisibilityField
        vf = VisibilityField((100, 100), blend_radius=0.0)
        mask = np.ones((100, 100), dtype=np.float32)
        result = vf._feather(mask, 50.0, 50.0, 30.0)
        # blend_radius=0 returns mask unchanged
        assert result is mask

    def test_feather_reduces_edge_values(self):
        from pharos_engine.visibility import VisibilityField
        vf = VisibilityField((200, 200), blend_radius=20.0)
        mask = np.ones((200, 200), dtype=np.float32)
        result = vf._feather(mask, 100.0, 100.0, 50.0)
        # At the boundary (~radius away), should be < centre value
        assert result[100, 145] < result[100, 100]


# =============================================================================
# _sample_los_points — returns correct number of points
# =============================================================================

class TestSampleLosPoints:
    def test_returns_num_rays_points(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((200, 200), blend_radius=0.0)
        ent = _Ent(100, 100)
        obs = VisibilityObserver(entity=ent, range=50.0, mode="circle")
        pts = vf._sample_los_points(obs, 100.0, 100.0, 50.0, num_rays=16)
        assert len(pts) == 16

    def test_points_are_2d_coords(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((200, 200), blend_radius=0.0)
        ent = _Ent(100, 100)
        obs = VisibilityObserver(entity=ent, range=50.0, mode="circle")
        pts = vf._sample_los_points(obs, 100.0, 100.0, 50.0, num_rays=8)
        for p in pts:
            assert len(p) == 2

    def test_points_approx_at_range_distance(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((400, 400), blend_radius=0.0)
        ent = _Ent(200, 200)
        obs = VisibilityObserver(entity=ent, range=60.0, mode="circle")
        pts = vf._sample_los_points(obs, 200.0, 200.0, 60.0, num_rays=8)
        for p in pts:
            dist = math.hypot(p[0] - 200.0, p[1] - 200.0)
            assert abs(dist - 60.0) < 1.0


# =============================================================================
# _rasterise_hull — fills polygon into mask
# =============================================================================

class TestRasteriseHull:
    def test_fills_triangle(self):
        from pharos_engine.visibility import VisibilityField
        vf = VisibilityField((100, 100), blend_radius=0.0)
        mask = np.zeros((100, 100), dtype=np.float32)
        hull = np.array([[30, 30], [70, 30], [50, 70]], dtype=np.float32)
        vf._rasterise_hull(mask, hull, 50.0, 50.0, obs_range=50.0)
        # centroid of triangle should be non-zero
        assert mask[50, 50] > 0.0

    def test_less_than_3_points_no_fill(self):
        from pharos_engine.visibility import VisibilityField
        vf = VisibilityField((100, 100), blend_radius=0.0)
        mask = np.zeros((100, 100), dtype=np.float32)
        hull = np.array([[10, 10], [20, 20]], dtype=np.float32)
        vf._rasterise_hull(mask, hull, 15.0, 15.0)
        assert mask.max() == 0.0


# =============================================================================
# get_layer — Layer2D output
# =============================================================================

class TestGetLayer:
    def test_empty_field_returns_layer_or_none(self):
        vf = _field(w=50, h=50)
        result = vf.get_layer()
        # May return None if Layer2D unavailable, or a Layer2D
        assert result is None or hasattr(result, "_image_data")

    def test_cache_returns_same_object(self):
        vf = _field(w=50, h=50)
        r1 = vf.get_layer()
        r2 = vf.get_layer()
        if r1 is not None:
            assert r1 is r2

    def test_update_invalidates_cache(self):
        vf = _field(w=50, h=50)
        vf.get_layer()  # populate cache
        vf.update()     # should clear cache
        assert vf._layer_cache is None

    def test_visible_pixel_has_nonzero_alpha(self):
        vf = _field(w=100, h=100, blend_radius=0.0)
        ent = _Ent(50, 50)
        vf.add_observer(_obs(ent, range_=20.0))
        vf.update()
        layer = vf.get_layer()
        if layer is not None and layer._image_data is not None:
            assert layer._image_data[50, 50, 3] > 0
