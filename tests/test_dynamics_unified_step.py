"""Vehicle + rope + ragdoll coexist in one World.step() with no NaN."""
from __future__ import annotations

import math

import numpy as np
import pytest

from slappyengine.dynamics import (
    BoneSpec,
    RagdollSpec,
    RopeSpec,
    World,
    build_ragdoll,
    build_rope,
    make_motor,
    make_spring,
)


def _build_toy_vehicle(world: World, anchor=(0.0, 2.0)) -> tuple[int, int, int]:
    """Hub + two rim nodes wired with a motor — minimal vehicle stand-in."""
    hub = world.add_node(anchor, mass=2.0)
    rim_a = world.add_node((anchor[0] + 0.3, anchor[1]), mass=0.3)
    rim_b = world.add_node((anchor[0] - 0.3, anchor[1]), mass=0.3)
    world.add_joint(make_motor(
        hub=hub, rim_a=rim_a, rim_b=rim_b,
        target_omega=5.0, max_torque=10.0, radius=0.3,
    ))
    # Spring keeping rim nodes apart so they don't collapse to hub.
    world.add_joint(make_spring(rim_a, rim_b, rest_length=0.6))
    return hub, rim_a, rim_b


def _build_toy_ragdoll(world: World) -> None:
    spec = RagdollSpec(
        bones=[
            BoneSpec(parent_idx=-1, length=0.4, mass=1.0,
                     direction=(0.0, 1.0)),
            BoneSpec(parent_idx=0, length=0.3, mass=0.5,
                     direction=(0.0, 1.0),
                     angle_limit=(-0.4, 0.4)),
            BoneSpec(parent_idx=0, length=0.3, mass=0.5,
                     direction=(-0.5, -1.0),
                     angle_limit=(-0.4, 0.4)),
        ],
        stiffness=1.0e7,
    )
    build_ragdoll(spec, world, anchor_pos=(4.0, 4.0), pin_root=True)


def _build_toy_rope(world: World) -> None:
    # damping=0.037 keeps effective per-step damping (~0.26 at iters=8) below
    # the 0.5 over-damped warning threshold while still bleeding rope energy.
    spec = RopeSpec(node_count=8, total_length=2.0, mass_per_node=0.05,
                    stiffness=1.0e6, damping=0.037)
    build_rope(spec, world, anchor_a=(-3.0, 5.0), anchor_b=(-1.0, 5.0))


def test_unified_step_no_nan_after_60_frames():
    w = World(gravity=(0.0, -9.81))
    w.solver_iterations = 8

    _build_toy_vehicle(w)
    _build_toy_rope(w)
    _build_toy_ragdoll(w)

    initial_mass_sum = float(np.sum(np.where(w.inv_masses > 0,
                                             1.0 / np.where(w.inv_masses > 0,
                                                            w.inv_masses, 1.0),
                                             0.0)))
    for _ in range(60):
        w.step(1.0 / 60.0)

    assert not np.isnan(w.positions).any()
    assert not np.isnan(w.velocities).any()
    # Mass conserved (we never add or remove nodes mid-step).
    final_mass_sum = float(np.sum(np.where(w.inv_masses > 0,
                                           1.0 / np.where(w.inv_masses > 0,
                                                          w.inv_masses, 1.0),
                                           0.0)))
    assert final_mass_sum == pytest.approx(initial_mass_sum, rel=1e-9)


def test_unified_step_bodies_registered():
    w = World(gravity=(0.0, -9.81))
    _build_toy_vehicle(w)
    _build_toy_rope(w)
    _build_toy_ragdoll(w)
    kinds = sorted({b.kind for b in w.bodies})
    assert "rope" in kinds
    assert "ragdoll" in kinds


def test_unified_step_joints_all_active():
    w = World(gravity=(0.0, -9.81))
    _build_toy_vehicle(w)
    _build_toy_rope(w)
    for _ in range(30):
        w.step(1.0 / 60.0)
    # No joint should have broken under nominal play.
    assert all(j.enabled for j in w.joints)
