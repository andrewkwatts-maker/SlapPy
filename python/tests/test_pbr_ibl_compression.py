"""Engine tests for gpu/pbr_material.py, gpu/ibl.py, residency/compression.py,
cube_array.py, shader_gen.py, shader_binding.py — all headless."""
from __future__ import annotations
import struct
import pytest
import numpy as np


# ---------------------------------------------------------------------------
# PbrMaterial
# ---------------------------------------------------------------------------

class TestPbrMaterialInit:
    def test_instantiates(self):
        from pharos_engine.gpu.pbr_material import PbrMaterial
        m = PbrMaterial()
        assert m is not None

    def test_default_metallic(self):
        from pharos_engine.gpu.pbr_material import PbrMaterial
        assert PbrMaterial().metallic == pytest.approx(0.0)

    def test_default_roughness(self):
        from pharos_engine.gpu.pbr_material import PbrMaterial
        assert PbrMaterial().roughness == pytest.approx(0.5)

    def test_default_albedo_white(self):
        from pharos_engine.gpu.pbr_material import PbrMaterial
        m = PbrMaterial()
        assert m.albedo_color == (1.0, 1.0, 1.0, 1.0)

    def test_default_emissive_black(self):
        from pharos_engine.gpu.pbr_material import PbrMaterial
        m = PbrMaterial()
        assert m.emissive_color == (0.0, 0.0, 0.0)

    def test_default_emissive_strength_zero(self):
        from pharos_engine.gpu.pbr_material import PbrMaterial
        assert PbrMaterial().emissive_strength == pytest.approx(0.0)

    def test_default_ior(self):
        from pharos_engine.gpu.pbr_material import PbrMaterial
        assert PbrMaterial().ior == pytest.approx(1.5)

    def test_albedo_texture_none(self):
        from pharos_engine.gpu.pbr_material import PbrMaterial
        assert PbrMaterial().albedo_texture is None

    def test_normal_map_none(self):
        from pharos_engine.gpu.pbr_material import PbrMaterial
        assert PbrMaterial().normal_map is None

    def test_custom_values(self):
        from pharos_engine.gpu.pbr_material import PbrMaterial
        m = PbrMaterial(metallic=1.0, roughness=0.0, ior=2.0)
        assert m.metallic == pytest.approx(1.0)
        assert m.roughness == pytest.approx(0.0)
        assert m.ior == pytest.approx(2.0)


class TestPbrMaterialToGpuBytes:
    def test_returns_bytes(self):
        from pharos_engine.gpu.pbr_material import PbrMaterial
        result = PbrMaterial().to_gpu_bytes()
        assert isinstance(result, bytes)

    def test_length_48_bytes(self):
        from pharos_engine.gpu.pbr_material import PbrMaterial
        assert len(PbrMaterial().to_gpu_bytes()) == 48

    def test_albedo_at_offset_0(self):
        from pharos_engine.gpu.pbr_material import PbrMaterial
        m = PbrMaterial(albedo_color=(0.5, 0.25, 0.75, 1.0))
        data = m.to_gpu_bytes()
        r, g, b, a = struct.unpack_from("4f", data, 0)
        assert r == pytest.approx(0.5)
        assert g == pytest.approx(0.25)
        assert b == pytest.approx(0.75)

    def test_metallic_at_offset_16(self):
        from pharos_engine.gpu.pbr_material import PbrMaterial
        m = PbrMaterial(metallic=0.8)
        data = m.to_gpu_bytes()
        metallic = struct.unpack_from("f", data, 16)[0]
        assert metallic == pytest.approx(0.8)

    def test_roughness_at_offset_20(self):
        from pharos_engine.gpu.pbr_material import PbrMaterial
        m = PbrMaterial(roughness=0.3)
        data = m.to_gpu_bytes()
        roughness = struct.unpack_from("f", data, 20)[0]
        assert roughness == pytest.approx(0.3)

    def test_emissive_at_offset_32(self):
        from pharos_engine.gpu.pbr_material import PbrMaterial
        m = PbrMaterial(emissive_color=(1.0, 0.5, 0.0))
        data = m.to_gpu_bytes()
        er, eg, eb = struct.unpack_from("3f", data, 32)
        assert er == pytest.approx(1.0)
        assert eg == pytest.approx(0.5)
        assert eb == pytest.approx(0.0)

    def test_emissive_strength_at_offset_44(self):
        from pharos_engine.gpu.pbr_material import PbrMaterial
        m = PbrMaterial(emissive_strength=2.5)
        data = m.to_gpu_bytes()
        strength = struct.unpack_from("f", data, 44)[0]
        assert strength == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# IBLSystem (headless — no GPU)
# ---------------------------------------------------------------------------

class TestIBLSystemInit:
    def test_instantiates(self):
        from pharos_engine.gpu.ibl import IBLSystem
        ibl = IBLSystem()
        assert ibl is not None

    def test_sh_coeffs_is_9(self):
        from pharos_engine.gpu.ibl import IBLSystem
        assert IBLSystem.SH_COEFFS == 9

    def test_brdf_lut_size(self):
        from pharos_engine.gpu.ibl import IBLSystem
        assert IBLSystem.BRDF_LUT_SIZE == 512

    def test_prefilter_mips(self):
        from pharos_engine.gpu.ibl import IBLSystem
        assert IBLSystem.PREFILTER_MIPS == 8

    def test_not_initialized_without_gpu(self):
        from pharos_engine.gpu.ibl import IBLSystem
        ibl = IBLSystem()
        assert ibl._initialized is False

    def test_gpu_initially_none(self):
        from pharos_engine.gpu.ibl import IBLSystem
        ibl = IBLSystem()
        assert ibl._gpu is None

    def test_default_sh_l0_coefficient(self):
        from pharos_engine.gpu.ibl import IBLSystem
        import math
        ibl = IBLSystem()
        # L0 Y0,0 = 1 / (2 * sqrt(pi)) ≈ 0.282095
        assert ibl._default_sh[0] == pytest.approx(0.282095, abs=1e-4)

    def test_init_gpu_none_no_crash(self):
        from pharos_engine.gpu.ibl import IBLSystem
        ibl = IBLSystem()
        ibl.init_gpu(None, width=640, height=480)
        assert ibl._initialized is False


# ---------------------------------------------------------------------------
# residency/compression.py
# ---------------------------------------------------------------------------

class TestCompressArray:
    def test_compress_returns_bytes(self):
        from pharos_engine.residency.compression import compress_array
        arr = np.zeros((4, 4), dtype=np.float32)
        result = compress_array(arr)
        assert isinstance(result, bytes)

    def test_roundtrip_zeros(self):
        from pharos_engine.residency.compression import compress_array, decompress_array
        arr = np.zeros((8, 8), dtype=np.float32)
        data = compress_array(arr)
        restored = decompress_array(data, shape=(8, 8))
        np.testing.assert_array_almost_equal(restored, arr)

    def test_roundtrip_random(self):
        from pharos_engine.residency.compression import compress_array, decompress_array
        rng = np.random.default_rng(42)
        arr = rng.random((16, 16), dtype=np.float32)
        data = compress_array(arr)
        restored = decompress_array(data, shape=(16, 16))
        np.testing.assert_array_almost_equal(restored, arr)

    def test_compressed_smaller_than_original(self):
        from pharos_engine.residency.compression import compress_array
        arr = np.zeros((64, 64), dtype=np.float32)
        data = compress_array(arr)
        assert len(data) < arr.nbytes

    def test_compress_int_array_promoted_to_float32(self):
        from pharos_engine.residency.compression import compress_array, decompress_array
        arr = np.array([[1, 2], [3, 4]], dtype=np.int32)
        data = compress_array(arr)
        restored = decompress_array(data, shape=(2, 2))
        assert restored.dtype == np.float32

    def test_roundtrip_3d_array(self):
        from pharos_engine.residency.compression import compress_array, decompress_array
        arr = np.ones((4, 4, 4), dtype=np.float32) * 0.5
        data = compress_array(arr)
        restored = decompress_array(data, shape=(4, 4, 4))
        np.testing.assert_array_almost_equal(restored, arr)


class TestCompressRaw:
    def test_compress_returns_bytes(self):
        from pharos_engine.residency.compression import compress_raw
        result = compress_raw(b"hello world" * 100)
        assert isinstance(result, bytes)

    def test_roundtrip(self):
        from pharos_engine.residency.compression import compress_raw, decompress_raw
        original = b"the quick brown fox" * 50
        compressed = compress_raw(original)
        restored = decompress_raw(compressed)
        assert restored == original

    def test_compressed_smaller(self):
        from pharos_engine.residency.compression import compress_raw
        data = b"\x00" * 1000
        compressed = compress_raw(data)
        assert len(compressed) < len(data)


# ---------------------------------------------------------------------------
# CubeArray
# ---------------------------------------------------------------------------

class TestCubeArrayInit:
    def test_instantiates(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        assert ca is not None

    def test_default_frame_count(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        assert ca.frame_count == 1

    def test_default_current_frame(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        assert ca.current_frame == 0

    def test_default_fps(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        assert ca.fps == pytest.approx(24.0)

    def test_not_playing_by_default(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        assert ca.playing is False

    def test_loop_true_by_default(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        assert ca.loop is True

    def test_name_stored(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray(name="Explosion")
        assert ca.name == "Explosion"


class TestCubeArrayPlayback:
    def test_play_sets_playing(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        ca.play()
        assert ca.playing is True

    def test_pause_clears_playing(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        ca.play()
        ca.pause()
        assert ca.playing is False

    def test_seek_sets_frame(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 10
        ca.seek(5)
        assert ca.current_frame == 5

    def test_seek_clamped_to_zero(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 5
        ca.seek(-10)
        assert ca.current_frame == 0

    def test_seek_clamped_to_last_frame(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 5
        ca.seek(100)
        assert ca.current_frame == 4

    def test_tick_advances_frame_when_playing(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 4
        ca.fps = 4.0          # 1 frame per second at 4fps
        ca.loop = True
        ca.play()
        ca.tick(0.26)         # ~1 frame elapsed
        assert ca.current_frame == 1

    def test_tick_wraps_when_loop(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 2
        ca.fps = 2.0
        ca.loop = True
        ca.play()
        ca.tick(2.0)          # 4 frames elapsed, wraps
        assert ca.current_frame == 0  # 4 % 2 == 0

    def test_tick_stops_at_last_frame_no_loop(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 3
        ca.fps = 3.0
        ca.loop = False
        ca.play()
        ca.tick(10.0)         # way past end
        assert ca.current_frame == 2
        assert ca.playing is False

    def test_tick_idle_when_not_playing(self):
        from pharos_engine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 10
        ca.tick(1.0)
        assert ca.current_frame == 0


# ---------------------------------------------------------------------------
# ShaderGen
# ---------------------------------------------------------------------------

class TestShaderGen:
    def _make_registry(self):
        from pharos_engine.struct_registry import StructRegistry, StructModule
        class _Mod(StructModule):
            name = "test"
            channels = [("hp", "f32"), ("mana", "f32")]
            default_values = {"hp": 1.0, "mana": 1.0}
            compute_passes = []
        reg = StructRegistry()
        reg.register(_Mod)
        return reg

    def test_pixel_struct_wgsl_returns_string(self):
        from pharos_engine.shader_gen import ShaderGen
        gen = ShaderGen(self._make_registry())
        result = gen.pixel_struct_wgsl()
        assert isinstance(result, str)

    def test_pixel_struct_contains_struct_keyword(self):
        from pharos_engine.shader_gen import ShaderGen
        gen = ShaderGen(self._make_registry())
        result = gen.pixel_struct_wgsl("PixelData")
        assert "struct PixelData" in result

    def test_pixel_struct_contains_field_names(self):
        from pharos_engine.shader_gen import ShaderGen
        gen = ShaderGen(self._make_registry())
        result = gen.pixel_struct_wgsl()
        assert "hp" in result
        assert "mana" in result

    def test_pixel_struct_contains_types(self):
        from pharos_engine.shader_gen import ShaderGen
        gen = ShaderGen(self._make_registry())
        result = gen.pixel_struct_wgsl()
        assert "f32" in result

    def test_custom_struct_name(self):
        from pharos_engine.shader_gen import ShaderGen
        gen = ShaderGen(self._make_registry())
        result = gen.pixel_struct_wgsl("MyStruct")
        assert "struct MyStruct" in result

    def test_inject_into_shader_replaces_placeholder(self):
        from pharos_engine.shader_gen import ShaderGen
        gen = ShaderGen(self._make_registry())
        template = "// before\n{{PIXEL_STRUCT}}\n// after"
        result = gen.inject_into_shader(template)
        assert "{{PIXEL_STRUCT}}" not in result
        assert "struct PixelData" in result

    def test_inject_preserves_surrounding(self):
        from pharos_engine.shader_gen import ShaderGen
        gen = ShaderGen(self._make_registry())
        template = "A {{PIXEL_STRUCT}} B"
        result = gen.inject_into_shader(template)
        assert result.startswith("A ")
        assert result.endswith(" B")


# ---------------------------------------------------------------------------
# ShaderBinding
# ---------------------------------------------------------------------------

class TestShaderBindingInit:
    def test_instantiates(self):
        from pharos_engine.shader_binding import ShaderBinding
        sb = ShaderBinding(
            source_module="pixel_physics",
            source_field="temperature",
            target_shader="lighting",
            target_param="emission",
        )
        assert sb is not None

    def test_defaults(self):
        from pharos_engine.shader_binding import ShaderBinding
        sb = ShaderBinding(
            source_module="m", source_field="f",
            target_shader="s", target_param="p",
        )
        assert sb.transform == "linear"
        assert sb.input_range == (0.0, 1.0)
        assert sb.output_range == (0.0, 1.0)
        assert sb.clamp is True
        assert sb.custom_wgsl == ""


class TestShaderBindingEvaluate:
    def _sb(self, transform="linear", input_range=(0.0, 1.0),
            output_range=(0.0, 1.0), clamp=True, custom=""):
        from pharos_engine.shader_binding import ShaderBinding
        return ShaderBinding(
            source_module="m", source_field="f",
            target_shader="s", target_param="p",
            transform=transform,
            input_range=input_range,
            output_range=output_range,
            clamp=clamp,
            custom_wgsl=custom,
        )

    def test_linear_midpoint(self):
        sb = self._sb()
        assert sb.evaluate(0.5) == pytest.approx(0.5)

    def test_linear_remapped(self):
        sb = self._sb(input_range=(0.0, 10.0), output_range=(0.0, 100.0))
        assert sb.evaluate(5.0) == pytest.approx(50.0)

    def test_clamp_below_min(self):
        sb = self._sb(input_range=(0.0, 1.0), output_range=(0.0, 1.0), clamp=True)
        assert sb.evaluate(-1.0) == pytest.approx(0.0)

    def test_clamp_above_max(self):
        sb = self._sb(input_range=(0.0, 1.0), output_range=(0.0, 2.0), clamp=True)
        assert sb.evaluate(10.0) == pytest.approx(2.0)

    def test_pow2_curvature(self):
        sb = self._sb(transform="pow2")
        # at 0.5 input → t=0.5 → t^2=0.25 → output 0.25
        assert sb.evaluate(0.5) == pytest.approx(0.25)

    def test_sqrt_curvature(self):
        import math
        sb = self._sb(transform="sqrt")
        # at 0.25 input → t=0.25 → sqrt(0.25)=0.5
        assert sb.evaluate(0.25) == pytest.approx(0.5)

    def test_equal_input_range_returns_zero(self):
        sb = self._sb(input_range=(5.0, 5.0))
        assert sb.evaluate(5.0) == pytest.approx(0.0)

    def test_no_clamp_allows_extrapolation(self):
        sb = self._sb(input_range=(0.0, 1.0), output_range=(0.0, 1.0), clamp=False)
        assert sb.evaluate(2.0) == pytest.approx(2.0)


class TestShaderBindingToWgsl:
    def test_returns_string(self):
        from pharos_engine.shader_binding import ShaderBinding
        sb = ShaderBinding("m", "f", "s", "p")
        result = sb.to_wgsl_expr()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_output_offset(self):
        from pharos_engine.shader_binding import ShaderBinding
        # output starts at 5.0
        sb = ShaderBinding("m", "f", "s", "p",
                           output_range=(5.0, 10.0))
        expr = sb.to_wgsl_expr()
        assert "5.0" in expr

    def test_pow2_expr_contains_pow(self):
        from pharos_engine.shader_binding import ShaderBinding
        sb = ShaderBinding("m", "f", "s", "p", transform="pow2")
        expr = sb.to_wgsl_expr()
        assert "pow" in expr

    def test_sqrt_expr_contains_sqrt(self):
        from pharos_engine.shader_binding import ShaderBinding
        sb = ShaderBinding("m", "f", "s", "p", transform="sqrt")
        expr = sb.to_wgsl_expr()
        assert "sqrt" in expr
