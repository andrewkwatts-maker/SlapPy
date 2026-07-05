"""Tests for slappyengine.render.instanced — LL3 Nova3D parity Sprint 16.

All tests use the NullRenderer path — no GPU required.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from slappyengine.render import (
    Camera3D,
    Material,
    NullRenderer,
    cube,
    quad,
)
from slappyengine.render.instanced import (
    INSTANCED_MESH_WGSL,
    InstanceData,
    InstancedMesh,
    circle,
    from_transforms,
    grid,
    pack_instance_ssbo,
    pack_instance_ubo,
    random_scatter,
    render_instanced,
    submit_instanced,
)


# ----------------------------------------------------------------------
# InstanceData
# ----------------------------------------------------------------------
def test_instance_data_construction_transforms_only():
    ts = np.stack([np.eye(4, dtype=np.float32)] * 3)
    d = InstanceData(instance_transforms=ts)
    assert d.instance_count == 3
    assert d.instance_transforms.shape == (3, 4, 4)
    assert d.instance_transforms.dtype == np.float32
    assert d.instance_colors is None
    assert d.instance_uv_offsets is None


def test_instance_data_with_colors_and_uvs():
    ts = np.stack([np.eye(4, dtype=np.float32)] * 2)
    colors = np.array([[1, 0, 0, 1], [0, 1, 0, 1]], dtype=np.float32)
    uvs = np.array([[0.0, 0.0], [0.5, 0.25]], dtype=np.float32)
    d = InstanceData(
        instance_transforms=ts,
        instance_colors=colors,
        instance_uv_offsets=uvs,
    )
    assert d.instance_count == 2
    assert d.instance_colors.shape == (2, 4)
    assert d.instance_uv_offsets.shape == (2, 2)


def test_instance_data_rejects_bad_transform_shape():
    with pytest.raises(ValueError):
        InstanceData(instance_transforms=np.zeros((3, 3, 3), dtype=np.float32))


def test_instance_data_rejects_mismatched_colors():
    ts = np.stack([np.eye(4, dtype=np.float32)] * 3)
    bad = np.zeros((2, 4), dtype=np.float32)  # wrong count
    with pytest.raises(ValueError):
        InstanceData(instance_transforms=ts, instance_colors=bad)


def test_instance_data_rejects_mismatched_uv_offsets():
    ts = np.stack([np.eye(4, dtype=np.float32)] * 3)
    bad = np.zeros((3, 3), dtype=np.float32)  # wrong last dim
    with pytest.raises(ValueError):
        InstanceData(instance_transforms=ts, instance_uv_offsets=bad)


# ----------------------------------------------------------------------
# InstancedMesh
# ----------------------------------------------------------------------
def test_instanced_mesh_instance_count_proxy():
    ts = np.stack([np.eye(4, dtype=np.float32)] * 5)
    im = InstancedMesh(base_mesh=cube(), instance_data=InstanceData(ts))
    assert im.instance_count == 5


def test_instanced_mesh_bounding_box_all_identity():
    ts = np.stack([np.eye(4, dtype=np.float32)])
    im = InstancedMesh(base_mesh=cube(1.0), instance_data=InstanceData(ts))
    lo, hi = im.bounding_box_all
    assert lo == pytest.approx((-0.5, -0.5, -0.5))
    assert hi == pytest.approx((0.5, 0.5, 0.5))


def test_instanced_mesh_bounding_box_covers_all_instances():
    im = grid(cube(1.0), rows=3, cols=3, spacing=4.0)
    lo, hi = im.bounding_box_all
    # rows=3, cols=3, spacing=4 → centres at ±4 along X/Z with ±0.5 mesh half
    assert lo[0] == pytest.approx(-4.5)
    assert hi[0] == pytest.approx(4.5)
    assert lo[2] == pytest.approx(-4.5)
    assert hi[2] == pytest.approx(4.5)


# ----------------------------------------------------------------------
# Factories — grid
# ----------------------------------------------------------------------
def test_grid_count():
    im = grid(cube(), rows=4, cols=5, spacing=2.0)
    assert im.instance_count == 20


def test_grid_positions_expected():
    im = grid(cube(), rows=2, cols=2, spacing=3.0)
    ts = im.instance_data.instance_transforms
    positions = {tuple(np.round(t[:3, 3], 4)) for t in ts}
    assert (-1.5, 0.0, -1.5) in positions
    assert (1.5, 0.0, -1.5) in positions
    assert (-1.5, 0.0, 1.5) in positions
    assert (1.5, 0.0, 1.5) in positions


def test_grid_zero_rows_or_cols():
    im = grid(cube(), rows=0, cols=5, spacing=1.0)
    assert im.instance_count == 0
    # Zero-instance bbox falls back to origin sentinel.
    assert im.bounding_box_all == ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))


# ----------------------------------------------------------------------
# Factories — random_scatter
# ----------------------------------------------------------------------
def test_random_scatter_count():
    im = random_scatter(
        cube(), count=100, region=((-5, -5, -5), (5, 5, 5)), seed=42
    )
    assert im.instance_count == 100


def test_random_scatter_deterministic_with_seed():
    r1 = random_scatter(
        cube(), count=50, region=((-1, -1, -1), (1, 1, 1)), seed=7
    )
    r2 = random_scatter(
        cube(), count=50, region=((-1, -1, -1), (1, 1, 1)), seed=7
    )
    np.testing.assert_array_equal(
        r1.instance_data.instance_transforms,
        r2.instance_data.instance_transforms,
    )


def test_random_scatter_within_region():
    im = random_scatter(
        cube(), count=200, region=((-3, -2, -1), (3, 2, 1)), seed=99
    )
    ts = im.instance_data.instance_transforms
    positions = ts[:, :3, 3]
    assert positions[:, 0].min() >= -3.0 - 1e-4
    assert positions[:, 0].max() <= 3.0 + 1e-4
    assert positions[:, 1].min() >= -2.0 - 1e-4
    assert positions[:, 1].max() <= 2.0 + 1e-4
    assert positions[:, 2].min() >= -1.0 - 1e-4
    assert positions[:, 2].max() <= 1.0 + 1e-4


# ----------------------------------------------------------------------
# Factories — circle
# ----------------------------------------------------------------------
def test_circle_count():
    im = circle(cube(), count=8, radius=3.0)
    assert im.instance_count == 8


def test_circle_places_at_radius():
    im = circle(cube(), count=12, radius=4.0)
    ts = im.instance_data.instance_transforms
    for t in ts:
        x, _y, z = t[0, 3], t[1, 3], t[2, 3]
        assert math.isclose(math.hypot(x, z), 4.0, rel_tol=1e-5)


def test_circle_first_instance_on_positive_x_axis():
    im = circle(cube(), count=6, radius=2.5)
    first = im.instance_data.instance_transforms[0]
    assert first[0, 3] == pytest.approx(2.5)
    assert first[2, 3] == pytest.approx(0.0, abs=1e-5)


# ----------------------------------------------------------------------
# Factories — from_transforms
# ----------------------------------------------------------------------
def test_from_transforms_explicit_list():
    a = np.eye(4, dtype=np.float32)
    a[0, 3] = 7.0
    b = np.eye(4, dtype=np.float32)
    b[1, 3] = -2.0
    im = from_transforms(cube(), [a, b])
    assert im.instance_count == 2
    assert im.instance_data.instance_transforms[0][0, 3] == pytest.approx(7.0)
    assert im.instance_data.instance_transforms[1][1, 3] == pytest.approx(-2.0)


def test_from_transforms_accepts_single_matrix():
    m = np.eye(4, dtype=np.float32)
    im = from_transforms(cube(), m)
    assert im.instance_count == 1


def test_from_transforms_rejects_bad_shape():
    with pytest.raises(ValueError):
        from_transforms(cube(), np.zeros((3, 5, 5), dtype=np.float32))


# ----------------------------------------------------------------------
# WGSL
# ----------------------------------------------------------------------
def test_instanced_mesh_wgsl_has_vertex_entry():
    assert "@vertex" in INSTANCED_MESH_WGSL
    assert "@fragment" in INSTANCED_MESH_WGSL
    assert "fn vs_main" in INSTANCED_MESH_WGSL


def test_instanced_mesh_wgsl_reads_per_instance_transform():
    # Storage buffer indexed by @builtin(instance_index) with a mat4x4
    # model field is the contract.
    assert "instance_index" in INSTANCED_MESH_WGSL
    assert "instances.data" in INSTANCED_MESH_WGSL
    assert "model: mat4x4<f32>" in INSTANCED_MESH_WGSL
    assert "var<storage" in INSTANCED_MESH_WGSL


def test_instanced_mesh_wgsl_byte_count_reasonable():
    n = len(INSTANCED_MESH_WGSL.encode("utf-8"))
    assert 500 < n < 4000


# ----------------------------------------------------------------------
# UBO / SSBO packing
# ----------------------------------------------------------------------
def test_pack_instance_ubo_byte_count():
    im = grid(cube(), rows=2, cols=3, spacing=1.0)  # 6 instances
    blob = pack_instance_ubo(im.instance_data)
    # N * 4x4 mat = N * 64 bytes
    assert len(blob) == 6 * 64


def test_pack_instance_ssbo_byte_count():
    im = grid(cube(), rows=2, cols=3, spacing=1.0)  # 6 instances
    blob = pack_instance_ssbo(im.instance_data)
    # mat4 (64) + color vec4 (16) + uv_offset vec4 (16) = 96 per inst
    assert len(blob) == 6 * 96


def test_pack_instance_ssbo_defaults_white_color():
    ts = np.stack([np.eye(4, dtype=np.float32)])
    d = InstanceData(instance_transforms=ts)
    blob = pack_instance_ssbo(d)
    arr = np.frombuffer(blob, dtype=np.float32).reshape(1, 24)
    # bytes 64-79 → floats 16..20 are the color; default is opaque white.
    np.testing.assert_array_equal(arr[0, 16:20], [1.0, 1.0, 1.0, 1.0])


def test_pack_instance_ssbo_encodes_provided_color():
    ts = np.stack([np.eye(4, dtype=np.float32)])
    colors = np.array([[0.25, 0.5, 0.75, 1.0]], dtype=np.float32)
    d = InstanceData(instance_transforms=ts, instance_colors=colors)
    blob = pack_instance_ssbo(d)
    arr = np.frombuffer(blob, dtype=np.float32).reshape(1, 24)
    np.testing.assert_allclose(arr[0, 16:20], [0.25, 0.5, 0.75, 1.0])


def test_pack_helpers_reject_non_instance_data():
    with pytest.raises(TypeError):
        pack_instance_ubo("nope")
    with pytest.raises(TypeError):
        pack_instance_ssbo(42)


# ----------------------------------------------------------------------
# Renderer dispatch
# ----------------------------------------------------------------------
def test_render_instanced_dispatches_single_draw_call():
    r = NullRenderer()
    r.begin_frame()
    im = grid(cube(), rows=3, cols=3, spacing=2.0)
    render_instanced(r, im, Material(name="stone"))
    r.end_frame()
    meshes = r.calls_of("mesh")
    assert len(meshes) == 1
    payload = meshes[0].payload
    assert payload["instance_count"] == 9
    assert payload["instanced"] is True
    assert payload["material_name"] == "stone"


def test_submit_instanced_alias_works_identically():
    r = NullRenderer()
    r.begin_frame()
    im = circle(cube(), count=6, radius=3.0)
    submit_instanced(r, im, Material(name="alias"))
    r.end_frame()
    meshes = r.calls_of("mesh")
    assert len(meshes) == 1
    assert meshes[0].payload["instance_count"] == 6
    assert meshes[0].payload["material_name"] == "alias"


def test_render_instanced_updates_camera_when_provided():
    r = NullRenderer()
    r.begin_frame()
    im = grid(cube(), rows=1, cols=1, spacing=1.0)
    cam = Camera3D(position=(0.0, 3.0, 8.0))
    render_instanced(r, im, Material(), cam)
    r.end_frame()
    assert r.calls_of("camera"), "camera call should have been recorded"
    assert r.calls_of("mesh"), "instanced mesh call should be recorded"


def test_render_instanced_records_bounding_box_all():
    r = NullRenderer()
    r.begin_frame()
    im = grid(cube(), rows=2, cols=2, spacing=5.0)
    render_instanced(r, im, Material())
    r.end_frame()
    payload = r.calls_of("mesh")[0].payload
    lo, hi = payload["bounding_box_all"]
    assert lo[0] == pytest.approx(-3.0)
    assert hi[0] == pytest.approx(3.0)


def test_render_instanced_uses_base_mesh_topology_counts():
    r = NullRenderer()
    r.begin_frame()
    base = quad(1.0)
    im = from_transforms(base, [np.eye(4, dtype=np.float32)] * 4)
    render_instanced(r, im, Material())
    r.end_frame()
    payload = r.calls_of("mesh")[0].payload
    assert payload["vertex_count"] == int(base.vertices.shape[0])
    assert payload["triangle_count"] == int(base.indices.shape[0])
    assert payload["instance_count"] == 4
