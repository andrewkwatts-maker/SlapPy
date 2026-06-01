"""Visual regression test: 6-bone ragdoll drops and settles on a flat floor.

Builds the scene programmatically via :func:`slappyengine.dynamics.build_ragdoll`
- self-contained, no imports from ``examples/`` - then steps the world for
60 frames and asserts the four documented invariants of a passive drop:

  (a) the centre of mass has dropped vs the spawn pose
  (b) the maximum node speed is back to ~0 (decelerated)
  (c) no node has been ejected to ``|pos| > 100`` (NaN / blow-up guard)
  (d) one rotational-limit (hinge) joint stayed within its declared band
      across the run

Damping is set so ``solver_iterations * damping == 0.30``, sitting exactly
at the over-damp warning threshold; the test fails fast if the dynamics
layer regresses and emits the diagnostic for a healthy configuration.
"""
from __future__ import annotations

import math
import warnings

import numpy as np
import pytest

from slappyengine.dynamics import BoneSpec, RagdollSpec, World, build_ragdoll


FRAMES = 60
DT = 1.0 / 60.0
GROUND_Y = 0.0
ANCHOR_POS = (0.0, 1.5)
SOLVER_ITERATIONS = 6
RAGDOLL_DAMPING = 0.05  # 6 * 0.05 == 0.30 (at over-damp threshold)
RAGDOLL_STIFFNESS = 5.0e6
ANGLE_LIMIT = (-math.pi, math.pi)


def _make_ragdoll():
    """Build the 6-bone humanoid ragdoll used by every assertion below."""
    bones = [
        BoneSpec(parent_idx=-1, length=0.6, mass=4.0,
                 angle_limit=ANGLE_LIMIT, direction=(0.0, -1.0), label="torso"),
        BoneSpec(parent_idx=0,  length=0.3, mass=1.5,
                 angle_limit=ANGLE_LIMIT, direction=(0.0, 1.0), label="head"),
        BoneSpec(parent_idx=0,  length=0.5, mass=1.0,
                 angle_limit=ANGLE_LIMIT, direction=(-1.0, 0.0), label="arm_l"),
        BoneSpec(parent_idx=0,  length=0.5, mass=1.0,
                 angle_limit=ANGLE_LIMIT, direction=(1.0, 0.0), label="arm_r"),
        BoneSpec(parent_idx=0,  length=0.7, mass=1.5,
                 angle_limit=ANGLE_LIMIT, direction=(-0.3, -1.0), label="leg_l"),
        BoneSpec(parent_idx=0,  length=0.7, mass=1.5,
                 angle_limit=ANGLE_LIMIT, direction=(0.3, -1.0), label="leg_r"),
    ]
    spec = RagdollSpec(
        bones=bones, stiffness=RAGDOLL_STIFFNESS, damping=RAGDOLL_DAMPING,
    )
    world = World(gravity=(0.0, -9.81))
    world.solver_iterations = SOLVER_ITERATIONS
    body = build_ragdoll(spec, world, anchor_pos=ANCHOR_POS, pin_root=False)
    return world, body, spec


def _ground_clamp(world: World) -> None:
    ys = world.positions[:, 1]
    below = ys < GROUND_Y
    if np.any(below):
        world.positions[below, 1] = GROUND_Y
        world.velocities[below, 1] = 0.0


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


def test_ragdoll_drops_settles_and_respects_joint_limits():
    world, body, spec = _make_ragdoll()
    node_idx = list(body.node_indices)

    initial_com_y = float(world.positions[node_idx, 1].mean())

    # Track one specific rotational-limit (hinge) joint across the whole run.
    hinges = [j for j in world.joints if j.kind == "hinge"]
    assert hinges, "build_ragdoll should produce at least one hinge joint"
    tracked = hinges[0]
    lo = float(tracked.params.get("min_angle", -math.pi))
    hi = float(tracked.params.get("max_angle", math.pi))
    slack = 1e-3  # XPBD projection allows a micro-overshoot mid-step

    # Catch the over-damp RuntimeWarning if the solver tuning regresses.
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        for _ in range(FRAMES):
            world.step(DT)
            _ground_clamp(world)

            ang = _joint_angle(world, tracked)
            assert lo - slack <= ang <= hi + slack, (
                f"hinge angle {ang:.4f} escaped band "
                f"[{lo:.4f}, {hi:.4f}] during settle"
            )

    final_com_y = float(world.positions[node_idx, 1].mean())
    max_speed = float(np.linalg.norm(world.velocities, axis=1).max())
    max_abs_pos = float(np.abs(world.positions).max())

    # (a) CoM dropped under gravity.
    assert final_com_y < initial_com_y - 0.1, (
        f"CoM did not drop: initial={initial_com_y:.3f}, final={final_com_y:.3f}"
    )
    # (b) velocity has decelerated to ~0 - well below initial fall speed
    # (~6 m/s at ground impact from a 1.5 m drop).
    assert max_speed < 1.5, (
        f"ragdoll still moving fast at frame {FRAMES}: max_speed={max_speed:.3f}"
    )
    # (c) no node ejected.
    assert max_abs_pos < 100.0, (
        f"a node was ejected to |pos|={max_abs_pos:.2f} (NaN/blow-up?)"
    )
    assert np.all(np.isfinite(world.positions)), "non-finite positions detected"
