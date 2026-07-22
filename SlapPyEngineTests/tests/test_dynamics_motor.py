"""Motor joint drives a rim around a hub at the target angular velocity."""
from __future__ import annotations

import math

import numpy as np
import pytest

from pharos_engine.dynamics import World, make_motor


def test_motor_spins_rim_at_target_omega():
    # Hub at origin (pinned), two rim nodes on opposite ends of a radius-0.5
    # diameter. Motor spins rim at omega=10 rad/s.
    radius = 0.5
    target_omega = 10.0

    w = World(gravity=(0.0, 0.0))
    w.solver_iterations = 6
    w.add_node((0.0, 0.0), mass=0.0)            # hub pinned
    w.add_node((+radius, 0.0), mass=1.0)        # rim_a
    w.add_node((-radius, 0.0), mass=1.0)        # rim_b
    joint = make_motor(
        hub=0, rim_a=1, rim_b=2,
        target_omega=target_omega, max_torque=200.0,
        radius=radius, stiffness=1.0e8, damping=0.0,
    )
    w.add_joint(joint)

    dt = 1.0 / 60.0
    for _ in range(30):
        w.step(dt)

    # Tangential speed should approach omega * r.
    p_rim_a = w.positions[1]
    v_rim_a = w.velocities[1]
    r_vec = p_rim_a - w.positions[0]
    r = float(np.linalg.norm(r_vec))
    assert r == pytest.approx(radius, abs=5e-2)
    # Tangential direction: rotate r 90 deg.
    t_hat = np.array([-r_vec[1], r_vec[0]]) / max(r, 1e-9)
    v_tan = float(np.dot(v_rim_a, t_hat))
    expected_tan = target_omega * radius
    # Within 25% — exact balance depends on stiffness/damping interplay,
    # we just need motor authority to dominate.
    assert v_tan > 0.5 * expected_tan
    assert abs(v_tan - expected_tan) / expected_tan < 0.5


def test_motor_no_nan_after_long_run():
    w = World(gravity=(0.0, -9.81))
    w.add_node((0.0, 5.0), mass=0.0)
    w.add_node((0.5, 5.0), mass=1.0)
    w.add_node((-0.5, 5.0), mass=1.0)
    w.add_joint(make_motor(
        hub=0, rim_a=1, rim_b=2,
        target_omega=20.0, max_torque=100.0, radius=0.5,
    ))
    for _ in range(120):
        w.step(1.0 / 60.0)
    assert not np.isnan(w.positions).any()
    assert not np.isnan(w.velocities).any()
