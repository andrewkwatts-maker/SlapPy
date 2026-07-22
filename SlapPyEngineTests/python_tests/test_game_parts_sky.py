"""Headless tests for Ochema Circuit: VehiclePart, AIBuildGenerator, SkyEntity."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("pharos_engine.compute.asset_compute", MagicMock())

_GAME_ROOT = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Ochema Circuit"
_GAME_STR = str(_GAME_ROOT)
if _GAME_STR not in sys.path:
    sys.path.insert(0, _GAME_STR)


# =============================================================================
# VehiclePart
# =============================================================================

class TestVehiclePartInit:
    def _p(self, part_type=None):
        from entities.part import VehiclePart, PartType
        return VehiclePart(part_type=part_type or PartType.COCKPIT, grid_x=0, grid_y=0)

    def test_instantiates(self):
        assert self._p() is not None

    def test_hp_positive(self):
        assert self._p().hp > 0

    def test_mass_positive(self):
        assert self._p().mass > 0

    def test_alive_initially(self):
        assert self._p().alive is True

    def test_color_is_tuple(self):
        p = self._p()
        assert isinstance(p.color, tuple)

    def test_tier_zero_initially(self):
        assert self._p().tier == 0

    def test_thrust_mult_one(self):
        assert self._p().thrust_mult == 1.0

    def test_grip_mult_one(self):
        assert self._p().grip_mult == 1.0

    def test_damage_mult_one(self):
        assert self._p().damage_mult == 1.0

    def test_grid_coordinates_stored(self):
        from entities.part import VehiclePart, PartType
        p = VehiclePart(PartType.ENGINE, grid_x=3, grid_y=5)
        assert p.grid_x == 3
        assert p.grid_y == 5

    def test_part_type_stored(self):
        from entities.part import VehiclePart, PartType
        p = VehiclePart(PartType.WHEEL, grid_x=0, grid_y=0)
        assert p.part_type == PartType.WHEEL


class TestVehiclePartTypes:
    def test_all_part_types_instantiate(self):
        from entities.part import VehiclePart, PartType
        for pt in PartType:
            p = VehiclePart(part_type=pt, grid_x=0, grid_y=0)
            assert p.hp > 0

    def test_cockpit_has_correct_type(self):
        from entities.part import VehiclePart, PartType
        p = VehiclePart(PartType.COCKPIT)
        assert p.part_type == PartType.COCKPIT

    def test_engine_has_correct_type(self):
        from entities.part import VehiclePart, PartType
        p = VehiclePart(PartType.ENGINE)
        assert p.part_type == PartType.ENGINE

    def test_armor_has_correct_type(self):
        from entities.part import VehiclePart, PartType
        p = VehiclePart(PartType.ARMOR)
        assert p.part_type == PartType.ARMOR

    def test_wheel_has_correct_type(self):
        from entities.part import VehiclePart, PartType
        p = VehiclePart(PartType.WHEEL)
        assert p.part_type == PartType.WHEEL

    def test_weapon_has_correct_type(self):
        from entities.part import VehiclePart, PartType
        p = VehiclePart(PartType.WEAPON)
        assert p.part_type == PartType.WEAPON


class TestVehiclePartDamage:
    def _p(self):
        from entities.part import VehiclePart, PartType
        return VehiclePart(PartType.COCKPIT, grid_x=0, grid_y=0)

    def test_take_damage_reduces_hp(self):
        p = self._p()
        initial_hp = p.hp
        p.take_damage(10.0)
        assert p.hp < initial_hp

    def test_take_damage_returns_false_when_not_destroyed(self):
        p = self._p()
        assert p.take_damage(1.0) is False
        assert p.alive is True

    def test_take_damage_returns_true_when_destroyed(self):
        p = self._p()
        destroyed = p.take_damage(p.hp)
        assert destroyed is True

    def test_alive_false_after_fatal_damage(self):
        p = self._p()
        p.take_damage(p.hp)
        assert p.alive is False

    def test_hp_floors_at_zero(self):
        p = self._p()
        p.take_damage(p.hp * 10)
        assert p.hp == 0.0

    def test_partial_damage_alive(self):
        p = self._p()
        p.take_damage(p.hp / 2)
        assert p.alive is True

    def test_multiple_hits_accumulate(self):
        p = self._p()
        orig = p.hp
        hit = orig / 4
        p.take_damage(hit)
        p.take_damage(hit)
        p.take_damage(hit)
        p.take_damage(hit)
        # 4 × (orig/4) = orig — should be exactly dead
        assert p.alive is False or p.hp == 0.0


# =============================================================================
# AIBuildGenerator
# =============================================================================

class TestAIBuildGenerator:
    def _build(self, budget=500):
        from systems.ai_build_generator import generate_ai_build
        return generate_ai_build(budget=budget)

    def test_returns_dict(self):
        assert isinstance(self._build(), dict)

    def test_all_part_types_present(self):
        build = self._build()
        for pt in ["cockpit", "engine", "armor", "wheel", "weapon"]:
            assert pt in build

    def test_tiers_non_negative(self):
        build = self._build()
        for pt, tier in build.items():
            assert tier >= 0

    def test_zero_budget_all_tier_zero(self):
        from systems.ai_build_generator import generate_ai_build
        build = generate_ai_build(budget=0)
        assert all(tier == 0 for tier in build.values())

    def test_large_budget_some_upgrades(self):
        from systems.ai_build_generator import generate_ai_build
        build = generate_ai_build(budget=100000)
        assert any(tier > 0 for tier in build.values())

    def test_small_budget_mostly_tier_zero(self):
        from systems.ai_build_generator import generate_ai_build
        build = generate_ai_build(budget=1)
        # With budget=1, almost nothing can be upgraded
        assert sum(build.values()) <= 1

    def test_returns_consistent_structure(self):
        from systems.ai_build_generator import generate_ai_build
        b1 = generate_ai_build(budget=300)
        b2 = generate_ai_build(budget=300)
        assert set(b1.keys()) == set(b2.keys())

    def test_budget_not_exceeded_under_large_budget(self):
        from systems.ai_build_generator import generate_ai_build
        import yaml
        from pathlib import Path as _P
        shop = yaml.safe_load((_P(_GAME_STR) / "config.yml").read_text()).get("shop", {})
        budget = 1000
        build = generate_ai_build(budget=budget)
        total_cost = 0
        for pt, tier_idx in build.items():
            tiers = shop.get(pt, {}).get("tiers", [{}])
            for i in range(1, tier_idx + 1):
                if i < len(tiers):
                    total_cost += int(tiers[i].get("cost", 0))
        assert total_cost <= budget

    def test_deterministic_for_same_seed(self):
        import random
        from systems.ai_build_generator import generate_ai_build
        random.seed(42)
        b1 = generate_ai_build(budget=500)
        random.seed(42)
        b2 = generate_ai_build(budget=500)
        assert b1 == b2


# =============================================================================
# SkyEntity
# =============================================================================

class TestSkyEntityInit:
    def _s(self, mode="night"):
        from entities.sky import SkyEntity
        return SkyEntity(width=320, height=240, mode=mode)

    def test_instantiates(self):
        assert self._s() is not None

    def test_mode_stored(self):
        assert self._s(mode="night").mode == "night"

    def test_day_mode(self):
        assert self._s(mode="day").mode == "day"

    def test_time_of_day_initial_half(self):
        s = self._s()
        assert abs(s.time_of_day - 0.5) < 0.01

    def test_moon_phase_zero(self):
        assert self._s().moon_phase == 0.0

    def test_layer_created(self):
        s = self._s()
        assert s._layer is not None

    def test_layers_not_empty(self):
        s = self._s()
        assert len(s.layers) > 0


class TestSkyEntityTick:
    def _s(self):
        from entities.sky import SkyEntity
        return SkyEntity(width=160, height=120, mode="night")

    def test_tick_advances_time_of_day(self):
        s = self._s()
        initial = s.time_of_day
        s.tick(0.016)
        assert s.time_of_day != initial

    def test_time_of_day_stays_in_range(self):
        s = self._s()
        for _ in range(1000):
            s.tick(1.0)
        assert 0.0 <= s.time_of_day <= 1.0

    def test_time_wraps_around(self):
        s = self._s()
        s.time_of_day = 0.999
        s.tick(100.0)  # big advance to wrap
        assert 0.0 <= s.time_of_day <= 1.0

    def test_tick_zero_no_change(self):
        s = self._s()
        initial = s.time_of_day
        s.tick(0.0)
        assert abs(s.time_of_day - initial) < 1e-10


class TestSkyEntityMode:
    def _s(self, mode="night"):
        from entities.sky import SkyEntity
        return SkyEntity(width=160, height=120, mode=mode)

    def test_set_mode_night(self):
        s = self._s(mode="day")
        s.mode = "night"
        assert s.mode == "night"

    def test_set_mode_day(self):
        s = self._s(mode="night")
        s.mode = "day"
        assert s.mode == "day"

    def test_same_mode_no_rebuild(self):
        s = self._s(mode="night")
        layer_before = s._layer
        s.mode = "night"  # same — should not rebuild
        assert s._layer is layer_before

    def test_layer_updated_after_mode_change(self):
        s = self._s(mode="night")
        s.mode = "day"
        assert s._layer is not None

    def test_sky_is_observable(self):
        from pharos_engine.event_bus import Observable
        from entities.sky import SkyEntity
        assert issubclass(SkyEntity, Observable)

    def test_time_of_day_is_tracked_attr(self):
        from pharos_engine.event_bus import subscribe, unsubscribe
        from entities.sky import SkyEntity
        s = SkyEntity(width=64, height=48, mode="night")
        received = []
        h = subscribe("SkyEntity.time_of_day", lambda e: received.append(e))
        s.time_of_day = 0.9
        unsubscribe(h)
        assert len(received) >= 1
