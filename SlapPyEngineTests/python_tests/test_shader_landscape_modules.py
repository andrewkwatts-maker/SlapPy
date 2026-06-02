"""Headless tests for shader_gen, shader_binding, and landscape modules.

Covers:
- slappyengine.shader_gen     (ShaderGen.pixel_struct_wgsl, inject_into_shader)
- slappyengine.shader_binding (ShaderBinding dataclass + evaluate + to_wgsl_expr)
- slappyengine.landscape      (TileCoord, Tile)
"""
from __future__ import annotations
import math
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# shader_gen.py — ShaderGen
# ---------------------------------------------------------------------------

class TestShaderGen:
    def _make_gen(self):
        from slappyengine.struct_registry import StructRegistry
        from slappyengine.shader_gen import ShaderGen
        r = StructRegistry()
        return ShaderGen(r), r

    def test_instantiates(self):
        gen, _ = self._make_gen()
        assert gen is not None

    def test_pixel_struct_wgsl_returns_string(self):
        gen, _ = self._make_gen()
        result = gen.pixel_struct_wgsl()
        assert isinstance(result, str)

    def test_default_struct_name(self):
        gen, _ = self._make_gen()
        result = gen.pixel_struct_wgsl()
        assert "PixelData" in result

    def test_custom_struct_name(self):
        gen, _ = self._make_gen()
        result = gen.pixel_struct_wgsl(struct_name="MyPixel")
        assert "MyPixel" in result

    def test_color_channel_in_output(self):
        gen, _ = self._make_gen()
        result = gen.pixel_struct_wgsl()
        assert "color" in result

    def test_added_channel_appears(self):
        from slappyengine.struct_registry import StructRegistry, StructModule
        from slappyengine.shader_gen import ShaderGen

        class HpMod(StructModule):
            name = "hp"
            channels = [("health", "f32")]

        r = StructRegistry()
        r.register(HpMod)
        gen = ShaderGen(r)
        result = gen.pixel_struct_wgsl()
        assert "health" in result

    def test_struct_wgsl_has_braces(self):
        gen, _ = self._make_gen()
        result = gen.pixel_struct_wgsl()
        assert "{" in result
        assert "}" in result

    def test_inject_into_shader_replaces_placeholder(self):
        gen, _ = self._make_gen()
        template = "// before\n{{PIXEL_STRUCT}}\n// after"
        result = gen.inject_into_shader(template)
        assert "{{PIXEL_STRUCT}}" not in result
        assert "PixelData" in result

    def test_inject_into_shader_preserves_surroundings(self):
        gen, _ = self._make_gen()
        template = "// before\n{{PIXEL_STRUCT}}\n// after"
        result = gen.inject_into_shader(template)
        assert "// before" in result
        assert "// after" in result

    def test_inject_no_placeholder_unchanged(self):
        gen, _ = self._make_gen()
        template = "fn main() {}"
        result = gen.inject_into_shader(template)
        assert result == "fn main() {}"


# ---------------------------------------------------------------------------
# shader_binding.py — ShaderBinding dataclass
# ---------------------------------------------------------------------------

class TestShaderBindingDefaults:
    def test_instantiates(self):
        from slappyengine.shader_binding import ShaderBinding
        sb = ShaderBinding(
            source_module="physics",
            source_field="temperature",
            target_shader="lighting",
            target_param="emission",
        )
        assert sb is not None

    def test_fields_stored(self):
        from slappyengine.shader_binding import ShaderBinding
        sb = ShaderBinding(
            source_module="A",
            source_field="B",
            target_shader="C",
            target_param="D",
        )
        assert sb.source_module == "A"
        assert sb.source_field == "B"
        assert sb.target_shader == "C"
        assert sb.target_param == "D"

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


class TestShaderBindingEvaluate:
    def _sb(self, transform="linear", in_range=(0.0, 1.0), out_range=(0.0, 1.0), clamp=True):
        from slappyengine.shader_binding import ShaderBinding
        return ShaderBinding("m", "f", "s", "p",
                             transform=transform,
                             input_range=in_range,
                             output_range=out_range,
                             clamp=clamp)

    def test_linear_midpoint(self):
        sb = self._sb()
        assert abs(sb.evaluate(0.5) - 0.5) < 1e-9

    def test_linear_zero(self):
        sb = self._sb()
        assert abs(sb.evaluate(0.0) - 0.0) < 1e-9

    def test_linear_one(self):
        sb = self._sb()
        assert abs(sb.evaluate(1.0) - 1.0) < 1e-9

    def test_linear_clamped_above(self):
        sb = self._sb()
        # Input above hi_in → clamped to 1.0 → output = 1.0
        assert abs(sb.evaluate(5.0) - 1.0) < 1e-9

    def test_linear_clamped_below(self):
        sb = self._sb()
        # Input below lo_in → clamped to 0.0 → output = 0.0
        assert abs(sb.evaluate(-1.0) - 0.0) < 1e-9

    def test_output_range_scaling(self):
        sb = self._sb(out_range=(0.0, 10.0))
        assert abs(sb.evaluate(0.5) - 5.0) < 1e-9

    def test_pow2_squaring(self):
        sb = self._sb(transform="pow2")
        # t=0.5 → t^2=0.25, output=0.25
        assert abs(sb.evaluate(0.5) - 0.25) < 1e-9

    def test_pow2_zero(self):
        sb = self._sb(transform="pow2")
        assert abs(sb.evaluate(0.0) - 0.0) < 1e-9

    def test_pow2_one(self):
        sb = self._sb(transform="pow2")
        assert abs(sb.evaluate(1.0) - 1.0) < 1e-9

    def test_sqrt_midpoint(self):
        sb = self._sb(transform="sqrt")
        # t=0.25 → sqrt(0.25)=0.5
        assert abs(sb.evaluate(0.25) - 0.5) < 1e-9

    def test_planck_monotonic(self):
        sb = self._sb(transform="planck")
        results = [sb.evaluate(v) for v in [0.0, 0.25, 0.5, 0.75, 1.0]]
        assert results == sorted(results)

    def test_custom_input_range(self):
        sb = self._sb(in_range=(100.0, 200.0))
        # val=150 → t=0.5 → output=0.5
        assert abs(sb.evaluate(150.0) - 0.5) < 1e-9

    def test_degenerate_input_range_no_crash(self):
        # hi_in == lo_in → t=0
        sb = self._sb(in_range=(1.0, 1.0))
        result = sb.evaluate(1.0)
        assert isinstance(result, float)


class TestShaderBindingToWgsl:
    def test_returns_string(self):
        from slappyengine.shader_binding import ShaderBinding
        sb = ShaderBinding("m", "f", "s", "p")
        result = sb.to_wgsl_expr()
        assert isinstance(result, str)

    def test_contains_output_range_start(self):
        from slappyengine.shader_binding import ShaderBinding
        sb = ShaderBinding("m", "f", "s", "p", output_range=(0.0, 5.0))
        result = sb.to_wgsl_expr()
        assert "0.0" in result

    def test_pow2_contains_pow(self):
        from slappyengine.shader_binding import ShaderBinding
        sb = ShaderBinding("m", "f", "s", "p", transform="pow2")
        result = sb.to_wgsl_expr()
        assert "pow" in result

    def test_sqrt_contains_sqrt(self):
        from slappyengine.shader_binding import ShaderBinding
        sb = ShaderBinding("m", "f", "s", "p", transform="sqrt")
        result = sb.to_wgsl_expr()
        assert "sqrt" in result

    def test_custom_wgsl_substituted(self):
        from slappyengine.shader_binding import ShaderBinding
        sb = ShaderBinding("m", "f", "s", "p",
                           transform="custom_wgsl",
                           custom_wgsl="val * val * 2.0")
        result = sb.to_wgsl_expr()
        assert "2.0" in result


# ---------------------------------------------------------------------------
# landscape.py — TileCoord
# ---------------------------------------------------------------------------

class TestTileCoord:
    def test_instantiates(self):
        from slappyengine.landscape import TileCoord
        tc = TileCoord(3, 7)
        assert tc is not None

    def test_x_stored(self):
        from slappyengine.landscape import TileCoord
        tc = TileCoord(5, 2)
        assert tc.x == 5

    def test_y_stored(self):
        from slappyengine.landscape import TileCoord
        tc = TileCoord(5, 2)
        assert tc.y == 2

    def test_equality(self):
        from slappyengine.landscape import TileCoord
        a = TileCoord(1, 2)
        b = TileCoord(1, 2)
        assert a == b

    def test_inequality(self):
        from slappyengine.landscape import TileCoord
        a = TileCoord(1, 2)
        b = TileCoord(3, 4)
        assert a != b

    def test_hash_equal_for_same_coords(self):
        from slappyengine.landscape import TileCoord
        a = TileCoord(5, 7)
        b = TileCoord(5, 7)
        assert hash(a) == hash(b)

    def test_hash_different_for_different_coords(self):
        from slappyengine.landscape import TileCoord
        a = TileCoord(1, 0)
        b = TileCoord(0, 1)
        assert hash(a) != hash(b)

    def test_usable_as_dict_key(self):
        from slappyengine.landscape import TileCoord
        d = {}
        tc = TileCoord(3, 4)
        d[tc] = "test"
        assert d[TileCoord(3, 4)] == "test"

    def test_repr(self):
        from slappyengine.landscape import TileCoord
        tc = TileCoord(3, 4)
        assert "3" in repr(tc)
        assert "4" in repr(tc)

    def test_equality_with_non_tile_coord(self):
        from slappyengine.landscape import TileCoord
        tc = TileCoord(1, 2)
        result = tc.__eq__("not a tile coord")
        assert result is NotImplemented


class TestTile:
    def test_instantiates(self):
        from slappyengine.landscape import Tile, TileCoord
        tile = Tile(TileCoord(0, 0), tile_size=256)
        assert tile is not None

    def test_coord_stored(self):
        from slappyengine.landscape import Tile, TileCoord
        tc = TileCoord(3, 7)
        tile = Tile(tc, tile_size=128)
        assert tile.coord is tc

    def test_tile_size_stored(self):
        from slappyengine.landscape import Tile, TileCoord
        tile = Tile(TileCoord(0, 0), tile_size=512)
        assert tile.tile_size == 512

    def test_name_from_coord(self):
        from slappyengine.landscape import Tile, TileCoord
        tile = Tile(TileCoord(2, 5), tile_size=256)
        assert "2" in tile.name
        assert "5" in tile.name

    def test_position_from_coord(self):
        from slappyengine.landscape import Tile, TileCoord
        tile = Tile(TileCoord(1, 2), tile_size=256)
        assert tile.position == (256.0, 512.0)

    def test_dirty_false_initially(self):
        from slappyengine.landscape import Tile, TileCoord
        tile = Tile(TileCoord(0, 0), tile_size=64)
        assert tile._dirty is False

    def test_mark_dirty(self):
        from slappyengine.landscape import Tile, TileCoord
        tile = Tile(TileCoord(0, 0), tile_size=64)
        tile.mark_dirty()
        assert tile._dirty is True

    def test_mark_clean(self):
        from slappyengine.landscape import Tile, TileCoord
        tile = Tile(TileCoord(0, 0), tile_size=64)
        tile.mark_dirty()
        tile.mark_clean()
        assert tile._dirty is False
