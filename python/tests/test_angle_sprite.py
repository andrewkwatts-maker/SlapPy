"""Engine tests for AngleSpriteMap + make_angle_map_from_spritesheet — headless."""
from __future__ import annotations
import math
import pytest


def _make_map_4way(blend_mode="lerp"):
    from slappyengine.angle_sprite import AngleSpriteMap, AngleEntry
    amap = AngleSpriteMap(blend_mode=blend_mode)
    for i, angle in enumerate([0.0, 90.0, 180.0, 270.0]):
        amap.add_entry(AngleEntry(angle_deg=angle, layer_index=i))
    return amap


class _FakeLayer:
    def __init__(self):
        self.opacity = 0.0


class _FakeEntity:
    def __init__(self, layer_count=4, rotation=0.0):
        self.rotation = rotation
        self.layers = [_FakeLayer() for _ in range(layer_count)]


class TestAngleEntryBasic:
    def test_entry_stores_fields(self):
        from slappyengine.angle_sprite import AngleEntry
        e = AngleEntry(angle_deg=45.0, layer_index=3, state_tag="boosting")
        assert e.angle_deg == pytest.approx(45.0)
        assert e.layer_index == 3
        assert e.state_tag == "boosting"

    def test_entry_default_state_tag(self):
        from slappyengine.angle_sprite import AngleEntry
        e = AngleEntry(angle_deg=0.0, layer_index=0)
        assert e.state_tag == ""


class TestAngleSpriteMapInit:
    def test_default_blend_mode_lerp(self):
        from slappyengine.angle_sprite import AngleSpriteMap
        amap = AngleSpriteMap()
        assert amap.blend_mode == "lerp"

    def test_entries_empty_initially(self):
        from slappyengine.angle_sprite import AngleSpriteMap
        amap = AngleSpriteMap()
        assert len(amap.entries) == 0

    def test_add_entry_increases_count(self):
        from slappyengine.angle_sprite import AngleSpriteMap, AngleEntry
        amap = AngleSpriteMap()
        amap.add_entry(AngleEntry(0.0, 0))
        amap.add_entry(AngleEntry(90.0, 1))
        assert len(amap.entries) == 2


class TestResolveLerp:
    def test_exact_keyframe_zero_blend(self):
        amap = _make_map_4way("lerp")
        a, b, t = amap.resolve(0.0)
        assert a == 0
        assert t == pytest.approx(0.0)

    def test_midpoint_blend_half(self):
        amap = _make_map_4way("lerp")
        a, b, t = amap.resolve(45.0)
        assert a == 0
        assert b == 1
        assert t == pytest.approx(0.5)

    def test_three_quarter_point_blend(self):
        amap = _make_map_4way("lerp")
        a, b, t = amap.resolve(67.5)  # 3/4 of the way from 0→90
        assert a == 0
        assert b == 1
        assert t == pytest.approx(0.75)

    def test_second_segment_blend(self):
        amap = _make_map_4way("lerp")
        a, b, t = amap.resolve(135.0)  # midpoint 90→180
        assert a == 1
        assert b == 2
        assert t == pytest.approx(0.5)

    def test_circular_wrap_near_360(self):
        amap = _make_map_4way("lerp")
        # 315° is midpoint between 270°(idx=3) and 360°/0°(idx=0)
        a, b, t = amap.resolve(315.0)
        assert a == 3
        assert b == 0
        assert t == pytest.approx(0.5)

    def test_exact_90_keyframe(self):
        amap = _make_map_4way("lerp")
        a, b, t = amap.resolve(90.0)
        assert (a == 1 or b == 1)
        assert t == pytest.approx(0.0) or t == pytest.approx(1.0)

    def test_blend_t_clamped_0_to_1(self):
        amap = _make_map_4way("lerp")
        for angle in [0.0, 45.0, 90.0, 180.0, 270.0, 315.0, 359.9]:
            _, _, t = amap.resolve(angle)
            assert 0.0 <= t <= 1.0


class TestResolveSnap:
    def test_snap_returns_same_index_both(self):
        amap = _make_map_4way("snap")
        a, b, t = amap.resolve(44.0)
        assert a == b
        assert t == pytest.approx(0.0)

    def test_snap_nearest_to_0(self):
        amap = _make_map_4way("snap")
        a, b, _ = amap.resolve(10.0)
        assert a == 0  # nearest to 0°

    def test_snap_nearest_to_90(self):
        amap = _make_map_4way("snap")
        a, b, _ = amap.resolve(80.0)
        assert a == 1  # nearest to 90°

    def test_snap_nearest_to_270(self):
        amap = _make_map_4way("snap")
        a, b, _ = amap.resolve(260.0)
        assert a == 3  # nearest to 270°


class TestResolveEdgeCases:
    def test_single_entry_returns_that_index(self):
        from slappyengine.angle_sprite import AngleSpriteMap, AngleEntry
        amap = AngleSpriteMap()
        amap.add_entry(AngleEntry(45.0, layer_index=7))
        a, b, t = amap.resolve(200.0)
        assert a == 7
        assert b == 7
        assert t == pytest.approx(0.0)

    def test_no_entries_returns_safe_default(self):
        from slappyengine.angle_sprite import AngleSpriteMap
        amap = AngleSpriteMap()
        a, b, t = amap.resolve(0.0)
        assert a == 0
        assert b == 0
        assert t == pytest.approx(0.0)

    def test_angle_normalised_over_360(self):
        amap = _make_map_4way("lerp")
        a_normal, b_normal, t_normal = amap.resolve(45.0)
        a_over, b_over, t_over = amap.resolve(45.0 + 360.0)
        assert a_normal == a_over
        assert b_normal == b_over
        assert t_normal == pytest.approx(t_over)


class TestStateTag:
    def test_state_tag_filters_entries(self):
        from slappyengine.angle_sprite import AngleSpriteMap, AngleEntry
        amap = AngleSpriteMap()
        amap.add_entry(AngleEntry(0.0, layer_index=0, state_tag=""))
        amap.add_entry(AngleEntry(0.0, layer_index=5, state_tag="damaged"))
        a, b, _ = amap.resolve(0.0, state_tag="damaged")
        assert a == 5

    def test_state_tag_fallback_to_base(self):
        from slappyengine.angle_sprite import AngleSpriteMap, AngleEntry
        amap = AngleSpriteMap()
        amap.add_entry(AngleEntry(0.0, layer_index=0))  # base state
        # Requesting "damaged" state falls back to base when no damaged entries
        a, b, _ = amap.resolve(0.0, state_tag="damaged")
        assert a == 0


class TestCloneState:
    def test_clone_creates_entries_with_new_tag(self):
        from slappyengine.angle_sprite import AngleSpriteMap, AngleEntry
        amap = AngleSpriteMap()
        amap.add_entry(AngleEntry(0.0,   layer_index=0))
        amap.add_entry(AngleEntry(90.0,  layer_index=1))
        amap.clone_state("", "damaged", layer_offset=10)
        damaged = [e for e in amap.entries if e.state_tag == "damaged"]
        assert len(damaged) == 2

    def test_clone_offsets_layer_index(self):
        from slappyengine.angle_sprite import AngleSpriteMap, AngleEntry
        amap = AngleSpriteMap()
        amap.add_entry(AngleEntry(0.0, layer_index=2))
        amap.clone_state("", "alt", layer_offset=8)
        alt = [e for e in amap.entries if e.state_tag == "alt"]
        assert alt[0].layer_index == 10

    def test_clone_preserves_angles(self):
        from slappyengine.angle_sprite import AngleSpriteMap, AngleEntry
        amap = AngleSpriteMap()
        amap.add_entry(AngleEntry(45.0, layer_index=0))
        amap.clone_state("", "boosting", layer_offset=4)
        boosting = [e for e in amap.entries if e.state_tag == "boosting"]
        assert boosting[0].angle_deg == pytest.approx(45.0)


class TestApply:
    def test_apply_sets_correct_layer_opacity_snap(self):
        amap = _make_map_4way("snap")
        entity = _FakeEntity(rotation=5.0)  # snaps to layer 0
        amap.apply(entity)
        assert entity.layers[0].opacity == pytest.approx(1.0)
        assert entity.layers[1].opacity == pytest.approx(0.0)

    def test_apply_zeroes_other_layers(self):
        amap = _make_map_4way("snap")
        entity = _FakeEntity(rotation=90.0)  # snaps to layer 1
        amap.apply(entity)
        assert entity.layers[0].opacity == pytest.approx(0.0)
        assert entity.layers[2].opacity == pytest.approx(0.0)

    def test_apply_lerp_sums_to_one(self):
        amap = _make_map_4way("lerp")
        entity = _FakeEntity(rotation=45.0)
        amap.apply(entity)
        total = sum(l.opacity for l in entity.layers)
        assert total == pytest.approx(1.0)

    def test_apply_empty_layers_no_crash(self):
        amap = _make_map_4way("lerp")
        entity = _FakeEntity(layer_count=0, rotation=0.0)
        amap.apply(entity)  # should not raise


class TestMakeAngleMapFromSpritesheet:
    def test_creates_correct_number_of_entries(self):
        from slappyengine.angle_sprite import make_angle_map_from_spritesheet
        amap = make_angle_map_from_spritesheet(8)
        assert len(amap.entries) == 8

    def test_angles_evenly_spaced(self):
        from slappyengine.angle_sprite import make_angle_map_from_spritesheet
        amap = make_angle_map_from_spritesheet(4)
        angles = sorted(e.angle_deg for e in amap.entries)
        assert angles == pytest.approx([0.0, 90.0, 180.0, 270.0])

    def test_layer_start_offset_applied(self):
        from slappyengine.angle_sprite import make_angle_map_from_spritesheet
        amap = make_angle_map_from_spritesheet(4, layer_start=10)
        indices = sorted(e.layer_index for e in amap.entries)
        assert indices == [10, 11, 12, 13]

    def test_blend_mode_passed_through(self):
        from slappyengine.angle_sprite import make_angle_map_from_spritesheet
        amap = make_angle_map_from_spritesheet(4, blend_mode="snap")
        assert amap.blend_mode == "snap"

    def test_angle_offset_shifts_all_angles(self):
        from slappyengine.angle_sprite import make_angle_map_from_spritesheet
        amap = make_angle_map_from_spritesheet(4, angle_offset=45.0)
        angles = sorted(e.angle_deg for e in amap.entries)
        assert angles == pytest.approx([45.0, 135.0, 225.0, 315.0])
