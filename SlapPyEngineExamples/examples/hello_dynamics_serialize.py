"""SlapPyEngine — Hello Dynamics Serialize

Demo of :func:`slappyengine.dynamics.serialize.save_world` /
:func:`load_world`. A 16-node rope is built, stepped 60 frames, saved
to JSON, then loaded into a second world. Both worlds are stepped
another 60 frames in parallel; the final positions must match within
float tolerance.

Run::

    PYTHONPATH=python python examples/hello_dynamics_serialize.py
    PYTHONPATH=python python examples/hello_dynamics_serialize.py --render
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np

from slappyengine.dynamics import RopeSpec, World, build_rope
from slappyengine.dynamics.serialize import save_world, load_world


def build_world() -> tuple[World, object]:
    w = World(gravity=(0.0, -9.81))
    w.solver_iterations = 8
    spec = RopeSpec(node_count=16, total_length=6.0, mass_per_node=0.05,
                    stiffness=1.0e7, damping=0.01)
    body = build_rope(spec, w, anchor_a=(1.0, 2.0), anchor_b=(5.0, 2.0))
    return w, body


def step(world: World, frames: int, dt: float = 1.0 / 60.0) -> None:
    for _ in range(frames):
        world.step(dt)


def _render(world_a: World, world_b: World, out_path: Path) -> None:
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (1280, 720), (10, 14, 22, 255))
    draw = ImageDraw.Draw(img)
    def world_to_pix(p: np.ndarray) -> tuple[int, int]:
        return (int(80 + p[0] * 200), int(80 + (4.0 - p[1]) * 100))
    for body, color, dashed in [(world_a, (255, 255, 255, 255), False),
                                 (world_b, (255, 60, 60, 255), True)]:
        positions = body.positions
        for i in range(len(positions) - 1):
            if dashed and i % 2:
                continue
            a = world_to_pix(positions[i])
            b = world_to_pix(positions[i + 1])
            draw.line([a, b], fill=color, width=3)
        for p in positions:
            cx, cy = world_to_pix(p)
            draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=color)
    draw.text((20, 20), "WHITE: original  RED dashed: loaded",
              fill=(220, 220, 220, 255))
    img.save(out_path)


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("out/hello_dynamics_serialize.png"))
    args = parser.parse_args(argv)

    world_a, body_a = build_world()
    step(world_a, args.frames)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        save_path = Path(f.name)
    save_world(world_a, save_path)
    on_disk_size = save_path.stat().st_size

    world_b = load_world(save_path)

    step(world_a, args.frames)
    step(world_b, args.frames)

    delta = np.max(np.abs(world_a.positions - world_b.positions))
    midpoint_a = world_a.positions[len(world_a.positions) // 2]
    midpoint_b = world_b.positions[len(world_b.positions) // 2]

    summary = {
        "stepped_frames_per_phase": args.frames,
        "on_disk_size_bytes": int(on_disk_size),
        "midpoint_a": (float(midpoint_a[0]), float(midpoint_a[1])),
        "midpoint_b": (float(midpoint_b[0]), float(midpoint_b[1])),
        "max_position_delta": float(delta),
        "no_nan_a": not bool(np.any(np.isnan(world_a.positions))),
        "no_nan_b": not bool(np.any(np.isnan(world_b.positions))),
    }
    print("hello_dynamics_serialize summary")
    for k, v in summary.items():
        print(f"  {k:24s}: {v}")

    if args.render:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        _render(world_a, world_b, args.out)
        print(f"  rendered                : {args.out}")
    save_path.unlink(missing_ok=True)
    return summary


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) is None)
