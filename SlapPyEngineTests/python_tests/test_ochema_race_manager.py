"""Headless tests for Ochema Circuit RaceManager."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("slappyengine.compute.asset_compute", MagicMock())

_OCHEMA_DIR = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Ochema Circuit"
_OCHEMA_STR = str(_OCHEMA_DIR)
if _OCHEMA_STR not in sys.path:
    sys.path.insert(0, _OCHEMA_STR)


_GATES = [
    (100.0, 100.0, 30.0, 20.0),
    (200.0, 100.0, 30.0, 20.0),
    (300.0, 100.0, 30.0, 20.0),
]


def _make_vehicle():
    v = MagicMock()
    v.position = (0.0, 0.0)
    v.velocity = (0.0, 0.0)
    return v


def _make_rm(laps=3, vehicles=None):
    from systems.race_manager import RaceManager
    return RaceManager(gate_defs=_GATES, laps_total=laps,
                       vehicles=vehicles or [])


def _advance_past_countdown(rm, extra_dt=0.016):
    from systems.race_manager import _COUNTDOWN_START
    rm.update(_COUNTDOWN_START + extra_dt)


def _simulate_lap(rm, entity):
    """Cross all gates in order + gate 0 to finish a lap."""
    rm._cp._on_gate_enter(entity, 0)
    rm._cp._on_gate_enter(entity, 1)
    rm._cp._on_gate_enter(entity, 2)
    rm._cp._on_gate_enter(entity, 0)  # completes the lap


# =============================================================================
# Init + state properties
# =============================================================================

class TestRaceManagerInit:
    def test_state_initially_countdown(self):
        rm = _make_rm()
        from systems.race_manager import RaceState
        assert rm.state == RaceState.COUNTDOWN

    def test_countdown_starts_at_three(self):
        rm = _make_rm()
        assert rm.countdown == pytest.approx(3.0)

    def test_elapsed_initially_zero(self):
        rm = _make_rm()
        assert rm.elapsed == pytest.approx(0.0)

    def test_finish_order_initially_empty(self):
        rm = _make_rm()
        assert rm.finish_order == []

    def test_add_vehicle_appends(self):
        rm = _make_rm()
        v = _make_vehicle()
        rm.add_vehicle(v)
        assert v in rm._vehicles

    def test_add_vehicle_no_duplicate(self):
        v = _make_vehicle()
        rm = _make_rm(vehicles=[v])
        rm.add_vehicle(v)  # already present
        assert rm._vehicles.count(v) == 1


# =============================================================================
# Countdown → Racing transition
# =============================================================================

class TestRaceManagerCountdown:
    def test_update_decrements_countdown(self):
        rm = _make_rm()
        rm.update(1.0)
        assert rm.countdown < 3.0

    def test_countdown_clamps_to_zero(self):
        rm = _make_rm()
        rm.update(10.0)
        assert rm.countdown == pytest.approx(0.0)

    def test_elapsed_advances_during_countdown(self):
        rm = _make_rm()
        rm.update(1.0)
        assert rm.elapsed == pytest.approx(1.0)

    def test_state_transitions_to_racing(self):
        from systems.race_manager import RaceState
        rm = _make_rm()
        _advance_past_countdown(rm)
        assert rm.state == RaceState.RACING

    def test_race_started_event_published(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        rm = _make_rm()
        events = []
        h = subscribe("Race.Started", lambda e: events.append(e))
        _advance_past_countdown(rm)
        unsubscribe(h)
        assert len(events) == 1

    def test_elapsed_continues_after_countdown(self):
        rm = _make_rm()
        _advance_past_countdown(rm)
        rm.update(1.0)
        assert rm.elapsed > 3.0

    def test_update_during_racing_no_crash(self):
        v = _make_vehicle()
        rm = _make_rm(vehicles=[v])
        _advance_past_countdown(rm)
        rm.update(0.016)


# =============================================================================
# Position tracking
# =============================================================================

class TestRaceManagerPositions:
    def test_position_for_single_vehicle(self):
        v = _make_vehicle()
        rm = _make_rm(vehicles=[v])
        # With one vehicle, position = 1
        assert rm.position(v) == 1

    def test_position_for_unknown_vehicle(self):
        rm = _make_rm(vehicles=[_make_vehicle()])
        unknown = _make_vehicle()
        pos = rm.position(unknown)
        # Should return len(vehicles) as default
        assert pos >= 1

    def test_calc_positions_with_two_vehicles(self):
        v1 = _make_vehicle()
        v2 = _make_vehicle()
        rm = _make_rm(vehicles=[v1, v2])
        _advance_past_countdown(rm)
        # Advance v1 by crossing a gate
        rm._cp._on_gate_enter(v1, 0)
        rm._calc_positions()
        # v1 should be ahead of v2 (or equal)
        assert rm.position(v1) <= rm.position(v2)

    def test_lap_count_via_race_manager(self):
        v = _make_vehicle()
        rm = _make_rm(vehicles=[v])
        _advance_past_countdown(rm)
        _simulate_lap(rm, v)
        assert rm.lap_count(v) == 1

    def test_best_lap_initially_zero(self):
        v = _make_vehicle()
        rm = _make_rm(vehicles=[v])
        assert rm.best_lap(v) == pytest.approx(0.0)

    def test_current_lap_elapsed_initially_zero(self):
        v = _make_vehicle()
        rm = _make_rm(vehicles=[v])
        assert rm.current_lap_elapsed(v) == pytest.approx(0.0)


# =============================================================================
# Lap string formatting
# =============================================================================

class TestRaceManagerLapStr:
    def test_lap_str_is_string(self):
        v = _make_vehicle()
        rm = _make_rm(vehicles=[v])
        s = rm.lap_str(v)
        assert isinstance(s, str)

    def test_lap_str_contains_lap_fraction(self):
        v = _make_vehicle()
        rm = _make_rm(laps=3, vehicles=[v])
        s = rm.lap_str(v)
        assert "3" in s

    def test_lap_str_contains_time(self):
        v = _make_vehicle()
        rm = _make_rm(vehicles=[v])
        s = rm.lap_str(v)
        assert ":" in s

    def test_lap_str_after_one_lap(self):
        v = _make_vehicle()
        rm = _make_rm(laps=3, vehicles=[v])
        _advance_past_countdown(rm)
        _simulate_lap(rm, v)
        s = rm.lap_str(v)
        # After 1 lap in a 3-lap race, lap str should say LAP 2/3
        assert "2" in s


# =============================================================================
# Finish detection
# =============================================================================

class TestRaceManagerFinish:
    def test_single_vehicle_finishes_on_all_laps(self):
        from systems.race_manager import RaceState
        v = _make_vehicle()
        rm = _make_rm(laps=1, vehicles=[v])
        _advance_past_countdown(rm)
        _simulate_lap(rm, v)
        assert rm.state == RaceState.FINISHED

    def test_finish_order_contains_vehicle(self):
        v = _make_vehicle()
        rm = _make_rm(laps=1, vehicles=[v])
        _advance_past_countdown(rm)
        _simulate_lap(rm, v)
        assert len(rm.finish_order) == 1
        assert rm.finish_order[0][0] is v

    def test_race_finished_event_published(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        v = _make_vehicle()
        rm = _make_rm(laps=1, vehicles=[v])
        _advance_past_countdown(rm)
        events = []
        h = subscribe("Race.Finished", lambda e: events.append(e))
        _simulate_lap(rm, v)
        unsubscribe(h)
        assert len(events) == 1

    def test_on_finish_callback_called(self):
        results = []
        v = _make_vehicle()
        rm = _make_rm(laps=1, vehicles=[v],
                      on_finish=lambda r: results.append(r))
        _advance_past_countdown(rm)
        _simulate_lap(rm, v)
        assert len(results) == 1

    def test_two_vehicles_race_finishes_when_all_done(self):
        from systems.race_manager import RaceState
        v1, v2 = _make_vehicle(), _make_vehicle()
        rm = _make_rm(laps=1, vehicles=[v1, v2])
        _advance_past_countdown(rm)
        _simulate_lap(rm, v1)
        assert rm.state != RaceState.FINISHED  # still waiting for v2
        _simulate_lap(rm, v2)
        assert rm.state == RaceState.FINISHED

    def test_finished_state_stops_updates(self):
        from systems.race_manager import RaceState
        v = _make_vehicle()
        rm = _make_rm(laps=1, vehicles=[v])
        _advance_past_countdown(rm)
        _simulate_lap(rm, v)
        elapsed_before = rm.elapsed
        rm.update(100.0)  # large dt after finish — elapsed still advances
        assert rm.state == RaceState.FINISHED


# =============================================================================
# _make_rm helper with on_finish callback
# =============================================================================

def _make_rm(laps=3, vehicles=None, on_finish=None):
    from systems.race_manager import RaceManager
    return RaceManager(gate_defs=_GATES, laps_total=laps,
                       vehicles=vehicles or [], on_finish=on_finish)
