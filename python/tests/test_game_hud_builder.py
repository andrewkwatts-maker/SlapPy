"""Headless tests for Ochema Circuit: CheckpointEntity, VehicleGridBuilder,
RaceHUD event handlers, _fmt_lap_time helper.
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("slappyengine.compute.asset_compute", MagicMock())

_GAME_ROOT = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Ochema Circuit"
_GAME_STR = str(_GAME_ROOT)
if _GAME_STR not in sys.path:
    sys.path.insert(0, _GAME_STR)


# =============================================================================
# CheckpointEntity
# =============================================================================

class TestCheckpointEntityInit:
    def _cp(self, x=0.0, y=0.0, w=100.0, h=20.0, cb=None):
        from entities.checkpoint import CheckpointEntity
        return CheckpointEntity(x=x, y=y, w=w, h=h, on_crossed=cb)

    def test_instantiates(self):
        assert self._cp() is not None

    def test_rect_stored(self):
        cp = self._cp(x=50.0, y=100.0, w=80.0, h=15.0)
        assert cp.rect == (50.0, 100.0, 80.0, 15.0)

    def test_crossed_empty_initially(self):
        assert len(self._cp()._crossed) == 0

    def test_no_callback_no_crash(self):
        cp = self._cp()
        assert not cp.check(1, 200.0, 200.0)  # outside rect, no crash


class TestCheckpointEntityCheck:
    def _cp(self, cb=None):
        from entities.checkpoint import CheckpointEntity
        return CheckpointEntity(x=0.0, y=0.0, w=100.0, h=20.0, on_crossed=cb)

    def test_inside_returns_true(self):
        cp = self._cp()
        assert cp.check(1, 50.0, 10.0) is True

    def test_outside_returns_false(self):
        cp = self._cp()
        assert cp.check(1, 200.0, 200.0) is False

    def test_marks_as_crossed(self):
        cp = self._cp()
        cp.check(1, 50.0, 10.0)
        assert 1 in cp._crossed

    def test_second_crossing_returns_false(self):
        cp = self._cp()
        cp.check(1, 50.0, 10.0)
        assert cp.check(1, 50.0, 10.0) is False

    def test_callback_called_on_first_crossing(self):
        called = []
        cp = self._cp(cb=lambda vid: called.append(vid))
        cp.check(42, 50.0, 10.0)
        assert called == [42]

    def test_callback_not_called_on_repeat(self):
        called = []
        cp = self._cp(cb=lambda vid: called.append(vid))
        cp.check(1, 50.0, 10.0)
        cp.check(1, 50.0, 10.0)
        assert len(called) == 1

    def test_different_vehicles_independent(self):
        cp = self._cp()
        assert cp.check(1, 50.0, 10.0) is True
        assert cp.check(2, 50.0, 10.0) is True

    def test_reset_clears_crossed(self):
        cp = self._cp()
        cp.check(1, 50.0, 10.0)
        cp.reset()
        assert len(cp._crossed) == 0

    def test_can_cross_again_after_reset(self):
        cp = self._cp()
        cp.check(1, 50.0, 10.0)
        cp.reset()
        assert cp.check(1, 50.0, 10.0) is True

    def test_boundary_left_edge(self):
        cp = self._cp()
        assert cp.check(1, 0.0, 10.0) is True  # exactly on left edge

    def test_boundary_right_edge(self):
        cp = self._cp()
        assert cp.check(1, 100.0, 10.0) is True  # exactly on right edge

    def test_boundary_top_edge(self):
        cp = self._cp()
        assert cp.check(1, 50.0, 0.0) is True

    def test_boundary_bottom_edge(self):
        cp = self._cp()
        assert cp.check(1, 50.0, 20.0) is True

    def test_just_outside_left(self):
        cp = self._cp()
        assert cp.check(1, -0.1, 10.0) is False


# =============================================================================
# VehicleGridBuilder
# =============================================================================

class TestVehicleGridBuilderInit:
    def _b(self):
        from systems.grid_builder import VehicleGridBuilder
        return VehicleGridBuilder()

    def test_instantiates(self):
        assert self._b() is not None

    def test_grid_empty_initially(self):
        b = self._b()
        assert len(b._grid) == 0


class TestVehicleGridBuilderPlace:
    def _b(self):
        from systems.grid_builder import VehicleGridBuilder
        return VehicleGridBuilder()

    def test_place_returns_true(self):
        from entities.part import PartType
        b = self._b()
        assert b.place(PartType.COCKPIT, 0, 0) is True

    def test_place_adds_to_grid(self):
        from entities.part import PartType
        b = self._b()
        b.place(PartType.ENGINE, 1, 1)
        assert (1, 1) in b._grid

    def test_place_duplicate_returns_false(self):
        from entities.part import PartType
        b = self._b()
        b.place(PartType.COCKPIT, 0, 0)
        assert b.place(PartType.ENGINE, 0, 0) is False

    def test_place_out_of_bounds_returns_false(self):
        from entities.part import PartType
        from systems.grid_builder import GRID_SIZE
        b = self._b()
        assert b.place(PartType.COCKPIT, GRID_SIZE, GRID_SIZE) is False

    def test_place_negative_returns_false(self):
        from entities.part import PartType
        b = self._b()
        assert b.place(PartType.COCKPIT, -1, 0) is False

    def test_place_multiple_distinct(self):
        from entities.part import PartType
        b = self._b()
        b.place(PartType.COCKPIT, 0, 0)
        b.place(PartType.ENGINE, 1, 0)
        b.place(PartType.WHEEL, 0, 1)
        assert len(b._grid) == 3


class TestVehicleGridBuilderRemove:
    def _b(self):
        from systems.grid_builder import VehicleGridBuilder
        return VehicleGridBuilder()

    def test_remove_placed_part(self):
        from entities.part import PartType, VehiclePart
        b = self._b()
        b.place(PartType.ENGINE, 2, 2)
        removed = b.remove(2, 2)
        assert isinstance(removed, VehiclePart)
        assert (2, 2) not in b._grid

    def test_remove_nonexistent_returns_none(self):
        b = self._b()
        result = b.remove(0, 0)
        assert result is None

    def test_remove_decrements_grid_count(self):
        from entities.part import PartType
        b = self._b()
        b.place(PartType.ENGINE, 0, 0)
        b.remove(0, 0)
        assert len(b._grid) == 0


class TestVehicleGridBuilderValidate:
    def _b(self):
        from systems.grid_builder import VehicleGridBuilder
        return VehicleGridBuilder()

    def test_empty_grid_invalid_no_cockpit(self):
        b = self._b()
        ok, msg = b.validate()
        assert ok is False
        assert "COCKPIT" in msg

    def test_no_engine_invalid(self):
        from entities.part import PartType
        b = self._b()
        b.place(PartType.COCKPIT, 0, 0)
        ok, msg = b.validate()
        assert ok is False
        assert "ENGINE" in msg

    def test_no_wheels_invalid(self):
        from entities.part import PartType
        b = self._b()
        b.place(PartType.COCKPIT, 0, 0)
        b.place(PartType.ENGINE, 1, 0)
        ok, msg = b.validate()
        assert ok is False
        assert "WHEEL" in msg

    def test_one_wheel_invalid(self):
        from entities.part import PartType
        b = self._b()
        b.place(PartType.COCKPIT, 0, 0)
        b.place(PartType.ENGINE, 1, 0)
        b.place(PartType.WHEEL, 2, 0)
        ok, _ = b.validate()
        assert ok is False

    def test_valid_minimal_build(self):
        from entities.part import PartType
        b = self._b()
        b.place(PartType.COCKPIT, 0, 0)
        b.place(PartType.ENGINE, 1, 0)
        b.place(PartType.WHEEL, 2, 0)
        b.place(PartType.WHEEL, 3, 0)
        ok, _ = b.validate()
        assert ok is True

    def test_valid_build_message_contains_valid(self):
        from entities.part import PartType
        b = self._b()
        b.place(PartType.COCKPIT, 0, 0)
        b.place(PartType.ENGINE, 1, 0)
        b.place(PartType.WHEEL, 2, 0)
        b.place(PartType.WHEEL, 3, 0)
        ok, msg = b.validate()
        assert ok is True
        assert "Valid" in msg or msg != ""


class TestVehicleGridBuilderBake:
    def _valid_builder(self):
        from systems.grid_builder import VehicleGridBuilder
        from entities.part import PartType
        b = VehicleGridBuilder()
        b.place(PartType.COCKPIT, 0, 0)
        b.place(PartType.ENGINE,  1, 0)
        b.place(PartType.WHEEL,   2, 0)
        b.place(PartType.WHEEL,   3, 0)
        return b

    def test_bake_returns_vehicle_entity(self):
        from entities.vehicle import VehicleEntity
        b = self._valid_builder()
        v = b.bake(driver_id=0)
        assert isinstance(v, VehicleEntity)

    def test_bake_vehicle_has_parts(self):
        b = self._valid_builder()
        v = b.bake(driver_id=0)
        assert len(v.parts) == 4

    def test_bake_driver_id_stored(self):
        b = self._valid_builder()
        v = b.bake(driver_id=3)
        assert v.driver_id == 3

    def test_bake_with_profile_applies_tier(self):
        from systems.player_profile import PlayerProfile
        b = self._valid_builder()
        profile = PlayerProfile()
        v = b.bake(driver_id=0, profile=profile)
        # all parts should have tier from profile (0 by default)
        for part in v.parts:
            assert part.tier >= 0


# =============================================================================
# _fmt_lap_time helper
# =============================================================================

class TestFmtLapTime:
    def _fmt(self, s):
        from entities.hud import _fmt_lap_time
        return _fmt_lap_time(s)

    def test_zero_returns_placeholder(self):
        result = self._fmt(0.0)
        assert result == "00:00.000"

    def test_negative_returns_placeholder(self):
        result = self._fmt(-1.0)
        assert result == "00:00.000"

    def test_30_seconds(self):
        result = self._fmt(30.0)
        assert "00:30" in result

    def test_one_minute(self):
        result = self._fmt(60.0)
        assert "01:00" in result

    def test_90_seconds(self):
        result = self._fmt(90.0)
        assert "01:30" in result

    def test_format_has_milliseconds(self):
        result = self._fmt(45.123)
        assert "." in result

    def test_format_is_string(self):
        assert isinstance(self._fmt(10.0), str)


# =============================================================================
# RaceHUD event handlers (no rendering)
# =============================================================================

class _FakeVehicle:
    def __init__(self):
        self.driver_id = 0
        self.velocity = [0.0, 0.0]
        self.position = (640.0, 360.0)
        self.armor_hp = {"FRONT": 100.0, "REAR": 100.0, "LEFT": 100.0, "RIGHT": 100.0}
        self.heat = 0.0
        self.weapon_locked = 0.0
        self.hull_integrity = 1.0
        self.speed = 0.0
        self.gear = 1


class TestRaceHUDEventHandlers:
    """Test event handler logic directly without calling _render()."""

    def _hud(self, vehicle=None):
        from entities.hud import RaceHUD
        v = vehicle or _FakeVehicle()
        hud = RaceHUD(vehicle=v, x=0.0, y=0.0)
        hud._vehicle = v
        return hud, v

    def teardown_hud(self, hud):
        hud.on_end()

    def test_on_speed_updates_speed(self):
        hud, v = self._hud()
        evt = MagicMock()
        evt.publisher = v
        evt.value = 250.0
        hud._on_speed(evt)
        assert abs(hud._speed - 250.0) < 1e-6
        self.teardown_hud(hud)

    def test_on_speed_ignores_other_vehicles(self):
        hud, v = self._hud()
        evt = MagicMock()
        evt.publisher = MagicMock()  # different vehicle
        evt.value = 999.0
        hud._on_speed(evt)
        assert hud._speed == 0.0  # unchanged
        self.teardown_hud(hud)

    def test_on_integrity_updates(self):
        hud, v = self._hud()
        evt = MagicMock()
        evt.publisher = v
        evt.value = 0.75
        hud._on_integrity(evt)
        assert abs(hud._hull_integrity - 0.75) < 1e-6
        self.teardown_hud(hud)

    def test_on_lap_complete_updates_lap(self):
        hud, v = self._hud()
        evt = MagicMock()
        evt.publisher = v
        evt.lap = 2
        evt.lap_time = 88.5
        hud._on_lap_complete(evt)
        assert hud._lap == 2
        self.teardown_hud(hud)

    def test_on_lap_complete_sets_best_lap(self):
        hud, v = self._hud()
        evt = MagicMock()
        evt.publisher = v
        evt.lap = 1
        evt.lap_time = 75.0
        hud._on_lap_complete(evt)
        assert abs(hud._best_lap_s - 75.0) < 1e-6
        self.teardown_hud(hud)

    def test_on_lap_complete_best_lap_flash_set(self):
        hud, v = self._hud()
        evt = MagicMock()
        evt.publisher = v
        evt.lap = 1
        evt.lap_time = 60.0
        hud._on_lap_complete(evt)
        assert hud._best_lap_flash > 0.0
        self.teardown_hud(hud)

    def test_on_positions_updates_rank(self):
        hud, v = self._hud()
        other = MagicMock()
        evt = MagicMock()
        evt.positions = [other, v]  # v is in 2nd place
        evt.gaps = [0.0, 10.0]
        hud._on_positions(evt)
        assert hud._position == 2
        self.teardown_hud(hud)

    def test_on_race_started_sets_flag(self):
        hud, v = self._hud()
        hud._on_race_started(MagicMock())
        assert hud._race_started is True
        self.teardown_hud(hud)

    def test_on_nitro_updates(self):
        hud, v = self._hud()
        evt = MagicMock()
        evt.publisher = v
        evt.active = True
        hud._on_nitro(evt)
        assert hud._nitro_active is True
        self.teardown_hud(hud)

    def test_on_dnf_sets_flag(self):
        hud, v = self._hud()
        evt = MagicMock()
        evt.publisher = v
        evt.driver_id = None
        hud._on_dnf(evt)
        assert hud._dnf is True
        self.teardown_hud(hud)

    def test_on_wrong_way_sets_timer(self):
        hud, v = self._hud()
        evt = MagicMock()
        evt.publisher = v
        evt.driver_id = None
        hud._on_wrong_way(evt)
        assert hud._wrong_way is True
        assert hud._wrong_way_timer > 0.0
        self.teardown_hud(hud)

    def test_on_boost_sets_flag(self):
        hud, v = self._hud()
        evt = MagicMock()
        evt.publisher = v
        hud._on_boost(evt)
        assert hud._boost_active is True
        self.teardown_hud(hud)

    def test_on_race_finished_sets_flag(self):
        hud, v = self._hud()
        hud._on_race_finished(MagicMock())
        assert hud._race_finished is True
        self.teardown_hud(hud)

    def test_on_coins_earned_updates(self):
        hud, v = self._hud()
        evt = MagicMock()
        evt.total = 150
        hud._on_coins_earned(evt)
        assert hud._coins == 150
        self.teardown_hud(hud)

    def test_on_pits_entered_sets_active(self):
        hud, v = self._hud()
        evt = MagicMock()
        evt.publisher = v
        hud._on_pits_entered(evt)
        assert hud._pits_active is True
        self.teardown_hud(hud)

    def test_on_pits_exited_clears_active(self):
        hud, v = self._hud()
        evt = MagicMock()
        evt.publisher = v
        hud._pits_active = True
        evt.total_cost = 25
        hud._on_pits_exited(evt)
        assert hud._pits_active is False
        self.teardown_hud(hud)

    def test_on_layer_destroyed_sets_message(self):
        hud, v = self._hud()
        evt = MagicMock()
        evt.publisher = v
        evt.layer_name = "chassis"
        hud._on_layer_destroyed(evt)
        assert "CHASSIS" in hud._layer_destroyed_msg
        assert hud._layer_destroyed_flash > 0.0
        self.teardown_hud(hud)

    def test_on_end_unsubscribes(self):
        hud, v = self._hud()
        hud.on_end()
        assert hud._handles == []

    def test_on_end_twice_no_crash(self):
        hud, v = self._hud()
        hud.on_end()
        hud.on_end()


class TestRaceHUDTimers:
    def _hud(self):
        from entities.hud import RaceHUD
        v = _FakeVehicle()
        hud = RaceHUD(vehicle=v, x=0.0, y=0.0)
        hud._vehicle = v
        return hud

    def test_tick_timers_decays_best_lap_flash(self):
        hud = self._hud()
        hud._best_lap_flash = 1.0
        hud._tick_timers(0.5)
        assert hud._best_lap_flash < 1.0
        hud.on_end()

    def test_tick_timers_clears_wrong_way(self):
        hud = self._hud()
        hud._wrong_way = True
        hud._wrong_way_timer = 0.1
        hud._tick_timers(0.2)
        assert hud._wrong_way is False
        hud.on_end()

    def test_tick_timers_clears_boost_active(self):
        hud = self._hud()
        hud._boost_active = True
        hud._boost_timer = 0.1
        hud._tick_timers(0.2)
        assert hud._boost_active is False
        hud.on_end()

    def test_tick_timers_decays_hit_flash(self):
        hud = self._hud()
        hud._hit_flash = 0.4
        hud._tick_timers(0.1)
        assert hud._hit_flash < 0.4
        hud.on_end()

    def test_tick_timers_clears_countdown(self):
        hud = self._hud()
        hud._countdown_tick = 3
        hud._countdown_timer = 0.1
        hud._tick_timers(0.2)
        assert hud._countdown_tick == 0
        hud.on_end()

    def test_tick_timers_decays_layer_destroyed_flash(self):
        hud = self._hud()
        hud._layer_destroyed_flash = 2.0
        hud._tick_timers(0.5)
        assert hud._layer_destroyed_flash < 2.0
        hud.on_end()
