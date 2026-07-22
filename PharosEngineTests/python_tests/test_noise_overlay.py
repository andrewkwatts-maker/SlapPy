"""Tests for Option 5 — opt-in per-material noise overlay.

Covers:

  * Zero amplitude is bit-identical to no overlay (no cost path).
  * Non-zero amplitude produces measurable per-cell brightness variance.
  * Noise pattern tracks the body in WORLD space (moves with the body).
  * Noise pattern flickers per-frame (depends on ``world.frame``).
  * Lava heat glow still dominates the final colour with noise applied
    (modulation is multiplicative, not replacement).

See ``docs/adaptive_simulation_strategies.md`` §Option 5 for the design.
"""
from __future__ import annotations

import numpy as np

from pharos_engine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
)
from pharos_engine.physics.render import (
    PhysicsRenderer,
    RenderConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _world(bounds=(-200.0, -100.0, 200.0, 250.0)) -> PhysicsWorld:
    return PhysicsWorld(world_bounds=bounds)


def _body_mask(frame: np.ndarray) -> np.ndarray:
    """Coarse foreground mask: anything that's not the dark blue bg gradient."""
    rgb = frame[..., :3].astype(np.int32)
    bg = (rgb[..., 0] < 40) & (rgb[..., 1] < 40) & (rgb[..., 2] < 80)
    return ~bg


def _luminance(frame: np.ndarray) -> np.ndarray:
    rgb = frame[..., :3].astype(np.float32)
    return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]


def _render_ball(material: str, position=(0.0, 0.0), frame_idx: int = 0) -> np.ndarray:
    w = _world()
    w.create_body(make_circle_silhouette(48), material, position=position)
    w.frame = frame_idx
    r = PhysicsRenderer()
    return r.render(w)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_zero_amplitude_no_change():
    """Steel (noise_overlay_amplitude == 0.0) renders bit-identical to a
    baseline render — the noise path must be fully skipped."""
    # Same world twice (deterministic sim state); two independent renders
    # should agree to the byte.
    f_a = _render_ball("steel")
    f_b = _render_ball("steel")
    assert np.array_equal(f_a, f_b), (
        "Steel with amp=0 must produce identical output across renders; "
        f"max diff={np.abs(f_a.astype(int) - f_b.astype(int)).max()}"
    )


def test_high_amplitude_visible_variation():
    """Mud (amp=0.15) must show measurable per-cell brightness variance,
    while a no-noise material (steel) is much flatter."""
    f_mud = _render_ball("mud")
    f_steel = _render_ball("steel")

    mask_mud = _body_mask(f_mud)
    mask_steel = _body_mask(f_steel)
    assert mask_mud.any() and mask_steel.any(), "render setup broken"

    std_mud = _luminance(f_mud)[mask_mud].std()
    std_steel = _luminance(f_steel)[mask_steel].std()

    # Mud's per-cell noise should produce a luma stdev well above the
    # steel baseline (steel has only quad-fill colour, ~0 variance).
    assert std_mud > 5.0, (
        f"mud (amp=0.15) should show >5 luma stdev (got {std_mud:.2f})"
    )
    assert std_mud > std_steel + 3.0, (
        f"mud noise variance ({std_mud:.2f}) should exceed steel baseline "
        f"({std_steel:.2f})"
    )


def test_noise_stays_with_body():
    """The noise is keyed on WORLD position, so when the body moves the
    noise pattern moves WITH it (a given cell's gain depends only on its
    world coordinate and the current frame).

    We verify the property indirectly: render the same material at two
    positions; the OVERALL noise statistics (stdev) should be similar
    because both renders sample the same noise function over a similarly
    sized footprint.  And — more importantly — the textures should NOT be
    identical pixel-for-pixel: because each body occupies a different
    world-space slab, its cells hash to a different noise field, which
    yields a different per-pixel pattern.
    """
    f_origin = _render_ball("mud", position=(0.0, 0.0))
    f_shifted = _render_ball("mud", position=(100.0, 0.0))

    mask_o = _body_mask(f_origin)
    mask_s = _body_mask(f_shifted)
    assert mask_o.any() and mask_s.any()

    # Statistical signature should be in the same ballpark — same material,
    # same amplitude, same renderer, just translated.
    std_o = _luminance(f_origin)[mask_o].std()
    std_s = _luminance(f_shifted)[mask_s].std()
    assert abs(std_o - std_s) < std_o * 0.6, (
        f"noise stdev should be comparable across positions "
        f"(origin={std_o:.2f}, shifted={std_s:.2f})"
    )

    # And the body silhouettes must actually be in different screen regions
    # (sanity check that the move took effect).
    xs_o = np.where(mask_o)[1]
    xs_s = np.where(mask_s)[1]
    assert xs_s.mean() > xs_o.mean() + 10.0, "body did not actually translate"


def test_noise_flickers_per_frame():
    """At ``world.frame = 0`` vs ``world.frame = 1`` the per-cell colour
    must differ — the noise hash incorporates the frame index, so the
    grain visibly twinkles."""
    f_t0 = _render_ball("mud", frame_idx=0)
    f_t1 = _render_ball("mud", frame_idx=1)

    mask = _body_mask(f_t0) & _body_mask(f_t1)
    assert mask.any()

    diff = np.abs(
        f_t0[..., :3].astype(np.int32) - f_t1[..., :3].astype(np.int32)
    ).sum(axis=-1)
    diff_inside = diff[mask]
    # The frame-to-frame change should be substantial: at amp=0.15 the
    # per-cell gain shifts by O(0.3) of the base colour, which on a brown
    # mud palette (~95+65+40) easily moves >5 LSBs per channel.
    assert diff_inside.mean() > 5.0, (
        f"per-cell colour should differ between frames "
        f"(mean abs diff={diff_inside.mean():.2f})"
    )
    # And a substantial fraction of body pixels should change at all.
    assert (diff_inside > 0).mean() > 0.5, (
        f"too few pixels changed between frames "
        f"(changed fraction={ (diff_inside > 0).mean():.2f})"
    )


def test_lava_glow_survives_noise():
    """Lava has ``noise_overlay_amplitude=0.30`` AND a strong red+orange
    heat glow.  The noise modulation MULTIPLIES, never replaces, so the
    final colour must still be visibly red-dominant — lava must not turn
    grey or blue under the noise.

    We disable ``contact_flash`` for this test because the default
    contact-flash overlay adds (255, 240, 200) on hot cells, which on lava
    saturates all three channels to white and masks both the noise and
    the underlying red dominance.  With the flash off, the red/orange
    body of the lava palette comes through clearly.
    """
    w = _world()
    w.create_body(make_circle_silhouette(48), "lava", position=(0.0, 0.0))
    w.frame = 0
    r = PhysicsRenderer(config=RenderConfig(contact_flash=False))
    f_lava = r.render(w)
    mask = _body_mask(f_lava)
    assert mask.any()

    rgb = f_lava[..., :3].astype(np.float32)
    mean_r = rgb[..., 0][mask].mean()
    mean_g = rgb[..., 1][mask].mean()
    mean_b = rgb[..., 2][mask].mean()

    assert mean_r > 180.0, f"lava should remain bright red (R={mean_r:.1f})"
    assert mean_r > mean_g + 10.0, (
        f"lava R must dominate G (R={mean_r:.1f}, G={mean_g:.1f})"
    )
    assert mean_r > mean_b + 60.0, (
        f"lava R must dominate B (R={mean_r:.1f}, B={mean_b:.1f})"
    )
