"""Engine tests for compute/library.py (ComputeLibrary), net/peer.py (Peer/PeerState),
and cli.py helpers (_find_project_file). All headless — no GPU required.
"""
from __future__ import annotations
import pytest
import numpy as np


# ---------------------------------------------------------------------------
# ComputeLibrary — reduce
# ---------------------------------------------------------------------------

class TestComputeLibraryReduce:
    def test_importable(self):
        from pharos_engine.compute.library import ComputeLibrary
        assert ComputeLibrary is not None

    def test_reduce_max(self):
        from pharos_engine.compute.library import ComputeLibrary
        data = np.array([1.0, 5.0, 3.0])
        assert ComputeLibrary.reduce(data, "max") == pytest.approx(5.0)

    def test_reduce_min(self):
        from pharos_engine.compute.library import ComputeLibrary
        data = np.array([1.0, 5.0, 3.0])
        assert ComputeLibrary.reduce(data, "min") == pytest.approx(1.0)

    def test_reduce_sum(self):
        from pharos_engine.compute.library import ComputeLibrary
        data = np.array([1.0, 2.0, 3.0, 4.0])
        assert ComputeLibrary.reduce(data, "sum") == pytest.approx(10.0)

    def test_reduce_mean(self):
        from pharos_engine.compute.library import ComputeLibrary
        data = np.array([0.0, 2.0, 4.0])
        assert ComputeLibrary.reduce(data, "mean") == pytest.approx(2.0)

    def test_reduce_std(self):
        from pharos_engine.compute.library import ComputeLibrary
        data = np.array([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
        assert ComputeLibrary.reduce(data, "std") == pytest.approx(2.0)

    def test_reduce_empty_returns_zero(self):
        from pharos_engine.compute.library import ComputeLibrary
        assert ComputeLibrary.reduce(np.array([]), "max") == pytest.approx(0.0)

    def test_reduce_2d_array(self):
        from pharos_engine.compute.library import ComputeLibrary
        data = np.array([[1.0, 2.0], [3.0, 4.0]])
        assert ComputeLibrary.reduce(data, "sum") == pytest.approx(10.0)

    def test_reduce_unknown_op_raises(self):
        from pharos_engine.compute.library import ComputeLibrary
        with pytest.raises(ValueError, match="Unknown op"):
            ComputeLibrary.reduce(np.array([1.0]), "banana")

    def test_reduce_single_element(self):
        from pharos_engine.compute.library import ComputeLibrary
        data = np.array([42.0])
        assert ComputeLibrary.reduce(data, "max") == pytest.approx(42.0)
        assert ComputeLibrary.reduce(data, "min") == pytest.approx(42.0)
        assert ComputeLibrary.reduce(data, "sum") == pytest.approx(42.0)
        assert ComputeLibrary.reduce(data, "mean") == pytest.approx(42.0)


# ---------------------------------------------------------------------------
# ComputeLibrary — convex_hull
# ---------------------------------------------------------------------------

class TestComputeLibraryConvexHull:
    def test_square_hull_4_points(self):
        from pharos_engine.compute.library import ComputeLibrary
        pts = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
        hull = ComputeLibrary.convex_hull(pts)
        assert hull.shape[1] == 2
        assert len(hull) >= 3  # at least a triangle

    def test_hull_with_interior_point(self):
        from pharos_engine.compute.library import ComputeLibrary
        pts = np.array([[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [1.0, 1.0]])
        hull = ComputeLibrary.convex_hull(pts)
        # Interior point should not be in the hull
        assert len(hull) == 4

    def test_hull_returns_float32(self):
        from pharos_engine.compute.library import ComputeLibrary
        pts = np.array([[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]])
        hull = ComputeLibrary.convex_hull(pts)
        assert hull.dtype == np.float32

    def test_hull_fewer_than_3_points_returns_copy(self):
        from pharos_engine.compute.library import ComputeLibrary
        pts = np.array([[0.0, 0.0], [1.0, 1.0]])
        hull = ComputeLibrary.convex_hull(pts)
        assert len(hull) == 2

    def test_hull_wrong_shape_raises(self):
        from pharos_engine.compute.library import ComputeLibrary
        with pytest.raises(ValueError):
            ComputeLibrary.convex_hull(np.array([1.0, 2.0, 3.0]))


# ---------------------------------------------------------------------------
# ComputeLibrary — reduce_async
# ---------------------------------------------------------------------------

class TestComputeLibraryReduceAsync:
    def setup_method(self):
        from pharos_engine.event_bus import global_bus
        global_bus.clear()

    def teardown_method(self):
        from pharos_engine.event_bus import global_bus
        global_bus.clear()

    def test_returns_scalar(self):
        from pharos_engine.compute.library import ComputeLibrary
        data = np.array([1.0, 2.0, 3.0])
        result = ComputeLibrary.reduce_async(data, "max")
        assert result == pytest.approx(3.0)

    def test_publishes_to_event_when_subscriber(self):
        from pharos_engine.compute.library import ComputeLibrary
        from pharos_engine.event_bus import subscribe, unsubscribe
        received = []
        h = subscribe("Compute.Test.Max", lambda e: received.append(e))
        data = np.array([1.0, 5.0, 3.0])
        ComputeLibrary.reduce_async(data, "max", event_name="Compute.Test.Max")
        unsubscribe(h)
        assert len(received) >= 1

    def test_no_event_without_subscriber(self):
        from pharos_engine.compute.library import ComputeLibrary
        # No crash when no subscribers
        data = np.array([1.0, 2.0])
        result = ComputeLibrary.reduce_async(data, "max", event_name="Orphan.Event")
        assert result == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# net/peer — Peer + PeerState
# ---------------------------------------------------------------------------

class TestPeerState:
    def test_states_exist(self):
        from pharos_engine.net.peer import PeerState
        assert PeerState.CONNECTING is not None
        assert PeerState.HOLE_PUNCHING is not None
        assert PeerState.CONNECTED is not None
        assert PeerState.DISCONNECTED is not None
        assert PeerState.FAILED is not None

    def test_states_have_string_values(self):
        from pharos_engine.net.peer import PeerState
        assert PeerState.CONNECTED.value == "connected"
        assert PeerState.DISCONNECTED.value == "disconnected"


class TestPeer:
    def test_instantiates(self):
        from pharos_engine.net.peer import Peer
        p = Peer(peer_id=1, external_addr=("1.2.3.4", 5000))
        assert p is not None

    def test_peer_id_stored(self):
        from pharos_engine.net.peer import Peer
        p = Peer(peer_id=42, external_addr=("10.0.0.1", 9000))
        assert p.peer_id == 42

    def test_external_addr_stored(self):
        from pharos_engine.net.peer import Peer
        p = Peer(peer_id=1, external_addr=("192.168.1.1", 4321))
        assert p.external_addr == ("192.168.1.1", 4321)

    def test_default_local_addr_none(self):
        from pharos_engine.net.peer import Peer
        p = Peer(peer_id=1, external_addr=("1.2.3.4", 100))
        assert p.local_addr is None

    def test_default_state_connecting(self):
        from pharos_engine.net.peer import Peer, PeerState
        p = Peer(peer_id=1, external_addr=("1.2.3.4", 100))
        assert p.state == PeerState.CONNECTING

    def test_default_rtt_zero(self):
        from pharos_engine.net.peer import Peer
        p = Peer(peer_id=1, external_addr=("1.2.3.4", 100))
        assert p.rtt_ms == pytest.approx(0.0)

    def test_is_alive_true_after_creation(self):
        from pharos_engine.net.peer import Peer
        p = Peer(peer_id=1, external_addr=("1.2.3.4", 100))
        assert p.is_alive(timeout=5.0) is True

    def test_is_alive_false_with_zero_timeout(self):
        from pharos_engine.net.peer import Peer
        import time
        p = Peer(peer_id=1, external_addr=("1.2.3.4", 100))
        time.sleep(0.01)
        assert p.is_alive(timeout=0.0) is False

    def test_mark_seen_refreshes_last_seen(self):
        from pharos_engine.net.peer import Peer
        import time
        p = Peer(peer_id=1, external_addr=("1.2.3.4", 100))
        time.sleep(0.01)
        p.mark_seen()
        assert p.is_alive(timeout=1.0) is True

    def test_state_mutable(self):
        from pharos_engine.net.peer import Peer, PeerState
        p = Peer(peer_id=1, external_addr=("1.2.3.4", 100))
        p.state = PeerState.CONNECTED
        assert p.state == PeerState.CONNECTED

    def test_rtt_mutable(self):
        from pharos_engine.net.peer import Peer
        p = Peer(peer_id=1, external_addr=("1.2.3.4", 100))
        p.rtt_ms = 45.5
        assert p.rtt_ms == pytest.approx(45.5)

    def test_local_addr_can_be_set(self):
        from pharos_engine.net.peer import Peer
        p = Peer(peer_id=1, external_addr=("1.2.3.4", 100),
                 local_addr=("192.168.1.5", 5000))
        assert p.local_addr == ("192.168.1.5", 5000)


# ---------------------------------------------------------------------------
# cli.py — _find_project_file helper
# ---------------------------------------------------------------------------

class TestCLIFindProjectFile:
    def test_finds_project_file_in_dir(self, tmp_path):
        from pharos_engine.cli import _find_project_file
        proj_file = tmp_path / "project.slap_proj"
        proj_file.write_text("name: test")
        result = _find_project_file(str(tmp_path))
        assert result.name == "project.slap_proj"

    def test_accepts_direct_slap_proj_path(self, tmp_path):
        from pharos_engine.cli import _find_project_file
        proj_file = tmp_path / "project.slap_proj"
        proj_file.write_text("name: test")
        result = _find_project_file(str(proj_file))
        assert result == proj_file

    def test_missing_file_calls_die(self, tmp_path):
        from pharos_engine.cli import _find_project_file
        with pytest.raises(SystemExit):
            _find_project_file(str(tmp_path))
