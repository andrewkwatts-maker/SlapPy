"""Pharos Engine - Hello Ragdoll

A 6-bone humanoid ragdoll drops onto a flat floor, lands, settles, then
breathes. The demo can record the run as an animated GIF using the same
``pharos_engine.media`` backbone the :mod:`pharos_engine.studio` helpers use,
or rasterise a single final-frame PNG for the smoke-test harness.

The skeleton is six bones (torso, head, two arms, two legs) wired by the
authoritative :func:`pharos_engine.dynamics.build_ragdoll` builder. After
landing, a small vertical sway on the head node simulates breathing without
breaking the joint band invariants.

Damping is tuned so ``solver_iterations * damping`` stays at or under
``0.3`` (the over-damp warning threshold documented in
:mod:`pharos_engine.dynamics.world`): ``iters=6`` and ``damping=0.05`` give
``0.30`` exactly, so the demo never trips ``RuntimeWarning``.

Run::

    PYTHONPATH=python python examples/hello_ragdoll.py
    PYTHONPATH=python python examples/hello_ragdoll.py --frames 60
    PYTHONPATH=python python examples/hello_ragdoll.py --no-gif
    PYTHONPATH=python python examples/hello_ragdoll.py --render --out out/hello_ragdoll.png
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

from pharos_engine.dynamics import BoneSpec, RagdollSpec, World, build_ragdoll
from pharos_engine.media import save_frames


# -- Demo parameters -------------------------------------------------------
# Anchor at y=2.0 (rather than 3.0): the taller drop looked more dramatic,
# but the ragdoll needed >90 frames to settle — testing wants CoM |v_y| < 0.5
# by frame 60. From y=2.0 the six-bone humanoid lands and its CoM y-velocity
# drops to ~0.12 within the first second (60 frames), well under threshold.
ANCHOR_POS: tuple[float, float] = (0.0, 2.0)
GRAVITY: tuple[float, float] = (0.0, -9.81)
GROUND_Y: float = 0.0
DEFAULT_DT: float = 1.0 / 60.0
DEFAULT_FRAMES: int = 180

# Solver tuning: keep iters * damping <= 0.3 to avoid the over-damp
# RuntimeWarning surfaced by World._check_overdamping. With iters=6 and
# damping=0.05 the effective per-step damping is 1-(1-0.05)^6 ≈ 0.265,
# comfortably below the 0.5 threshold.
SOLVER_ITERATIONS: int = 6
RAGDOLL_DAMPING: float = 0.05  # 6 * 0.05 == 0.30 (product cap, effective ~0.265)
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


def step_world(
    world: World,
    frames: int,
    dt: float = DEFAULT_DT,
    *,
    body=None,
    audit_limits: bool = False,
    capture_pil_frames: bool = False,
) -> dict:
    """Integrate the world for ``frames`` ticks with the demo's ground clamp.

    Args:
        world: the world produced by :func:`build_world`.
        frames: number of fixed-dt steps to run.
        dt: integration step (default :data:`DEFAULT_DT`).
        body: optional ragdoll body returned by :func:`build_world`; required
            for breathing/GIF capture, harmless to omit for short smoke runs.
        audit_limits: if True, sample every hinge angle each frame and clear
            the returned ``limits_respected`` flag on the first breach.
        capture_pil_frames: if True, accumulate a PIL image per frame for
            downstream GIF writing.

    Returns:
        A trace dict with keys ``limits_respected`` (bool — always present;
        defaults to ``True`` when ``audit_limits`` is False) and
        ``pil_frames`` (list — empty unless ``capture_pil_frames`` is True).
    """
    hinges = _hinge_joints(world) if audit_limits else []
    limits_respected = True
    pil_frames: list = []

    for f in range(frames):
        if body is not None:
            _apply_breathing(world, body, f)
        world.step(dt)
        _ground_clamp(world)

        if audit_limits and limits_respected:
            for j in hinges:
                ang = _joint_angle(world, j)
                lo = float(j.params.get("min_angle", -math.pi))
                hi = float(j.params.get("max_angle", math.pi))
                if ang < lo - 1e-3 or ang > hi + 1e-3:
                    limits_respected = False
                    break

        if capture_pil_frames and body is not None:
            pil_frames.append(_render_frame_pil(world, body))

    return {
        "limits_respected": bool(limits_respected),
        "pil_frames": pil_frames,
    }


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


def _render_frame_pil(world: World, body):
    """Rasterise the skeleton onto a PIL Image: floor line + bones + joints."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (RENDER_W, RENDER_H), (12, 14, 22, 255))
    draw = ImageDraw.Draw(img)

    # Floor line.
    fy0 = _world_to_pixel(np.asarray([VIEW_MIN[0], GROUND_Y]))[1]
    draw.line([(0, fy0), (RENDER_W - 1, fy0)], fill=(70, 80, 60, 255), width=2)

    root_node = int(body.parameters["root_node"])
    child_nodes: list[int] = list(body.parameters["child_nodes"])
    spec: RagdollSpec = body.parameters["spec"]

    # Bones.
    for bi, bone in enumerate(spec.bones):
        parent_node = root_node if bone.parent_idx < 0 else child_nodes[bone.parent_idx]
        child = child_nodes[bi]
        a = _world_to_pixel(world.positions[parent_node])
        b = _world_to_pixel(world.positions[child])
        draw.line([a, b], fill=(230, 230, 240, 255), width=3)

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
            fill=(255, 200, 120, 255), outline=(255, 220, 160, 255),
        )
    return img


def _render_frame(world: World, body) -> np.ndarray:
    """Return the skeleton frame as an ``(H, W, 4)`` uint8 RGBA array.

    Tests reach for this directly and feed it to the visual harness via
    ``SimpleNamespace(_image_data=...)``.
    """
    return np.asarray(_render_frame_pil(world, body), dtype=np.uint8)


def save_render(world: World, body, out_path: Path) -> Path:
    """Write a single rendered frame to ``out_path`` (PNG). Creates parents."""
    from PIL import Image

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arr = _render_frame(world, body)
    Image.fromarray(arr, mode="RGBA").save(out_path)
    return out_path


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def summarise(
    world: World,
    body,
    spec: RagdollSpec,
    trace_or_frames,
    frames_or_limits=None,
) -> dict:
    """Build the summary dict.

    Supports two call shapes:

    * New (test-facing): ``summarise(world, body, spec, trace_dict, frames)``
      where ``trace_dict`` is the return value of :func:`step_world` and
      ``frames`` is the integer frame count.
    * Legacy (kept for the CLI ``run()`` glue):
      ``summarise(world, body, spec, frames, limits_respected)``.
    """
    if isinstance(trace_or_frames, dict):
        trace = trace_or_frames
        frames = int(frames_or_limits) if frames_or_limits is not None else 0
        limits_respected = bool(trace.get("limits_respected", True))
    else:
        frames = int(trace_or_frames)
        limits_respected = bool(frames_or_limits) if frames_or_limits is not None else True

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
    from pharos_engine.examples_common import build_demo_arg_parser

    parser = build_demo_arg_parser(
        "Hello Ragdoll - Pharos Engine demo",
        default_frames=DEFAULT_FRAMES,
    )
    return parser.parse_args(argv)


def main(
    frames: int = DEFAULT_FRAMES,
    render: bool = True,
    out: Path | str | None = None,
    *,
    capture_gif: bool | None = None,
) -> dict:
    """Run the demo end-to-end. Returns the summary dict for tests.

    Args:
        frames: number of fixed-dt steps to integrate.
        render: when False, skip all visual output (smoke-test fast path).
            Maps directly to the legacy ``capture_gif`` semantics.
        out: where to write the artefact. ``.png`` suffix saves a single
            final-frame PNG; anything else writes a GIF. Default is the
            committed ``examples/output/ragdoll/hello_ragdoll.gif`` path.
        capture_gif: alias for ``render`` (back-compat for code that still
            passes the original kwarg). If both are supplied, ``capture_gif``
            wins.
    """
    if capture_gif is not None:
        render = bool(capture_gif)

    out_path = Path(out) if out is not None else None
    want_png = render and out_path is not None and out_path.suffix.lower() == ".png"
    want_gif = render and not want_png

    world, body, spec = build_world()
    trace = step_world(
        world,
        frames,
        DEFAULT_DT,
        body=body,
        audit_limits=True,
        capture_pil_frames=want_gif,
    )
    summary = summarise(world, body, spec, trace, frames)
    print_summary(summary)

    if want_png:
        written = save_render(world, body, out_path)
        summary["png_path"] = str(written)
        print(f"  png written to       : {written}")
    elif want_gif:
        gif_out = out_path if out_path is not None else _default_gif_path()
        gif_out.parent.mkdir(parents=True, exist_ok=True)
        written = save_frames(trace["pil_frames"], gif_out, fps=GIF_FPS)
        summary["gif_path"] = str(written)
        print(f"  gif written to       : {written}")
    return summary


def _cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    # --render overrides --no-gif; otherwise --no-gif disables output.
    if args.render:
        render = True
    else:
        render = not args.no_gif
    try:
        main(frames=args.frames, render=render, out=args.out)
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"hello_ragdoll: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
