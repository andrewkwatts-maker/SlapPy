"""Engine tests for shader_binding.py, shader_gen.py, render_target.py, cube_array.py.
All headless — no GPU required.
"""
from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# ShaderBinding
# ---------------------------------------------------------------------------

class TestShaderBindingDefaults:
    def test_instantiates(self):
        from slappyengine.shader_binding import ShaderBinding
        sb = ShaderBinding(
            source_module="pixel_physics",
            source_field="temperature",
            target_shader="lighting_emission",
            target_param="emission_intensity",
        )
        assert sb is not None

    def test_fields_stored(self):
        from slappyengine.shader_binding import ShaderBinding
        sb = ShaderBinding(
            source_module="fluid",
            source_field="viscosity",
            target_shader="fluid_render",
            target_param="viscosity_uniform",
        )
        assert sb.source_module == "fluid"
        assert sb.source_field == "viscosity"
        assert sb.target_shader == "fluid_render"
        assert sb.target_param == "viscosity_uniform"

    def test_default_transform_linear(self):
        from slappyengine.shader_binding import ShaderBinding
        sb = ShaderBinding("m", "f", "s", "p")
        assert sb.transform == "linear"

    def test_default_input_range(self):
        from slappyengine.shader_binding import ShaderBinding
        sb = ShaderBinding("m", "f", "s", "p")
        assert sb.input_range == (0.0, 1.0)

    def test_default_output_range(self):
        from slappyengine.shader_binding import ShaderBinding
        sb = ShaderBinding("m", "f", "s", "p")
        assert sb.output_range == (0.0, 1.0)

    def test_default_clamp_true(self):
        from slappyengine.shader_binding import ShaderBinding
        sb = ShaderBinding("m", "f", "s", "p")
        assert sb.clamp is True

    def test_custom_transform(self):
        from slappyengine.shader_binding import ShaderBinding
        sb = ShaderBinding("m", "f", "s", "p", transform="pow2")
        assert sb.transform == "pow2"


class TestShaderBindingEvaluate:
    def _binding(self, transform="linear", input_range=(0.0, 1.0),
                 output_range=(0.0, 1.0), clamp=True):
        from slappyengine.shader_binding import ShaderBinding
        return ShaderBinding("m", "f", "s", "p",
                             transform=transform,
                             input_range=input_range,
                             output_range=output_range,
                             clamp=clamp)

    def test_linear_midpoint(self):
        sb = self._binding(input_range=(0.0, 1.0), output_range=(0.0, 10.0))
        assert sb.evaluate(0.5) == pytest.approx(5.0)

    def test_linear_zero(self):
        sb = self._binding()
        assert sb.evaluate(0.0) == pytest.approx(0.0)

    def test_linear_one(self):
        sb = self._binding(output_range=(0.0, 100.0))
        assert sb.evaluate(1.0) == pytest.approx(100.0)

    def test_clamp_below_min(self):
        sb = self._binding(input_range=(0.0, 1.0), output_range=(0.0, 1.0), clamp=True)
        assert sb.evaluate(-1.0) == pytest.approx(0.0)

    def test_clamp_above_max(self):
        sb = self._binding(input_range=(0.0, 1.0), output_range=(0.0, 1.0), clamp=True)
        assert sb.evaluate(2.0) == pytest.approx(1.0)

    def test_no_clamp_below_min(self):
        sb = self._binding(input_range=(0.0, 1.0), output_range=(0.0, 1.0), clamp=False)
        # With clamp=False, t can be negative
        result = sb.evaluate(-1.0)
        assert result < 0.0

    def test_pow2_transform(self):
        sb = self._binding(transform="pow2", output_range=(0.0, 1.0))
        # At t=0.5, pow2 gives 0.25
        result = sb.evaluate(0.5)
        assert result == pytest.approx(0.25)

    def test_sqrt_transform(self):
        sb = self._binding(transform="sqrt", input_range=(0.0, 1.0), output_range=(0.0, 1.0))
        import math
        result = sb.evaluate(0.25)
        assert result == pytest.approx(math.sqrt(0.25))

    def test_planck_transform(self):
        sb = self._binding(transform="planck", output_range=(0.0, 1.0))
        # At 1.0, planck = 1.0^0.5 = 1.0
        assert sb.evaluate(1.0) == pytest.approx(1.0)

    def test_equal_input_range_returns_lo_out(self):
        sb = self._binding(input_range=(5.0, 5.0), output_range=(2.0, 8.0))
        result = sb.evaluate(5.0)
        assert result == pytest.approx(2.0)

    def test_custom_input_output_range(self):
        sb = self._binding(input_range=(0.0, 100.0), output_range=(0.0, 1.0))
        assert sb.evaluate(50.0) == pytest.approx(0.5)


class TestShaderBindingWgsl:
    def test_to_wgsl_expr_returns_string(self):
        from slappyengine.shader_binding import ShaderBinding
        sb = ShaderBinding("m", "f", "s", "p", transform="linear")
        expr = sb.to_wgsl_expr()
        assert isinstance(expr, str)
        assert len(expr) > 0

    def test_to_wgsl_expr_pow2(self):
        from slappyengine.shader_binding import ShaderBinding
        sb = ShaderBinding("m", "f", "s", "p", transform="pow2")
        expr = sb.to_wgsl_expr()
        assert "pow" in expr

    def test_to_wgsl_expr_sqrt(self):
        from slappyengine.shader_binding import ShaderBinding
        sb = ShaderBinding("m", "f", "s", "p", transform="sqrt")
        expr = sb.to_wgsl_expr()
        assert "sqrt" in expr


# ---------------------------------------------------------------------------
# ShaderGen
# ---------------------------------------------------------------------------

class TestShaderGen:
    def _registry_with_physics(self):
        from slappyengine.struct_registry import StructRegistry
        from slappyengine.modules.physics import PhysicsModule
        reg = StructRegistry()
        reg.register(PhysicsModule)
        return reg

    def test_instantiates(self):
        from slappyengine.shader_gen import ShaderGen
        from slappyengine.struct_registry import StructRegistry
        sg = ShaderGen(StructRegistry())
        assert sg is not None

    def test_pixel_struct_wgsl_returns_string(self):
        from slappyengine.shader_gen import ShaderGen
        sg = ShaderGen(self._registry_with_physics())
        wgsl = sg.pixel_struct_wgsl("MyPixel")
        assert isinstance(wgsl, str)
        assert "MyPixel" in wgsl

    def test_pixel_struct_contains_field_names(self):
        from slappyengine.shader_gen import ShaderGen
        sg = ShaderGen(self._registry_with_physics())
        wgsl = sg.pixel_struct_wgsl()
        assert "vel_x" in wgsl

    def test_inject_into_shader(self):
        from slappyengine.shader_gen import ShaderGen
        sg = ShaderGen(self._registry_with_physics())
        template = "// before\n{{PIXEL_STRUCT}}\n// after"
        result = sg.inject_into_shader(template)
        assert "{{PIXEL_STRUCT}}" not in result
        assert "// before" in result
        assert "// after" in result

    def test_inject_replaces_placeholder(self):
        from slappyengine.shader_gen import ShaderGen
        sg = ShaderGen(self._registry_with_physics())
        template = "{{PIXEL_STRUCT}}"
        result = sg.inject_into_shader(template, struct_name="Pixel")
        # The placeholder should be replaced with struct definition
        assert "struct Pixel" in result

    def test_empty_registry(self):
        from slappyengine.shader_gen import ShaderGen
        from slappyengine.struct_registry import StructRegistry
        sg = ShaderGen(StructRegistry())
        wgsl = sg.pixel_struct_wgsl("Empty")
        assert "Empty" in wgsl


# ---------------------------------------------------------------------------
# RenderTarget
# ---------------------------------------------------------------------------

class TestRenderTarget:
    def test_instantiates(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt is not None

    def test_name_stored(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget(name="Scene")
        assert rt.name == "Scene"

    def test_default_size(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt.size == (64, 64)

    def test_custom_size(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget(size=(1280, 720))
        assert rt.size == (1280, 720)

    def test_default_position(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt.position == (0.0, 0.0)

    def test_visible_default_true(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt.visible is True

    def test_z_order_default_zero(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt.z_order == pytest.approx(0.0)

    def test_layers_initially_empty(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt.layers == []

    def test_post_process_initially_none(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt.post_process is None

    def test_add_layer(self):
        from slappyengine.render_target import RenderTarget
        from slappyengine.layer import Layer2D
        rt = RenderTarget()
        l = Layer2D(width=64, height=64)
        result = rt.add_layer(l)
        assert result is l
        assert l in rt.layers

    def test_add_layer_sets_entity(self):
        from slappyengine.render_target import RenderTarget
        from slappyengine.layer import Layer2D
        rt = RenderTarget()
        l = Layer2D()
        rt.add_layer(l)
        assert l.entity is rt

    def test_remove_layer(self):
        from slappyengine.render_target import RenderTarget
        from slappyengine.layer import Layer2D
        rt = RenderTarget()
        l = Layer2D()
        rt.add_layer(l)
        rt.remove_layer(l)
        assert l not in rt.layers

    def test_tick_no_crash(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        rt.tick(0.016)

    def test_is_entity_subclass(self):
        from slappyengine.render_target import RenderTarget
        from slappyengine.entity import Entity
        rt = RenderTarget()
        assert isinstance(rt, Entity)


# ---------------------------------------------------------------------------
# CubeArray
# ---------------------------------------------------------------------------

class TestCubeArrayDefaults:
    def test_instantiates(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        assert ca is not None

    def test_frame_count_default_one(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        assert ca.frame_count == 1

    def test_current_frame_default_zero(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        assert ca.current_frame == 0

    def test_fps_default(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        assert ca.fps == pytest.approx(24.0)

    def test_loop_default_true(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        assert ca.loop is True

    def test_playing_default_false(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        assert ca.playing is False

    def test_animation_graph_none(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        assert ca.animation_graph is None

    def test_is_render_target_subclass(self):
        from slappyengine.cube_array import CubeArray
        from slappyengine.render_target import RenderTarget
        ca = CubeArray()
        assert isinstance(ca, RenderTarget)


class TestCubeArrayPlayback:
    def test_play_sets_playing(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.play()
        assert ca.playing is True

    def test_pause_clears_playing(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.play()
        ca.pause()
        assert ca.playing is False

    def test_seek_clamps_to_range(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 10
        ca.seek(5)
        assert ca.current_frame == 5

    def test_seek_clamps_below_zero(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 10
        ca.seek(-1)
        assert ca.current_frame == 0

    def test_seek_clamps_above_max(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 10
        ca.seek(20)
        assert ca.current_frame == 9

    def test_tick_not_playing_no_frame_change(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 10
        ca.current_frame = 0
        ca.tick(1.0)
        assert ca.current_frame == 0

    def test_tick_advances_frame_when_playing(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 10
        ca.fps = 10.0
        ca.play()
        ca.tick(0.15)  # 1.5 frames elapsed → advance by 1
        assert ca.current_frame == 1

    def test_tick_loops_past_end(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 4
        ca.fps = 4.0
        ca.loop = True
        ca.play()
        ca.tick(1.5)  # 6 frames elapsed, loops: 6 % 4 = 2
        assert ca.current_frame == 2

    def test_tick_stops_at_end_no_loop(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 4
        ca.fps = 4.0
        ca.loop = False
        ca.play()
        ca.tick(2.0)  # 8 frames elapsed → clamp to 3
        assert ca.current_frame == 3
        assert ca.playing is False

    def test_tick_single_frame_no_crash(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 1
        ca.play()
        ca.tick(1.0)  # frame_count == 1, no advance
        assert ca.current_frame == 0
