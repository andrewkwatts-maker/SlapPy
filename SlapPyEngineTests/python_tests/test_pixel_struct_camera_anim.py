"""Engine tests for pixel_struct.py, struct_registry.py, camera.py,
and animation/graph.py + animation/procedural.py.
All headless — no GPU required.
"""
from __future__ import annotations
import math
import pytest
import numpy as np


# ---------------------------------------------------------------------------
# pixel_struct.py — PixelStruct, FieldDef, DTYPE_TO_CHANNELS
# ---------------------------------------------------------------------------

class TestPixelStructBasics:
    def test_instantiates(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"albedo": "vec4", "roughness": "f32"})
        assert ps is not None

    def test_total_channels(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"albedo": "vec4", "roughness": "f32", "puddle": "f32"})
        assert ps.total_channels == 6  # 4 + 1 + 1

    def test_field_names(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"a": "f32", "b": "vec2"})
        assert ps.field_names == ["a", "b"]

    def test_unknown_dtype_raises(self):
        from pharos_engine.pixel_struct import PixelStruct
        with pytest.raises(ValueError):
            PixelStruct({"x": "badtype"})

    def test_empty_array_shape(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"a": "f32", "b": "vec2"})  # 3 channels
        arr = ps.empty_array(10, 20)
        assert arr.shape == (10, 20, 3)
        assert arr.dtype == np.float32

    def test_empty_array_zeros(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"x": "f32"})
        arr = ps.empty_array(4, 4)
        assert np.all(arr == 0)

    def test_dtype_constants(self):
        from pharos_engine.pixel_struct import DTYPE_TO_CHANNELS
        assert DTYPE_TO_CHANNELS["f32"] == 1
        assert DTYPE_TO_CHANNELS["vec2"] == 2
        assert DTYPE_TO_CHANNELS["vec3"] == 3
        assert DTYPE_TO_CHANNELS["vec4"] == 4
        assert DTYPE_TO_CHANNELS["u32"] == 1

    def test_repr(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"a": "f32"})
        r = repr(ps)
        assert "a" in r
        assert "f32" in r


class TestPixelStructReadWrite:
    def _make_struct_and_array(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"albedo": "vec4", "roughness": "f32", "puddle": "f32"})
        arr = ps.empty_array(8, 8)
        return ps, arr

    def test_write_and_read_scalar(self):
        ps, arr = self._make_struct_and_array()
        ps.write_pixel(arr, 3, 4, {"roughness": 0.7})
        result = ps.read_pixel(arr, 3, 4)
        assert result["roughness"] == pytest.approx(0.7)

    def test_write_and_read_vec4(self):
        ps, arr = self._make_struct_and_array()
        ps.write_pixel(arr, 2, 2, {"albedo": (0.1, 0.2, 0.3, 1.0)})
        result = ps.read_pixel(arr, 2, 2)
        assert result["albedo"] == pytest.approx((0.1, 0.2, 0.3, 1.0))

    def test_unknown_field_write_ignored(self):
        ps, arr = self._make_struct_and_array()
        ps.write_pixel(arr, 0, 0, {"nonexistent_field": 99.0})
        # Should not raise

    def test_read_defaults_to_zero(self):
        ps, arr = self._make_struct_and_array()
        result = ps.read_pixel(arr, 0, 0)
        assert result["roughness"] == pytest.approx(0.0)
        assert result["puddle"] == pytest.approx(0.0)

    def test_multiple_fields_independent(self):
        ps, arr = self._make_struct_and_array()
        ps.write_pixel(arr, 0, 0, {"roughness": 0.5, "puddle": 0.8})
        result = ps.read_pixel(arr, 0, 0)
        assert result["roughness"] == pytest.approx(0.5)
        assert result["puddle"] == pytest.approx(0.8)


class TestPixelStructWgslAndSlice:
    def test_wgsl_struct_contains_field_names(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"albedo": "vec4", "roughness": "f32"})
        wgsl = ps.to_wgsl_struct("TrackPixel")
        assert "TrackPixel" in wgsl
        assert "albedo" in wgsl
        assert "roughness" in wgsl

    def test_wgsl_struct_custom_name(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"x": "f32"})
        wgsl = ps.to_wgsl_struct("MyStruct")
        assert "struct MyStruct" in wgsl

    def test_slice_field_scalar(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"a": "f32", "b": "f32"})
        arr = ps.empty_array(4, 4)
        arr[:, :, 0] = 9.0  # field "a"
        sl = ps.slice_field(arr, "a")
        assert sl.shape == (4, 4)
        assert sl[0, 0] == pytest.approx(9.0)

    def test_slice_field_vec(self):
        from pharos_engine.pixel_struct import PixelStruct
        ps = PixelStruct({"color": "vec4"})
        arr = ps.empty_array(2, 2)
        arr[0, 0, :] = [1, 2, 3, 4]
        sl = ps.slice_field(arr, "color")
        assert sl.shape == (2, 2, 4)


# ---------------------------------------------------------------------------
# struct_registry.py — StructModule, StructRegistry
# ---------------------------------------------------------------------------

class TestStructRegistry:
    def test_instantiates(self):
        from pharos_engine.struct_registry import StructRegistry
        r = StructRegistry()
        assert r is not None

    def test_default_color_channel(self):
        from pharos_engine.struct_registry import StructRegistry
        r = StructRegistry()
        names = [n for n, _ in r.channels]
        assert "color" in names

    def test_register_module(self):
        from pharos_engine.struct_registry import StructRegistry, StructModule
        r = StructRegistry()

        class HealthMod(StructModule):
            name = "health"
            channels = [("hp", "f32")]
            compute_passes = []
            default_values = {"hp": 1.0}

        r.register(HealthMod)
        names = [n for n, _ in r.channels]
        assert "hp" in names

    def test_register_duplicate_channel_raises(self):
        from pharos_engine.struct_registry import StructRegistry, StructModule
        r = StructRegistry()

        class ModA(StructModule):
            name = "a"
            channels = [("shared", "f32")]

        class ModB(StructModule):
            name = "b"
            channels = [("shared", "f32")]

        r.register(ModA)
        with pytest.raises(ValueError):
            r.register(ModB)

    def test_lock_prevents_register(self):
        from pharos_engine.struct_registry import StructRegistry, StructModule
        r = StructRegistry()
        r.lock()

        class MyMod(StructModule):
            name = "m"
            channels = [("x", "f32")]

        with pytest.raises(RuntimeError):
            r.register(MyMod)

    def test_channel_offset_computed(self):
        from pharos_engine.struct_registry import StructRegistry
        r = StructRegistry()
        offset = r.channel_offset("color")
        assert isinstance(offset, int)
        assert offset >= 0

    def test_stride_bytes_positive(self):
        from pharos_engine.struct_registry import StructRegistry
        r = StructRegistry()
        stride = r.stride_bytes()
        assert isinstance(stride, int)
        assert stride > 0

    def test_stride_divisible_by_16(self):
        from pharos_engine.struct_registry import StructRegistry
        r = StructRegistry()
        stride = r.stride_bytes()
        assert stride % 16 == 0

    def test_default_for_channel(self):
        from pharos_engine.struct_registry import StructRegistry, StructModule
        r = StructRegistry()

        class MyMod(StructModule):
            name = "m"
            channels = [("fuel", "f32")]
            compute_passes = []
            default_values = {"fuel": 0.75}

        r.register(MyMod)
        assert r.default_for_channel("fuel") == pytest.approx(0.75)

    def test_default_for_unknown_channel_zero(self):
        from pharos_engine.struct_registry import StructRegistry
        r = StructRegistry()
        assert r.default_for_channel("nonexistent") == pytest.approx(0.0)

    def test_required_compute_passes(self):
        from pharos_engine.struct_registry import StructRegistry, StructModule
        r = StructRegistry()

        class MyMod(StructModule):
            name = "m"
            channels = [("x", "f32")]
            compute_passes = ["my_shader.wgsl"]
            default_values = {}

        r.register(MyMod)
        passes = r.required_compute_passes()
        assert "my_shader.wgsl" in passes

    def test_no_duplicate_compute_passes(self):
        from pharos_engine.struct_registry import StructRegistry, StructModule
        r = StructRegistry()

        class ModA(StructModule):
            name = "a"
            channels = [("ax", "f32")]
            compute_passes = ["shared.wgsl"]
            default_values = {}

        class ModB(StructModule):
            name = "b"
            channels = [("bx", "f32")]
            compute_passes = ["shared.wgsl"]
            default_values = {}

        r.register(ModA)
        r.register(ModB)
        passes = r.required_compute_passes()
        assert passes.count("shared.wgsl") == 1


# ---------------------------------------------------------------------------
# camera.py — Camera
# ---------------------------------------------------------------------------

class TestCameraDefaults:
    def test_instantiates(self):
        from pharos_engine.camera import Camera
        c = Camera()
        assert c is not None

    def test_default_position(self):
        from pharos_engine.camera import Camera
        c = Camera()
        assert c.position == (0.0, 0.0)

    def test_default_zoom(self):
        from pharos_engine.camera import Camera
        c = Camera()
        assert c.zoom == pytest.approx(1.0)

    def test_default_rotation(self):
        from pharos_engine.camera import Camera
        c = Camera()
        assert c.rotation == pytest.approx(0.0)

    def test_custom_values(self):
        from pharos_engine.camera import Camera
        c = Camera(position=(100.0, 200.0), zoom=2.0, rotation=0.5)
        assert c.position == (100.0, 200.0)
        assert c.zoom == pytest.approx(2.0)
        assert c.rotation == pytest.approx(0.5)


class TestCameraWorldToScreen:
    def test_origin_at_center(self):
        from pharos_engine.camera import Camera
        c = Camera()
        c._viewport_size = (800, 600)
        sx, sy = c.world_to_screen((0.0, 0.0))
        assert sx == pytest.approx(400.0)
        assert sy == pytest.approx(300.0)

    def test_camera_offset(self):
        from pharos_engine.camera import Camera
        c = Camera(position=(100.0, 0.0))
        c._viewport_size = (800, 600)
        sx, sy = c.world_to_screen((100.0, 0.0))
        assert sx == pytest.approx(400.0)  # centred

    def test_zoom_scales(self):
        from pharos_engine.camera import Camera
        c = Camera(zoom=2.0)
        c._viewport_size = (800, 600)
        sx, sy = c.world_to_screen((10.0, 0.0))
        sx0, _ = c.world_to_screen((0.0, 0.0))
        assert (sx - sx0) == pytest.approx(20.0)  # 10 * zoom=2

    def test_returns_float_pair(self):
        from pharos_engine.camera import Camera
        c = Camera()
        result = c.world_to_screen((5.0, 5.0))
        assert len(result) == 2
        assert isinstance(result[0], float)


class TestCameraScreenToWorld:
    def test_center_maps_to_camera_position(self):
        from pharos_engine.camera import Camera
        c = Camera(position=(50.0, 30.0))
        c._viewport_size = (800, 600)
        wx, wy = c.screen_to_world((400.0, 300.0))
        assert wx == pytest.approx(50.0)
        assert wy == pytest.approx(30.0)

    def test_roundtrip(self):
        from pharos_engine.camera import Camera
        c = Camera(position=(200.0, 100.0), zoom=1.5)
        c._viewport_size = (800, 600)
        world_in = (350.0, 220.0)
        screen = c.world_to_screen(world_in)
        world_out = c.screen_to_world(screen)
        assert world_out[0] == pytest.approx(world_in[0], rel=1e-5)
        assert world_out[1] == pytest.approx(world_in[1], rel=1e-5)


class TestCameraVisibleRect:
    def test_returns_four_values(self):
        from pharos_engine.camera import Camera
        c = Camera()
        c._viewport_size = (800, 600)
        rect = c.visible_rect()
        assert len(rect) == 4

    def test_centered_on_camera_position(self):
        from pharos_engine.camera import Camera
        c = Camera(position=(0.0, 0.0))
        c._viewport_size = (800, 600)
        left, top, right, bottom = c.visible_rect()
        assert (left + right) / 2 == pytest.approx(0.0)
        assert (top + bottom) / 2 == pytest.approx(0.0)

    def test_zoom_shrinks_rect(self):
        from pharos_engine.camera import Camera
        c1 = Camera(zoom=1.0)
        c2 = Camera(zoom=2.0)
        c1._viewport_size = c2._viewport_size = (800, 600)
        l1, t1, r1, b1 = c1.visible_rect()
        l2, t2, r2, b2 = c2.visible_rect()
        assert (r2 - l2) < (r1 - l1)  # zoomed in → smaller world rect


class TestCameraFollow:
    def test_follow_snaps_at_lerp_one(self):
        from pharos_engine.camera import Camera

        class FakeEntity:
            position = (200.0, 150.0)

        c = Camera()
        c._viewport_size = (800, 600)
        c.follow(FakeEntity(), lerp=1.0)
        assert c.position == (200.0 - 400.0, 150.0 - 300.0)

    def test_follow_lerps_at_partial(self):
        from pharos_engine.camera import Camera

        class FakeEntity:
            position = (400.0, 300.0)

        c = Camera(position=(0.0, 0.0))
        c._viewport_size = (800, 600)
        c.follow(FakeEntity(), lerp=0.5)
        # target = (400-400, 300-300) = (0, 0); lerp from (0,0) → stays (0,0)
        assert c.position == pytest.approx((0.0, 0.0))


class TestCameraViewMatrix:
    def test_returns_list_of_16(self):
        from pharos_engine.camera import Camera
        c = Camera()
        m = c.view_matrix()
        assert len(m) == 16

    def test_identity_at_origin_zero_rotation(self):
        from pharos_engine.camera import Camera
        c = Camera()
        c._viewport_size = (800, 600)
        m = c.view_matrix()
        # All values should be finite
        for v in m:
            assert math.isfinite(v)


# ---------------------------------------------------------------------------
# animation/graph.py — AnimState, AnimTransition, AnimUpdate, AnimationGraph
# ---------------------------------------------------------------------------

class TestAnimState:
    def test_instantiates(self):
        from pharos_engine.animation.graph import AnimState
        s = AnimState(name="idle")
        assert s is not None

    def test_defaults(self):
        from pharos_engine.animation.graph import AnimState
        s = AnimState(name="run")
        assert s.clip_indices == []
        assert s.loop is True
        assert s.fps == pytest.approx(24.0)

    def test_custom_values(self):
        from pharos_engine.animation.graph import AnimState
        s = AnimState(name="jump", clip_indices=[0, 1, 2], loop=False, fps=12.0)
        assert s.name == "jump"
        assert s.clip_indices == [0, 1, 2]
        assert s.loop is False


class TestAnimTransition:
    def test_instantiates(self):
        from pharos_engine.animation.graph import AnimTransition
        t = AnimTransition(from_state="idle", to_state="run")
        assert t is not None

    def test_condition_false_by_default(self):
        from pharos_engine.animation.graph import AnimTransition
        t = AnimTransition(from_state="idle", to_state="run")
        assert t.condition() is False

    def test_custom_condition(self):
        from pharos_engine.animation.graph import AnimTransition
        t = AnimTransition(from_state="idle", to_state="run",
                           condition=lambda: True)
        assert t.condition() is True


class TestAnimUpdate:
    def test_instantiates(self):
        from pharos_engine.animation.graph import AnimUpdate
        u = AnimUpdate(state_name="run", frame_index=2, blend_fraction=0.5)
        assert u.state_name == "run"
        assert u.frame_index == 2
        assert u.blend_fraction == pytest.approx(0.5)


class TestAnimationGraph:
    def test_instantiates(self):
        from pharos_engine.animation.graph import AnimationGraph
        g = AnimationGraph()
        assert g is not None

    def test_no_state_update_returns_none(self):
        from pharos_engine.animation.graph import AnimationGraph
        g = AnimationGraph()
        result = g.update(0.016)
        assert result is None

    def test_add_state_and_set_initial(self):
        from pharos_engine.animation.graph import AnimationGraph, AnimState
        g = AnimationGraph()
        s = AnimState(name="idle", clip_indices=[0, 1, 2])
        g.add_state(s)
        g.set_initial("idle")
        assert g.current_state is s

    def test_update_returns_anim_update(self):
        from pharos_engine.animation.graph import AnimationGraph, AnimState, AnimUpdate
        g = AnimationGraph()
        g.add_state(AnimState(name="idle", clip_indices=[0, 1, 2]))
        g.set_initial("idle")
        result = g.update(0.016)
        assert isinstance(result, AnimUpdate)
        assert result.state_name == "idle"

    def test_frame_advances_over_time(self):
        from pharos_engine.animation.graph import AnimationGraph, AnimState
        g = AnimationGraph()
        g.add_state(AnimState(name="run", clip_indices=[0, 1, 2, 3], fps=10.0))
        g.set_initial("run")
        g.update(0.0)   # start
        g.update(0.15)  # 1.5 frames at 10fps → frame 1
        result = g.update(0.0)
        assert result is not None

    def test_transition_fires(self):
        from pharos_engine.animation.graph import AnimationGraph, AnimState, AnimTransition
        g = AnimationGraph()
        g.add_state(AnimState(name="idle", clip_indices=[0]))
        g.add_state(AnimState(name="run", clip_indices=[1, 2]))
        trigger = [True]
        g.add_transition(AnimTransition("idle", "run", condition=lambda: trigger[0]))
        g.set_initial("idle")
        g.update(0.016)
        assert g._current == "run"

    def test_loop_wraps_frames(self):
        from pharos_engine.animation.graph import AnimationGraph, AnimState
        g = AnimationGraph()
        g.add_state(AnimState(name="walk", clip_indices=[0, 1], fps=10.0, loop=True))
        g.set_initial("walk")
        for _ in range(50):
            g.update(0.02)  # total 1.0 second at 10fps = 10 frames → wraps on 2
        result = g.update(0.0)
        assert result is not None

    def test_non_loop_stops_at_last_frame(self):
        from pharos_engine.animation.graph import AnimationGraph, AnimState
        g = AnimationGraph()
        g.add_state(AnimState(name="die", clip_indices=[0, 1, 2], fps=10.0, loop=False))
        g.set_initial("die")
        for _ in range(100):
            g.update(0.05)
        result = g.update(0.0)
        assert result is not None
        assert result.frame_index == 2  # clamped at last


# ---------------------------------------------------------------------------
# animation/procedural.py — ControlPoint, ProceduralRig
# ---------------------------------------------------------------------------

class TestControlPoint:
    def test_instantiates(self):
        from pharos_engine.animation.procedural import ControlPoint
        cp = ControlPoint(name="elbow", uv=(0.5, 0.3))
        assert cp is not None

    def test_defaults(self):
        from pharos_engine.animation.procedural import ControlPoint
        cp = ControlPoint(name="knee", uv=(0.4, 0.8))
        assert cp.parent is None
        assert cp.constraint == "free"
        assert cp.min_angle == pytest.approx(-180.0)
        assert cp.max_angle == pytest.approx(180.0)


class TestProceduralRig:
    def test_instantiates(self):
        from pharos_engine.animation.procedural import ProceduralRig
        r = ProceduralRig()
        assert r is not None

    def test_add_point(self):
        from pharos_engine.animation.procedural import ProceduralRig, ControlPoint
        r = ProceduralRig()
        cp = ControlPoint(name="hip", uv=(0.5, 0.5))
        r.add_point(cp)
        assert "hip" in r._points

    def test_remove_point(self):
        from pharos_engine.animation.procedural import ProceduralRig, ControlPoint
        r = ProceduralRig()
        cp = ControlPoint(name="hip", uv=(0.5, 0.5))
        r.add_point(cp)
        r.remove_point("hip")
        assert "hip" not in r._points

    def test_remove_nonexistent_no_crash(self):
        from pharos_engine.animation.procedural import ProceduralRig
        r = ProceduralRig()
        r.remove_point("ghost")

    def test_get_chain_simple(self):
        from pharos_engine.animation.procedural import ProceduralRig, ControlPoint
        r = ProceduralRig()
        r.add_point(ControlPoint(name="hip", uv=(0.5, 0.9)))
        r.add_point(ControlPoint(name="knee", uv=(0.5, 0.7), parent="hip"))
        r.add_point(ControlPoint(name="ankle", uv=(0.5, 0.5), parent="knee"))
        chain = r.get_chain("hip", "ankle")
        names = [cp.name for cp in chain]
        assert names == ["hip", "knee", "ankle"]

    def test_solve_ik_no_crash(self):
        from pharos_engine.animation.procedural import ProceduralRig, ControlPoint
        r = ProceduralRig()
        r.add_point(ControlPoint(name="hip", uv=(0.5, 0.9)))
        r.add_point(ControlPoint(name="foot", uv=(0.5, 0.5), parent="hip"))
        result = r.solve_ik({"foot": (0.6, 0.4)})
        assert isinstance(result, dict)
