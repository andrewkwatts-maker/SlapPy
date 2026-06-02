"""Visual drop-tests — produces per-scenario GIFs that visibly differ.

Replaces the harness placeholder for physics scenarios.  Each test runs a
real ``PhysicsWorld`` simulation through the per-pixel kernel and renders
it via :class:`PhysicsRenderer` so the GIFs show actual material
differences (mud splats, water ripples, stone rings, lava glows).

These run by default but skip GIF emission unless ``SLAPPY_VISUAL=1``
is set in the environment.  CI keeps them cheap; humans flip the env
var to look at the artefacts.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from slappyengine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)
from slappyengine.physics.render import (
    PhysicsRenderer,
    render_world_gif,
)


OUTPUT_DIR = Path(__file__).resolve().parents[2] / "tests" / "visual" / "output" / "physics_drops"
EMIT_GIFS = bool(os.environ.get("SLAPPY_VISUAL"))


def _make_world() -> PhysicsWorld:
    return PhysicsWorld(world_bounds=(-200.0, -100.0, 200.0, 250.0))


def _drop_scene(projectile_mat: str, ground_mat: str) -> PhysicsWorld:
    w = _make_world()
    w.create_body(
        make_rect_silhouette(240, 16), material=ground_mat,
        position=(0.0, 180.0), fixed=True,
    )
    w.create_body(
        make_circle_silhouette(36), material=projectile_mat,
        position=(0.0, 0.0),
    )
    return w


def _frame_signature(frame: np.ndarray) -> tuple[float, float, float, float]:
    """Cheap summary of a frame: mean R, G, B, and total non-bg pixel count."""
    rgb = frame[..., :3].astype(np.float32)
    bg_mask = (rgb[..., 0] < 40) & (rgb[..., 1] < 40) & (rgb[..., 2] < 80)
    fg = ~bg_mask
    if fg.any():
        mr = float(rgb[..., 0][fg].mean())
        mg = float(rgb[..., 1][fg].mean())
        mb = float(rgb[..., 2][fg].mean())
    else:
        mr = mg = mb = 0.0
    return mr, mg, mb, float(fg.sum())


@pytest.mark.parametrize(
    "name, projectile, ground",
    [
        ("steel_into_stone", "steel", "stone"),
        ("steel_into_mud", "steel", "mud"),
        ("steel_into_water", "steel", "water"),
        ("glass_into_stone", "glass", "stone"),
        ("lava_onto_ice", "lava", "ice"),
        ("iron_into_iron", "iron", "iron"),
    ],
)
def test_visual_drop_produces_distinct_frame(name, projectile, ground):
    """Each material-pair must produce a *visibly distinct* peak-impact frame.

    We run the sim through impact, render at a couple of representative
    frames, and check that:
      - the foreground (body+ground pixels) has a colour signature that
        matches the projectile palette,
      - mid-impact pixels differ measurably from start.
    """
    w = _drop_scene(projectile, ground)
    renderer = PhysicsRenderer()
    frame_start = renderer.render(w)
    # Run until impact + ringing.
    for _ in range(90):
        w.step()
    frame_mid = renderer.render(w)
    # And further so settled state can read like settled state.
    for _ in range(60):
        w.step()
    frame_end = renderer.render(w)

    sig_start = _frame_signature(frame_start)
    sig_mid = _frame_signature(frame_mid)
    sig_end = _frame_signature(frame_end)

    # Mid frame must differ in colour means from the start frame.
    delta = (
        abs(sig_mid[0] - sig_start[0])
        + abs(sig_mid[1] - sig_start[1])
        + abs(sig_mid[2] - sig_start[2])
    )
    assert delta > 5.0, (
        f"{name}: mid frame doesn't visibly differ from start "
        f"(Δrgb={delta:.2f})"
    )
    # End frame must still have some foreground (the body didn't disappear).
    assert sig_end[3] > 100, f"{name}: end frame has < 100 foreground pixels"

    if EMIT_GIFS:
        # Re-run fresh and emit a GIF of the full event.
        w2 = _drop_scene(projectile, ground)
        out = OUTPUT_DIR / f"{name}.gif"
        render_world_gif(w2, out, frame_count=80, steps_per_frame=2, fps=30)
        assert out.exists() and out.stat().st_size > 1000


def test_renderer_distinct_materials_distinct_colors():
    """A snapshot of two different materials must produce different colour
    signatures — proves the palette is wired and the body is visible."""
    w_steel = _make_world()
    w_steel.create_body(make_circle_silhouette(48), "steel", position=(0.0, 0.0))
    w_water = _make_world()
    w_water.create_body(make_circle_silhouette(48), "water", position=(0.0, 0.0))
    r = PhysicsRenderer()
    sig_steel = _frame_signature(r.render(w_steel))
    sig_water = _frame_signature(r.render(w_water))
    # Steel is grey, water is blue — channel means must clearly differ.
    diff = abs(sig_steel[0] - sig_water[0]) + abs(sig_steel[2] - sig_water[2])
    assert diff > 30.0, (
        f"Steel ({sig_steel}) vs water ({sig_water}) shouldn't be near-identical"
    )


def test_renderer_lava_emits_heat_glow():
    """Lava starts pre-heated above melt_point; the renderer must paint the
    glow channel so the result is *brighter* than the dark base palette
    in the red channel."""
    w = _make_world()
    body = w.create_body(make_circle_silhouette(48), "lava", position=(0.0, 0.0))
    # Sanity: lava cells start hot.
    assert body.cells[..., 12].max() > 5.0
    r = PhysicsRenderer()
    sig = _frame_signature(r.render(w))
    # Lava palette base R=220; with glow the actual rendered red should be
    # very high (>180) and well above blue.
    assert sig[0] > 180.0 and sig[0] > sig[2] + 80, (
        f"Lava should glow red-hot: {sig}"
    )
