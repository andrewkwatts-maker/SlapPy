"""Engine tests for net/ subpackage — SessionConfig, RoomCode, InputFrame, LockstepSync.
All headless — no network, no sockets, no servers required.
"""
from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# SessionConfig
# ---------------------------------------------------------------------------

class TestSessionConfig:
    def test_instantiates(self):
        from slappyengine.net.session import SessionConfig
        cfg = SessionConfig()
        assert cfg is not None

    def test_default_tick_rate(self):
        from slappyengine.net.session import SessionConfig
        assert SessionConfig().tick_rate == 30

    def test_default_timeout_ms(self):
        from slappyengine.net.session import SessionConfig
        assert SessionConfig().timeout_ms == pytest.approx(100.0)

    def test_default_max_players(self):
        from slappyengine.net.session import SessionConfig
        assert SessionConfig().max_players == 8

    def test_default_use_lan_discovery(self):
        from slappyengine.net.session import SessionConfig
        assert SessionConfig().use_lan_discovery is True

    def test_default_use_dht_discovery(self):
        from slappyengine.net.session import SessionConfig
        assert SessionConfig().use_dht_discovery is True

    def test_default_udp_port_zero(self):
        from slappyengine.net.session import SessionConfig
        assert SessionConfig().udp_port == 0

    def test_custom_values(self):
        from slappyengine.net.session import SessionConfig
        cfg = SessionConfig(tick_rate=60, max_players=4, udp_port=7000)
        assert cfg.tick_rate == 60
        assert cfg.max_players == 4
        assert cfg.udp_port == 7000


# ---------------------------------------------------------------------------
# RoomCode
# ---------------------------------------------------------------------------

class TestRoomCode:
    def test_generate_returns_roomcode(self):
        from slappyengine.net.room import RoomCode
        r = RoomCode.generate()
        assert r is not None

    def test_generate_length_6(self):
        from slappyengine.net.room import RoomCode
        r = RoomCode.generate()
        assert len(r.code) == 6

    def test_generate_chars_in_safe_set(self):
        from slappyengine.net.room import RoomCode
        r = RoomCode.generate()
        assert all(c in RoomCode._SAFE for c in r.code)

    def test_generate_unique(self):
        from slappyengine.net.room import RoomCode
        codes = {RoomCode.generate().code for _ in range(10)}
        assert len(codes) > 1   # very unlikely to collide 10 times

    def test_constructor_stores_code_uppercase(self):
        from slappyengine.net.room import RoomCode
        r = RoomCode("abcdef")
        assert r.code == "ABCDEF"

    def test_dht_key_is_bytes(self):
        from slappyengine.net.room import RoomCode
        r = RoomCode("ABCDEF")
        assert isinstance(r.dht_key, bytes)

    def test_dht_key_nonzero_length(self):
        from slappyengine.net.room import RoomCode
        r = RoomCode("ABCDEF")
        assert len(r.dht_key) > 0

    def test_same_code_same_dht_key(self):
        from slappyengine.net.room import RoomCode
        a = RoomCode("TESTXX")
        b = RoomCode("TESTXX")
        assert a.dht_key == b.dht_key

    def test_different_codes_different_keys(self):
        from slappyengine.net.room import RoomCode
        a = RoomCode("AAAAAA")
        b = RoomCode("BBBBBB")
        assert a.dht_key != b.dht_key

    def test_str_returns_code(self):
        from slappyengine.net.room import RoomCode
        r = RoomCode("XYZABC")
        assert str(r) == "XYZABC"

    def test_hash_consistent(self):
        from slappyengine.net.room import RoomCode
        r = RoomCode("HASH42")
        assert hash(r) == hash(r)


# ---------------------------------------------------------------------------
# InputFrame
# ---------------------------------------------------------------------------

class TestInputFrame:
    def test_instantiates(self):
        from slappyengine.net.sync import InputFrame
        frame = InputFrame(tick=0, player_id=0, actions={}, axes={})
        assert frame is not None

    def test_tick_stored(self):
        from slappyengine.net.sync import InputFrame
        frame = InputFrame(tick=42, player_id=0, actions={}, axes={})
        assert frame.tick == 42

    def test_player_id_stored(self):
        from slappyengine.net.sync import InputFrame
        frame = InputFrame(tick=0, player_id=3, actions={}, axes={})
        assert frame.player_id == 3

    def test_actions_stored(self):
        from slappyengine.net.sync import InputFrame
        actions = {"fire": True, "jump": False}
        frame = InputFrame(tick=0, player_id=0, actions=actions, axes={})
        assert frame.actions == actions

    def test_axes_stored(self):
        from slappyengine.net.sync import InputFrame
        axes = {"x": 0.5, "y": -0.3}
        frame = InputFrame(tick=0, player_id=0, actions={}, axes=axes)
        assert frame.axes == axes

    def test_timestamp_is_float(self):
        from slappyengine.net.sync import InputFrame
        frame = InputFrame(tick=0, player_id=0, actions={}, axes={})
        assert isinstance(frame.timestamp, float)

    def test_timestamp_positive(self):
        from slappyengine.net.sync import InputFrame
        frame = InputFrame(tick=0, player_id=0, actions={}, axes={})
        assert frame.timestamp > 0.0


# ---------------------------------------------------------------------------
# LockstepSync — init and pure-Python fields
# ---------------------------------------------------------------------------

class TestLockstepSyncInit:
    def test_instantiates(self):
        from slappyengine.net.sync import LockstepSync
        ls = LockstepSync(local_player_id=0, num_players=2)
        assert ls is not None

    def test_tick_starts_zero(self):
        from slappyengine.net.sync import LockstepSync
        ls = LockstepSync(local_player_id=0, num_players=2)
        assert ls.tick == 0

    def test_num_players_stored(self):
        from slappyengine.net.sync import LockstepSync
        ls = LockstepSync(local_player_id=0, num_players=4)
        assert ls.num_players == 4

    def test_receive_frame_no_crash(self):
        from slappyengine.net.sync import LockstepSync, InputFrame
        ls = LockstepSync(local_player_id=0, num_players=2)
        frame = InputFrame(tick=0, player_id=1, actions={}, axes={})
        ls.receive_frame(frame)

    def test_receive_frame_from_remote_player(self):
        from slappyengine.net.sync import LockstepSync, InputFrame
        ls = LockstepSync(local_player_id=0, num_players=2)
        frame = InputFrame(tick=0, player_id=1, actions={"boost": True}, axes={})
        ls.receive_frame(frame)   # should not raise


# ---------------------------------------------------------------------------
# GameSession — pure-Python init (no socket bind)
# ---------------------------------------------------------------------------

class TestGameSessionInit:
    def test_instantiates_without_network(self):
        from slappyengine.net.session import GameSession, SessionConfig
        from slappyengine.net.room import RoomCode
        cfg = SessionConfig()
        room = RoomCode("TESTAB")
        session = GameSession(room_code=room, local_player_id=0, cfg=cfg)
        assert session is not None

    def test_room_code_stored(self):
        from slappyengine.net.session import GameSession, SessionConfig
        from slappyengine.net.room import RoomCode
        room = RoomCode("MYROOM")
        session = GameSession(room_code=room, local_player_id=0, cfg=SessionConfig())
        assert session.room_code is room

    def test_local_player_id_stored(self):
        from slappyengine.net.session import GameSession, SessionConfig
        from slappyengine.net.room import RoomCode
        room = RoomCode("PLYR01")
        session = GameSession(room_code=room, local_player_id=2, cfg=SessionConfig())
        assert session.local_player_id == 2

    def test_peers_empty_initially(self):
        from slappyengine.net.session import GameSession, SessionConfig
        from slappyengine.net.room import RoomCode
        session = GameSession(
            room_code=RoomCode("NOPEERS"),
            local_player_id=0,
            cfg=SessionConfig()
        )
        assert session.peers == {}

    def test_not_running_initially(self):
        from slappyengine.net.session import GameSession, SessionConfig
        from slappyengine.net.room import RoomCode
        session = GameSession(
            room_code=RoomCode("NORUN01"),
            local_player_id=0,
            cfg=SessionConfig()
        )
        assert session._running is False
