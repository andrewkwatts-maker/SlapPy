"""Regression tests for DDD2 cross-layer buffer sampling.

Covers the ``Layer.sample_from`` / ``bind_sampled_layers`` /
``Layer2D.apply_post_process_from`` / ``Layer3D.use_layer_as_texture`` surface
plus the ``cross_layer_composite.wgsl`` shader that backs them.

Everything runs headless — no wgpu device required. The sampling helpers
degrade gracefully when wgpu isn't installed (the CI matrix / sandbox path).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pharos_engine.layer import Layer2D, Layer3D
from pharos_engine.render.layer_sampling import (
    BLEND_MODES,
    LayerSampleBinding,
    LayerTextureBinding,
    PostProcessDescriptor,
    apply_post_process_from,
    bind_sampled_layers,
    fallback_texture_view,
    load_composite_shader,
    make_layer_sample_binding,
    use_layer_as_texture,
)


# --------------------------------------------------------------------------
# LayerSampleBinding + Layer.sample_from
# --------------------------------------------------------------------------
def test_layer2d_sample_from_layer3d_returns_binding():
    layer_2d = Layer2D(name="hud", width=32, height=32)
    layer_3d = Layer3D(name="scene", resolution=(32, 32))

    binding = layer_2d.sample_from(layer_3d, uniform_name="u_scene")

    assert isinstance(binding, LayerSampleBinding)
    assert binding.layer is layer_3d
    assert binding.uniform_name == "u_scene"
    assert binding.filter == "linear"
    assert binding.address_mode == "clamp"


def test_layer3d_sample_from_layer2d_returns_binding():
    layer_3d = Layer3D(name="scene", resolution=(32, 32))
    layer_2d = Layer2D(name="paint", width=32, height=32)

    binding = layer_3d.sample_from(layer_2d, uniform_name="u_paint")

    assert isinstance(binding, LayerSampleBinding)
    assert binding.layer is layer_2d
    assert binding.uniform_name == "u_paint"


def test_default_uniform_name():
    layer_a = Layer2D(name="a", width=8, height=8)
    layer_b = Layer2D(name="b", width=8, height=8)

    binding = layer_a.sample_from(layer_b)
    assert binding.uniform_name == "u_source_layer"


def test_binding_rejects_invalid_filter():
    layer_a = Layer2D(name="a", width=8, height=8)
    layer_b = Layer2D(name="b", width=8, height=8)
    with pytest.raises(ValueError, match="filter"):
        make_layer_sample_binding(layer_b, filter="cubic")


def test_binding_rejects_invalid_address_mode():
    layer_a = Layer2D(name="a", width=8, height=8)
    with pytest.raises(ValueError, match="address_mode"):
        make_layer_sample_binding(layer_a, address_mode="wrap")


def test_binding_rejects_empty_uniform_name():
    layer_a = Layer2D(name="a", width=8, height=8)
    with pytest.raises(ValueError, match="uniform_name"):
        make_layer_sample_binding(layer_a, uniform_name="")


# --------------------------------------------------------------------------
# bind_sampled_layers — with real (mock) target and fallback
# --------------------------------------------------------------------------
class _MockTextureView:
    def __init__(self, name: str = "view") -> None:
        self.name = name


class _MockTexture:
    def __init__(self, name: str = "tex") -> None:
        self.name = name

    def create_view(self):
        return _MockTextureView(self.name + "_view")


def test_bind_sampled_layers_with_source_texture():
    layer_3d = Layer3D(name="scene", resolution=(16, 16))
    layer_3d.render_target = _MockTexture("scene_rt")

    layer_2d = Layer2D(name="hud", width=16, height=16)
    binding = layer_2d.sample_from(layer_3d)

    bg = bind_sampled_layers(
        pass_encoder=None,
        sample_bindings=[binding],
        bind_group_layout=None,
        device=None,
    )
    # 2 entries per binding — view + sampler
    assert len(bg) == 2
    assert bg.entries[0]["binding"] == 0
    assert bg.entries[1]["binding"] == 1
    assert bg.entries[0]["uniform_name"] == "u_source_layer"
    assert bg.entries[1]["uniform_name"] == "u_source_layer_sampler"
    # View entry should be the mock texture view (not the fallback)
    view = bg.entries[0]["resource"]
    assert getattr(view, "is_fallback", False) is False


def test_bind_sampled_layers_fallback_when_render_target_missing():
    layer_3d = Layer3D(name="scene", resolution=(16, 16))
    assert layer_3d.render_target is None  # not yet allocated

    layer_2d = Layer2D(name="hud", width=16, height=16)
    binding = layer_2d.sample_from(layer_3d)

    # Should NOT crash and should substitute the fallback view
    bg = bind_sampled_layers(
        pass_encoder=None,
        sample_bindings=[binding],
        bind_group_layout=None,
        device=None,
    )
    assert len(bg) == 2
    view = bg.entries[0]["resource"]
    assert getattr(view, "is_fallback", False) is True
    assert view.size == (1, 1)
    assert view.data == b"\x00\x00\x00\x00"


def test_bind_sampled_layers_multiple_bindings():
    layer_a = Layer2D(name="a", width=8, height=8)
    layer_a.render_target = _MockTexture("a_rt")
    layer_b = Layer3D(name="b", resolution=(8, 8))
    layer_b.render_target = _MockTexture("b_rt")

    target = Layer2D(name="composite", width=8, height=8)
    binding_a = target.sample_from(layer_a, uniform_name="u_a")
    binding_b = target.sample_from(layer_b, uniform_name="u_b")
    binding_b.slot = 1  # move to second slot

    bg = bind_sampled_layers(
        pass_encoder=None,
        sample_bindings=[binding_a, binding_b],
        bind_group_layout=None,
        device=None,
    )
    # 2 bindings × (view + sampler) = 4 entries
    assert len(bg) == 4
    uniform_names = {e["uniform_name"] for e in bg.entries}
    assert "u_a" in uniform_names
    assert "u_b" in uniform_names


def test_fallback_texture_view_headless():
    view = fallback_texture_view(device=None)
    assert view.is_fallback
    assert view.size == (1, 1)
    assert view.format == "rgba8unorm"


# --------------------------------------------------------------------------
# apply_post_process_from — 2D samples another layer
# --------------------------------------------------------------------------
def test_layer2d_apply_post_process_from_layer3d():
    layer_3d = Layer3D(name="scene", resolution=(32, 32))
    layer_2d = Layer2D(name="outline", width=32, height=32)

    desc = layer_2d.apply_post_process_from(layer_3d, blend_mode="alpha")

    assert isinstance(desc, PostProcessDescriptor)
    assert desc.source_layer is layer_3d
    assert desc.blend_mode == "alpha"
    # The descriptor is queued on the target layer
    assert desc in layer_2d._post_process


def test_apply_post_process_from_rejects_bad_blend_mode():
    layer_3d = Layer3D(name="scene", resolution=(8, 8))
    layer_2d = Layer2D(name="hud", width=8, height=8)
    with pytest.raises(ValueError, match="blend_mode"):
        apply_post_process_from(layer_2d, layer_3d, blend_mode="banana")


def test_apply_post_process_accepts_all_blend_modes():
    layer_3d = Layer3D(name="scene", resolution=(8, 8))
    for mode in BLEND_MODES:
        layer_2d = Layer2D(name=f"hud_{mode}", width=8, height=8)
        desc = layer_2d.apply_post_process_from(layer_3d, blend_mode=mode)
        assert desc.blend_mode == mode


# --------------------------------------------------------------------------
# use_layer_as_texture — 3D binds a 2D drawing as a mesh texture
# --------------------------------------------------------------------------
def test_layer3d_use_layer_as_texture():
    layer_3d = Layer3D(name="cube", resolution=(64, 64))
    layer_2d = Layer2D(name="drawing", width=64, height=64)

    ltb = layer_3d.use_layer_as_texture(layer_2d, uniform_slot="u_albedo")

    assert isinstance(ltb, LayerTextureBinding)
    assert ltb.source_layer is layer_2d
    assert ltb.uniform_slot == "u_albedo"
    assert ltb.binding.uniform_name == "u_albedo"
    # Registered on the target layer under the slot name
    assert layer_3d._sampled_layer_textures["u_albedo"] is ltb


def test_layer3d_use_layer_as_texture_multiple_slots():
    layer_3d = Layer3D(name="cube", resolution=(8, 8))
    layer_a = Layer2D(name="a", width=8, height=8)
    layer_b = Layer2D(name="b", width=8, height=8)

    layer_3d.use_layer_as_texture(layer_a, uniform_slot="u_albedo")
    layer_3d.use_layer_as_texture(layer_b, uniform_slot="u_emissive")

    slots = layer_3d._sampled_layer_textures
    assert set(slots.keys()) == {"u_albedo", "u_emissive"}


def test_use_layer_as_texture_via_helper():
    target = Layer3D(name="t", resolution=(8, 8))
    src = Layer2D(name="s", width=8, height=8)
    ltb = use_layer_as_texture(target, src, uniform_slot="u_x", filter="nearest",
                                address_mode="repeat")
    assert ltb.binding.filter == "nearest"
    assert ltb.binding.address_mode == "repeat"


# --------------------------------------------------------------------------
# Blend-mode enums preserved
# --------------------------------------------------------------------------
def test_blend_modes_enum_stable():
    assert "add" in BLEND_MODES
    assert "multiply" in BLEND_MODES
    assert "alpha" in BLEND_MODES
    assert "screen" in BLEND_MODES
    # Enum is closed — nothing else should sneak in unnoticed
    assert BLEND_MODES == frozenset({"add", "multiply", "alpha", "screen"})


# --------------------------------------------------------------------------
# WGSL shader sanity checks
# --------------------------------------------------------------------------
def test_composite_shader_parses_basic():
    src = load_composite_shader()
    assert "@vertex" in src
    assert "@fragment" in src
    # Exactly one entry point each
    assert src.count("@vertex") == 1
    assert src.count("@fragment") == 1
    # Blend helpers present
    for helper in ("blend_add", "blend_multiply", "blend_alpha", "blend_screen"):
        assert helper in src


def test_composite_shader_file_lives_next_to_module():
    from pharos_engine.render import layer_sampling
    shader_dir = Path(layer_sampling.__file__).parent / "shaders"
    assert (shader_dir / "cross_layer_composite.wgsl").is_file()
