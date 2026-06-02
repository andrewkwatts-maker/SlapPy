"""Headless tests for slappyengine.visibility (VisibilityObserver, VisibilityField).

No GPU required — all tests use numpy for the field and dummy entities.
"""
from __future__ import annotations
import numpy as np


# ---------------------------------------------------------------------------
# VisibilityObserver dataclass
# ---------------------------------------------------------------------------

class TestVisibilityObserver:
    def _entity(self, pos=(0.0, 0.0)):
        class E:
            position = pos
        return E()

    def test_instantiates(self):
        from slappyengine.visibility import VisibilityObserver
        obs = VisibilityObserver(entity=self._entity())
        assert obs is not None

    def test_default_range(self):
        from slappyengine.visibility import VisibilityObserver
        obs = VisibilityObserver(entity=self._entity())
        assert obs.range == 200.0

    def test_custom_range(self):
        from slappyengine.visibility import VisibilityObserver
        obs = VisibilityObserver(entity=self._entity(), range=500.0)
        assert obs.range == 500.0

    def test_default_mode_circle(self):
        from slappyengine.visibility import VisibilityObserver
        obs = VisibilityObserver(entity=self._entity())
        assert obs.mode == "circle"

    def test_default_cone_angle_360(self):
        from slappyengine.visibility import VisibilityObserver
        obs = VisibilityObserver(entity=self._entity())
        assert obs.cone_angle == 360.0

    def test_default_hull_alpha(self):
        from slappyengine.visibility import VisibilityObserver
        obs = VisibilityObserver(entity=self._entity())
        assert abs(obs.hull_alpha - 0.3) < 1e-9

    def test_default_occluders_empty(self):
        from slappyengine.visibility import VisibilityObserver
        obs = VisibilityObserver(entity=self._entity())
        assert obs.occluders == []

    def test_entity_stored(self):
        from slappyengine.visibility import VisibilityObserver
        e = self._entity()
        obs = VisibilityObserver(entity=e)
        assert obs.entity is e


# ---------------------------------------------------------------------------
# VisibilityField — __init__ and pure-Python API
# ---------------------------------------------------------------------------

class TestVisibilityFieldInit:
    def test_instantiates(self):
        from slappyengine.visibility import VisibilityField
        vf = VisibilityField(size=(64, 64))
        assert vf is not None

    def test_field_shape(self):
        from slappyengine.visibility import VisibilityField
        vf = VisibilityField(size=(32, 16))
        assert vf._field.shape == (16, 32)

    def test_field_zeros_initially(self):
        from slappyengine.visibility import VisibilityField
        vf = VisibilityField(size=(8, 8))
        assert np.all(vf._field == 0.0)

    def test_default_blend_radius(self):
        from slappyengine.visibility import VisibilityField
        vf = VisibilityField(size=(64, 64))
        assert vf.blend_radius == 20.0

    def test_custom_blend_radius(self):
        from slappyengine.visibility import VisibilityField
        vf = VisibilityField(size=(64, 64), blend_radius=5.0)
        assert vf.blend_radius == 5.0

    def test_default_overlap_mode_max(self):
        from slappyengine.visibility import VisibilityField
        vf = VisibilityField(size=(64, 64))
        assert vf.overlap_mode == "max"

    def test_custom_overlap_mode(self):
        from slappyengine.visibility import VisibilityField
        vf = VisibilityField(size=(64, 64), overlap_mode="add")
        assert vf.overlap_mode == "add"

    def test_default_decay_rate_zero(self):
        from slappyengine.visibility import VisibilityField
        vf = VisibilityField(size=(64, 64))
        assert vf.decay_rate == 0.0

    def test_observers_empty_initially(self):
        from slappyengine.visibility import VisibilityField
        vf = VisibilityField(size=(64, 64))
        assert vf._observers == {}

    def test_obs_counter_starts_zero(self):
        from slappyengine.visibility import VisibilityField
        vf = VisibilityField(size=(64, 64))
        assert vf._obs_counter == 0


class TestVisibilityFieldObservers:
    def _entity(self, pos=(32.0, 32.0)):
        class E:
            position = pos
        return E()

    def test_add_observer_returns_handle(self):
        from slappyengine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField(size=(64, 64))
        obs = VisibilityObserver(entity=self._entity(), range=20.0)
        handle = vf.add_observer(obs)
        assert isinstance(handle, int)
        assert handle > 0

    def test_add_observer_stores_observer(self):
        from slappyengine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField(size=(64, 64))
        obs = VisibilityObserver(entity=self._entity(), range=20.0)
        handle = vf.add_observer(obs)
        assert handle in vf._observers

    def test_handles_increment(self):
        from slappyengine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField(size=(64, 64))
        h1 = vf.add_observer(VisibilityObserver(entity=self._entity()))
        h2 = vf.add_observer(VisibilityObserver(entity=self._entity()))
        assert h2 > h1

    def test_remove_observer(self):
        from slappyengine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField(size=(64, 64))
        handle = vf.add_observer(VisibilityObserver(entity=self._entity()))
        vf.remove_observer(handle)
        assert handle not in vf._observers

    def test_remove_nonexistent_no_crash(self):
        from slappyengine.visibility import VisibilityField
        vf = VisibilityField(size=(64, 64))
        vf.remove_observer(999)  # should not raise


class TestVisibilityFieldSample:
    def test_sample_returns_float(self):
        from slappyengine.visibility import VisibilityField
        vf = VisibilityField(size=(64, 64))
        result = vf.sample((10.0, 10.0))
        assert isinstance(result, float)

    def test_sample_zero_before_update(self):
        from slappyengine.visibility import VisibilityField
        vf = VisibilityField(size=(64, 64))
        assert vf.sample((10.0, 10.0)) == 0.0

    def test_sample_in_range_zero_to_one(self):
        from slappyengine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField(size=(128, 128))

        class E:
            position = (64.0, 64.0)

        obs = VisibilityObserver(entity=E(), range=30.0, mode="circle")
        vf.add_observer(obs)
        vf.update()
        val = vf.sample((64.0, 64.0))
        assert 0.0 <= val <= 1.0


class TestVisibilityFieldUpdate:
    def test_update_no_crash_empty(self):
        from slappyengine.visibility import VisibilityField
        vf = VisibilityField(size=(64, 64))
        vf.update()  # should not raise

    def test_update_with_observer_modifies_field(self):
        from slappyengine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField(size=(64, 64))

        class E:
            position = (32.0, 32.0)

        obs = VisibilityObserver(entity=E(), range=10.0, mode="circle")
        vf.add_observer(obs)
        vf.update()
        assert np.any(vf._field > 0.0)

    def test_update_max_mode_union(self):
        from slappyengine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField(size=(128, 128), overlap_mode="max")

        class E1:
            position = (20.0, 64.0)

        class E2:
            position = (100.0, 64.0)

        obs1 = VisibilityObserver(entity=E1(), range=15.0)
        obs2 = VisibilityObserver(entity=E2(), range=15.0)
        vf.add_observer(obs1)
        vf.add_observer(obs2)
        vf.update()
        # Both areas should have nonzero visibility
        val1 = vf.sample((20.0, 64.0))
        val2 = vf.sample((100.0, 64.0))
        assert val1 > 0.0
        assert val2 > 0.0

    def test_update_decay_rate_reduces_old_visibility(self):
        from slappyengine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField(size=(64, 64), decay_rate=0.5)

        class E:
            position = (32.0, 32.0)

        obs = VisibilityObserver(entity=E(), range=10.0)
        handle = vf.add_observer(obs)
        vf.update()
        val_after_reveal = vf.sample((32.0, 32.0))

        # Remove observer, update again — field should fade
        vf.remove_observer(handle)
        vf.update()
        val_after_decay = vf.sample((32.0, 32.0))
        assert val_after_decay < val_after_reveal
