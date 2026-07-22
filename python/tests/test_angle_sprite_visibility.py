"""Engine tests for angle_sprite.py and visibility.py.
All headless — no GPU required.
"""
from __future__ import annotations
import math
import pytest
import numpy as np


# ---------------------------------------------------------------------------
# angle_sprite.py — AngleEntry, AngleSpriteMap
# ---------------------------------------------------------------------------

class TestAngleEntry:
    def test_instantiates(self):
        from slappyengine.angle_sprite import AngleEntry
        e = AngleEntry(angle_deg=0.0, layer_index=0)
        assert e is not None

    def test_defaults(self):
        from slappyengine.angle_sprite import AngleEntry
        e = AngleEntry(angle_deg=90.0, layer_index=2)
        assert e.state_tag == ""

    def test_custom_state_tag(self):
        from slappyengine.angle_sprite import AngleEntry
        e = AngleEntry(angle_deg=45.0, layer_index=1, state_tag="damaged")
        assert e.state_tag == "damaged"


class TestAngleSpriteMapBasics:
    def test_instantiates(self):
        from slappyengine.angle_sprite import AngleSpriteMap
        m = AngleSpriteMap()
        assert m is not None

    def test_defaults(self):
        from slappyengine.angle_sprite import AngleSpriteMap
        m = AngleSpriteMap()
        assert m.blend_mode == "lerp"
        assert m.entries == []

    def test_add_entry(self):
        from slappyengine.angle_sprite import AngleSpriteMap, AngleEntry
        m = AngleSpriteMap()
        m.add_entry(AngleEntry(angle_deg=0.0, layer_index=0))
        assert len(m.entries) == 1

    def test_add_multiple_entries(self):
        from slappyengine.angle_sprite import AngleSpriteMap, AngleEntry
        m = AngleSpriteMap()
        for angle in [0, 90, 180, 270]:
            m.add_entry(AngleEntry(angle_deg=float(angle), layer_index=angle // 90))
        assert len(m.entries) == 4

    def test_clone_state(self):
        from slappyengine.angle_sprite import AngleSpriteMap, AngleEntry
        m = AngleSpriteMap()
        m.add_entry(AngleEntry(angle_deg=0.0, layer_index=0, state_tag=""))
        m.add_entry(AngleEntry(angle_deg=90.0, layer_index=1, state_tag=""))
        m.clone_state("", "damaged", layer_offset=10)
        damaged = [e for e in m.entries if e.state_tag == "damaged"]
        assert len(damaged) == 2
        assert damaged[0].layer_index == 10
        assert damaged[1].layer_index == 11


class TestAngleSpriteMapResolveSnap:
    def _make_4dir_snap(self):
        from slappyengine.angle_sprite import AngleSpriteMap, AngleEntry
        m = AngleSpriteMap(blend_mode="snap")
        for i, angle in enumerate([0.0, 90.0, 180.0, 270.0]):
            m.add_entry(AngleEntry(angle_deg=angle, layer_index=i))
        return m

    def test_resolve_exact_angle(self):
        m = self._make_4dir_snap()
        a, b, t = m.resolve(0.0)
        assert a == b == 0
        assert t == pytest.approx(0.0)

    def test_resolve_near_90(self):
        m = self._make_4dir_snap()
        a, b, t = m.resolve(85.0)
        assert a == b == 1  # closest to 90°

    def test_resolve_near_270(self):
        m = self._make_4dir_snap()
        a, b, t = m.resolve(265.0)
        assert a == b == 3  # closest to 270°

    def test_resolve_wrap_around(self):
        m = self._make_4dir_snap()
        a, b, t = m.resolve(355.0)
        assert a == b == 0  # closest to 0°/360°

    def test_snap_blend_t_is_zero(self):
        m = self._make_4dir_snap()
        _, _, t = m.resolve(45.0)
        assert t == pytest.approx(0.0)

    def test_no_entries_returns_safe_default(self):
        from slappyengine.angle_sprite import AngleSpriteMap
        m = AngleSpriteMap()
        a, b, t = m.resolve(0.0)
        assert a == 0 and b == 0 and t == pytest.approx(0.0)

    def test_single_entry_returns_same_layer(self):
        from slappyengine.angle_sprite import AngleSpriteMap, AngleEntry
        m = AngleSpriteMap(blend_mode="snap")
        m.add_entry(AngleEntry(angle_deg=0.0, layer_index=3))
        a, b, t = m.resolve(180.0)
        assert a == b == 3


class TestAngleSpriteMapResolveLerp:
    def _make_4dir_lerp(self):
        from slappyengine.angle_sprite import AngleSpriteMap, AngleEntry
        m = AngleSpriteMap(blend_mode="lerp")
        for i, angle in enumerate([0.0, 90.0, 180.0, 270.0]):
            m.add_entry(AngleEntry(angle_deg=angle, layer_index=i))
        return m

    def test_resolve_exactly_on_keyframe(self):
        m = self._make_4dir_lerp()
        a, b, t = m.resolve(0.0)
        # At exactly 0°, should have blend_t = 0 (pure first frame) or 1 (wraps)
        assert isinstance(a, int) and isinstance(b, int)
        assert 0.0 <= t <= 1.0

    def test_resolve_midpoint_blend(self):
        m = self._make_4dir_lerp()
        a, b, t = m.resolve(45.0)  # midway between 0° and 90°
        assert t == pytest.approx(0.5)
        assert {a, b} == {0, 1}

    def test_resolve_three_quarter_blend(self):
        m = self._make_4dir_lerp()
        a, b, t = m.resolve(67.5)  # 3/4 of the way from 0° to 90°
        assert t == pytest.approx(0.75)

    def test_blend_t_in_range(self):
        m = self._make_4dir_lerp()
        for angle in range(0, 360, 10):
            _, _, t = m.resolve(float(angle))
            assert 0.0 <= t <= 1.0, f"t={t} out of range at angle={angle}"

    def test_state_tag_filtering(self):
        from slappyengine.angle_sprite import AngleSpriteMap, AngleEntry
        m = AngleSpriteMap(blend_mode="snap")
        m.add_entry(AngleEntry(angle_deg=0.0, layer_index=0, state_tag=""))
        m.add_entry(AngleEntry(angle_deg=0.0, layer_index=5, state_tag="boosting"))
        a, b, t = m.resolve(0.0, state_tag="boosting")
        assert a == 5

    def test_state_tag_fallback_to_base(self):
        from slappyengine.angle_sprite import AngleSpriteMap, AngleEntry
        m = AngleSpriteMap(blend_mode="snap")
        m.add_entry(AngleEntry(angle_deg=0.0, layer_index=0, state_tag=""))
        a, b, t = m.resolve(0.0, state_tag="nonexistent")
        assert a == 0  # falls back to base state


class TestAngleSpriteMapApply:
    def _make_entity_with_layers(self, n_layers=4):
        class FakeLayer:
            def __init__(self):
                self.opacity = 1.0

        class FakeEntity:
            def __init__(self, n):
                self.rotation = 0.0
                self.layers = [FakeLayer() for _ in range(n)]

        return FakeEntity(n_layers)

    def test_apply_sets_visible_layer(self):
        from slappyengine.angle_sprite import AngleSpriteMap, AngleEntry
        m = AngleSpriteMap(blend_mode="snap")
        for i in range(4):
            m.add_entry(AngleEntry(angle_deg=float(i * 90), layer_index=i))
        entity = self._make_entity_with_layers(4)
        entity.rotation = 0.0
        m.apply(entity)
        assert entity.layers[0].opacity == pytest.approx(1.0)
        assert entity.layers[1].opacity == pytest.approx(0.0)

    def test_apply_empty_layers_no_crash(self):
        from slappyengine.angle_sprite import AngleSpriteMap, AngleEntry
        m = AngleSpriteMap()
        m.add_entry(AngleEntry(angle_deg=0.0, layer_index=0))

        class FakeEntity:
            rotation = 0.0
            layers = []

        m.apply(FakeEntity())

    def test_apply_lerp_distributes_opacity(self):
        from slappyengine.angle_sprite import AngleSpriteMap, AngleEntry
        m = AngleSpriteMap(blend_mode="lerp")
        m.add_entry(AngleEntry(angle_deg=0.0, layer_index=0))
        m.add_entry(AngleEntry(angle_deg=90.0, layer_index=1))
        entity = self._make_entity_with_layers(4)
        entity.rotation = 45.0  # midpoint → 0.5 blend
        m.apply(entity)
        assert entity.layers[0].opacity == pytest.approx(0.5)
        assert entity.layers[1].opacity == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# visibility.py — VisibilityObserver, VisibilityField
# ---------------------------------------------------------------------------

class _FakeEntity:
    def __init__(self, x=0.0, y=0.0):
        self.position = (x, y)
        self.rotation = 0.0


class TestVisibilityObserver:
    def test_instantiates(self):
        from slappyengine.visibility import VisibilityObserver
        e = _FakeEntity()
        obs = VisibilityObserver(entity=e)
        assert obs is not None

    def test_defaults(self):
        from slappyengine.visibility import VisibilityObserver
        obs = VisibilityObserver(entity=_FakeEntity())
        assert obs.range == pytest.approx(200.0)
        assert obs.mode == "circle"
        assert obs.cone_angle == pytest.approx(360.0)
        assert obs.hull_alpha == pytest.approx(0.3)
        assert obs.occluders == []


class TestVisibilityFieldBasics:
    def test_instantiates(self):
        from slappyengine.visibility import VisibilityField
        vf = VisibilityField(size=(64, 64))
        assert vf is not None

    def test_defaults(self):
        from slappyengine.visibility import VisibilityField
        vf = VisibilityField(size=(64, 64))
        assert vf.blend_radius == pytest.approx(20.0)
        assert vf.overlap_mode == "max"
        assert vf.decay_rate == pytest.approx(0.0)

    def test_initial_field_all_zero(self):
        from slappyengine.visibility import VisibilityField
        vf = VisibilityField(size=(32, 32))
        assert np.all(vf._field == 0.0)

    def test_sample_initially_zero(self):
        from slappyengine.visibility import VisibilityField
        vf = VisibilityField(size=(64, 64))
        assert vf.sample((10.0, 10.0)) == pytest.approx(0.0)

    def test_add_observer_returns_handle(self):
        from slappyengine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField(size=(64, 64))
        obs = VisibilityObserver(entity=_FakeEntity(32, 32))
        h = vf.add_observer(obs)
        assert isinstance(h, int)

    def test_remove_observer_no_crash(self):
        from slappyengine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField(size=(64, 64))
        obs = VisibilityObserver(entity=_FakeEntity(32, 32))
        h = vf.add_observer(obs)
        vf.remove_observer(h)

    def test_remove_nonexistent_no_crash(self):
        from slappyengine.visibility import VisibilityField
        vf = VisibilityField(size=(64, 64))
        vf.remove_observer(9999)  # should not raise


class TestVisibilityFieldUpdate:
    def test_update_no_observers_no_crash(self):
        from slappyengine.visibility import VisibilityField
        vf = VisibilityField(size=(64, 64))
        vf.update()

    def test_update_circle_observer_reveals_center(self):
        from slappyengine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField(size=(64, 64), blend_radius=0)
        entity = _FakeEntity(32.0, 32.0)
        obs = VisibilityObserver(entity=entity, range=10.0, mode="circle")
        vf.add_observer(obs)
        vf.update()
        # Center should be visible
        assert vf.sample((32.0, 32.0)) > 0.0

    def test_update_circle_does_not_reveal_far(self):
        from slappyengine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField(size=(128, 128), blend_radius=0)
        entity = _FakeEntity(64.0, 64.0)
        obs = VisibilityObserver(entity=entity, range=5.0, mode="circle")
        vf.add_observer(obs)
        vf.update()
        # Far corner should still be 0
        assert vf.sample((0.0, 0.0)) == pytest.approx(0.0)

    def test_overlap_mode_max(self):
        from slappyengine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField(size=(64, 64), blend_radius=0, overlap_mode="max")
        vf.add_observer(VisibilityObserver(entity=_FakeEntity(32, 32), range=15))
        vf.update()
        val = vf.sample((32.0, 32.0))
        assert 0.0 <= val <= 1.0

    def test_overlap_mode_add(self):
        from slappyengine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField(size=(64, 64), blend_radius=0, overlap_mode="add")
        vf.add_observer(VisibilityObserver(entity=_FakeEntity(32, 32), range=15))
        vf.update()
        val = vf.sample((32.0, 32.0))
        assert 0.0 <= val <= 1.0

    def test_decay_rate_zero_permanent(self):
        from slappyengine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField(size=(64, 64), blend_radius=0, decay_rate=0.0)
        e = _FakeEntity(32, 32)
        obs = VisibilityObserver(entity=e, range=10, mode="circle")
        h = vf.add_observer(obs)
        vf.update()
        val_before = vf.sample((32.0, 32.0))
        vf.remove_observer(h)
        vf.update()  # no observers now
        val_after = vf.sample((32.0, 32.0))
        # Permanent reveal: should stay revealed (no decay)
        assert val_after >= val_before

    def test_decay_reduces_visibility(self):
        from slappyengine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField(size=(64, 64), blend_radius=0, decay_rate=0.5)
        e = _FakeEntity(32, 32)
        obs = VisibilityObserver(entity=e, range=10, mode="circle")
        h = vf.add_observer(obs)
        vf.update()
        vf.remove_observer(h)
        val_first = vf.sample((32.0, 32.0))
        vf.update()  # second update with no observers
        val_second = vf.sample((32.0, 32.0))
        # With decay=0.5 and no new observers, field should diminish
        assert val_second <= val_first

    def test_cone_mode_no_crash(self):
        from slappyengine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField(size=(64, 64))
        obs = VisibilityObserver(entity=_FakeEntity(32, 32), range=15,
                                 mode="cone", cone_angle=90.0)
        vf.add_observer(obs)
        vf.update()  # should not raise

    def test_get_layer_no_crash(self):
        from slappyengine.visibility import VisibilityField, VisibilityObserver
        vf = VisibilityField(size=(64, 64))
        obs = VisibilityObserver(entity=_FakeEntity(32, 32), range=10)
        vf.add_observer(obs)
        vf.update()
        layer = vf.get_layer()
        # May return None if Layer2D import fails headlessly, but should not raise
