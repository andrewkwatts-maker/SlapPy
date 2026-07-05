"""Tests for slappyengine.render.ssao — screen-space AO for the forward renderer.

All checks are pure numpy + WGSL source-string introspection. The GPU path
is exercised through :class:`NullRenderer` so no wgpu adapter is needed.
"""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.render import Camera3D, NullRenderer
from slappyengine.render.ssao import (
    SSAOConfig,
    SSAOPass,
    depth_to_view_z,
    reconstruct_position_from_depth,
)


# ----------------------------------------------------------------------
# SSAOConfig
# ----------------------------------------------------------------------
def test_ssao_config_defaults() -> None:
    cfg = SSAOConfig()
    assert cfg.sample_count == 16
    assert cfg.radius_world == pytest.approx(0.5)
    assert cfg.bias == pytest.approx(0.025)
    assert cfg.intensity == pytest.approx(1.5)
    assert cfg.noise_texture_size == 4


def test_ssao_config_overrides() -> None:
    cfg = SSAOConfig(sample_count=32, radius_world=1.0, bias=0.05)
    assert cfg.sample_count == 32
    assert cfg.radius_world == pytest.approx(1.0)
    assert cfg.bias == pytest.approx(0.05)


# ----------------------------------------------------------------------
# Construction guards
# ----------------------------------------------------------------------
def test_ssao_pass_rejects_bad_config() -> None:
    with pytest.raises(TypeError):
        SSAOPass("not a config", (128, 128))  # type: ignore[arg-type]


def test_ssao_pass_rejects_zero_screen() -> None:
    with pytest.raises(ValueError):
        SSAOPass(SSAOConfig(), (0, 128))


def test_ssao_pass_rejects_zero_samples() -> None:
    with pytest.raises(ValueError):
        SSAOPass(SSAOConfig(sample_count=0), (128, 128))


# ----------------------------------------------------------------------
# Kernel
# ----------------------------------------------------------------------
def test_generate_kernel_shape_and_count() -> None:
    p = SSAOPass(SSAOConfig(sample_count=24), (256, 256))
    k = p.generate_kernel()
    assert k.shape == (24, 3)
    assert k.dtype == np.float32


def test_generate_kernel_hemisphere() -> None:
    """All samples should live on the +z half-space (tangent-space z >= 0)."""
    p = SSAOPass(SSAOConfig(sample_count=32), (256, 256))
    k = p.generate_kernel()
    assert np.all(k[:, 2] >= 0.0 - 1e-6)


def test_generate_kernel_center_bias() -> None:
    """Average length must grow with sample index (radius-biased spread)."""
    p = SSAOPass(SSAOConfig(sample_count=16), (256, 256))
    k = p.generate_kernel()
    lengths = np.linalg.norm(k, axis=1)
    # Bucket into 4 quarters and check monotone growth of the mean length.
    buckets = lengths.reshape(4, 4).mean(axis=1)
    for a, b in zip(buckets[:-1], buckets[1:]):
        assert b > a


def test_generate_kernel_never_zero() -> None:
    p = SSAOPass(SSAOConfig(sample_count=16), (256, 256))
    k = p.generate_kernel()
    lengths = np.linalg.norm(k, axis=1)
    assert np.all(lengths > 1e-4)


# ----------------------------------------------------------------------
# Noise texture
# ----------------------------------------------------------------------
def test_generate_noise_texture_shape() -> None:
    p = SSAOPass(SSAOConfig(noise_texture_size=4), (256, 256))
    n = p.generate_noise_texture()
    assert n.shape == (16, 3)
    assert n.dtype == np.float32


def test_generate_noise_texture_tangent_plane() -> None:
    """Rotation vectors live in the tangent plane (z == 0)."""
    p = SSAOPass(SSAOConfig(), (256, 256))
    n = p.generate_noise_texture()
    assert np.all(n[:, 2] == 0.0)


def test_generate_noise_texture_normalised_xy() -> None:
    p = SSAOPass(SSAOConfig(), (256, 256))
    n = p.generate_noise_texture()
    xy_lens = np.linalg.norm(n[:, :2], axis=1)
    np.testing.assert_allclose(xy_lens, 1.0, atol=1e-5)


def test_generate_noise_texture_custom_size() -> None:
    p = SSAOPass(SSAOConfig(noise_texture_size=8), (256, 256))
    n = p.generate_noise_texture()
    assert n.shape == (64, 3)


# ----------------------------------------------------------------------
# Utilities
# ----------------------------------------------------------------------
def test_depth_to_view_z_near_and_far() -> None:
    """A depth of 0 should map near the near plane; 1 near the far plane."""
    near, far = 0.1, 100.0
    # Reverse-Y projection: depth=0 at near plane -> z_view=near.
    z_near = depth_to_view_z(0.0, near, far)
    assert z_near == pytest.approx(near, rel=1e-3)
    z_far = depth_to_view_z(1.0, near, far)
    # depth=1 corresponds to the far plane in reverse-Y wgpu convention.
    assert z_far == pytest.approx(far, rel=1e-2)


def test_reconstruct_position_round_trip_identity() -> None:
    """Identity inverse projection: uv/depth pass through cleanly."""
    identity = np.eye(4, dtype=np.float32)
    pos = reconstruct_position_from_depth((0.5, 0.5), 0.5, identity)
    # UV (0.5, 0.5) with identity maps to clip (0, 0, 0.5) / w=1.
    assert pos.shape == (3,)
    np.testing.assert_allclose(pos, np.array([0.0, 0.0, 0.5]), atol=1e-5)


def test_reconstruct_position_uses_camera_proj() -> None:
    """Round-trip using a real Camera3D inverse projection."""
    cam = Camera3D(position=(0.0, 0.0, 5.0))
    p = cam.projection_matrix()
    p_inv = np.linalg.inv(p)
    # A pixel at the centre of the screen at depth 0.5 should reconstruct
    # to a view-space z that's negative (right-handed) with finite xy.
    pos = reconstruct_position_from_depth((0.5, 0.5), 0.5, p_inv)
    assert np.isfinite(pos).all()
    # Centre pixel: xy should be very close to 0.
    assert abs(pos[0]) < 1e-4
    assert abs(pos[1]) < 1e-4


# ----------------------------------------------------------------------
# WGSL emission
# ----------------------------------------------------------------------
def test_emit_ssao_wgsl_has_fragment_entry() -> None:
    p = SSAOPass(SSAOConfig(), (1280, 720))
    src = p.emit_ssao_wgsl()
    assert "@fragment" in src
    assert "fs_main" in src
    assert "depth_texture" in src
    assert "normal_texture" in src


def test_emit_ssao_wgsl_under_budget() -> None:
    """WGSL body should stay well under the 4KB safety cap."""
    p = SSAOPass(SSAOConfig(), (1280, 720))
    src = p.emit_ssao_wgsl()
    assert len(src) < 4096
    assert len(src) > 500  # sanity: not empty


def test_emit_ssao_wgsl_bakes_sample_count() -> None:
    p = SSAOPass(SSAOConfig(sample_count=24), (256, 256))
    src = p.emit_ssao_wgsl()
    # The sample count should appear in the loop bound and array size.
    assert "24" in src


def test_emit_blur_wgsl_bilateral() -> None:
    p = SSAOPass(SSAOConfig(), (1280, 720))
    src = p.emit_blur_wgsl()
    assert "@fragment" in src
    assert "fs_blur" in src
    assert "depth_tex" in src
    assert len(src) < 1600


# ----------------------------------------------------------------------
# execute() via NullRenderer
# ----------------------------------------------------------------------
def test_execute_returns_texture_shape_matches_screen() -> None:
    r = NullRenderer(window_size=(320, 240))
    cam = Camera3D()
    p = SSAOPass(SSAOConfig(), (320, 240))

    class _Tex:
        pass

    ao = p.execute(r, cam, _Tex(), _Tex())
    assert ao is not None
    # NullRenderer.upload_texture returns a TextureHandle sized to input.
    assert ao.width == 320
    assert ao.height == 240


def test_execute_logs_ssao_draw_call() -> None:
    r = NullRenderer(window_size=(320, 240))
    cam = Camera3D()
    p = SSAOPass(SSAOConfig(), (320, 240))
    depth = object()
    normal = object()
    p.execute(r, cam, depth, normal)
    ssao_calls = [c for c in r.draw_log if c.kind == "ssao"]
    assert len(ssao_calls) == 1
    payload = ssao_calls[0].payload
    assert payload["screen_size"] == (320, 240)
    assert payload["sample_count"] == 16
