"""Tests for pharos_engine.deform_modes."""
from __future__ import annotations
import dataclasses
import pytest

from pharos_engine.deform_modes import (
    DeformSimMode,
    DecayMode,
    DestroyMode,
    MaterialPreset,
    CrackMode,
    PhysicsCoupling,
    RepairMode,
    SimFrequency,
    ZoneConfig,
    MaterialConfig,
    MATERIAL_CONFIGS,
    resolve_material,
    register_material,
    unregister_material,
    get_material,
    list_materials,
    _CUSTOM_MATERIALS,
)


# ---------------------------------------------------------------------------
# Enum member presence
# ---------------------------------------------------------------------------

class TestDeformSimMode:
    def test_members(self):
        names = {m.name for m in DeformSimMode}
        assert names == {"ALWAYS_ON", "COLLISION_TRIGGERED", "MANUAL"}

    def test_values_are_strings(self):
        for m in DeformSimMode:
            assert isinstance(m.value, str)


class TestDecayMode:
    def test_members(self):
        names = {m.name for m in DecayMode}
        assert names == {"CONSTANT", "CURVE", "NONE"}


class TestDestroyMode:
    def test_members(self):
        names = {m.name for m in DestroyMode}
        assert names == {"PERSIST", "FRAGMENT", "REMOVE", "RESPAWN", "DISABLE"}


class TestMaterialPreset:
    def test_members(self):
        names = {m.name for m in MaterialPreset}
        assert names == {
            "METAL", "GLASS", "RUBBER", "WOOD", "STONE",
            "CLOTH", "ICE", "ORGANIC", "CUSTOM",
        }

    def test_values_are_strings(self):
        for m in MaterialPreset:
            assert isinstance(m.value, str)


class TestCrackMode:
    def test_members(self):
        names = {m.name for m in CrackMode}
        assert names == {"NONE", "RADIAL", "GRAIN", "STRUCTURAL"}


class TestPhysicsCoupling:
    def test_members(self):
        names = {m.name for m in PhysicsCoupling}
        assert names == {"ISOLATED", "MASS", "DRAG", "COM", "FULL"}


class TestRepairMode:
    def test_members(self):
        names = {m.name for m in RepairMode}
        assert names == {"NONE", "AUTO", "AUTO_CURVE", "EVENT_ONLY", "BUDGET"}


class TestSimFrequency:
    def test_members(self):
        names = {m.name for m in SimFrequency}
        assert names == {"EVERY_FRAME", "EVERY_N_FRAMES", "LOD_DISTANCE", "BUDGET_DRIVEN"}


# ---------------------------------------------------------------------------
# MATERIAL_CONFIGS coverage
# ---------------------------------------------------------------------------

class TestMaterialConfigs:
    def test_all_presets_present(self):
        """Every MaterialPreset must have an entry in MATERIAL_CONFIGS."""
        for preset in MaterialPreset:
            assert preset in MATERIAL_CONFIGS, f"Missing config for {preset}"

    def test_all_values_are_material_config(self):
        for preset, cfg in MATERIAL_CONFIGS.items():
            assert isinstance(cfg, MaterialConfig), (
                f"MATERIAL_CONFIGS[{preset}] is {type(cfg)}, expected MaterialConfig"
            )

    def test_metal_elastic_threshold(self):
        cfg = MATERIAL_CONFIGS[MaterialPreset.METAL]
        assert cfg.elastic_threshold == 80.0

    def test_glass_elastic_threshold(self):
        cfg = MATERIAL_CONFIGS[MaterialPreset.GLASS]
        assert cfg.elastic_threshold == 5.0

    def test_rubber_elastic_threshold(self):
        cfg = MATERIAL_CONFIGS[MaterialPreset.RUBBER]
        assert cfg.elastic_threshold == 200.0

    def test_custom_uses_all_defaults(self):
        cfg = MATERIAL_CONFIGS[MaterialPreset.CUSTOM]
        defaults = MaterialConfig()
        assert cfg == defaults


# ---------------------------------------------------------------------------
# resolve_material
# ---------------------------------------------------------------------------

class TestResolveMaterial:
    def test_no_override_returns_preset_config(self):
        cfg = resolve_material(MaterialPreset.METAL)
        assert cfg.elastic_threshold == 80.0
        assert cfg.physics_coupling == PhysicsCoupling.COM

    def test_override_elastic_threshold(self):
        cfg = resolve_material(MaterialPreset.METAL, elastic_threshold=42.0)
        assert cfg.elastic_threshold == 42.0

    def test_override_does_not_mutate_original(self):
        resolve_material(MaterialPreset.METAL, elastic_threshold=1.0)
        assert MATERIAL_CONFIGS[MaterialPreset.METAL].elastic_threshold == 80.0

    def test_override_preserves_other_fields(self):
        cfg = resolve_material(MaterialPreset.METAL, elastic_threshold=99.0)
        assert cfg.physics_coupling == PhysicsCoupling.COM
        assert cfg.decay_mode == DecayMode.CURVE

    def test_returns_material_config_instance(self):
        cfg = resolve_material(MaterialPreset.GLASS)
        assert isinstance(cfg, MaterialConfig)

    def test_multiple_overrides(self):
        cfg = resolve_material(
            MaterialPreset.WOOD,
            elastic_threshold=50.0,
            crack_count=8,
        )
        assert cfg.elastic_threshold == 50.0
        assert cfg.crack_count == 8

    def test_glass_crack_mode_radial(self):
        cfg = resolve_material(MaterialPreset.GLASS)
        assert cfg.crack_mode == CrackMode.RADIAL


# ---------------------------------------------------------------------------
# ZoneConfig dataclass
# ---------------------------------------------------------------------------

class TestZoneConfig:
    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(ZoneConfig)

    def test_required_field_name(self):
        z = ZoneConfig(name="front_bumper")
        assert z.name == "front_bumper"

    def test_default_integrity_threshold(self):
        z = ZoneConfig(name="test")
        assert z.integrity_threshold == 0.0

    def test_default_material_is_none(self):
        z = ZoneConfig(name="test")
        assert z.material is None

    def test_default_on_destroy_event(self):
        z = ZoneConfig(name="test")
        assert z.on_destroy_event == "Deform.ZoneDestroyed"

    def test_default_strength_scale(self):
        z = ZoneConfig(name="test")
        assert z.strength_scale == 1.0

    def test_all_fields_overridable(self):
        z = ZoneConfig(
            name="engine_block",
            integrity_threshold=0.25,
            material=MaterialPreset.METAL,
            on_destroy_event="Car.EngineDestroyed",
            strength_scale=1.5,
        )
        assert z.name == "engine_block"
        assert z.integrity_threshold == 0.25
        assert z.material == MaterialPreset.METAL
        assert z.on_destroy_event == "Car.EngineDestroyed"
        assert z.strength_scale == 1.5

    def test_missing_name_raises(self):
        with pytest.raises(TypeError):
            ZoneConfig()  # name is required


# ---------------------------------------------------------------------------
# MaterialConfig dataclass
# ---------------------------------------------------------------------------

class TestMaterialConfig:
    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(MaterialConfig)

    def test_default_construction(self):
        cfg = MaterialConfig()
        assert cfg.elastic_threshold == 80.0
        assert cfg.spring_decay == 0.94
        assert cfg.decay_mode == DecayMode.CONSTANT
        assert cfg.decay_curve is None
        assert cfg.crack_mode == CrackMode.NONE
        assert cfg.crack_count == 6
        assert cfg.crack_length_px == 40.0
        assert cfg.destroy_mode == DestroyMode.PERSIST
        assert cfg.repair_mode == RepairMode.EVENT_ONLY
        assert cfg.repair_rate == 1.0
        assert cfg.physics_coupling == PhysicsCoupling.ISOLATED
        assert cfg.sim_mode == DeformSimMode.COLLISION_TRIGGERED
        assert cfg.sim_frequency == SimFrequency.EVERY_FRAME
        assert cfg.settle_threshold == 0.5
        assert cfg.settling_ramp_rate == 4.0

    def test_equality(self):
        a = MaterialConfig()
        b = MaterialConfig()
        assert a == b

    def test_inequality_on_field_change(self):
        a = MaterialConfig()
        b = MaterialConfig(elastic_threshold=1.0)
        assert a != b

    def test_dataclass_replace(self):
        base = MaterialConfig()
        patched = dataclasses.replace(base, crack_count=10)
        assert patched.crack_count == 10
        assert base.crack_count == 6  # original unchanged


# ---------------------------------------------------------------------------
# Custom material registry
# ---------------------------------------------------------------------------

class TestMaterialRegistry:
    """Tests for register_material / unregister_material / get_material / list_materials."""

    def setup_method(self):
        """Ensure the custom registry is clean before each test."""
        _CUSTOM_MATERIALS.clear()

    def teardown_method(self):
        """Leave the registry clean after each test."""
        _CUSTOM_MATERIALS.clear()

    # --- register / get ----------------------------------------------------

    def test_register_custom_material(self):
        cfg = MaterialConfig(elastic_threshold=99.0)
        register_material("my_material", cfg)
        result = get_material("my_material")
        assert result is cfg
        assert result.elastic_threshold == 99.0

    def test_get_unknown_material_returns_none(self):
        result = get_material("does_not_exist")
        assert result is None

    # --- unregister --------------------------------------------------------

    def test_unregister_material(self):
        cfg = MaterialConfig(elastic_threshold=42.0)
        register_material("temp_material", cfg)
        assert get_material("temp_material") is cfg
        unregister_material("temp_material")
        assert get_material("temp_material") is None

    def test_unregister_nonexistent_is_noop(self):
        """unregister_material on an unknown name must not raise."""
        unregister_material("never_registered")  # should be silent

    # --- list_materials ----------------------------------------------------

    def test_list_materials_includes_custom(self):
        register_material("zz_custom", MaterialConfig())
        names = list_materials()
        assert "zz_custom" in names
        # Built-ins must also be present
        for preset in MaterialPreset:
            assert preset.value in names

    def test_list_materials_builtin_order(self):
        """Built-in presets appear before custom entries."""
        register_material("alpha_custom", MaterialConfig())
        names = list_materials()
        builtin_names = [p.value for p in MaterialPreset]
        # First N names must equal the built-in list
        assert names[: len(builtin_names)] == builtin_names

    def test_list_materials_no_duplicates_for_custom_shadowing(self):
        """When a custom name matches a built-in, it should not appear twice."""
        register_material("metal", MaterialConfig(elastic_threshold=1.0))
        names = list_materials()
        assert names.count("metal") == 1

    # --- get by enum value -------------------------------------------------

    def test_get_material_by_enum_value(self):
        result = get_material("metal")
        expected = MATERIAL_CONFIGS[MaterialPreset.METAL]
        # Should return the built-in config (no custom registered)
        assert result is expected
        assert result.elastic_threshold == 80.0

    def test_get_material_glass_by_value(self):
        result = get_material("glass")
        assert result is not None
        assert result.elastic_threshold == 5.0

    # --- override built-in preset ------------------------------------------

    def test_override_preset(self):
        """Registering under a built-in name shadows the built-in via get_material."""
        custom_cfg = MaterialConfig(elastic_threshold=1.0)
        register_material("metal", custom_cfg)
        result = get_material("metal")
        # Custom registry takes priority
        assert result is custom_cfg
        assert result.elastic_threshold == 1.0

    def test_override_does_not_mutate_material_configs(self):
        """The override must not change MATERIAL_CONFIGS itself."""
        register_material("metal", MaterialConfig(elastic_threshold=1.0))
        assert MATERIAL_CONFIGS[MaterialPreset.METAL].elastic_threshold == 80.0

    def test_unregister_restores_builtin(self):
        """After unregistering an override, get_material falls back to built-in."""
        register_material("metal", MaterialConfig(elastic_threshold=1.0))
        unregister_material("metal")
        result = get_material("metal")
        assert result is MATERIAL_CONFIGS[MaterialPreset.METAL]
