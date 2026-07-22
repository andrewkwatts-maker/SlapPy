"""Engine tests for modules/ subpackage — FluidParamsModule, PhysicsModule,
PixelPhysicsModule — and related struct-registry integration.  Headless."""
from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# FluidParamsModule
# ---------------------------------------------------------------------------

class TestFluidParamsModule:
    def test_importable(self):
        from pharos_engine.modules.fluid_params import FluidParamsModule
        assert FluidParamsModule is not None

    def test_name(self):
        from pharos_engine.modules.fluid_params import FluidParamsModule
        assert FluidParamsModule.name == "fluid"

    def test_channels_present(self):
        from pharos_engine.modules.fluid_params import FluidParamsModule
        names = [n for n, _ in FluidParamsModule.channels]
        assert "viscosity" in names
        assert "pressure" in names
        assert "divergence" in names
        assert "fluid_tag" in names

    def test_fluid_tag_is_u32(self):
        from pharos_engine.modules.fluid_params import FluidParamsModule
        types = {n: t for n, t in FluidParamsModule.channels}
        assert types["fluid_tag"] == "u32"

    def test_float_channels_are_f32(self):
        from pharos_engine.modules.fluid_params import FluidParamsModule
        types = {n: t for n, t in FluidParamsModule.channels}
        for ch in ("viscosity", "pressure", "divergence"):
            assert types[ch] == "f32"

    def test_compute_passes(self):
        from pharos_engine.modules.fluid_params import FluidParamsModule
        assert "fluid" in FluidParamsModule.compute_passes

    def test_default_viscosity(self):
        from pharos_engine.modules.fluid_params import FluidParamsModule
        assert FluidParamsModule.default_values["viscosity"] == pytest.approx(0.001)

    def test_default_pressure_zero(self):
        from pharos_engine.modules.fluid_params import FluidParamsModule
        assert FluidParamsModule.default_values["pressure"] == pytest.approx(0.0)

    def test_default_divergence_zero(self):
        from pharos_engine.modules.fluid_params import FluidParamsModule
        assert FluidParamsModule.default_values["divergence"] == pytest.approx(0.0)

    def test_default_fluid_tag_zero(self):
        from pharos_engine.modules.fluid_params import FluidParamsModule
        assert FluidParamsModule.default_values["fluid_tag"] == 0

    def test_is_struct_module_subclass(self):
        from pharos_engine.modules.fluid_params import FluidParamsModule
        from pharos_engine.struct_registry import StructModule
        assert issubclass(FluidParamsModule, StructModule)

    def test_registers_without_conflict(self):
        from pharos_engine.modules.fluid_params import FluidParamsModule
        from pharos_engine.struct_registry import StructRegistry
        reg = StructRegistry()
        reg.register(FluidParamsModule)
        names = [n for n, _ in reg.channels]
        assert "viscosity" in names


# ---------------------------------------------------------------------------
# PhysicsModule
# ---------------------------------------------------------------------------

class TestPhysicsModule:
    def test_importable(self):
        from pharos_engine.modules.physics import PhysicsModule
        assert PhysicsModule is not None

    def test_name(self):
        from pharos_engine.modules.physics import PhysicsModule
        assert PhysicsModule.name == "physics"

    def test_channels_present(self):
        from pharos_engine.modules.physics import PhysicsModule
        names = [n for n, _ in PhysicsModule.channels]
        for ch in ("strength", "stiffness", "density", "vel_x", "vel_y"):
            assert ch in names

    def test_all_channels_f32(self):
        from pharos_engine.modules.physics import PhysicsModule
        types = {n: t for n, t in PhysicsModule.channels}
        for ch in ("strength", "stiffness", "density", "vel_x", "vel_y"):
            assert types[ch] == "f32"

    def test_compute_passes(self):
        from pharos_engine.modules.physics import PhysicsModule
        assert "rigid" in PhysicsModule.compute_passes

    def test_default_strength_one(self):
        from pharos_engine.modules.physics import PhysicsModule
        assert PhysicsModule.default_values["strength"] == pytest.approx(1.0)

    def test_default_vel_x_zero(self):
        from pharos_engine.modules.physics import PhysicsModule
        assert PhysicsModule.default_values["vel_x"] == pytest.approx(0.0)

    def test_default_vel_y_zero(self):
        from pharos_engine.modules.physics import PhysicsModule
        assert PhysicsModule.default_values["vel_y"] == pytest.approx(0.0)

    def test_registers_without_conflict(self):
        from pharos_engine.modules.physics import PhysicsModule
        from pharos_engine.struct_registry import StructRegistry
        reg = StructRegistry()
        reg.register(PhysicsModule)
        names = [n for n, _ in reg.channels]
        assert "vel_x" in names


# ---------------------------------------------------------------------------
# PixelPhysicsModule
# ---------------------------------------------------------------------------

class TestPixelPhysicsModule:
    def test_importable(self):
        from pharos_engine.modules.pixel_physics import PixelPhysicsModule
        assert PixelPhysicsModule is not None

    def test_name(self):
        from pharos_engine.modules.pixel_physics import PixelPhysicsModule
        assert PixelPhysicsModule.name == "pixel_physics"

    def test_eight_channels(self):
        from pharos_engine.modules.pixel_physics import PixelPhysicsModule
        assert len(PixelPhysicsModule.channels) == 8

    def test_required_channels_present(self):
        from pharos_engine.modules.pixel_physics import PixelPhysicsModule
        names = [n for n, _ in PixelPhysicsModule.channels]
        for ch in ("vel_x", "vel_y", "mass", "friction", "elasticity", "temperature"):
            assert ch in names

    def test_state_channel_is_u32(self):
        from pharos_engine.modules.pixel_physics import PixelPhysicsModule
        types = {n: t for n, t in PixelPhysicsModule.channels}
        assert types["state"] == "u32"

    def test_pad_channel_is_u32(self):
        from pharos_engine.modules.pixel_physics import PixelPhysicsModule
        types = {n: t for n, t in PixelPhysicsModule.channels}
        assert types["_pad"] == "u32"

    def test_float_channels_are_f32(self):
        from pharos_engine.modules.pixel_physics import PixelPhysicsModule
        types = {n: t for n, t in PixelPhysicsModule.channels}
        for ch in ("vel_x", "vel_y", "mass", "friction", "elasticity", "temperature"):
            assert types[ch] == "f32"

    def test_compute_passes(self):
        from pharos_engine.modules.pixel_physics import PixelPhysicsModule
        assert "pixel_physics" in PixelPhysicsModule.compute_passes

    def test_default_mass_one(self):
        from pharos_engine.modules.pixel_physics import PixelPhysicsModule
        assert PixelPhysicsModule.default_values["mass"] == pytest.approx(1.0)

    def test_default_temperature_room(self):
        from pharos_engine.modules.pixel_physics import PixelPhysicsModule
        assert PixelPhysicsModule.default_values["temperature"] == pytest.approx(293.0)

    def test_default_state_solid(self):
        from pharos_engine.modules.pixel_physics import PixelPhysicsModule
        assert PixelPhysicsModule.default_values["state"] == 0

    def test_default_friction_half(self):
        from pharos_engine.modules.pixel_physics import PixelPhysicsModule
        assert PixelPhysicsModule.default_values["friction"] == pytest.approx(0.5)

    def test_default_elasticity(self):
        from pharos_engine.modules.pixel_physics import PixelPhysicsModule
        assert PixelPhysicsModule.default_values["elasticity"] == pytest.approx(0.3)

    def test_stride_is_32_bytes(self):
        """8 × 4-byte fields → 32 bytes = 2 × 16-byte alignment quanta."""
        from pharos_engine.modules.pixel_physics import PixelPhysicsModule
        from pharos_engine.struct_registry import StructRegistry
        reg = StructRegistry()
        reg.register(PixelPhysicsModule)
        # color(vec4f=16) + 8×f32/u32(32) = 48, rounds up to 48 (already aligned)
        assert reg.stride_bytes() >= 48

    def test_registers_without_conflict(self):
        from pharos_engine.modules.pixel_physics import PixelPhysicsModule
        from pharos_engine.struct_registry import StructRegistry
        reg = StructRegistry()
        reg.register(PixelPhysicsModule)
        names = [n for n, _ in reg.channels]
        assert "temperature" in names


# ---------------------------------------------------------------------------
# Lazy import via modules/__init__.py
# ---------------------------------------------------------------------------

class TestModulesLazyImport:
    def test_fluid_via_package(self):
        from pharos_engine.modules import FluidParamsModule
        assert FluidParamsModule.name == "fluid"

    def test_physics_via_package(self):
        from pharos_engine.modules import PhysicsModule
        assert PhysicsModule.name == "physics"

    def test_pixel_physics_via_package(self):
        from pharos_engine.modules import PixelPhysicsModule
        assert PixelPhysicsModule.name == "pixel_physics"

    def test_health_via_package(self):
        from pharos_engine.modules import HealthModule
        assert HealthModule.name == "health"

    def test_unknown_attr_raises(self):
        import pharos_engine.modules as mods
        with pytest.raises(AttributeError):
            _ = mods.NonExistentModule


# ---------------------------------------------------------------------------
# Module combinations that are compatible (no channel name collision)
# PhysicsModule and PixelPhysicsModule both define vel_x/vel_y — they are
# mutually exclusive by design (game chooses one physics model per layer).
# ---------------------------------------------------------------------------

class TestCompatibleModuleCombinations:
    def test_health_fluid_pixel_physics_co_register(self):
        """Health + Fluid + PixelPhysics have no shared channel names."""
        from pharos_engine.modules.health import HealthModule
        from pharos_engine.modules.fluid_params import FluidParamsModule
        from pharos_engine.modules.pixel_physics import PixelPhysicsModule
        from pharos_engine.struct_registry import StructRegistry
        reg = StructRegistry()
        reg.register(HealthModule)
        reg.register(FluidParamsModule)
        reg.register(PixelPhysicsModule)
        names = [n for n, _ in reg.channels]
        assert "health" in names
        assert "viscosity" in names
        assert "temperature" in names

    def test_health_physics_fluid_co_register(self):
        """Health + Physics + Fluid have no shared channel names."""
        from pharos_engine.modules.health import HealthModule
        from pharos_engine.modules.physics import PhysicsModule
        from pharos_engine.modules.fluid_params import FluidParamsModule
        from pharos_engine.struct_registry import StructRegistry
        reg = StructRegistry()
        reg.register(HealthModule)
        reg.register(PhysicsModule)
        reg.register(FluidParamsModule)
        names = [n for n, _ in reg.channels]
        assert "health" in names
        assert "strength" in names
        assert "viscosity" in names

    def test_physics_pixel_physics_conflict_raises(self):
        """PhysicsModule and PixelPhysicsModule share vel_x/vel_y — co-register must raise."""
        from pharos_engine.modules.physics import PhysicsModule
        from pharos_engine.modules.pixel_physics import PixelPhysicsModule
        from pharos_engine.struct_registry import StructRegistry
        reg = StructRegistry()
        reg.register(PhysicsModule)
        with pytest.raises(ValueError):
            reg.register(PixelPhysicsModule)

    def test_passes_from_compatible_triple(self):
        from pharos_engine.modules.health import HealthModule
        from pharos_engine.modules.physics import PhysicsModule
        from pharos_engine.modules.fluid_params import FluidParamsModule
        from pharos_engine.struct_registry import StructRegistry
        reg = StructRegistry()
        for mod in (HealthModule, PhysicsModule, FluidParamsModule):
            reg.register(mod)
        passes = reg.required_compute_passes()
        for p in ("health_sum", "rigid", "fluid"):
            assert p in passes
