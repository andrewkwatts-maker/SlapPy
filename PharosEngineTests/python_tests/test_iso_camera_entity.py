"""Engine tests for IsoCamera, IsoEntity, and TagRegistry — headless."""
from __future__ import annotations
import math
import pytest


class TestTagRegistry:
    def test_define_creates_bit(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        mask = reg.define("enemy")
        assert mask == 1  # bit 0

    def test_define_second_tag_next_bit(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        reg.define("enemy")
        mask = reg.define("player")
        assert mask == 2  # bit 1

    def test_define_duplicate_returns_same_mask(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        m1 = reg.define("enemy")
        m2 = reg.define("enemy")
        assert m1 == m2

    def test_define_explicit_bit(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        mask = reg.define("boss", bit=5)
        assert mask == (1 << 5)

    def test_define_bit_exceeds_max_raises(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry(max_bits=4)
        with pytest.raises(ValueError):
            reg.define("overflow", bit=4)

    def test_mask_combines_tags(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        reg.define("enemy")
        reg.define("player")
        combined = reg.mask("enemy", "player")
        assert combined == 3  # bits 0 and 1

    def test_mask_undefined_raises(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        with pytest.raises(KeyError):
            reg.mask("nonexistent")

    def test_getitem_returns_mask(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        reg.define("pickup")
        assert reg["pickup"] == 1

    def test_contains_true_for_defined(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        reg.define("wall")
        assert "wall" in reg

    def test_contains_false_for_undefined(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        assert "ghost" not in reg

    def test_name_for_bit_found(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        reg.define("trigger")
        assert reg.name_for_bit(0) == "trigger"

    def test_name_for_bit_not_found(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        assert reg.name_for_bit(7) is None

    def test_all_tags_returns_dict(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        reg.define("a")
        reg.define("b")
        tags = reg.all_tags()
        assert "a" in tags
        assert "b" in tags


class TestIsoCameraInit:
    def test_default_viewpoint_ne(self):
        from pharos_engine.iso.iso_camera import IsoCamera
        from pharos_engine.iso.projection import IsoViewpoint
        cam = IsoCamera()
        assert cam.viewpoint == IsoViewpoint.NE

    def test_default_pan_zero(self):
        from pharos_engine.iso.iso_camera import IsoCamera
        cam = IsoCamera()
        assert cam.cam_x == pytest.approx(0.0)
        assert cam.cam_y == pytest.approx(0.0)


class TestIsoCameraPan:
    def test_pan_shifts_offset(self):
        from pharos_engine.iso.iso_camera import IsoCamera
        cam = IsoCamera()
        cam.pan(50.0, 30.0)
        assert cam.cam_x == pytest.approx(50.0)
        assert cam.cam_y == pytest.approx(30.0)

    def test_pan_accumulates(self):
        from pharos_engine.iso.iso_camera import IsoCamera
        cam = IsoCamera()
        cam.pan(10.0, 20.0)
        cam.pan(5.0, -5.0)
        assert cam.cam_x == pytest.approx(15.0)
        assert cam.cam_y == pytest.approx(15.0)

    def test_reset_pan_zeros(self):
        from pharos_engine.iso.iso_camera import IsoCamera
        cam = IsoCamera()
        cam.pan(100.0, 200.0)
        cam.reset_pan()
        assert cam.cam_x == pytest.approx(0.0)
        assert cam.cam_y == pytest.approx(0.0)


class TestIsoCameraRotation:
    def test_rotate_cw_ne_to_se(self):
        from pharos_engine.iso.iso_camera import IsoCamera
        from pharos_engine.iso.projection import IsoViewpoint
        cam = IsoCamera(IsoViewpoint.NE)
        cam.rotate_cw()
        assert cam.viewpoint == IsoViewpoint.SE

    def test_rotate_cw_full_cycle(self):
        from pharos_engine.iso.iso_camera import IsoCamera
        from pharos_engine.iso.projection import IsoViewpoint
        cam = IsoCamera(IsoViewpoint.NE)
        for _ in range(4):
            cam.rotate_cw()
        assert cam.viewpoint == IsoViewpoint.NE

    def test_rotate_ccw_ne_to_nw(self):
        from pharos_engine.iso.iso_camera import IsoCamera
        from pharos_engine.iso.projection import IsoViewpoint
        cam = IsoCamera(IsoViewpoint.NE)
        cam.rotate_ccw()
        assert cam.viewpoint == IsoViewpoint.NW

    def test_rotate_ccw_full_cycle(self):
        from pharos_engine.iso.iso_camera import IsoCamera
        from pharos_engine.iso.projection import IsoViewpoint
        cam = IsoCamera(IsoViewpoint.NE)
        for _ in range(4):
            cam.rotate_ccw()
        assert cam.viewpoint == IsoViewpoint.NE

    def test_cw_ccw_inverse(self):
        from pharos_engine.iso.iso_camera import IsoCamera
        from pharos_engine.iso.projection import IsoViewpoint
        cam = IsoCamera(IsoViewpoint.SW)
        cam.rotate_cw()
        cam.rotate_ccw()
        assert cam.viewpoint == IsoViewpoint.SW

    def test_set_viewpoint(self):
        from pharos_engine.iso.iso_camera import IsoCamera
        from pharos_engine.iso.projection import IsoViewpoint
        cam = IsoCamera()
        cam.set_viewpoint(IsoViewpoint.SW)
        assert cam.viewpoint == IsoViewpoint.SW


class TestIsoCameraAngle:
    def test_angle_deg_ne_is_45(self):
        from pharos_engine.iso.iso_camera import IsoCamera
        from pharos_engine.iso.projection import IsoViewpoint
        cam = IsoCamera(IsoViewpoint.NE)
        assert cam.angle_deg == pytest.approx(45.0)

    def test_angle_deg_all_viewpoints_distinct(self):
        from pharos_engine.iso.iso_camera import IsoCamera
        from pharos_engine.iso.projection import IsoViewpoint
        angles = set()
        for vp in IsoViewpoint:
            cam = IsoCamera(vp)
            angles.add(cam.angle_deg)
        assert len(angles) == 4


class TestIsoCameraScreenToGrid:
    def test_center_maps_to_origin(self):
        from pharos_engine.iso.iso_camera import IsoCamera
        from pharos_engine.iso.projection import IsoViewpoint
        cam = IsoCamera(IsoViewpoint.NE)
        gx, gy = cam.screen_to_grid(640, 360, screen_w=1280, screen_h=720)
        assert gx == 0
        assert gy == 0


class TestIsoCameraUpdateEntityViewpoints:
    def test_sets_entity_rotation(self):
        from pharos_engine.iso.iso_camera import IsoCamera
        from pharos_engine.iso.projection import IsoViewpoint

        class _E:
            rotation = 0.0

        cam = IsoCamera(IsoViewpoint.NE)
        e = _E()
        cam.update_entity_viewpoints([e])
        assert e.rotation == pytest.approx(45.0)  # NE viewpoint angle

    def test_respects_facing_angle(self):
        from pharos_engine.iso.iso_camera import IsoCamera
        from pharos_engine.iso.projection import IsoViewpoint

        class _E:
            rotation = 0.0
            _facing_angle = 90.0  # facing east

        cam = IsoCamera(IsoViewpoint.NE)
        e = _E()
        cam.update_entity_viewpoints([e])
        assert e.rotation == pytest.approx((90.0 + 45.0) % 360)

    def test_multiple_entities(self):
        from pharos_engine.iso.iso_camera import IsoCamera
        from pharos_engine.iso.projection import IsoViewpoint

        class _E:
            rotation = 0.0

        cam = IsoCamera(IsoViewpoint.SW)
        entities = [_E() for _ in range(5)]
        cam.update_entity_viewpoints(entities)
        for e in entities:
            assert e.rotation == pytest.approx(225.0)  # SW angle


class TestIsoEntity:
    def test_defaults(self):
        from pharos_engine.iso.iso_entity import IsoEntity
        e = IsoEntity()
        assert e.grid_x == pytest.approx(0.0)
        assert e.grid_y == pytest.approx(0.0)
        assert e.grid_z == pytest.approx(0.0)
        assert e.facing_angle == pytest.approx(0.0)
        assert e.receives_fluid_forces is False

    def test_total_z_sum(self):
        from pharos_engine.iso.iso_entity import IsoEntity
        e = IsoEntity(grid_z=3.0, local_z=0.5)
        assert e.total_z == pytest.approx(3.5)

    def test_facing_angle_alias(self):
        from pharos_engine.iso.iso_entity import IsoEntity
        e = IsoEntity(facing_angle=120.0)
        assert e._facing_angle == pytest.approx(120.0)

    def test_move_to(self):
        from pharos_engine.iso.iso_entity import IsoEntity
        e = IsoEntity()
        e.move_to(5.0, 3.0, 1.0)
        assert e.grid_x == pytest.approx(5.0)
        assert e.grid_y == pytest.approx(3.0)
        assert e.grid_z == pytest.approx(1.0)

    def test_move_by(self):
        from pharos_engine.iso.iso_entity import IsoEntity
        e = IsoEntity(grid_x=2.0, grid_y=1.0)
        e.move_by(1.0, -1.0)
        assert e.grid_x == pytest.approx(3.0)
        assert e.grid_y == pytest.approx(0.0)

    def test_face_toward_sets_angle(self):
        from pharos_engine.iso.iso_entity import IsoEntity
        e = IsoEntity(grid_x=0.0, grid_y=0.0)
        e.face_toward(1.0, 0.0)
        assert e.facing_angle == pytest.approx(0.0, abs=1.0)

    def test_face_toward_normalized_to_360(self):
        from pharos_engine.iso.iso_entity import IsoEntity
        e = IsoEntity(grid_x=0.0, grid_y=0.0)
        e.face_toward(-1.0, -1.0)  # SW direction
        assert 0.0 <= e.facing_angle < 360.0

    def test_distance_to_pythagoras(self):
        from pharos_engine.iso.iso_entity import IsoEntity
        a = IsoEntity(grid_x=0.0, grid_y=0.0)
        b = IsoEntity(grid_x=3.0, grid_y=4.0)
        assert a.distance_to(b) == pytest.approx(5.0)

    def test_distance_to_self_is_zero(self):
        from pharos_engine.iso.iso_entity import IsoEntity
        e = IsoEntity(grid_x=5.0, grid_y=5.0)
        assert e.distance_to(e) == pytest.approx(0.0)

    def test_distance_ignores_z(self):
        from pharos_engine.iso.iso_entity import IsoEntity
        a = IsoEntity(grid_x=0.0, grid_y=0.0, grid_z=0.0)
        b = IsoEntity(grid_x=3.0, grid_y=4.0, grid_z=100.0)
        assert a.distance_to(b) == pytest.approx(5.0)
