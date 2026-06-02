"""SlapPyEngine — Hello IK Chain

Minimal demo of :class:`slappyengine.dynamics.IKChainSpec` + :func:`solve_ik`.

A 5-link kinematic chain (5 nodes wired by distance joints, base pinned at
the origin) tracks a target that orbits an off-centre anchor::

    target.x = 2 + 1.5 * sin(frame / 30)
    target.y = 1 + 1.5 * cos(frame / 30)

For 240 frames the CCD solver is asked to bring the tip onto the target.
We record (frame, target_x, target_y, end_effector_x, end_effector_y,
converged) every step and report convergence statistics on stdout.

Run::

    PYTHONPATH=python python examples/hello_ik_chain.py
    PYTHONPATH=python python examples/hello_ik_chain.py --render
    PYTHONPATH=python python examples/hello_ik_chain.py --frames 240 --render --out out/

No GPU is required — when ``--render`` is supplied the chain is rasterised
to a PNG with pure PIL.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

from slappyengine.dynamics import IKChainSpec, JointSpec, World, solve_ik


# ── Demo parameters ────────────────────────────────────────────────────────
NODE_COUNT: int = 5
LINK_LENGTH: float = 1.0           # each segment is this long
BASE_POSITION: tuple[float, float] = (0.0, 0.0)
MASS_PER_NODE: float = 1.0
STIFFNESS: float = 1.0e7
DAMPING: float = 0.02
SOLVER_ITERATIONS: int = 20
SOLVER_TOLERANCE: float = 0.01
DEFAULT_FRAMES: int = 240

# ── Render parameters ──────────────────────────────────────────────────────
RENDER_W: int = 1280
RENDER_H: int = 720
# View box covers the full reach of the chain (5 units) + the orbit radius.
VIEW_MIN: tuple[float, float] = (-5.0, -5.0)
VIEW_MAX: tuple[float, float] = (5.0, 5.0)


# ────────────────────────────────────────────────────────────────────────────
# Target trajectory
# ────────────────────────────────────────────────────────────────────────────

def target_at(frame: int) -> tuple[float, float]:
    """Animated target position for the given frame index."""
    return (
        2.0 + 1.5 * math.sin(frame / 30.0),
        1.0 + 1.5 * math.cos(frame / 30.0),
    )


# ────────────────────────────────────────────────────────────────────────────
# World / chain construction
# ────────────────────────────────────────────────────────────────────────────

def build_world() -> tuple[World, IKChainSpec]:
    """Construct the world + 5-link chain used by every code path in this demo.

    Nodes are laid out along +x at 1.0 unit spacing. The base node (index 0)
    is pinned (``mass = 0``); every other node carries ``MASS_PER_NODE``.
    Distance joints glue consecutive nodes so the chain has fixed segment
    lengths even when the solver isn't running ``solve_ik``.
    """
    world = World(gravity=(0.0, 0.0))     # IK is pure kinematic; no gravity
    world.solver_iterations = 8

    node_indices: list[int] = []
    for i in range(NODE_COUNT):
        pos = (BASE_POSITION[0] + i * LINK_LENGTH, BASE_POSITION[1])
        mass = 0.0 if i == 0 else MASS_PER_NODE
        node_indices.append(world.add_node(pos, mass=mass))

    for i in range(NODE_COUNT - 1):
        world.add_joint(
            JointSpec(
                kind="distance",
                node_a=node_indices[i],
                node_b=node_indices[i + 1],
                rest_length=LINK_LENGTH,
                stiffness=STIFFNESS,
                damping=DAMPING,
            )
        )

    spec = IKChainSpec(
        node_indices=list(node_indices),
        target=target_at(0),
        fixed_root=True,
    )
    return world, spec


def run_frames(world: World, spec: IKChainSpec, frames: int) -> list[tuple]:
    """Step the IK demo for *frames* frames; return per-frame records.

    Each record is ``(frame, target_x, target_y, tip_x, tip_y, converged)``.
    """
    records: list[tuple] = []
    tip_idx = spec.node_indices[-1]
    for frame in range(frames):
        tx, ty = target_at(frame)
        spec.target = (tx, ty)
        converged = solve_ik(
            spec, world,
            iterations=SOLVER_ITERATIONS,
            tolerance=SOLVER_TOLERANCE,
        )
        tip = world.positions[tip_idx]
        records.append((
            frame,
            float(tx), float(ty),
            float(tip[0]), float(tip[1]),
            bool(converged),
        ))
    return records


# ────────────────────────────────────────────────────────────────────────────
# Pure-PIL renderer (no GPU dependency)
# ────────────────────────────────────────────────────────────────────────────

def _world_to_pixel(p) -> tuple[int, int]:
    """Map a (x, y) point in world space to integer pixel coordinates."""
    vx0, vy0 = VIEW_MIN
    vx1, vy1 = VIEW_MAX
    px_w = float(p[0])
    px_y = float(p[1])
    u = (px_w - vx0) / (vx1 - vx0)
    v = (px_y - vy0) / (vy1 - vy0)
    px = int(round(u * (RENDER_W - 1)))
    py = int(round((1.0 - v) * (RENDER_H - 1)))
    return px, py


def _render_frame(world: World, spec: IKChainSpec) -> np.ndarray:
    """Rasterise the chain to an (H, W, 4) uint8 RGBA numpy array.

    * Black background.
    * Chain: white line segments between consecutive nodes.
    * Nodes: small white circles; the base (pinned) gets a slightly larger
      marker and the end-effector gets a larger circle so the eye can pick
      the tip out of the chain.
    * Target: a red cross.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (RENDER_W, RENDER_H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)

    nodes = list(spec.node_indices)
    positions = world.positions

    # Chain segments.
    for i in range(len(nodes) - 1):
        a = _world_to_pixel(positions[nodes[i]])
        b = _world_to_pixel(positions[nodes[i + 1]])
        draw.line([a, b], fill=(255, 255, 255, 255), width=3)

    # Node dots.
    node_r = 4
    base_r = 7
    tip_r = 10
    for i, ni in enumerate(nodes):
        x, y = _world_to_pixel(positions[ni])
        if i == 0:
            r = base_r
        elif i == len(nodes) - 1:
            r = tip_r
        else:
            r = node_r
        draw.ellipse(
            [(x - r, y - r), (x + r, y + r)],
            fill=(255, 255, 255, 255),
            outline=(255, 255, 255, 255),
        )

    # Target — red cross.
    tx, ty = _world_to_pixel(np.asarray(spec.target, dtype=np.float64))
    cross_r = 12
    cross_w = 3
    draw.line(
        [(tx - cross_r, ty), (tx + cross_r, ty)],
        fill=(255, 32, 32, 255), width=cross_w,
    )
    draw.line(
        [(tx, ty - cross_r), (tx, ty + cross_r)],
        fill=(255, 32, 32, 255), width=cross_w,
    )

    return np.asarray(img, dtype=np.uint8)


def save_render(world: World, spec: IKChainSpec, out_path: Path) -> Path:
    """Write the rendered frame to ``out_path``. Creates parent dirs."""
    from PIL import Image

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arr = _render_frame(world, spec)
    Image.fromarray(arr, mode="RGBA").save(out_path)
    return out_path


# ────────────────────────────────────────────────────────────────────────────
# Diagnostics
# ────────────────────────────────────────────────────────────────────────────

def summarise(records: list[tuple]) -> dict:
    arr = np.asarray(
        [(r[1], r[2], r[3], r[4]) for r in records], dtype=np.float64,
    )
    converged_flags = np.asarray([r[5] for r in records], dtype=bool)
    if arr.size:
        target = arr[:, :2]
        tip = arr[:, 2:]
        dist = np.linalg.norm(tip - target, axis=1)
    else:
        dist = np.zeros((0,), dtype=np.float64)

    if converged_flags.any():
        max_dist_converged = float(dist[converged_flags].max())
    else:
        max_dist_converged = float("nan")

    return {
        "frames": len(records),
        "frames_converged": int(converged_flags.sum()),
        "convergence_rate": (
            float(converged_flags.mean()) if records else 0.0
        ),
        "max_tip_to_target": float(dist.max()) if dist.size else 0.0,
        "max_tip_to_target_converged": max_dist_converged,
    }


def print_summary(summary: dict) -> None:
    print("hello_ik_chain summary")
    print(f"  frames                          : {summary['frames']}")
    print(f"  frames converged                : {summary['frames_converged']}")
    print(f"  convergence rate                : {summary['convergence_rate']:.4f}")
    print(f"  max tip-to-target distance      : {summary['max_tip_to_target']:.4f}")
    print(
        "  max tip-to-target (converged)   : "
        f"{summary['max_tip_to_target_converged']:.4f}"
    )


# ────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ────────────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Hello IK Chain — SlapPyEngine demo",
    )
    parser.add_argument(
        "--frames", type=int, default=DEFAULT_FRAMES,
        help=f"number of IK frames to integrate (default: {DEFAULT_FRAMES})",
    )
    parser.add_argument(
        "--render", action="store_true",
        help="rasterise the final frame to a PNG (pure PIL, no GPU)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("out/hello_ik_chain.png"),
        help="output PNG path when --render is supplied",
    )
    return parser.parse_args(argv)


def main(
    frames: int = DEFAULT_FRAMES,
    render: bool = False,
    out: Path | str = Path("out/hello_ik_chain.png"),
) -> dict:
    """Run the demo and return the summary dict.

    Exposed as a regular function so tests can drive it without a subprocess.
    """
    world, spec = build_world()
    records = run_frames(world, spec, frames)
    summary = summarise(records)
    summary["records"] = records
    print_summary(summary)

    if render:
        out_path = save_render(world, spec, Path(out))
        print(f"  rendered to                     : {out_path}")
    return summary


def _cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        main(frames=args.frames, render=args.render, out=args.out)
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"hello_ik_chain: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
