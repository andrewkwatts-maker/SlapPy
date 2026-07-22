"""Tests for :mod:`pharos_engine.physics.shadows`.

These exercise the directional ShadowPass and the crack-aware AOPass in
isolation.  Each test builds a tiny PhysicsWorld, calls a pass's
``render(frame, world)``, and asserts pixel-level relationships against
the input frame.
"""
from __future__ import annotations

import numpy as np
import pytest

from pharos_engine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)
from pharos_engine.physics.shadows import AOPass, ShadowPass


# Default screen / world geometry must match the ShadowPass defaults.
_WORLD_VIEW = (-200.0, -100.0, 200.0, 250.0)
_W = 640
_H = 360


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _blank_frame(rgb: tuple[int, int, int] = (180, 180, 180)) -> np.ndarray:
    """Return a uniform RGBA frame so darkening is easy to detect."""
    f = np.zeros((_H, _W, 4), dtype=np.uint8)
    f[..., 0] = rgb[0]
    f[..., 1] = rgb[1]
    f[..., 2] = rgb[2]
    f[..., 3] = 255
    return f


def _world_to_screen(x: float, y: float) -> tuple[int, int]:
    wx0, wy0, wx1, wy1 = _WORLD_VIEW
    sx = int((x - wx0) / (wx1 - wx0) * _W)
    sy = int((y - wy0) / (wy1 - wy0) * _H)
    return sx, sy


def _build_ball_on_ground_world() -> PhysicsWorld:
    """Single 30 px ball at (0, 0) and a wide ground rect at y=180."""
    world = PhysicsWorld()
    ball = make_circle_silhouette(30)
    world.create_body(
        silhouette=ball,
        material="steel",
        position=(0.0, 0.0),
        velocity=(0.0, 0.0),
    )
    ground = make_rect_silhouette(width=320, height=20)
    world.create_body(
        silhouette=ground,
        material="stone",
        position=(0.0, 180.0),
        velocity=(0.0, 0.0),
        fixed=True,
    )
    return world


def _strip_brightness(
    frame: np.ndarray, cx: int, cy: int, w: int = 8, h: int = 4,
) -> float:
    """Mean RGB brightness in a small rectangle around (cx, cy)."""
    x0 = max(0, cx - w // 2)
    x1 = min(frame.shape[1], cx + w // 2)
    y0 = max(0, cy - h // 2)
    y1 = min(frame.shape[0], cy + h // 2)
    region = frame[y0:y1, x0:x1, :3].astype(np.float32)
    return float(region.mean())


# ---------------------------------------------------------------------------
# ShadowPass
# ---------------------------------------------------------------------------


def test_shadow_appears_below_body_with_default_light() -> None:
    """Cells directly along the +light direction from the ball are darker
    than cells far from the ball on the ground strip."""
    world = _build_ball_on_ground_world()
    frame = _blank_frame()
    sp = ShadowPass(
        light_direction=(0.3, 1.0),
        shadow_length=80.0,
        opacity=0.55,
        softness_px=4.0,
    )
    out = sp.render(frame, world)

    # The light goes (0.3, 1.0): for a ball at (0, 0) the shadow centre
    # on the ground (y=180) sits at x = 0 + 0.3 * 180 = 54.
    sx_below, sy_below = _world_to_screen(54.0, 180.0)
    sx_far, sy_far = _world_to_screen(-180.0, 180.0)

    below = _strip_brightness(out, sx_below, sy_below)
    far = _strip_brightness(out, sx_far, sy_far)

    # Shadow zone should be perceptibly darker than the unshadowed strip.
    assert below < far - 5.0, (
        f"shadowed brightness {below:.1f} not darker than far {far:.1f}"
    )


def test_shadow_length_clamps_extent() -> None:
    """A longer ``shadow_length`` should darken pixels farther along the
    light direction than a shorter shadow.
    """
    world = _build_ball_on_ground_world()
    base = _blank_frame()

    short = ShadowPass(
        light_direction=(0.3, 1.0),
        shadow_length=20.0,
        opacity=0.6,
        softness_px=0.0,
        shadow_samples=8,
    ).render(base, world)
    long_ = ShadowPass(
        light_direction=(0.3, 1.0),
        shadow_length=120.0,
        opacity=0.6,
        softness_px=0.0,
        shadow_samples=8,
    ).render(base, world)

    # Pick a point well past the short shadow's reach (y ~110, x along ray).
    far_x = 0.3 * 110.0
    sx, sy = _world_to_screen(far_x, 110.0)

    short_b = _strip_brightness(short, sx, sy)
    long_b = _strip_brightness(long_, sx, sy)
    assert long_b < short_b - 3.0, (
        f"long shadow brightness {long_b:.1f} not darker than short {short_b:.1f}"
    )


def test_opacity_zero_no_shadow() -> None:
    """``opacity=0`` must return pixels equal to the input frame."""
    world = _build_ball_on_ground_world()
    frame = _blank_frame()
    out = ShadowPass(opacity=0.0).render(frame, world)
    assert np.array_equal(out, frame)


def test_softness_controls_blur() -> None:
    """Larger ``softness_px`` produces a smoother (lower-variance) shadow
    edge than tighter softness.
    """
    world = _build_ball_on_ground_world()
    frame = _blank_frame()

    sharp = ShadowPass(
        light_direction=(0.3, 1.0),
        shadow_length=80.0,
        opacity=0.6,
        softness_px=0.0,
    ).render(frame, world)
    soft = ShadowPass(
        light_direction=(0.3, 1.0),
        shadow_length=80.0,
        opacity=0.6,
        softness_px=12.0,
    ).render(frame, world)

    # Look at a row that straddles the shadow boundary on the ground: a
    # sharp edge produces a large single-pixel jump, while a blurred edge
    # spreads that jump over many smaller steps.  We compare the *max*
    # gradient along the row — blurring should reduce the worst-case step.
    _, sy_row = _world_to_screen(0.0, 180.0)
    sy_row = max(0, min(_H - 1, sy_row))

    sharp_row = sharp[sy_row, :, 0].astype(np.float32)
    soft_row = soft[sy_row, :, 0].astype(np.float32)

    sharp_grad = float(np.abs(np.diff(sharp_row)).max())
    soft_grad = float(np.abs(np.diff(soft_row)).max())
    assert soft_grad < sharp_grad, (
        f"soft gradient {soft_grad:.2f} not less than sharp {sharp_grad:.2f}"
    )


# ---------------------------------------------------------------------------
# AOPass
# ---------------------------------------------------------------------------


def _build_single_block_world() -> PhysicsWorld:
    world = PhysicsWorld()
    rect = make_rect_silhouette(width=80, height=80)
    world.create_body(
        silhouette=rect,
        material="stone",
        position=(0.0, 100.0),
        velocity=(0.0, 0.0),
    )
    return world


def test_ao_darkens_cracked_regions() -> None:
    """Setting bond_e < 0.2 in a sub-rect of a body's cells should make
    that area visibly darker after AOPass than an uncracked area of the
    same body.
    """
    world = _build_single_block_world()
    body = world.bodies[0]
    cells = body.cells
    assert cells is not None
    # Crack a 6x6 block of cells centred-ish in the body.
    cells[10:16, 10:16, 14] = 0.0  # bond_e (channel 14) below threshold
    cells[10:16, 10:16, 15] = 0.0  # bond_s (channel 15) below threshold

    frame = _blank_frame()
    ao = AOPass(radius_px=6.0, intensity=0.5)
    out = ao.render(frame, world)

    # Body extends 80 px in world units centred at (0, 100). The 32-cell
    # grid maps 1 cell == 2.5 world units, so cell (13, 13) lives near
    # world (-7.5, 92.5).  An uncracked region (e.g. cell (28, 28)) sits
    # at world (32.5, 132.5).
    sx_crack, sy_crack = _world_to_screen(-7.5, 92.5)
    sx_clean, sy_clean = _world_to_screen(32.5, 132.5)

    crack_b = _strip_brightness(out, sx_crack, sy_crack)
    clean_b = _strip_brightness(out, sx_clean, sy_clean)
    assert crack_b < clean_b - 5.0, (
        f"cracked area brightness {crack_b:.1f} not darker than clean {clean_b:.1f}"
    )


def test_ao_radius_controls_spread() -> None:
    """A larger ``radius_px`` should darken pixels farther from the cracked
    region than a tighter radius.
    """
    world = _build_single_block_world()
    body = world.bodies[0]
    cells = body.cells
    assert cells is not None
    # Crack a single cell column down the middle of the body.
    cells[10:22, 16, 14] = 0.0
    cells[10:22, 16, 15] = 0.0

    frame = _blank_frame()
    tight = AOPass(radius_px=2.0, intensity=0.6).render(frame, world)
    wide = AOPass(radius_px=12.0, intensity=0.6).render(frame, world)

    # Cell column 16 maps to world x≈0; sample 8 cells (~20 world units)
    # to the side of the crack column.
    sx, sy = _world_to_screen(20.0, 100.0)

    tight_b = _strip_brightness(tight, sx, sy)
    wide_b = _strip_brightness(wide, sx, sy)
    assert wide_b < tight_b - 2.0, (
        f"wide-radius AO brightness {wide_b:.1f} not darker than tight {tight_b:.1f}"
    )


def test_ao_zero_intensity_no_op() -> None:
    """AOPass with intensity=0 returns the input frame unchanged."""
    world = _build_single_block_world()
    body = world.bodies[0]
    cells = body.cells
    assert cells is not None
    cells[5:10, 5:10, 14] = 0.0
    frame = _blank_frame()
    out = AOPass(intensity=0.0).render(frame, world)
    assert np.array_equal(out, frame)
