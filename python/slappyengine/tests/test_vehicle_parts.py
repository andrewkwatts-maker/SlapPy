"""Tests for slappyengine.vehicle_parts — VehiclePartSystem."""
from __future__ import annotations

import sys
import os
import math
import pytest

# Ensure the slappyengine package is importable when running directly from the
# tests directory (pytest discovers the package via conftest / sys.path anyway).
_pkg_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from slappyengine.vehicle_parts import (
    VehiclePartSystem,
    PartStats,
    PartSlot,
    PART_PRESETS,
    ENGINE_STANDARD,
    ENGINE_HEAVY,
    ENGINE_LIGHT,
    TURBO_NONE,
    TURBO_STANDARD,
    TURBO_TWIN,
    TRANS_AUTO,
    TRANS_MANUAL,
    TRANS_CVT,
    ROLL_CAGE_NONE,
    ROLL_CAGE_TUBE,
    ROLL_CAGE_FULL,
    ARMOR_NONE,
    ARMOR_LIGHT,
    ARMOR_MEDIUM,
    ARMOR_HEAVY,
    LIGHTS_NONE,
    LIGHTS_BASIC,
    LIGHTS_RALLY,
    LIGHTS_STADIUM,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh() -> VehiclePartSystem:
    """Return a VehiclePartSystem with no installed parts."""
    return VehiclePartSystem()


def _with(*parts) -> VehiclePartSystem:
    """Return a VehiclePartSystem with the given parts pre-installed."""
    sys_ = _fresh()
    for p in parts:
        sys_.install(p)
    return sys_


# ---------------------------------------------------------------------------
# Weight
# ---------------------------------------------------------------------------

class TestTotalWeight:
    def test_no_parts_returns_base_weight(self):
        s = _fresh()
        assert s.total_weight == VehiclePartSystem.BASE_WEIGHT

    def test_total_weight_includes_all_parts(self):
        s = _with(ENGINE_STANDARD, TURBO_STANDARD, TRANS_AUTO)
        expected = (
            VehiclePartSystem.BASE_WEIGHT
            + ENGINE_STANDARD.weight
            + TURBO_STANDARD.weight
            + TRANS_AUTO.weight
        )
        assert math.isclose(s.total_weight, expected, rel_tol=1e-9)

    def test_replacing_slot_does_not_double_count(self):
        s = _with(ENGINE_STANDARD)
        s.install(ENGINE_HEAVY)
        expected = VehiclePartSystem.BASE_WEIGHT + ENGINE_HEAVY.weight
        assert math.isclose(s.total_weight, expected, rel_tol=1e-9)

    def test_uninstall_removes_weight(self):
        s = _with(ENGINE_HEAVY)
        s.uninstall(PartSlot.ENGINE)
        assert math.isclose(s.total_weight, VehiclePartSystem.BASE_WEIGHT, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# Base stats (no parts)
# ---------------------------------------------------------------------------

class TestBaseStats:
    def test_no_parts_returns_base_max_speed(self):
        s = _fresh()
        assert math.isclose(s.max_speed, VehiclePartSystem.BASE_MAX_SPEED, rel_tol=1e-9)

    def test_no_parts_returns_base_fuel_rate(self):
        s = _fresh()
        assert math.isclose(s.fuel_rate, VehiclePartSystem.BASE_FUEL_RATE, rel_tol=1e-9)

    def test_no_parts_impact_absorption_is_zero(self):
        s = _fresh()
        assert s.impact_absorption == 0.0

    def test_no_parts_elastic_threshold_is_base(self):
        s = _fresh()
        assert math.isclose(
            s.elastic_threshold, VehiclePartSystem.BASE_ELASTIC_THRESHOLD, rel_tol=1e-9
        )

    def test_no_parts_headlight_range_is_280(self):
        s = _fresh()
        assert math.isclose(s.headlight_range, 280.0, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# Engine effects
# ---------------------------------------------------------------------------

class TestEngineEffects:
    def test_heavy_engine_increases_max_speed(self):
        base = _fresh()
        heavy = _with(ENGINE_HEAVY)
        assert heavy.max_speed > base.max_speed

    def test_light_engine_decreases_max_speed(self):
        base = _fresh()
        light = _with(ENGINE_LIGHT)
        assert light.max_speed < base.max_speed

    def test_heavy_engine_increases_fuel_rate(self):
        s = _with(ENGINE_HEAVY)
        assert s.fuel_rate > VehiclePartSystem.BASE_FUEL_RATE

    def test_light_engine_decreases_fuel_rate(self):
        s = _with(ENGINE_LIGHT)
        assert s.fuel_rate < VehiclePartSystem.BASE_FUEL_RATE


# ---------------------------------------------------------------------------
# Turbo effects
# ---------------------------------------------------------------------------

class TestTurboSpool:
    def test_turbo_zero_spool_at_zero_throttle(self):
        """At throttle=0, turbo spool should converge to 0."""
        s = _with(TURBO_STANDARD)
        # Tick for a long time at throttle=0 so spool decays
        for _ in range(200):
            s.tick(0.05, 0.0)
        assert s._turbo_spool < 0.01

    def test_turbo_spools_up_over_time(self):
        """After enough ticks at full throttle, spool should be near 1."""
        s = _with(TURBO_STANDARD)
        # TURBO_STANDARD.spool_time == 1.5 s; tick well past that
        for _ in range(100):
            s.tick(0.05, 1.0)
        assert s._turbo_spool > 0.95

    def test_turbo_twin_spools_faster_than_standard(self):
        """Twin turbo has lower spool_time, so it should reach higher spool
        level in the same number of ticks."""
        s_std  = _with(TURBO_STANDARD)
        s_twin = _with(TURBO_TWIN)
        for _ in range(10):
            s_std.tick(0.05, 1.0)
            s_twin.tick(0.05, 1.0)
        assert s_twin._turbo_spool >= s_std._turbo_spool

    def test_no_turbo_spool_instant(self):
        """No Turbo part: spool immediately tracks throttle (no lag)."""
        s = _with(TURBO_NONE)
        s.tick(0.016, 0.8)
        assert math.isclose(s._turbo_spool, 0.8, rel_tol=1e-9)

    def test_full_turbo_boosts_max_speed_above_no_turbo(self):
        """With turbo fully spooled at full throttle, max_speed should exceed
        the base engine-only value."""
        s_no_turbo = _with(ENGINE_STANDARD, TURBO_NONE)
        s_turbo    = _with(ENGINE_STANDARD, TURBO_STANDARD)
        # Spool up turbo fully
        for _ in range(200):
            s_turbo.tick(0.05, 1.0)
        assert s_turbo.max_speed > s_no_turbo.max_speed


# ---------------------------------------------------------------------------
# Roll cage effects
# ---------------------------------------------------------------------------

class TestRollCage:
    def test_no_roll_cage_zero_absorption(self):
        s = _with(ROLL_CAGE_NONE)
        assert math.isclose(s.impact_absorption, 0.0, abs_tol=1e-9)

    def test_tube_roll_cage_reduces_impact(self):
        s = _with(ROLL_CAGE_TUBE)
        assert s.impact_absorption > 0.0

    def test_full_exo_cage_higher_than_tube(self):
        tube = _with(ROLL_CAGE_TUBE)
        full = _with(ROLL_CAGE_FULL)
        assert full.impact_absorption > tube.impact_absorption

    def test_roll_cage_adds_elastic_threshold(self):
        s_no   = _fresh()
        s_cage = _with(ROLL_CAGE_FULL)
        assert s_cage.elastic_threshold > s_no.elastic_threshold


# ---------------------------------------------------------------------------
# Armor effects
# ---------------------------------------------------------------------------

class TestArmor:
    def test_armor_boosts_elastic_threshold(self):
        s_no    = _fresh()
        s_armor = _with(ARMOR_HEAVY)
        assert s_armor.elastic_threshold > s_no.elastic_threshold

    def test_heavier_armor_gives_higher_threshold(self):
        light  = _with(ARMOR_LIGHT)
        medium = _with(ARMOR_MEDIUM)
        heavy  = _with(ARMOR_HEAVY)
        assert light.elastic_threshold < medium.elastic_threshold < heavy.elastic_threshold

    def test_armor_contributes_to_impact_absorption(self):
        """Armor provides secondary absorption (armor_damage_reduction * 0.15)."""
        s_armor = _with(ARMOR_HEAVY)
        assert s_armor.impact_absorption > 0.0

    def test_armor_damage_reduction_formula(self):
        """ARMOR_MEDIUM: 100 kg → 5 panels. reduction = 1 - 0.85^5."""
        panels = max(1, int(ARMOR_MEDIUM.weight / 20.0))  # 5
        expected = 1.0 - (0.85 ** panels)
        assert math.isclose(ARMOR_MEDIUM.armor_damage_reduction, expected, rel_tol=1e-9)

    def test_no_armor_zero_damage_reduction(self):
        assert math.isclose(ARMOR_NONE.armor_damage_reduction, 0.0, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# Fuel
# ---------------------------------------------------------------------------

class TestFuel:
    def test_fuel_starts_at_100(self):
        s = _fresh()
        assert math.isclose(s.fuel, 100.0, rel_tol=1e-9)

    def test_fuel_drains_with_throttle(self):
        s = _with(ENGINE_STANDARD)
        initial = s.fuel
        s.tick(1.0, 1.0)  # 1 second at full throttle
        assert s.fuel < initial

    def test_fuel_does_not_drain_at_zero_throttle(self):
        s = _with(ENGINE_STANDARD)
        initial = s.fuel
        for _ in range(60):
            s.tick(1.0 / 60.0, 0.0)
        assert math.isclose(s.fuel, initial, rel_tol=1e-9)

    def test_out_of_fuel_kills_power(self):
        s = _with(ENGINE_STANDARD)
        s.fuel = 0.0
        assert s.effective_power == 0.0

    def test_out_of_fuel_property(self):
        s = _fresh()
        assert not s.out_of_fuel
        s.fuel = 0.0
        assert s.out_of_fuel

    def test_fuel_setter_clamps_to_0_100(self):
        s = _fresh()
        s.fuel = 150.0
        assert s.fuel == 100.0
        s.fuel = -10.0
        assert s.fuel == 0.0


# ---------------------------------------------------------------------------
# Transmission / shift lag
# ---------------------------------------------------------------------------

class TestTransmission:
    def test_manual_shift_adds_lag(self):
        s = _with(TRANS_MANUAL)
        s.shift_up()
        assert s._shift_lag > 0.0

    def test_manual_shift_causes_power_dip(self):
        s_no_lag = _with(TRANS_MANUAL, ENGINE_STANDARD)
        s_lag    = _with(TRANS_MANUAL, ENGINE_STANDARD)
        s_lag.shift_up()  # introduces lag
        # During lag, effective_power is halved at the trans step
        assert s_lag.effective_power < s_no_lag.effective_power

    def test_shift_lag_decays_over_time(self):
        s = _with(TRANS_MANUAL)
        s.shift_up()
        initial_lag = s._shift_lag
        s.tick(initial_lag + 0.1, 0.0)
        assert s._shift_lag == 0.0

    def test_cvt_no_shift_lag(self):
        """CVT has no discrete gears — shift_up/down should not add lag."""
        s = _with(TRANS_CVT)
        s.shift_up()
        assert s._shift_lag == 0.0

    def test_auto_no_shift_lag(self):
        """Auto transmission: shift_up is a no-op (no manual lag)."""
        s = _with(TRANS_AUTO)
        s.shift_up()
        assert s._shift_lag == 0.0

    def test_manual_gear_count_capped(self):
        s = _with(TRANS_MANUAL)
        for _ in range(20):
            s.shift_up()
        assert s._current_gear <= TRANS_MANUAL.gear_count

    def test_manual_gear_floor_at_1(self):
        s = _with(TRANS_MANUAL)
        for _ in range(20):
            s.shift_down()
        assert s._current_gear >= 1


# ---------------------------------------------------------------------------
# Lights
# ---------------------------------------------------------------------------

class TestLights:
    def test_headlight_range_base_with_no_lights(self):
        s = _fresh()
        assert math.isclose(s.headlight_range, 280.0, rel_tol=1e-9)

    def test_headlight_range_with_rally_lights(self):
        s = _with(LIGHTS_RALLY)
        assert math.isclose(s.headlight_range, 280.0 + LIGHTS_RALLY.headlight_range_bonus, rel_tol=1e-9)

    def test_stadium_rig_gives_maximum_range(self):
        rally   = _with(LIGHTS_RALLY)
        stadium = _with(LIGHTS_STADIUM)
        assert stadium.headlight_range > rally.headlight_range


# ---------------------------------------------------------------------------
# Impact absorption cap
# ---------------------------------------------------------------------------

class TestImpactAbsorptionCap:
    def test_impact_absorption_cap_at_0_7(self):
        """Even with best cage + best armor, absorption must not exceed 0.7."""
        s = _with(ROLL_CAGE_FULL, ARMOR_HEAVY)
        assert s.impact_absorption <= 0.7

    def test_combined_cage_and_armor_higher_than_cage_alone(self):
        cage_only  = _with(ROLL_CAGE_FULL)
        cage_armor = _with(ROLL_CAGE_FULL, ARMOR_HEAVY)
        assert cage_armor.impact_absorption >= cage_only.impact_absorption


# ---------------------------------------------------------------------------
# install_from_name
# ---------------------------------------------------------------------------

class TestInstallFromName:
    def test_install_from_name_valid(self):
        s = _fresh()
        result = s.install_from_name("Standard Engine")
        assert result is True
        assert s.get(PartSlot.ENGINE) is ENGINE_STANDARD

    def test_install_from_name_invalid_returns_false(self):
        s = _fresh()
        result = s.install_from_name("Does Not Exist")
        assert result is False

    def test_all_presets_are_installable(self):
        """Every entry in PART_PRESETS must be accessible by name."""
        for name in PART_PRESETS:
            s = _fresh()
            assert s.install_from_name(name) is True, f"Failed to install preset: {name!r}"


# ---------------------------------------------------------------------------
# get / uninstall
# ---------------------------------------------------------------------------

class TestGetUninstall:
    def test_get_returns_installed_part(self):
        s = _with(ENGINE_HEAVY)
        assert s.get(PartSlot.ENGINE) is ENGINE_HEAVY

    def test_get_returns_none_for_empty_slot(self):
        s = _fresh()
        assert s.get(PartSlot.ENGINE) is None

    def test_uninstall_empties_slot(self):
        s = _with(ENGINE_HEAVY)
        s.uninstall(PartSlot.ENGINE)
        assert s.get(PartSlot.ENGINE) is None

    def test_uninstall_noop_on_empty_slot(self):
        s = _fresh()
        s.uninstall(PartSlot.ENGINE)   # must not raise
        assert s.get(PartSlot.ENGINE) is None
