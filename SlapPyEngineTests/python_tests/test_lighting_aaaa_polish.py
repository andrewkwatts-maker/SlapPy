"""Regression tests for AAAA-quality lighting polish landed 2026-05-26.

These tests don't run the full GPU pipeline — they verify the shader
source code carries the expected features (soft-PCF shadows, Karis
firefly suppression, per-pixel jitter on fog ray marches) so a future
refactor that accidentally re-introduces the binary 0.3/1.0 shadow or
removes the firefly clamp gets caught at unit-test time.

Run:
    PYTHONPATH=python python -m pytest python/tests/test_lighting_aaaa_polish.py -q
"""
from __future__ import annotations

from pathlib import Path


_SHADERS = Path(__file__).resolve().parents[2] / "shaders"


def _shader(name: str) -> str:
    return (_SHADERS / name).read_text(encoding="utf-8")


def test_directional_shadows_use_soft_pcf_not_binary_03():
    """The pre-polish shader had ``if (sz > z) { shadow_factor = 0.3; }``
    which produces a hard "billiard-ball stencil" shadow boundary. The
    polished version replaces it with a 5-tap cross PCF kernel and
    smooth shadow_t lerp."""
    src = _shader("lighting_directional.wgsl")
    # The old binary 0.3 assignment is gone
    assert "shadow_factor = 0.3" not in src, (
        "directional shadow regressed to binary 0.3/1.0"
    )
    # The new PCF features are in place
    assert "_tap_occluded" in src
    assert "SHADOW_MIN" in src
    assert "SHADOW_TAP_PX" in src
    # Five taps means the centre + 4 perpendicular samples
    assert src.count("_tap_occluded(") >= 5


def test_bloom_has_karis_firefly_suppression():
    """The pre-polish bloom shader extracted glow as ``color * weight``
    which lets a single 100-nit speck strobe across frames. The Karis
    average divides by (1 + luma) to cap firefly contribution."""
    src = _shader("bloom.wgsl")
    assert "firefly_clamp" in src or "1.0 / (1.0 + lum" in src, (
        "bloom regressed: Karis firefly suppression missing"
    )


def test_volumetric_fog_uses_per_pixel_jitter():
    """Pre-polish fog stepped at ``(f32(i) + 0.5)*step_size`` for every
    pixel, causing visible slice-banding. The polished version adds a
    per-pixel + per-time hash jitter so TAA dissolves the residual."""
    src = _shader("volumetric_fog.wgsl")
    assert "jitter" in src, "volumetric fog regressed: no jitter"
    assert "params.time" in src, (
        "volumetric fog regressed: jitter not animated"
    )
    # The legacy "(f32(i) + 0.5)*step_size" pattern must be gone
    assert "(f32(i) + 0.5) * step_size" not in src, (
        "volumetric fog regressed to non-jittered step midpoints"
    )


def test_point_light_uses_karis_windowed_inverse_square():
    """Pre-polish point light used plain 1/(1 + d²/r²) which produces a
    visible "light disc edge" line at the radius boundary. Karis-windowed
    inverse-square multiplies by smoothstep((d/r)^4) so the light fades
    cleanly to zero at radius."""
    src = _shader("lighting_point.wgsl")
    assert "window" in src or "dr4" in src, (
        "point light regressed: no Karis window term"
    )
    assert "Karis" in src or "windowed" in src, (
        "point light regressed: Karis attribution comment missing"
    )


def test_cluster_accum_clear_reuses_cached_zero_buffer():
    """The pre-polish lighting system allocated bytes(w*h*8) every frame
    to zero-clear the cluster accumulator (~16 MB/frame at 1080p). The
    polished version caches the buffer."""
    src = (Path(__file__).resolve().parents[2]
           / "python" / "slappyengine" / "lighting.py").read_text(encoding="utf-8")
    assert "_cluster_accum_zero" in src, (
        "lighting regressed: cluster zero-buffer no longer cached"
    )
