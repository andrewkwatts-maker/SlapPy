"""Input-validation tests for the public ``slappyengine.dynamics`` API.

Engineering policy: validate at system boundaries, refuse bad input loudly
rather than silently coercing it to a default. Each test in this file
exercises one rejection path with a precise substring match so messages
stay useful for callers debugging their authoring code.

Positive paths live alongside the existing ``tests/test_dynamics_*.py``;
this file only covers the rejection contract.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from slappyengine.dynamics import (
    BoneSpec,
    IKChainSpec,
    JointSpec,
    RagdollSpec,
    RopeSpec,
    World,
    build_ragdoll,
    build_rope,
    make_motor,
    make_spring,
    solve_ik,
)


# ---------------------------------------------------------------------------
# JointSpec.__post_init__
# ---------------------------------------------------------------------------

def test_jointspec_rejects_unknown_kind():
    with pytest.raises(ValueError, match="JointSpec.kind"):
        JointSpec(kind="banana", node_a=0, node_b=1)


def test_jointspec_rejects_non_string_kind():
    with pytest.raises(TypeError, match="JointSpec.kind"):
        JointSpec(kind=42, node_a=0, node_b=1)  # type: ignore[arg-type]


def test_jointspec_rejects_equal_node_indices():
    with pytest.raises(ValueError, match="node_a and node_b must differ"):
        JointSpec(kind="distance", node_a=3, node_b=3)


def test_jointspec_rejects_negative_node_index():
    with pytest.raises(ValueError, match="non-negative"):
        JointSpec(kind="distance", node_a=-1, node_b=2)


def test_jointspec_rejects_negative_rest_length():
    with pytest.raises(ValueError, match="rest_length"):
        JointSpec(kind="distance", node_a=0, node_b=1, rest_length=-0.5)


def test_jointspec_rejects_zero_stiffness():
    with pytest.raises(ValueError, match="stiffness"):
        JointSpec(kind="distance", node_a=0, node_b=1, stiffness=0.0)


def test_jointspec_rejects_damping_above_one():
    with pytest.raises(ValueError, match="damping"):
        JointSpec(kind="distance", node_a=0, node_b=1, damping=1.5)


def test_jointspec_rejects_negative_damping():
    with pytest.raises(ValueError, match="damping"):
        JointSpec(kind="distance", node_a=0, node_b=1, damping=-0.1)


def test_jointspec_rejects_non_dict_params():
    with pytest.raises(TypeError, match="params"):
        JointSpec(kind="distance", node_a=0, node_b=1, params=[1, 2])  # type: ignore[arg-type]


def test_jointspec_rejects_zero_break_force():
    with pytest.raises(ValueError, match="break_force"):
        JointSpec(kind="distance", node_a=0, node_b=1, break_force=0.0)


def test_jointspec_accepts_inf_break_force_by_default():
    j = JointSpec(kind="distance", node_a=0, node_b=1)
    assert j.break_force == math.inf


def test_jointspec_rejects_nan_break_force():
    with pytest.raises(ValueError, match="break_force"):
        JointSpec(kind="distance", node_a=0, node_b=1,
                  break_force=float("nan"))


# ---------------------------------------------------------------------------
# RopeSpec.__post_init__
# ---------------------------------------------------------------------------

def test_ropespec_rejects_single_node():
    with pytest.raises(ValueError, match="node_count"):
        RopeSpec(node_count=1, total_length=1.0)


def test_ropespec_rejects_zero_total_length():
    with pytest.raises(ValueError, match="total_length"):
        RopeSpec(node_count=5, total_length=0.0)


def test_ropespec_rejects_negative_mass():
    with pytest.raises(ValueError, match="mass_per_node"):
        RopeSpec(node_count=5, total_length=1.0, mass_per_node=-0.1)


def test_ropespec_rejects_zero_stiffness():
    with pytest.raises(ValueError, match="stiffness"):
        RopeSpec(node_count=5, total_length=1.0, stiffness=0.0)


def test_ropespec_rejects_damping_above_one():
    with pytest.raises(ValueError, match="damping"):
        RopeSpec(node_count=5, total_length=1.0, damping=2.0)


def test_ropespec_rejects_inf_total_length():
    with pytest.raises(ValueError, match="total_length"):
        RopeSpec(node_count=5, total_length=float("inf"))


def test_ropespec_rejects_negative_bend_stiffness():
    with pytest.raises(ValueError, match="bend_stiffness"):
        RopeSpec(node_count=5, total_length=1.0, bend_stiffness=-1.0)


# ---------------------------------------------------------------------------
# build_rope
# ---------------------------------------------------------------------------

def _ok_rope_spec() -> RopeSpec:
    return RopeSpec(node_count=5, total_length=1.0)


def test_build_rope_rejects_non_ropespec():
    w = World()
    with pytest.raises(TypeError, match="build_rope: spec"):
        build_rope("not-a-spec", w, (0.0, 0.0), (1.0, 0.0))  # type: ignore[arg-type]


def test_build_rope_rejects_non_world():
    with pytest.raises(TypeError, match="build_rope: world"):
        build_rope(_ok_rope_spec(), object(), (0.0, 0.0), (1.0, 0.0))


def test_build_rope_rejects_3_tuple_anchor():
    w = World()
    with pytest.raises(ValueError, match="anchor_a"):
        build_rope(_ok_rope_spec(), w, (0.0, 0.0, 0.0), (1.0, 0.0))  # type: ignore[arg-type]


def test_build_rope_rejects_nan_anchor():
    w = World()
    with pytest.raises(ValueError, match="anchor_b"):
        build_rope(_ok_rope_spec(), w, (0.0, 0.0), (float("nan"), 0.0))


def test_build_rope_rejects_identical_anchors():
    w = World()
    with pytest.raises(ValueError, match="anchor_a and anchor_b must differ"):
        build_rope(_ok_rope_spec(), w, (1.0, 2.0), (1.0, 2.0))


def test_build_rope_rejects_string_anchor():
    w = World()
    with pytest.raises(TypeError, match="anchor_a"):
        build_rope(_ok_rope_spec(), w, "origin", (1.0, 0.0))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# BoneSpec / RagdollSpec / build_ragdoll
# ---------------------------------------------------------------------------

def test_bonespec_rejects_zero_length():
    with pytest.raises(ValueError, match="BoneSpec.length"):
        BoneSpec(length=0.0)


def test_bonespec_rejects_negative_mass():
    with pytest.raises(ValueError, match="BoneSpec.mass"):
        BoneSpec(mass=-1.0)


def test_bonespec_rejects_inverted_angle_limit():
    with pytest.raises(ValueError, match="angle_limit"):
        BoneSpec(angle_limit=(0.5, -0.5))


def test_bonespec_rejects_bad_direction_shape():
    with pytest.raises(ValueError, match="direction"):
        BoneSpec(direction=(1.0, 0.0, 0.0))  # type: ignore[arg-type]


def test_ragdollspec_rejects_empty_bones():
    with pytest.raises(ValueError, match="RagdollSpec.bones"):
        RagdollSpec(bones=[])


def test_ragdollspec_rejects_out_of_range_parent():
    with pytest.raises(ValueError, match="parent_idx"):
        RagdollSpec(bones=[
            BoneSpec(parent_idx=-1),
            BoneSpec(parent_idx=99),
        ])


def test_ragdollspec_rejects_forward_parent_reference():
    # bones[0].parent_idx=1 would reference a bone that hasn't been built yet.
    with pytest.raises(ValueError, match="parent_idx"):
        RagdollSpec(bones=[
            BoneSpec(parent_idx=1),
            BoneSpec(parent_idx=-1),
        ])


def test_ragdollspec_rejects_non_bone_entries():
    with pytest.raises(TypeError, match="bones"):
        RagdollSpec(bones=["not-a-bone"])  # type: ignore[list-item]


def test_ragdollspec_rejects_zero_stiffness():
    with pytest.raises(ValueError, match="RagdollSpec.stiffness"):
        RagdollSpec(bones=[BoneSpec()], stiffness=0.0)


def test_build_ragdoll_rejects_non_ragdollspec():
    w = World()
    with pytest.raises(TypeError, match="build_ragdoll: spec"):
        build_ragdoll("nope", w, (0.0, 0.0))  # type: ignore[arg-type]


def test_build_ragdoll_rejects_non_world():
    spec = RagdollSpec(bones=[BoneSpec()])
    with pytest.raises(TypeError, match="build_ragdoll: world"):
        build_ragdoll(spec, object(), (0.0, 0.0))


def test_build_ragdoll_rejects_infinite_anchor():
    spec = RagdollSpec(bones=[BoneSpec()])
    w = World()
    with pytest.raises(ValueError, match="anchor_pos"):
        build_ragdoll(spec, w, (0.0, float("inf")))


def test_build_ragdoll_rejects_short_anchor():
    spec = RagdollSpec(bones=[BoneSpec()])
    w = World()
    with pytest.raises(ValueError, match="anchor_pos"):
        build_ragdoll(spec, w, (0.0,))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# IKChainSpec / solve_ik
# ---------------------------------------------------------------------------

def test_ikchainspec_rejects_empty_nodes():
    with pytest.raises(ValueError, match="node_indices"):
        IKChainSpec(node_indices=[], target=(0.0, 0.0))


def test_ikchainspec_rejects_negative_node_index():
    with pytest.raises(ValueError, match="node_indices"):
        IKChainSpec(node_indices=[0, -1, 2], target=(0.0, 0.0))


def test_ikchainspec_rejects_non_finite_target():
    with pytest.raises(ValueError, match="target"):
        IKChainSpec(node_indices=[0, 1], target=(float("inf"), 0.0))


def test_ikchainspec_rejects_3_tuple_target():
    with pytest.raises(ValueError, match="target"):
        IKChainSpec(node_indices=[0, 1], target=(1.0, 2.0, 3.0))  # type: ignore[arg-type]


def test_solve_ik_rejects_non_spec():
    w = World()
    w.add_node((0.0, 0.0))
    w.add_node((1.0, 0.0))
    with pytest.raises(TypeError, match="solve_ik: spec"):
        solve_ik("nope", w)  # type: ignore[arg-type]


def test_solve_ik_rejects_non_world():
    spec = IKChainSpec(node_indices=[0, 1], target=(1.0, 1.0))
    with pytest.raises(TypeError, match="solve_ik: world"):
        solve_ik(spec, object())


def test_solve_ik_rejects_zero_iterations():
    spec = IKChainSpec(node_indices=[0, 1], target=(1.0, 1.0))
    w = World()
    w.add_node((0.0, 0.0))
    w.add_node((1.0, 0.0))
    with pytest.raises(ValueError, match="iterations"):
        solve_ik(spec, w, iterations=0)


def test_solve_ik_rejects_negative_iterations():
    spec = IKChainSpec(node_indices=[0, 1], target=(1.0, 1.0))
    w = World()
    w.add_node((0.0, 0.0))
    w.add_node((1.0, 0.0))
    with pytest.raises(ValueError, match="iterations"):
        solve_ik(spec, w, iterations=-5)


def test_solve_ik_rejects_zero_tolerance():
    spec = IKChainSpec(node_indices=[0, 1], target=(1.0, 1.0))
    w = World()
    w.add_node((0.0, 0.0))
    w.add_node((1.0, 0.0))
    with pytest.raises(ValueError, match="tolerance"):
        solve_ik(spec, w, tolerance=0.0)


def test_solve_ik_rejects_nan_tolerance():
    spec = IKChainSpec(node_indices=[0, 1], target=(1.0, 1.0))
    w = World()
    w.add_node((0.0, 0.0))
    w.add_node((1.0, 0.0))
    with pytest.raises(ValueError, match="tolerance"):
        solve_ik(spec, w, tolerance=float("nan"))


# ---------------------------------------------------------------------------
# make_spring
# ---------------------------------------------------------------------------

def test_make_spring_rejects_negative_index():
    with pytest.raises(ValueError, match="make_spring: node_a"):
        make_spring(-1, 2, rest_length=1.0)


def test_make_spring_rejects_equal_indices():
    with pytest.raises(ValueError, match="must differ"):
        make_spring(3, 3, rest_length=1.0)


def test_make_spring_rejects_negative_rest_length():
    with pytest.raises(ValueError, match="rest_length"):
        make_spring(0, 1, rest_length=-1.0)


def test_make_spring_rejects_zero_stiffness():
    with pytest.raises(ValueError, match="stiffness"):
        make_spring(0, 1, rest_length=1.0, stiffness=0.0)


def test_make_spring_rejects_damping_above_one():
    with pytest.raises(ValueError, match="damping"):
        make_spring(0, 1, rest_length=1.0, damping=1.1)


def test_make_spring_rejects_non_int_index():
    with pytest.raises(TypeError, match="make_spring: node_a"):
        make_spring("zero", 1, rest_length=1.0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# make_motor
# ---------------------------------------------------------------------------

def test_make_motor_rejects_negative_index():
    with pytest.raises(ValueError, match="make_motor: rim_a"):
        make_motor(hub=0, rim_a=-1, rim_b=2,
                   target_omega=5.0, max_torque=1.0)


def test_make_motor_rejects_hub_equals_rim():
    with pytest.raises(ValueError, match="hub must differ"):
        make_motor(hub=1, rim_a=1, rim_b=2,
                   target_omega=5.0, max_torque=1.0)


def test_make_motor_rejects_zero_max_torque():
    with pytest.raises(ValueError, match="max_torque"):
        make_motor(hub=0, rim_a=1, rim_b=2,
                   target_omega=5.0, max_torque=0.0)


def test_make_motor_rejects_negative_max_torque():
    with pytest.raises(ValueError, match="max_torque"):
        make_motor(hub=0, rim_a=1, rim_b=2,
                   target_omega=5.0, max_torque=-1.0)


def test_make_motor_rejects_inf_target_omega():
    with pytest.raises(ValueError, match="target_omega"):
        make_motor(hub=0, rim_a=1, rim_b=2,
                   target_omega=float("inf"), max_torque=1.0)


def test_make_motor_rejects_nan_target_omega():
    with pytest.raises(ValueError, match="target_omega"):
        make_motor(hub=0, rim_a=1, rim_b=2,
                   target_omega=float("nan"), max_torque=1.0)


def test_make_motor_rejects_negative_radius():
    with pytest.raises(ValueError, match="radius"):
        make_motor(hub=0, rim_a=1, rim_b=2,
                   target_omega=5.0, max_torque=1.0, radius=-0.1)


def test_make_motor_rejects_bad_axis_shape():
    with pytest.raises(TypeError, match="axis"):
        make_motor(hub=0, rim_a=1, rim_b=2,
                   target_omega=5.0, max_torque=1.0,
                   axis=(1.0, 0.0, 0.0))  # type: ignore[arg-type]


def test_make_motor_rejects_equal_rims():
    with pytest.raises(ValueError, match="rim_a and rim_b must differ"):
        make_motor(hub=0, rim_a=1, rim_b=1,
                   target_omega=5.0, max_torque=1.0)


# ---------------------------------------------------------------------------
# Smoke: validated builders still produce a working scene end-to-end.
# (Catches the case where over-aggressive validation rejects legal input.)
# ---------------------------------------------------------------------------

def test_validated_builders_still_compose_a_working_world():
    w = World(gravity=(0.0, -9.81))
    w.solver_iterations = 4
    # Rope
    rope_body = build_rope(
        RopeSpec(node_count=4, total_length=1.0),
        w,
        anchor_a=(-0.5, 2.0),
        anchor_b=(0.5, 2.0),
    )
    # Ragdoll
    ragdoll_body = build_ragdoll(
        RagdollSpec(bones=[BoneSpec(length=0.3)]),
        w,
        anchor_pos=(0.0, 1.0),
    )
    # Spring and motor between fresh nodes
    hub = w.add_node((1.0, 0.5), mass=1.0)
    rim_a = w.add_node((1.2, 0.5), mass=0.5)
    rim_b = w.add_node((0.8, 0.5), mass=0.5)
    w.add_joint(make_spring(hub, rim_a, rest_length=0.2))
    w.add_joint(make_motor(hub=hub, rim_a=rim_a, rim_b=rim_b,
                           target_omega=2.0, max_torque=1.0, radius=0.2))
    # IK chain on the rope nodes (purely a smoke; not expected to converge)
    ik_spec = IKChainSpec(
        node_indices=list(rope_body.node_indices),
        target=(0.0, 1.5),
    )
    solve_ik(ik_spec, w, iterations=3, tolerance=0.1)

    for _ in range(10):
        w.step(1.0 / 60.0)
    assert not np.isnan(w.positions).any()
    assert ragdoll_body.kind == "ragdoll"
    assert rope_body.kind == "rope"
