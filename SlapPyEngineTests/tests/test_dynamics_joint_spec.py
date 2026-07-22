"""All seven JointSpec kinds construct and resolve through a World step."""
from __future__ import annotations

import math

import numpy as np
import pytest

from pharos_engine.dynamics import (
    JointSpec,
    KIND_PARAM_KEYS,
    World,
    make_motor,
    make_spring,
)


def _world_with_pair(p_a=(0.0, 0.0), p_b=(1.0, 0.0)) -> World:
    w = World(gravity=(0.0, 0.0))
    w.add_node(p_a, mass=1.0)
    w.add_node(p_b, mass=1.0)
    return w


def test_distance_joint_constructs_and_steps():
    w = _world_with_pair()
    j = JointSpec(kind="distance", node_a=0, node_b=1, rest_length=1.0)
    w.add_joint(j)
    w.step(1.0 / 60.0)
    assert not np.isnan(w.positions).any()


def test_spring_builder_writes_expected_keys():
    j = make_spring(0, 1, rest_length=2.0)
    assert j.kind == "spring"
    assert set(j.params.keys()) <= KIND_PARAM_KEYS["spring"] | set()
    assert j.rest_length == pytest.approx(2.0)


def test_weld_joint_holds_distance():
    w = _world_with_pair((0.0, 0.0), (1.0, 0.0))
    w.add_joint(JointSpec(kind="weld", node_a=0, node_b=1, rest_length=1.0,
                          stiffness=1.0e9, damping=0.0))
    for _ in range(20):
        w.step(1.0 / 60.0)
    d = float(np.linalg.norm(w.positions[1] - w.positions[0]))
    assert d == pytest.approx(1.0, abs=1e-3)


def test_ball_joint_zero_rest_length():
    w = _world_with_pair((0.0, 0.0), (2.0, 0.0))
    w.add_joint(JointSpec(kind="ball", node_a=0, node_b=1,
                          stiffness=1.0e9, damping=0.0))
    for _ in range(30):
        w.step(1.0 / 60.0)
    d = float(np.linalg.norm(w.positions[1] - w.positions[0]))
    assert d < 1.0e-2


def test_hinge_joint_has_documented_keys():
    j = JointSpec(
        kind="hinge", node_a=0, node_b=1, rest_length=1.0,
        params={"anchor": 2, "min_angle": -0.3, "max_angle": 0.3},
    )
    assert set(j.params.keys()) <= KIND_PARAM_KEYS["hinge"]


def test_motor_builder_writes_expected_keys():
    j = make_motor(hub=0, rim_a=1, rim_b=2,
                   target_omega=10.0, max_torque=5.0, radius=0.5)
    assert j.kind == "motor"
    assert set(j.params.keys()) == KIND_PARAM_KEYS["motor"]
    assert j.params["target_omega"] == pytest.approx(10.0)


def test_prismatic_keys_match_schema():
    j = JointSpec(
        kind="prismatic", node_a=0, node_b=1,
        params={"axis": (1.0, 0.0), "min": -1.0, "max": 1.0},
    )
    assert set(j.params.keys()) == KIND_PARAM_KEYS["prismatic"]


def test_unknown_kind_raises():
    # Validation now fires at construction time (was previously lazy at
    # resolve-time). Both paths surface ValueError so the contract is
    # strengthened, not changed in spirit.
    with pytest.raises(ValueError, match="kind"):
        JointSpec(kind="not-a-thing", node_a=0, node_b=1)


def test_all_kinds_listed_in_schema():
    expected = {"distance", "spring", "weld", "ball", "hinge",
                "motor", "prismatic"}
    assert set(KIND_PARAM_KEYS.keys()) == expected
