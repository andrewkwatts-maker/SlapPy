"""Tests for slappyengine.render.shadows — CSM math + PCF WGSL (JJ7).

All tests are pure math + WGSL source-string checks. No wgpu needed.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from slappyengine.render import Camera3D, Light
from slappyengine.render.shadows import (
    CSMBuilder,
    CascadeSplit,
    SHADOW_DEPTH_ONLY_WGSL,
    SHADOW_SAMPLE_WGSL_SNIPPET,
    SHADOW_SAMPLER_DESC,
    ShadowMapConfig,
    find_cascade_for_world_pos,
    pack_cascade_ubo,
)


# ----------------------------------------------------------------------
# Split scheme
# ----------------------------------------------------------------------
def test_compute_cascade_splits_returns_four_pairs() -> None:
    splits = CSMBuilder.compute_cascade_splits(0.1, 100.0, 4, 0.5)
    assert len(splits) == 4
    for near, far in splits:
        assert far > near


def test_cascade_splits_monotonic() -> None:
    splits = CSMBuilder.compute_cascade_splits(0.1, 100.0, 4, 0.5)
    # Farther cascades cover later frustum slabs.
    for i in range(len(splits) - 1):
        assert splits[i][1] == pytest.approx(splits[i + 1][0])
    assert splits[0][0] == pytest.approx(0.1)
    assert splits[-1][1] == pytest.approx(100.0)


def test_cascade_splits_lambda_zero_is_uniform() -> None:
    splits = CSMBuilder.compute_cascade_splits(1.0, 5.0, 4, 0.0)
    # Uniform: each cascade covers 1 unit.
    for near, far in splits:
        assert (far - near) == pytest.approx(1.0)


def test_cascade_splits_lambda_one_is_logarithmic() -> None:
    splits = CSMBuilder.compute_cascade_splits(1.0, 16.0, 4, 1.0)
    # Log-uniform: ratio of each pair should be constant = 16^(1/4) = 2.
    ratios = [far / near for near, far in splits]
    for r in ratios:
        assert r == pytest.approx(2.0, rel=1e-4)


def test_cascade_splits_empty_when_count_zero() -> None:
    assert CSMBuilder.compute_cascade_splits(0.1, 100.0, 0, 0.5) == []


def test_cascade_splits_bad_range_raises() -> None:
    with pytest.raises(ValueError):
        CSMBuilder.compute_cascade_splits(10.0, 1.0, 4, 0.5)


# ----------------------------------------------------------------------
# Light view
# ----------------------------------------------------------------------
def test_compute_light_view_shape() -> None:
    light = Light(kind="directional", direction=(0.0, -1.0, 0.0))
    view = CSMBuilder.compute_light_view(light)
    assert view.shape == (4, 4)
    assert view.dtype == np.float32


def test_compute_light_view_transforms_origin() -> None:
    """A downward light view should keep world origin at light-space origin xy."""
    light = Light(kind="directional", direction=(0.0, -1.0, 0.0))
    view = CSMBuilder.compute_light_view(light)
    origin = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
    ls = view @ origin
    assert abs(ls[0]) < 1e-4
    assert abs(ls[1]) < 1e-4


def test_compute_light_view_degenerate_direction_uses_fallback() -> None:
    light = Light(kind="directional", direction=(0.0, -1.0, 0.0))
    # Poke a zero direction (bypass Light's normalize) — should not crash.
    light.direction = (0.0, 0.0, 0.0)
    view = CSMBuilder.compute_light_view(light)
    assert not np.any(np.isnan(view))


# ----------------------------------------------------------------------
# Frustum corners
# ----------------------------------------------------------------------
def test_frustum_corners_returns_eight() -> None:
    cam = Camera3D(position=(0.0, 0.0, 5.0), look_at=(0.0, 0.0, 0.0))
    vp = cam.view_projection()
    corners = CSMBuilder.frustum_corners_world(vp)
    assert corners.shape == (8, 3)


def test_frustum_corners_non_degenerate() -> None:
    cam = Camera3D(position=(3.0, 2.0, 5.0), look_at=(0.0, 0.0, 0.0))
    vp = cam.view_projection()
    corners = CSMBuilder.frustum_corners_world(vp)
    # Points must not collapse to a single location.
    span = corners.max(axis=0) - corners.min(axis=0)
    assert float(np.max(span)) > 1e-3


# ----------------------------------------------------------------------
# Ortho bounds
# ----------------------------------------------------------------------
def test_compute_ortho_bounds_non_degenerate_shifted_camera() -> None:
    cam = Camera3D(position=(3.0, 2.0, 5.0), look_at=(0.0, 0.0, 0.0))
    vp = cam.view_projection()
    light = Light(kind="directional", direction=(0.0, -1.0, 0.0))
    light_view = CSMBuilder.compute_light_view(light)
    l, r, b, t, n, f = CSMBuilder.compute_ortho_bounds(vp, light_view)
    assert r > l
    assert t > b
    assert f > n


def test_compute_ortho_bounds_returns_six_floats() -> None:
    cam = Camera3D()
    light = Light(kind="directional", direction=(0.0, -1.0, 0.0))
    lv = CSMBuilder.compute_light_view(light)
    bounds = CSMBuilder.compute_ortho_bounds(cam.view_projection(), lv)
    assert len(bounds) == 6
    for b in bounds:
        assert isinstance(b, float)


# ----------------------------------------------------------------------
# Stabilisation
# ----------------------------------------------------------------------
def test_stabilize_bounds_preserves_size() -> None:
    bounds = (0.13, 4.13, -2.7, 5.3, 0.5, 20.5)
    l, r, b, t, n, f = CSMBuilder.stabilize(bounds, 2048)
    assert (r - l) == pytest.approx(bounds[1] - bounds[0], rel=1e-4)
    assert (t - b) == pytest.approx(bounds[3] - bounds[2], rel=1e-4)


def test_stabilize_snap_within_texel() -> None:
    bounds = (0.13, 4.13, -2.7, 5.3, 0.5, 20.5)
    l, r, b, t, n, f = CSMBuilder.stabilize(bounds, 2048)
    texel_x = (bounds[1] - bounds[0]) / 2048
    texel_y = (bounds[3] - bounds[2]) / 2048
    # Snapped origin is within one texel of the original bound.
    assert abs(l - bounds[0]) <= texel_x + 1e-6
    assert abs(b - bounds[2]) <= texel_y + 1e-6


def test_stabilize_z_bounds_unchanged() -> None:
    bounds = (0.13, 4.13, -2.7, 5.3, 0.5, 20.5)
    _, _, _, _, n, f = CSMBuilder.stabilize(bounds, 2048)
    assert n == bounds[4]
    assert f == bounds[5]


# ----------------------------------------------------------------------
# build_cascades
# ----------------------------------------------------------------------
def test_build_cascades_default_count() -> None:
    cam = Camera3D(near=0.1, far=100.0)
    light = Light(kind="directional", direction=(0.3, -1.0, 0.2))
    cfg = ShadowMapConfig()
    cascades = CSMBuilder.build_cascades(cam, light, cfg)
    assert len(cascades) == 4


def test_build_cascades_monotonic_splits() -> None:
    cam = Camera3D(near=0.1, far=100.0)
    light = Light(kind="directional", direction=(0.3, -1.0, 0.2))
    cfg = ShadowMapConfig()
    cascades = CSMBuilder.build_cascades(cam, light, cfg)
    for i in range(len(cascades) - 1):
        assert cascades[i].far_z <= cascades[i + 1].near_z + 1e-4
    assert cascades[0].near_z == pytest.approx(0.1)


def test_build_cascades_indices_dense() -> None:
    cam = Camera3D()
    light = Light(kind="directional")
    cfg = ShadowMapConfig(cascade_count=4)
    cascades = CSMBuilder.build_cascades(cam, light, cfg)
    assert [c.shadow_map_index for c in cascades] == [0, 1, 2, 3]


def test_build_cascades_matrices_are_4x4_float32() -> None:
    cam = Camera3D()
    light = Light(kind="directional")
    cfg = ShadowMapConfig()
    cascades = CSMBuilder.build_cascades(cam, light, cfg)
    for c in cascades:
        assert c.light_view_matrix.shape == (4, 4)
        assert c.light_projection_matrix.shape == (4, 4)
        assert c.light_view_projection.shape == (4, 4)
        assert c.light_view_matrix.dtype == np.float32
        assert c.light_view_projection.dtype == np.float32


def test_build_cascades_respects_max_shadow_distance() -> None:
    cam = Camera3D(near=0.1, far=1000.0)
    light = Light(kind="directional")
    cfg = ShadowMapConfig(max_shadow_distance=50.0)
    cascades = CSMBuilder.build_cascades(cam, light, cfg)
    assert cascades[-1].far_z == pytest.approx(50.0, rel=1e-4)


def test_build_cascades_restores_camera_near_far() -> None:
    cam = Camera3D(near=0.5, far=200.0)
    light = Light(kind="directional")
    cfg = ShadowMapConfig()
    _ = CSMBuilder.build_cascades(cam, light, cfg)
    assert cam.near == 0.5
    assert cam.far == 200.0


def test_build_cascades_stabilize_off_still_works() -> None:
    cam = Camera3D()
    light = Light(kind="directional")
    cfg = ShadowMapConfig(stabilize_cascades=False)
    cascades = CSMBuilder.build_cascades(cam, light, cfg)
    assert len(cascades) == 4


# ----------------------------------------------------------------------
# UBO packing
# ----------------------------------------------------------------------
def test_pack_cascade_ubo_byte_length() -> None:
    cam = Camera3D()
    light = Light(kind="directional")
    cascades = CSMBuilder.build_cascades(cam, light, ShadowMapConfig())
    blob = pack_cascade_ubo(cascades)
    # 4 cascades * 16 floats * 4 bytes = 256 bytes.
    assert len(blob) == 256


def test_pack_cascade_ubo_empty_pads_to_256() -> None:
    assert len(pack_cascade_ubo([])) == 256


def test_pack_cascade_ubo_truncates_over_four() -> None:
    cam = Camera3D()
    light = Light(kind="directional")
    cascades = CSMBuilder.build_cascades(cam, light, ShadowMapConfig())
    # Overpack: send 6, should still be 256 bytes.
    blob = pack_cascade_ubo(list(cascades) + list(cascades[:2]))
    assert len(blob) == 256


# ----------------------------------------------------------------------
# Cascade selection
# ----------------------------------------------------------------------
def test_find_cascade_for_world_pos_near_origin() -> None:
    cam = Camera3D(position=(0.0, 5.0, 5.0), look_at=(0.0, 0.0, 0.0))
    light = Light(kind="directional", direction=(0.0, -1.0, 0.0))
    cascades = CSMBuilder.build_cascades(cam, light, ShadowMapConfig())
    idx = find_cascade_for_world_pos((0.0, 0.0, 0.0), cascades)
    assert idx in (0, 1, 2, 3)


def test_find_cascade_empty_returns_negative() -> None:
    assert find_cascade_for_world_pos((0.0, 0.0, 0.0), []) == -1


def test_find_cascade_falls_back_to_last() -> None:
    cam = Camera3D()
    light = Light(kind="directional")
    cascades = CSMBuilder.build_cascades(cam, light, ShadowMapConfig())
    # A point very far away should fall back to the last cascade index.
    idx = find_cascade_for_world_pos((1e6, 1e6, 1e6), cascades)
    assert idx == cascades[-1].shadow_map_index


# ----------------------------------------------------------------------
# WGSL sources
# ----------------------------------------------------------------------
def test_shadow_depth_only_wgsl_has_vertex_marker() -> None:
    assert "@vertex" in SHADOW_DEPTH_ONLY_WGSL
    assert "vs_main" in SHADOW_DEPTH_ONLY_WGSL


def test_shadow_depth_only_wgsl_has_fragment_marker() -> None:
    assert "@fragment" in SHADOW_DEPTH_ONLY_WGSL


def test_shadow_sample_snippet_has_function() -> None:
    assert "sample_shadow_cascade" in SHADOW_SAMPLE_WGSL_SNIPPET
    assert "texture_depth_2d_array" in SHADOW_SAMPLE_WGSL_SNIPPET
    assert "sampler_comparison" in SHADOW_SAMPLE_WGSL_SNIPPET


def test_shadow_sample_snippet_has_pcf_loop() -> None:
    # 3x3 PCF should contain nested loops in the source.
    src = SHADOW_SAMPLE_WGSL_SNIPPET
    assert src.count("for (var") >= 2


def test_wgsl_sources_within_byte_budget() -> None:
    # Depth pass must be tiny (aim ~400B).
    assert len(SHADOW_DEPTH_ONLY_WGSL.encode("utf-8")) < 800
    # Sample snippet stays under ~1500 B (3x3 PCF + guards).
    assert len(SHADOW_SAMPLE_WGSL_SNIPPET.encode("utf-8")) < 1500


# ----------------------------------------------------------------------
# Sampler config
# ----------------------------------------------------------------------
def test_shadow_sampler_desc_compare_mode() -> None:
    assert SHADOW_SAMPLER_DESC["compare"] == "less_equal"


def test_shadow_sampler_desc_linear_mag_filter() -> None:
    assert SHADOW_SAMPLER_DESC["mag_filter"] == "linear"


# ----------------------------------------------------------------------
# Dataclass basics
# ----------------------------------------------------------------------
def test_shadow_map_config_defaults() -> None:
    cfg = ShadowMapConfig()
    assert cfg.resolution == 2048
    assert cfg.cascade_count == 4
    assert cfg.cascade_split_lambda == 0.5
    assert cfg.max_shadow_distance == 100.0
    assert cfg.stabilize_cascades is True


def test_cascade_split_is_dataclass() -> None:
    m = np.eye(4, dtype=np.float32)
    c = CascadeSplit(
        near_z=0.1,
        far_z=10.0,
        light_view_matrix=m,
        light_projection_matrix=m,
        light_view_projection=m,
        shadow_map_index=0,
    )
    assert c.shadow_map_index == 0
    assert c.near_z == 0.1
