"""SlapPyEngine — Hello Motor

Minimal demo of :func:`pharos_engine.dynamics.make_motor`.

A wheel is built from three nodes:

* a **hub** pinned at the world origin (infinite mass),
* two **rim** nodes at radius 1.0 from the hub, spaced 180 degrees apart.

Two distance joints glue each rim to the hub so the rim stays on the radius.
A motor joint then drives the rim around the hub at ``target_omega = pi``
rad/s. The world is stepped at ``dt = 1/60`` for 240 frames (4 seconds), so
the wheel is expected to complete two full revolutions.

Run::

    PYTHONPATH=python python examples/hello_motor.py
    PYTHONPATH=python python examples/hello_motor.py --render
    PYTHONPATH=python python examples/hello_motor.py --frames 240 --render --out out/

No GPU is required — when ``--render`` is supplied the wheel is rasterised
to a PNG with pure PIL: hub as a dot, rim nodes as circles, distance joints
as lines, and a faded trail of the last 30 frames of rim positions.
"""
from __future__ import annotations

import argparse
import math
import sys
from collections import deque
from pathlib import Path

import numpy as np

from pharos_engine.dynamics import JointSpec, World, make_motor


# ── Demo parameters ────────────────────────────────────────────────────────
HUB_POS: tuple[float, float] = (0.0, 0.0)
RADIUS: float = 1.0
RIM_MASS: float = 1.0
TARGET_OMEGA: float = math.pi          # ~0.5 Hz (one rev per 2 seconds)
MAX_TORQUE: float = 10.0
RIM_STIFFNESS: float = 1.0e7           # keep the radius tight
RIM_DAMPING: float = 0.02
SOLVER_ITERATIONS: int = 16
GRAVITY: tuple[float, float] = (0.0, 0.0)  # pure motor; no gravity bias
DEFAULT_DT: float = 1.0 / 60.0
DEFAULT_FRAMES: int = 240
OMEGA_WINDOW: int = 60                  # average omega over last N frames

# ── Render parameters ──────────────────────────────────────────────────────
RENDER_W: int = 1280
RENDER_H: int = 720
# Square-ish view box so the wheel doesn't look ovalised.
VIEW_MIN: tuple[float, float] = (-2.0, -2.0)
VIEW_MAX: tuple[float, float] = (2.0, 2.0)
TRAIL_LENGTH: int = 30


# ────────────────────────────────────────────────────────────────────────────
# World / wheel construction
# ────────────────────────────────────────────────────────────────────────────

def build_world() -> tuple[World, dict]:
    """Construct the world + wheel used by every code path in this demo.

    Returns ``(world, info)`` where ``info`` carries the absolute node
    indices for the hub and the two rim nodes so the caller can inspect
    them without having to recompute the layout.
    """
    world = World(gravity=GRAVITY)
    world.solver_iterations = SOLVER_ITERATIONS

    # Hub: pinned at the origin (mass = 0 -> inv_mass = 0).
    hub_idx = world.add_node(HUB_POS, mass=0.0)
    # Two rims at +x and -x, 180 degrees apart.
    rim_a_idx = world.add_node(
        (HUB_POS[0] + RADIUS, HUB_POS[1]), mass=RIM_MASS,
    )
    rim_b_idx = world.add_node(
        (HUB_POS[0] - RADIUS, HUB_POS[1]), mass=RIM_MASS,
    )

    # Distance joint hub -> rim_a holds the radius.
    world.add_joint(
        JointSpec(
            kind="distance",
            node_a=hub_idx,
            node_b=rim_a_idx,
            rest_length=RADIUS,
            stiffness=RIM_STIFFNESS,
            damping=RIM_DAMPING,
        )
    )
    # Distance joint hub -> rim_b holds the radius.
    world.add_joint(
        JointSpec(
            kind="distance",
            node_a=hub_idx,
            node_b=rim_b_idx,
            rest_length=RADIUS,
            stiffness=RIM_STIFFNESS,
            damping=RIM_DAMPING,
        )
    )
    # Motor joint: hub drives rim_a and rim_b around it at target_omega.
    # rest_length on the motor itself is left at 0 so the motor only adds
    # the tangential impulse — the two distance joints above hold the radius.
    world.add_joint(
        make_motor(
            hub=hub_idx,
            rim_a=rim_a_idx,
            rim_b=rim_b_idx,
            target_omega=TARGET_OMEGA,
            max_torque=MAX_TORQUE,
        )
    )

    info = {
        "hub": hub_idx,
        "rim_a": rim_a_idx,
        "rim_b": rim_b_idx,
    }
    return world, info


# ────────────────────────────────────────────────────────────────────────────
# Stepping with per-frame angle / radius tracking
# ────────────────────────────────────────────────────────────────────────────

def _angle_of(world: World, hub: int, rim: int) -> float:
    """Signed angle of (rim - hub) in radians, range ``(-pi, pi]``."""
    r = world.positions[rim] - world.positions[hub]
    return float(math.atan2(float(r[1]), float(r[0])))


def _radius_of(world: World, hub: int, rim: int) -> float:
    r = world.positions[rim] - world.positions[hub]
    return float(np.linalg.norm(r))


def step_world(
    world: World,
    info: dict,
    frames: int,
    dt: float = DEFAULT_DT,
) -> dict:
    """Step *world* for *frames* iterations, recording rim trajectory.

    Returns a dict with per-frame unwrapped angles, per-frame radius
    deviations from ``RADIUS``, a rolling trail of rim positions for the
    renderer, and the smoothed angular velocity measured over the last
    ``OMEGA_WINDOW`` frames.
    """
    hub = info["hub"]
    rim_a = info["rim_a"]
    rim_b = info["rim_b"]

    # Start angles + unwrapping bookkeeping.
    ang_a_prev = _angle_of(world, hub, rim_a)
    ang_b_prev = _angle_of(world, hub, rim_b)
    ang_a_unwrapped = ang_a_prev
    ang_b_unwrapped = ang_b_prev

    angles_a: list[float] = [ang_a_unwrapped]
    angles_b: list[float] = [ang_b_unwrapped]
    radii_a: list[float] = [_radius_of(world, hub, rim_a)]
    radii_b: list[float] = [_radius_of(world, hub, rim_b)]

    trail_a: deque = deque(maxlen=TRAIL_LENGTH)
    trail_b: deque = deque(maxlen=TRAIL_LENGTH)
    trail_a.append(tuple(world.positions[rim_a].tolist()))
    trail_b.append(tuple(world.positions[rim_b].tolist()))

    nan_seen = False

    for _ in range(frames):
        world.step(dt)

        # Unwrap each rim's angle independently so wrap-around at ±pi
        # doesn't fold long-run revolutions back on themselves.
        ang_a_now = _angle_of(world, hub, rim_a)
        ang_b_now = _angle_of(world, hub, rim_b)
        dA = ang_a_now - ang_a_prev
        if dA > math.pi:
            dA -= 2.0 * math.pi
        elif dA < -math.pi:
            dA += 2.0 * math.pi
        dB = ang_b_now - ang_b_prev
        if dB > math.pi:
            dB -= 2.0 * math.pi
        elif dB < -math.pi:
            dB += 2.0 * math.pi
        ang_a_unwrapped += dA
        ang_b_unwrapped += dB
        ang_a_prev = ang_a_now
        ang_b_prev = ang_b_now

        angles_a.append(ang_a_unwrapped)
        angles_b.append(ang_b_unwrapped)
        radii_a.append(_radius_of(world, hub, rim_a))
        radii_b.append(_radius_of(world, hub, rim_b))

        trail_a.append(tuple(world.positions[rim_a].tolist()))
        trail_b.append(tuple(world.positions[rim_b].tolist()))

        if not nan_seen and not np.all(np.isfinite(world.positions)):
            nan_seen = True

    # Smoothed omega: linear fit over the last OMEGA_WINDOW samples gives
    # a noise-tolerant estimate of d(angle)/dt. We average the rim_a and
    # rim_b estimates because both should track the same spin.
    measured_omega = _smoothed_omega(angles_a, angles_b, dt)

    return {
        "angles_a": angles_a,
        "angles_b": angles_b,
        "radii_a": radii_a,
        "radii_b": radii_b,
        "trail_a": list(trail_a),
        "trail_b": list(trail_b),
        "measured_omega": measured_omega,
        "nan_seen": nan_seen,
    }


def _smoothed_omega(
    angles_a: list[float],
    angles_b: list[float],
    dt: float,
) -> float:
    """Average angular velocity over the last :data:`OMEGA_WINDOW` frames.

    Uses a simple end-point-difference average across both rim trajectories.
    """
    if len(angles_a) < 2:
        return 0.0
    window = min(OMEGA_WINDOW, len(angles_a) - 1)
    da = (angles_a[-1] - angles_a[-1 - window]) / (window * dt)
    db = (angles_b[-1] - angles_b[-1 - window]) / (window * dt)
    return 0.5 * (da + db)


# ────────────────────────────────────────────────────────────────────────────
# Pure-PIL renderer (no GPU dependency)
# ────────────────────────────────────────────────────────────────────────────

def _world_to_pixel(p) -> tuple[int, int]:
    vx0, vy0 = VIEW_MIN
    vx1, vy1 = VIEW_MAX
    u = (float(p[0]) - vx0) / (vx1 - vx0)
    v = (float(p[1]) - vy0) / (vy1 - vy0)
    px = int(round(u * (RENDER_W - 1)))
    py = int(round((1.0 - v) * (RENDER_H - 1)))
    return px, py


def _render_frame(world: World, info: dict, trace: dict) -> np.ndarray:
    """Rasterise the wheel: hub dot, rim circles, distance lines, faded trail."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (RENDER_W, RENDER_H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)

    hub = info["hub"]
    rim_a = info["rim_a"]
    rim_b = info["rim_b"]

    positions = world.positions

    # Faded trail for the last TRAIL_LENGTH frames: older = darker.
    trail_a = trace["trail_a"]
    trail_b = trace["trail_b"]
    n_trail = max(len(trail_a), len(trail_b))
    for i in range(1, n_trail):
        # alpha ramps from 32 (oldest) to 192 (newest).
        t = i / max(1, n_trail - 1)
        alpha = int(round(32 + t * (192 - 32)))
        if i < len(trail_a):
            a0 = _world_to_pixel(trail_a[i - 1])
            a1 = _world_to_pixel(trail_a[i])
            draw.line([a0, a1], fill=(255, 96, 96, alpha), width=2)
        if i < len(trail_b):
            b0 = _world_to_pixel(trail_b[i - 1])
            b1 = _world_to_pixel(trail_b[i])
            draw.line([b0, b1], fill=(96, 160, 255, alpha), width=2)

    # Distance joints: hub -> rim_a, hub -> rim_b.
    hub_px = _world_to_pixel(positions[hub])
    rim_a_px = _world_to_pixel(positions[rim_a])
    rim_b_px = _world_to_pixel(positions[rim_b])
    draw.line([hub_px, rim_a_px], fill=(255, 255, 255, 255), width=3)
    draw.line([hub_px, rim_b_px], fill=(255, 255, 255, 255), width=3)

    # Hub dot.
    hub_r = 6
    draw.ellipse(
        [(hub_px[0] - hub_r, hub_px[1] - hub_r),
         (hub_px[0] + hub_r, hub_px[1] + hub_r)],
        fill=(255, 255, 255, 255),
        outline=(255, 255, 255, 255),
    )

    # Rim nodes as circles (filled).
    rim_r = 12
    draw.ellipse(
        [(rim_a_px[0] - rim_r, rim_a_px[1] - rim_r),
         (rim_a_px[0] + rim_r, rim_a_px[1] + rim_r)],
        outline=(255, 96, 96, 255),
        fill=(255, 96, 96, 255),
        width=2,
    )
    draw.ellipse(
        [(rim_b_px[0] - rim_r, rim_b_px[1] - rim_r),
         (rim_b_px[0] + rim_r, rim_b_px[1] + rim_r)],
        outline=(96, 160, 255, 255),
        fill=(96, 160, 255, 255),
        width=2,
    )

    return np.asarray(img, dtype=np.uint8)


def save_render(world: World, info: dict, trace: dict, out_path: Path) -> Path:
    from PIL import Image

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arr = _render_frame(world, info, trace)
    Image.fromarray(arr, mode="RGBA").save(out_path)
    return out_path


# ────────────────────────────────────────────────────────────────────────────
# Diagnostics
# ────────────────────────────────────────────────────────────────────────────

def summarise(world: World, info: dict, trace: dict, frames: int) -> dict:
    hub = info["hub"]
    rim_a = info["rim_a"]
    rim_b = info["rim_b"]

    radii = np.concatenate([
        np.asarray(trace["radii_a"], dtype=np.float64),
        np.asarray(trace["radii_b"], dtype=np.float64),
    ])
    max_radius_deviation = float(np.max(np.abs(radii - RADIUS)))

    measured = float(trace["measured_omega"])
    target = float(TARGET_OMEGA)
    if abs(target) > 1e-9:
        ratio = measured / target
    else:
        ratio = float("nan")

    return {
        "frames": frames,
        "hub_position": tuple(world.positions[hub].tolist()),
        "rim_a_final_angle": float(trace["angles_a"][-1]),
        "rim_b_final_angle": float(trace["angles_b"][-1]),
        "target_omega": target,
        "measured_omega": measured,
        "omega_ratio": ratio,
        "max_radius_deviation": max_radius_deviation,
        "nan_seen": bool(trace["nan_seen"]),
    }


def print_summary(summary: dict) -> None:
    hub_x, hub_y = summary["hub_position"]
    print("hello_motor summary")
    print(f"  hub position           : ({hub_x:.4f}, {hub_y:.4f})")
    print(f"  rim_a final angle (rad): {summary['rim_a_final_angle']:.4f}")
    print(f"  rim_b final angle (rad): {summary['rim_b_final_angle']:.4f}")
    print(f"  target omega (rad/s)   : {summary['target_omega']:.4f}")
    print(f"  measured omega (rad/s) : {summary['measured_omega']:.4f}")
    print(f"  measured/target ratio  : {summary['omega_ratio']:.4f}")
    print(f"  max radius deviation   : {summary['max_radius_deviation']:.4f}")
    print(f"  any NaN in positions   : {summary['nan_seen']}")
    print(f"  stepped frames         : {summary['frames']}")


# ────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ────────────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hello Motor — SlapPyEngine demo")
    parser.add_argument(
        "--frames", type=int, default=DEFAULT_FRAMES,
        help=f"number of dt=1/60 steps to integrate (default: {DEFAULT_FRAMES})",
    )
    parser.add_argument(
        "--render", action="store_true",
        help="rasterise the final frame to a PNG (pure PIL, no GPU)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("out/hello_motor.png"),
        help="output PNG path when --render is supplied",
    )
    return parser.parse_args(argv)


def main(
    frames: int = DEFAULT_FRAMES,
    render: bool = False,
    out: Path | str = Path("out/hello_motor.png"),
) -> dict:
    """Run the demo end-to-end. Returns the summary dict for tests."""
    world, info = build_world()
    trace = step_world(world, info, frames, DEFAULT_DT)
    summary = summarise(world, info, trace, frames)
    print_summary(summary)

    if render:
        out_path = save_render(world, info, trace, Path(out))
        print(f"  rendered to            : {out_path}")
    return summary


def _cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        main(frames=args.frames, render=args.render, out=args.out)
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"hello_motor: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
