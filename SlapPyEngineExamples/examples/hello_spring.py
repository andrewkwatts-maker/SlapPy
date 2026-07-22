"""SlapPyEngine - Hello Spring

Minimal demo of :func:`pharos_engine.dynamics.make_spring`.

A pinned anchor at ``(0, 4)`` holds a single ``mass = 1.0`` node attached by
a Hooke-style spring (``rest_length = 2.0``, ``stiffness = 100``, light
``damping = 0.01``). The mass is released from ``(0, 0.5)`` -- ``1.5`` units
below its equilibrium at ``(0, 2.0)`` -- and the world is stepped at
``dt = 1/120`` for 480 frames (4 seconds).

For a 1D Hookean oscillator the natural period is::

    T = 2 * pi * sqrt(m / k)

so with ``m = 1`` kg and ``k = 100`` N/m the theoretical period is
~``0.628 s`` and we expect ~``6.36`` cycles inside the 4 s window. The
demo measures the observed period from zero-crossings of ``y - rest_y``,
prints the ratio versus theory, and (when ``--render`` is supplied)
rasterises the final frame to a PNG -- anchor as a white square, spring
as a zig-zag, mass as a filled white disc.

Run::

    PYTHONPATH=python python examples/hello_spring.py
    PYTHONPATH=python python examples/hello_spring.py --render
    PYTHONPATH=python python examples/hello_spring.py --frames 480 --render --out out/

No GPU is required.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

from pharos_engine.dynamics import World, make_spring


# -- Demo parameters --------------------------------------------------------
ANCHOR_POS: tuple[float, float] = (0.0, 4.0)
MASS_POS_REST: tuple[float, float] = (0.0, 2.0)       # equilibrium target
MASS_POS_INIT: tuple[float, float] = (0.0, 0.5)       # displaced start
MASS: float = 1.0
REST_LENGTH: float = 2.0
STIFFNESS: float = 100.0
DAMPING: float = 0.01                                  # light - oscillation visible
GRAVITY: tuple[float, float] = (0.0, 0.0)              # pure spring physics
DEFAULT_DT: float = 1.0 / 120.0
DEFAULT_FRAMES: int = 480

# -- Render parameters ------------------------------------------------------
RENDER_W: int = 1280
RENDER_H: int = 720
# View box covers a bit above the anchor and a bit below the initial release.
VIEW_MIN: tuple[float, float] = (-2.5, -0.5)
VIEW_MAX: tuple[float, float] = (2.5, 4.5)
SPRING_COILS: int = 12           # zig-zag count along the spring
SPRING_AMPLITUDE: float = 0.18   # zig-zag half-width in world units
ANCHOR_HALF_SIZE: float = 0.18   # world-space half side of anchor square
MASS_RADIUS: float = 0.18        # world-space mass radius


# ---------------------------------------------------------------------------
#  Simulation helpers
# ---------------------------------------------------------------------------

def build_world() -> tuple[World, int, int]:
    """Construct the world + spring used by every code path in this demo.

    Returns
    -------
    world : World
        Configured XPBD world with a single spring joint.
    anchor_idx : int
        Node index of the pinned anchor.
    mass_idx : int
        Node index of the free mass (already displaced to ``MASS_POS_INIT``).
    """
    world = World(gravity=GRAVITY)
    # XPBD position damping is applied per solver iteration; high
    # iteration counts therefore drown out any visible oscillation. One
    # iteration is sufficient for a single distance constraint and lines
    # the measured period up within ~2 % of the analytical
    # ``T = 2*pi*sqrt(m/k)``.
    world.solver_iterations = 1
    anchor_idx = world.add_node(ANCHOR_POS, mass=0.0)        # pinned
    mass_idx = world.add_node(MASS_POS_INIT, mass=MASS)     # free, displaced
    world.add_joint(
        make_spring(
            anchor_idx,
            mass_idx,
            rest_length=REST_LENGTH,
            stiffness=STIFFNESS,
            damping=DAMPING,
        )
    )
    return world, anchor_idx, mass_idx


def step_world(
    world: World,
    mass_idx: int,
    frames: int,
    dt: float = DEFAULT_DT,
) -> np.ndarray:
    """Step the world for ``frames`` ticks, returning per-frame mass y."""
    history = np.zeros(frames, dtype=np.float64)
    for i in range(frames):
        world.step(dt)
        history[i] = float(world.positions[mass_idx, 1])
    return history


# ---------------------------------------------------------------------------
#  Diagnostics
# ---------------------------------------------------------------------------

def _zero_crossings(signal: np.ndarray) -> int:
    """Count sign changes in ``signal`` (excluding exact zeros)."""
    sign = np.sign(signal)
    # Treat zeros as their predecessor's sign so a flat zero doesn't count.
    nonzero_sign = np.where(sign == 0, np.nan, sign)
    sign_changes = (nonzero_sign[:-1] * nonzero_sign[1:]) < 0
    return int(np.nansum(sign_changes))


def analyse(
    history: np.ndarray, dt: float, rest_y: float = MASS_POS_REST[1]
) -> dict:
    """Extract oscillation period + amplitude metrics from a y-history."""
    centered = history - rest_y
    crossings = _zero_crossings(centered)
    # Two zero-crossings per full period.
    cycles = crossings / 2.0
    total_time = len(history) * dt
    measured_period = total_time / cycles if cycles > 0 else math.inf
    theoretical_period = 2.0 * math.pi * math.sqrt(MASS / STIFFNESS)
    ratio = (
        measured_period / theoretical_period
        if math.isfinite(measured_period)
        else math.inf
    )

    # Peak amplitudes in the first 60-frame window vs the last 60-frame window.
    win = min(60, len(centered) // 2 if len(centered) else 1)
    win = max(1, win)
    peak_early = float(np.max(np.abs(centered[:win]))) if len(centered) else 0.0
    peak_late = (
        float(np.max(np.abs(centered[-win:]))) if len(centered) else 0.0
    )

    return {
        "frames": len(history),
        "dt": dt,
        "duration": total_time,
        "rest_y": rest_y,
        "zero_crossings": crossings,
        "cycles": cycles,
        "measured_period": measured_period,
        "theoretical_period": theoretical_period,
        "ratio": ratio,
        "peak_amplitude_early": peak_early,
        "peak_amplitude_late": peak_late,
        "min_y": float(np.min(history)) if len(history) else math.nan,
        "max_y": float(np.max(history)) if len(history) else math.nan,
        "final_y": float(history[-1]) if len(history) else math.nan,
    }


def print_summary(summary: dict) -> None:
    print("hello_spring summary")
    print(f"  frames               : {summary['frames']}")
    print(f"  dt                   : {summary['dt']:.6f}")
    print(f"  duration             : {summary['duration']:.4f} s")
    print(f"  rest_y               : {summary['rest_y']:.4f}")
    print(f"  zero crossings       : {summary['zero_crossings']}")
    print(f"  cycles               : {summary['cycles']:.4f}")
    print(f"  measured period      : {summary['measured_period']:.4f} s")
    print(f"  theoretical period   : {summary['theoretical_period']:.4f} s")
    print(f"  ratio (meas / theory): {summary['ratio']:.4f}")
    print(f"  peak amplitude early : {summary['peak_amplitude_early']:.4f}")
    print(f"  peak amplitude late  : {summary['peak_amplitude_late']:.4f}")
    print(
        "  amplitude decay      : "
        f"{(1.0 - summary['peak_amplitude_late'] / max(summary['peak_amplitude_early'], 1e-12)) * 100.0:.2f} %"
    )
    print(f"  y range              : [{summary['min_y']:.4f}, {summary['max_y']:.4f}]")
    print(f"  final y              : {summary['final_y']:.4f}")


# ---------------------------------------------------------------------------
#  Pure-PIL renderer (no GPU dependency)
# ---------------------------------------------------------------------------

def _world_to_pixel(p: tuple[float, float] | np.ndarray) -> tuple[int, int]:
    vx0, vy0 = VIEW_MIN
    vx1, vy1 = VIEW_MAX
    x = float(p[0])
    y = float(p[1])
    u = (x - vx0) / (vx1 - vx0)
    v = (y - vy0) / (vy1 - vy0)
    px = int(round(u * (RENDER_W - 1)))
    # Image-space y grows downward; world y grows upward.
    py = int(round((1.0 - v) * (RENDER_H - 1)))
    return px, py


def _spring_polyline(
    anchor: np.ndarray, mass: np.ndarray, coils: int, amplitude: float
) -> list[tuple[int, int]]:
    """Build a zig-zag polyline between ``anchor`` and ``mass`` in pixels."""
    seg_count = 2 * coils + 2          # endpoints + 2 turns per coil
    if seg_count < 2:
        seg_count = 2
    direction = mass - anchor
    length = float(np.linalg.norm(direction))
    if length < 1e-9:
        return [_world_to_pixel(anchor), _world_to_pixel(mass)]
    axis = direction / length
    # In 2D the perpendicular of (ax, ay) is (-ay, ax).
    perp = np.array([-axis[1], axis[0]], dtype=np.float64)

    points: list[tuple[int, int]] = []
    for i in range(seg_count + 1):
        t = i / seg_count
        base = anchor + direction * t
        # First and last point sit on the centerline; interior points zig-zag.
        if 0 < i < seg_count:
            offset = amplitude if (i % 2 == 1) else -amplitude
            world_p = base + perp * offset
        else:
            world_p = base
        points.append(_world_to_pixel(world_p))
    return points


def _render_frame(world: World, anchor_idx: int, mass_idx: int) -> np.ndarray:
    """Rasterise the spring + mass to an ``(H, W, 4)`` uint8 RGBA buffer.

    Black background. Anchor is a white square, the spring is a white
    zig-zag polyline, the mass is a filled white disc.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (RENDER_W, RENDER_H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)

    anchor = world.positions[anchor_idx]
    mass = world.positions[mass_idx]

    # Spring (zig-zag polyline). Drawn first so the markers sit on top.
    polyline = _spring_polyline(anchor, mass, SPRING_COILS, SPRING_AMPLITUDE)
    if len(polyline) >= 2:
        draw.line(polyline, fill=(255, 255, 255, 255), width=2)

    # Anchor: white square.
    ax, ay = _world_to_pixel(anchor)
    half_px = int(round(
        ANCHOR_HALF_SIZE / (VIEW_MAX[0] - VIEW_MIN[0]) * (RENDER_W - 1)
    ))
    half_px = max(4, half_px)
    draw.rectangle(
        [(ax - half_px, ay - half_px), (ax + half_px, ay + half_px)],
        fill=(255, 255, 255, 255),
        outline=(255, 255, 255, 255),
    )

    # Mass: filled white disc.
    mx, my = _world_to_pixel(mass)
    r_px = int(round(
        MASS_RADIUS / (VIEW_MAX[0] - VIEW_MIN[0]) * (RENDER_W - 1)
    ))
    r_px = max(4, r_px)
    draw.ellipse(
        [(mx - r_px, my - r_px), (mx + r_px, my + r_px)],
        fill=(255, 255, 255, 255),
        outline=(255, 255, 255, 255),
    )

    return np.asarray(img, dtype=np.uint8)


def save_render(
    world: World, anchor_idx: int, mass_idx: int, out_path: Path
) -> Path:
    """Write the rendered frame to ``out_path``."""
    from PIL import Image

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arr = _render_frame(world, anchor_idx, mass_idx)
    Image.fromarray(arr, mode="RGBA").save(out_path)
    return out_path


# ---------------------------------------------------------------------------
#  CLI entry point
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Hello Spring -- SlapPyEngine demo"
    )
    parser.add_argument(
        "--frames", type=int, default=DEFAULT_FRAMES,
        help=f"number of dt=1/120 steps to integrate (default: {DEFAULT_FRAMES})",
    )
    parser.add_argument(
        "--render", action="store_true",
        help="rasterise the final frame to a PNG (pure PIL, no GPU)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("out/hello_spring.png"),
        help="output PNG path when --render is supplied",
    )
    return parser.parse_args(argv)


def main(
    frames: int = DEFAULT_FRAMES,
    render: bool = False,
    out: Path | str = Path("out/hello_spring.png"),
) -> dict:
    """Run the demo and return the diagnostics dict.

    Exposed as a regular function so tests can drive it without a subprocess.
    """
    world, anchor_idx, mass_idx = build_world()
    history = step_world(world, mass_idx, frames, DEFAULT_DT)
    summary = analyse(history, DEFAULT_DT)
    summary["history"] = history
    summary["anchor_idx"] = anchor_idx
    summary["mass_idx"] = mass_idx
    print_summary(summary)

    if render:
        out_path = save_render(world, anchor_idx, mass_idx, Path(out))
        print(f"  rendered to          : {out_path}")
    return summary


def _cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        main(frames=args.frames, render=args.render, out=args.out)
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"hello_spring: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
