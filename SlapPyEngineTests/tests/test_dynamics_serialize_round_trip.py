"""Round-trip tests for every spec kind in :mod:`slappyengine.dynamics.serialize`.

Sprint 7E surface regen pinned ``dynamics.serialize`` as a public submodule.
Round 1 (Body / JointSpec / SpringSpec / MotorSpec / RopeSpec) and Round 2
(RagdollSpec / BoneSpec / IKChainSpec / Humanoid / Material) added new types
that must save → load byte-identical for their primitive fields.

This module covers:

* Per-spec ``*_to_dict`` / ``*_from_dict`` round trips for primitive fields.
* :class:`Humanoid` round-trips all 15 named bone nodes, the bone-lengths
  table, and the two flesh-slice dicts populated by ``build_flesh_wrap``.
* A built world that mixes a rope, a ragdoll, and a motor saves to JSON
  and loads back with identical bodies / joints / scalar tuning.
* Strict JSON-safety for ``JointSpec.params``: numpy floats coerce to
  Python floats, unsupported value types raise :class:`TypeError`.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from slappyengine.dynamics import (
    BoneSpec,
    Body,
    Humanoid,
    IKChainSpec,
    JointSpec,
    LAYER_BONE,
    Material,
    MotorSpec,
    RagdollSpec,
    RopeSpec,
    SpringSpec,
    World,
    body_from_dict,
    body_to_dict,
    bone_spec_from_dict,
    bone_spec_to_dict,
    build_ragdoll,
    build_rope,
    humanoid_from_dict,
    humanoid_to_dict,
    ik_chain_from_dict,
    ik_chain_to_dict,
    joint_from_dict,
    joint_to_dict,
    load_world,
    build_humanoid,
    make_motor,
    make_spring,
    material_from_dict,
    material_to_dict,
    motor_from_dict,
    motor_to_dict,
    ragdoll_spec_from_dict,
    ragdoll_spec_to_dict,
    rope_spec_from_dict,
    rope_spec_to_dict,
    save_world,
    spring_from_dict,
    spring_to_dict,
    world_from_dict,
    world_to_dict,
    build_flesh_wrap,
)
from slappyengine.softbody import SoftBodyWorld


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _through_json(d: dict) -> dict:
    """Push a dict through :mod:`json` so we catch anything that looks JSON-
    safe but actually contains a non-serialisable value."""
    return json.loads(json.dumps(d))


# ---------------------------------------------------------------------------
# Material
# ---------------------------------------------------------------------------


def test_material_round_trip_default():
    mat = Material()
    d = _through_json(material_to_dict(mat))
    mat2 = material_from_dict(d)
    assert mat2.name == mat.name
    assert mat2.density == mat.density
    assert mat2.stiffness == mat.stiffness
    assert mat2.damping == mat.damping
    assert mat2.restitution == mat.restitution
    assert mat2.friction == mat.friction
    assert math.isinf(mat2.breaking_strain)
    assert mat2.properties == {}


def test_material_round_trip_custom_properties():
    mat = Material(
        name="rubber",
        density=950.0,
        stiffness=2.5e5,
        damping=0.12,
        restitution=0.8,
        friction=0.95,
        breaking_strain=0.35,
        properties={"hardness": 60, "color": "black", "alpha": 0.5},
    )
    d = _through_json(material_to_dict(mat))
    mat2 = material_from_dict(d)
    assert mat2.name == "rubber"
    assert mat2.breaking_strain == pytest.approx(0.35)
    assert mat2.properties == {"hardness": 60, "color": "black", "alpha": 0.5}


def test_material_to_dict_rejects_non_material():
    with pytest.raises(TypeError, match="expected Material"):
        material_to_dict({"density": 1.0})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Body
# ---------------------------------------------------------------------------


def test_body_round_trip_primitive_fields():
    b = Body(
        kind="lattice",
        parameters={"width": 3, "height": 5, "scale": 1.5},
        node_offset=4,
        node_count=15,
        label="hull",
    )
    d = _through_json(body_to_dict(b))
    b2 = body_from_dict(d)
    assert b2.kind == "lattice"
    assert b2.node_offset == 4
    assert b2.node_count == 15
    assert b2.label == "hull"
    assert b2.parameters == {"width": 3, "height": 5, "scale": 1.5}


def test_body_to_dict_rejects_non_body():
    with pytest.raises(TypeError, match="expected Body"):
        body_to_dict({"kind": "lattice"})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# JointSpec — all seven kinds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,extra_params",
    [
        ("distance", {}),
        ("spring", {}),
        ("weld", {"rest_offset": (0.1, -0.2)}),
        ("ball", {}),
        ("hinge", {"anchor": 7, "min_angle": -1.5, "max_angle": 1.5}),
        (
            "motor",
            {"hub": 3, "axis": (0.0, 1.0), "target_omega": 6.283, "max_torque": 100.0},
        ),
        ("prismatic", {"axis": (1.0, 0.0), "min": -0.5, "max": 0.5}),
    ],
)
def test_joint_round_trip_every_kind(kind: str, extra_params: dict):
    j = JointSpec(
        kind=kind,
        node_a=0,
        node_b=1,
        rest_length=1.0,
        stiffness=1.0e6,
        damping=0.1,
        params=extra_params,
        break_force=42.5,
        enabled=True,
    )
    d = _through_json(joint_to_dict(j))
    j2 = joint_from_dict(d)
    assert j2.kind == kind
    assert j2.node_a == 0
    assert j2.node_b == 1
    assert j2.rest_length == 1.0
    assert j2.stiffness == 1.0e6
    assert j2.damping == 0.1
    assert j2.break_force == 42.5
    assert j2.enabled is True
    # Each kind's specific params should survive a JSON round trip.
    for k, expected in extra_params.items():
        got = j2.params[k]
        if isinstance(expected, tuple):
            assert list(got) == list(expected)
        else:
            assert got == expected


def test_joint_params_coerces_numpy_floats():
    """numpy scalars in params should land as Python floats on reload."""
    j = JointSpec(
        kind="motor",
        node_a=0,
        node_b=1,
        rest_length=1.0,
        params={
            "hub": np.int64(5),
            "target_omega": np.float32(6.28),
            "max_torque": np.float64(100.0),
            "axis": np.array([0.0, 1.0]),
        },
    )
    d = joint_to_dict(j)
    # All scalar leaves should be JSON-trivial — float / int / bool / str /
    # None / list / dict. No numpy types should survive into the dict.
    encoded = json.dumps(d)  # must not raise
    j2 = joint_from_dict(json.loads(encoded))
    assert isinstance(j2.params["hub"], int)
    assert isinstance(j2.params["target_omega"], float)
    assert isinstance(j2.params["max_torque"], float)
    assert list(j2.params["axis"]) == [0.0, 1.0]


def test_joint_params_rejects_unsupported_type():
    """An opaque object inside params should fail loudly at encode time."""

    class Opaque:
        pass

    j = JointSpec(
        kind="distance",
        node_a=0,
        node_b=1,
        rest_length=1.0,
        params={"widget": Opaque()},
    )
    with pytest.raises(TypeError, match="cannot serialise value"):
        joint_to_dict(j)


def test_joint_params_rejects_unsupported_inside_nested_dict():
    class Opaque:
        pass

    j = JointSpec(
        kind="distance",
        node_a=0,
        node_b=1,
        rest_length=1.0,
        params={"outer": {"inner": Opaque()}},
    )
    with pytest.raises(TypeError, match="params.outer.inner"):
        joint_to_dict(j)


# ---------------------------------------------------------------------------
# SpringSpec
# ---------------------------------------------------------------------------


def test_spring_spec_round_trip():
    sp = SpringSpec(
        node_a=2,
        node_b=5,
        rest_length=1.5,
        stiffness=3.0e5,
        damping=0.1,
        params={"label": "suspension"},
    )
    d = _through_json(spring_to_dict(sp))
    sp2 = spring_from_dict(d)
    assert sp2.node_a == 2
    assert sp2.node_b == 5
    assert sp2.rest_length == 1.5
    assert sp2.stiffness == 3.0e5
    assert sp2.damping == 0.1
    assert sp2.params == {"label": "suspension"}


# ---------------------------------------------------------------------------
# MotorSpec
# ---------------------------------------------------------------------------


def test_motor_spec_round_trip():
    m = MotorSpec(
        hub=0,
        rim_a=1,
        rim_b=2,
        target_omega=12.5,
        max_torque=80.0,
        radius=0.4,
        axis=(0.0, 1.0),
        stiffness=2.0e8,
        damping=0.05,
        params={"role": "front_left"},
    )
    d = _through_json(motor_to_dict(m))
    m2 = motor_from_dict(d)
    assert m2.hub == 0
    assert m2.rim_a == 1
    assert m2.rim_b == 2
    assert m2.target_omega == 12.5
    assert m2.max_torque == 80.0
    assert m2.radius == 0.4
    assert m2.axis == (0.0, 1.0)
    assert m2.stiffness == 2.0e8
    assert m2.damping == 0.05
    assert m2.params == {"role": "front_left"}


# ---------------------------------------------------------------------------
# RopeSpec
# ---------------------------------------------------------------------------


def test_rope_spec_round_trip_all_fields():
    rs = RopeSpec(
        node_count=12,
        total_length=3.5,
        mass_per_node=0.08,
        stiffness=2.5e6,
        damping=0.07,
        bend_stiffness=1.0e3,
        anchor_a_pinned=False,
        anchor_b_pinned=True,
        params={"material": "hemp"},
    )
    d = _through_json(rope_spec_to_dict(rs))
    rs2 = rope_spec_from_dict(d)
    assert rs2.node_count == 12
    assert rs2.total_length == 3.5
    assert rs2.mass_per_node == 0.08
    assert rs2.stiffness == 2.5e6
    assert rs2.damping == 0.07
    assert rs2.bend_stiffness == 1.0e3
    assert rs2.anchor_a_pinned is False
    assert rs2.anchor_b_pinned is True
    assert rs2.params == {"material": "hemp"}


# ---------------------------------------------------------------------------
# BoneSpec + RagdollSpec
# ---------------------------------------------------------------------------


def test_bone_spec_round_trip():
    b = BoneSpec(
        parent_idx=2,
        length=0.55,
        mass=1.2,
        angle_limit=(-1.0, 1.0),
        direction=(0.0, -1.0),
        label="upper_leg",
    )
    d = _through_json(bone_spec_to_dict(b))
    b2 = bone_spec_from_dict(d)
    assert b2.parent_idx == 2
    assert b2.length == 0.55
    assert b2.mass == 1.2
    assert b2.angle_limit == (-1.0, 1.0)
    assert b2.direction == (0.0, -1.0)
    assert b2.label == "upper_leg"


def test_ragdoll_spec_round_trip():
    spec = RagdollSpec(
        bones=[
            BoneSpec(parent_idx=-1, length=0.5, mass=2.0, label="pelvis"),
            BoneSpec(
                parent_idx=0,
                length=0.4,
                mass=1.0,
                direction=(0.0, -1.0),
                angle_limit=(-0.5, 0.5),
                label="spine",
            ),
            BoneSpec(
                parent_idx=1,
                length=0.2,
                mass=0.8,
                direction=(0.0, -1.0),
                label="head",
            ),
        ],
        joints=[
            JointSpec(
                kind="spring",
                node_a=0,
                node_b=2,
                rest_length=0.6,
                stiffness=5.0e5,
                damping=0.1,
            )
        ],
        stiffness=4.5e6,
        damping=0.04,
    )
    d = _through_json(ragdoll_spec_to_dict(spec))
    spec2 = ragdoll_spec_from_dict(d)
    assert len(spec2.bones) == 3
    assert spec2.bones[0].label == "pelvis"
    assert spec2.bones[2].direction == (0.0, -1.0)
    assert len(spec2.joints) == 1
    assert spec2.joints[0].kind == "spring"
    assert spec2.stiffness == 4.5e6
    assert spec2.damping == 0.04


# ---------------------------------------------------------------------------
# IKChainSpec
# ---------------------------------------------------------------------------


def test_ik_chain_round_trip():
    ik = IKChainSpec(
        node_indices=[0, 1, 2, 3],
        target=(2.5, -1.3),
        fixed_root=False,
        params={"tolerance": 0.01},
    )
    d = _through_json(ik_chain_to_dict(ik))
    ik2 = ik_chain_from_dict(d)
    assert ik2.node_indices == [0, 1, 2, 3]
    assert ik2.target == (2.5, -1.3)
    assert ik2.fixed_root is False
    assert ik2.params == {"tolerance": 0.01}


# ---------------------------------------------------------------------------
# Humanoid: 15 nodes + bone names + flesh slices
# ---------------------------------------------------------------------------


def _bare_softbody_world() -> SoftBodyWorld:
    w = SoftBodyWorld()
    w.config["floor_y"] = 100.0
    w.config["contact"]["enabled"] = False
    w.config["gravity"] = [0.0, 0.0]
    return w


def test_humanoid_round_trip_15_named_nodes():
    world = _bare_softbody_world()
    skel = build_humanoid(world, root_position=(0.0, 1.0))
    d = _through_json(humanoid_to_dict(skel))
    skel2 = humanoid_from_dict(d)

    bone_names = (
        "pelvis", "neck", "head",
        "shoulder_l", "elbow_l", "wrist_l",
        "shoulder_r", "elbow_r", "wrist_r",
        "hip_l", "knee_l", "ankle_l",
        "hip_r", "knee_r", "ankle_r",
    )
    assert len(bone_names) == 15
    for name in bone_names:
        assert getattr(skel2, name) == getattr(skel, name), (
            f"humanoid round trip lost {name}"
        )
    # node_slice / beam_slice are tuples on reload.
    assert skel2.node_slice == skel.node_slice
    assert skel2.beam_slice == skel.beam_slice
    assert skel2.body_id == skel.body_id
    # 15 bone nodes inside the recorded slice.
    ns, ne = skel2.node_slice
    assert ne - ns == 15
    # bone_lengths table preserved value-for-value.
    assert skel2.bone_lengths.keys() == skel.bone_lengths.keys()
    for k, v in skel.bone_lengths.items():
        assert skel2.bone_lengths[k] == pytest.approx(v)


def test_humanoid_round_trip_includes_flesh_slices():
    world = _bare_softbody_world()
    skel = build_humanoid(world, root_position=(0.0, 1.0))
    build_flesh_wrap(world, skel)
    assert set(skel.flesh_node_slices) == {"muscle", "skin"}

    d = _through_json(humanoid_to_dict(skel))
    skel2 = humanoid_from_dict(d)
    assert set(skel2.flesh_node_slices) == {"muscle", "skin"}
    for layer in ("muscle", "skin"):
        assert skel2.flesh_node_slices[layer] == skel.flesh_node_slices[layer]
        assert skel2.flesh_beam_slices[layer] == skel.flesh_beam_slices[layer]
        # Slices are honest 2-tuples after reload, not stray lists.
        assert isinstance(skel2.flesh_node_slices[layer], tuple)


# ---------------------------------------------------------------------------
# Built-world round trip: rope + ragdoll + motor
# ---------------------------------------------------------------------------


def _build_mixed_world() -> World:
    """A non-trivial world: rope chain + ragdoll skeleton + motor wheel."""
    w = World(gravity=(0.0, -9.81))
    w.solver_iterations = 6

    # 1. Rope between two anchors.
    rope = RopeSpec(
        node_count=8,
        total_length=2.0,
        mass_per_node=0.05,
        stiffness=1.5e6,
        damping=0.05,
        anchor_a_pinned=True,
        anchor_b_pinned=False,
    )
    build_rope(rope, w, anchor_a=(-1.0, 2.0), anchor_b=(1.0, 2.0))

    # 2. Two-bone ragdoll.
    rd = RagdollSpec(
        bones=[
            BoneSpec(parent_idx=-1, length=0.5, mass=1.0, label="trunk"),
            BoneSpec(
                parent_idx=0,
                length=0.3,
                mass=0.5,
                direction=(0.0, -1.0),
                angle_limit=(-0.8, 0.8),
                label="arm",
            ),
        ],
        stiffness=4.0e6,
        damping=0.05,
    )
    build_ragdoll(rd, w, anchor_pos=(3.0, 2.0), pin_root=True)

    # 3. A motor with a hub + two rim nodes.
    hub = w.add_node((-3.0, 1.0), mass=0.0)
    rim_a = w.add_node((-2.7, 1.0), mass=0.5)
    rim_b = w.add_node((-3.3, 1.0), mass=0.5)
    w.add_joint(
        make_motor(
            hub=hub,
            rim_a=rim_a,
            rim_b=rim_b,
            target_omega=5.0,
            max_torque=20.0,
            radius=0.3,
        )
    )
    # Plus a plain spring so spring kind shows up too.
    w.add_joint(make_spring(rim_a, rim_b, rest_length=0.6))

    # Run a few steps so positions are non-trivial.
    for _ in range(5):
        w.step(1.0 / 240.0)
    return w


def test_mixed_world_save_load_identical(tmp_path: Path):
    w = _build_mixed_world()
    path = tmp_path / "mixed.json"
    save_world(w, path)
    w2 = load_world(path)

    np.testing.assert_array_equal(w2.positions, w.positions)
    np.testing.assert_array_equal(w2.prev_positions, w.prev_positions)
    np.testing.assert_array_equal(w2.velocities, w.velocities)
    np.testing.assert_array_equal(w2.inv_masses, w.inv_masses)
    np.testing.assert_array_equal(w2.gravity, w.gravity)
    assert w2.solver_iterations == w.solver_iterations
    assert w2.frame == w.frame
    assert w2.warn_overdamping == w.warn_overdamping

    # Bodies preserved kind / label / slice.
    assert len(w2.bodies) == len(w.bodies)
    for a, b in zip(w.bodies, w2.bodies):
        assert a.kind == b.kind
        assert a.label == b.label
        assert a.node_offset == b.node_offset
        assert a.node_count == b.node_count

    # Joint count and per-joint kind / endpoints / tuning preserved.
    assert len(w2.joints) == len(w.joints)
    kinds_in = [j.kind for j in w.joints]
    kinds_out = [j.kind for j in w2.joints]
    assert kinds_in == kinds_out
    assert "motor" in kinds_in  # spotcheck the motor survived
    assert "spring" in kinds_in
    for a, b in zip(w.joints, w2.joints):
        assert a.kind == b.kind
        assert a.node_a == b.node_a
        assert a.node_b == b.node_b
        assert a.rest_length == pytest.approx(b.rest_length, rel=1e-12)
        assert a.stiffness == pytest.approx(b.stiffness, rel=1e-12)
        assert a.damping == pytest.approx(b.damping, rel=1e-12)


def test_mixed_world_post_load_step_matches_original():
    """A single ``step`` of the reloaded mixed world tracks the original
    to machine precision — the determinism contract for save-resume."""
    w = _build_mixed_world()
    w2 = world_from_dict(world_to_dict(w))
    dt = 1.0 / 240.0
    w.step(dt)
    w2.step(dt)
    err = float(np.max(np.abs(w.positions - w2.positions)))
    assert err <= 1e-9, f"post-load step error {err} exceeds 1e-9"


# ---------------------------------------------------------------------------
# world_to_dict / world_from_dict surface guards (Round 2 deliverables).
# ---------------------------------------------------------------------------


def test_world_save_preserves_gravity_and_solver_iterations(tmp_path: Path):
    w = World(gravity=(1.5, -7.25))
    w.solver_iterations = 12
    # Need at least one node so step() exercises the SoA arrays.
    w.add_node((0.0, 0.0), mass=1.0)
    w.add_node((1.0, 0.0), mass=1.0)
    w.add_joint(make_spring(0, 1, rest_length=1.0))
    save_world(w, tmp_path / "world.json")
    w2 = load_world(tmp_path / "world.json")
    assert tuple(w2.gravity) == (1.5, -7.25)
    assert w2.solver_iterations == 12
