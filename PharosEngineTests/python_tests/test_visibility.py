"""Engine tests for VisibilityField + VisibilityObserver.

All tests run headless — no GPU, no window required.
Covers: circle / cone / hull modes, overlap modes, decay_rate,
sample(), get_layer(), add/remove observer, and edge cases.
"""
from __future__ import annotations
import math
import pytest
import numpy as np


class _Entity:
    """Minimal entity stub with position and rotation."""
    def __init__(self, x: float = 0.0, y: float = 0.0, rotation: float = 0.0):
        self.position = (x, y)
        self.rotation = rotation


# ---------------------------------------------------------------------------
# VisibilityObserver dataclass
# ---------------------------------------------------------------------------

class TestVisibilityObserver:
    def test_import(self):
        from pharos_engine.visibility import VisibilityObserver
        assert VisibilityObserver is not None

    def test_defaults(self):
        from pharos_engine.visibility import VisibilityObserver
        ent = _Entity()
        obs = VisibilityObserver(entity=ent)
        assert obs.range == 200.0
        assert obs.mode == "circle"
        assert obs.cone_angle == 360.0
        assert obs.hull_alpha == pytest.approx(0.3)
        assert obs.occluders == []

    def test_custom_range(self):
        from pharos_engine.visibility import VisibilityObserver
        obs = VisibilityObserver(entity=_Entity(), range=150.0)
        assert obs.range == 150.0

    def test_cone_mode(self):
        from pharos_engine.visibility import VisibilityObserver
        obs = VisibilityObserver(entity=_Entity(), mode="cone", cone_angle=90.0)
        assert obs.mode == "cone"
        assert obs.cone_angle == 90.0


# ---------------------------------------------------------------------------
# VisibilityField construction
# ---------------------------------------------------------------------------

class TestVisibilityFieldConstruction:
    def test_import(self):
        from pharos_engine.visibility import VisibilityField
        assert VisibilityField is not None

    def test_default_params(self):
        from pharos_engine.visibility import VisibilityField
        vf = VisibilityField((100, 80))
        assert vf.blend_radius == pytest.approx(20.0)
        assert vf.overlap_mode == "max"
        assert vf.decay_rate == pytest.approx(0.0)

    def test_field_starts_all_hidden(self):
        from pharos_engine.visibility import VisibilityField
        vf = VisibilityField((64, 64))
        assert float(np.max(vf._field)) == pytest.approx(0.0)

    def test_field_shape(self):
        from pharos_engine.visibility import VisibilityField
        vf = VisibilityField((100, 60))
        # _field is (H, W)
        assert vf._field.shape == (60, 100)

    def test_custom_blend_radius(self):
        from pharos_engine.visibility import VisibilityField
        vf = VisibilityField((64, 64), blend_radius=5.0)
        assert vf.blend_radius == pytest.approx(5.0)

    def test_no_observers_initially(self):
        from pharos_engine.visibility import VisibilityField
        vf = VisibilityField((64, 64))
        assert len(vf._observers) == 0


# ---------------------------------------------------------------------------
# add_observer / remove_observer
# ---------------------------------------------------------------------------

class TestObserverManagement:
    def test_add_observer_returns_handle(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((64, 64))
        h = vf.add_observer(VisibilityObserver(entity=_Entity(32, 32)))
        assert isinstance(h, int)
        assert h > 0

    def test_two_observers_different_handles(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((64, 64))
        h1 = vf.add_observer(VisibilityObserver(entity=_Entity(10, 10)))
        h2 = vf.add_observer(VisibilityObserver(entity=_Entity(50, 50)))
        assert h1 != h2

    def test_add_increases_observer_count(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((64, 64))
        vf.add_observer(VisibilityObserver(entity=_Entity()))
        assert len(vf._observers) == 1

    def test_remove_observer_decreases_count(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((64, 64))
        h = vf.add_observer(VisibilityObserver(entity=_Entity()))
        vf.remove_observer(h)
        assert len(vf._observers) == 0

    def test_remove_nonexistent_handle_no_crash(self):
        from pharos_engine.visibility import VisibilityField
        vf = VisibilityField((64, 64))
        vf.remove_observer(9999)  # must not raise


# ---------------------------------------------------------------------------
# Circle mode
# ---------------------------------------------------------------------------

class TestCircleMode:
    def test_circle_reveals_centre(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((128, 128), blend_radius=0)
        obs = VisibilityObserver(entity=_Entity(64, 64), range=30.0, mode="circle")
        vf.add_observer(obs)
        vf.update()
        assert vf.sample((64.0, 64.0)) > 0.5

    def test_circle_hides_far_point(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((256, 256), blend_radius=0)
        # Observer at (128, 128) with range=20 — point at (200, 200) is far
        obs = VisibilityObserver(entity=_Entity(128, 128), range=20.0, mode="circle")
        vf.add_observer(obs)
        vf.update()
        assert vf.sample((200.0, 200.0)) < 0.1

    def test_circle_falloff_monotonic(self):
        """Visibility should decrease as distance from observer increases."""
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((256, 256), blend_radius=0)
        obs = VisibilityObserver(entity=_Entity(128, 128), range=60.0, mode="circle")
        vf.add_observer(obs)
        vf.update()
        close  = vf.sample((130.0, 128.0))   # 2 px away
        medium = vf.sample((148.0, 128.0))   # 20 px away
        far    = vf.sample((185.0, 128.0))   # 57 px away
        assert close >= medium >= far

    def test_update_without_observers_leaves_field_zero(self):
        from pharos_engine.visibility import VisibilityField
        vf = VisibilityField((64, 64))
        vf.update()
        assert float(np.max(vf._field)) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Cone mode
# ---------------------------------------------------------------------------

class TestConeMode:
    def test_cone_reveals_in_front(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((256, 256), blend_radius=0)
        # Observer at (128, 128) facing right (0°), 90° cone
        obs = VisibilityObserver(
            entity=_Entity(128, 128, rotation=0.0),
            range=50.0, mode="cone", cone_angle=90.0,
        )
        vf.add_observer(obs)
        vf.update()
        # Right of observer should be visible
        right_vis = vf.sample((160.0, 128.0))
        assert right_vis > 0.3

    def test_cone_hides_behind(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((256, 256), blend_radius=0)
        # Observer facing right (0°), 60° cone — directly left is 180° off
        obs = VisibilityObserver(
            entity=_Entity(128, 128, rotation=0.0),
            range=50.0, mode="cone", cone_angle=60.0,
        )
        vf.add_observer(obs)
        vf.update()
        # Directly behind: (80, 128) — 48 px left
        behind_vis = vf.sample((80.0, 128.0))
        assert behind_vis < 0.1

    def test_full_cone_behaves_like_circle(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((128, 128), blend_radius=0)
        obs = VisibilityObserver(
            entity=_Entity(64, 64, rotation=0.0),
            range=30.0, mode="cone", cone_angle=360.0,
        )
        vf.add_observer(obs)
        vf.update()
        # Centre and all cardinal directions should be visible
        assert vf.sample((64.0, 64.0)) > 0.5
        assert vf.sample((80.0, 64.0)) > 0.1
        assert vf.sample((48.0, 64.0)) > 0.1


# ---------------------------------------------------------------------------
# Overlap modes
# ---------------------------------------------------------------------------

class TestOverlapModes:
    def _make_two_observer_field(self, overlap_mode: str):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((128, 128), overlap_mode=overlap_mode, blend_radius=0)
        obs1 = VisibilityObserver(entity=_Entity(32, 64), range=30.0, mode="circle")
        obs2 = VisibilityObserver(entity=_Entity(96, 64), range=30.0, mode="circle")
        vf.add_observer(obs1)
        vf.add_observer(obs2)
        vf.update()
        return vf

    def test_max_mode_union_of_observers(self):
        vf = self._make_two_observer_field("max")
        # Each observer's zone should be visible
        assert vf.sample((32.0, 64.0)) > 0.5
        assert vf.sample((96.0, 64.0)) > 0.5

    def test_add_mode_brighter_in_overlap(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        # Two overlapping observers — overlap zone should be 1.0 (clamped)
        vf = VisibilityField((128, 128), overlap_mode="add", blend_radius=0)
        obs1 = VisibilityObserver(entity=_Entity(64, 64), range=30.0)
        obs2 = VisibilityObserver(entity=_Entity(64, 64), range=30.0)
        vf.add_observer(obs1)
        vf.add_observer(obs2)
        vf.update()
        # Centre: both observers contribute; clamped to 1.0
        assert vf.sample((64.0, 64.0)) == pytest.approx(1.0, abs=0.01)

    def test_intersect_mode_only_both_see_it(self):
        """Intersect: only pixels seen by ALL observers are revealed."""
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((128, 128), overlap_mode="intersect", blend_radius=0)
        # Two non-overlapping observers
        obs1 = VisibilityObserver(entity=_Entity(20, 64), range=15.0)
        obs2 = VisibilityObserver(entity=_Entity(108, 64), range=15.0)
        vf.add_observer(obs1)
        vf.add_observer(obs2)
        vf.update()
        # Middle (64, 64) is not in either observer's range → should be invisible
        assert vf.sample((64.0, 64.0)) < 0.1


# ---------------------------------------------------------------------------
# Decay rate
# ---------------------------------------------------------------------------

class TestDecayRate:
    def test_no_decay_field_persists(self):
        """decay_rate=0: once revealed, pixels stay revealed even when observer gone."""
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((64, 64), decay_rate=0.0, blend_radius=0)
        h = vf.add_observer(VisibilityObserver(entity=_Entity(32, 32), range=15.0))
        vf.update()
        revealed = vf.sample((32.0, 32.0))
        assert revealed > 0.5
        # Remove observer — field should still show revealed
        vf.remove_observer(h)
        vf.update()
        still_revealed = vf.sample((32.0, 32.0))
        assert still_revealed == pytest.approx(revealed, rel=0.01)

    def test_high_decay_fades_fast(self):
        """decay_rate=0.5: revealed area halves each frame when unobserved."""
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((64, 64), decay_rate=0.5, blend_radius=0)
        h = vf.add_observer(VisibilityObserver(entity=_Entity(32, 32), range=15.0))
        vf.update()
        initial = vf.sample((32.0, 32.0))
        vf.remove_observer(h)
        for _ in range(8):
            vf.update()
        faded = vf.sample((32.0, 32.0))
        assert faded < initial * 0.05  # decayed to <5% of original


# ---------------------------------------------------------------------------
# sample()
# ---------------------------------------------------------------------------

class TestSample:
    def test_sample_hidden_returns_zero(self):
        from pharos_engine.visibility import VisibilityField
        vf = VisibilityField((64, 64))
        assert vf.sample((10.0, 10.0)) == pytest.approx(0.0)

    def test_sample_wrap_around(self):
        """sample() should wrap world_pos within field bounds (modulo)."""
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((64, 64), blend_radius=0)
        # Observer in top-left corner
        vf.add_observer(VisibilityObserver(entity=_Entity(2, 2), range=10.0))
        vf.update()
        # Querying at (2, 2) and (66, 66) should give same result (modulo 64)
        v1 = vf.sample((2.0, 2.0))
        v2 = vf.sample((66.0, 66.0))
        assert v1 == pytest.approx(v2, abs=1e-4)

    def test_sample_range_0_to_1(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((64, 64), blend_radius=0)
        vf.add_observer(VisibilityObserver(entity=_Entity(32, 32), range=20.0))
        vf.update()
        # Sample many points — all must be in [0, 1]
        for x in range(0, 64, 8):
            for y in range(0, 64, 8):
                v = vf.sample((float(x), float(y)))
                assert 0.0 <= v <= 1.0


# ---------------------------------------------------------------------------
# get_layer()
# ---------------------------------------------------------------------------

class TestGetLayer:
    def test_get_layer_returns_layer2d(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        from pharos_engine.layer import Layer2D
        vf = VisibilityField((64, 64))
        vf.add_observer(VisibilityObserver(entity=_Entity(32, 32), range=20.0))
        vf.update()
        layer = vf.get_layer()
        assert isinstance(layer, Layer2D)

    def test_get_layer_size(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((80, 60))
        vf.add_observer(VisibilityObserver(entity=_Entity(40, 30), range=20.0))
        vf.update()
        layer = vf.get_layer()
        if layer is not None:
            assert layer._image_data.shape[:2] == (60, 80)

    def test_get_layer_cached(self):
        """Second call without update() returns same object."""
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((32, 32))
        vf.add_observer(VisibilityObserver(entity=_Entity(16, 16), range=10.0))
        vf.update()
        l1 = vf.get_layer()
        l2 = vf.get_layer()
        assert l1 is l2

    def test_get_layer_invalidated_on_update(self):
        """Cache is invalidated after update()."""
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((32, 32))
        obs = VisibilityObserver(entity=_Entity(16, 16), range=10.0)
        vf.add_observer(obs)
        vf.update()
        l1 = vf.get_layer()
        vf.update()
        l2 = vf.get_layer()
        assert l1 is not l2  # new layer object after cache invalidation

    def test_get_layer_empty_field_returns_layer(self):
        from pharos_engine.visibility import VisibilityField
        from pharos_engine.layer import Layer2D
        vf = VisibilityField((32, 32))
        vf.update()
        layer = vf.get_layer()
        assert isinstance(layer, Layer2D)


# ---------------------------------------------------------------------------
# Multiple observers + update called repeatedly
# ---------------------------------------------------------------------------

class TestMultipleObserversAndRepeatedUpdates:
    def test_multiple_updates_stable(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((64, 64), blend_radius=0)
        vf.add_observer(VisibilityObserver(entity=_Entity(32, 32), range=20.0))
        for _ in range(20):
            vf.update()
        # Field should remain in [0, 1]
        assert float(np.min(vf._field)) >= 0.0
        assert float(np.max(vf._field)) <= 1.0

    def test_moving_observer_tracks_entity(self):
        """With decay_rate=1 (instant fade), visibility follows the entity position."""
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        # decay_rate=1.0 → field = current accumulated only (no persistence)
        vf = VisibilityField((128, 128), blend_radius=0, decay_rate=1.0)
        ent = _Entity(20, 64)
        vf.add_observer(VisibilityObserver(entity=ent, range=20.0))
        vf.update()
        left_vis = vf.sample((20.0, 64.0))
        assert left_vis > 0.5

        # Move entity to the right
        ent.position = (100, 64)
        vf.update()
        right_vis = vf.sample((100.0, 64.0))
        left_after_move = vf.sample((20.0, 64.0))

        assert right_vis > 0.5
        assert left_after_move < 0.1  # decay_rate=1 → previous area instantly dark

    def test_three_observers_max_mode_union(self):
        from pharos_engine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField((128, 128), overlap_mode="max", blend_radius=0)
        positions = [(20, 64), (64, 20), (64, 108)]
        for x, y in positions:
            vf.add_observer(VisibilityObserver(entity=_Entity(x, y), range=18.0))
        vf.update()
        for x, y in positions:
            assert vf.sample((float(x), float(y))) > 0.5
