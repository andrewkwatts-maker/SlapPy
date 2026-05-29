"""SlapPyEngine — Hello Ragdoll

Minimal demo of :class:`slappyengine.dynamics.RagdollSpec`.

A 6-bone humanoid skeleton (torso + head + two arms + two legs) is dropped
from ``y = 3.0`` with zero initial velocity. The world is stepped at
``dt = 1/60`` for 180 frames under gravity, with a simple ``y = max(y, 0)``
ground clamp applied after every solver step. The demo prints a summary
covering bone/joint counts, the lowest bone tip, and a boolean confirming
every hinge angle stayed inside its declared band across the run.

Run::

    PYTHONPATH=python python examples/hello_ragdoll.py
    PYTHONPATH=python python examples/hello_ragdoll.py --render
    PYTHONPATH=python python examples/hello_ragdoll.py --frames 240 --render --out out/

No GPU is required — when ``--render`` is supplied the skeleton is
rasterised to a PNG with pure PIL: white line segments along each bone,
small dots at the joints.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

from slappyengine.dynamics import BoneSpec, RagdollSpec, World, build_ragdoll


# ── Demo parameters ────────────────────────────────────────────────────────
ANCHOR_POS: tuple[float, float] = (0.0, 3.0)
GRAVITY: tuple[float, float] = (0.0, -9.81)
GROUND_Y: float = 0.0
DEFAULT_DT: float = 1.0 / 60.0
DEFAULT_FRAMES: int = 180

# Bone proportions (six-bone humanoid). Lengths in world units, mass in kg.
TORSO_LENGTH: float = 0.6
HEAD_LENGTH: float = 0.3
ARM_LENGTH: float = 0.5
LEG_LENGTH: float = 0.7
TORSO_MASS: float = 4.0
HEAD_MASS: float = 1.5
ARM_MASS: float = 1.0
LEG_MASS: float = 1.5

# Angle limits are intentionally generous — wide enough that simple falling
# never breaches them, but the hinge constraints still fire and document
# the API surface for downstream authoring code.
ANGLE_LIMIT: tuple[float, float] = (-math.pi, math.pi)

# ── Render parameters ──────────────────────────────────────────────────────
RENDER_W: int = 1280
RENDER_H: int = 720
VIEW_MIN: tuple[float, float] = (-2.0, -0.5)
VIEW_MAX: tuple[float, float] = (2.0, 3.5)


# ────────────────────────────────────────────────────────────────────────────
# Skeleton construction
# ────────────────────────────────────────────────────────────────────────────

def build_humanoid_spec() -> RagdollSpec:
    """Six-bone humanoid skeleton: torso, head, 2 arms, 2 legs."""
    bones: list[BoneSpec] = [
        BoneSpec(  # 0: torso (root)
            parent_idx=-1,
            length=TORSO_LENGTH,
            mass=TORSO_MASS,
            angle_limit=ANGLE_LIMIT,
            direction=(0.0, -1.0),
            label="torso",
        ),
        BoneSpec(  # 1: head — extends UP from the torso shoulder line
            parent_idx=0,
            length=HEAD_LENGTH,
            mass=HEAD_MASS,
            angle_limit=ANGLE_LIMIT,
            direction=(0.0, 1.0),
            label="head",
        ),
        BoneSpec(  # 2: left arm
            parent_idx=0,
            length=ARM_LENGTH,
            mass=ARM_MASS,
            angle_limit=ANGLE_LIMIT,
            direction=(-1.0, 0.0),
            label="arm_l",
        ),
        BoneSpec(  # 3: right arm
            parent_idx=0,
            length=ARM_LENGTH,
            mass=ARM_MASS,
            angle_limit=ANGLE_LIMIT,
            direction=(1.0, 0.0),
            label="arm_r",
        ),
        BoneSpec(  # 4: left leg
            parent_idx=0,
            length=LEG_LENGTH,
            mass=LEG_MASS,
            angle_limit=ANGLE_LIMIT,
            direction=(-0.3, -1.0),
            label="leg_l",
        ),
        BoneSpec(  # 5: right leg
            parent_idx=0,
            length=LEG_LENGTH,
            mass=LEG_MASS,
            angle_limit=ANGLE_LIMIT,
            direction=(0.3, -1.0),
            label="leg_r",
        ),
    ]
    return RagdollSpec(bones=bones)


def build_world() -> tuple[World, "object", RagdollSpec]:
    """Construct the world + ragdoll used by every code path in this demo."""
    world = World(gravity=GRAVITY)
    world.solver_iterations = 12
    spec = build_humanoid_spec()
    body = build_ragdoll(spec, world, anchor_pos=ANCHOR_POS, pin_root=False)
    return world, body, spec


# ────────────────────────────────────────────────────────────────────────────
# Stepping with a ground clamp + per-frame joint-angle audit
# ────────────────────────────────────────────────────────────────────────────

def _ground_clamp(world: World, ground_y: float = GROUND_Y) -> None:
    """In-place: lift any node that dropped below ``ground_y`` back to it."""
    ys = world.positions[:, 1]
    below = ys < ground_y
    if np.any(below):
        world.positions[below, 1] = ground_y
        world.velocities[below, 1] = 0.0


def _hinge_joints(world: World) -> list:
    """Return only the hinge joints (angular limits) from the world."""
    return [j for j in world.joints if j.kind == "hinge"]


def _joint_angle(world: World, joint) -> float:
    """Measure the signed angle between (anchor->node_a) and (anchor->node_b)."""
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


def step_world(
    world: World,
    frames: int,
    dt: float = DEFAULT_DT,
    *,
    audit_limits: bool = True,
) -> dict:
    """Step *world* for *frames* iterations with a ground clamp.

    When ``audit_limits`` is true the hinge joint angles are sampled after
    every step and checked against their declared ``[min_angle, max_angle]``
    band. The returned dict carries the running booleans + min/max y so
    callers can summarise without re-traversing the trajectory.
    """
    hinges = _hinge_joints(world)
    limits_respected = True
    min_y_seen = float("inf")
    nan_seen = False

    for _ in range(frames):
        world.step(dt)
        _ground_clamp(world)

        if not nan_seen and not np.all(np.isfinite(world.positions)):
            nan_seen = True

        cur_min = float(world.positions[:, 1].min())
        if cur_min < min_y_seen:
            min_y_seen = cur_min

        if audit_limits and limits_respected:
            for j in hinges:
                ang = _joint_angle(world, j)
                lo = float(j.params.get("min_angle", -math.pi))
                hi = float(j.params.get("max_angle", math.pi))
                # Allow a small slack — XPBD projection is iterative so a
                # micro-overshoot during the same step is acceptable as long
                # as it lands back inside the band on the next sample.
                slack = 1e-3
                if ang < lo - slack or ang > hi + slack:
                    limits_respected = False
                    break

    return {
        "lowest_y": min_y_seen,
        "limits_respected": limits_respected,
        "nan_seen": nan_seen,
    }


# ────────────────────────────────────────────────────────────────────────────
# Pure-PIL renderer (no GPU dependency)
# ────────────────────────────────────────────────────────────────────────────

def _world_to_pixel(p: np.ndarray) -> tuple[int, int]:
    vx0, vy0 = VIEW_MIN
    vx1, vy1 = VIEW_MAX
    u = (float(p[0]) - vx0) / (vx1 - vx0)
    v = (float(p[1]) - vy0) / (vy1 - vy0)
    px = int(round(u * (RENDER_W - 1)))
    py = int(round((1.0 - v) * (RENDER_H - 1)))
    return px, py


def _render_frame(world: World, body) -> np.ndarray:
    """Rasterise the skeleton: white line per bone, dot per joint."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (RENDER_W, RENDER_H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)

    root_node = int(body.parameters["root_node"])
    child_nodes: list[int] = list(body.parameters["child_nodes"])
    spec: RagdollSpec = body.parameters["spec"]

    # Lines: parent endpoint -> child endpoint for every bone.
    for bi, bone in enumerate(spec.bones):
        if bone.parent_idx < 0:
            parent_node = root_node
        else:
            parent_node = child_nodes[bone.parent_idx]
        child = child_nodes[bi]
        a = _world_to_pixel(world.positions[parent_node])
        b = _world_to_pixel(world.positions[child])
        draw.line([a, b], fill=(255, 255, 255, 255), width=3)

    # Dots: every node owned by the body.
    node_r = 4
    seen: set[int] = set()
    for idx in (root_node, *child_nodes):
        if idx in seen:
            continue
        seen.add(idx)
        x, y = _world_to_pixel(world.positions[idx])
        draw.ellipse(
            [(x - node_r, y - node_r), (x + node_r, y + node_r)],
            fill=(255, 255, 255, 255),
            outline=(255, 255, 255, 255),
        )

    return np.asarray(img, dtype=np.uint8)


def save_render(world: World, body, out_path: Path) -> Path:
    from PIL import Image

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arr = _render_frame(world, body)
    Image.fromarray(arr, mode="RGBA").save(out_path)
    return out_path


# ────────────────────────────────────────────────────────────────────────────
# Diagnostics
# ────────────────────────────────────────────────────────────────────────────

def summarise(world: World, body, spec: RagdollSpec, trace: dict, frames: int) -> dict:
    bone_count = len(spec.bones)
    joint_count = len(world.joints)
    # Lowest *bone tip* y (excludes the abstract root node if it happens to
    # float above). We treat every node owned by the body as a candidate.
    node_ys = world.positions[list(body.node_indices), 1]
    lowest_bone_y = float(node_ys.min())
    return {
        "frames": frames,
        "bones": bone_count,
        "joints": joint_count,
        "lowest_bone_y": lowest_bone_y,
        "lowest_y_seen": trace["lowest_y"],
        "limits_respected": bool(trace["limits_respected"]),
        "nan_seen": bool(trace["nan_seen"]),
    }


def print_summary(summary: dict) -> None:
    print("hello_ragdoll summary")
    print(f"  bones                : {summary['bones']}")
    print(f"  joints               : {summary['joints']}")
    print(f"  lowest bone y        : {summary['lowest_bone_y']:.4f}")
    print(f"  lowest y seen        : {summary['lowest_y_seen']:.4f}")
    print(f"  joint limits respected: {summary['limits_respected']}")
    print(f"  any NaN in positions : {summary['nan_seen']}")
    print(f"  stepped frames       : {summary['frames']}")


# ────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ────────────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hello Ragdoll — SlapPyEngine demo")
    parser.add_argument(
        "--frames", type=int, default=DEFAULT_FRAMES,
        help=f"number of dt=1/60 steps to integrate (default: {DEFAULT_FRAMES})",
    )
    parser.add_argument(
        "--render", action="store_true",
        help="rasterise the final frame to a PNG (pure PIL, no GPU)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("out/hello_ragdoll.png"),
        help="output PNG path when --render is supplied",
    )
    return parser.parse_args(argv)


def main(
    frames: int = DEFAULT_FRAMES,
    render: bool = False,
    out: Path | str = Path("out/hello_ragdoll.png"),
) -> dict:
    """Run the demo end-to-end. Returns the summary dict for tests."""
    world, body, spec = build_world()
    trace = step_world(world, frames, DEFAULT_DT)
    summary = summarise(world, body, spec, trace, frames)
    print_summary(summary)

    if render:
        out_path = save_render(world, body, Path(out))
        print(f"  rendered to          : {out_path}")
    return summary


def _cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        main(frames=args.frames, render=args.render, out=args.out)
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"hello_ragdoll: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
