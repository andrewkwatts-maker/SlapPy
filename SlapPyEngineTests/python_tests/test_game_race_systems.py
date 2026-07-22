"""Headless tests for Ochema Circuit game-side systems.

Covers:
  - LapTimer
  - AchievementSystem
  - SaveSystem
  - CheckpointSystem
  - RaceManager
"""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

# ── Mock heavy dependencies before any game imports ───────────────────────────
sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("pharos_engine.compute.asset_compute", MagicMock())

# ── Add game root to sys.path so game imports resolve ─────────────────────────
# H:\Github\SlapPyEngine\python\tests  → go up 4 levels to reach H:\
# then down into DaedalusSVN\Ochema Circuit
_GAME_ROOT = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Ochema Circuit"
_GAME_STR = str(_GAME_ROOT)
if _GAME_STR not in sys.path:
    sys.path.insert(0, _GAME_STR)


# =============================================================================
# LapTimer
# =============================================================================

class TestLapTimerInit:
    def _t(self):
        from systems.lap_timer import LapTimer
        return LapTimer()

    def test_initial_lap_count(self):
        assert self._t().lap_count == 0

    def test_initial_total_elapsed(self):
        assert self._t().total_elapsed == 0.0

    def test_initial_best_lap_zero(self):
        assert self._t().best_lap == 0.0

    def test_initial_lap_times_empty(self):
        assert self._t().lap_times == []

    def test_initial_current_lap_elapsed_zero(self):
        assert self._t().current_lap_elapsed == 0.0


class TestLapTimerUpdate:
    def _t(self):
        from systems.lap_timer import LapTimer
        return LapTimer()

    def test_update_increases_total(self):
        t = self._t()
        t.update(1.5)
        assert abs(t.total_elapsed - 1.5) < 1e-9

    def test_update_accumulates(self):
        t = self._t()
        t.update(1.0)
        t.update(0.5)
        assert abs(t.total_elapsed - 1.5) < 1e-9

    def test_current_lap_elapsed_before_start(self):
        t = self._t()
        t.update(2.0)
        assert abs(t.current_lap_elapsed - 2.0) < 1e-9

    def test_current_lap_elapsed_after_start(self):
        t = self._t()
        t.update(1.0)
        t.start()
        t.update(0.5)
        assert abs(t.current_lap_elapsed - 0.5) < 1e-9


class TestLapTimerRecordLap:
    def _t(self):
        from systems.lap_timer import LapTimer
        return LapTimer()

    def test_record_lap_increments_count(self):
        t = self._t()
        t.start()
        t.update(10.0)
        t.record_lap()
        assert t.lap_count == 1

    def test_record_lap_returns_duration(self):
        t = self._t()
        t.start()
        t.update(8.0)
        duration = t.record_lap()
        assert abs(duration - 8.0) < 1e-9

    def test_first_lap_sets_best(self):
        t = self._t()
        t.start()
        t.update(10.0)
        t.record_lap()
        assert abs(t.best_lap - 10.0) < 1e-9

    def test_faster_lap_updates_best(self):
        t = self._t()
        t.start()
        t.update(10.0)
        t.record_lap()
        t.update(7.0)
        t.record_lap()
        assert abs(t.best_lap - 7.0) < 1e-9

    def test_slower_lap_keeps_best(self):
        t = self._t()
        t.start()
        t.update(7.0)
        t.record_lap()
        t.update(12.0)
        t.record_lap()
        assert abs(t.best_lap - 7.0) < 1e-9

    def test_lap_times_appended(self):
        t = self._t()
        t.start()
        t.update(5.0)
        t.record_lap()
        t.update(6.0)
        t.record_lap()
        laps = t.lap_times
        assert len(laps) == 2
        assert abs(laps[0] - 5.0) < 1e-9
        assert abs(laps[1] - 6.0) < 1e-9

    def test_record_lap_resets_lap_start(self):
        t = self._t()
        t.start()
        t.update(10.0)
        t.record_lap()
        t.update(3.0)
        assert abs(t.current_lap_elapsed - 3.0) < 1e-9

    def test_lap_times_returns_copy(self):
        t = self._t()
        t.start()
        t.update(5.0)
        t.record_lap()
        laps1 = t.lap_times
        laps1.append(999.0)
        assert len(t.lap_times) == 1


# =============================================================================
# AchievementSystem
# =============================================================================

class TestAchievementSystemInit:
    def _a(self, td=None):
        from systems.achievement_system import AchievementSystem
        if td is None:
            td = tempfile.mkdtemp()
        return AchievementSystem(save_dir=td)

    def test_instantiates(self):
        assert self._a() is not None

    def test_catalog_not_empty(self):
        a = self._a()
        assert len(a.get_all()) > 0

    def test_achievements_have_names(self):
        a = self._a()
        for ach in a.get_all():
            assert ach.name != ""

    def test_none_unlocked_initially(self):
        td = tempfile.mkdtemp()
        a = self._a(td)
        assert all(not ach.unlocked for ach in a.get_all())

    def test_known_achievements_present(self):
        from systems.achievement_system import AchievementSystem
        keys = set(AchievementSystem.ACHIEVEMENTS.keys())
        assert "first_win" in keys
        assert "speed_demon" in keys
        assert "clean_lap" in keys

    def test_teardown_no_crash(self):
        a = self._a()
        a.teardown()


class TestAchievementSystemUnlock:
    def _a(self):
        from systems.achievement_system import AchievementSystem
        return AchievementSystem(save_dir=tempfile.mkdtemp())

    def test_unlock_sets_flag(self):
        a = self._a()
        a.unlock("first_win")
        ach = next(x for x in a.get_all() if x.id == "first_win")
        assert ach.unlocked is True

    def test_unlock_idempotent(self):
        a = self._a()
        a.unlock("first_win")
        a.unlock("first_win")
        unlocked = [x for x in a.get_all() if x.unlocked]
        assert len(unlocked) == 1

    def test_unlock_unknown_no_crash(self):
        a = self._a()
        a.unlock("nonexistent_achievement")  # should not raise

    def test_unlock_publishes_event(self):
        from pharos_engine.event_bus import subscribe, unsubscribe
        a = self._a()
        received = []
        h = subscribe("Achievement.Unlocked|speed_demon", lambda e: received.append(e))
        a.unlock("speed_demon")
        unsubscribe(h)
        assert len(received) == 1

    def test_unlock_sets_date(self):
        a = self._a()
        a.unlock("first_win")
        ach = next(x for x in a.get_all() if x.id == "first_win")
        assert ach.unlocked_at != ""


class TestAchievementSystemPersistence:
    def test_unlock_saves_and_reloads(self):
        from systems.achievement_system import AchievementSystem
        td = tempfile.mkdtemp()
        a = AchievementSystem(save_dir=td)
        a.unlock("speed_demon")
        a.teardown()

        a2 = AchievementSystem(save_dir=td)
        unlocked = [x for x in a2.get_all() if x.unlocked]
        a2.teardown()
        assert any(x.id == "speed_demon" for x in unlocked)

    def test_save_dir_created(self):
        from systems.achievement_system import AchievementSystem
        td = tempfile.mkdtemp()
        save_dir = str(Path(td) / "nested" / "saves")
        a = AchievementSystem(save_dir=save_dir)
        a.unlock("first_win")
        a.teardown()
        assert Path(save_dir).exists()

    def test_corrupt_save_handled(self):
        from systems.achievement_system import AchievementSystem
        td = tempfile.mkdtemp()
        save_path = Path(td) / "achievements.json"
        save_path.write_text("not valid json!", encoding="utf-8")
        a = AchievementSystem(save_dir=td)  # should not raise
        a.teardown()


class TestAchievementSystemSpeed:
    def test_speed_demon_via_event(self):
        from systems.achievement_system import AchievementSystem, MAX_SPEED_CFG
        from pharos_engine.event_bus import publish
        td = tempfile.mkdtemp()
        a = AchievementSystem(save_dir=td)
        mock_vehicle = object()
        a.set_player_vehicle(mock_vehicle)

        # Publish a speed event at 95% of max speed
        speed = 0.96 * MAX_SPEED_CFG
        publish("VehicleEntity.speed", publisher=mock_vehicle, value=speed)
        unlocked_ids = {x.id for x in a.get_all() if x.unlocked}
        a.teardown()
        assert "speed_demon" in unlocked_ids

    def test_speed_below_threshold_not_unlocked(self):
        from systems.achievement_system import AchievementSystem, MAX_SPEED_CFG
        from pharos_engine.event_bus import publish
        td = tempfile.mkdtemp()
        a = AchievementSystem(save_dir=td)
        mock_vehicle = object()
        a.set_player_vehicle(mock_vehicle)

        speed = 0.5 * MAX_SPEED_CFG
        publish("VehicleEntity.speed", publisher=mock_vehicle, value=speed)
        unlocked_ids = {x.id for x in a.get_all() if x.unlocked}
        a.teardown()
        assert "speed_demon" not in unlocked_ids


class TestAchievementSystemNitro:
    def test_nitro_junkie_after_10_uses(self):
        from systems.achievement_system import AchievementSystem
        from pharos_engine.event_bus import publish
        td = tempfile.mkdtemp()
        a = AchievementSystem(save_dir=td)
        mock_vehicle = object()
        a.set_player_vehicle(mock_vehicle)

        for _ in range(10):
            publish("Vehicle.NitroActive", publisher=mock_vehicle)
        unlocked_ids = {x.id for x in a.get_all() if x.unlocked}
        a.teardown()
        assert "nitro_junkie" in unlocked_ids

    def test_nitro_junkie_not_before_10(self):
        from systems.achievement_system import AchievementSystem
        from pharos_engine.event_bus import publish
        td = tempfile.mkdtemp()
        a = AchievementSystem(save_dir=td)
        mock_vehicle = object()
        a.set_player_vehicle(mock_vehicle)

        for _ in range(9):
            publish("Vehicle.NitroActive", publisher=mock_vehicle)
        unlocked_ids = {x.id for x in a.get_all() if x.unlocked}
        a.teardown()
        assert "nitro_junkie" not in unlocked_ids


# =============================================================================
# SaveSystem
# =============================================================================

class TestSaveSystemInit:
    def _ss(self, td=None):
        from systems.save_system import SaveSystem
        if td is None:
            td = tempfile.mkdtemp()
        return SaveSystem(save_dir=td)

    def test_instantiates(self):
        assert self._ss() is not None

    def test_save_dir_created(self):
        td = tempfile.mkdtemp()
        save_dir = str(Path(td) / "my_saves")
        ss = self._ss(save_dir)
        ss.teardown()
        assert Path(save_dir).exists()

    def test_teardown_no_crash(self):
        ss = self._ss()
        ss.teardown()


class TestSaveSystemKeyValue:
    def _ss(self):
        from systems.save_system import SaveSystem
        return SaveSystem(save_dir=tempfile.mkdtemp())

    def test_update_and_load_profile(self):
        td = tempfile.mkdtemp()
        from systems.save_system import SaveSystem
        ss = SaveSystem(save_dir=td)
        ss.update("total_coins", 100)
        ss.save()
        ss.teardown()

        ss2 = SaveSystem(save_dir=td)
        loaded = ss2.load()
        ss2.teardown()
        assert loaded.get("total_coins") == 100

    def test_save_best_lap(self):
        from systems.save_system import SaveSystem
        td = tempfile.mkdtemp()
        ss = SaveSystem(save_dir=td)
        ss.save_best_lap("circuit01", 75.3)
        ss.teardown()

        ss2 = SaveSystem(save_dir=td)
        ss2.load()
        best = ss2.load_best_laps()
        ss2.teardown()
        assert abs(best.get("circuit01", 0) - 75.3) < 1e-6

    def test_save_best_lap_keeps_faster(self):
        from systems.save_system import SaveSystem
        td = tempfile.mkdtemp()
        ss = SaveSystem(save_dir=td)
        ss.save_best_lap("track", 80.0)
        ss.save_best_lap("track", 60.0)
        ss.save_best_lap("track", 90.0)
        ss.teardown()

        ss2 = SaveSystem(save_dir=td)
        ss2.load()
        best = ss2.load_best_laps()
        ss2.teardown()
        assert abs(best.get("track", 0) - 60.0) < 1e-6

    def test_load_empty_returns_dict(self):
        ss = self._ss()
        result = ss.load()
        ss.teardown()
        assert isinstance(result, dict)

    def test_save_race_records(self):
        from systems.save_system import SaveSystem
        td = tempfile.mkdtemp()
        ss = SaveSystem(save_dir=td)
        ss.save_race("circuit01", [1, 2, 3], [75.0, 80.0])
        ss.save()
        ss.teardown()

        ss2 = SaveSystem(save_dir=td)
        data = ss2.load()
        ss2.teardown()
        assert "races" in data
        assert len(data["races"]) >= 1

    def test_total_races_increments_via_event(self):
        from systems.save_system import SaveSystem
        from pharos_engine.event_bus import publish
        td = tempfile.mkdtemp()
        ss = SaveSystem(save_dir=td)
        publish("Race.Finished", publisher=None, track_name="t1", results=[])
        ss.teardown()

        ss2 = SaveSystem(save_dir=td)
        data = ss2.load()
        ss2.teardown()
        assert data.get("total_races", 0) >= 1


class TestSaveSystemQuickHelpers:
    def test_quick_save_and_load(self):
        from systems.save_system import quick_save, quick_load
        td = tempfile.mkdtemp()
        quick_save({"score": 42}, save_dir=td)
        result = quick_load(save_dir=td)
        assert result.get("score") == 42

    def test_quick_load_empty_dir(self):
        from systems.save_system import quick_load
        td = tempfile.mkdtemp()
        result = quick_load(save_dir=td)
        assert isinstance(result, dict)


# =============================================================================
# CheckpointSystem
# =============================================================================

class _FakeVehicle:
    def __init__(self, pos=(0.0, 0.0)):
        self.position = pos
        self.velocity = (0.0, 0.0)
        self.size = (20.0, 20.0)


class TestCheckpointSystemInit:
    _GATES = [(100, 100, 60, 20), (300, 100, 60, 20), (500, 100, 60, 20)]

    def _cp(self, **kw):
        from systems.checkpoint_system import CheckpointSystem
        return CheckpointSystem(gate_defs=self._GATES, **kw)

    def test_instantiates(self):
        cp = self._cp()
        cp.teardown()

    def test_gates_count(self):
        cp = self._cp(laps_total=3)
        # 3 gate defs → 3 volumes
        assert len(cp._volumes) == 3
        cp.teardown()

    def test_empty_gates_no_crash(self):
        from systems.checkpoint_system import CheckpointSystem
        cp = CheckpointSystem(gate_defs=[], laps_total=1)
        cp.teardown()


class TestCheckpointSystemRegister:
    def _cp(self):
        from systems.checkpoint_system import CheckpointSystem
        return CheckpointSystem(gate_defs=[(0, 0, 50, 20), (200, 0, 50, 20)], laps_total=1)

    def test_register_entity(self):
        cp = self._cp()
        v = _FakeVehicle()
        cp.register(v)
        assert id(v) in cp._state
        cp.teardown()

    def test_register_twice_no_duplicate(self):
        cp = self._cp()
        v = _FakeVehicle()
        cp.register(v)
        cp.register(v)
        assert len(cp._state) == 1
        cp.teardown()

    def test_lap_count_zero_before_crossing(self):
        cp = self._cp()
        v = _FakeVehicle()
        cp.register(v)
        assert cp.lap_count(v) == 0
        cp.teardown()

    def test_gates_crossed_zero_before_crossing(self):
        cp = self._cp()
        v = _FakeVehicle()
        cp.register(v)
        assert cp.gates_crossed(v) == 0
        cp.teardown()

    def test_unregistered_entity_lap_count_zero(self):
        cp = self._cp()
        v = _FakeVehicle()
        assert cp.lap_count(v) == 0
        cp.teardown()

    def test_progress_zero_before_start(self):
        cp = self._cp()
        v = _FakeVehicle()
        cp.register(v)
        assert cp.progress(v) == 0.0
        cp.teardown()


class TestCheckpointSystemGateCrossing:
    def _cp_with_vehicle(self):
        from systems.checkpoint_system import CheckpointSystem
        # Gate 0 at (50, 50), Gate 1 at (200, 50) — large enough to overlap
        cp = CheckpointSystem(
            gate_defs=[(50, 50, 100, 100), (200, 50, 100, 100)],
            laps_total=1,
        )
        v = _FakeVehicle(pos=(50.0, 50.0))
        cp.register(v)
        cp.start_race()
        return cp, v

    def test_gate_enter_fires_event(self):
        from pharos_engine.event_bus import subscribe, unsubscribe
        cp, v = self._cp_with_vehicle()
        received = []
        h = subscribe("Race.CheckpointCrossed", lambda e: received.append(e))
        cp.update(0.016, [v])
        unsubscribe(h)
        cp.teardown()
        assert len(received) >= 1

    def test_gates_crossed_increments(self):
        cp, v = self._cp_with_vehicle()
        cp.update(0.016, [v])
        crossed = cp.gates_crossed(v)
        cp.teardown()
        assert crossed == 1

    def test_finish_callback_fired_after_full_lap(self):
        from systems.checkpoint_system import CheckpointSystem
        finished = []
        # 2-gate track: gate 0 (finish), gate 1 (mid)
        cp = CheckpointSystem(
            gate_defs=[(50, 50, 100, 100), (200, 50, 100, 100)],
            laps_total=1,
            on_finish=lambda e, laps, best: finished.append((e, laps)),
        )
        v = _FakeVehicle()
        cp.register(v)
        cp.start_race()
        # Cross gates in order: 0 → 1 → then gate 0 again = lap complete
        cp._on_gate_enter(v, 0)
        cp._on_gate_enter(v, 1)
        # Now all 2 gates crossed → next crossing of gate 0 → complete lap
        cp._on_gate_enter(v, 0)
        cp.teardown()
        assert len(finished) == 1


class TestCheckpointSystemProgress:
    def test_progress_increases_with_gates(self):
        from systems.checkpoint_system import CheckpointSystem
        cp = CheckpointSystem(
            gate_defs=[(50, 50, 100, 100), (200, 50, 100, 100)],
            laps_total=2,
        )
        v = _FakeVehicle(pos=(50.0, 50.0))
        cp.register(v)
        cp._on_gate_enter(v, 0)  # cross gate 0
        p = cp.progress(v)
        cp.teardown()
        assert p > 0.0

    def test_is_finished_false_initially(self):
        from systems.checkpoint_system import CheckpointSystem
        cp = CheckpointSystem(gate_defs=[(0, 0, 50, 50)], laps_total=1)
        v = _FakeVehicle()
        cp.register(v)
        assert cp.is_finished(v) is False
        cp.teardown()


# =============================================================================
# RaceManager
# =============================================================================

class TestRaceManagerInit:
    def _rm(self, **kw):
        from systems.race_manager import RaceManager
        return RaceManager(gate_defs=[(100, 100, 60, 20)], laps_total=2, **kw)

    def test_instantiates(self):
        assert self._rm() is not None

    def test_initial_state_countdown(self):
        from systems.race_manager import RaceState
        assert self._rm().state == RaceState.COUNTDOWN

    def test_countdown_positive(self):
        assert self._rm().countdown > 0.0

    def test_elapsed_zero_initially(self):
        assert self._rm().elapsed == 0.0

    def test_finish_order_empty_initially(self):
        assert self._rm().finish_order == []


class TestRaceManagerCountdown:
    def _rm(self):
        from systems.race_manager import RaceManager
        return RaceManager(gate_defs=[(100, 100, 60, 20)], laps_total=1)

    def test_update_decrements_countdown(self):
        rm = self._rm()
        before = rm.countdown
        rm.update(0.5)
        assert rm.countdown < before

    def test_countdown_transitions_to_racing(self):
        from systems.race_manager import RaceState
        rm = self._rm()
        rm.update(5.0)  # more than countdown duration (3s)
        assert rm.state == RaceState.RACING

    def test_race_started_event_fires(self):
        from pharos_engine.event_bus import subscribe, unsubscribe
        from systems.race_manager import RaceManager
        received = []
        h = subscribe("Race.Started", lambda e: received.append(e))
        rm = RaceManager(gate_defs=[], laps_total=1)
        rm.update(5.0)
        unsubscribe(h)
        assert len(received) == 1

    def test_elapsed_increases(self):
        rm = self._rm()
        rm.update(1.0)
        assert rm.elapsed >= 1.0


class TestRaceManagerVehicles:
    def _rm(self, vehicles=None):
        from systems.race_manager import RaceManager
        return RaceManager(gate_defs=[(100, 100, 60, 20)], laps_total=1, vehicles=vehicles or [])

    def test_add_vehicle(self):
        rm = self._rm()
        v = _FakeVehicle()
        rm.add_vehicle(v)
        assert v in rm._vehicles

    def test_add_vehicle_duplicate(self):
        rm = self._rm()
        v = _FakeVehicle()
        rm.add_vehicle(v)
        rm.add_vehicle(v)
        assert rm._vehicles.count(v) == 1

    def test_position_returns_valid_rank(self):
        v = _FakeVehicle()
        rm = self._rm(vehicles=[v])
        rank = rm.position(v)
        assert rank >= 1

    def test_lap_str_format(self):
        v = _FakeVehicle()
        rm = self._rm(vehicles=[v])
        s = rm.lap_str(v)
        assert "LAP" in s

    def test_on_finish_callback_called(self):
        from systems.race_manager import RaceManager
        done = []
        v = _FakeVehicle()
        rm = RaceManager(
            gate_defs=[(50, 50, 100, 100), (200, 50, 100, 100)],
            laps_total=1,
            vehicles=[v],
            on_finish=lambda order: done.append(order),
        )
        rm.update(5.0)  # transition to racing
        # Cross gate 0, then gate 1, then gate 0 again = 1 lap = finish
        rm._cp._on_gate_enter(v, 0)
        rm._cp._on_gate_enter(v, 1)
        rm._cp._on_gate_enter(v, 0)
        assert len(done) == 1


class TestRaceManagerPosition:
    def test_calc_positions_with_vehicles(self):
        from systems.race_manager import RaceManager
        v1 = _FakeVehicle()
        v2 = _FakeVehicle()
        rm = RaceManager(gate_defs=[], laps_total=1, vehicles=[v1, v2])
        rm.update(5.0)  # start racing
        rm._calc_positions()
        # Both vehicles have rank
        assert rm.position(v1) in (1, 2)
        assert rm.position(v2) in (1, 2)

    def test_lap_count_query(self):
        from systems.race_manager import RaceManager
        v = _FakeVehicle()
        rm = RaceManager(gate_defs=[], laps_total=1, vehicles=[v])
        assert rm.lap_count(v) == 0
