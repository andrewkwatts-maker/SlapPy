"""Engine tests for StructRegistry + StructModule — headless."""
from __future__ import annotations
import pytest


class TestStructRegistryInit:
    def test_default_color_channel(self):
        from slappyengine.struct_registry import StructRegistry
        reg = StructRegistry()
        names = [name for name, _ in reg.channels]
        assert "color" in names

    def test_initially_unlocked(self):
        from slappyengine.struct_registry import StructRegistry
        reg = StructRegistry()
        assert reg._locked is False

    def test_no_modules_initially(self):
        from slappyengine.struct_registry import StructRegistry
        reg = StructRegistry()
        assert len(reg._modules) == 0


class TestStructModuleRegistration:
    def _make_module(self, name="test", channels=None, defaults=None, passes=None):
        from slappyengine.struct_registry import StructModule
        class _Mod(StructModule):
            pass
        _Mod.name = name
        _Mod.channels = channels or [("hp", "f32")]
        _Mod.default_values = defaults or {"hp": 1.0}
        _Mod.compute_passes = passes or []
        return _Mod

    def test_register_adds_channels(self):
        from slappyengine.struct_registry import StructRegistry
        reg = StructRegistry()
        mod = self._make_module(channels=[("hp", "f32"), ("shield", "f32")])
        reg.register(mod)
        names = [n for n, _ in reg.channels]
        assert "hp" in names
        assert "shield" in names

    def test_register_duplicate_channel_raises(self):
        from slappyengine.struct_registry import StructRegistry
        reg = StructRegistry()
        mod_a = self._make_module("a", [("hp", "f32")])
        mod_b = self._make_module("b", [("hp", "f32")])
        reg.register(mod_a)
        with pytest.raises(ValueError):
            reg.register(mod_b)

    def test_register_after_lock_raises(self):
        from slappyengine.struct_registry import StructRegistry
        reg = StructRegistry()
        reg.lock()
        mod = self._make_module()
        with pytest.raises(RuntimeError):
            reg.register(mod)

    def test_lock_prevents_registration(self):
        from slappyengine.struct_registry import StructRegistry
        reg = StructRegistry()
        reg.lock()
        assert reg._locked is True


class TestStructRegistryLayout:
    def _make_health_module(self):
        from slappyengine.struct_registry import StructModule
        class _Health(StructModule):
            name = "health"
            channels = [("hp", "f32"), ("max_hp", "f32")]
            default_values = {"hp": 1.0, "max_hp": 1.0}
            compute_passes = ["health_sum"]
        return _Health

    def test_channel_offset_color_is_zero(self):
        from slappyengine.struct_registry import StructRegistry
        reg = StructRegistry()
        assert reg.channel_offset("color") == 0

    def test_channel_offset_f32_after_vec4f(self):
        from slappyengine.struct_registry import StructRegistry
        reg = StructRegistry()
        reg.register(self._make_health_module())
        # color is vec4f (16 bytes at offset 0), hp should be at offset 16
        assert reg.channel_offset("hp") == 16

    def test_stride_is_multiple_of_16(self):
        from slappyengine.struct_registry import StructRegistry
        reg = StructRegistry()
        reg.register(self._make_health_module())
        stride = reg.stride_bytes()
        assert stride % 16 == 0

    def test_stride_at_least_covers_all_channels(self):
        from slappyengine.struct_registry import StructRegistry
        reg = StructRegistry()
        reg.register(self._make_health_module())
        stride = reg.stride_bytes()
        # vec4f(16) + 2×f32(8) = 24, rounds to 32
        assert stride >= 24


class TestStructRegistryDefaults:
    def test_default_for_registered_channel(self):
        from slappyengine.struct_registry import StructRegistry, StructModule
        class _Mod(StructModule):
            name = "ammo"
            channels = [("ammo", "f32")]
            default_values = {"ammo": 30.0}
            compute_passes = []
        reg = StructRegistry()
        reg.register(_Mod)
        assert reg.default_for_channel("ammo") == pytest.approx(30.0)

    def test_default_for_unregistered_channel_returns_zero(self):
        from slappyengine.struct_registry import StructRegistry
        reg = StructRegistry()
        assert reg.default_for_channel("nonexistent") == pytest.approx(0.0)


class TestStructRegistryComputePasses:
    def test_required_passes_deduplicated(self):
        from slappyengine.struct_registry import StructRegistry, StructModule
        class _ModA(StructModule):
            name = "a"
            channels = [("a_val", "f32")]
            default_values = {}
            compute_passes = ["shared_pass", "unique_a"]
        class _ModB(StructModule):
            name = "b"
            channels = [("b_val", "f32")]
            default_values = {}
            compute_passes = ["shared_pass", "unique_b"]
        reg = StructRegistry()
        reg.register(_ModA)
        reg.register(_ModB)
        passes = reg.required_compute_passes()
        assert passes.count("shared_pass") == 1
        assert "unique_a" in passes
        assert "unique_b" in passes

    def test_no_modules_no_passes(self):
        from slappyengine.struct_registry import StructRegistry
        reg = StructRegistry()
        assert reg.required_compute_passes() == []


class TestBuiltinHealthModule:
    def test_health_module_importable(self):
        from slappyengine.modules.health import HealthModule
        assert HealthModule.name == "health"

    def test_health_module_has_health_channel(self):
        from slappyengine.modules.health import HealthModule
        names = [n for n, _ in HealthModule.channels]
        assert "health" in names

    def test_health_module_registers(self):
        from slappyengine.struct_registry import StructRegistry
        from slappyengine.modules.health import HealthModule
        reg = StructRegistry()
        reg.register(HealthModule)
        names = [n for n, _ in reg.channels]
        assert "health" in names
        assert "max_health" in names
