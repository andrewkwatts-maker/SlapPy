"""Regression tests for the DDD1 hybrid 2D+3D layer stack.

Covers:
* ``Layer2D`` / ``Layer3D`` instantiation with the DDD1 defaults.
* Backwards-compatible ``Layer(mode="2D")`` / ``Layer(mode="3D")`` API.
* ``Scene.add_layer`` + ``layers`` iteration sorted by ``z_order``.
* ``Layer.allocate_render_target`` idempotency + shape.
* ``Layer.get_view_for_sampling`` for cross-layer buffer sharing (DDD2 hook).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent.parent / "python")
)

from slappyengine.layer import Layer, Layer2D, Layer3D, Camera3D  # noqa: E402
from slappyengine.scene import Scene  # noqa: E402


# ---------------------------------------------------------------------------
# Test doubles — minimal wgpu-like device/texture stubs so tests do not need
# a real GPU.
# ---------------------------------------------------------------------------


class _MockTextureView:
    def __init__(self, texture):
        self.texture = texture


class _MockTexture:
    def __init__(self, size, format, usage, label=""):
        self.size = size
        self.format = format
        self.usage = usage
        self.label = label

    def create_view(self):
        return _MockTextureView(self)


class _MockDevice:
    def __init__(self):
        self.created: list[_MockTexture] = []

    def create_texture(self, size, format, usage, label=""):
        tex = _MockTexture(size=size, format=format, usage=usage, label=label)
        self.created.append(tex)
        return tex


# ---------------------------------------------------------------------------
# Layer2D / Layer3D instantiation
# ---------------------------------------------------------------------------


def test_layer2d_default_mode_is_2d():
    layer = Layer2D()
    assert layer.mode == "2D"
    assert layer.z_order == 0
    assert layer.blend_mode == "normal"
    assert layer.visible is True
    assert layer.opacity == 1.0


def test_layer3d_default_mode_is_3d():
    layer = Layer3D()
    assert layer.mode == "3D"
    assert isinstance(layer.camera_3d, Camera3D)
    assert layer.bodies == []
    assert layer.z_order == 0


def test_layer2d_has_orthographic_camera():
    layer = Layer2D(name="l2d", width=128, height=64)
    assert layer.camera is not None
    assert layer.camera._viewport_size == (128, 64)


def test_layer3d_camera_3d_has_expected_fields():
    cam = Layer3D().camera_3d
    assert cam.fov_deg == 60.0
    assert cam.near == 0.1
    assert cam.far == 1000.0


# ---------------------------------------------------------------------------
# Backwards-compatibility — Layer(mode="2D") / Layer(mode="3D") still work
# ---------------------------------------------------------------------------


def test_base_layer_mode_2d_backcompat():
    layer = Layer(name="L", mode="2D")
    assert layer.mode == "2D"
    assert layer.z_order == 0
    assert layer.blend_mode == "normal"


def test_base_layer_mode_3d_backcompat():
    layer = Layer(name="L3", mode="3D")
    assert layer.mode == "3D"


def test_layer_blank_backcompat():
    layer = Layer.blank(32, 24, name="bl")
    assert layer.mode == "2D"
    assert layer.size == (32, 24)


def test_layer_rejects_bad_blend_mode():
    with pytest.raises(ValueError, match="blend_mode must be one of"):
        Layer(name="L", mode="2D", blend_mode="silly")


# ---------------------------------------------------------------------------
# Scene.add_layer + layers iteration sorted by z_order
# ---------------------------------------------------------------------------


def test_scene_add_layer_and_iterate_by_z_order():
    scene = Scene()
    l0 = Layer2D(name="a")
    l1 = Layer3D(name="b", z_order=1)
    scene.add_layer(l0)
    scene.add_layer(l1)
    ordered = scene.layers
    assert ordered == [l0, l1]


def test_scene_layers_sort_ascending_z_order():
    scene = Scene()
    high = Layer3D(name="high", z_order=10)
    low = Layer2D(name="low", z_order=-5)
    mid = Layer2D(name="mid", z_order=0)
    scene.add_layer(high)
    scene.add_layer(low)
    scene.add_layer(mid)
    assert [l.name for l in scene.layers] == ["low", "mid", "high"]


def test_scene_layers_preserve_insertion_order_on_tie():
    scene = Scene()
    a = Layer2D(name="a", z_order=5)
    b = Layer2D(name="b", z_order=5)
    c = Layer2D(name="c", z_order=5)
    scene.add_layer(a)
    scene.add_layer(b)
    scene.add_layer(c)
    assert [l.name for l in scene.layers] == ["a", "b", "c"]


def test_scene_remove_layer():
    scene = Scene()
    l = Layer2D()
    scene.add_layer(l)
    scene.remove_layer(l)
    assert scene.layers == []


def test_scene_add_layer_rejects_non_layer():
    scene = Scene()
    with pytest.raises(TypeError, match="must be a Layer"):
        scene.add_layer("not a layer")


def test_scene_add_layer_ignores_duplicate():
    scene = Scene()
    l = Layer2D()
    scene.add_layer(l)
    scene.add_layer(l)
    assert scene.layers == [l]


# ---------------------------------------------------------------------------
# allocate_render_target + get_view_for_sampling
# ---------------------------------------------------------------------------


def test_allocate_render_target_creates_texture_for_2d():
    device = _MockDevice()
    layer = Layer2D(name="l", width=64, height=48)
    layer.allocate_render_target(device)
    assert layer.render_target is not None
    assert layer.render_target.size == (64, 48, 1)
    # 2D layers get no depth target
    assert layer.depth_target is None


def test_allocate_render_target_creates_depth_for_3d():
    device = _MockDevice()
    layer = Layer3D(name="l3", resolution=(320, 200))
    layer.allocate_render_target(device)
    assert layer.render_target is not None
    assert layer.render_target.size == (320, 200, 1)
    assert layer.depth_target is not None
    assert layer.depth_target.size == (320, 200, 1)


def test_allocate_render_target_is_idempotent():
    device = _MockDevice()
    layer = Layer2D(width=32, height=32)
    layer.allocate_render_target(device)
    first = layer.render_target
    layer.allocate_render_target(device)  # second call, same size
    assert layer.render_target is first


def test_allocate_render_target_recreates_on_resolution_change():
    device = _MockDevice()
    layer = Layer2D(width=32, height=32)
    layer.allocate_render_target(device)
    first = layer.render_target
    layer.resolution = (64, 64)
    layer.allocate_render_target(device)
    assert layer.render_target is not first
    assert layer.render_target.size == (64, 64, 1)


def test_get_view_for_sampling_returns_view_from_texture():
    device = _MockDevice()
    layer = Layer3D(resolution=(16, 16))
    layer.allocate_render_target(device)
    view = layer.get_view_for_sampling()
    assert view is not None
    assert isinstance(view, _MockTextureView)
    assert view.texture is layer.render_target


def test_get_view_for_sampling_none_before_allocation():
    layer = Layer2D()
    assert layer.get_view_for_sampling() is None


def test_allocate_render_target_none_device_noop():
    layer = Layer2D()
    layer.allocate_render_target(None)  # must not raise
    assert layer.render_target is None
