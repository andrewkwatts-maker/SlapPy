"""Headless tests for Ochema Circuit: CheckpointEntity, HazardSystem,
PitsSystem, and VehicleGridBuilder.
"""
from __future__ import annotations
import sys
import tempfile
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
    def _cp(self, callback=None):
        from entities.checkpoint import CheckpointEntity
        return CheckpointEntity(x=0, y=0, w=100, h=100, on_crossed=callback)

    def test_rect_stored(self):
        cp = self._cp()
        assert cp.rect == (0, 0, 100, 100)

    def test_crossed_set_empty_initially(self):
        cp = self._cp()
        assert len(cp._crossed) == 0

    def test_callback_none_by_default(self):
        cp = self._cp()
        assert cp._on_crossed is None


class TestCheckpointEntityCheck:
    def _cp(self, callback=None):
        from entities.checkpoint import CheckpointEntity
        return CheckpointEntity(x=0, y=0, w=100, h=100, on_crossed=callback)

    def test_outside_returns_false(self):
        cp = self._cp()
        assert cp.check(1, 200, 200) is False

    def test_inside_returns_true_first_time(self):
        cp = self._cp()
        assert cp.check(1, 50, 50) is True

    def test_inside_already_crossed_returns_false(self):
        cp = self._cp()
        cp.check(1, 50, 50)
        assert cp.check(1, 50, 50) is False

    def test_different_vehicles_both_can_cross(self):
        cp = self._cp()
        assert cp.check(1, 50, 50) is True
        assert cp.check(2, 50, 50) is True

    def test_same_vehicle_only_once(self):
        cp = self._cp()
        cp.check(1, 50, 50)
        cp.check(1, 50, 50)
        assert len(cp._crossed) == 1

    def test_callback_fires_on_cross(self):
        fired = []
        cp = self._cp(callback=lambda vid: fired.append(vid))
        cp.check(42, 50, 50)
        assert fired == [42]

    def test_callback_not_fired_outside(self):
        fired = []
        cp = self._cp(callback=lambda vid: fired.append(vid))
        cp.check(1, 999, 999)
        assert len(fired) == 0

    def test_callback_not_fired_duplicate(self):
        fired = []
        cp = self._cp(callback=lambda vid: fired.append(vid))
        cp.check(1, 50, 50)
        cp.check(1, 50, 50)  # duplicate
        assert len(fired) == 1

    def test_boundary_left_edge_inside(self):
        cp = self._cp()
        assert cp.check(1, 0, 50) is True

    def test_boundary_right_edge_inside(self):
        cp = self._cp()
        assert cp.check(1, 100, 50) is True

    def test_boundary_just_outside_right(self):
        cp = self._cp()
        assert cp.check(1, 101, 50) is False


class TestCheckpointEntityReset:
    def _cp(self):
        from entities.checkpoint import CheckpointEntity
        return CheckpointEntity(x=0, y=0, w=100, h=100)

    def test_reset_clears_crossed(self):
        cp = self._cp()
        cp.check(1, 50, 50)
        cp.check(2, 50, 50)
        cp.reset()
        assert len(cp._crossed) == 0

    def test_after_reset_vehicle_can_cross_again(self):
        cp = self._cp()
        cp.check(1, 50, 50)
        cp.reset()
        assert cp.check(1, 50, 50) is True

    def test_reset_no_crash_when_empty(self):
        cp = self._cp()
        cp.reset()  # should not raise


# =============================================================================
# HazardSystem
# =============================================================================

class TestHazardSystemInit:
    def _hs(self):
        from systems.hazard_system import HazardSystem
        from slappyengine.trigger import TriggerSystem
        ts = TriggerSystem()
        hs = HazardSystem(ts)
        return hs, ts

    def test_instantiates(self):
        hs, ts = self._hs()
        hs.teardown()

    def test_no_volumes_initially(self):
        hs, ts = self._hs()
        assert len(hs._boost_vols) == 0
        assert len(hs._damage_vols) == 0
        hs.teardown()

    def test_teardown_no_crash(self):
        hs, ts = self._hs()
        hs.teardown()
        hs.teardown()  # double teardown harmless


class TestHazardSystemBoostPad:
    def _hs(self):
        from systems.hazard_system import HazardSystem
        from slappyengine.trigger import TriggerSystem
        ts = TriggerSystem()
        return HazardSystem(ts), ts

    def test_add_boost_pad_returns_volume(self):
        from slappyengine.trigger import TriggerVolume
        hs, ts = self._hs()
        vol = hs.add_boost_pad((100, 100))
        assert isinstance(vol, TriggerVolume)
        hs.teardown()

    def test_add_boost_pad_has_boost_tag(self):
        hs, ts = self._hs()
        vol = hs.add_boost_pad((100, 100))
        assert vol.tag == "boost"
        hs.teardown()

    def test_add_boost_pad_added_to_list(self):
        hs, ts = self._hs()
        hs.add_boost_pad((100, 100))
        assert len(hs._boost_vols) == 1
        hs.teardown()

    def test_multiple_boost_pads(self):
        hs, ts = self._hs()
        hs.add_boost_pad((100, 100))
        hs.add_boost_pad((200, 200))
        assert len(hs._boost_vols) == 2
        hs.teardown()

    def test_boost_pad_fires_event_on_enter(self):
        from systems.hazard_system import HazardSystem
        from slappyengine.trigger import TriggerSystem
        from slappyengine.event_bus import subscribe, unsubscribe
        ts = TriggerSystem()
        hs = HazardSystem(ts)
        hs.add_boost_pad((50, 50), size=(200, 200))

        class FakeVehicle:
            position = (50.0, 50.0)
            velocity = (0.0, 0.0)
            size = (10.0, 10.0)

        received = []
        h = subscribe("Vehicle.Boost", lambda e: received.append(e))
        ts.update([FakeVehicle()])
        unsubscribe(h)
        hs.teardown()
        assert len(received) >= 1


class TestHazardSystemDamageZone:
    def _hs(self):
        from systems.hazard_system import HazardSystem
        from slappyengine.trigger import TriggerSystem
        ts = TriggerSystem()
        return HazardSystem(ts), ts

    def test_add_damage_zone_returns_volume(self):
        from slappyengine.trigger import TriggerVolume
        hs, ts = self._hs()
        vol = hs.add_damage_zone((200, 200))
        assert isinstance(vol, TriggerVolume)
        hs.teardown()

    def test_damage_zone_has_damage_tag(self):
        hs, ts = self._hs()
        vol = hs.add_damage_zone((200, 200))
        assert vol.tag == "damage"
        hs.teardown()

    def test_damage_zone_added_to_list(self):
        hs, ts = self._hs()
        hs.add_damage_zone((200, 200))
        assert len(hs._damage_vols) == 1
        hs.teardown()

    def test_damage_zone_fires_event(self):
        from systems.hazard_system import HazardSystem
        from slappyengine.trigger import TriggerSystem
        from slappyengine.event_bus import subscribe, unsubscribe
        ts = TriggerSystem()
        hs = HazardSystem(ts)
        hs.add_damage_zone((50, 50), size=(200, 200), damage=0.1)

        class FakeVehicle:
            position = (50.0, 50.0)
            velocity = (0.0, 0.0)
            size = (10.0, 10.0)

        received = []
        h = subscribe("Vehicle.DamageZone", lambda e: received.append(e))
        ts.update([FakeVehicle()])
        unsubscribe(h)
        hs.teardown()
        assert len(received) >= 1


# =============================================================================
# PitsSystem
# =============================================================================

class _SlowVehicle:
    """Vehicle moving below entry speed limit."""
    def __init__(self):
        self.position = (100.0, 100.0)
        self.velocity = [0.0, 0.0]  # stopped
        self.size = (20.0, 20.0)
        self.hull_integrity = 0.5


class _FastVehicle:
    """Vehicle moving above entry speed limit."""
    def __init__(self):
        self.position = (100.0, 100.0)
        self.velocity = [100.0, 0.0]  # 100 px/s > 60 limit
        self.size = (20.0, 20.0)
        self.hull_integrity = 0.5


class TestPitsSystemInit:
    def _ps(self, positions=None):
        from systems.pits_system import PitsSystem
        from slappyengine.trigger import TriggerSystem
        ts = TriggerSystem()
        ps = PitsSystem(ts, vehicles=[], pit_positions=positions)
        return ps, ts

    def test_instantiates(self):
        ps, ts = self._ps()
        ps.teardown()

    def test_default_pit_volume_created(self):
        ps, ts = self._ps()
        assert len(ps._pit_volumes) >= 1
        ps.teardown()

    def test_custom_pit_positions(self):
        ps, ts = self._ps(positions=[(50, 50, 80, 40, 1, 0), (300, 50, 80, 40, 1, 0)])
        assert len(ps._pit_volumes) == 2
        ps.teardown()

    def test_no_active_sessions_initially(self):
        ps, ts = self._ps()
        assert len(ps._active_sessions) == 0
        ps.teardown()

    def test_teardown_no_crash(self):
        ps, ts = self._ps()
        ps.teardown()


class TestPitsSystemEnter:
    def _ps(self, pit_pos=(100, 100, 200, 200)):
        from systems.pits_system import PitsSystem
        from slappyengine.trigger import TriggerSystem
        ts = TriggerSystem()
        ps = PitsSystem(ts, vehicles=[], pit_positions=[(*pit_pos, 1.0, 0.0)])
        return ps, ts

    def test_slow_vehicle_enters_session(self):
        ps, ts = self._ps()
        v = _SlowVehicle()
        ts.update([v])
        result = id(v) in ps._active_sessions
        ps.teardown()
        assert result is True

    def test_fast_vehicle_rejected(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        ps, ts = self._ps()
        v = _FastVehicle()
        rejected = []
        h = subscribe("Pits.Rejected", lambda e: rejected.append(e))
        ts.update([v])
        unsubscribe(h)
        ps.teardown()
        assert len(rejected) >= 1

    def test_pits_entered_event_fires(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        ps, ts = self._ps()
        v = _SlowVehicle()
        received = []
        h = subscribe("Pits.Entered", lambda e: received.append(e))
        ts.update([v])
        unsubscribe(h)
        ps.teardown()
        assert len(received) >= 1

    def test_duplicate_entry_no_duplicate_session(self):
        ps, ts = self._ps()
        v = _SlowVehicle()
        ts.update([v])
        ts.update([v])  # second trigger
        count = len(ps._active_sessions)
        ps.teardown()
        assert count == 1


class TestPitsSystemUpdate:
    def _ps(self):
        from systems.pits_system import PitsSystem
        from slappyengine.trigger import TriggerSystem
        ts = TriggerSystem()
        ps = PitsSystem(ts, vehicles=[], pit_positions=[(100, 100, 200, 200, 1.0, 0.0)])
        return ps, ts

    def test_update_no_active_sessions_no_crash(self):
        ps, ts = self._ps()
        ps.update(0.016)
        ps.teardown()

    def test_update_publishes_repairing_event(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        ps, ts = self._ps()
        v = _SlowVehicle()
        ts.update([v])
        received = []
        h = subscribe("Pits.Repairing", lambda e: received.append(e))
        ps.update(0.016)
        unsubscribe(h)
        ps.teardown()
        assert len(received) >= 1

    def test_session_removed_when_max_repair_reached(self):
        from systems.pits_system import PitsSystem, MAX_REPAIR_PER_VISIT
        from slappyengine.trigger import TriggerSystem
        ts = TriggerSystem()
        ps = PitsSystem(ts, vehicles=[], pit_positions=[(100, 100, 200, 200, 1.0, 0.0)])
        v = _SlowVehicle()
        ts.update([v])
        # Force max repair
        ps._active_sessions[id(v)].repair_this_visit = MAX_REPAIR_PER_VISIT
        ps.update(0.016)
        result = id(v) not in ps._active_sessions
        ps.teardown()
        assert result is True

    def test_pits_exited_event_fires_on_max_repair(self):
        from systems.pits_system import PitsSystem, MAX_REPAIR_PER_VISIT
        from slappyengine.trigger import TriggerSystem
        from slappyengine.event_bus import subscribe, unsubscribe
        ts = TriggerSystem()
        ps = PitsSystem(ts, vehicles=[], pit_positions=[(100, 100, 200, 200, 1.0, 0.0)])
        v = _SlowVehicle()
        ts.update([v])
        ps._active_sessions[id(v)].repair_this_visit = MAX_REPAIR_PER_VISIT
        received = []
        h = subscribe("Pits.Exited", lambda e: received.append(e))
        ps.update(0.016)
        unsubscribe(h)
        ps.teardown()
        assert len(received) >= 1


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
        assert len(self._b()._grid) == 0

    def test_grid_size_positive(self):
        from systems.grid_builder import GRID_SIZE
        assert GRID_SIZE > 0


class TestVehicleGridBuilderPlace:
    def _b(self):
        from systems.grid_builder import VehicleGridBuilder
        return VehicleGridBuilder()

    def _place_cockpit(self, b):
        from entities.part import PartType
        return b.place(PartType.COCKPIT, 0, 0)

    def test_place_within_bounds_returns_true(self):
        b = self._b()
        assert self._place_cockpit(b) is True

    def test_place_adds_to_grid(self):
        b = self._b()
        self._place_cockpit(b)
        assert len(b._grid) == 1

    def test_place_out_of_bounds_returns_false(self):
        from entities.part import PartType
        from systems.grid_builder import GRID_SIZE, VehicleGridBuilder
        b = VehicleGridBuilder()
        assert b.place(PartType.COCKPIT, GRID_SIZE, 0) is False

    def test_place_occupied_cell_returns_false(self):
        from entities.part import PartType
        b = self._b()
        b.place(PartType.COCKPIT, 0, 0)
        assert b.place(PartType.ENGINE, 0, 0) is False

    def test_place_multiple_cells(self):
        from entities.part import PartType
        b = self._b()
        b.place(PartType.COCKPIT, 0, 0)
        b.place(PartType.ENGINE, 1, 0)
        b.place(PartType.WHEEL, 2, 0)
        assert len(b._grid) == 3


class TestVehicleGridBuilderRemove:
    def _b(self):
        from systems.grid_builder import VehicleGridBuilder
        return VehicleGridBuilder()

    def test_remove_existing_part_returns_it(self):
        from entities.part import PartType
        b = self._b()
        b.place(PartType.COCKPIT, 0, 0)
        part = b.remove(0, 0)
        assert part is not None

    def test_remove_nonexistent_returns_none(self):
        b = self._b()
        assert b.remove(5, 5) is None

    def test_remove_decrements_grid(self):
        from entities.part import PartType
        b = self._b()
        b.place(PartType.COCKPIT, 0, 0)
        b.remove(0, 0)
        assert len(b._grid) == 0


class TestVehicleGridBuilderValidate:
    def _b(self):
        from systems.grid_builder import VehicleGridBuilder
        return VehicleGridBuilder()

    def test_empty_grid_invalid_no_cockpit(self):
        ok, msg = self._b().validate()
        assert ok is False
        assert "COCKPIT" in msg

    def test_cockpit_only_invalid_no_engine(self):
        from entities.part import PartType
        b = self._b()
        b.place(PartType.COCKPIT, 0, 0)
        ok, msg = b.validate()
        assert ok is False
        assert "ENGINE" in msg

    def test_cockpit_engine_invalid_no_wheels(self):
        from entities.part import PartType
        b = self._b()
        b.place(PartType.COCKPIT, 0, 0)
        b.place(PartType.ENGINE, 1, 0)
        ok, msg = b.validate()
        assert ok is False
        assert "WHEEL" in msg.upper() or "wheel" in msg.lower()

    def test_cockpit_engine_two_wheels_valid(self):
        from entities.part import PartType
        b = self._b()
        b.place(PartType.COCKPIT, 0, 0)
        b.place(PartType.ENGINE, 1, 0)
        b.place(PartType.WHEEL, 2, 0)
        b.place(PartType.WHEEL, 3, 0)
        ok, msg = b.validate()
        assert ok is True

    def test_one_wheel_invalid(self):
        from entities.part import PartType
        b = self._b()
        b.place(PartType.COCKPIT, 0, 0)
        b.place(PartType.ENGINE, 1, 0)
        b.place(PartType.WHEEL, 2, 0)  # only 1 wheel
        ok, msg = b.validate()
        assert ok is False

    def test_validation_status_event_fired_on_place(self):
        from entities.part import PartType
        from slappyengine.event_bus import subscribe, unsubscribe
        b = self._b()
        received = []
        h = subscribe("Garage.ValidationStatus", lambda e: received.append(e))
        b.place(PartType.COCKPIT, 0, 0)
        unsubscribe(h)
        assert len(received) >= 1
