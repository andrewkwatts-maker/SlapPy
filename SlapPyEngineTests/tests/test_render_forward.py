"""Tests for slappyengine.render — HH4 forward renderer.

All tests use the NullRenderer path so no GPU is required.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from slappyengine.render import (
    Camera2D,
    Camera3D,
    DrawCall,
    Light,
    MAX_LIGHTS,
    Material,
    Mesh,
    MeshHandle,
    NullRenderer,
    Renderer,
    ShaderSource,
    STOCK_SHADERS,
    TextureHandle,
    Transform2D,
    Transform3D,
    cube,
    get_shader,
    is_unlit,
    is_wgpu_available,
    pack_lights_ubo,
    quad,
)
from slappyengine.render.shader_stock import (
    LINE_3D_WGSL,
    PHONG_3D_WGSL,
    SPRITE_2D_WGSL,
    UNLIT_3D_WGSL,
)


# ----------------------------------------------------------------------
# Mesh
# ----------------------------------------------------------------------
def test_mesh_from_arrays_shape_validation():
    v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    i = np.array([[0, 1, 2]], dtype=np.uint32)
    m = Mesh.from_arrays(v, i)
    assert m.vertices.shape == (3, 3)
    assert m.indices.shape == (1, 3)


def test_mesh_rejects_bad_vertex_shape():
    with pytest.raises(ValueError):
        Mesh(vertices=np.zeros((4, 2), dtype=np.float32), indices=np.zeros((1, 3), dtype=np.uint32))


def test_mesh_rejects_bad_index_shape():
    with pytest.raises(ValueError):
        Mesh(vertices=np.zeros((3, 3), dtype=np.float32), indices=np.zeros((1, 4), dtype=np.uint32))


def test_mesh_bounding_box_from_vertices():
    v = np.array([[-1, -2, -3], [4, 5, 6], [0, 0, 0]], dtype=np.float32)
    i = np.array([[0, 1, 2]], dtype=np.uint32)
    m = Mesh(vertices=v, indices=i)
    assert m.bounding_box[0] == pytest.approx((-1, -2, -3))
    assert m.bounding_box[1] == pytest.approx((4, 5, 6))


def test_mesh_normal_shape_mismatch():
    v = np.zeros((3, 3), dtype=np.float32)
    i = np.array([[0, 1, 2]], dtype=np.uint32)
    with pytest.raises(ValueError):
        Mesh(vertices=v, indices=i, normals=np.zeros((2, 3), dtype=np.float32))


def test_mesh_uv_validation():
    v = np.zeros((3, 3), dtype=np.float32)
    i = np.array([[0, 1, 2]], dtype=np.uint32)
    with pytest.raises(ValueError):
        Mesh(vertices=v, indices=i, uvs=np.zeros((3, 3), dtype=np.float32))


def test_mesh_compute_normals_returns_unit_length():
    m = cube()
    n = m.compute_normals()
    assert n.shape == m.vertices.shape
    lens = np.linalg.norm(n, axis=1)
    assert np.allclose(lens, 1.0, atol=1e-5)


def test_cube_primitive_topology():
    c = cube(2.0)
    assert c.vertices.shape == (8, 3)
    assert c.indices.shape == (12, 3)
    assert c.triangle_count() == 12


def test_quad_primitive_has_uvs():
    q = quad()
    assert q.vertices.shape == (4, 3)
    assert q.uvs is not None
    assert q.uvs.shape == (4, 2)


def test_mesh_upload_returns_handle():
    r = NullRenderer()
    h = cube().upload_to_gpu(r)
    assert isinstance(h, MeshHandle)
    assert h.vertex_count == 8
    assert h.index_count == 12


# ----------------------------------------------------------------------
# Material
# ----------------------------------------------------------------------
def test_material_defaults():
    m = Material()
    assert m.base_color == (1.0, 1.0, 1.0, 1.0)
    assert m.alpha_mode == "opaque"
    assert m.alpha_cutoff == 0.5
    assert m.metallic == 0.0
    assert m.roughness == 0.5


def test_material_invalid_alpha_mode():
    with pytest.raises(ValueError):
        Material(alpha_mode="hologram")


def test_material_metallic_range_enforced():
    with pytest.raises(ValueError):
        Material(metallic=1.5)


def test_material_roughness_range_enforced():
    with pytest.raises(ValueError):
        Material(roughness=-0.1)


def test_material_uniform_bytes_length():
    m = Material()
    b = m.uniform_bytes()
    assert len(b) == 48  # 12 floats × 4 bytes


def test_material_emit_wgsl_contains_struct():
    m = Material()
    src = m.emit_wgsl()
    assert "struct MaterialUBO" in src
    assert "base_color" in src


# ----------------------------------------------------------------------
# Camera3D
# ----------------------------------------------------------------------
def test_camera3d_identity_view_when_looking_down_neg_z():
    cam = Camera3D(position=(0, 0, 5), look_at=(0, 0, 0), up=(0, 1, 0))
    v = cam.view_matrix()
    # Camera at +5z looking at origin: view translates by (0, 0, -5).
    expected = np.eye(4, dtype=np.float32)
    expected[2, 3] = -5.0
    assert np.allclose(v, expected, atol=1e-5)


def test_camera3d_projection_matrix_shape_and_finite():
    cam = Camera3D(fov_degrees=60, near=0.1, far=100.0, aspect=1.5)
    p = cam.projection_matrix()
    assert p.shape == (4, 4)
    assert np.all(np.isfinite(p))
    assert p[3, 2] == -1.0  # perspective divide entry


def test_camera3d_view_projection_composes():
    cam = Camera3D()
    vp = cam.view_projection()
    assert vp.shape == (4, 4)


def test_camera3d_projection_maps_near_to_zero_depth():
    cam = Camera3D(near=1.0, far=100.0)
    p = cam.projection_matrix()
    v = np.array([0.0, 0.0, -1.0, 1.0], dtype=np.float32)  # point at near plane
    clip = p @ v
    ndc_z = clip[2] / clip[3]
    assert ndc_z == pytest.approx(0.0, abs=1e-4)


def test_camera3d_projection_maps_far_to_one_depth():
    cam = Camera3D(near=1.0, far=100.0)
    p = cam.projection_matrix()
    v = np.array([0.0, 0.0, -100.0, 1.0], dtype=np.float32)
    clip = p @ v
    ndc_z = clip[2] / clip[3]
    assert ndc_z == pytest.approx(1.0, abs=1e-4)


# ----------------------------------------------------------------------
# Camera2D
# ----------------------------------------------------------------------
def test_camera2d_ortho_view_translates_only():
    cam = Camera2D(position=(3, 4), zoom=1.0, viewport_size=(100, 100))
    v = cam.view_matrix()
    assert v[0, 3] == -3.0
    assert v[1, 3] == -4.0


def test_camera2d_projection_scales_by_viewport():
    cam = Camera2D(position=(0, 0), zoom=1.0, viewport_size=(100, 200))
    p = cam.projection_matrix()
    # Point at half viewport should hit NDC ±1.
    v = np.array([50.0, 100.0, 0.0, 1.0], dtype=np.float32)
    clip = p @ v
    assert clip[0] == pytest.approx(1.0)
    assert clip[1] == pytest.approx(1.0)


def test_camera2d_zoom_shrinks_view_extent():
    cam = Camera2D(viewport_size=(100, 100), zoom=2.0)
    p = cam.projection_matrix()
    # At zoom=2, half-extent is 25 → point (25,25) maps to NDC (1,1).
    v = np.array([25.0, 25.0, 0.0, 1.0], dtype=np.float32)
    clip = p @ v
    assert clip[0] == pytest.approx(1.0)


# ----------------------------------------------------------------------
# Transform3D
# ----------------------------------------------------------------------
def test_transform3d_identity_matrix():
    t = Transform3D()
    m = t.matrix()
    assert np.allclose(m, np.eye(4), atol=1e-6)


def test_transform3d_translate_then_matrix():
    t = Transform3D().translate(1, 2, 3)
    m = t.matrix()
    assert m[0, 3] == pytest.approx(1.0)
    assert m[1, 3] == pytest.approx(2.0)
    assert m[2, 3] == pytest.approx(3.0)


def test_transform3d_rotate_z_90_deg():
    t = Transform3D().rotate_z(math.pi / 2.0)
    m = t.matrix()
    # X axis maps to +Y.
    p = m @ np.array([1.0, 0.0, 0.0, 1.0], dtype=np.float32)
    assert p[0] == pytest.approx(0.0, abs=1e-5)
    assert p[1] == pytest.approx(1.0, abs=1e-5)


def test_transform3d_scale_by():
    t = Transform3D().scale_by(2, 3, 4)
    m = t.matrix()
    assert m[0, 0] == pytest.approx(2.0)
    assert m[1, 1] == pytest.approx(3.0)
    assert m[2, 2] == pytest.approx(4.0)


def test_transform3d_compose_translate_and_rotate():
    t = Transform3D().rotate_z(math.pi / 2.0).translate(5, 0, 0)
    m = t.matrix()
    p = m @ np.array([1.0, 0.0, 0.0, 1.0], dtype=np.float32)
    # Rotate x-axis → +y, then translation shifts x by +5.
    assert p[0] == pytest.approx(5.0, abs=1e-5)
    assert p[1] == pytest.approx(1.0, abs=1e-5)


def test_transform2d_matrix_shape():
    t = Transform2D(position=(1, 2), rotation=math.pi / 4, scale=(2, 2))
    m = t.matrix()
    assert m.shape == (3, 3)
    assert m[0, 2] == pytest.approx(1.0)
    assert m[1, 2] == pytest.approx(2.0)


# ----------------------------------------------------------------------
# NullRenderer / draw log
# ----------------------------------------------------------------------
def test_null_renderer_lifecycle_records_frame():
    r = NullRenderer()
    r.begin_frame()
    r.end_frame()
    assert r.frame_count == 1
    assert r.calls_of("clear")
    assert r.calls_of("present")


def test_null_renderer_records_mesh_call():
    r = NullRenderer()
    r.begin_frame()
    r.submit_mesh(cube(), np.eye(4, dtype=np.float32), Material(name="brick"))
    r.end_frame()
    mesh_calls = r.calls_of("mesh")
    assert len(mesh_calls) == 1
    assert mesh_calls[0].payload["material_name"] == "brick"
    assert mesh_calls[0].payload["triangle_count"] == 12


def test_null_renderer_records_sprite_call():
    r = NullRenderer()
    tex = TextureHandle(id=1, width=64, height=64)
    r.begin_frame()
    r.submit_sprite(tex, np.eye(3, dtype=np.float32), tint=(1, 0, 0, 1))
    r.end_frame()
    sprites = r.calls_of("sprite")
    assert len(sprites) == 1
    assert sprites[0].payload["texture_id"] == 1
    assert sprites[0].payload["tint"] == (1.0, 0.0, 0.0, 1.0)


def test_null_renderer_records_camera_call():
    r = NullRenderer()
    cam = Camera3D()
    r.set_camera(cam.view_matrix(), cam.projection_matrix())
    calls = r.calls_of("camera")
    assert len(calls) == 1
    assert calls[0].payload["view"].shape == (4, 4)
    assert calls[0].payload["proj"].shape == (4, 4)


def test_null_renderer_records_lights_call():
    r = NullRenderer()
    lights = [Light(kind="directional"), Light(kind="ambient", intensity=0.2)]
    r.set_lights(lights)
    calls = r.calls_of("lights")
    assert len(calls) == 1
    assert calls[0].payload["count"] == 2


def test_null_renderer_submit_outside_frame_raises():
    r = NullRenderer()
    with pytest.raises(RuntimeError):
        r.submit_mesh(cube(), np.eye(4), Material())


def test_null_renderer_double_begin_raises():
    r = NullRenderer()
    r.begin_frame()
    with pytest.raises(RuntimeError):
        r.begin_frame()


def test_null_renderer_end_without_begin_raises():
    r = NullRenderer()
    with pytest.raises(RuntimeError):
        r.end_frame()


def test_null_renderer_read_pixels_returns_ndarray():
    r = NullRenderer(window_size=(4, 3), clear_color=(1, 0, 0, 1))
    px = r.read_pixels()
    assert isinstance(px, np.ndarray)
    assert px.shape == (3, 4, 4)
    assert px[0, 0, 0] == 255
    assert px[0, 0, 1] == 0


def test_null_renderer_offscreen_resizes():
    r = NullRenderer()
    r.create_offscreen(200, 100)
    assert r.window_size == (200, 100)
    assert r.calls_of("offscreen")


def test_null_renderer_clear_log():
    r = NullRenderer()
    r.begin_frame()
    r.end_frame()
    assert r.draw_log
    r.clear_log()
    assert r.draw_log == []


# ----------------------------------------------------------------------
# Lights UBO
# ----------------------------------------------------------------------
def test_pack_lights_ubo_size_matches_layout():
    ubo = pack_lights_ubo([])
    assert ubo.dtype == np.float32
    assert ubo.shape == (MAX_LIGHTS * 16 + 4,)


def test_pack_lights_ubo_encodes_directional_light():
    ubo = pack_lights_ubo([Light(kind="directional", direction=(0, -1, 0), color=(1, 1, 1), intensity=2.0)])
    # Slot 0 direction should be normalised to (0, -1, 0).
    assert ubo[4] == pytest.approx(0.0)
    assert ubo[5] == pytest.approx(-1.0)
    assert ubo[6] == pytest.approx(0.0)
    # Slot 0 intensity.
    assert ubo[11] == pytest.approx(2.0)
    # Enabled flag.
    assert ubo[13] == pytest.approx(1.0)


def test_pack_lights_ubo_ambient_goes_to_tail():
    ubo = pack_lights_ubo([Light(kind="ambient", color=(0.2, 0.3, 0.4), intensity=0.5)])
    tail = ubo[MAX_LIGHTS * 16:]
    assert tail[0] == pytest.approx(0.2 * 0.5)
    assert tail[3] == pytest.approx(0.5)


def test_is_unlit_true_when_only_ambient():
    assert is_unlit([Light(kind="ambient")])
    assert is_unlit([])
    assert not is_unlit([Light(kind="directional")])


def test_light_rejects_bad_kind():
    with pytest.raises(ValueError):
        Light(kind="fluorescent")


def test_pack_lights_ubo_caps_at_max_lights():
    lights = [Light(kind="point") for _ in range(MAX_LIGHTS + 3)]
    ubo = pack_lights_ubo(lights)
    # All 4 slots enabled, extras discarded.
    for slot in range(MAX_LIGHTS):
        assert ubo[slot * 16 + 13] == 1.0


# ----------------------------------------------------------------------
# Shader stock
# ----------------------------------------------------------------------
def test_stock_shaders_registered():
    # KK2 added "depth_only" for the DepthPrepass; base 4 shaders remain.
    assert {"unlit_3d", "phong_3d", "sprite_2d", "line_3d"} <= set(STOCK_SHADERS)


def test_unlit_shader_has_entry_points():
    src = UNLIT_3D_WGSL
    assert "vs_main" in src
    assert "fs_main" in src


def test_phong_shader_has_four_light_loop():
    assert "array<LightSlot, 4>" in PHONG_3D_WGSL


def test_sprite_shader_samples_texture():
    assert "textureSample" in SPRITE_2D_WGSL


def test_line_shader_passes_color():
    assert "in.color" in LINE_3D_WGSL


def test_get_shader_returns_source():
    s = get_shader("unlit_3d")
    assert isinstance(s, ShaderSource)
    assert s.entry_vs == "vs_main"
    assert s.byte_size > 100


def test_get_shader_unknown_raises():
    with pytest.raises(KeyError):
        get_shader("does_not_exist")


# ----------------------------------------------------------------------
# Public Renderer (force null path so tests are deterministic)
# ----------------------------------------------------------------------
def test_renderer_begin_end_lifecycle():
    r = Renderer(force_null=True)
    r.begin_frame()
    r.end_frame()
    assert r.frame_count == 1


def test_renderer_full_frame_records_mesh_camera_light():
    r = Renderer(force_null=True, window_size=(64, 48))
    cam = Camera3D()
    r.set_camera(cam.view_matrix(), cam.projection_matrix())
    r.set_lights([Light(kind="directional")])
    r.begin_frame()
    r.submit_mesh(cube(), Transform3D().matrix(), Material())
    r.end_frame()
    assert r.calls_of("mesh")
    assert r.calls_of("camera")
    assert r.calls_of("lights")


def test_renderer_read_pixels_returns_ndarray():
    r = Renderer(force_null=True, window_size=(8, 6), clear_color=(0, 1, 0, 1))
    img = r.read_pixels()
    assert img.shape == (6, 8, 4)
    assert img[0, 0, 1] == 255


def test_renderer_force_null_flag_reports_backend():
    r = Renderer(force_null=True)
    assert r.is_null
    assert r.backend == "null"


def test_is_wgpu_available_boolean():
    assert isinstance(is_wgpu_available(), bool)


def test_renderer_offscreen_updates_window_size():
    r = Renderer(force_null=True)
    r.create_offscreen(320, 240)
    assert r.window_size == (320, 240)


def test_renderer_light_ubo_helper():
    r = Renderer(force_null=True)
    ubo = r.light_ubo([Light(kind="directional")])
    assert ubo.shape == (MAX_LIGHTS * 16 + 4,)
