"""Headless tests for LockstepSync.tick_async — no sockets, uses asyncio.run()."""
from __future__ import annotations
import asyncio
import pytest


async def _noop_send(data: bytes) -> None:
    pass


def _run(coro):
    return asyncio.run(coro)


def _make_sync(num_players=2, local_player_id=0, timeout_ms=50.0):
    from slappyengine.net.sync import LockstepSync
    return LockstepSync(
        local_player_id=local_player_id,
        num_players=num_players,
        timeout_ms=timeout_ms,
    )


def _frame(tick, player_id, actions=None, axes=None):
    from slappyengine.net.sync import InputFrame
    return InputFrame(tick=tick, player_id=player_id,
                      actions=actions or {}, axes=axes or {})


# =============================================================================
# Single-player (num_players=1) — returns immediately
# =============================================================================

class TestTickAsyncSinglePlayer:
    def test_returns_list(self):
        ls = _make_sync(num_players=1)
        result = _run(ls.tick_async(_frame(0, 0), _noop_send))
        assert isinstance(result, list)

    def test_returns_one_frame(self):
        ls = _make_sync(num_players=1)
        result = _run(ls.tick_async(_frame(0, 0), _noop_send))
        assert len(result) == 1

    def test_local_frame_in_result(self):
        ls = _make_sync(num_players=1)
        f = _frame(0, 0, actions={"fire": True})
        result = _run(ls.tick_async(f, _noop_send))
        assert result[0].player_id == 0
        assert result[0].actions == {"fire": True}

    def test_tick_advances_after_call(self):
        ls = _make_sync(num_players=1)
        _run(ls.tick_async(_frame(0, 0), _noop_send))
        assert ls.tick == 1

    def test_two_calls_advance_tick_twice(self):
        ls = _make_sync(num_players=1)
        _run(ls.tick_async(_frame(0, 0), _noop_send))
        _run(ls.tick_async(_frame(1, 0), _noop_send))
        assert ls.tick == 2

    def test_send_fn_called(self):
        ls = _make_sync(num_players=1)
        sent = []

        async def capture_send(data):
            sent.append(data)

        _run(ls.tick_async(_frame(0, 0), capture_send))
        assert len(sent) == 1
        assert isinstance(sent[0], bytes)

    def test_send_fn_receives_frame_bytes(self):
        ls = _make_sync(num_players=1)
        sent = []

        async def capture_send(data):
            sent.append(data)

        f = _frame(0, 0, actions={"boost": True})
        _run(ls.tick_async(f, capture_send))
        # Reconstruct and verify
        from slappyengine.net.sync import InputFrame
        decoded = InputFrame.from_bytes(sent[0])
        assert decoded.actions["boost"] is True


# =============================================================================
# Two players — remote frame injected before timeout
# =============================================================================

class TestTickAsyncTwoPlayersArriving:
    def _make_injecting_send(self, ls, remote_frame):
        """send_fn that injects remote_frame immediately after being called."""
        async def injecting_send(data):
            ls.receive_frame(remote_frame)
        return injecting_send

    def test_returns_two_frames(self):
        ls = _make_sync(num_players=2)
        remote = _frame(0, 1, actions={"jump": True})
        result = _run(ls.tick_async(_frame(0, 0), self._make_injecting_send(ls, remote)))
        assert len(result) == 2

    def test_both_player_ids_present(self):
        ls = _make_sync(num_players=2)
        remote = _frame(0, 1)
        result = _run(ls.tick_async(_frame(0, 0), self._make_injecting_send(ls, remote)))
        pids = {f.player_id for f in result}
        assert 0 in pids
        assert 1 in pids

    def test_remote_actions_preserved(self):
        ls = _make_sync(num_players=2)
        remote = _frame(0, 1, actions={"special": True})
        result = _run(ls.tick_async(_frame(0, 0), self._make_injecting_send(ls, remote)))
        p1 = next(f for f in result if f.player_id == 1)
        assert p1.actions.get("special") is True

    def test_local_actions_preserved(self):
        ls = _make_sync(num_players=2)
        remote = _frame(0, 1)
        result = _run(ls.tick_async(
            _frame(0, 0, actions={"dash": True}),
            self._make_injecting_send(ls, remote)
        ))
        p0 = next(f for f in result if f.player_id == 0)
        assert p0.actions.get("dash") is True

    def test_tick_advances(self):
        ls = _make_sync(num_players=2)
        remote = _frame(0, 1)
        _run(ls.tick_async(_frame(0, 0), self._make_injecting_send(ls, remote)))
        assert ls.tick == 1


# =============================================================================
# Timeout — missing remote frame → prediction
# =============================================================================

class TestTickAsyncTimeout:
    def test_returns_list_on_timeout(self):
        ls = _make_sync(num_players=2, timeout_ms=1.0)
        result = _run(ls.tick_async(_frame(0, 0), _noop_send))
        assert isinstance(result, list)

    def test_returns_num_players_items_on_timeout(self):
        ls = _make_sync(num_players=2, timeout_ms=1.0)
        result = _run(ls.tick_async(_frame(0, 0), _noop_send))
        assert len(result) == 2

    def test_local_frame_included_after_timeout(self):
        ls = _make_sync(num_players=2, timeout_ms=1.0)
        result = _run(ls.tick_async(_frame(0, 0), _noop_send))
        pids = {f.player_id for f in result}
        assert 0 in pids

    def test_missing_peer_predicted_empty_actions(self):
        ls = _make_sync(num_players=2, timeout_ms=1.0)
        result = _run(ls.tick_async(_frame(0, 0), _noop_send))
        p1 = next(f for f in result if f.player_id == 1)
        assert p1.actions == {}

    def test_missing_peer_predicted_with_last_frame(self):
        ls = _make_sync(num_players=2, timeout_ms=1.0)
        ls._last_frames[1] = _frame(-1, 1, actions={"boost": True}, axes={"x": 0.5})
        result = _run(ls.tick_async(_frame(0, 0), _noop_send))
        p1 = next(f for f in result if f.player_id == 1)
        assert p1.actions.get("boost") is True

    def test_predicted_axes_from_last_frame(self):
        ls = _make_sync(num_players=2, timeout_ms=1.0)
        ls._last_frames[1] = _frame(-1, 1, axes={"steer": -0.7})
        result = _run(ls.tick_async(_frame(0, 0), _noop_send))
        p1 = next(f for f in result if f.player_id == 1)
        assert p1.axes.get("steer") == pytest.approx(-0.7)

    def test_predicted_frame_has_correct_tick(self):
        ls = _make_sync(num_players=2, timeout_ms=1.0)
        ls._last_frames[1] = _frame(-1, 1, actions={"fire": True})
        result = _run(ls.tick_async(_frame(0, 0), _noop_send))
        p1 = next(f for f in result if f.player_id == 1)
        assert p1.tick == 0  # current tick, not -1

    def test_tick_increments_even_after_timeout(self):
        ls = _make_sync(num_players=2, timeout_ms=1.0)
        _run(ls.tick_async(_frame(0, 0), _noop_send))
        assert ls.tick == 1

    def test_three_players_two_missing_predicts_both(self):
        ls = _make_sync(num_players=3, timeout_ms=1.0)
        result = _run(ls.tick_async(_frame(0, 0), _noop_send))
        assert len(result) == 3
        pids = {f.player_id for f in result}
        assert {0, 1, 2} == pids


# =============================================================================
# InputFrame.to_bytes / from_bytes roundtrip
# =============================================================================

class TestInputFrameSerialization:
    def test_to_bytes_returns_bytes(self):
        from slappyengine.net.sync import InputFrame
        f = InputFrame(tick=5, player_id=2, actions={"fire": True}, axes={"x": 0.5})
        assert isinstance(f.to_bytes(), bytes)

    def test_roundtrip_tick(self):
        from slappyengine.net.sync import InputFrame
        f = InputFrame(tick=42, player_id=0, actions={}, axes={})
        recovered = InputFrame.from_bytes(f.to_bytes())
        assert recovered.tick == 42

    def test_roundtrip_player_id(self):
        from slappyengine.net.sync import InputFrame
        f = InputFrame(tick=0, player_id=7, actions={}, axes={})
        recovered = InputFrame.from_bytes(f.to_bytes())
        assert recovered.player_id == 7

    def test_roundtrip_actions(self):
        from slappyengine.net.sync import InputFrame
        f = InputFrame(tick=0, player_id=0, actions={"fire": True, "jump": False}, axes={})
        recovered = InputFrame.from_bytes(f.to_bytes())
        assert recovered.actions["fire"] is True
        assert recovered.actions["jump"] is False

    def test_roundtrip_axes(self):
        from slappyengine.net.sync import InputFrame
        f = InputFrame(tick=0, player_id=0, actions={}, axes={"x": 0.5, "y": -0.25})
        recovered = InputFrame.from_bytes(f.to_bytes())
        assert recovered.axes["x"] == pytest.approx(0.5)
        assert recovered.axes["y"] == pytest.approx(-0.25)

    def test_roundtrip_empty_dicts(self):
        from slappyengine.net.sync import InputFrame
        f = InputFrame(tick=0, player_id=0, actions={}, axes={})
        recovered = InputFrame.from_bytes(f.to_bytes())
        assert recovered.actions == {}
        assert recovered.axes == {}

    def test_axes_rounded_to_3_decimals(self):
        from slappyengine.net.sync import InputFrame
        f = InputFrame(tick=0, player_id=0, actions={}, axes={"v": 0.123456789})
        recovered = InputFrame.from_bytes(f.to_bytes())
        assert abs(recovered.axes["v"] - 0.123) < 0.001
