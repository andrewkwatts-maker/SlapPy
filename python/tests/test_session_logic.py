"""Headless tests for GameSession pure-Python logic — enable_lockstep, callbacks, connected_player_ids, _prune_dead_peers."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock


def _make_session(local_player_id=0, tick_rate=30, timeout_ms=100.0):
    from slappyengine.net.session import GameSession, SessionConfig
    from slappyengine.net.room import RoomCode
    cfg = SessionConfig(tick_rate=tick_rate, timeout_ms=timeout_ms)
    room = RoomCode("TESTAB")
    return GameSession(room_code=room, local_player_id=local_player_id, cfg=cfg)


def _make_peer(peer_id, state_name="connected", alive=True):
    from slappyengine.net.peer import Peer, PeerState
    state = PeerState(state_name)
    peer = Peer(peer_id=peer_id, external_addr=("127.0.0.1", 10000 + peer_id), state=state)
    peer.is_alive = lambda timeout=5.0: alive
    return peer


# =============================================================================
# enable_lockstep
# =============================================================================

class TestEnableLockstep:
    def test_returns_lockstep_sync(self):
        from slappyengine.net.sync import LockstepSync
        session = _make_session()
        result = session.enable_lockstep(num_players=2)
        assert isinstance(result, LockstepSync)

    def test_sync_stored_on_session(self):
        session = _make_session()
        sync = session.enable_lockstep(num_players=2)
        assert session.sync is sync

    def test_num_players_explicit(self):
        session = _make_session()
        sync = session.enable_lockstep(num_players=4)
        assert sync.num_players == 4

    def test_num_players_auto_counts_peers_plus_one(self):
        session = _make_session(local_player_id=0)
        session.peers[1] = _make_peer(1)
        session.peers[2] = _make_peer(2)
        sync = session.enable_lockstep()
        assert sync.num_players == 3  # 2 peers + 1 local

    def test_auto_count_no_peers_is_one(self):
        session = _make_session()
        sync = session.enable_lockstep()
        assert sync.num_players == 1  # 0 peers + 1 local

    def test_tick_rate_propagated(self):
        session = _make_session(tick_rate=60)
        sync = session.enable_lockstep(num_players=2)
        assert sync.tick_rate == 60

    def test_timeout_ms_propagated(self):
        session = _make_session(timeout_ms=200.0)
        sync = session.enable_lockstep(num_players=2)
        assert sync.timeout_ms == pytest.approx(200.0)

    def test_local_player_id_propagated(self):
        session = _make_session(local_player_id=3)
        sync = session.enable_lockstep(num_players=4)
        assert sync.local_player_id == 3

    def test_sync_starts_at_tick_zero(self):
        session = _make_session()
        sync = session.enable_lockstep(num_players=2)
        assert sync.tick == 0

    def test_enable_twice_replaces_sync(self):
        session = _make_session()
        first = session.enable_lockstep(num_players=2)
        second = session.enable_lockstep(num_players=3)
        assert session.sync is second
        assert session.sync is not first


# =============================================================================
# on_player_joined / on_player_left
# =============================================================================

class TestCallbacks:
    def test_on_player_joined_registered(self):
        session = _make_session()
        cb = MagicMock()
        session.on_player_joined(cb)
        assert cb in session._on_player_joined

    def test_on_player_left_registered(self):
        session = _make_session()
        cb = MagicMock()
        session.on_player_left(cb)
        assert cb in session._on_player_left

    def test_on_player_joined_returns_fn(self):
        session = _make_session()
        def my_fn(pid): pass
        result = session.on_player_joined(my_fn)
        assert result is my_fn

    def test_on_player_left_returns_fn(self):
        session = _make_session()
        def my_fn(pid): pass
        result = session.on_player_left(my_fn)
        assert result is my_fn

    def test_multiple_join_callbacks_all_stored(self):
        session = _make_session()
        cb1, cb2, cb3 = MagicMock(), MagicMock(), MagicMock()
        session.on_player_joined(cb1)
        session.on_player_joined(cb2)
        session.on_player_joined(cb3)
        assert len(session._on_player_joined) == 3

    def test_multiple_left_callbacks_all_stored(self):
        session = _make_session()
        cb1, cb2 = MagicMock(), MagicMock()
        session.on_player_left(cb1)
        session.on_player_left(cb2)
        assert len(session._on_player_left) == 2

    def test_on_player_joined_as_decorator(self):
        session = _make_session()

        @session.on_player_joined
        def handle_join(pid):
            pass

        assert handle_join in session._on_player_joined

    def test_on_player_left_as_decorator(self):
        session = _make_session()

        @session.on_player_left
        def handle_leave(pid):
            pass

        assert handle_leave in session._on_player_left

    def test_joined_left_independent(self):
        session = _make_session()
        join_cb = MagicMock()
        left_cb = MagicMock()
        session.on_player_joined(join_cb)
        session.on_player_left(left_cb)
        assert join_cb not in session._on_player_left
        assert left_cb not in session._on_player_joined


# =============================================================================
# connected_player_ids
# =============================================================================

class TestConnectedPlayerIds:
    def test_empty_when_no_peers(self):
        session = _make_session()
        assert session.connected_player_ids == []

    def test_returns_list(self):
        session = _make_session()
        assert isinstance(session.connected_player_ids, list)

    def test_returns_connected_peer_ids(self):
        session = _make_session()
        session.peers[7] = _make_peer(7, "connected")
        session.peers[8] = _make_peer(8, "connected")
        ids = session.connected_player_ids
        assert 7 in ids
        assert 8 in ids

    def test_excludes_disconnected_peers(self):
        session = _make_session()
        session.peers[1] = _make_peer(1, "connected")
        session.peers[2] = _make_peer(2, "disconnected")
        ids = session.connected_player_ids
        assert 1 in ids
        assert 2 not in ids

    def test_excludes_connecting_peers(self):
        session = _make_session()
        session.peers[1] = _make_peer(1, "connecting")
        ids = session.connected_player_ids
        assert 1 not in ids

    def test_excludes_failed_peers(self):
        session = _make_session()
        session.peers[1] = _make_peer(1, "failed")
        ids = session.connected_player_ids
        assert 1 not in ids

    def test_excludes_hole_punching_peers(self):
        session = _make_session()
        session.peers[1] = _make_peer(1, "hole_punching")
        ids = session.connected_player_ids
        assert 1 not in ids

    def test_count_matches_connected_only(self):
        session = _make_session()
        session.peers[1] = _make_peer(1, "connected")
        session.peers[2] = _make_peer(2, "connected")
        session.peers[3] = _make_peer(3, "disconnected")
        assert len(session.connected_player_ids) == 2


# =============================================================================
# _prune_dead_peers
# =============================================================================

class TestPruneDeadPeers:
    def test_no_peers_no_crash(self):
        session = _make_session()
        session._prune_dead_peers()  # must not raise

    def test_removes_dead_peers(self):
        session = _make_session()
        session.peers[10] = _make_peer(10, "connected", alive=False)
        session._prune_dead_peers()
        assert 10 not in session.peers

    def test_keeps_alive_peers(self):
        session = _make_session()
        session.peers[11] = _make_peer(11, "connected", alive=True)
        session._prune_dead_peers()
        assert 11 in session.peers

    def test_calls_on_player_left_for_dead(self):
        session = _make_session()
        session.peers[10] = _make_peer(10, "connected", alive=False)
        cb = MagicMock()
        session.on_player_left(cb)
        session._prune_dead_peers()
        cb.assert_called_once_with(10)

    def test_does_not_call_left_for_alive(self):
        session = _make_session()
        session.peers[5] = _make_peer(5, "connected", alive=True)
        cb = MagicMock()
        session.on_player_left(cb)
        session._prune_dead_peers()
        cb.assert_not_called()

    def test_multiple_dead_peers_all_removed(self):
        session = _make_session()
        session.peers[1] = _make_peer(1, "connected", alive=False)
        session.peers[2] = _make_peer(2, "connected", alive=False)
        session.peers[3] = _make_peer(3, "connected", alive=True)
        session._prune_dead_peers()
        assert 1 not in session.peers
        assert 2 not in session.peers
        assert 3 in session.peers

    def test_multiple_callbacks_all_called_for_dead_peer(self):
        session = _make_session()
        session.peers[99] = _make_peer(99, "connected", alive=False)
        cb1, cb2 = MagicMock(), MagicMock()
        session.on_player_left(cb1)
        session.on_player_left(cb2)
        session._prune_dead_peers()
        cb1.assert_called_once_with(99)
        cb2.assert_called_once_with(99)

    def test_mix_alive_and_dead(self):
        session = _make_session()
        for i in range(1, 6):
            alive = (i % 2 == 0)
            session.peers[i] = _make_peer(i, "connected", alive=alive)
        session._prune_dead_peers()
        for i in range(1, 6):
            if i % 2 == 0:
                assert i in session.peers
            else:
                assert i not in session.peers

    def test_prune_twice_is_idempotent(self):
        session = _make_session()
        session.peers[10] = _make_peer(10, "connected", alive=False)
        session._prune_dead_peers()
        session._prune_dead_peers()  # second call must not raise
        assert 10 not in session.peers

    def test_no_join_callbacks_called_during_prune(self):
        session = _make_session()
        session.peers[10] = _make_peer(10, "connected", alive=False)
        join_cb = MagicMock()
        session.on_player_joined(join_cb)
        session._prune_dead_peers()
        join_cb.assert_not_called()
