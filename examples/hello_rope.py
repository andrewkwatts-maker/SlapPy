"""SlapPyEngine — Hello Rope

Minimal demo of :class:`slappyengine.dynamics.RopeSpec`.

A 24-node rope is hung between two pinned anchors 4.0 units apart at
``y = 2.0``. The rope is given ``total_length = 6.0`` (50% slack) so it
droops into a catenary curve under gravity. The world is stepped for
120 frames at ``dt = 1/60`` and the final state is summarised on stdout.

Run::

    PYTHONPATH=python python examples/hello_rope.py
    PYTHONPATH=python python examples/hello_rope.py --render
    PYTHONPATH=python python examples/hello_rope.py --frames 240 --render --out out/

No GPU is required — when ``--render`` is supplied the rope is rasterised
to a PNG with pure PIL.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from slappyengine.dynamics import RopeSpec, World, build_rope


# ── Demo parameters ────────────────────────────────────────────────────────
NODE_COUNT: int = 24
TOTAL_LENGTH: float = 6.0       # rope length (slack: span = 4.0)
SPAN: float = 4.0               # horizontal distance between anchors
ANCHOR_Y: float = 2.0           # both anchors at this height
MASS_PER_NODE: float = 0.05
STIFFNESS: float = 2.0e6
DAMPING: float = 0.08
GRAVITY: tuple[float, float] = (0.0, -9.81)
DEFAULT_DT: float = 1.0 / 60.0
DEFAULT_FRAMES: int = 120

# ── Render parameters ──────────────────────────────────────────────────────
RENDER_W: int = 1280
RENDER_H: int = 720
# World-space view box for the renderer: y goes from a bit above the anchors
# down past the expected catenary low-point.
VIEW_MIN: tuple[float, float] = (-3.0, -3.0)
VIEW_MAX: tuple[float, float] = (3.0, 3.0)


# ────────────────────────────────────────────────────────────────────────────
# Simulation helpers
# ────────────────────────────────────────────────────────────────────────────

def build_world() -> tuple[World, "object"]:
    """Construct the world + rope used by every code path in this demo."""
    world = World(gravity=GRAVITY)
    world.solver_iterations = 16  # tight enough that segments don't visibly stretch
    spec = RopeSpec(
        node_count=NODE_COUNT,
        total_length=TOTAL_LENGTH,
        mass_per_node=MASS_PER_NODE,
        stiffness=STIFFNESS,
        damping=DAMPING,
        anchor_a_pinned=True,
        anchor_b_pinned=True,
    )
    anchor_a = (-SPAN / 2.0, ANCHOR_Y)
    anchor_b = (+SPAN / 2.0, ANCHOR_Y)
    body = build_rope(spec, world, anchor_a=anchor_a, anchor_b=anchor_b)
    return world, body


def step_world(world: World, frames: int, dt: float = DEFAULT_DT) -> None:
    for _ in range(frames):
        world.step(dt)


# ────────────────────────────────────────────────────────────────────────────
# Pure-PIL renderer (no GPU dependency)
# ────────────────────────────────────────────────────────────────────────────

def _world_to_pixel(p: np.ndarray) -> tuple[int, int]:
    """Map a (x, y) point in world space to integer pixel coordinates."""
    vx0, vy0 = VIEW_MIN
    vx1, vy1 = VIEW_MAX
    u = (float(p[0]) - vx0) / (vx1 - vx0)
    v = (float(p[1]) - vy0) / (vy1 - vy0)
    px = int(round(u * (RENDER_W - 1)))
    # Image space y grows downward; world y grows upward.
    py = int(round((1.0 - v) * (RENDER_H - 1)))
    return px, py


def _render_frame(world: World) -> np.ndarray:
    """Rasterise the rope to an (H, W, 4) uint8 RGBA numpy array.

    Black background, thin white line segments between bonded nodes, white
    circles at each node. Anchors (pinned, ``inv_mass == 0``) get a slightly
    larger marker so the eye can pick them out.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (RENDER_W, RENDER_H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)

    positions = world.positions
    inv_masses = world.inv_masses

    # Lines between consecutive nodes (distance joints in the rope).
    n = positions.shape[0]
    for i in range(n - 1):
        a = _world_to_pixel(positions[i])
        b = _world_to_pixel(positions[i + 1])
        draw.line([a, b], fill=(255, 255, 255, 255), width=2)

    # Node dots.
    node_r = 3
    anchor_r = 6
    for i in range(n):
        x, y = _world_to_pixel(positions[i])
        r = anchor_r if inv_masses[i] == 0.0 else node_r
        draw.ellipse(
            [(x - r, y - r), (x + r, y + r)],
            fill=(255, 255, 255, 255),
            outline=(255, 255, 255, 255),
        )

    return np.asarray(img, dtype=np.uint8)


def save_render(world: World, out_path: Path) -> Path:
    """Write the rendered frame to ``out_path``. Creates parent dirs."""
    from PIL import Image

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arr = _render_frame(world)
    Image.fromarray(arr, mode="RGBA").save(out_path)
    return out_path


# ────────────────────────────────────────────────────────────────────────────
# Diagnostics
# ────────────────────────────────────────────────────────────────────────────

def summarise(world: World, body, frames: int) -> dict:
    nodes = list(body.node_indices)
    mid = nodes[len(nodes) // 2]
    y_mid = float(world.positions[mid, 1])
    total_mass = float(NODE_COUNT * MASS_PER_NODE)
    droop = ANCHOR_Y - y_mid

    # Expected catenary droop range: for a flexible rope with length L hung
    # between same-height anchors of span s, the sag is bounded between
    # ~(L - s) / 2 (loose lower bound) and ~L / 2 (a perfectly limp chain).
    expected_lo = max(0.0, (TOTAL_LENGTH - SPAN) * 0.5)
    expected_hi = TOTAL_LENGTH * 0.5
    return {
        "frames": frames,
        "nodes": NODE_COUNT,
        "total_mass": total_mass,
        "anchor_y": ANCHOR_Y,
        "midpoint_y": y_mid,
        "droop": droop,
        "expected_lo": expected_lo,
        "expected_hi": expected_hi,
    }


def print_summary(summary: dict) -> None:
    print("hello_rope summary")
    print(f"  nodes               : {summary['nodes']}")
    print(f"  total mass          : {summary['total_mass']:.4f}")
    print(f"  anchor y            : {summary['anchor_y']:.4f}")
    print(f"  midpoint y          : {summary['midpoint_y']:.4f}")
    print(f"  droop (anchor - mid): {summary['droop']:.4f}")
    print(
        "  expected droop range: "
        f"[{summary['expected_lo']:.4f}, {summary['expected_hi']:.4f}]"
    )
    print(f"  stepped frames      : {summary['frames']}")


# ────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ────────────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hello Rope — SlapPyEngine demo")
    parser.add_argument(
        "--frames", type=int, default=DEFAULT_FRAMES,
        help=f"number of dt=1/60 steps to integrate (default: {DEFAULT_FRAMES})",
    )
    parser.add_argument(
        "--render", action="store_true",
        help="rasterise the final frame to a PNG (pure PIL, no GPU)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("out/hello_rope.png"),
        help="output PNG path when --render is supplied",
    )
    return parser.parse_args(argv)


def main(
    frames: int = DEFAULT_FRAMES,
    render: bool = False,
    out: Path | str = Path("out/hello_rope.png"),
) -> dict:
    """Run the demo and return the summary dict.

    Exposed as a regular function so tests can drive it without a subprocess.
    """
    world, body = build_world()
    step_world(world, frames, DEFAULT_DT)
    summary = summarise(world, body, frames)
    print_summary(summary)

    if render:
        out_path = save_render(world, Path(out))
        print(f"  rendered to         : {out_path}")
    return summary


def _cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        main(frames=args.frames, render=args.render, out=args.out)
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"hello_rope: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
