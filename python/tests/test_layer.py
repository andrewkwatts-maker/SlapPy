"""Engine tests for layer.py — Layer, Layer2D, Layer3D, LayerDataBuffer.
All headless — no GPU/wgpu required.
"""
from __future__ import annotations
import pytest
import numpy as np


# ---------------------------------------------------------------------------
# Layer base class
# ---------------------------------------------------------------------------

class TestLayerDefaults:
    def test_instantiates(self):
        from slappyengine.layer import Layer
        l = Layer()
        assert l is not None

    def test_default_name(self):
        from slappyengine.layer import Layer
        l = Layer()
        assert l.name == "Layer"

    def test_custom_name(self):
        from slappyengine.layer import Layer
        l = Layer(name="Background")
        assert l.name == "Background"

    def test_default_mode_2d(self):
        from slappyengine.layer import Layer
        l = Layer()
        assert l.mode == "2D"

    def test_custom_mode(self):
        from slappyengine.layer import Layer
        l = Layer(name="x", mode="3D")
        assert l.mode == "3D"

    def test_blend_mode_default_normal(self):
        from slappyengine.layer import Layer
        l = Layer()
        assert l.blend_mode == "normal"

    def test_visible_default_true(self):
        from slappyengine.layer import Layer
        l = Layer()
        assert l.visible is True

    def test_opacity_default_one(self):
        from slappyengine.layer import Layer
        l = Layer()
        assert l.opacity == pytest.approx(1.0)

    def test_image_data_initially_none(self):
        from slappyengine.layer import Layer
        l = Layer()
        assert l._image_data is None

    def test_size_returns_none_without_data(self):
        from slappyengine.layer import Layer
        l = Layer()
        assert l.size is None

    def test_entity_initially_none(self):
        from slappyengine.layer import Layer
        l = Layer()
        assert l.entity is None

    def test_visual_texture_initially_none(self):
        from slappyengine.layer import Layer
        l = Layer()
        assert l.visual_texture is None

    def test_texture_dirty_flag_true(self):
        from slappyengine.layer import Layer
        l = Layer()
        assert l._texture_dirty is True

    def test_channel_map_defaults(self):
        from slappyengine.layer import Layer
        l = Layer()
        assert l.channel_map["R"] == "visual_red"
        assert l.channel_map["G"] == "visual_green"
        assert l.channel_map["B"] == "visual_blue"
        assert l.channel_map["A"] == "opacity"


class TestLayerBlank:
    def test_blank_returns_layer(self):
        from slappyengine.layer import Layer
        l = Layer.blank(32, 32)
        assert l is not None

    def test_blank_image_data_shape(self):
        from slappyengine.layer import Layer
        l = Layer.blank(32, 16)
        assert l._image_data.shape == (16, 32, 4)

    def test_blank_image_data_dtype(self):
        from slappyengine.layer import Layer
        l = Layer.blank(32, 32)
        assert l._image_data.dtype == np.uint8

    def test_blank_image_data_zeros(self):
        from slappyengine.layer import Layer
        l = Layer.blank(32, 32)
        assert np.all(l._image_data == 0)

    def test_blank_size_property(self):
        from slappyengine.layer import Layer
        l = Layer.blank(64, 48)
        assert l.size == (64, 48)

    def test_blank_custom_name(self):
        from slappyengine.layer import Layer
        l = Layer.blank(16, 16, name="MyLayer")
        assert l.name == "MyLayer"

    def test_blank_default_name(self):
        from slappyengine.layer import Layer
        l = Layer.blank(16, 16)
        assert l.name == "Layer"


class TestLayerMutability:
    def test_blend_mode_mutable(self):
        from slappyengine.layer import Layer
        l = Layer()
        l.blend_mode = "multiply"
        assert l.blend_mode == "multiply"

    def test_visible_mutable(self):
        from slappyengine.layer import Layer
        l = Layer()
        l.visible = False
        assert l.visible is False

    def test_opacity_mutable(self):
        from slappyengine.layer import Layer
        l = Layer()
        l.opacity = 0.5
        assert l.opacity == pytest.approx(0.5)

    def test_image_data_mutable(self):
        from slappyengine.layer import Layer
        l = Layer.blank(4, 4)
        l._image_data[0, 0, 0] = 255
        assert l._image_data[0, 0, 0] == 255


class TestLayerScripts:
    def test_attach_script_no_crash(self):
        from slappyengine.layer import Layer

        class DummyScript:
            def on_tick(self, layer, dt): pass

        l = Layer.blank(8, 8)
        l.attach_script(DummyScript())

    def test_tick_calls_on_tick(self):
        from slappyengine.layer import Layer
        calls = []

        class TickScript:
            def on_tick(self, layer, dt): calls.append(dt)

        l = Layer.blank(8, 8)
        l.attach_script(TickScript())
        l.tick(0.016)
        assert calls == [pytest.approx(0.016)]

    def test_tick_no_scripts_no_crash(self):
        from slappyengine.layer import Layer
        l = Layer.blank(4, 4)
        l.tick(0.016)


# ---------------------------------------------------------------------------
# Layer2D
# ---------------------------------------------------------------------------

class TestLayer2DDefaults:
    def test_instantiates(self):
        from slappyengine.layer import Layer2D
        l = Layer2D()
        assert l is not None

    def test_mode_is_2d(self):
        from slappyengine.layer import Layer2D
        l = Layer2D()
        assert l.mode == "2D"

    def test_default_size_64(self):
        from slappyengine.layer import Layer2D
        l = Layer2D()
        assert l._image_data.shape == (64, 64, 4)

    def test_custom_size(self):
        from slappyengine.layer import Layer2D
        l = Layer2D(width=128, height=96)
        assert l._image_data.shape == (96, 128, 4)

    def test_image_data_dtype(self):
        from slappyengine.layer import Layer2D
        l = Layer2D()
        assert l._image_data.dtype == np.uint8

    def test_image_data_zeros(self):
        from slappyengine.layer import Layer2D
        l = Layer2D(width=16, height=16)
        assert np.all(l._image_data == 0)

    def test_size_property(self):
        from slappyengine.layer import Layer2D
        l = Layer2D(width=100, height=50)
        assert l.size == (100, 50)

    def test_custom_name(self):
        from slappyengine.layer import Layer2D
        l = Layer2D(name="Sprite")
        assert l.name == "Sprite"


class TestLayer2DBlank:
    def test_blank_returns_layer2d(self):
        from slappyengine.layer import Layer2D
        l = Layer2D.blank(32, 16)
        assert isinstance(l, Layer2D)

    def test_blank_size(self):
        from slappyengine.layer import Layer2D
        l = Layer2D.blank(64, 32)
        assert l.size == (64, 32)

    def test_blank_zeros(self):
        from slappyengine.layer import Layer2D
        l = Layer2D.blank(8, 8)
        assert np.all(l._image_data == 0)

    def test_blank_name(self):
        from slappyengine.layer import Layer2D
        l = Layer2D.blank(8, 8, name="bg")
        assert l.name == "bg"


class TestLayer2DPixelOps:
    def test_write_and_read_pixel(self):
        from slappyengine.layer import Layer2D
        l = Layer2D(width=16, height=16)
        l._image_data[5, 3, :] = [100, 150, 200, 255]
        assert list(l._image_data[5, 3, :]) == [100, 150, 200, 255]

    def test_alpha_channel_writable(self):
        from slappyengine.layer import Layer2D
        l = Layer2D(width=8, height=8)
        l._image_data[:, :, 3] = 128
        assert np.all(l._image_data[:, :, 3] == 128)


# ---------------------------------------------------------------------------
# Layer3D
# ---------------------------------------------------------------------------

class TestLayer3DDefaults:
    def test_instantiates(self):
        from slappyengine.layer import Layer3D
        l = Layer3D()
        assert l is not None

    def test_mode_is_3d(self):
        from slappyengine.layer import Layer3D
        l = Layer3D()
        assert l.mode == "3D"

    def test_lighting_mode_default_unlit(self):
        from slappyengine.layer import Layer3D
        l = Layer3D()
        assert l.lighting_mode == "unlit"

    def test_gbuffer_target_initially_none(self):
        from slappyengine.layer import Layer3D
        l = Layer3D()
        assert l.gbuffer_target is None

    def test_mesh_initially_none(self):
        from slappyengine.layer import Layer3D
        l = Layer3D()
        assert l.mesh is None

    def test_material_initially_none(self):
        from slappyengine.layer import Layer3D
        l = Layer3D()
        assert l.material is None

    def test_custom_name(self):
        from slappyengine.layer import Layer3D
        l = Layer3D(name="Terrain")
        assert l.name == "Terrain"


class TestLayer3DProperties:
    def test_lighting_mode_mutable(self):
        from slappyengine.layer import Layer3D
        l = Layer3D()
        l.lighting_mode = "self_3d"
        assert l.lighting_mode == "self_3d"

    def test_gbuffer_target_setter_updates_mode(self):
        from slappyengine.layer import Layer3D, Layer2D
        l3 = Layer3D()
        l2 = Layer2D(width=64, height=64)
        l3.gbuffer_target = l2
        assert l3.lighting_mode == "defer_2d"
        assert l3.gbuffer_target is l2

    def test_gbuffer_target_none_does_not_reset_mode(self):
        from slappyengine.layer import Layer3D, Layer2D
        l3 = Layer3D()
        l3.gbuffer_target = Layer2D(width=32, height=32)
        l3.gbuffer_target = None
        # Mode stays defer_2d — setter only updates when value is not None
        assert l3._gbuffer_target is None

    def test_bake_to_2d_non_3d_raises(self):
        from slappyengine.layer import Layer
        l = Layer.blank(32, 32)
        with pytest.raises(ValueError, match="3D"):
            l.bake_to_2d((32, 32))

    def test_bake_to_2d_headless_returns_blank(self):
        from slappyengine.layer import Layer3D
        l = Layer3D(name="Mesh")
        result = l.bake_to_2d((64, 64))
        assert result is not None
        assert result.size == (64, 64)

    def test_apply_heightmap_non_3d_raises(self):
        from slappyengine.layer import Layer, Layer2D
        l = Layer.blank(32, 32)
        hm = Layer2D.blank(32, 32)
        with pytest.raises(ValueError, match="3D"):
            l.apply_heightmap(hm)

    def test_apply_heightmap_no_mesh_no_crash(self):
        from slappyengine.layer import Layer3D, Layer2D
        l3 = Layer3D()
        hm = Layer2D.blank(32, 32)
        l3.apply_heightmap(hm)  # mesh_geometry is None — should not raise

    def test_apply_normal_map_non_3d_raises(self):
        from slappyengine.layer import Layer, Layer2D
        l = Layer.blank(32, 32)
        nm = Layer2D.blank(32, 32)
        with pytest.raises(ValueError, match="3D"):
            l.apply_normal_map(nm)

    def test_apply_albedo_non_3d_raises(self):
        from slappyengine.layer import Layer, Layer2D
        l = Layer.blank(32, 32)
        ab = Layer2D.blank(32, 32)
        with pytest.raises(ValueError, match="3D"):
            l.apply_albedo(ab)


# ---------------------------------------------------------------------------
# LayerDataBuffer
# ---------------------------------------------------------------------------

class TestLayerDataBuffer:
    def test_instantiates(self):
        from slappyengine.layer import LayerDataBuffer
        l = LayerDataBuffer(name="data", width=16, height=16,
                            struct_fields=["vel_x", "vel_y", "mass"])
        assert l is not None

    def test_struct_fields_stored(self):
        from slappyengine.layer import LayerDataBuffer
        fields = ["a", "b", "c"]
        l = LayerDataBuffer("buf", 8, 8, fields)
        assert l.struct_fields == fields

    def test_data_array_shape(self):
        from slappyengine.layer import LayerDataBuffer
        l = LayerDataBuffer("buf", 16, 8, ["x", "y", "z"])
        # (height, width, num_fields)
        assert l._data_array.shape == (8, 16, 3)

    def test_data_array_dtype_float32(self):
        from slappyengine.layer import LayerDataBuffer
        l = LayerDataBuffer("buf", 8, 8, ["f"])
        assert l._data_array.dtype == np.float32

    def test_data_array_zeros(self):
        from slappyengine.layer import LayerDataBuffer
        l = LayerDataBuffer("buf", 8, 8, ["a", "b"])
        assert np.all(l._data_array == 0.0)

    def test_set_and_get_field(self):
        from slappyengine.layer import LayerDataBuffer
        l = LayerDataBuffer("buf", 4, 4, ["vel_x", "vel_y"])
        vals = np.ones((4, 4), dtype=np.float32) * 3.14
        l.set_field("vel_x", vals)
        result = l.get_field("vel_x")
        assert np.allclose(result, vals)

    def test_get_field_does_not_affect_others(self):
        from slappyengine.layer import LayerDataBuffer
        l = LayerDataBuffer("buf", 4, 4, ["vel_x", "vel_y"])
        l.set_field("vel_x", np.ones((4, 4), dtype=np.float32))
        vy = l.get_field("vel_y")
        assert np.all(vy == 0.0)

    def test_is_layer2d_subclass(self):
        from slappyengine.layer import LayerDataBuffer, Layer2D
        l = LayerDataBuffer("buf", 8, 8, ["f"])
        assert isinstance(l, Layer2D)

    def test_image_data_present(self):
        from slappyengine.layer import LayerDataBuffer
        l = LayerDataBuffer("buf", 16, 16, ["r"])
        assert l._image_data is not None
        assert l._image_data.shape == (16, 16, 4)
