"""Headless tests for net modules (Peer, RoomCode, InputFrame, LockstepSync)
and CodeModePanel module-level helpers.

Covers:
- slappyengine.net.peer         (PeerState, Peer)
- slappyengine.net.room         (RoomCode)
- slappyengine.net.sync         (InputFrame, LockstepSync)
- slappyengine.ui.editor.code_mode_panel (_fmt_age, _now_str, CodeModePanel)

DPG guard: installed so code_mode_panel doesn't segfault on import.
"""
from __future__ import annotations
import sys
import time
import unittest.mock

# ---------------------------------------------------------------------------
# DPG mock — prevents segfault from dearpygui without a viewport context.
# ---------------------------------------------------------------------------
_DPG_MOCK = unittest.mock.MagicMock()
_DPG_MOCK.does_item_exist.return_value = False
if 'dearpygui.dearpygui' not in sys.modules:
    sys.modules['dearpygui'] = unittest.mock.MagicMock()
    sys.modules['dearpygui.dearpygui'] = _DPG_MOCK
else:
    sys.modules['dearpygui.dearpygui'] = _DPG_MOCK


# ---------------------------------------------------------------------------
# net/peer.py — PeerState enum
# ---------------------------------------------------------------------------

class TestPeerState:
    def test_connecting_value(self):
        from slappyengine.net.peer import PeerState
        assert PeerState.CONNECTING.value == "connecting"

    def test_hole_punching_value(self):
        from slappyengine.net.peer import PeerState
        assert PeerState.HOLE_PUNCHING.value == "hole_punching"

    def test_connected_value(self):
        from slappyengine.net.peer import PeerState
        assert PeerState.CONNECTED.value == "connected"

    def test_disconnected_value(self):
        from slappyengine.net.peer import PeerState
        assert PeerState.DISCONNECTED.value == "disconnected"

    def test_failed_value(self):
        from slappyengine.net.peer import PeerState
        assert PeerState.FAILED.value == "failed"

    def test_five_states(self):
        from slappyengine.net.peer import PeerState
        assert len(list(PeerState)) == 5


class TestPeer:
    def _make_peer(self, peer_id=1, addr=("127.0.0.1", 5000)):
        from slappyengine.net.peer import Peer
        return Peer(peer_id=peer_id, external_addr=addr)

    def test_instantiates(self):
        p = self._make_peer()
        assert p is not None

    def test_peer_id_stored(self):
        p = self._make_peer(peer_id=42)
        assert p.peer_id == 42

    def test_external_addr_stored(self):
        p = self._make_peer(addr=("10.0.0.1", 9000))
        assert p.external_addr == ("10.0.0.1", 9000)

    def test_local_addr_none_by_default(self):
        p = self._make_peer()
        assert p.local_addr is None

    def test_default_state_connecting(self):
        from slappyengine.net.peer import PeerState
        p = self._make_peer()
        assert p.state == PeerState.CONNECTING

    def test_default_rtt_ms_zero(self):
        p = self._make_peer()
        assert p.rtt_ms == 0.0

    def test_is_alive_fresh(self):
        p = self._make_peer()
        assert p.is_alive(timeout=5.0) is True

    def test_is_alive_long_timeout(self):
        p = self._make_peer()
        assert p.is_alive(timeout=9999.0) is True

    def test_mark_seen_updates_last_seen(self):
        p = self._make_peer()
        old = p.last_seen
        time.sleep(0.02)
        p.mark_seen()
        assert p.last_seen > old

    def test_send_seq_starts_zero(self):
        p = self._make_peer()
        assert p._send_seq == 0

    def test_recv_seq_starts_neg_one(self):
        p = self._make_peer()
        assert p._recv_seq == -1


# ---------------------------------------------------------------------------
# net/room.py — RoomCode
# ---------------------------------------------------------------------------

class TestRoomCode:
    def test_instantiates(self):
        from slappyengine.net.room import RoomCode
        rc = RoomCode("ABCDEF")
        assert rc is not None

    def test_code_stored(self):
        from slappyengine.net.room import RoomCode
        rc = RoomCode("ABCDEF")
        assert rc.code == "ABCDEF"

    def test_lowercase_uppercased(self):
        from slappyengine.net.room import RoomCode
        rc = RoomCode("abcdef")
        assert rc.code == "ABCDEF"

    def test_whitespace_stripped(self):
        from slappyengine.net.room import RoomCode
        rc = RoomCode("  ABCDEF  ")
        assert rc.code == "ABCDEF"

    def test_str_returns_code(self):
        from slappyengine.net.room import RoomCode
        rc = RoomCode("X7K2MQ")
        assert str(rc) == "X7K2MQ"

    def test_repr_contains_code(self):
        from slappyengine.net.room import RoomCode
        rc = RoomCode("X7K2MQ")
        assert "X7K2MQ" in repr(rc)

    def test_generate_returns_room_code(self):
        from slappyengine.net.room import RoomCode
        rc = RoomCode.generate()
        assert isinstance(rc, RoomCode)

    def test_generate_six_chars(self):
        from slappyengine.net.room import RoomCode
        rc = RoomCode.generate()
        assert len(rc.code) == 6

    def test_generate_uses_safe_chars(self):
        from slappyengine.net.room import RoomCode
        for _ in range(10):
            rc = RoomCode.generate()
            for ch in rc.code:
                assert ch in RoomCode._SAFE

    def test_dht_key_is_bytes(self):
        from slappyengine.net.room import RoomCode
        rc = RoomCode("ABCDEF")
        assert isinstance(rc.dht_key, bytes)

    def test_dht_key_length_20(self):
        from slappyengine.net.room import RoomCode
        rc = RoomCode("ABCDEF")
        assert len(rc.dht_key) == 20

    def test_dht_key_deterministic(self):
        from slappyengine.net.room import RoomCode
        rc1 = RoomCode("ABCDEF")
        rc2 = RoomCode("ABCDEF")
        assert rc1.dht_key == rc2.dht_key

    def test_different_codes_different_keys(self):
        from slappyengine.net.room import RoomCode
        rc1 = RoomCode("ABCDEF")
        rc2 = RoomCode("GHJKLM")
        assert rc1.dht_key != rc2.dht_key

    def test_safe_chars_excludes_confusables(self):
        from slappyengine.net.room import RoomCode
        assert "O" not in RoomCode._SAFE
        assert "0" not in RoomCode._SAFE
        assert "I" not in RoomCode._SAFE
        assert "1" not in RoomCode._SAFE

    def test_generate_multiple_unique(self):
        from slappyengine.net.room import RoomCode
        codes = {RoomCode.generate().code for _ in range(50)}
        # Very unlikely to collide with 50 out of 32^6 = ~1B possibilities
        assert len(codes) >= 40


# ---------------------------------------------------------------------------
# net/sync.py — InputFrame
# ---------------------------------------------------------------------------

class TestInputFrame:
    def _make_frame(self, tick=0, player_id=0):
        from slappyengine.net.sync import InputFrame
        return InputFrame(
            tick=tick,
            player_id=player_id,
            actions={"fire": True, "jump": False},
            axes={"move_x": 0.5, "move_y": -0.3},
        )

    def test_instantiates(self):
        f = self._make_frame()
        assert f is not None

    def test_tick_stored(self):
        f = self._make_frame(tick=42)
        assert f.tick == 42

    def test_player_id_stored(self):
        f = self._make_frame(player_id=3)
        assert f.player_id == 3

    def test_actions_stored(self):
        f = self._make_frame()
        assert f.actions["fire"] is True
        assert f.actions["jump"] is False

    def test_axes_stored(self):
        f = self._make_frame()
        assert abs(f.axes["move_x"] - 0.5) < 1e-9

    def test_to_bytes_returns_bytes(self):
        f = self._make_frame()
        result = f.to_bytes()
        assert isinstance(result, bytes)

    def test_to_bytes_nonempty(self):
        f = self._make_frame()
        assert len(f.to_bytes()) > 2

    def test_roundtrip(self):
        from slappyengine.net.sync import InputFrame
        original = self._make_frame(tick=7, player_id=2)
        data = original.to_bytes()
        recovered = InputFrame.from_bytes(data)
        assert recovered.tick == 7
        assert recovered.player_id == 2
        assert recovered.actions["fire"] is True
        assert recovered.actions["jump"] is False

    def test_roundtrip_axes(self):
        from slappyengine.net.sync import InputFrame
        original = self._make_frame()
        data = original.to_bytes()
        recovered = InputFrame.from_bytes(data)
        assert abs(recovered.axes["move_x"] - 0.5) < 1e-3

    def test_empty_actions_roundtrip(self):
        from slappyengine.net.sync import InputFrame
        f = InputFrame(tick=0, player_id=0, actions={}, axes={})
        data = f.to_bytes()
        recovered = InputFrame.from_bytes(data)
        assert recovered.actions == {}
        assert recovered.axes == {}

    def test_header_encodes_length(self):
        import struct
        f = self._make_frame()
        data = f.to_bytes()
        length_from_header = struct.unpack("!H", data[:2])[0]
        assert length_from_header == len(data) - 2


# ---------------------------------------------------------------------------
# net/sync.py — LockstepSync (pure-Python init and receive_frame)
# ---------------------------------------------------------------------------

class TestLockstepSync:
    def test_instantiates(self):
        from slappyengine.net.sync import LockstepSync
        s = LockstepSync(local_player_id=0, num_players=2)
        assert s is not None

    def test_local_player_id(self):
        from slappyengine.net.sync import LockstepSync
        s = LockstepSync(local_player_id=1, num_players=4)
        assert s.local_player_id == 1

    def test_num_players(self):
        from slappyengine.net.sync import LockstepSync
        s = LockstepSync(local_player_id=0, num_players=4)
        assert s.num_players == 4

    def test_default_tick_rate(self):
        from slappyengine.net.sync import LockstepSync
        s = LockstepSync(local_player_id=0, num_players=2)
        assert s.tick_rate == 30

    def test_custom_tick_rate(self):
        from slappyengine.net.sync import LockstepSync
        s = LockstepSync(local_player_id=0, num_players=2, tick_rate=60)
        assert s.tick_rate == 60

    def test_default_timeout_ms(self):
        from slappyengine.net.sync import LockstepSync
        s = LockstepSync(local_player_id=0, num_players=2)
        assert s.timeout_ms == 100.0

    def test_initial_tick_zero(self):
        from slappyengine.net.sync import LockstepSync
        s = LockstepSync(local_player_id=0, num_players=2)
        assert s.tick == 0

    def test_pending_empty(self):
        from slappyengine.net.sync import LockstepSync
        s = LockstepSync(local_player_id=0, num_players=2)
        assert s._pending == {}

    def test_last_frames_empty(self):
        from slappyengine.net.sync import LockstepSync
        s = LockstepSync(local_player_id=0, num_players=2)
        assert s._last_frames == {}

    def test_receive_frame_stores_in_pending(self):
        from slappyengine.net.sync import LockstepSync, InputFrame
        s = LockstepSync(local_player_id=0, num_players=2)
        f = InputFrame(tick=0, player_id=1, actions={}, axes={})
        s.receive_frame(f)
        assert 1 in s._pending.get(0, {})

    def test_receive_frame_updates_last_frames(self):
        from slappyengine.net.sync import LockstepSync, InputFrame
        s = LockstepSync(local_player_id=0, num_players=2)
        f = InputFrame(tick=5, player_id=1, actions={"fire": True}, axes={})
        s.receive_frame(f)
        assert s._last_frames[1] is f

    def test_receive_multiple_frames_different_ticks(self):
        from slappyengine.net.sync import LockstepSync, InputFrame
        s = LockstepSync(local_player_id=0, num_players=2)
        for tick in range(3):
            f = InputFrame(tick=tick, player_id=1, actions={}, axes={})
            s.receive_frame(f)
        assert len(s._pending) == 3

    def test_max_prediction_ticks(self):
        from slappyengine.net.sync import LockstepSync
        s = LockstepSync(local_player_id=0, num_players=2, max_prediction_ticks=4)
        assert s.max_prediction_ticks == 4


# ---------------------------------------------------------------------------
# CodeModePanel module helpers: _fmt_age, _now_str
# ---------------------------------------------------------------------------

class TestFmtAge:
    def test_zero_ts_returns_never(self):
        from slappyengine.ui.editor.code_mode_panel import _fmt_age
        assert _fmt_age(0.0) == "never"

    def test_recent_ts_seconds(self):
        from slappyengine.ui.editor.code_mode_panel import _fmt_age
        ts = time.monotonic() - 5
        result = _fmt_age(ts)
        assert result.endswith("s ago")
        assert result[0].isdigit()

    def test_old_ts_minutes(self):
        from slappyengine.ui.editor.code_mode_panel import _fmt_age
        ts = time.monotonic() - 120
        result = _fmt_age(ts)
        assert "m ago" in result

    def test_just_under_minute_shows_seconds(self):
        from slappyengine.ui.editor.code_mode_panel import _fmt_age
        ts = time.monotonic() - 59
        result = _fmt_age(ts)
        assert "s ago" in result

    def test_just_over_minute_shows_minutes(self):
        from slappyengine.ui.editor.code_mode_panel import _fmt_age
        ts = time.monotonic() - 61
        result = _fmt_age(ts)
        assert "m ago" in result


class TestNowStr:
    def test_returns_string(self):
        from slappyengine.ui.editor.code_mode_panel import _now_str
        result = _now_str()
        assert isinstance(result, str)

    def test_format_hh_mm_ss(self):
        from slappyengine.ui.editor.code_mode_panel import _now_str
        result = _now_str()
        parts = result.split(":")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_hours_in_range(self):
        from slappyengine.ui.editor.code_mode_panel import _now_str
        result = _now_str()
        hours = int(result.split(":")[0])
        assert 0 <= hours <= 23

    def test_minutes_in_range(self):
        from slappyengine.ui.editor.code_mode_panel import _now_str
        result = _now_str()
        mins = int(result.split(":")[1])
        assert 0 <= mins <= 59

    def test_seconds_in_range(self):
        from slappyengine.ui.editor.code_mode_panel import _now_str
        result = _now_str()
        secs = int(result.split(":")[2])
        assert 0 <= secs <= 59


# ---------------------------------------------------------------------------
# CodeModePanel — __init__ and data-model methods (AI mocked)
# ---------------------------------------------------------------------------

class TestCodeModePanelInit:
    def test_instantiates(self):
        from slappyengine.ui.editor.code_mode_panel import CodeModePanel
        p = CodeModePanel(engine=None)
        assert p is not None

    def test_prompt_text_empty(self):
        from slappyengine.ui.editor.code_mode_panel import CodeModePanel
        p = CodeModePanel(engine=None)
        assert p._prompt_text == ""

    def test_code_text_empty(self):
        from slappyengine.ui.editor.code_mode_panel import CodeModePanel
        p = CodeModePanel(engine=None)
        assert p._code_text == ""

    def test_prompt_mtime_zero(self):
        from slappyengine.ui.editor.code_mode_panel import CodeModePanel
        p = CodeModePanel(engine=None)
        assert p._prompt_mtime == 0.0

    def test_code_mtime_zero(self):
        from slappyengine.ui.editor.code_mode_panel import CodeModePanel
        p = CodeModePanel(engine=None)
        assert p._code_mtime == 0.0

    def test_ai_busy_false(self):
        from slappyengine.ui.editor.code_mode_panel import CodeModePanel
        p = CodeModePanel(engine=None)
        assert p._ai_busy is False

    def test_script_path_none(self):
        from slappyengine.ui.editor.code_mode_panel import CodeModePanel
        p = CodeModePanel(engine=None)
        assert p._script_path is None

    def test_watcher_none(self):
        from slappyengine.ui.editor.code_mode_panel import CodeModePanel
        p = CodeModePanel(engine=None)
        assert p._watcher is None

    def test_status_is_string(self):
        from slappyengine.ui.editor.code_mode_panel import CodeModePanel
        p = CodeModePanel(engine=None)
        assert isinstance(p._status, str)
        assert len(p._status) > 0

    def test_engine_stored(self):
        from slappyengine.ui.editor.code_mode_panel import CodeModePanel
        p = CodeModePanel(engine=None)
        assert p._engine is None


class TestCodeModePanelCallbacks:
    def test_on_prompt_edited_updates_text(self):
        from slappyengine.ui.editor.code_mode_panel import CodeModePanel
        p = CodeModePanel(engine=None)
        p._on_prompt_edited(None, "hello world")
        assert p._prompt_text == "hello world"

    def test_on_prompt_edited_updates_mtime(self):
        from slappyengine.ui.editor.code_mode_panel import CodeModePanel
        p = CodeModePanel(engine=None)
        before = time.monotonic()
        p._on_prompt_edited(None, "hello")
        assert p._prompt_mtime >= before

    def test_on_code_edited_updates_text(self):
        from slappyengine.ui.editor.code_mode_panel import CodeModePanel
        p = CodeModePanel(engine=None)
        p._on_code_edited(None, "def foo(): pass")
        assert p._code_text == "def foo(): pass"

    def test_on_code_edited_updates_mtime(self):
        from slappyengine.ui.editor.code_mode_panel import CodeModePanel
        p = CodeModePanel(engine=None)
        before = time.monotonic()
        p._on_code_edited(None, "x = 1")
        assert p._code_mtime >= before

    def test_set_status_updates_status(self):
        from slappyengine.ui.editor.code_mode_panel import CodeModePanel
        p = CodeModePanel(engine=None)
        p._set_status("Test message")
        assert p._status == "Test message"

    def test_toggle_auto_sync_no_crash_without_watcher(self):
        from slappyengine.ui.editor.code_mode_panel import CodeModePanel
        p = CodeModePanel(engine=None)
        p._toggle_auto_sync(None, True)  # should not raise

    def test_sync_prompt_to_code_no_crash_without_llm(self):
        from slappyengine.ui.editor.code_mode_panel import CodeModePanel
        p = CodeModePanel(engine=None)
        p._sync_prompt_to_code()  # llm is None → returns immediately

    def test_sync_code_to_prompt_no_crash_without_llm(self):
        from slappyengine.ui.editor.code_mode_panel import CodeModePanel
        p = CodeModePanel(engine=None)
        p._sync_code_to_prompt()  # llm is None → returns immediately

    def test_prompt_after_code_mtime_ordering(self):
        from slappyengine.ui.editor.code_mode_panel import CodeModePanel
        p = CodeModePanel(engine=None)
        p._on_code_edited(None, "code")
        time.sleep(0.01)
        p._on_prompt_edited(None, "prompt")
        assert p._prompt_mtime > p._code_mtime
