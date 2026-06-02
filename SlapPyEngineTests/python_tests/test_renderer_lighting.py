"""Point-light Lambert shading tests for :class:`PhysicsRenderer`.

These exercise the new ``lights`` / ``ambient_intensity`` /
``enable_normal_map`` / ``normal_curvature_bias`` knobs on
:class:`RenderConfig` and confirm that:

  * legacy renders (lights=[]) are bit-identical to the prior renderer
  * a single light shades the lit side brighter
  * symmetric lights produce symmetric brightness
  * distance attenuation works
  * curvature_bias=0 flattens the shading
  * lava self-emission still survives with no point lights
"""
from __future__ import annotations

import numpy as np

from slappyengine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
)
from slappyengine.physics.render import (
    PhysicsRenderer,
    PointLight,
    RenderConfig,
)


def _world() -> PhysicsWorld:
    return PhysicsWorld(world_bounds=(-200.0, -100.0, 200.0, 250.0))


def _steel_ball_world(position=(0.0, 0.0)) -> PhysicsWorld:
    w = _world()
    w.create_body(make_circle_silhouette(48), "steel", position=position)
    return w


def _body_mask(frame: np.ndarray) -> np.ndarray:
    """A coarse 'this is body, not background' mask: pixels that aren't the
    dark blue gradient.  Background uses R<40, G<40, B<80 — anything
    brighter counts as body."""
    rgb = frame[..., :3].astype(np.int32)
    bg = (rgb[..., 0] < 40) & (rgb[..., 1] < 40) & (rgb[..., 2] < 80)
    return ~bg


def _body_mask_from_legacy(world_factory) -> np.ndarray:
    """Render the same world with the legacy (no-lights) renderer to derive
    a robust body mask for tests where the lit render itself may be dim
    (e.g. ambient=0)."""
    w = world_factory()
    r = PhysicsRenderer()  # default config, lights=[]
    frame = r.render(w)
    return _body_mask(frame)


def _luminance(frame: np.ndarray) -> np.ndarray:
    rgb = frame[..., :3].astype(np.float32)
    return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]


# -------------------------------------------------------------------------
# Backwards-compat: empty lights list = identical output to legacy path
# -------------------------------------------------------------------------

def test_default_render_unchanged_when_no_lights():
    """With an empty ``lights`` list the new code path must NOT touch the
    pixels — the legacy uniform shading is preserved bit-for-bit (we
    allow 1 unit per channel for any float-rounding noise but in practice
    expect 0)."""
    w = _steel_ball_world()
    r_default = PhysicsRenderer()
    r_explicit_no_lights = PhysicsRenderer(
        config=RenderConfig(lights=[], ambient_intensity=0.25, enable_normal_map=True)
    )
    f_default = r_default.render(w)
    # Re-create world so simulation state is the same.
    w2 = _steel_ball_world()
    f_explicit = r_explicit_no_lights.render(w2)
    diff = np.abs(f_default.astype(np.int32) - f_explicit.astype(np.int32))
    assert diff.max() <= 1, f"Lights=[] must match legacy output; max diff={diff.max()}"


# -------------------------------------------------------------------------
# Directional shading: light from -X darkens +X half of the body
# -------------------------------------------------------------------------

def test_single_light_from_left_darkens_right_side():
    w = _steel_ball_world(position=(0.0, 0.0))
    cfg = RenderConfig(
        lights=[PointLight(position=(-200.0, 0.0), color=(255, 255, 255),
                            intensity=2.0, radius=300.0)],
        ambient_intensity=0.1,
        enable_normal_map=True,
        normal_curvature_bias=1.0,
    )
    r = PhysicsRenderer(config=cfg)
    frame = r.render(w)
    mask = _body_mask(frame)
    assert mask.any(), "No body pixels detected — render setup is broken"

    # Find body bounding box in screen space.
    ys, xs = np.where(mask)
    x_mid = (xs.min() + xs.max()) // 2

    lum = _luminance(frame)
    # Pixels on the body, left half vs right half of its bbox.
    left_mask = mask & (np.arange(frame.shape[1])[None, :] <= x_mid)
    right_mask = mask & (np.arange(frame.shape[1])[None, :] > x_mid)
    left_mean = lum[left_mask].mean()
    right_mean = lum[right_mask].mean()
    assert left_mean > right_mean + 5.0, (
        f"Light is on -X; left side should be brighter "
        f"(left={left_mean:.1f}, right={right_mean:.1f})"
    )


# -------------------------------------------------------------------------
# Symmetric lights → symmetric brightness
# -------------------------------------------------------------------------

def test_two_lights_balanced():
    w = _steel_ball_world(position=(0.0, 0.0))
    cfg = RenderConfig(
        lights=[
            PointLight(position=(-200.0, 0.0), color=(255, 255, 255),
                       intensity=1.5, radius=300.0),
            PointLight(position=(200.0, 0.0), color=(255, 255, 255),
                       intensity=1.5, radius=300.0),
        ],
        ambient_intensity=0.1,
        enable_normal_map=True,
        normal_curvature_bias=1.0,
    )
    r = PhysicsRenderer(config=cfg)
    frame = r.render(w)
    # Use a legacy-renderer mask so symmetric-dim cases still find the body.
    mask = _body_mask_from_legacy(lambda: _steel_ball_world(position=(0.0, 0.0)))
    ys, xs = np.where(mask)
    x_mid = (xs.min() + xs.max()) // 2
    lum = _luminance(frame)
    left_mask = mask & (np.arange(frame.shape[1])[None, :] <= x_mid)
    right_mask = mask & (np.arange(frame.shape[1])[None, :] > x_mid)
    left_mean = lum[left_mask].mean()
    right_mean = lum[right_mask].mean()
    assert abs(left_mean - right_mean) < 5.0, (
        f"Two symmetric lights should give symmetric brightness "
        f"(left={left_mean:.2f}, right={right_mean:.2f})"
    )


# -------------------------------------------------------------------------
# Distance attenuation: nearer body is brighter
# -------------------------------------------------------------------------

def test_distance_attenuation():
    # Light is offset in +Y by a small amount so a flat normal still
    # produces a non-zero n·l (otherwise nz·lz would be 0 for in-plane
    # lights and distance wouldn't visibly matter).  We use a curvature
    # bias of 1.0 so the body's implicit curvature picks up the light.
    light = PointLight(position=(0.0, 0.0), color=(255, 255, 255),
                       intensity=3.0, radius=60.0)
    cfg = RenderConfig(
        lights=[light],
        ambient_intensity=0.0,
        enable_normal_map=True,
        normal_curvature_bias=1.0,
    )
    # Same renderer config; just move the body further from the light.
    def make_close():
        ww = _world()
        ww.create_body(make_circle_silhouette(36), "steel", position=(30.0, 0.0))
        return ww

    def make_far():
        ww = _world()
        ww.create_body(make_circle_silhouette(36), "steel", position=(150.0, 0.0))
        return ww

    w_close = make_close()
    w_far = make_far()
    r = PhysicsRenderer(config=cfg)
    f_close = r.render(w_close)
    f_far = r.render(w_far)
    mask_close = _body_mask_from_legacy(make_close)
    mask_far = _body_mask_from_legacy(make_far)
    lum_close = _luminance(f_close)[mask_close].mean()
    lum_far = _luminance(f_far)[mask_far].mean()
    # Closer body must be visibly brighter. Use a ratio bound rather than
    # absolute (luma scales with palette / heat / glow factors that can
    # shift the absolute floor; what matters is the relative falloff).
    assert lum_close > lum_far * 1.5, (
        f"Closer body should be measurably brighter (close={lum_close:.1f}, "
        f"far={lum_far:.1f}, ratio={lum_close/max(lum_far, 1e-3):.2f})"
    )


# -------------------------------------------------------------------------
# curvature_bias = 0 → flat shading
# -------------------------------------------------------------------------

def test_normal_curvature_bias_zero_flat():
    # Light directly above the body so a flat (0,0,1) normal still gives
    # uniform illumination across the body.  We compare luminance std to a
    # curved version (bias=1.0) which must be visibly more varied.
    # Light off to the side (not at the body's centre) so any curvature
    # produces visible spatial variation.
    light_args = dict(position=(-200.0, 0.0), color=(255, 255, 255),
                      intensity=2.0, radius=400.0)
    cfg_flat = RenderConfig(
        lights=[PointLight(**light_args)],
        ambient_intensity=0.2,
        enable_normal_map=True,
        normal_curvature_bias=0.0,
    )
    cfg_curved = RenderConfig(
        lights=[PointLight(**light_args)],
        ambient_intensity=0.2,
        enable_normal_map=True,
        normal_curvature_bias=1.0,
    )
    w_flat = _steel_ball_world(position=(0.0, 0.0))
    w_curved = _steel_ball_world(position=(0.0, 0.0))
    frame_flat = PhysicsRenderer(config=cfg_flat).render(w_flat)
    frame_curved = PhysicsRenderer(config=cfg_curved).render(w_curved)
    mask = _body_mask_from_legacy(lambda: _steel_ball_world(position=(0.0, 0.0)))
    lum_flat = _luminance(frame_flat)[mask]
    lum_curved = _luminance(frame_curved)[mask]
    # Flat shading should have much smaller spatial variation than curved.
    assert lum_flat.std() < lum_curved.std() * 0.8, (
        f"curvature_bias=0 should give flatter shading than bias=1 "
        f"(flat_std={lum_flat.std():.2f}, curved_std={lum_curved.std():.2f})"
    )


# -------------------------------------------------------------------------
# Lava self-emission survives the Lambert path
# -------------------------------------------------------------------------

def test_lit_lava_still_visibly_glows():
    """A lava body with NO point lights must still glow brightly — its
    heat-driven emissive layer is added on top of the (now lit) base, so
    even when ambient_intensity is tiny the glow keeps it red-hot."""
    w = _world()
    body = w.create_body(make_circle_silhouette(48), "lava", position=(0.0, 0.0))
    # Lava starts pre-heated.
    assert body.cells[..., 12].max() > 5.0
    # Tiny ambient + no lights — the test confirms emissives don't get
    # multiplied away by the ambient term.
    cfg = RenderConfig(
        lights=[],  # no lights — only ambient + emissive
        ambient_intensity=0.1,
    )
    r = PhysicsRenderer(config=cfg)
    frame = r.render(w)
    mask = _body_mask(frame)
    assert mask.any(), "Lava body should be visible"
    rgb = frame[..., :3].astype(np.float32)
    mean_r = rgb[..., 0][mask].mean()
    mean_b = rgb[..., 2][mask].mean()
    assert mean_r > 180.0 and mean_r > mean_b + 80.0, (
        f"Lava must still glow red-hot (R={mean_r:.1f}, B={mean_b:.1f})"
    )


def test_lit_lava_with_lights_still_glows():
    """Same as above but WITH point lights enabled — the Lambert path
    must still let emissive bleed through."""
    w = _world()
    w.create_body(make_circle_silhouette(48), "lava", position=(0.0, 0.0))
    cfg = RenderConfig(
        lights=[PointLight(position=(0.0, -100.0), color=(100, 100, 255),
                           intensity=1.0, radius=200.0)],
        ambient_intensity=0.2,
        enable_normal_map=True,
        normal_curvature_bias=0.3,
    )
    r = PhysicsRenderer(config=cfg)
    frame = r.render(w)
    mask = _body_mask(frame)
    rgb = frame[..., :3].astype(np.float32)
    mean_r = rgb[..., 0][mask].mean()
    assert mean_r > 150.0, (
        f"Even with a blue point light, lava emissive should keep R high "
        f"(R={mean_r:.1f})"
    )
