"""Materials Gallery demo — one ball of every supported material, dropped
simultaneously onto a shared stone ground.

Produces two artefacts under ``examples/output/``:

  * ``physics_materials_gallery.gif`` — 180-frame animation of all balls
    falling and settling on the stone slab in one shot.
  * ``materials_strip.png`` — a single annotated frame (rendered after the
    bodies have settled) with each material's name drawn above its ball,
    suitable for documentation / README inclusion.

The demo is the visual reference for the per-material palette in
``pharos_engine.physics.render``: if you can read all 18+ material names
off the strip *and* visually tell their balls apart, the palette is doing
its job.  See the bottom of this file for the palette overrides we apply
to keep otherwise-grey metals (steel vs iron vs concrete) and the icy
trio (ice / glass / diamond) distinguishable.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

import numpy as np

# Make sure ``python/`` is on sys.path so this script runs from a source
# checkout without a prior ``pip install -e``.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "python"))

from pharos_engine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)
from pharos_engine.physics.render import PhysicsRenderer, RenderConfig
from pharos_engine.deform_modes import list_materials


# ---------------------------------------------------------------------------
# Materials we want to showcase, in left-to-right display order.
# ---------------------------------------------------------------------------

MATERIALS_TO_SHOW: List[str] = [
    "steel", "iron", "stone", "glass", "wood", "rubber",
    "ice", "mud", "water", "sand", "clay", "lava",
    "concrete", "oil", "slime", "diamond", "paper", "snow", "gold",
]

# Scene geometry ------------------------------------------------------------
BALL_DIAMETER = 16
BALL_SPACING_X = 50               # distance between ball centres
BALL_START_Y = -20.0              # spawn just above the visible top
GROUND_W = 1000
GROUND_H = 16
GROUND_X = 0.0
GROUND_Y = 200.0
GROUND_TOP = GROUND_Y - GROUND_H / 2.0

# Render config -------------------------------------------------------------
FRAME_COUNT = 180
RENDER_W = 1024
RENDER_H = 480
WORLD_VIEW = (-500.0, -100.0, 500.0, 250.0)

# Output paths --------------------------------------------------------------
OUT_DIR = _REPO_ROOT / "examples" / "output"
GIF_PATH = OUT_DIR / "physics_materials_gallery.gif"
STRIP_PATH = OUT_DIR / "materials_strip.png"


# ---------------------------------------------------------------------------
# Palette overrides
# ---------------------------------------------------------------------------
#
# The default palette in ``physics.render.DEFAULT_PALETTE`` covers the
# v2 simulator's first 14 materials, but several of the entries we add
# here (concrete / oil / slime / diamond / paper / snow / gold) have no
# defaults — without overrides they all fall back to medium grey and
# become indistinguishable.  We also nudge a few default greys so steel,
# iron, concrete and stone read as visually distinct in the strip.
PALETTE_OVERRIDES: dict[str, tuple[int, int, int]] = {
    # Metals — keep them all in a cool grey family but well-separated in L*.
    "steel":    (190, 200, 215),   # brightest, slight cyan tint
    "iron":     (120, 120, 135),   # dim, neutral grey
    "concrete": ( 95, 100,  95),   # darker, slight green undertone
    "stone":    (140, 130, 115),   # warm tan grey
    # Translucent/icy materials.
    "glass":    (210, 230, 245),
    "ice":      (165, 215, 245),
    "diamond":  (255, 245, 255),   # near-white violet for sparkle
    # New extended-registry materials.
    "oil":      ( 35,  30,  20),   # nearly black with brown tint
    "slime":    ( 90, 220,  80),   # vivid green
    "paper":    (230, 220, 195),   # off-white parchment
    "snow":     (245, 250, 255),   # bright cold white
    "gold":     (235, 195,  60),   # warm yellow-gold
    # Tighten lava away from default so it doesn't blow out next to glass.
    "lava":     (235, 100,  25),
}


# ---------------------------------------------------------------------------
# Scene construction
# ---------------------------------------------------------------------------

def filter_supported(names: list[str]) -> list[str]:
    """Drop any material that the engine's registry doesn't know about."""
    available = set(list_materials())
    kept: list[str] = []
    missing: list[str] = []
    for n in names:
        if n in available:
            kept.append(n)
        else:
            missing.append(n)
    if missing:
        print(f"[gallery] skipping unregistered materials: {missing}")
    return kept


def build_world(materials: list[str]) -> tuple[PhysicsWorld, list]:
    """Create the world + spawn a stone ground and one ball per material.

    Returns ``(world, balls)`` where ``balls`` is a list of ``PhysicsBody``
    handles in the same order as ``materials``.
    """
    world = PhysicsWorld(world_bounds=(-500.0, -100.0, 500.0, 250.0))

    # Stone ground slab — wide enough to catch every ball in the row.
    ground_mask = make_rect_silhouette(GROUND_W, GROUND_H)
    world.create_body(
        silhouette=ground_mask,
        material="stone",
        position=(GROUND_X, GROUND_Y),
        fixed=True,
    )

    # Row of balls, centred around x=0.
    n = len(materials)
    row_width = (n - 1) * BALL_SPACING_X
    x0 = -row_width / 2.0

    balls = []
    ball_mask = make_circle_silhouette(BALL_DIAMETER)
    for i, mat in enumerate(materials):
        x = x0 + i * BALL_SPACING_X
        b = world.create_body(
            silhouette=ball_mask,
            material=mat,
            position=(x, BALL_START_Y),
        )
        balls.append(b)
    return world, balls


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def make_renderer() -> PhysicsRenderer:
    cfg = RenderConfig(
        width=RENDER_W,
        height=RENDER_H,
        world_view=WORLD_VIEW,
    )
    return PhysicsRenderer(config=cfg, palette=PALETTE_OVERRIDES)


def render_strip_png(
    frame_rgba: np.ndarray,
    materials: list[str],
    out_path: Path,
) -> Path:
    """Annotate ``frame_rgba`` with material labels above each ball."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.fromarray(frame_rgba, mode="RGBA").convert("RGBA")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 13)
    except OSError:
        font = ImageFont.load_default()

    n = len(materials)
    row_width = (n - 1) * BALL_SPACING_X
    x0_world = -row_width / 2.0

    wx0, wy0, wx1, wy1 = WORLD_VIEW
    label_y_world = BALL_START_Y - 18  # well above the spawn line

    def world_to_screen(wx: float, wy: float) -> tuple[int, int]:
        sx = (wx - wx0) / (wx1 - wx0) * RENDER_W
        sy = (wy - wy0) / (wy1 - wy0) * RENDER_H
        return int(sx), int(sy)

    for i, mat in enumerate(materials):
        wx = x0_world + i * BALL_SPACING_X
        sx, sy = world_to_screen(wx, label_y_world)
        # Centre the label over the ball.
        try:
            tb = draw.textbbox((0, 0), mat, font=font)
            tw = tb[2] - tb[0]
        except AttributeError:
            tw = len(mat) * 6
        draw.text((sx - tw / 2, sy), mat, fill=(240, 240, 240, 255), font=font)

    # Title at the top.
    title = f"SlapPyEngine — Materials Gallery  ({n} materials)"
    draw.text((10, 6), title, fill=(255, 255, 255, 255), font=font)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def run(
    materials: list[str] | None = None,
    frame_count: int = FRAME_COUNT,
    gif_path: Path = GIF_PATH,
    strip_path: Path = STRIP_PATH,
    strip_frame: int = 120,
) -> dict:
    """Build the scene, simulate ``frame_count`` frames, write the GIF + strip.

    Returns a dict with paths + per-material final positions so callers (the
    tests) can introspect the result without re-running the simulation.
    """
    mats = filter_supported(materials if materials is not None else MATERIALS_TO_SHOW)
    if not mats:
        raise RuntimeError("No supported materials to display — registry empty.")
    world, balls = build_world(mats)
    renderer = make_renderer()

    frames: list[np.ndarray] = []
    strip_frame_rgba: np.ndarray | None = None
    final_positions: list[tuple[float, float]] = []

    for frame_idx in range(frame_count):
        world.step()
        rgba = renderer.render(world)
        frames.append(rgba)
        if frame_idx == strip_frame:
            strip_frame_rgba = rgba.copy()

    if strip_frame_rgba is None:
        strip_frame_rgba = frames[-1].copy()

    for b in balls:
        final_positions.append(b.position)

    gif_path.parent.mkdir(parents=True, exist_ok=True)
    renderer.save_gif(frames, gif_path, fps=30)
    render_strip_png(strip_frame_rgba, mats, strip_path)

    return {
        "materials": mats,
        "gif_path": gif_path,
        "strip_path": strip_path,
        "frames": len(frames),
        "final_positions": final_positions,
        "ground_top": GROUND_TOP,
        "ball_diameter": BALL_DIAMETER,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result = run()
    print(f"[gallery] materials shown: {result['materials']}")
    print(f"[gallery] frames simulated: {result['frames']}")
    print(f"[gallery] GIF   -> {result['gif_path']}")
    print(f"[gallery] strip -> {result['strip_path']}")


if __name__ == "__main__":
    main()
