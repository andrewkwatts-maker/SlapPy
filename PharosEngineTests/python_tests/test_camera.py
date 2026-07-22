"""Engine tests for Camera — headless."""
from __future__ import annotations
import math
import pytest


class _Entity:
    def __init__(self, x=0.0, y=0.0):
        self.position = (x, y)


class TestCameraInit:
    def test_default_position_origin(self):
        from pharos_engine.camera import Camera
        cam = Camera()
        assert cam.position == (0.0, 0.0)

    def test_default_zoom_one(self):
        from pharos_engine.camera import Camera
        cam = Camera()
        assert cam.zoom == pytest.approx(1.0)

    def test_default_rotation_zero(self):
        from pharos_engine.camera import Camera
        cam = Camera()
        assert cam.rotation == pytest.approx(0.0)

    def test_init_with_values(self):
        from pharos_engine.camera import Camera
        cam = Camera(position=(100.0, 200.0), zoom=2.0, rotation=0.5)
        assert cam.position == (100.0, 200.0)
        assert cam.zoom == pytest.approx(2.0)
        assert cam.rotation == pytest.approx(0.5)


class TestCameraWorldToScreen:
    def test_origin_at_center(self):
        from pharos_engine.camera import Camera
        cam = Camera(position=(0.0, 0.0))
        cam._viewport_size = (800, 600)
        sx, sy = cam.world_to_screen((0.0, 0.0))
        assert sx == pytest.approx(400.0)  # vw/2
        assert sy == pytest.approx(300.0)  # vh/2

    def test_world_point_right_of_cam(self):
        from pharos_engine.camera import Camera
        cam = Camera(position=(0.0, 0.0))
        cam._viewport_size = (800, 600)
        sx, sy = cam.world_to_screen((100.0, 0.0))
        assert sx == pytest.approx(500.0)  # 400 + 100

    def test_zoom_doubles_offset(self):
        from pharos_engine.camera import Camera
        cam = Camera(position=(0.0, 0.0), zoom=2.0)
        cam._viewport_size = (800, 600)
        sx1, _ = Camera(position=(0.0, 0.0)).world_to_screen((50.0, 0.0))
        cam._viewport_size = (800, 600)
        sx2, _ = cam.world_to_screen((50.0, 0.0))
        # At zoom=2, offset should be doubled
        assert sx2 - 400.0 == pytest.approx(2.0 * (sx1 - 400.0))


class TestCameraScreenToWorld:
    def test_center_maps_to_cam_position(self):
        from pharos_engine.camera import Camera
        cam = Camera(position=(0.0, 0.0))
        cam._viewport_size = (800, 600)
        wx, wy = cam.screen_to_world((400.0, 300.0))
        assert wx == pytest.approx(0.0)
        assert wy == pytest.approx(0.0)

    def test_roundtrip_w2s_s2w(self):
        from pharos_engine.camera import Camera
        cam = Camera(position=(50.0, 80.0), zoom=1.5)
        cam._viewport_size = (800, 600)
        world_pt = (120.0, 240.0)
        screen_pt = cam.world_to_screen(world_pt)
        restored = cam.screen_to_world(screen_pt)
        assert restored[0] == pytest.approx(world_pt[0], abs=0.01)
        assert restored[1] == pytest.approx(world_pt[1], abs=0.01)


class TestCameraVisibleRect:
    def test_visible_rect_includes_position(self):
        from pharos_engine.camera import Camera
        cam = Camera(position=(100.0, 100.0))
        cam._viewport_size = (200, 100)
        x0, y0, x1, y1 = cam.visible_rect()
        assert x0 < 100.0 < x1
        assert y0 < 100.0 < y1

    def test_visible_rect_size_at_zoom_1(self):
        from pharos_engine.camera import Camera
        cam = Camera(position=(0.0, 0.0), zoom=1.0)
        cam._viewport_size = (800, 600)
        x0, y0, x1, y1 = cam.visible_rect()
        assert (x1 - x0) == pytest.approx(800.0)
        assert (y1 - y0) == pytest.approx(600.0)

    def test_visible_rect_smaller_at_zoom_2(self):
        from pharos_engine.camera import Camera
        cam_z1 = Camera(position=(0.0, 0.0), zoom=1.0)
        cam_z1._viewport_size = (800, 600)
        cam_z2 = Camera(position=(0.0, 0.0), zoom=2.0)
        cam_z2._viewport_size = (800, 600)
        r1 = cam_z1.visible_rect()
        r2 = cam_z2.visible_rect()
        assert (r2[2] - r2[0]) < (r1[2] - r1[0])


class TestCameraFollow:
    def test_follow_snap_moves_to_target(self):
        from pharos_engine.camera import Camera
        cam = Camera(position=(0.0, 0.0))
        cam._viewport_size = (800, 600)
        entity = _Entity(400.0, 300.0)
        cam.follow(entity, lerp=1.0, screen_w=800, screen_h=600)
        # Entity at (400,300) with screen size 800x600 → target = (400-400, 300-300) = (0,0)
        assert cam.position[0] == pytest.approx(0.0)
        assert cam.position[1] == pytest.approx(0.0)

    def test_follow_lerp_partial_move(self):
        from pharos_engine.camera import Camera
        cam = Camera(position=(0.0, 0.0))
        cam._viewport_size = (800, 600)
        entity = _Entity(800.0, 600.0)  # target cam pos → (0, 0) for 800x600 screen
        initial_x = cam.position[0]
        cam.follow(entity, lerp=0.5, screen_w=800, screen_h=600)
        # Half-step toward target
        assert cam.position[0] != initial_x or cam.position[1] != 0.0

    def test_follow_large_lerp_snaps(self):
        from pharos_engine.camera import Camera
        cam = Camera(position=(0.0, 0.0))
        cam._viewport_size = (800, 600)
        entity = _Entity(100.0, 100.0)
        cam.follow(entity, lerp=1.0, screen_w=800, screen_h=600)
        # At lerp=1.0, should snap exactly to target
        assert cam.position == (100.0 - 400, 100.0 - 300)


class TestCameraViewMatrix:
    def test_view_matrix_returns_16_floats(self):
        from pharos_engine.camera import Camera
        cam = Camera()
        m = cam.view_matrix()
        assert len(m) == 16

    def test_view_matrix_no_crash_with_rotation(self):
        from pharos_engine.camera import Camera
        cam = Camera(rotation=0.5, zoom=1.5)
        cam.view_matrix()

    def test_view_matrix_identity_like_at_origin(self):
        from pharos_engine.camera import Camera
        cam = Camera(position=(0.0, 0.0), zoom=1.0, rotation=0.0)
        cam._viewport_size = (2, 2)  # simple: 2×scale/2 = scale
        m = cam.view_matrix()
        # col 0 = (a*cr, b*sr, 0, 0) = (a, 0, 0, 0) when rotation=0
        # col 3 translation should be 0 at origin
        assert m[12] == pytest.approx(0.0)  # tx
        assert m[13] == pytest.approx(0.0)  # ty
