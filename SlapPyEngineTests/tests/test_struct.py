"""
Tests for struct registry and shader generation — no GPU required.
"""
import pytest

from slappyengine.struct_registry import StructRegistry, StructModule
from slappyengine.shader_gen import ShaderGen
from slappyengine.modules.health import HealthModule
from slappyengine.modules.physics import PhysicsModule


# ---------------------------------------------------------------------------
# test_struct_registry_register
# ---------------------------------------------------------------------------

def test_struct_registry_register():
    reg = StructRegistry()
    reg.register(HealthModule)
    reg.register(PhysicsModule)

    channel_names = [name for name, _ in reg.channels]

    # Built-in color channel always present
    assert "color" in channel_names

    # HealthModule channels
    for ch in ("health", "max_health", "tag"):
        assert ch in channel_names

    # PhysicsModule channels
    for ch in ("strength", "stiffness", "density", "vel_x", "vel_y"):
        assert ch in channel_names


# ---------------------------------------------------------------------------
# test_struct_registry_no_duplicate
# ---------------------------------------------------------------------------

def test_struct_registry_no_duplicate():
    class ModuleA(StructModule):
        name = "a"
        channels = [("shared_field", "f32")]
        default_values = {"shared_field": 0.0}

    class ModuleB(StructModule):
        name = "b"
        channels = [("shared_field", "f32")]   # same channel name
        default_values = {"shared_field": 0.0}

    reg = StructRegistry()
    reg.register(ModuleA)

    with pytest.raises(ValueError, match="shared_field"):
        reg.register(ModuleB)


# ---------------------------------------------------------------------------
# test_struct_layout_offsets
# ---------------------------------------------------------------------------

def test_struct_layout_offsets():
    reg = StructRegistry()
    reg.register(HealthModule)

    # "color" is vec4f (16 bytes, 16-byte aligned) → offset 0
    color_offset = reg.channel_offset("color")
    assert color_offset == 0

    # "health" is the first f32 after vec4f → offset must be >= 16
    health_offset = reg.channel_offset("health")
    assert health_offset >= 16

    # stride must be a multiple of 16 (WGSL uniform buffer alignment rule)
    stride = reg.stride_bytes()
    assert stride % 16 == 0


# ---------------------------------------------------------------------------
# test_shader_gen_struct_output
# ---------------------------------------------------------------------------

def test_shader_gen_struct_output():
    reg = StructRegistry()
    reg.register(HealthModule)
    gen = ShaderGen(reg)

    wgsl = gen.pixel_struct_wgsl()

    assert "struct PixelData" in wgsl
    # All registered channel names must appear in the output
    for name, _ in reg.channels:
        assert name in wgsl


# ---------------------------------------------------------------------------
# test_struct_registry_lock
# ---------------------------------------------------------------------------

def test_struct_registry_lock():
    class ExtraModule(StructModule):
        name = "extra"
        channels = [("extra_field", "f32")]
        default_values = {"extra_field": 0.0}

    reg = StructRegistry()
    reg.register(HealthModule)
    reg.lock()

    with pytest.raises(RuntimeError):
        reg.register(ExtraModule)


# ---------------------------------------------------------------------------
# test_default_values
# ---------------------------------------------------------------------------

def test_default_values():
    reg = StructRegistry()
    reg.register(HealthModule)

    assert reg.default_for_channel("health") == 1.0
    assert reg.default_for_channel("tag") == 0

    # Unregistered channel falls back to 0.0
    assert reg.default_for_channel("nonexistent") == 0.0
