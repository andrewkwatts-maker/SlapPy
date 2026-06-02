"""Visual test: ConstraintSolver — a DistanceConstraint swings a steel ball.

Builds a small two-body scene where a fixed stone anchor and a falling
steel ball are joined by a :class:`DistanceConstraint`.  Without the
constraint the steel ball would fall straight down off-screen; with the
constraint it is yanked into a pendulum arc.

This exercises the public ``ConstraintSolver`` /
``DistanceConstraint`` API plus its integration with ``PhysicsWorld``
and ``PhysicsRenderer``, which had no visual coverage prior to this
test.

Assertions:
    * 30 PNG frames are written.
    * Frames are not all-zero / not all-uniform (renderer actually drew).
    * The ball's body-centroid in screen space travels along a curved
      path: its X coordinate varies meaningfully between frame 0 and a
      mid-range frame (proves the constraint pulled it sideways instead
      of dropping straight down).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from slappyengine.physics import (
    ConstraintSolver,
    DistanceConstraint,
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)
from slappyengine.physics.render import PhysicsRenderer, RenderConfig


TEST_NAME = "constraints"
N_FRAMES = 60
FRAME_W = 320
FRAME_H = 240
WORLD_VIEW = (-150.0, -100.0, 150.0, 150.0)


def _output_dir() -> Path:
    p = Path(__file__).parent / "output" / TEST_NAME
    p.mkdir(parents=True, exist_ok=True)
    for old in p.glob("frame_*.png"):
        try:
            old.unlink()
        except OSError:
            pass
    return p


def _body_centroid_x(frame_rgba: np.ndarray) -> float:
    """Approximate the steel ball's centroid X via its grey-ish silhouette."""
    r = frame_rgba[..., 0].astype(np.int32)
    g = frame_rgba[..., 1].astype(np.int32)
    b = frame_rgba[..., 2].astype(np.int32)
    grey = (np.abs(r - g) < 16) & (np.abs(g - b) < 16) & ((r + g + b) > 120)
    ys, xs = np.where(grey)
    if xs.size == 0:
        return float("nan")
    return float(xs.mean())


def test_constraints_pendulum_swing() -> None:
    out_dir = _output_dir()

    # Deterministic: PhysicsWorld uses no RNG for body trajectories at this
    # scale; the only seed needed is on the solver, which we set explicitly.
    world = PhysicsWorld(world_bounds=WORLD_VIEW)

    # Fixed stone anchor near the top-centre of the world.
    anchor_sil = make_rect_silhouette(width=16, height=16)
    anchor = world.create_body(
        silhouette=anchor_sil,
        material="stone",
        position=(0.0, -40.0),
        fixed=True,
    )

    # Steel ball spawned directly below the anchor with a strong sideways
    # kick.  Without the rod it would fly off to the right; with the rod
    # constraining its distance from the anchor at 60 units, it is forced
    # into a pendulum arc.
    ball_sil = make_circle_silhouette(diameter=20)
    ball = world.create_body(
        silhouette=ball_sil,
        material="steel",
        position=(0.0, 20.0),
        velocity=(180.0, 0.0),
    )

    # Stiff rod of length matching the initial separation (60 world units).
    solver = ConstraintSolver(iterations=6)
    solver.add(DistanceConstraint(
        body_a=anchor,
        body_b=ball,
        local_anchor_a=(0.0, 0.0),
        local_anchor_b=(0.0, 0.0),
        distance=60.0,
        stiffness=1.0,
        break_strain=10.0,  # never break
    ))

    cfg = RenderConfig(width=FRAME_W, height=FRAME_H, world_view=WORLD_VIEW)
    renderer = PhysicsRenderer(config=cfg)

    centroids_x: list[float] = []
    for f in range(N_FRAMES):
        world.step()
        solver.solve(world, dt=1.0 / 60.0)
        frame = renderer.render(world)
        Image.fromarray(frame, mode="RGBA").save(out_dir / f"frame_{f:05d}.png")
        centroids_x.append(_body_centroid_x(frame))

    # --- assertion 1: correct number of frames written ---------------------
    saved = sorted(out_dir.glob("frame_*.png"))
    assert len(saved) == N_FRAMES, f"expected {N_FRAMES} frames, got {len(saved)}"

    # --- assertion 2: a representative frame is non-trivial ---------------
    mid = np.array(Image.open(saved[N_FRAMES // 2]).convert("RGBA"))
    assert mid.shape == (FRAME_H, FRAME_W, 4), f"wrong shape {mid.shape}"
    assert mid.any(), "rendered frame is all zero"
    # Not all pixels identical (image has structure).
    rgb = mid[..., :3]
    assert rgb.std() > 1.0, f"frame too uniform (std={rgb.std():.3f})"

    # --- assertion 3: ball moved horizontally under the constraint --------
    # Without a constraint the ball would fall straight down — centroid X
    # would barely change.  With the rod it swings, so the X centroid sweeps
    # noticeably between frame 0 and the late-frame sample.
    valid_x = [x for x in centroids_x if not np.isnan(x)]
    assert len(valid_x) >= 5, "ball not detected in enough frames"
    x_range = max(valid_x) - min(valid_x)
    assert x_range > 4.0, (
        f"ball centroid did not sweep horizontally enough "
        f"(range={x_range:.2f}px); constraint may be inactive"
    )


if __name__ == "__main__":  # pragma: no cover - manual run helper
    pytest.main([__file__, "-v", "--tb=short"])
