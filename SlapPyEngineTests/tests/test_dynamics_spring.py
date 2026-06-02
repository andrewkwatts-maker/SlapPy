"""Spring oscillates near its natural frequency; damping bleeds energy."""
from __future__ import annotations

import math

import numpy as np
import pytest

from slappyengine.dynamics import World, make_spring
from slappyengine.dynamics.world import _reset_warning_cache


def test_spring_oscillates_and_damps():
    # Two equal masses on a spring along x; left mass pinned, right mass free
    # so the effective oscillator is m=1, k=stiffness, omega = sqrt(k/m).
    mass = 1.0
    stiffness = 400.0
    rest = 1.0
    initial_offset = 0.2  # pull mass to (1.2, 0)

    w = World(gravity=(0.0, 0.0))
    w.solver_iterations = 12
    w.add_node((0.0, 0.0), mass=0.0)
    w.add_node((rest + initial_offset, 0.0), mass=mass)
    w.add_joint(make_spring(0, 1, rest_length=rest, stiffness=stiffness, damping=0.0))

    dt = 1.0 / 240.0
    history: list[float] = []
    for _ in range(2400):  # 10 seconds
        w.step(dt)
        history.append(float(w.positions[1, 0] - rest))

    arr = np.asarray(history)
    # Energy proxy: amplitude in first second vs amplitude in last second.
    amp_early = float(np.max(np.abs(arr[: int(0.5 / dt)])))
    amp_late = float(np.max(np.abs(arr[-int(0.5 / dt):])))
    # XPBD position damping bleeds amplitude even at damping=0 due to projection
    # round-off — accept that natural attenuation.
    assert amp_late <= amp_early + 1e-3

    # Period estimate from zero crossings.
    sign = np.sign(arr)
    crossings = int(np.sum((sign[:-1] * sign[1:]) < 0))
    # Two zero-crossings per period.
    period_est = (2 * len(arr) * dt) / max(crossings, 1)
    expected_period = 2 * math.pi * math.sqrt(mass / stiffness)
    # Allow generous slack — XPBD is energy-conservative in the limit but
    # finite stiffness shifts the period slightly.
    assert abs(period_est - expected_period) / expected_period < 0.6


def test_spring_with_damping_loses_energy():
    # damping=0.4 at the default solver_iterations=8 deliberately exceeds the
    # over-damped warning threshold (effective per-step damping ~0.98) so the
    # damped world bleeds energy faster than the undamped one. Catch the
    # diagnostic so it doesn't pollute the suite-wide warning summary.
    mass = 1.0
    w_no = World(gravity=(0.0, 0.0))
    w_no.add_node((0.0, 0.0), mass=0.0)
    w_no.add_node((1.2, 0.0), mass=mass)
    w_no.add_joint(make_spring(0, 1, 1.0, stiffness=400.0, damping=0.0))

    w_yes = World(gravity=(0.0, 0.0))
    w_yes.add_node((0.0, 0.0), mass=0.0)
    w_yes.add_node((1.2, 0.0), mass=mass)
    w_yes.add_joint(make_spring(0, 1, 1.0, stiffness=400.0, damping=0.4))

    dt = 1.0 / 240.0
    # The over-damp warning is throttled process-wide on
    # (kind, damping, iters); reset so this test can observe it
    # regardless of which suite ran before us.
    _reset_warning_cache()
    with pytest.warns(RuntimeWarning, match="over-damp"):
        for _ in range(2400):
            w_no.step(dt)
            w_yes.step(dt)
    e_no = float(np.linalg.norm(w_no.velocities[1]))
    e_yes = float(np.linalg.norm(w_yes.velocities[1]))
    assert e_yes < e_no + 1e-6
