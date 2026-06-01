"""SlapPyEngine - Hello Ragdoll

A 6-bone humanoid ragdoll drops onto a flat floor, lands, settles, then
breathes. The demo records the run as an animated GIF using the same
``slappyengine.media`` backbone the :mod:`slappyengine.studio` helpers use.

The skeleton is six bones (torso, head, two arms, two legs) wired by the
authoritative :func:`slappyengine.dynamics.build_ragdoll` builder. After
landing, a small vertical sway on the head node simulates breathing without
breaking the joint band invariants.

Damping is tuned so ``solver_iterations * damping`` stays at or under
``0.3`` (the over-damp warning threshold documented in
:mod:`slappyengine.dynamics.world`): ``iters=6`` and ``damping=0.05`` give
``0.30`` exactly, so the demo never trips ``RuntimeWarning``.

Run::

    PYTHONPATH=python python examples/hello_ragdoll.py
    PYTHONPATH=python python examples/hello_ragdoll.py --frames 60
    PYTHONPATH=python python examples/hello_ragdoll.py --no-gif
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

from slappyengine.dynamics import BoneSpec, RagdollSpec, World, build_ragdoll
from slappyengine.media import save_frames


# -- Demo parameters -------------------------------------------------------
ANCHOR_POS: tuple[float, float] = (0.0, 3.0)
GRAVITY: tuple[float, float] = (0.0, -9.81)
GROUND_Y: float = 0.0
DEFAULT_DT: float = 1.0 / 60.0
DEFAULT_FRAMES: int = 180

# Solver tuning: keep iters * damping <= 0.3 to avoid the over-damp
# RuntimeWarning surfaced by World._check_overdamping.
SOLVER_ITERATIONS: int = 6
RAGDOLL_DAMPING: float = 0.05  # 6 * 0.05 == 0.30 (exactly at threshold)
RAGDOLL_STIFFNESS: float = 5.0e6

# Breathing animation (applied once the ragdoll has settled).
BREATHING_START_FRAME: int = 90
BREATHING_AMPLITUDE: float = 0.015  # world units of vertical sway on head
BREATHING_HZ: float = 0.4

# Bone proportions (six-bone humanoid). Lengths in world units, mass in kg.
TORSO_LENGTH: float = 0.6
HEAD_LENGTH: float = 0.3
ARM_LENGTH: float = 0.5
LEG_LENGTH: float = 0.7
TORSO_MASS: float = 4.0
HEAD_MASS: float = 1.5
ARM_MASS: float = 1.0
LEG_MASS: float = 1.5

# Angle limits are wide enough that a passive drop never breaches them, but
# the hinge constraints still fire and document the API surface.
ANGLE_LIMIT: tuple[float, float] = (-math.pi, math.pi)

# -- Render parameters -----------------------------------------------------
RENDER_W: int = 480
RENDER_H: int = 360
VIEW_MIN: tuple[float, float] = (-2.0, -0.5)
VIEW_MAX: tuple[float, float] = (2.0, 3.5)
GIF_FPS: int = 30


# ---------------------------------------------------------------------------
# Skeleton construction
# ---------------------------------------------------------------------------

def build_humanoid_spec() -> RagdollSpec:
    """Six-bone humanoid skeleton: torso, head, 2 arms, 2 legs."""
    bones: list[BoneSpec] = [
        BoneSpec(  # 0: torso (root)
            parent_idx=-1, length=TORSO_LENGTH, mass=TORSO_MASS,
            angle_limit=ANGLE_LIMIT, direction=(0.0, -1.0), label="torso",
        ),
        BoneSpec(  # 1: head - extends UP from the torso shoulder line
            parent_idx=0, length=HEAD_LENGTH, mass=HEAD_MASS,
            angle_limit=ANGLE_LIMIT, direction=(0.0, 1.0), label="head",
        ),
        BoneSpec(  # 2: left arm
            parent_idx=0, length=ARM_LENGTH, mass=ARM_MASS,
            angle_limit=ANGLE_LIMIT, direction=(-1.0, 0.0), label="arm_l",
        ),
        BoneSpec(  # 3: right arm
            parent_idx=0, length=ARM_LENGTH, mass=ARM_MASS,
            angle_limit=ANGLE_LIMIT, direction=(1.0, 0.0), label="arm_r",
        ),
        BoneSpec(  # 4: left leg
            parent_idx=0, length=LEG_LENGTH, mass=LEG_MASS,
            angle_limit=ANGLE_LIMIT, direction=(-0.3, -1.0), label="leg_l",
        ),
        BoneSpec(  # 5: right leg
            parent_idx=0, length=LEG_LENGTH, mass=LEG_MASS,
            angle_limit=ANGLE_LIMIT, direction=(0.3, -1.0), label="leg_r",
        ),
    ]
    return RagdollSpec(
        bones=bones,
        stiffness=RAGDOLL_STIFFNESS,
        damping=RAGDOLL_DAMPING,
    )


def build_world() -> tuple[World, "object", RagdollSpec]:
    """Construct the world + ragdoll used by every code path in this demo."""
    world = World(gravity=GRAVITY)
    world.solver_iterations = SOLVER_ITERATIONS
    spec = build_humanoid_spec()
    body = build_ragdoll(spec, world, anchor_pos=ANCHOR_POS, pin_root=False)
    return world, body, spec


# ---------------------------------------------------------------------------
# Stepping with a ground clamp + breathing animation
# ---------------------------------------------------------------------------

def _ground_clamp(world: World, ground_y: float = GROUND_Y) -> None:
    """In-place: lift any node that dropped below ``ground_y`` back to it."""
    ys = world.positions[:, 1]
    below = ys < ground_y
    if np.any(below):
        world.positions[below, 1] = ground_y
        world.velocities[below, 1] = 0.0


def _apply_breathing(world: World, body, frame: int) -> None:
    """Once settled, gently sway the head node to simulate breathing.

    The sway is a tiny vertical displacement on the head's child endpoint
    only. It's small enough that the hinge bands never trip.
    """
    if frame < BREATHING_START_FRAME:
        return
    head_child = int(body.parameters["child_nodes"][1])  # bone idx 1 = head
    t = (frame - BREATHING_START_FRAME) * DEFAULT_DT
    dy = BREATHING_AMPLITUDE * math.sin(2.0 * math.pi * BREATHING_HZ * t)
    world.positions[head_child, 1] += dy


def _hinge_joints(world: World) -> list:
    return [j for j in world.joints if j.kind == "hinge"]


def _joint_angle(world: World, joint) -> float:
    anchor = int(joint.params.get("anchor", joint.node_a))
    p0 = world.positions[anchor]
    pa = world.positions[joint.node_a]
    pb = world.positions[joint.node_b]
    va = pa - p0
    vb = pb - p0
    if float(np.linalg.norm(va)) < 1e-9 or float(np.linalg.norm(vb)) < 1e-9:
        return 0.0
    return float(math.atan2(
        va[0] * vb[1] - va[1] * vb[0],
        va[0] * vb[0] + va[1] * vb[1],
    ))


# ---------------------------------------------------------------------------
# Pure-PIL renderer (no GPU dependency)
# ---------------------------------------------------------------------------

def _world_to_pixel(p: np.ndarray) -> tuple[int, int]:
    vx0, vy0 = VIEW_MIN
    vx1, vy1 = VIEW_MAX
    u = (float(p[0]) - vx0) / (vx1 - vx0)
    v = (float(p[1]) - vy0) / (vy1 - vy0)
    px = int(round(u * (RENDER_W - 1)))
    py = int(round((1.0 - v) * (RENDER_H - 1)))
    return px, py


def _render_frame(world: World, body):
    """Rasterise the skeleton onto a PIL Image: floor line + bones + joints."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (RENDER_W, RENDER_H), (12, 14, 22))
    draw = ImageDraw.Draw(img)

    # Floor line.
    fy0 = _world_to_pixel(np.asarray([VIEW_MIN[0], GROUND_Y]))[1]
    draw.line([(0, fy0), (RENDER_W - 1, fy0)], fill=(70, 80, 60), width=2)

    root_node = int(body.parameters["root_node"])
    child_nodes: list[int] = list(body.parameters["child_nodes"])
    spec: RagdollSpec = body.parameters["spec"]

    # Bones.
    for bi, bone in enumerate(spec.bones):
        parent_node = root_node if bone.parent_idx < 0 else child_nodes[bone.parent_idx]
        child = child_nodes[bi]
        a = _world_to_pixel(world.positions[parent_node])
        b = _world_to_pixel(world.positions[child])
        draw.line([a, b], fill=(230, 230, 240), width=3)

    # Joints.
    node_r = 4
    seen: set[int] = set()
    for idx in (root_node, *child_nodes):
        if idx in seen:
            continue
        seen.add(idx)
        x, y = _world_to_pixel(world.positions[idx])
        draw.ellipse(
            [(x - node_r, y - node_r), (x + node_r, y + node_r)],
            fill=(255, 200, 120), outline=(255, 220, 160),
        )
    return img


# ---------------------------------------------------------------------------
# Run loop + GIF capture (uses slappyengine.media.save_frames, same backbone
# the slappyengine.studio.record() helper sits on top of)
# ---------------------------------------------------------------------------

def run(frames: int, capture_gif: bool):
    """Step the world ``frames`` times and optionally capture each frame."""
    world, body, spec = build_world()
    pil_frames: list = []
    hinges = _hinge_joints(world)
    limits_respected = True

    for f in range(frames):
        _apply_breathing(world, body, f)
        world.step(DEFAULT_DT)
        _ground_clamp(world)

        if limits_respected:
            for j in hinges:
                ang = _joint_angle(world, j)
                lo = float(j.params.get("min_angle", -math.pi))
                hi = float(j.params.get("max_angle", math.pi))
                if ang < lo - 1e-3 or ang > hi + 1e-3:
                    limits_respected = False
                    break

        if capture_gif:
            pil_frames.append(_render_frame(world, body))

    return world, body, spec, pil_frames, limits_respected


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def summarise(world: World, body, spec: RagdollSpec, frames: int,
              limits_respected: bool) -> dict:
    node_ys = world.positions[list(body.node_indices), 1]
    final_speed = float(np.linalg.norm(world.velocities, axis=1).max())
    return {
        "frames": frames,
        "bones": len(spec.bones),
        "joints": len(world.joints),
        "lowest_bone_y": float(node_ys.min()),
        "max_speed_final": final_speed,
        "limits_respected": bool(limits_respected),
        "iters_x_damping": SOLVER_ITERATIONS * RAGDOLL_DAMPING,
    }


def print_summary(summary: dict) -> None:
    print("hello_ragdoll summary")
    print(f"  bones                : {summary['bones']}")
    print(f"  joints               : {summary['joints']}")
    print(f"  lowest bone y        : {summary['lowest_bone_y']:.4f}")
    print(f"  max final speed      : {summary['max_speed_final']:.4f}")
    print(f"  joint limits respected: {summary['limits_respected']}")
    print(f"  iters * damping      : {summary['iters_x_damping']:.3f} (<= 0.3 OK)")
    print(f"  stepped frames       : {summary['frames']}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _default_gif_path() -> Path:
    return Path(__file__).resolve().parent / "output" / "ragdoll" / "hello_ragdoll.gif"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hello Ragdoll - SlapPyEngine demo")
    parser.add_argument(
        "--frames", type=int, default=DEFAULT_FRAMES,
        help=f"number of dt=1/60 steps to integrate (default: {DEFAULT_FRAMES})",
    )
    parser.add_argument(
        "--no-gif", action="store_true",
        help="skip GIF capture (smoke-test mode; pairs well with --frames 60)",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="GIF output path (default: examples/output/ragdoll/hello_ragdoll.gif)",
    )
    return parser.parse_args(argv)


def main(
    frames: int = DEFAULT_FRAMES,
    capture_gif: bool = True,
    out: Path | str | None = None,
) -> dict:
    """Run the demo end-to-end. Returns the summary dict for tests."""
    world, body, spec, pil_frames, limits_respected = run(frames, capture_gif)
    summary = summarise(world, body, spec, frames, limits_respected)
    print_summary(summary)

    if capture_gif and pil_frames:
        out_path = Path(out) if out is not None else _default_gif_path()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        written = save_frames(pil_frames, out_path, fps=GIF_FPS)
        summary["gif_path"] = str(written)
        print(f"  gif written to       : {written}")
    return summary


def _cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        main(frames=args.frames, capture_gif=not args.no_gif, out=args.out)
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"hello_ragdoll: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
