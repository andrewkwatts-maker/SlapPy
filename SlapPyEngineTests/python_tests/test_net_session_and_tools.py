"""Headless tests for net/session.py and tools/gen_placeholders.py helpers.

Covers:
- slappyengine.net.session   (SessionConfig, GameSession.__init__ state)
- slappyengine.tools.gen_placeholders (_star_points, _new pure-Python helpers)
- slappyengine.ext.*         (shim re-export smoke tests)
"""
from __future__ import annotations
import math


# ---------------------------------------------------------------------------
# net/session.py — SessionConfig
# ---------------------------------------------------------------------------

class TestSessionConfig:
    def test_instantiates(self):
        from slappyengine.net.session import SessionConfig
        cfg = SessionConfig()
        assert cfg is not None

    def test_default_tick_rate(self):
        from slappyengine.net.session import SessionConfig
        cfg = SessionConfig()
        assert cfg.tick_rate == 30

    def test_default_timeout_ms(self):
        from slappyengine.net.session import SessionConfig
        cfg = SessionConfig()
        assert cfg.timeout_ms == 100.0

    def test_default_max_players(self):
        from slappyengine.net.session import SessionConfig
        cfg = SessionConfig()
        assert cfg.max_players == 8

    def test_default_use_lan_discovery(self):
        from slappyengine.net.session import SessionConfig
        cfg = SessionConfig()
        assert cfg.use_lan_discovery is True

    def test_default_use_dht_discovery(self):
        from slappyengine.net.session import SessionConfig
        cfg = SessionConfig()
        assert cfg.use_dht_discovery is True

    def test_default_udp_port_zero(self):
        from slappyengine.net.session import SessionConfig
        cfg = SessionConfig()
        assert cfg.udp_port == 0

    def test_custom_tick_rate(self):
        from slappyengine.net.session import SessionConfig
        cfg = SessionConfig(tick_rate=60)
        assert cfg.tick_rate == 60

    def test_custom_max_players(self):
        from slappyengine.net.session import SessionConfig
        cfg = SessionConfig(max_players=4)
        assert cfg.max_players == 4

    def test_custom_udp_port(self):
        from slappyengine.net.session import SessionConfig
        cfg = SessionConfig(udp_port=5555)
        assert cfg.udp_port == 5555

    def test_custom_timeout(self):
        from slappyengine.net.session import SessionConfig
        cfg = SessionConfig(timeout_ms=200.0)
        assert cfg.timeout_ms == 200.0


class TestGameSessionInit:
    def _make_session(self):
        from slappyengine.net.session import GameSession, SessionConfig
        from slappyengine.net.room import RoomCode
        rc = RoomCode("ABCDEF")
        cfg = SessionConfig()
        return GameSession(room_code=rc, local_player_id=0, cfg=cfg)

    def test_instantiates(self):
        s = self._make_session()
        assert s is not None

    def test_room_code_stored(self):
        from slappyengine.net.room import RoomCode
        s = self._make_session()
        assert isinstance(s.room_code, RoomCode)

    def test_room_code_value(self):
        s = self._make_session()
        assert s.room_code.code == "ABCDEF"

    def test_local_player_id(self):
        s = self._make_session()
        assert s.local_player_id == 0

    def test_peers_empty(self):
        s = self._make_session()
        assert s.peers == {}

    def test_sync_none(self):
        s = self._make_session()
        assert s.sync is None

    def test_sock_none(self):
        s = self._make_session()
        assert s._sock is None

    def test_external_addr_none(self):
        s = self._make_session()
        assert s._external_addr is None

    def test_local_addr_none(self):
        s = self._make_session()
        assert s._local_addr is None

    def test_running_false(self):
        s = self._make_session()
        assert s._running is False

    def test_on_player_joined_empty(self):
        s = self._make_session()
        assert s._on_player_joined == []

    def test_on_player_left_empty(self):
        s = self._make_session()
        assert s._on_player_left == []

    def test_cfg_stored(self):
        from slappyengine.net.session import GameSession, SessionConfig
        from slappyengine.net.room import RoomCode
        cfg = SessionConfig(tick_rate=60)
        rc = RoomCode("XXXXXX")
        s = GameSession(room_code=rc, local_player_id=1, cfg=cfg)
        assert s.cfg.tick_rate == 60

    def test_different_player_id(self):
        from slappyengine.net.session import GameSession, SessionConfig
        from slappyengine.net.room import RoomCode
        rc = RoomCode("GHIJKL")
        cfg = SessionConfig()
        s = GameSession(room_code=rc, local_player_id=3, cfg=cfg)
        assert s.local_player_id == 3


# ---------------------------------------------------------------------------
# tools/gen_placeholders.py — _star_points (pure math)
# ---------------------------------------------------------------------------

class TestStarPoints:
    def test_five_point_star_has_10_vertices(self):
        from slappyengine.tools.gen_placeholders import _star_points
        verts = _star_points(50, 50, 20.0, 10.0, 5)
        assert len(verts) == 10  # points * 2

    def test_six_point_star_has_12_vertices(self):
        from slappyengine.tools.gen_placeholders import _star_points
        verts = _star_points(0, 0, 30.0, 15.0, 6)
        assert len(verts) == 12

    def test_vertices_are_tuples_of_floats(self):
        from slappyengine.tools.gen_placeholders import _star_points
        verts = _star_points(0, 0, 20.0, 10.0, 5)
        for v in verts:
            assert len(v) == 2
            assert isinstance(v[0], float)
            assert isinstance(v[1], float)

    def test_outer_vertices_at_correct_distance(self):
        from slappyengine.tools.gen_placeholders import _star_points
        cx, cy = 0, 0
        r_outer = 20.0
        r_inner = 10.0
        verts = _star_points(cx, cy, r_outer, r_inner, 5)
        # Even indices are outer vertices
        for i in range(0, len(verts), 2):
            x, y = verts[i]
            dist = math.sqrt((x - cx)**2 + (y - cy)**2)
            assert abs(dist - r_outer) < 1e-9

    def test_inner_vertices_at_correct_distance(self):
        from slappyengine.tools.gen_placeholders import _star_points
        cx, cy = 0, 0
        r_outer = 20.0
        r_inner = 10.0
        verts = _star_points(cx, cy, r_outer, r_inner, 5)
        # Odd indices are inner vertices
        for i in range(1, len(verts), 2):
            x, y = verts[i]
            dist = math.sqrt((x - cx)**2 + (y - cy)**2)
            assert abs(dist - r_inner) < 1e-9

    def test_center_offset(self):
        from slappyengine.tools.gen_placeholders import _star_points
        verts_origin = _star_points(0, 0, 20.0, 10.0, 4)
        verts_offset = _star_points(100, 200, 20.0, 10.0, 4)
        for (ox, oy), (tx, ty) in zip(verts_origin, verts_offset):
            assert abs((tx - 100) - ox) < 1e-9
            assert abs((ty - 200) - oy) < 1e-9

    def test_first_vertex_is_at_top_approximately(self):
        from slappyengine.tools.gen_placeholders import _star_points
        # First vertex uses angle = -pi/2, so it points upward
        verts = _star_points(0, 0, 20.0, 10.0, 5)
        x0, y0 = verts[0]
        # At angle -pi/2: x = r*cos(-pi/2) = 0, y = r*sin(-pi/2) = -r
        assert abs(x0) < 1e-9
        assert abs(y0 - (-20.0)) < 1e-9

    def test_three_point_star_has_6_vertices(self):
        from slappyengine.tools.gen_placeholders import _star_points
        verts = _star_points(0, 0, 30.0, 15.0, 3)
        assert len(verts) == 6


# ---------------------------------------------------------------------------
# tools/gen_placeholders.py — _new (PIL helper, pure creation)
# ---------------------------------------------------------------------------

class TestNewHelper:
    def test_returns_image_and_draw(self):
        from slappyengine.tools.gen_placeholders import _new
        from PIL import Image, ImageDraw
        img, draw = _new(10, 10)
        assert isinstance(img, Image.Image)
        assert isinstance(draw, ImageDraw.ImageDraw)

    def test_default_mode_rgba(self):
        from slappyengine.tools.gen_placeholders import _new
        img, _ = _new(4, 4)
        assert img.mode == "RGBA"

    def test_custom_mode_rgb(self):
        from slappyengine.tools.gen_placeholders import _new
        img, _ = _new(4, 4, mode="RGB")
        assert img.mode == "RGB"

    def test_dimensions_correct(self):
        from slappyengine.tools.gen_placeholders import _new
        img, _ = _new(32, 48)
        assert img.size == (32, 48)

    def test_default_background_transparent(self):
        from slappyengine.tools.gen_placeholders import _new
        img, _ = _new(2, 2)
        pixel = img.getpixel((0, 0))
        assert pixel[3] == 0  # alpha = 0

    def test_custom_background(self):
        from slappyengine.tools.gen_placeholders import _new
        img, _ = _new(2, 2, bg=(255, 0, 0, 255))
        pixel = img.getpixel((0, 0))
        assert pixel[0] == 255
        assert pixel[3] == 255


# ---------------------------------------------------------------------------
# ext/ shim smoke tests — import only, verify exported names present
# ---------------------------------------------------------------------------

class TestExtAngleSpriteShim:
    def test_angle_entry_importable(self):
        from slappyengine.ext.angle_sprite import AngleEntry
        assert AngleEntry is not None

    def test_angle_sprite_map_importable(self):
        from slappyengine.ext.angle_sprite import AngleSpriteMap
        assert AngleSpriteMap is not None

    def test_make_angle_map_importable(self):
        from slappyengine.ext.angle_sprite import make_angle_map_from_spritesheet
        assert callable(make_angle_map_from_spritesheet)


class TestExtFluidSimShim:
    def test_fluid_sim_config_importable(self):
        from slappyengine.ext.fluid_sim import FluidSimConfig
        assert FluidSimConfig is not None

    def test_global_fluid_sim_importable(self):
        from slappyengine.ext.fluid_sim import GlobalFluidSim
        assert GlobalFluidSim is not None

    def test_fog_config_importable(self):
        from slappyengine.ext.fluid_sim import fog_config
        assert callable(fog_config)

    def test_water_config_importable(self):
        from slappyengine.ext.fluid_sim import water_config
        assert callable(water_config)

    def test_smoke_config_importable(self):
        from slappyengine.ext.fluid_sim import smoke_config
        assert callable(smoke_config)


class TestExtLightingShim:
    def test_lighting_system_importable(self):
        from slappyengine.ext.lighting import LightingSystem
        assert LightingSystem is not None

    def test_point_light_importable(self):
        from slappyengine.ext.lighting import PointLight
        assert PointLight is not None

    def test_cone_light_importable(self):
        from slappyengine.ext.lighting import ConeLight
        assert ConeLight is not None

    def test_directional_light_importable(self):
        from slappyengine.ext.lighting import DirectionalLight
        assert DirectionalLight is not None

    def test_flash_light_importable(self):
        from slappyengine.ext.lighting import FlashLight
        assert FlashLight is not None


class TestExtSplitScreenShim:
    def test_viewport_importable(self):
        from slappyengine.ext.split_screen import Viewport
        assert Viewport is not None

    def test_split_screen_manager_importable(self):
        from slappyengine.ext.split_screen import SplitScreenManager
        assert SplitScreenManager is not None

    def test_viewport_is_same_as_canonical(self):
        from slappyengine.ext.split_screen import Viewport as ExtViewport
        from slappyengine.split_screen import Viewport as CanonicalViewport
        assert ExtViewport is CanonicalViewport

    def test_manager_is_same_as_canonical(self):
        from slappyengine.ext.split_screen import SplitScreenManager as Ext
        from slappyengine.split_screen import SplitScreenManager as Canonical
        assert Ext is Canonical
