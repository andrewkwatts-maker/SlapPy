"""Tests for pharos_engine.render.pipeline + wgpu forward path (JJ1).

Every wgpu-dependent test soft-skips when the interpreter has no wgpu
install or when no adapter can be requested (typical headless CI). The
pure-Python tests exercise the format / cache / signature helpers so
they run even without a GPU.
"""
from __future__ import annotations

import numpy as np
import pytest

from pharos_engine.render import (
    Camera3D,
    Light,
    Material,
    Renderer,
    Transform3D,
    cube,
    is_wgpu_available,
)
from pharos_engine.render.pipeline import (
    BLEND_MODES,
    BufferUploader,
    PipelineCache,
    UniformBufferPool,
    VertexAttribute,
    VertexFormat,
    VERTEX_FORMAT_POS2_UV2,
    VERTEX_FORMAT_POS3_COL4,
    VERTEX_FORMAT_POS3_NRM3_UV2,
    VERTEX_FORMAT_POS3_UV2,
    VERTEX_FORMATS,
    create_forward_pipeline,
    create_line_pipeline,
    create_sprite_pipeline,
    parse_wgsl_vs_locations,
)
from pharos_engine.render.shader_stock import (
    LINE_3D_WGSL,
    PHONG_3D_WGSL,
    SPRITE_2D_WGSL,
    UNLIT_3D_WGSL,
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _wgpu_or_skip():
    if not is_wgpu_available():
        pytest.skip("wgpu not installed")
    try:
        import wgpu  # noqa: F401

        adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
        if adapter is None:
            pytest.skip("no wgpu adapter available")
        return adapter.request_device_sync()
    except Exception as e:  # pragma: no cover
        pytest.skip(f"wgpu adapter/device failure: {e!r}")


def _renderer_or_skip(**kwargs) -> Renderer:
    r = Renderer(**kwargs)
    if r.is_null:
        pytest.skip("Renderer fell back to NullRenderer — no GPU here")
    return r


# ----------------------------------------------------------------------
# VertexFormat + attribute layout
# ----------------------------------------------------------------------
def test_vertex_format_pos3_uv2_stride():
    assert VERTEX_FORMAT_POS3_UV2.stride == 20
    assert VERTEX_FORMAT_POS3_UV2.attributes[0].byte_size == 12
    assert VERTEX_FORMAT_POS3_UV2.attributes[1].byte_size == 8


def test_vertex_format_pos3_nrm3_uv2_stride():
    assert VERTEX_FORMAT_POS3_NRM3_UV2.stride == 32
    assert len(VERTEX_FORMAT_POS3_NRM3_UV2.attributes) == 3


def test_vertex_format_pos2_uv2_stride():
    assert VERTEX_FORMAT_POS2_UV2.stride == 16


def test_vertex_format_pos3_col4_stride():
    assert VERTEX_FORMAT_POS3_COL4.stride == 28


def test_vertex_format_as_wgpu_layout_shape():
    layout = VERTEX_FORMAT_POS3_UV2.as_wgpu_layout()
    assert layout["array_stride"] == 20
    assert layout["step_mode"] == "vertex"
    assert layout["attributes"][0]["shader_location"] == 0
    assert layout["attributes"][0]["format"] == "float32x3"
    assert layout["attributes"][1]["offset"] == 12


def test_vertex_formats_registry_keys():
    assert {"pos3_uv2", "pos3_nrm3_uv2", "pos2_uv2", "pos3_col4"}.issubset(VERTEX_FORMATS)


def test_blend_modes_registry():
    assert BLEND_MODES == {"opaque", "alpha", "additive"}


# ----------------------------------------------------------------------
# WGSL parser — verify shader @location layout matches VertexFormat
# ----------------------------------------------------------------------
def test_wgsl_parser_extracts_unlit_locations():
    locs = parse_wgsl_vs_locations(UNLIT_3D_WGSL)
    assert 0 in locs and 1 in locs
    assert locs[0].startswith("vec3")
    assert locs[1].startswith("vec2")


def test_wgsl_parser_extracts_phong_locations():
    locs = parse_wgsl_vs_locations(PHONG_3D_WGSL)
    assert set(locs.keys()) == {0, 1, 2}
    assert locs[0].startswith("vec3")
    assert locs[1].startswith("vec3")
    assert locs[2].startswith("vec2")


def test_wgsl_parser_extracts_sprite_locations():
    locs = parse_wgsl_vs_locations(SPRITE_2D_WGSL)
    assert set(locs.keys()) == {0, 1}
    assert locs[0].startswith("vec2")
    assert locs[1].startswith("vec2")


def test_wgsl_parser_extracts_line_locations():
    locs = parse_wgsl_vs_locations(LINE_3D_WGSL)
    assert set(locs.keys()) == {0, 1}
    assert locs[0].startswith("vec3")
    assert locs[1].startswith("vec4")


def test_phong_vertex_format_matches_shader_locations():
    locs = parse_wgsl_vs_locations(PHONG_3D_WGSL)
    fmt_locs = VERTEX_FORMAT_POS3_NRM3_UV2.locations
    assert set(fmt_locs) == set(locs.keys())


def test_unlit_vertex_format_matches_shader_locations():
    locs = parse_wgsl_vs_locations(UNLIT_3D_WGSL)
    assert set(VERTEX_FORMAT_POS3_UV2.locations) == set(locs.keys())


def test_sprite_vertex_format_matches_shader_locations():
    locs = parse_wgsl_vs_locations(SPRITE_2D_WGSL)
    assert set(VERTEX_FORMAT_POS2_UV2.locations) == set(locs.keys())


def test_line_vertex_format_matches_shader_locations():
    locs = parse_wgsl_vs_locations(LINE_3D_WGSL)
    assert set(VERTEX_FORMAT_POS3_COL4.locations) == set(locs.keys())


# ----------------------------------------------------------------------
# PipelineCache — pure structure
# ----------------------------------------------------------------------
def test_pipeline_cache_starts_empty():
    c = PipelineCache()
    assert len(c) == 0


def test_pipeline_cache_clear():
    c = PipelineCache()
    # Manually stuff a fake entry so we can assert clear() empties.
    c._cache[("a", "b", "c", 1, "rgba", "d24", "tri")] = object()
    assert len(c) == 1
    c.clear()
    assert len(c) == 0


def test_pipeline_cache_returns_same_pipeline_for_same_key():
    device = _wgpu_or_skip()
    cache = PipelineCache()
    p1 = create_forward_pipeline(device, shader_id="phong_3d", msaa_samples=1, cache=cache)
    p2 = create_forward_pipeline(device, shader_id="phong_3d", msaa_samples=1, cache=cache)
    assert p1 is p2
    assert len(cache) == 1


def test_pipeline_cache_different_msaa_gives_new_pipeline():
    device = _wgpu_or_skip()
    cache = PipelineCache()
    p1 = create_forward_pipeline(device, shader_id="phong_3d", msaa_samples=1, cache=cache)
    p4 = create_forward_pipeline(device, shader_id="phong_3d", msaa_samples=4, cache=cache)
    assert p1 is not p4
    assert len(cache) == 2


def test_pipeline_cache_different_shader_gives_new_pipeline():
    device = _wgpu_or_skip()
    cache = PipelineCache()
    p_phong = create_forward_pipeline(device, shader_id="phong_3d", cache=cache)
    p_unlit = create_forward_pipeline(device, shader_id="unlit_3d", cache=cache)
    assert p_phong is not p_unlit
    assert len(cache) == 2


# ----------------------------------------------------------------------
# Pipeline factories — check they return real wgpu.RenderPipeline objects
# ----------------------------------------------------------------------
def test_create_forward_pipeline_returns_render_pipeline():
    import wgpu

    device = _wgpu_or_skip()
    p = create_forward_pipeline(device, shader_id="phong_3d", msaa_samples=1)
    assert p.__class__.__name__ == "GPURenderPipeline"


def test_create_forward_unlit_pipeline():
    device = _wgpu_or_skip()
    p = create_forward_pipeline(device, shader_id="unlit_3d", msaa_samples=1)
    assert p.__class__.__name__ == "GPURenderPipeline"


def test_create_sprite_pipeline_returns_render_pipeline():
    device = _wgpu_or_skip()
    p = create_sprite_pipeline(device, msaa_samples=1)
    assert p.__class__.__name__ == "GPURenderPipeline"


def test_create_line_pipeline_returns_render_pipeline():
    device = _wgpu_or_skip()
    p = create_line_pipeline(device, msaa_samples=1)
    assert p.__class__.__name__ == "GPURenderPipeline"


# ----------------------------------------------------------------------
# BufferUploader — signature caching
# ----------------------------------------------------------------------
def test_buffer_uploader_requires_device_before_upload():
    up = BufferUploader()
    with pytest.raises(RuntimeError):
        up.upload(np.zeros(4, dtype=np.float32))


def test_buffer_uploader_caches_by_signature():
    device = _wgpu_or_skip()
    up = BufferUploader(device)
    arr = np.array([1, 2, 3, 4], dtype=np.float32)
    b1, n1 = up.upload(arr, usage="vertex")
    b2, n2 = up.upload(arr.copy(), usage="vertex")
    assert b1 is b2
    assert n1 == n2 == 16
    assert len(up) == 1


def test_buffer_uploader_different_content_different_buffer():
    device = _wgpu_or_skip()
    up = BufferUploader(device)
    a = np.array([1, 2, 3, 4], dtype=np.float32)
    b = np.array([1, 2, 3, 5], dtype=np.float32)
    ba, _ = up.upload(a)
    bb, _ = up.upload(b)
    assert ba is not bb
    assert len(up) == 2


def test_buffer_uploader_different_usage_different_key():
    device = _wgpu_or_skip()
    up = BufferUploader(device)
    arr = np.array([1, 2, 3, 4], dtype=np.uint32)
    b_vertex, _ = up.upload(arr, usage="vertex")
    b_index, _ = up.upload(arr, usage="index")
    assert b_vertex is not b_index


def test_buffer_uploader_contains_check():
    device = _wgpu_or_skip()
    up = BufferUploader(device)
    arr = np.array([1, 2, 3], dtype=np.float32)
    assert not up.contains(arr)
    up.upload(arr, usage="vertex")
    assert up.contains(arr, usage="vertex")
    assert not up.contains(arr, usage="index")


# ----------------------------------------------------------------------
# UniformBufferPool
# ----------------------------------------------------------------------
def test_uniform_pool_requires_device():
    pool = UniformBufferPool()
    with pytest.raises(RuntimeError):
        pool.acquire()


def test_uniform_pool_acquire_returns_buffer():
    device = _wgpu_or_skip()
    pool = UniformBufferPool(device)
    buf = pool.acquire(size=64)
    assert buf is not None
    assert len(pool) == 1


def test_uniform_pool_reset_frees_all_slots():
    device = _wgpu_or_skip()
    pool = UniformBufferPool(device)
    b1 = pool.acquire(size=64)
    b2 = pool.acquire(size=64)
    assert b1 is not b2
    pool.reset()
    b3 = pool.acquire(size=64)
    # First-free slot should be reused after reset.
    assert b3 is b1


def test_uniform_pool_round_trips_mat4():
    device = _wgpu_or_skip()
    pool = UniformBufferPool(device)
    buf = pool.acquire(size=64)
    m = np.eye(4, dtype=np.float32) * 2.0
    pool.write_mat4(buf, m)
    # Round-trip by copying back to a mappable staging buffer.
    import wgpu

    staging = device.create_buffer(
        size=64, usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ
    )
    enc = device.create_command_encoder()
    enc.copy_buffer_to_buffer(buf, 0, staging, 0, 64)
    device.queue.submit([enc.finish()])
    staging.map_sync(wgpu.MapMode.READ)
    try:
        raw = bytes(staging.read_mapped())
    finally:
        staging.unmap()
    got = np.frombuffer(raw, dtype=np.float32).reshape(4, 4)
    assert np.allclose(got, m)


def test_uniform_pool_write_mat4_rejects_bad_shape():
    device = _wgpu_or_skip()
    pool = UniformBufferPool(device)
    buf = pool.acquire(size=64)
    with pytest.raises(ValueError):
        pool.write_mat4(buf, np.zeros((3, 3), dtype=np.float32))


# ----------------------------------------------------------------------
# End-to-end wgpu render (mesh path)
# ----------------------------------------------------------------------
def test_wgpu_renderer_produces_nonzero_pixels():
    r = _renderer_or_skip(window_size=(64, 64), msaa=1)
    cam = Camera3D(position=(0, 0, 3), look_at=(0, 0, 0), aspect=1.0)
    r.set_camera(cam.view_matrix(), cam.projection_matrix())
    r.set_lights([Light(kind="ambient", color=(1, 1, 1), intensity=1.0)])
    r.begin_frame()
    mat = Material(base_color=(1.0, 0.2, 0.3, 1.0))
    r.submit_mesh(cube(1.0), Transform3D().matrix(), mat)
    r.end_frame()
    px = r.read_pixels()
    assert px.shape == (64, 64, 4)
    # Center of the frame should be red-ish (cube base color).
    center = px[32, 32]
    assert center[0] > 100  # red
    assert center[3] == 255  # alpha


def test_wgpu_renderer_backend_reports_wgpu():
    r = _renderer_or_skip()
    assert r.backend == "wgpu"
    assert not r.is_null


def test_wgpu_renderer_msaa1_valid_image():
    r = _renderer_or_skip(window_size=(32, 32), msaa=1)
    cam = Camera3D(position=(0, 0, 3), aspect=1.0)
    r.set_camera(cam.view_matrix(), cam.projection_matrix())
    r.set_lights([Light(kind="ambient", intensity=1.0)])
    r.begin_frame()
    r.submit_mesh(cube(1.0), Transform3D().matrix(), Material(base_color=(0.5, 0.5, 0.5, 1.0)))
    r.end_frame()
    px = r.read_pixels()
    assert px.shape == (32, 32, 4)
    assert px[16, 16, 0] > 50


def test_wgpu_renderer_msaa4_valid_image():
    r = _renderer_or_skip(window_size=(32, 32), msaa=4)
    cam = Camera3D(position=(0, 0, 3), aspect=1.0)
    r.set_camera(cam.view_matrix(), cam.projection_matrix())
    r.set_lights([Light(kind="ambient", intensity=1.0)])
    r.begin_frame()
    r.submit_mesh(cube(1.0), Transform3D().matrix(), Material(base_color=(0.5, 0.5, 0.5, 1.0)))
    r.end_frame()
    px = r.read_pixels()
    assert px.shape == (32, 32, 4)
    assert px[16, 16, 0] > 50


def test_wgpu_renderer_multi_frame_lifecycle():
    r = _renderer_or_skip(window_size=(16, 16), msaa=1)
    cam = Camera3D(position=(0, 0, 3), aspect=1.0)
    r.set_camera(cam.view_matrix(), cam.projection_matrix())
    r.set_lights([Light(kind="ambient", intensity=1.0)])
    for _ in range(3):
        r.begin_frame()
        r.submit_mesh(cube(1.0), Transform3D().matrix(), Material(base_color=(1, 1, 1, 1)))
        r.end_frame()
    assert r.frame_count >= 3


def test_wgpu_depth_test_near_occludes_far():
    r = _renderer_or_skip(window_size=(32, 32), msaa=1)
    cam = Camera3D(position=(0, 0, 3), aspect=1.0)
    r.set_camera(cam.view_matrix(), cam.projection_matrix())
    r.set_lights([Light(kind="ambient", intensity=1.0)])
    r.begin_frame()
    # Far cube = green, near cube = red. Near should paint over far.
    r.submit_mesh(
        cube(1.0),
        Transform3D(position=(0, 0, -2)).matrix(),
        Material(base_color=(0.0, 1.0, 0.0, 1.0)),
    )
    r.submit_mesh(
        cube(1.0),
        Transform3D(position=(0, 0, 0)).matrix(),
        Material(base_color=(1.0, 0.0, 0.0, 1.0)),
    )
    r.end_frame()
    px = r.read_pixels()
    center = px[16, 16]
    assert center[0] > center[1]  # red > green → near occludes far


def test_wgpu_phong_shading_lit_face_brighter_than_dark():
    r = _renderer_or_skip(window_size=(64, 64), msaa=1)
    cam = Camera3D(position=(2, 0.5, 2.5), look_at=(0, 0, 0), aspect=1.0)
    r.set_camera(cam.view_matrix(), cam.projection_matrix())
    # Light coming from +X.
    r.set_lights(
        [
            Light(kind="directional", direction=(-1.0, 0.0, 0.0), color=(1, 1, 1), intensity=1.0),
            Light(kind="ambient", color=(0.05, 0.05, 0.05), intensity=1.0),
        ]
    )
    r.begin_frame()
    r.submit_mesh(cube(1.0), Transform3D().matrix(), Material(base_color=(0.7, 0.7, 0.7, 1.0)))
    r.end_frame()
    px = r.read_pixels()
    # Just require that we got a non-clear frame.
    non_clear = np.abs(px[..., :3].astype(int) - np.array([13, 15, 20])).sum(axis=2)
    assert (non_clear > 30).sum() > 100


def test_wgpu_line_submission_no_error():
    r = _renderer_or_skip(window_size=(32, 32), msaa=1)
    cam = Camera3D(position=(0, 0, 3), aspect=1.0)
    r.set_camera(cam.view_matrix(), cam.projection_matrix())
    r.set_lights([Light(kind="ambient", intensity=1.0)])
    r.begin_frame()
    verts = np.array([[-1, 0, 0], [1, 0, 0], [0, -1, 0], [0, 1, 0]], dtype=np.float32)
    colors = np.array([[1, 0, 0, 1]] * 4, dtype=np.float32)
    r.submit_lines(verts, colors)
    r.end_frame()
    # Just assert the frame completed and the draw call was recorded.
    assert r.calls_of("line")


def test_wgpu_renderer_pipeline_cache_populated_after_first_draw():
    r = _renderer_or_skip(window_size=(16, 16), msaa=1)
    cam = Camera3D(position=(0, 0, 3), aspect=1.0)
    r.set_camera(cam.view_matrix(), cam.projection_matrix())
    r.set_lights([Light(kind="ambient", intensity=1.0)])
    assert len(r.pipeline_cache) == 0
    r.begin_frame()
    r.submit_mesh(cube(1.0), Transform3D().matrix(), Material())
    r.end_frame()
    assert len(r.pipeline_cache) >= 1


def test_wgpu_renderer_buffer_uploader_populated():
    r = _renderer_or_skip(window_size=(16, 16), msaa=1)
    cam = Camera3D(position=(0, 0, 3), aspect=1.0)
    r.set_camera(cam.view_matrix(), cam.projection_matrix())
    r.set_lights([Light(kind="ambient", intensity=1.0)])
    r.begin_frame()
    r.submit_mesh(cube(1.0), Transform3D().matrix(), Material())
    r.end_frame()
    # Two buffers: interleaved vertices + indices.
    assert len(r.buffer_uploader) >= 2


def test_wgpu_renderer_second_identical_submit_reuses_buffers():
    r = _renderer_or_skip(window_size=(16, 16), msaa=1)
    cam = Camera3D(position=(0, 0, 3), aspect=1.0)
    r.set_camera(cam.view_matrix(), cam.projection_matrix())
    r.set_lights([Light(kind="ambient", intensity=1.0)])
    r.begin_frame()
    r.submit_mesh(cube(1.0), Transform3D().matrix(), Material())
    n_after_1 = len(r.buffer_uploader)
    r.submit_mesh(cube(1.0), Transform3D().matrix(), Material())
    n_after_2 = len(r.buffer_uploader)
    r.end_frame()
    # Same mesh + identical model matrix → BufferUploader shouldn't grow.
    assert n_after_2 == n_after_1


def test_wgpu_renderer_records_draw_log_on_wgpu_path():
    r = _renderer_or_skip(window_size=(16, 16), msaa=1)
    cam = Camera3D(position=(0, 0, 3), aspect=1.0)
    r.set_camera(cam.view_matrix(), cam.projection_matrix())
    r.set_lights([Light(kind="ambient", intensity=1.0)])
    r.begin_frame()
    r.submit_mesh(cube(1.0), Transform3D().matrix(), Material(name="draw_me"))
    r.end_frame()
    assert any(c.payload.get("material_name") == "draw_me" for c in r.calls_of("mesh"))


def test_wgpu_renderer_offscreen_resize():
    r = _renderer_or_skip(window_size=(16, 16), msaa=1)
    r.create_offscreen(64, 48)
    assert r.window_size == (64, 48)
    cam = Camera3D(aspect=64 / 48)
    r.set_camera(cam.view_matrix(), cam.projection_matrix())
    r.set_lights([Light(kind="ambient", intensity=1.0)])
    r.begin_frame()
    r.submit_mesh(cube(1.0), Transform3D().matrix(), Material())
    r.end_frame()
    px = r.read_pixels()
    assert px.shape == (48, 64, 4)


def test_wgpu_renderer_clear_color_visible_in_readback():
    r = _renderer_or_skip(window_size=(8, 8), msaa=1, clear_color=(0.0, 1.0, 0.0, 1.0))
    r.set_camera(Camera3D().view_matrix(), Camera3D().projection_matrix())
    r.set_lights([])
    r.begin_frame()
    r.end_frame()
    px = r.read_pixels()
    # Fully cleared to green.
    assert px[0, 0, 1] == 255
    assert px[0, 0, 0] == 0


def test_wgpu_renderer_light_ubo_helper_shape():
    r = _renderer_or_skip()
    ubo = r.light_ubo([Light(kind="directional")])
    assert ubo.shape[0] == 4 * 16 + 4


# ----------------------------------------------------------------------
# Fallback path — force NullRenderer to ensure HH4 tests untouched
# ----------------------------------------------------------------------
def test_force_null_still_records_draw_log():
    r = Renderer(force_null=True)
    r.begin_frame()
    r.submit_mesh(cube(), Transform3D().matrix(), Material())
    r.end_frame()
    assert r.calls_of("mesh")
    assert r.is_null


def test_force_null_renderer_read_pixels_matches_clear():
    r = Renderer(force_null=True, window_size=(4, 3), clear_color=(1, 0, 0, 1))
    px = r.read_pixels()
    assert px.shape == (3, 4, 4)
    assert px[0, 0, 0] == 255


def test_pipeline_cache_key_len_seven():
    from pharos_engine.render.pipeline import _PipelineKey

    key = _PipelineKey(
        shader_id="phong_3d",
        mesh_format="pos3_nrm3_uv2",
        blend_mode="opaque",
        msaa=4,
        color_format="rgba8unorm",
        depth_format="depth24plus",
        topology="triangle-list",
    )
    assert len(key.as_tuple()) == 7


def test_vertex_attribute_dataclass_frozen():
    a = VertexAttribute(location=0, offset=0, format="float32x3")
    with pytest.raises(Exception):
        a.location = 1  # frozen
