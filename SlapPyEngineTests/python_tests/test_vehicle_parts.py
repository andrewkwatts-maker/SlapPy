"""Engine tests for VehiclePartSystem — headless, no GPU."""
from __future__ import annotations
import pytest


class TestVehiclePartSystemInit:
    def test_default_fuel_full(self):
        from slappyengine.vehicle_parts import VehiclePartSystem
        vps = VehiclePartSystem()
        assert vps.fuel == pytest.approx(100.0)

    def test_default_no_parts(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, PartSlot
        vps = VehiclePartSystem()
        for slot in PartSlot:
            assert vps.get(slot) is None

    def test_default_weight_is_base(self):
        from slappyengine.vehicle_parts import VehiclePartSystem
        vps = VehiclePartSystem()
        assert vps.total_weight == pytest.approx(VehiclePartSystem.BASE_WEIGHT)

    def test_default_not_out_of_fuel(self):
        from slappyengine.vehicle_parts import VehiclePartSystem
        vps = VehiclePartSystem()
        assert vps.out_of_fuel is False


class TestInstallUninstall:
    def test_install_engine(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, PartSlot, ENGINE_STANDARD
        vps = VehiclePartSystem()
        vps.install(ENGINE_STANDARD)
        assert vps.get(PartSlot.ENGINE) is ENGINE_STANDARD

    def test_install_replaces_existing(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, PartSlot, ENGINE_STANDARD, ENGINE_HEAVY
        vps = VehiclePartSystem()
        vps.install(ENGINE_STANDARD)
        vps.install(ENGINE_HEAVY)
        assert vps.get(PartSlot.ENGINE) is ENGINE_HEAVY

    def test_uninstall_clears_slot(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, PartSlot, ENGINE_STANDARD
        vps = VehiclePartSystem()
        vps.install(ENGINE_STANDARD)
        vps.uninstall(PartSlot.ENGINE)
        assert vps.get(PartSlot.ENGINE) is None

    def test_uninstall_empty_slot_no_crash(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, PartSlot
        vps = VehiclePartSystem()
        vps.uninstall(PartSlot.ENGINE)  # should not raise

    def test_install_from_name_known(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, PartSlot
        vps = VehiclePartSystem()
        result = vps.install_from_name("Heavy V8")
        assert result is True
        assert vps.get(PartSlot.ENGINE) is not None

    def test_install_from_name_unknown_returns_false(self):
        from slappyengine.vehicle_parts import VehiclePartSystem
        vps = VehiclePartSystem()
        result = vps.install_from_name("NOT_A_PART")
        assert result is False


class TestWeightAndPower:
    def test_engine_adds_weight(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, ENGINE_HEAVY
        vps = VehiclePartSystem()
        base = vps.total_weight
        vps.install(ENGINE_HEAVY)
        assert vps.total_weight > base

    def test_armor_adds_weight(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, ARMOR_HEAVY
        vps = VehiclePartSystem()
        base = vps.total_weight
        vps.install(ARMOR_HEAVY)
        assert vps.total_weight > base

    def test_effective_power_no_parts_equals_base(self):
        from slappyengine.vehicle_parts import VehiclePartSystem
        vps = VehiclePartSystem()
        vps._turbo_spool = 1.0
        assert vps.effective_power == pytest.approx(VehiclePartSystem.BASE_POWER)

    def test_heavy_engine_increases_power(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, ENGINE_HEAVY
        base_vps = VehiclePartSystem()
        heavy_vps = VehiclePartSystem()
        heavy_vps.install(ENGINE_HEAVY)
        assert heavy_vps.effective_power > base_vps.effective_power

    def test_turbo_increases_power_when_spooled(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, TURBO_STANDARD
        vps = VehiclePartSystem()
        base_power = vps.effective_power
        vps.install(TURBO_STANDARD)
        vps._turbo_spool = 1.0
        assert vps.effective_power > base_power

    def test_turbo_unspooled_gives_minimal_boost(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, TURBO_STANDARD
        no_turbo = VehiclePartSystem()
        with_turbo = VehiclePartSystem()
        with_turbo.install(TURBO_STANDARD)
        with_turbo._turbo_spool = 0.0
        assert with_turbo.effective_power == pytest.approx(no_turbo.effective_power, rel=0.01)

    def test_out_of_fuel_zeroes_power(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, ENGINE_HEAVY
        vps = VehiclePartSystem()
        vps.install(ENGINE_HEAVY)
        vps._fuel = 0.0
        assert vps.effective_power == pytest.approx(0.0)

    def test_max_speed_scales_with_power(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, ENGINE_HEAVY
        base = VehiclePartSystem()
        fast = VehiclePartSystem()
        fast.install(ENGINE_HEAVY)
        assert fast.max_speed > base.max_speed


class TestFuel:
    def test_tick_drains_fuel_at_full_throttle(self):
        from slappyengine.vehicle_parts import VehiclePartSystem
        vps = VehiclePartSystem()
        vps.tick(1.0, throttle=1.0)
        assert vps.fuel < 100.0

    def test_tick_no_drain_below_threshold(self):
        from slappyengine.vehicle_parts import VehiclePartSystem
        vps = VehiclePartSystem()
        vps.tick(1.0, throttle=0.05)
        assert vps.fuel == pytest.approx(100.0)

    def test_fuel_setter_clamps_max(self):
        from slappyengine.vehicle_parts import VehiclePartSystem
        vps = VehiclePartSystem()
        vps.fuel = 200.0
        assert vps.fuel == pytest.approx(100.0)

    def test_fuel_setter_clamps_min(self):
        from slappyengine.vehicle_parts import VehiclePartSystem
        vps = VehiclePartSystem()
        vps.fuel = -50.0
        assert vps.fuel == pytest.approx(0.0)

    def test_out_of_fuel_triggers_when_depleted(self):
        from slappyengine.vehicle_parts import VehiclePartSystem
        vps = VehiclePartSystem()
        vps.fuel = 0.0
        assert vps.out_of_fuel is True

    def test_fuel_rate_modified_by_engine(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, ENGINE_HEAVY
        base = VehiclePartSystem()
        with_eng = VehiclePartSystem()
        with_eng.install(ENGINE_HEAVY)
        # Heavy engine should have different fuel rate (likely higher)
        assert with_eng.fuel_rate != pytest.approx(base.fuel_rate)


class TestTurboSpool:
    def test_tick_spools_up_turbo(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, TURBO_STANDARD
        vps = VehiclePartSystem()
        vps.install(TURBO_STANDARD)
        assert vps._turbo_spool == pytest.approx(0.0)
        vps.tick(1.0, throttle=1.0)
        assert vps._turbo_spool > 0.0

    def test_no_turbo_spool_equals_throttle(self):
        from slappyengine.vehicle_parts import VehiclePartSystem
        vps = VehiclePartSystem()
        vps.tick(0.016, throttle=0.8)
        assert vps._turbo_spool == pytest.approx(0.8)

    def test_spool_approaches_target_throttle(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, TURBO_TWIN
        vps = VehiclePartSystem()
        vps.install(TURBO_TWIN)
        for _ in range(200):
            vps.tick(0.016, throttle=1.0)
        assert vps._turbo_spool > 0.9


class TestShiftLag:
    def test_shift_up_with_manual_adds_lag(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, TRANS_MANUAL
        vps = VehiclePartSystem()
        vps.install(TRANS_MANUAL)
        vps.shift_up()
        assert vps._shift_lag > 0.0

    def test_shift_down_with_manual_adds_lag(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, TRANS_MANUAL
        vps = VehiclePartSystem()
        vps.install(TRANS_MANUAL)
        vps._current_gear = 3
        vps.shift_down()
        assert vps._shift_lag > 0.0

    def test_shift_no_manual_trans_no_lag(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, TRANS_AUTO
        vps = VehiclePartSystem()
        vps.install(TRANS_AUTO)
        vps.shift_up()
        assert vps._shift_lag == pytest.approx(0.0)

    def test_shift_lag_reduces_power(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, TRANS_MANUAL
        vps = VehiclePartSystem()
        vps.install(TRANS_MANUAL)
        normal_power = vps.effective_power
        vps._shift_lag = 0.25
        assert vps.effective_power < normal_power

    def test_tick_reduces_shift_lag(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, TRANS_MANUAL
        vps = VehiclePartSystem()
        vps.install(TRANS_MANUAL)
        vps.shift_up()
        before = vps._shift_lag
        vps.tick(0.1, throttle=0.0)
        assert vps._shift_lag < before

    def test_shift_up_at_max_gear_no_crash(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, TRANS_MANUAL
        vps = VehiclePartSystem()
        vps.install(TRANS_MANUAL)
        for _ in range(20):
            vps.shift_up()  # should clamp at max gear

    def test_shift_down_at_gear_1_no_crash(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, TRANS_MANUAL
        vps = VehiclePartSystem()
        vps.install(TRANS_MANUAL)
        for _ in range(5):
            vps.shift_down()  # should clamp at 1


class TestImpactAbsorption:
    def test_no_cage_no_armor_zero_absorption(self):
        from slappyengine.vehicle_parts import VehiclePartSystem
        vps = VehiclePartSystem()
        assert vps.impact_absorption == pytest.approx(0.0)

    def test_roll_cage_adds_absorption(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, ROLL_CAGE_FULL
        vps = VehiclePartSystem()
        vps.install(ROLL_CAGE_FULL)
        assert vps.impact_absorption > 0.0

    def test_armor_adds_absorption(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, ARMOR_HEAVY
        vps = VehiclePartSystem()
        vps.install(ARMOR_HEAVY)
        assert vps.impact_absorption > 0.0

    def test_absorption_capped_at_07(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, ROLL_CAGE_FULL, ARMOR_HEAVY
        vps = VehiclePartSystem()
        vps.install(ROLL_CAGE_FULL)
        vps.install(ARMOR_HEAVY)
        assert vps.impact_absorption <= 0.7


class TestElasticThreshold:
    def test_default_threshold_equals_base(self):
        from slappyengine.vehicle_parts import VehiclePartSystem
        vps = VehiclePartSystem()
        assert vps.elastic_threshold == pytest.approx(VehiclePartSystem.BASE_ELASTIC_THRESHOLD)

    def test_armor_increases_threshold(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, ARMOR_HEAVY
        base = VehiclePartSystem()
        with_armor = VehiclePartSystem()
        with_armor.install(ARMOR_HEAVY)
        assert with_armor.elastic_threshold >= base.elastic_threshold


class TestHeadlightRange:
    def test_no_lights_base_range(self):
        from slappyengine.vehicle_parts import VehiclePartSystem
        vps = VehiclePartSystem()
        assert vps.headlight_range == pytest.approx(280.0)

    def test_rally_lights_increase_range(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, LIGHTS_RALLY
        vps = VehiclePartSystem()
        vps.install(LIGHTS_RALLY)
        assert vps.headlight_range > 280.0

    def test_stadium_lights_increase_range_more(self):
        from slappyengine.vehicle_parts import VehiclePartSystem, LIGHTS_RALLY, LIGHTS_STADIUM
        rally = VehiclePartSystem()
        rally.install(LIGHTS_RALLY)
        stadium = VehiclePartSystem()
        stadium.install(LIGHTS_STADIUM)
        assert stadium.headlight_range >= rally.headlight_range
