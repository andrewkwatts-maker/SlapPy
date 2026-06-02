"""Headless tests for Ochema Circuit GhostSystem and CheckpointSystem."""
from __future__ import annotations
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock
import pytest

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("slappyengine.compute.asset_compute", MagicMock())

_OCHEMA_DIR = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Ochema Circuit"
_OCHEMA_STR = str(_OCHEMA_DIR)
if _OCHEMA_STR not in sys.path:
    sys.path.insert(0, _OCHEMA_STR)


# =============================================================================
# GhostSystem
# =============================================================================

def _make_vehicle(pos=(100.0, 200.0), rotation=0.0):
    v = MagicMock()
    v.position = pos
    v.rotation = rotation
    return v


class TestGhostSystemInit:
    def _gs(self, save_dir=None):
        from systems.ghost_system import GhostSystem
        return GhostSystem(save_dir=save_dir)

    def test_init_no_crash(self):
        gs = self._gs()
        gs.teardown()

    def test_has_ghost_false_initially(self):
        gs = self._gs()
        assert gs.has_ghost is False
        gs.teardown()

    def test_ghost_entity_none_initially(self):
        gs = self._gs()
        assert gs.ghost_entity is None
        gs.teardown()

    def test_recording_false_initially(self):
        gs = self._gs()
        assert gs._recording is False
        gs.teardown()

    def test_teardown_clears_handles(self):
        gs = self._gs()
        gs.teardown()
        assert len(gs._handles) == 0


class TestGhostSystemRecording:
    def _gs(self, vehicle=None):
        from systems.ghost_system import GhostSystem
        return GhostSystem(tracked_vehicle=vehicle)

    def test_race_started_starts_recording(self):
        from slappyengine.event_bus import publish
        gs = self._gs()
        publish("Race.Started", publisher=None)
        assert gs._recording is True
        gs.teardown()

    def test_race_finished_stops_recording(self):
        from slappyengine.event_bus import publish
        gs = self._gs()
        publish("Race.Started", publisher=None)
        publish("Race.Finished", publisher=None)
        assert gs._recording is False
        gs.teardown()

    def test_record_tick_no_vehicle_no_crash(self):
        gs = self._gs(vehicle=None)
        gs._recording = True
        gs.record_tick(0.016)
        gs.teardown()

    def test_record_tick_with_vehicle_captures_frames(self):
        v = _make_vehicle()
        gs = self._gs(vehicle=v)
        gs._recording = True
        # Force sample immediately by setting _last_sample in the past
        gs._last_sample = time.perf_counter() - 1.0
        gs.record_tick(0.016)
        assert len(gs._frames) >= 1
        gs.teardown()

    def test_record_tick_not_recording_no_frames(self):
        v = _make_vehicle()
        gs = self._gs(vehicle=v)
        gs._recording = False
        gs._last_sample = time.perf_counter() - 1.0
        gs.record_tick(0.016)
        assert len(gs._frames) == 0
        gs.teardown()

    def test_frames_store_position(self):
        v = _make_vehicle(pos=(42.0, 77.0))
        gs = self._gs(vehicle=v)
        gs._recording = True
        gs._last_sample = time.perf_counter() - 1.0
        gs.record_tick(0.016)
        if gs._frames:
            assert gs._frames[0].x == pytest.approx(42.0)
            assert gs._frames[0].y == pytest.approx(77.0)
        gs.teardown()


class TestGhostSystemBestLap:
    def _gs(self):
        from systems.ghost_system import GhostSystem
        return GhostSystem()

    def test_best_lap_event_saves_frames(self):
        from slappyengine.event_bus import publish
        from systems.ghost_system import GhostFrame
        gs = self._gs()
        gs._frames = [GhostFrame(t=0.0, x=1.0, y=2.0, rotation=0.0)]
        publish("Race.BestLap", publisher=None, lap_time=60.0)
        assert gs.has_ghost is True
        gs.teardown()

    def test_best_lap_only_saves_faster_lap(self):
        from slappyengine.event_bus import publish
        from systems.ghost_system import GhostFrame
        gs = self._gs()
        gs._best_lap_time = 50.0
        gs._frames = [GhostFrame(t=0.0, x=0.0, y=0.0, rotation=0.0)]
        # Slower lap — should NOT replace best
        publish("Race.BestLap", publisher=None, lap_time=55.0)
        assert gs._best_lap_time == pytest.approx(50.0)
        gs.teardown()

    def test_best_lap_updates_when_faster(self):
        from slappyengine.event_bus import publish
        from systems.ghost_system import GhostFrame
        gs = self._gs()
        gs._best_lap_time = 100.0
        gs._frames = [GhostFrame(t=0.0, x=0.0, y=0.0, rotation=0.0)]
        publish("Race.BestLap", publisher=None, lap_time=45.0)
        assert gs._best_lap_time == pytest.approx(45.0)
        gs.teardown()


class TestGhostSystemPlayback:
    def _gs_with_ghost(self):
        from systems.ghost_system import GhostSystem, GhostFrame
        gs = GhostSystem()
        gs._best_frames = [
            GhostFrame(t=0.0, x=10.0, y=20.0, rotation=0.0),
            GhostFrame(t=0.5, x=15.0, y=20.0, rotation=10.0),
            GhostFrame(t=1.0, x=20.0, y=20.0, rotation=20.0),
        ]
        gs._best_lap_time = 1.0
        return gs

    def test_playback_tick_returns_none_when_not_playing(self):
        gs = self._gs_with_ghost()
        result = gs.playback_tick(0.016)
        assert result is None
        gs.teardown()

    def test_start_playback_sets_playing(self):
        gs = self._gs_with_ghost()
        gs._start_playback()
        assert gs._playback is True
        gs.teardown()

    def test_playback_tick_returns_tuple_when_active(self):
        gs = self._gs_with_ghost()
        gs._start_playback()
        result = gs.playback_tick(0.016)
        assert result is not None
        assert len(result) == 3
        gs.teardown()

    def test_playback_tick_positions_are_floats(self):
        gs = self._gs_with_ghost()
        gs._start_playback()
        result = gs.playback_tick(0.016)
        if result is not None:
            x, y, rot = result
            assert isinstance(x, float)
            assert isinstance(y, float)
        gs.teardown()


class TestGhostSystemPersistence:
    def test_save_and_load(self, tmp_path):
        from systems.ghost_system import GhostSystem, GhostFrame
        gs1 = GhostSystem(save_dir=str(tmp_path))
        gs1._best_frames = [GhostFrame(t=0.0, x=5.0, y=6.0, rotation=1.0)]
        gs1._best_lap_time = 42.5
        gs1._save()
        gs1.teardown()

        gs2 = GhostSystem(save_dir=str(tmp_path))
        assert gs2.has_ghost is True
        assert gs2._best_lap_time == pytest.approx(42.5)
        gs2.teardown()

    def test_load_missing_no_crash(self, tmp_path):
        from systems.ghost_system import GhostSystem
        gs = GhostSystem(save_dir=str(tmp_path / "no_dir"))
        gs.teardown()


# =============================================================================
# CheckpointSystem
# =============================================================================

def _three_gate_cs(laps=3, on_lap=None, on_finish=None):
    from systems.checkpoint_system import CheckpointSystem
    gates = [
        (100.0, 100.0, 30.0, 20.0),
        (200.0, 100.0, 30.0, 20.0),
        (300.0, 100.0, 30.0, 20.0),
    ]
    return CheckpointSystem(gate_defs=gates, laps_total=laps,
                            on_lap=on_lap, on_finish=on_finish)


def _simulate_lap(cs, entity):
    """Cross all 3 gates in order, then gate 0 again to complete a lap."""
    cs._on_gate_enter(entity, 0)
    cs._on_gate_enter(entity, 1)
    cs._on_gate_enter(entity, 2)
    # All gates crossed — now gate 0 completes the lap
    cs._on_gate_enter(entity, 0)


class TestCheckpointSystemInit:
    def test_init_no_crash(self):
        cs = _three_gate_cs()
        cs.teardown()

    def test_volumes_created(self):
        cs = _three_gate_cs()
        assert len(cs._volumes) == 3
        cs.teardown()

    def test_update_empty_no_crash(self):
        cs = _three_gate_cs()
        cs.update(0.016, [])
        cs.teardown()


class TestCheckpointSystemRegister:
    def test_register_adds_state(self):
        cs = _three_gate_cs()
        e = MagicMock()
        cs.register(e)
        assert id(e) in cs._state
        cs.teardown()

    def test_lap_count_unregistered_zero(self):
        cs = _three_gate_cs()
        e = MagicMock()
        assert cs.lap_count(e) == 0
        cs.teardown()

    def test_start_race_no_crash(self):
        cs = _three_gate_cs()
        e = MagicMock()
        cs.register(e)
        cs.start_race()
        cs.teardown()

    def test_gates_crossed_initially_zero(self):
        cs = _three_gate_cs()
        e = MagicMock()
        cs.register(e)
        assert cs.gates_crossed(e) == 0
        cs.teardown()

    def test_progress_unregistered_zero(self):
        cs = _three_gate_cs()
        e = MagicMock()
        assert cs.progress(e) == pytest.approx(0.0)
        cs.teardown()


class TestCheckpointSystemGateCrossing:
    def test_crossing_gate_0_first(self):
        cs = _three_gate_cs()
        e = MagicMock()
        cs.register(e)
        cs._on_gate_enter(e, 0)
        assert cs.gates_crossed(e) == 1
        cs.teardown()

    def test_out_of_order_gate_ignored(self):
        cs = _three_gate_cs()
        e = MagicMock()
        cs.register(e)
        cs._on_gate_enter(e, 2)  # skip gate 0 and 1
        assert cs.gates_crossed(e) == 0
        cs.teardown()

    def test_gate_crossing_publishes_event(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        cs = _three_gate_cs()
        e = MagicMock()
        cs.register(e)
        events = []
        h = subscribe("Race.CheckpointCrossed", lambda evt: events.append(evt))
        cs._on_gate_enter(e, 0)
        unsubscribe(h)
        assert len(events) == 1
        cs.teardown()

    def test_complete_lap_increments_count(self):
        cs = _three_gate_cs()
        e = MagicMock()
        cs.register(e)
        cs.start_race()
        _simulate_lap(cs, e)
        assert cs.lap_count(e) == 1
        cs.teardown()

    def test_complete_lap_publishes_lap_complete(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        cs = _three_gate_cs()
        e = MagicMock()
        cs.register(e)
        cs.start_race()
        events = []
        h = subscribe("Race.LapComplete", lambda evt: events.append(evt))
        _simulate_lap(cs, e)
        unsubscribe(h)
        assert len(events) == 1
        cs.teardown()

    def test_finish_after_all_laps(self):
        cs = _three_gate_cs(laps=2)
        e = MagicMock()
        cs.register(e)
        cs.start_race()
        _simulate_lap(cs, e)
        _simulate_lap(cs, e)
        assert cs.is_finished(e) is True
        cs.teardown()

    def test_not_finished_before_all_laps(self):
        cs = _three_gate_cs(laps=3)
        e = MagicMock()
        cs.register(e)
        cs.start_race()
        _simulate_lap(cs, e)
        assert cs.is_finished(e) is False
        cs.teardown()

    def test_on_lap_callback_called(self):
        called = []
        cs = _three_gate_cs(laps=3, on_lap=lambda e, n, t: called.append(n))
        e = MagicMock()
        cs.register(e)
        cs.start_race()
        _simulate_lap(cs, e)
        assert called == [1]
        cs.teardown()

    def test_on_finish_callback_called(self):
        finished = []
        cs = _three_gate_cs(laps=1, on_finish=lambda e, n, t: finished.append(n))
        e = MagicMock()
        cs.register(e)
        cs.start_race()
        _simulate_lap(cs, e)
        assert len(finished) == 1
        cs.teardown()

    def test_progress_increases_with_gates(self):
        cs = _three_gate_cs()
        e = MagicMock()
        cs.register(e)
        cs.start_race()
        p0 = cs.progress(e)
        cs._on_gate_enter(e, 0)
        p1 = cs.progress(e)
        assert p1 > p0
        cs.teardown()


class TestCheckpointSystemVehicleDestroyed:
    def test_destroyed_publishes_dnf(self):
        from slappyengine.event_bus import subscribe, unsubscribe, publish
        cs = _three_gate_cs()
        e = MagicMock()
        cs.register(e)
        events = []
        h = subscribe("Race.DNF", lambda evt: events.append(evt))
        publish("Vehicle.Destroyed", publisher=e)
        unsubscribe(h)
        assert len(events) == 1
        cs.teardown()

    def test_destroyed_marks_finished(self):
        from slappyengine.event_bus import publish
        cs = _three_gate_cs()
        e = MagicMock()
        cs.register(e)
        publish("Vehicle.Destroyed", publisher=e)
        assert cs.is_finished(e) is True
        cs.teardown()
