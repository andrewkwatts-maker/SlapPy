"""Engine tests for LambdaToWGSL and compile_apply_shader — headless."""
from __future__ import annotations
import pytest


def _make_registry(*extra_channels):
    from slappyengine.struct_registry import StructRegistry, StructModule
    reg = StructRegistry()

    class BaseModule(StructModule):
        name = "base"
        channels = list(extra_channels) if extra_channels else []

    reg.register(BaseModule)
    return reg


def _make_registry_with(ch_list):
    from slappyengine.struct_registry import StructRegistry, StructModule
    reg = StructRegistry()
    _ch = list(ch_list)

    class Mod(StructModule):
        name = "test_mod"
        channels = _ch

    reg.register(Mod)
    return reg


class TestLambdaToWGSLConstants:
    def test_float_constant(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL
        reg = _make_registry()
        c = LambdaToWGSL(reg)
        result = c.compile_lambda(lambda px: 1.5)
        assert "1.5f" in result

    def test_int_constant(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL
        reg = _make_registry()
        c = LambdaToWGSL(reg)
        result = c.compile_lambda(lambda px: 0)
        assert "0" in result

    def test_bool_true(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL
        reg = _make_registry()
        c = LambdaToWGSL(reg)
        result = c.compile_lambda(lambda px: True)
        assert result == "true"

    def test_bool_false(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL
        reg = _make_registry()
        c = LambdaToWGSL(reg)
        result = c.compile_lambda(lambda px: False)
        assert result == "false"


class TestLambdaToWGSLAttributes:
    def test_channel_access(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL
        reg = _make_registry_with([("health", "f32")])
        c = LambdaToWGSL(reg)
        result = c.compile_lambda(lambda px: px.health)
        assert "health" in result

    def test_unknown_channel_raises(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL, ASTCompilerError
        reg = _make_registry()
        c = LambdaToWGSL(reg)
        with pytest.raises(ASTCompilerError):
            c.compile_lambda(lambda px: px.nonexistent)

    def test_used_channels_tracked(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL
        reg = _make_registry_with([("health", "f32"), ("mana", "f32")])
        c = LambdaToWGSL(reg)
        c.compile_lambda(lambda px: px.health)
        assert "health" in c.used_channels
        assert "mana" not in c.used_channels


class TestLambdaToWGSLBinOps:
    def test_addition(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL
        reg = _make_registry_with([("a", "f32"), ("b", "f32")])
        c = LambdaToWGSL(reg)
        result = c.compile_lambda(lambda px: px.a + px.b)
        assert "+" in result
        assert "a" in result
        assert "b" in result

    def test_subtraction(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL
        reg = _make_registry_with([("x", "f32")])
        c = LambdaToWGSL(reg)
        result = c.compile_lambda(lambda px: px.x - 1.0)
        assert "-" in result

    def test_multiplication(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL
        reg = _make_registry_with([("x", "f32")])
        c = LambdaToWGSL(reg)
        result = c.compile_lambda(lambda px: px.x * 2.0)
        assert "*" in result

    def test_division(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL
        reg = _make_registry_with([("x", "f32")])
        c = LambdaToWGSL(reg)
        result = c.compile_lambda(lambda px: px.x / 2.0)
        assert "/" in result

    def test_bitwise_and(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL
        reg = _make_registry_with([("tag", "u32")])
        c = LambdaToWGSL(reg)
        result = c.compile_lambda(lambda px: px.tag & 1)
        assert "&" in result


class TestLambdaToWGSLCompare:
    def test_greater_than(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL
        reg = _make_registry_with([("hp", "f32")])
        c = LambdaToWGSL(reg)
        result = c.compile_lambda(lambda px: px.hp > 0.5)
        assert ">" in result

    def test_less_than(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL
        reg = _make_registry_with([("hp", "f32")])
        c = LambdaToWGSL(reg)
        result = c.compile_lambda(lambda px: px.hp < 1.0)
        assert "<" in result

    def test_equal(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL
        reg = _make_registry_with([("tag", "u32")])
        c = LambdaToWGSL(reg)
        result = c.compile_lambda(lambda px: px.tag == 0)
        assert "==" in result


class TestLambdaToWGSLBoolOps:
    def test_and_operator(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL
        reg = _make_registry_with([("a", "f32"), ("b", "f32")])
        c = LambdaToWGSL(reg)
        result = c.compile_lambda(lambda px: px.a > 0.5 and px.b > 0.5)
        assert "&&" in result

    def test_or_operator(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL
        reg = _make_registry_with([("a", "f32"), ("b", "f32")])
        c = LambdaToWGSL(reg)
        result = c.compile_lambda(lambda px: px.a > 0.0 or px.b > 0.0)
        assert "||" in result

    def test_not_operator(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL
        reg = _make_registry_with([("alive", "f32")])
        c = LambdaToWGSL(reg)
        result = c.compile_lambda(lambda px: not px.alive > 0.0)
        assert "!" in result

    def test_unary_negate(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL
        reg = _make_registry_with([("x", "f32")])
        c = LambdaToWGSL(reg)
        result = c.compile_lambda(lambda px: -px.x)
        assert "-" in result


class TestLambdaToWGSLErrors:
    def test_non_lambda_raises(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL, ASTCompilerError
        reg = _make_registry()
        c = LambdaToWGSL(reg)
        def not_lambda(px): return 1.0
        with pytest.raises(ASTCompilerError):
            c.compile_lambda(not_lambda)

    def test_unsupported_op_raises(self):
        from slappyengine.compute.ast_compiler import LambdaToWGSL, ASTCompilerError
        reg = _make_registry_with([("x", "f32")])
        c = LambdaToWGSL(reg)
        with pytest.raises(ASTCompilerError):
            # Floor division not in BINOP_MAP
            c.compile_lambda(lambda px: px.x // 2.0)


class TestShaderGen:
    def test_pixel_struct_wgsl_contains_struct_name(self):
        from slappyengine.shader_gen import ShaderGen
        from slappyengine.struct_registry import StructRegistry, StructModule
        reg = StructRegistry()

        class Mod(StructModule):
            name = "test"
            channels = [("health", "f32")]

        reg.register(Mod)
        sg = ShaderGen(reg)
        wgsl = sg.pixel_struct_wgsl("MyPixel")
        assert "MyPixel" in wgsl

    def test_pixel_struct_wgsl_contains_channels(self):
        from slappyengine.shader_gen import ShaderGen
        from slappyengine.struct_registry import StructRegistry, StructModule
        reg = StructRegistry()

        class Mod(StructModule):
            name = "test2"
            channels = [("mana", "f32"), ("shield", "f32")]

        reg.register(Mod)
        sg = ShaderGen(reg)
        wgsl = sg.pixel_struct_wgsl()
        assert "mana" in wgsl
        assert "shield" in wgsl

    def test_inject_into_shader_replaces_placeholder(self):
        from slappyengine.shader_gen import ShaderGen
        from slappyengine.struct_registry import StructRegistry, StructModule
        reg = StructRegistry()

        class Mod(StructModule):
            name = "test3"
            channels = [("hp", "f32")]

        reg.register(Mod)
        sg = ShaderGen(reg)
        template = "// shader\n{{PIXEL_STRUCT}}\nvoid main() {}"
        result = sg.inject_into_shader(template)
        assert "{{PIXEL_STRUCT}}" not in result
        assert "hp" in result


class TestZHeight:
    def test_zlayer_init(self):
        from slappyengine.z_height import ZLayer
        zl = ZLayer(name="ground", z=0.0, parallax_x=1.0, parallax_y=0.8)
        assert zl.name == "ground"
        assert zl.z == pytest.approx(0.0)
        assert zl.parallax_x == pytest.approx(1.0)
        assert zl.parallax_y == pytest.approx(0.8)

    def test_zlayer_shadow_receiver_default(self):
        from slappyengine.z_height import ZLayer
        zl = ZLayer(name="test")
        assert zl.is_shadow_receiver is True

    def test_zaabb_shape_fields(self):
        from slappyengine.z_height import ZAABBShape
        shape = ZAABBShape(width=32.0, height=64.0, z_min=0.0, z_max=48.0)
        assert shape.width == pytest.approx(32.0)
        assert shape.z_max == pytest.approx(48.0)

    def test_check_z_aabb_no_shapes_returns_true(self):
        from slappyengine.z_height import check_z_aabb

        class E: pass
        assert check_z_aabb(E(), E()) is True

    def test_check_z_aabb_overlapping_returns_true(self):
        from slappyengine.z_height import check_z_aabb, ZAABBShape

        class E:
            z_height = 0.0
        a = E(); a.z_collision_shape = ZAABBShape(10, 10, z_min=0, z_max=10)
        b = E(); b.z_collision_shape = ZAABBShape(10, 10, z_min=5, z_max=15)
        assert check_z_aabb(a, b) is True

    def test_check_z_aabb_non_overlapping_returns_false(self):
        from slappyengine.z_height import check_z_aabb, ZAABBShape

        class E:
            z_height = 0.0
        a = E(); a.z_collision_shape = ZAABBShape(10, 10, z_min=0, z_max=5)
        b = E(); b.z_collision_shape = ZAABBShape(10, 10, z_min=10, z_max=20)
        assert check_z_aabb(a, b) is False

    def test_check_z_aabb_touching_at_boundary_returns_true(self):
        from slappyengine.z_height import check_z_aabb, ZAABBShape

        class E:
            z_height = 0.0
        a = E(); a.z_collision_shape = ZAABBShape(10, 10, z_min=0, z_max=10)
        b = E(); b.z_collision_shape = ZAABBShape(10, 10, z_min=10, z_max=20)
        assert check_z_aabb(a, b) is True

    def test_check_z_aabb_uses_entity_z_height(self):
        from slappyengine.z_height import check_z_aabb, ZAABBShape

        class E:
            pass
        a = E(); a.z_height = 0.0; a.z_collision_shape = ZAABBShape(10, 10, z_min=0, z_max=5)
        b = E(); b.z_height = 20.0; b.z_collision_shape = ZAABBShape(10, 10, z_min=0, z_max=5)
        # With z_height offset: b is at 20..25, a is at 0..5 — no overlap
        assert check_z_aabb(a, b) is False
