"""Engine tests for net.RoomCode and net.sync.InputFrame — headless."""
from __future__ import annotations
import pytest


class TestRoomCode:
    def test_generate_six_chars(self):
        from pharos_engine.net.room import RoomCode
        code = RoomCode.generate()
        assert len(code.code) == 6

    def test_generate_uppercase(self):
        from pharos_engine.net.room import RoomCode
        code = RoomCode.generate()
        assert code.code == code.code.upper()

    def test_generate_safe_chars_only(self):
        from pharos_engine.net.room import RoomCode
        for _ in range(20):
            code = RoomCode.generate()
            for ch in code.code:
                assert ch in RoomCode._SAFE

    def test_construct_from_string(self):
        from pharos_engine.net.room import RoomCode
        code = RoomCode("X7K2MQ")
        assert code.code == "X7K2MQ"

    def test_construct_normalises_lowercase(self):
        from pharos_engine.net.room import RoomCode
        code = RoomCode("x7k2mq")
        assert code.code == "X7K2MQ"

    def test_dht_key_is_20_bytes(self):
        from pharos_engine.net.room import RoomCode
        code = RoomCode("ABCDEF")
        assert len(code.dht_key) == 20

    def test_dht_key_same_for_same_code(self):
        from pharos_engine.net.room import RoomCode
        a = RoomCode("TESTXX")
        b = RoomCode("TESTXX")
        assert a.dht_key == b.dht_key

    def test_dht_key_different_for_different_codes(self):
        from pharos_engine.net.room import RoomCode
        a = RoomCode("AAAAAA")
        b = RoomCode("BBBBBB")
        assert a.dht_key != b.dht_key

    def test_str_representation(self):
        from pharos_engine.net.room import RoomCode
        code = RoomCode("ZXCVBN")
        assert str(code) == "ZXCVBN"

    def test_repr_representation(self):
        from pharos_engine.net.room import RoomCode
        code = RoomCode("HELLO2")
        assert "HELLO2" in repr(code)


class TestInputFrame:
    def _make_frame(self):
        from pharos_engine.net.sync import InputFrame
        return InputFrame(
            tick=42,
            player_id=1,
            actions={"fire": True, "jump": False},
            axes={"move_x": 0.75, "move_y": -0.5},
        )

    def test_init_stores_fields(self):
        frame = self._make_frame()
        assert frame.tick == 42
        assert frame.player_id == 1
        assert frame.actions["fire"] is True
        assert frame.axes["move_x"] == pytest.approx(0.75)

    def test_to_bytes_returns_bytes(self):
        frame = self._make_frame()
        data = frame.to_bytes()
        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_from_bytes_roundtrip(self):
        from pharos_engine.net.sync import InputFrame
        frame = self._make_frame()
        data = frame.to_bytes()
        restored = InputFrame.from_bytes(data)
        assert restored.tick == frame.tick
        assert restored.player_id == frame.player_id
        assert restored.actions["fire"] is True
        assert restored.actions["jump"] is False
        assert restored.axes["move_x"] == pytest.approx(0.75, abs=0.01)
        assert restored.axes["move_y"] == pytest.approx(-0.5, abs=0.01)

    def test_empty_actions_roundtrip(self):
        from pharos_engine.net.sync import InputFrame
        frame = InputFrame(tick=0, player_id=0, actions={}, axes={})
        data = frame.to_bytes()
        restored = InputFrame.from_bytes(data)
        assert restored.actions == {}
        assert restored.axes == {}

    def test_timestamp_set_automatically(self):
        from pharos_engine.net.sync import InputFrame
        frame = InputFrame(tick=1, player_id=0, actions={}, axes={})
        assert frame.timestamp > 0.0


class TestLockstepSync:
    def test_init_stores_params(self):
        from pharos_engine.net.sync import LockstepSync
        ls = LockstepSync(local_player_id=0, num_players=2, tick_rate=30)
        assert ls.local_player_id == 0
        assert ls.num_players == 2
        assert ls.tick_rate == 30

    def test_initial_tick_zero(self):
        from pharos_engine.net.sync import LockstepSync
        ls = LockstepSync(0, 2)
        assert ls.tick == 0

    def test_receive_frame_stores_it(self):
        from pharos_engine.net.sync import LockstepSync, InputFrame
        ls = LockstepSync(0, 2)
        frame = InputFrame(tick=0, player_id=1, actions={}, axes={})
        ls.receive_frame(frame)
        assert 1 in ls._pending.get(0, {})

    def test_receive_frame_updates_last_known(self):
        from pharos_engine.net.sync import LockstepSync, InputFrame
        ls = LockstepSync(0, 2)
        frame = InputFrame(tick=0, player_id=1, actions={"a": True}, axes={})
        ls.receive_frame(frame)
        assert ls._last_frames.get(1) is frame
