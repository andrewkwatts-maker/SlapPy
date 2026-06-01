"""Humanoid IK-to-terrain — feet plant on a sinewave ground.

The humanoid skeleton is repositioned each frame so its feet sit on an
undulating terrain. :func:`slappyengine.dynamics.place_feet_on_terrain`
shifts the pelvis vertically so the lower foot rests on the ground
beneath it, then runs 2-bone IK on each leg to plant the ankles on the
surface. The character "walks" sideways across the terrain so both feet
trace the height profile.

Showcase: ``humanoid_stage()`` + ``terrain_overlay()`` factory + a
per-frame ``post_step`` callback that re-IKs the pose. Total demo body
~30 lines vs ~80 of boilerplate.

Solver tuning: ``SoftBodyWorld`` defaults ``iters=4``; ``make_humanoid``
defaults ``bone_damping=0.05`` → ``iters * damping == 0.20``, sitting
under the documented over-damp threshold (``0.3``) so no
``RuntimeWarning`` ever fires.

Run::

    PYTHONPATH=python python examples/humanoid_ik_terrain_demo.py
    PYTHONPATH=python python examples/humanoid_ik_terrain_demo.py --frames 60
    PYTHONPATH=python python examples/humanoid_ik_terrain_demo.py --no-gif

Output:
    examples/output/humanoid/humanoid_ik_terrain.gif
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from slappyengine.dynamics import make_humanoid, place_feet_on_terrain
from slappyengine.studio import (
    Stage, humanoid_stage, output_path, record, terrain_overlay,
)


DEFAULT_FRAMES: int = 180
PELVIS_HEIGHT_ABOVE_TERRAIN: float = 0.9
SOLVER_ITERS_DEFAULT: int = 4
BONE_DAMPING_DEFAULT: float = 0.05  # 4 * 0.05 == 0.20 (< 0.30 threshold)


def terrain_fn(x: float) -> float:
    """Smooth undulating ground. Positive y = down (engine convention)."""
    return 3.5 + 0.35 * math.sin(x * 1.2) - 0.18 * math.cos(x * 2.1)


def _build_stage_and_skeleton(frames: int):
    """Set up the humanoid stage + 13-bone skeleton used by every path."""
    stage = humanoid_stage(view_box=(-3.5, -0.5, 3.5, 4.5),
                            width=480, height=320)
    iters = int(stage.world.config.get("iters", SOLVER_ITERS_DEFAULT))
    assert iters * BONE_DAMPING_DEFAULT <= 0.30, (
        f"solver tuning regressed: iters={iters} * damping="
        f"{BONE_DAMPING_DEFAULT} > 0.30 over-damp threshold"
    )
    skel = make_humanoid(stage.world, root_position=(-2.5, 1.0))

    def walk(s: Stage, f: int) -> None:
        # Slide the character across the terrain.
        x = -2.5 + 5.0 * (f / max(frames - 1, 1))
        cur_x = float(s.world.nodes.pos[skel.pelvis, 0])
        ns, ne = skel.node_slice
        s.world.nodes.pos[ns:ne, 0] += x - cur_x
        place_feet_on_terrain(s.world, skel, terrain_fn,
                               pelvis_height_above_terrain=PELVIS_HEIGHT_ABOVE_TERRAIN)

    return stage, skel, walk


def main(frames: int = DEFAULT_FRAMES, capture_gif: bool = True,
         out: Path | str | None = None) -> dict:
    """Run the demo. Returns a summary dict for smoke tests."""
    stage, skel, walk = _build_stage_and_skeleton(frames)

    if capture_gif:
        out_path = Path(out) if out is not None else output_path(
            "humanoid_ik_terrain", __file__, subdir="humanoid",
        )
        record(stage, frames=frames, output=out_path,
               step_world=False, post_step=walk,
               overlay=terrain_overlay(terrain_fn))
        print(f"wrote {out_path}")
        gif_path: str | None = str(out_path)
    else:
        # Smoke-test path: step the IK loop without rendering / saving.
        for f in range(frames):
            walk(stage, f)
        gif_path = None

    ankle_l_y = float(stage.world.nodes.pos[skel.ankle_l, 1])
    ankle_r_y = float(stage.world.nodes.pos[skel.ankle_r, 1])
    return {
        "frames": frames,
        "ankle_l_y": ankle_l_y,
        "ankle_r_y": ankle_r_y,
        "gif_path": gif_path,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Humanoid IK-to-terrain — SlapPyEngine demo",
    )
    parser.add_argument(
        "--frames", type=int, default=DEFAULT_FRAMES,
        help=f"number of frames to walk across the terrain (default: {DEFAULT_FRAMES})",
    )
    parser.add_argument(
        "--no-gif", action="store_true",
        help="skip GIF capture (smoke-test mode; pairs well with --frames 60)",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="GIF output path (default: examples/output/humanoid/humanoid_ik_terrain.gif)",
    )
    return parser.parse_args(argv)


def _cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        main(frames=args.frames, capture_gif=not args.no_gif, out=args.out)
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"humanoid_ik_terrain_demo: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
