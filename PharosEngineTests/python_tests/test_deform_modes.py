"""Engine tests for deform_modes.py — headless."""
from __future__ import annotations
import pytest


class TestDeformSimMode:
    def test_all_values_present(self):
        from pharos_engine.deform_modes import DeformSimMode
        names = {m.value for m in DeformSimMode}
        assert "always_on" in names
        assert "collision_triggered" in names
        assert "manual" in names

    def test_enum_by_value(self):
        from pharos_engine.deform_modes import DeformSimMode
        assert DeformSimMode("always_on") is DeformSimMode.ALWAYS_ON


class TestDecayMode:
    def test_all_values_present(self):
        from pharos_engine.deform_modes import DecayMode
        names = {m.value for m in DecayMode}
        assert "constant" in names
        assert "curve" in names
        assert "none" in names

    def test_enum_identity(self):
        from pharos_engine.deform_modes import DecayMode
        assert DecayMode.CURVE is not DecayMode.CONSTANT


class TestDestroyMode:
    def test_expected_modes(self):
        from pharos_engine.deform_modes import DestroyMode
        names = {m.value for m in DestroyMode}
        assert "persist" in names
        assert "fragment" in names
        assert "remove" in names
        assert "respawn" in names
        assert "disable" in names


class TestCrackMode:
    def test_expected_modes(self):
        from pharos_engine.deform_modes import CrackMode
        names = {m.value for m in CrackMode}
        assert "none" in names
        assert "radial" in names
        assert "grain" in names
        assert "structural" in names


class TestPhysicsCoupling:
    def test_expected_modes(self):
        from pharos_engine.deform_modes import PhysicsCoupling
        names = {m.value for m in PhysicsCoupling}
        assert "isolated" in names
        assert "mass" in names
        assert "drag" in names
        assert "com" in names
        assert "full" in names


class TestRepairMode:
    def test_expected_modes(self):
        from pharos_engine.deform_modes import RepairMode
        names = {m.value for m in RepairMode}
        assert "none" in names
        assert "auto" in names
        assert "event_only" in names
        assert "budget" in names


class TestMaterialPreset:
    def test_expected_presets(self):
        from pharos_engine.deform_modes import MaterialPreset
        names = {m.value for m in MaterialPreset}
        for expected in ["metal", "glass", "rubber", "wood", "stone", "cloth", "ice", "organic", "custom"]:
            assert expected in names, f"Missing preset: {expected}"


class TestMaterialConfig:
    def test_default_instantiation(self):
        from pharos_engine.deform_modes import MaterialConfig
        cfg = MaterialConfig()
        assert cfg.elastic_threshold == pytest.approx(80.0)
        assert cfg.spring_decay == pytest.approx(0.94)

    def test_custom_values(self):
        from pharos_engine.deform_modes import MaterialConfig, CrackMode, DestroyMode
        cfg = MaterialConfig(
            elastic_threshold=10.0,
            crack_mode=CrackMode.RADIAL,
            destroy_mode=DestroyMode.FRAGMENT,
        )
        assert cfg.elastic_threshold == pytest.approx(10.0)
        assert cfg.crack_mode is CrackMode.RADIAL
        assert cfg.destroy_mode is DestroyMode.FRAGMENT

    def test_decay_curve_default_none(self):
        from pharos_engine.deform_modes import MaterialConfig
        cfg = MaterialConfig()
        assert cfg.decay_curve is None

    def test_physics_coupling_default(self):
        from pharos_engine.deform_modes import MaterialConfig, PhysicsCoupling
        cfg = MaterialConfig()
        assert cfg.physics_coupling is PhysicsCoupling.ISOLATED


class TestMaterialConfigs:
    def test_all_presets_have_config(self):
        from pharos_engine.deform_modes import MaterialPreset, MATERIAL_CONFIGS
        for preset in MaterialPreset:
            assert preset in MATERIAL_CONFIGS, f"Missing config for {preset}"

    def test_metal_high_threshold(self):
        from pharos_engine.deform_modes import MaterialPreset, MATERIAL_CONFIGS
        cfg = MATERIAL_CONFIGS[MaterialPreset.METAL]
        assert cfg.elastic_threshold >= 50.0

    def test_glass_low_threshold(self):
        from pharos_engine.deform_modes import MaterialPreset, MATERIAL_CONFIGS
        cfg = MATERIAL_CONFIGS[MaterialPreset.GLASS]
        assert cfg.elastic_threshold < 20.0

    def test_rubber_high_threshold(self):
        from pharos_engine.deform_modes import MaterialPreset, MATERIAL_CONFIGS
        cfg = MATERIAL_CONFIGS[MaterialPreset.RUBBER]
        assert cfg.elastic_threshold > 100.0

    def test_glass_fragments(self):
        from pharos_engine.deform_modes import MaterialPreset, MATERIAL_CONFIGS, DestroyMode
        cfg = MATERIAL_CONFIGS[MaterialPreset.GLASS]
        assert cfg.destroy_mode is DestroyMode.FRAGMENT

    def test_rubber_auto_repairs(self):
        from pharos_engine.deform_modes import MaterialPreset, MATERIAL_CONFIGS, RepairMode
        cfg = MATERIAL_CONFIGS[MaterialPreset.RUBBER]
        assert cfg.repair_mode is RepairMode.AUTO

    def test_stone_cracks_structurally(self):
        from pharos_engine.deform_modes import MaterialPreset, MATERIAL_CONFIGS, CrackMode
        cfg = MATERIAL_CONFIGS[MaterialPreset.STONE]
        assert cfg.crack_mode is CrackMode.STRUCTURAL


class TestResolveMaterial:
    def test_returns_base_config_without_overrides(self):
        from pharos_engine.deform_modes import MaterialPreset, MATERIAL_CONFIGS, resolve_material
        base = MATERIAL_CONFIGS[MaterialPreset.METAL]
        result = resolve_material(MaterialPreset.METAL)
        assert result.elastic_threshold == pytest.approx(base.elastic_threshold)

    def test_override_applied(self):
        from pharos_engine.deform_modes import MaterialPreset, resolve_material
        cfg = resolve_material(MaterialPreset.METAL, elastic_threshold=60.0)
        assert cfg.elastic_threshold == pytest.approx(60.0)

    def test_override_does_not_mutate_original(self):
        from pharos_engine.deform_modes import MaterialPreset, MATERIAL_CONFIGS, resolve_material
        original = MATERIAL_CONFIGS[MaterialPreset.METAL].elastic_threshold
        resolve_material(MaterialPreset.METAL, elastic_threshold=999.0)
        assert MATERIAL_CONFIGS[MaterialPreset.METAL].elastic_threshold == pytest.approx(original)


class TestCustomMaterialRegistry:
    def test_register_and_get(self):
        from pharos_engine.deform_modes import register_material, get_material, MaterialConfig
        cfg = MaterialConfig(elastic_threshold=42.0)
        register_material("test_custom_mat", cfg)
        result = get_material("test_custom_mat")
        assert result is not None
        assert result.elastic_threshold == pytest.approx(42.0)

    def test_unregister(self):
        from pharos_engine.deform_modes import register_material, unregister_material, get_material, MaterialConfig
        register_material("_temp_mat", MaterialConfig())
        unregister_material("_temp_mat")
        assert get_material("_temp_mat") is None

    def test_get_builtin_by_name_string(self):
        from pharos_engine.deform_modes import get_material
        cfg = get_material("metal")
        assert cfg is not None
        assert cfg.elastic_threshold >= 50.0

    def test_get_unknown_returns_none(self):
        from pharos_engine.deform_modes import get_material
        assert get_material("nonexistent_xyz_material") is None

    def test_list_materials_contains_builtins(self):
        from pharos_engine.deform_modes import list_materials
        names = list_materials()
        assert "metal" in names
        assert "glass" in names
        assert "custom" in names

    def test_list_materials_includes_custom(self):
        from pharos_engine.deform_modes import register_material, list_materials, MaterialConfig, unregister_material
        register_material("_survey_test_mat", MaterialConfig())
        names = list_materials()
        assert "_survey_test_mat" in names
        unregister_material("_survey_test_mat")


class TestZoneConfig:
    def test_default_values(self):
        from pharos_engine.deform_modes import ZoneConfig
        zc = ZoneConfig(name="bumper")
        assert zc.name == "bumper"
        assert zc.integrity_threshold == pytest.approx(0.0)
        assert zc.material is None
        assert zc.strength_scale == pytest.approx(1.0)
        assert zc.on_destroy_event == "Deform.ZoneDestroyed"

    def test_custom_zone(self):
        from pharos_engine.deform_modes import ZoneConfig, MaterialPreset
        zc = ZoneConfig(
            name="windshield",
            integrity_threshold=0.3,
            material=MaterialPreset.GLASS,
            on_destroy_event="Deform.WindshieldShattered",
            strength_scale=0.5,
        )
        assert zc.name == "windshield"
        assert zc.integrity_threshold == pytest.approx(0.3)
        assert zc.material is MaterialPreset.GLASS
        assert zc.strength_scale == pytest.approx(0.5)
