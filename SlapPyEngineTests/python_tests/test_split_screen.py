"""Engine tests for SplitScreenManager + Viewport — headless."""
from __future__ import annotations
import pytest


class TestViewport:
    def test_init_stores_fields(self):
        from pharos_engine.split_screen import Viewport
        vp = Viewport(player_id=0, x=0, y=0, width=640, height=360, camera=None)
        assert vp.player_id == 0
        assert vp.width == 640
        assert vp.height == 360

    def test_default_border_color(self):
        from pharos_engine.split_screen import Viewport
        vp = Viewport(player_id=0, x=0, y=0, width=100, height=100, camera=None)
        assert isinstance(vp.border_color, tuple)
        assert len(vp.border_color) == 3

    def test_default_border_px(self):
        from pharos_engine.split_screen import Viewport
        vp = Viewport(player_id=0, x=0, y=0, width=100, height=100, camera=None)
        assert vp.border_px == 2


class TestSplitScreenManagerSinglePlayer:
    def test_one_player_full_screen(self):
        from pharos_engine.split_screen import SplitScreenManager
        ss = SplitScreenManager(1280, 720, num_players=1)
        assert len(ss.viewports) == 1
        vp = ss.viewports[0]
        assert vp.width == 1280
        assert vp.height == 720

    def test_one_player_at_origin(self):
        from pharos_engine.split_screen import SplitScreenManager
        ss = SplitScreenManager(1280, 720, num_players=1)
        assert ss.viewports[0].x == 0
        assert ss.viewports[0].y == 0


class TestSplitScreenManagerTwoPlayers:
    def test_two_players_landscape_side_by_side(self):
        from pharos_engine.split_screen import SplitScreenManager
        ss = SplitScreenManager(1280, 720, num_players=2)  # landscape
        assert len(ss.viewports) == 2
        # Both should be full height
        assert ss.viewports[0].height == 720
        assert ss.viewports[1].height == 720
        # Should be side by side
        assert ss.viewports[0].x == 0
        assert ss.viewports[1].x > 0

    def test_two_players_portrait_top_bottom(self):
        from pharos_engine.split_screen import SplitScreenManager
        ss = SplitScreenManager(600, 900, num_players=2)  # portrait (H > W)
        assert ss.viewports[0].y == 0
        assert ss.viewports[1].y > 0

    def test_two_players_cover_full_screen(self):
        from pharos_engine.split_screen import SplitScreenManager
        W, H = 1280, 720
        ss = SplitScreenManager(W, H, num_players=2)
        total_area = sum(vp.width * vp.height for vp in ss.viewports)
        assert total_area == W * H


class TestSplitScreenManagerThreePlayers:
    def test_three_players_three_viewports(self):
        from pharos_engine.split_screen import SplitScreenManager
        ss = SplitScreenManager(1280, 720, num_players=3)
        assert len(ss.viewports) == 3

    def test_three_players_first_is_top_panel(self):
        from pharos_engine.split_screen import SplitScreenManager
        ss = SplitScreenManager(1280, 720, num_players=3)
        vp0 = ss.viewports[0]
        # Top panel: y=0, full width
        assert vp0.x == 0
        assert vp0.y == 0
        assert vp0.width == 1280


class TestSplitScreenManagerFourPlayers:
    def test_four_players_four_viewports(self):
        from pharos_engine.split_screen import SplitScreenManager
        ss = SplitScreenManager(1280, 720, num_players=4)
        assert len(ss.viewports) == 4

    def test_four_players_grid_layout(self):
        from pharos_engine.split_screen import SplitScreenManager
        ss = SplitScreenManager(1280, 720, num_players=4)
        # 4 players → 2×2 grid
        xs = {vp.x for vp in ss.viewports}
        ys = {vp.y for vp in ss.viewports}
        assert len(xs) == 2  # two column positions
        assert len(ys) == 2  # two row positions

    def test_four_players_cover_full_screen(self):
        from pharos_engine.split_screen import SplitScreenManager
        W, H = 1280, 720
        ss = SplitScreenManager(W, H, num_players=4)
        total_area = sum(vp.width * vp.height for vp in ss.viewports)
        assert total_area == W * H


class TestSplitScreenManagerNPlayers:
    def test_six_players_no_crash(self):
        from pharos_engine.split_screen import SplitScreenManager
        ss = SplitScreenManager(1280, 720, num_players=6)
        assert len(ss.viewports) == 6

    def test_player_ids_correct(self):
        from pharos_engine.split_screen import SplitScreenManager
        ss = SplitScreenManager(1280, 720, num_players=4)
        ids = [vp.player_id for vp in ss.viewports]
        assert ids == [0, 1, 2, 3]

    def test_cameras_assigned_from_list(self):
        from pharos_engine.split_screen import SplitScreenManager
        cams = ["cam0", "cam1", "cam2"]
        ss = SplitScreenManager(1280, 720, num_players=3, cameras=cams)
        assert ss.viewports[0].camera == "cam0"
        assert ss.viewports[1].camera == "cam1"
        assert ss.viewports[2].camera == "cam2"


class TestSplitScreenManagerSetCamera:
    def test_set_camera_assigns_camera(self):
        from pharos_engine.split_screen import SplitScreenManager
        ss = SplitScreenManager(1280, 720, num_players=2)
        ss.set_camera(0, "my_camera")
        assert ss.viewports[0].camera == "my_camera"

    def test_set_camera_invalid_player_raises(self):
        from pharos_engine.split_screen import SplitScreenManager
        ss = SplitScreenManager(1280, 720, num_players=2)
        with pytest.raises(ValueError):
            ss.set_camera(99, "cam")


class TestSplitScreenManagerSetLayout:
    def test_set_layout_replaces_viewports(self):
        from pharos_engine.split_screen import SplitScreenManager, Viewport
        ss = SplitScreenManager(1280, 720, num_players=2)
        custom = [
            Viewport(0, 0, 0, 640, 720, None),
            Viewport(1, 640, 0, 640, 720, None),
        ]
        ss.set_layout(custom)
        assert len(ss.viewports) == 2
        assert ss.viewports[0].width == 640

    def test_set_layout_updates_num_players(self):
        from pharos_engine.split_screen import SplitScreenManager, Viewport
        ss = SplitScreenManager(1280, 720, num_players=2)
        ss.set_layout([Viewport(0, 0, 0, 1280, 720, None)])
        assert ss.num_players == 1


class TestSplitScreenManagerViewportForPlayer:
    def test_viewport_for_player_found(self):
        from pharos_engine.split_screen import SplitScreenManager
        ss = SplitScreenManager(1280, 720, num_players=4)
        vp = ss.viewport_for_player(2)
        assert vp is not None
        assert vp.player_id == 2

    def test_viewport_for_player_not_found(self):
        from pharos_engine.split_screen import SplitScreenManager
        ss = SplitScreenManager(1280, 720, num_players=2)
        assert ss.viewport_for_player(99) is None
