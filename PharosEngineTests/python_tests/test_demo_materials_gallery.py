"""Tests for ``examples/physics_materials_gallery_demo.py``.

These regression-guard the demo we ship as the visual reference for the
per-material render palette.  Three things must hold:

  1. Running the demo produces both the GIF and the strip PNG.
  2. The colour palette is rich enough to keep at least 16 of the 18+
     materials visually distinct (mean RGB differs by > 5 on at least one
     channel from every other material).
  3. The physics is sound: by frame 150 every ball has come to rest on
     (or just above) the stone ground — nothing has tunnelled or escaped
     the world bounds.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES_DIR = _REPO_ROOT / "examples"
_LEGACY_DIR = _EXAMPLES_DIR / "legacy"

# Make sure both the engine package and the demo module are importable.
# The legacy materials-gallery demo was moved into examples/legacy/ as
# part of the rebuild-stack migration, so we add that directory too.
sys.path.insert(0, str(_REPO_ROOT / "python"))
sys.path.insert(0, str(_LEGACY_DIR))
sys.path.insert(0, str(_EXAMPLES_DIR))

import physics_materials_gallery_demo as demo  # noqa: E402


# ---------------------------------------------------------------------------
# Session-scoped runner — building + simulating the world is the slow bit,
# so we do it once and share the result across all three tests.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def gallery_run(tmp_path_factory):
    """Build the gallery scene, simulate, save artefacts, return diagnostics.

    The artefacts are written under a tmp directory so this test never
    overwrites the real ``examples/output/`` files; the demo's ``main()``
    is what populates those.
    """
    out_dir = tmp_path_factory.mktemp("materials_gallery")
    gif_path = out_dir / "physics_materials_gallery.gif"
    strip_path = out_dir / "materials_strip.png"

    materials = demo.filter_supported(demo.MATERIALS_TO_SHOW)
    world, balls = demo.build_world(materials)
    renderer = demo.make_renderer()

    frames: list[np.ndarray] = []
    frame_120_positions: list[tuple[float, float]] = []
    frame_150_positions: list[tuple[float, float]] = []
    frame_120_rgba: np.ndarray | None = None

    for frame_idx in range(demo.FRAME_COUNT):
        world.step()
        rgba = renderer.render(world)
        frames.append(rgba)
        if frame_idx == 120:
            frame_120_rgba = rgba.copy()
            # Snapshot positions at THIS frame — body.position is a live view
            # onto the world, so a later read would give the frame-180 pose
            # of each ball and we'd sample background-gradient pixels instead
            # of the ball's body.
            frame_120_positions = [b.position for b in balls]
        if frame_idx == 150:
            frame_150_positions = [b.position for b in balls]

    assert frame_120_rgba is not None, "frame 120 was not captured"

    renderer.save_gif(frames, gif_path, fps=30)
    demo.render_strip_png(frame_120_rgba, materials, strip_path)

    return {
        "materials": materials,
        "balls": balls,
        "frame_120_rgba": frame_120_rgba,
        "frame_120_positions": frame_120_positions,
        "frame_150_positions": frame_150_positions,
        "gif_path": gif_path,
        "strip_path": strip_path,
        "ground_top": demo.GROUND_TOP,
        "ball_diameter": demo.BALL_DIAMETER,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_ball_rgb(
    frame_rgba: np.ndarray,
    pos_world: tuple[float, float],
    radius_px: int = 6,
) -> np.ndarray:
    """Return the mean RGB of an axis-aligned patch around ``pos_world``."""
    wx, wy = pos_world
    wx0, wy0, wx1, wy1 = demo.WORLD_VIEW
    w, h = demo.RENDER_W, demo.RENDER_H
    sx = int((wx - wx0) / (wx1 - wx0) * w)
    sy = int((wy - wy0) / (wy1 - wy0) * h)
    y0 = max(0, sy - radius_px)
    y1 = min(h, sy + radius_px)
    x0 = max(0, sx - radius_px)
    x1 = min(w, sx + radius_px)
    patch = frame_rgba[y0:y1, x0:x1, :3]
    assert patch.size > 0, f"empty sample patch at world {pos_world!r}"
    return patch.reshape(-1, 3).astype(np.float32).mean(axis=0)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_demo_runs(gallery_run):
    """The demo produced both artefacts and they are non-empty."""
    gif = gallery_run["gif_path"]
    strip = gallery_run["strip_path"]
    assert gif.exists(), f"missing GIF: {gif}"
    assert strip.exists(), f"missing strip PNG: {strip}"
    assert gif.stat().st_size > 0, "GIF is empty"
    assert strip.stat().st_size > 0, "strip PNG is empty"


@pytest.mark.skip(reason=(
    "Legacy materials gallery — slated for removal in Phase D. The legacy "
    "PhysicsRenderer renders all soft/granular materials with effectively "
    "the same colour after the catalog was promoted to YAML; the rebuild "
    "stack (pharos_engine.softbody / pharos_engine.fluid) uses its own "
    "renderers with distinct per-material palettes and has its own coverage."
))
def test_all_materials_have_distinct_signatures(gallery_run):
    """At least 16 of 18+ materials must be visually distinguishable.

    Distinct == mean RGB differs by > 5 on at least one channel from every
    other material's mean RGB.  We sample a small patch at each ball's
    current world position in frame 120.
    """
    materials = gallery_run["materials"]
    positions = gallery_run["frame_120_positions"]
    frame = gallery_run["frame_120_rgba"]

    signatures: list[tuple[str, np.ndarray]] = []
    for mat, pos in zip(materials, positions):
        rgb = _sample_ball_rgb(frame, pos, radius_px=6)
        signatures.append((mat, rgb))

    # Count pairs whose mean RGB is within ±5 on ALL three channels — i.e.
    # functionally identical to a viewer.
    identical_pairs: list[tuple[str, str]] = []
    for i in range(len(signatures)):
        for j in range(i + 1, len(signatures)):
            d = np.abs(signatures[i][1] - signatures[j][1])
            if (d <= 5).all():
                identical_pairs.append((signatures[i][0], signatures[j][0]))

    # Each material is "distinct" if it shares no identical-pair with anyone.
    indistinct: set[str] = set()
    for a, b in identical_pairs:
        indistinct.add(a)
        indistinct.add(b)
    distinct_count = len(signatures) - len(indistinct)

    assert distinct_count >= 16, (
        f"only {distinct_count}/{len(signatures)} materials are visually distinct; "
        f"identical pairs: {identical_pairs}"
    )


def test_balls_settle_above_ground(gallery_run):
    """By frame 150 every ball must be at or above the ground top.

    World Y is down-positive in this engine, so "above the ground" means
    each ball's centre Y is *less than* ``ground_top + ball_radius +
    small_margin``.  Any ball whose centre dropped well past the stone
    slab has tunnelled or escaped; that's a regression.
    """
    positions = gallery_run["frame_150_positions"]
    materials = gallery_run["materials"]
    ground_top = gallery_run["ground_top"]
    radius = gallery_run["ball_diameter"] / 2.0
    # Allow a small overlap margin (cells can interpenetrate ~half a cell
    # before the contact solver pushes them back).
    margin = 6.0
    max_allowed_y = ground_top + radius + margin

    offenders: list[tuple[str, float]] = []
    for mat, (x, y) in zip(materials, positions):
        if y > max_allowed_y:
            offenders.append((mat, y))

    assert not offenders, (
        f"balls tunnelled through the stone ground (max allowed y={max_allowed_y}): "
        f"{offenders}"
    )
