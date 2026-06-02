"""Headless tests for strata, compression, and struct_registry modules.

Covers:
- slappyengine.strata                (StrataLayer, StrataWorld)
- slappyengine.residency.compression (compress_array, decompress_array, compress_raw, decompress_raw)
- slappyengine.struct_registry       (WGSL_TYPE_INFO, StructModule, StructRegistry)
"""
from __future__ import annotations
import numpy as np


# ---------------------------------------------------------------------------
# strata.py
# ---------------------------------------------------------------------------

class TestStrataLayer:
    def test_instantiates(self):
        from slappyengine.strata import StrataLayer
        sl = StrataLayer(name="Physical", index=0, tint=(1.0, 1.0, 1.0, 1.0))
        assert sl is not None

    def test_name_stored(self):
        from slappyengine.strata import StrataLayer
        sl = StrataLayer(name="Cyber", index=1, tint=(0.4, 0.6, 1.0, 0.9))
        assert sl.name == "Cyber"

    def test_index_stored(self):
        from slappyengine.strata import StrataLayer
        sl = StrataLayer(name="x", index=2, tint=(1.0, 0.3, 0.2, 0.9))
        assert sl.index == 2

    def test_tint_stored(self):
        from slappyengine.strata import StrataLayer
        tint = (0.5, 0.5, 0.5, 1.0)
        sl = StrataLayer(name="mid", index=0, tint=tint)
        assert sl.tint == tint

    def test_default_parallax(self):
        from slappyengine.strata import StrataLayer
        sl = StrataLayer(name="x", index=0, tint=(1, 1, 1, 1))
        assert sl.parallax == 1.0

    def test_custom_parallax(self):
        from slappyengine.strata import StrataLayer
        sl = StrataLayer(name="bg", index=0, tint=(1, 1, 1, 1), parallax=0.8)
        assert sl.parallax == 0.8


class TestStrataWorld:
    def _make_world(self):
        from slappyengine.strata import StrataLayer, StrataWorld
        layers = [
            StrataLayer("Physical", 0, (1.0, 1.0, 1.0, 1.0)),
            StrataLayer("Cyber",    1, (0.4, 0.6, 1.0, 0.9)),
            StrataLayer("Ruined",   2, (1.0, 0.35, 0.2, 0.9)),
        ]
        return StrataWorld(layers)

    def test_instantiates(self):
        w = self._make_world()
        assert w is not None

    def test_active_index_zero(self):
        w = self._make_world()
        assert w.active_index == 0

    def test_inactive_dim_default(self):
        w = self._make_world()
        assert abs(w.inactive_dim - 0.35) < 1e-9

    def test_active_layer_returns_first(self):
        from slappyengine.strata import StrataLayer
        w = self._make_world()
        assert isinstance(w.active_layer, StrataLayer)
        assert w.active_layer.index == 0

    def test_set_active_changes_layer(self):
        w = self._make_world()
        w.set_active(1)
        assert w.active_index == 1
        assert w.active_layer.name == "Cyber"

    def test_set_active_wraps(self):
        w = self._make_world()
        w.set_active(3)  # wraps: 3 % 3 = 0
        assert w.active_index == 0

    def test_get_layer_valid(self):
        from slappyengine.strata import StrataLayer
        w = self._make_world()
        layer = w.get_layer(1)
        assert isinstance(layer, StrataLayer)
        assert layer.index == 1

    def test_get_layer_out_of_range(self):
        w = self._make_world()
        assert w.get_layer(99) is None

    def test_get_layer_negative(self):
        w = self._make_world()
        assert w.get_layer(-1) is None

    def test_entity_visibility_active_layer_is_one(self):
        w = self._make_world()

        class E:
            strata_layer = 0

        assert abs(w.entity_visibility_alpha(E()) - 1.0) < 1e-9

    def test_entity_visibility_inactive_layer_dim(self):
        w = self._make_world()

        class E:
            strata_layer = 1  # not active (active=0)

        assert abs(w.entity_visibility_alpha(E()) - 0.35) < 1e-9

    def test_entity_visibility_no_strata_layer_attr(self):
        w = self._make_world()

        class E:
            pass

        # defaults to layer 0 which is active → 1.0
        assert abs(w.entity_visibility_alpha(E()) - 1.0) < 1e-9

    def test_entity_tint_active_layer(self):
        w = self._make_world()

        class E:
            strata_layer = 0

        tint = w.entity_tint(E())
        assert tint == (1.0, 1.0, 1.0, 1.0)

    def test_entity_tint_invalid_layer_returns_white(self):
        w = self._make_world()

        class E:
            strata_layer = 99

        assert w.entity_tint(E()) == (1.0, 1.0, 1.0, 1.0)

    def test_begin_phase_sets_half_alpha(self):
        w = self._make_world()

        class E:
            strata_layer = 1  # inactive layer (active=0)

        e = E()
        w.begin_phase(e)
        assert abs(w.entity_visibility_alpha(e) - 0.5) < 1e-9

    def test_end_phase_removes_transition(self):
        w = self._make_world()

        class E:
            strata_layer = 1

        e = E()
        w.begin_phase(e)
        w.end_phase(e)
        # back to inactive dim
        assert abs(w.entity_visibility_alpha(e) - 0.35) < 1e-9

    def test_tick_advances_transitions(self):
        w = self._make_world()

        class E:
            strata_layer = 1

        e = E()
        w.begin_phase(e)
        initial = w.entity_visibility_alpha(e)
        w.tick(0.1)
        assert w.entity_visibility_alpha(e) > initial

    def test_tick_completes_transition(self):
        w = self._make_world()

        class E:
            strata_layer = 0

        e = E()
        w.begin_phase(e)
        w.tick(10.0)  # large dt — complete immediately
        # Transition removed → back to normal visibility
        assert id(e) not in w._phase_transitions


# ---------------------------------------------------------------------------
# residency/compression.py
# ---------------------------------------------------------------------------

class TestCompressArray:
    def test_returns_bytes(self):
        from slappyengine.residency.compression import compress_array
        arr = np.zeros((4, 4), dtype=np.float32)
        result = compress_array(arr)
        assert isinstance(result, bytes)

    def test_nonempty(self):
        from slappyengine.residency.compression import compress_array
        arr = np.ones((10, 10), dtype=np.float32)
        result = compress_array(arr)
        assert len(result) > 0

    def test_int_array_works(self):
        from slappyengine.residency.compression import compress_array
        arr = np.array([1, 2, 3, 4], dtype=np.int32)
        result = compress_array(arr)
        assert isinstance(result, bytes)


class TestDecompressArray:
    def test_roundtrip(self):
        from slappyengine.residency.compression import compress_array, decompress_array
        arr = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
        compressed = compress_array(arr)
        recovered = decompress_array(compressed, shape=(2, 2))
        np.testing.assert_array_almost_equal(arr, recovered)

    def test_zeros_roundtrip(self):
        from slappyengine.residency.compression import compress_array, decompress_array
        arr = np.zeros((8, 8), dtype=np.float32)
        compressed = compress_array(arr)
        recovered = decompress_array(compressed, shape=(8, 8))
        np.testing.assert_array_equal(arr, recovered)

    def test_large_array_roundtrip(self):
        from slappyengine.residency.compression import compress_array, decompress_array
        arr = np.random.rand(64, 64).astype(np.float32)
        compressed = compress_array(arr)
        recovered = decompress_array(compressed, shape=(64, 64))
        np.testing.assert_array_almost_equal(arr, recovered)


class TestCompressDecompressRaw:
    def test_compress_returns_bytes(self):
        from slappyengine.residency.compression import compress_raw
        result = compress_raw(b"hello world")
        assert isinstance(result, bytes)

    def test_roundtrip_raw(self):
        from slappyengine.residency.compression import compress_raw, decompress_raw
        data = b"The quick brown fox jumps over the lazy dog"
        compressed = compress_raw(data)
        recovered = decompress_raw(compressed)
        assert recovered == data

    def test_empty_bytes_roundtrip(self):
        from slappyengine.residency.compression import compress_raw, decompress_raw
        data = b""
        compressed = compress_raw(data)
        recovered = decompress_raw(compressed)
        assert recovered == data

    def test_binary_data_roundtrip(self):
        from slappyengine.residency.compression import compress_raw, decompress_raw
        data = bytes(range(256))
        compressed = compress_raw(data)
        recovered = decompress_raw(compressed)
        assert recovered == data


# ---------------------------------------------------------------------------
# struct_registry.py — WGSL_TYPE_INFO constant
# ---------------------------------------------------------------------------

class TestWgslTypeInfo:
    def test_f32_size(self):
        from slappyengine.struct_registry import WGSL_TYPE_INFO
        size, align = WGSL_TYPE_INFO["f32"]
        assert size == 4

    def test_f32_align(self):
        from slappyengine.struct_registry import WGSL_TYPE_INFO
        size, align = WGSL_TYPE_INFO["f32"]
        assert align == 4

    def test_vec4f_size(self):
        from slappyengine.struct_registry import WGSL_TYPE_INFO
        size, align = WGSL_TYPE_INFO["vec4f"]
        assert size == 16

    def test_vec4f_align(self):
        from slappyengine.struct_registry import WGSL_TYPE_INFO
        size, align = WGSL_TYPE_INFO["vec4f"]
        assert align == 16

    def test_vec3f_size(self):
        from slappyengine.struct_registry import WGSL_TYPE_INFO
        size, align = WGSL_TYPE_INFO["vec3f"]
        assert size == 12

    def test_vec3f_align_16(self):
        from slappyengine.struct_registry import WGSL_TYPE_INFO
        # vec3 has 16-byte alignment in structs
        size, align = WGSL_TYPE_INFO["vec3f"]
        assert align == 16

    def test_vec2f_size(self):
        from slappyengine.struct_registry import WGSL_TYPE_INFO
        size, align = WGSL_TYPE_INFO["vec2f"]
        assert size == 8

    def test_u32_and_i32_match_f32(self):
        from slappyengine.struct_registry import WGSL_TYPE_INFO
        assert WGSL_TYPE_INFO["u32"] == WGSL_TYPE_INFO["f32"]
        assert WGSL_TYPE_INFO["i32"] == WGSL_TYPE_INFO["f32"]

    def test_six_types(self):
        from slappyengine.struct_registry import WGSL_TYPE_INFO
        assert len(WGSL_TYPE_INFO) == 6


# ---------------------------------------------------------------------------
# struct_registry.py — StructRegistry
# ---------------------------------------------------------------------------

class TestStructRegistry:
    def test_instantiates(self):
        from slappyengine.struct_registry import StructRegistry
        r = StructRegistry()
        assert r is not None

    def test_initial_channels_has_color(self):
        from slappyengine.struct_registry import StructRegistry
        r = StructRegistry()
        names = [n for n, _ in r.channels]
        assert "color" in names

    def test_not_locked_initially(self):
        from slappyengine.struct_registry import StructRegistry
        r = StructRegistry()
        assert r._locked is False

    def test_lock_sets_locked(self):
        from slappyengine.struct_registry import StructRegistry
        r = StructRegistry()
        r.lock()
        assert r._locked is True

    def test_register_after_lock_raises(self):
        import pytest
        from slappyengine.struct_registry import StructRegistry, StructModule

        class MyMod(StructModule):
            name = "health"
            channels = [("hp", "f32")]

        r = StructRegistry()
        r.lock()
        with pytest.raises(RuntimeError):
            r.register(MyMod)

    def test_register_module_adds_channels(self):
        from slappyengine.struct_registry import StructRegistry, StructModule

        class HpMod(StructModule):
            name = "health"
            channels = [("hp", "f32")]

        r = StructRegistry()
        r.register(HpMod)
        names = [n for n, _ in r.channels]
        assert "hp" in names

    def test_register_duplicate_channel_raises(self):
        import pytest
        from slappyengine.struct_registry import StructRegistry, StructModule

        class ModA(StructModule):
            name = "a"
            channels = [("x", "f32")]

        class ModB(StructModule):
            name = "b"
            channels = [("x", "f32")]  # duplicate

        r = StructRegistry()
        r.register(ModA)
        with pytest.raises(ValueError):
            r.register(ModB)

    def test_stride_bytes_multiple_of_16(self):
        from slappyengine.struct_registry import StructRegistry
        r = StructRegistry()
        stride = r.stride_bytes()
        assert stride % 16 == 0

    def test_channel_offset_color_zero(self):
        from slappyengine.struct_registry import StructRegistry
        r = StructRegistry()
        assert r.channel_offset("color") == 0

    def test_default_for_channel_returns_zero_if_not_set(self):
        from slappyengine.struct_registry import StructRegistry
        r = StructRegistry()
        assert r.default_for_channel("color") == 0.0

    def test_default_for_channel_with_module_default(self):
        from slappyengine.struct_registry import StructRegistry, StructModule

        class HpMod(StructModule):
            name = "hp"
            channels = [("health", "f32")]
            default_values = {"health": 1.0}

        r = StructRegistry()
        r.register(HpMod)
        assert r.default_for_channel("health") == 1.0

    def test_required_compute_passes_empty_by_default(self):
        from slappyengine.struct_registry import StructRegistry
        r = StructRegistry()
        assert r.required_compute_passes() == []

    def test_required_compute_passes_from_module(self):
        from slappyengine.struct_registry import StructRegistry, StructModule

        class PhysMod(StructModule):
            name = "physics"
            channels = [("vel_x", "f32")]
            compute_passes = ["pixel_physics.wgsl"]

        r = StructRegistry()
        r.register(PhysMod)
        passes = r.required_compute_passes()
        assert "pixel_physics.wgsl" in passes

    def test_channels_returns_copy(self):
        from slappyengine.struct_registry import StructRegistry
        r = StructRegistry()
        ch = r.channels
        ch.append(("fake", "f32"))
        assert "fake" not in [n for n, _ in r.channels]
