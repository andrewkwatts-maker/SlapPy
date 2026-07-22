"""Tests for pharos_engine.dynamics — unified JointSpec + Body + Motor."""
from __future__ import annotations

import math
import warnings

import numpy as np
import pytest

from pharos_engine.dynamics import (
    JOINT_KINDS,
    Body,
    JointSpec,
    MotorHandle,
    make_ball,
    make_distance,
    make_hinge,
    make_motor,
    make_spring,
    make_weld,
    resolve_joint_specs,
)
from pharos_engine.dynamics.motor import apply_motor
from pharos_engine.softbody import SoftBodyWorld, make_lattice_body
from pharos_engine.softbody.solver import step as softbody_step


@pytest.fixture(autouse=True)
def _no_runtime_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=RuntimeWarning)
        yield


# ── Body dataclass ──────────────────────────────────────────────────────────


def test_body_dataclass_defaults():
    b = Body(body_id=0)
    assert b.kind == "lattice"
    assert b.node_count == 0
    assert b.beam_count == 0
    assert b.parameters == {}


def test_body_from_meta():
    w = SoftBodyWorld()
    meta = make_lattice_body(w, "steel", width_cells=2, height_cells=2,
                             cell_size=0.1, position=(0.0, 0.0))
    body = Body.from_meta(body_id=0, meta=meta, kind="lattice",
                         parameters={"foo": 1})
    assert body.kind == "lattice"
    assert body.node_slice == meta.node_slice
    assert body.beam_slice == meta.beam_slice
    assert body.parameters == {"foo": 1}


# ── JointSpec basics ────────────────────────────────────────────────────────


def test_joint_kinds_enumeration():
    assert "distance" in JOINT_KINDS
    assert "spring" in JOINT_KINDS
    assert "motor" in JOINT_KINDS
    assert len(JOINT_KINDS) == 7  # distance, spring, weld, ball, hinge, motor, prismatic


def test_joint_spec_rejects_unknown_kind():
    with pytest.raises(ValueError):
        JointSpec(kind="warp", node_a=0, node_b=1)


def test_joint_spec_get_param_uses_schema_default():
    spec = make_hinge(0, 1)
    # min_angle / max_angle default to ±π in the schema.
    assert spec.get_param("min_angle") == pytest.approx(-math.pi)
    assert spec.get_param("max_angle") == pytest.approx(math.pi)
    # An unknown key falls through to the caller-supplied default.
    assert spec.get_param("bogus", default=42) == 42


def test_joint_spec_schema_keys_per_kind():
    # Each kind exposes its declared schema keys.
    assert make_distance(0, 1, 1.0).schema_keys() == set()
    assert make_spring(0, 1, 1.0).schema_keys() == {"damping_boost"}
    assert make_motor(0, [1, 2]) is not None  # builder returns MotorHandle, not JointSpec


# ── Builders ────────────────────────────────────────────────────────────────


def _two_node_world() -> tuple[SoftBodyWorld, int, int]:
    """World with two free nodes at known positions. Returns (world, a, b)."""
    w = SoftBodyWorld()
    pos = np.asarray([[0.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    mass = np.asarray([1.0, 1.0], dtype=np.float32)
    fixed = np.asarray([False, False], dtype=bool)
    damping = np.asarray([0.05, 0.05], dtype=np.float32)
    w.nodes.append(pos=pos, mass=mass, body_id=0, layer=0,
                   damping=damping, fixed=fixed)
    return w, 0, 1


def test_resolve_distance_creates_beam():
    w, a, b = _two_node_world()
    spec = make_distance(a, b, rest_length=1.0, stiffness=2.0e9, damping=0.05)
    beam_idx, motors = resolve_joint_specs(w, [spec])
    assert motors == []
    assert beam_idx[0] >= 0
    assert w.beams.count == 1
    assert float(w.beams.rest_length[0]) == pytest.approx(1.0)
    assert float(w.beams.stiffness[0]) == pytest.approx(2.0e9)


def test_resolve_spring_boosts_damping():
    w, a, b = _two_node_world()
    spec = make_spring(a, b, rest_length=1.0, damping=0.10, damping_boost=2.0)
    resolve_joint_specs(w, [spec])
    # The resolver multiplies damping by damping_boost on spring kind.
    assert float(w.beams.damping[0]) == pytest.approx(0.20, rel=1e-5)


def test_resolve_weld_uses_zero_rest_length():
    w, a, b = _two_node_world()
    resolve_joint_specs(w, [make_weld(a, b, stiffness=1.0e10)])
    assert float(w.beams.rest_length[0]) == 0.0
    assert float(w.beams.stiffness[0]) == pytest.approx(1.0e10)


def test_resolve_ball_and_hinge_use_zero_rest_length():
    w, a, b = _two_node_world()
    specs = [make_ball(a, b), make_hinge(a, b)]
    resolve_joint_specs(w, specs)
    assert w.beams.count == 2
    assert (w.beams.rest_length == 0.0).all()


def test_resolve_skips_disabled_specs():
    w, a, b = _two_node_world()
    spec = make_distance(a, b, 1.0)
    spec.enabled = False
    beam_idx, _ = resolve_joint_specs(w, [spec])
    assert beam_idx == [-1]
    assert w.beams.count == 0


def test_resolve_returns_motor_indices_unresolved():
    w, a, b = _two_node_world()
    motor_spec = JointSpec(kind="motor", node_a=a, node_b=b)
    dist_spec = make_distance(a, b, 1.0)
    beam_idx, motors = resolve_joint_specs(w, [motor_spec, dist_spec])
    # Motor index is reported back; distance still resolves.
    assert motors == [0]
    assert beam_idx[1] >= 0


def test_resolve_groups_by_body_id():
    """Beams with different body_id are grouped and each batch get the right tag."""
    w = SoftBodyWorld()
    # First two nodes for body 0
    w.nodes.append(
        pos=np.asarray([[0.0, 0.0], [1.0, 0.0]], dtype=np.float32),
        mass=np.ones(2, dtype=np.float32),
        body_id=0, layer=0,
        damping=np.full(2, 0.05, dtype=np.float32),
        fixed=np.zeros(2, dtype=bool),
    )
    # Next two nodes for body 1
    w.nodes.append(
        pos=np.asarray([[0.0, 1.0], [1.0, 1.0]], dtype=np.float32),
        mass=np.ones(2, dtype=np.float32),
        body_id=1, layer=0,
        damping=np.full(2, 0.05, dtype=np.float32),
        fixed=np.zeros(2, dtype=bool),
    )
    specs = [
        make_distance(0, 1, 1.0, body_id=0),
        make_distance(2, 3, 1.0, body_id=1),
    ]
    resolve_joint_specs(w, specs)
    # Two beams in total; their `body_id` field reflects the spec's body_id.
    assert w.beams.count == 2
    assert set(int(b) for b in w.beams.body_id.tolist()) == {0, 1}


# ── Motor effector ──────────────────────────────────────────────────────────


def _hub_rim_world() -> tuple[SoftBodyWorld, int, list[int]]:
    """Hub at origin + 4 rim nodes at radius 1. Hub fixed, rim free."""
    w = SoftBodyWorld()
    pos = np.asarray([
        [0.0, 0.0],          # hub
        [1.0, 0.0],          # rim east
        [0.0, 1.0],          # rim north
        [-1.0, 0.0],         # rim west
        [0.0, -1.0],         # rim south
    ], dtype=np.float32)
    mass = np.asarray([100.0, 1.0, 1.0, 1.0, 1.0], dtype=np.float32)
    fixed = np.asarray([True, False, False, False, False], dtype=bool)
    damping = np.full(5, 0.05, dtype=np.float32)
    w.nodes.append(pos=pos, mass=mass, body_id=0, layer=0,
                   damping=damping, fixed=fixed)
    return w, 0, [1, 2, 3, 4]


def test_motor_adds_tangential_velocity_ccw():
    w, hub, rim = _hub_rim_world()
    motor = make_motor(hub_node=hub, rim_nodes=rim,
                       target_omega=1.0, max_torque=2.0)
    v_before = w.nodes.vel[rim].copy()
    apply_motor(w, motor, dt=0.1)
    v_after = w.nodes.vel[rim]
    # East rim (at +x, radius 1): tangent = (0, +1), so v.y should increase.
    assert v_after[0, 1] > v_before[0, 1]
    # North rim (at +y): tangent = (-1, 0), v.x should decrease.
    assert v_after[1, 0] < v_before[1, 0]


def test_motor_reverses_for_negative_target_omega():
    w, hub, rim = _hub_rim_world()
    motor = make_motor(hub_node=hub, rim_nodes=rim,
                       target_omega=-1.0, max_torque=2.0)
    apply_motor(w, motor, dt=0.1)
    # East rim: tangent CCW = (0, +1); reverse direction means v.y < 0.
    assert w.nodes.vel[1, 1] < 0.0


def test_motor_does_nothing_when_max_torque_zero():
    w, hub, rim = _hub_rim_world()
    motor = make_motor(hub_node=hub, rim_nodes=rim, target_omega=1.0, max_torque=0.0)
    v_before = w.nodes.vel[rim].copy()
    apply_motor(w, motor, dt=0.1)
    assert np.allclose(w.nodes.vel[rim], v_before)


def test_motor_does_nothing_when_disabled():
    w, hub, rim = _hub_rim_world()
    motor = make_motor(hub_node=hub, rim_nodes=rim, target_omega=1.0, max_torque=2.0)
    motor.enabled = False
    v_before = w.nodes.vel[rim].copy()
    apply_motor(w, motor, dt=0.1)
    assert np.allclose(w.nodes.vel[rim], v_before)


def test_motor_skips_rim_at_hub_position():
    """If a rim node sits exactly on the hub, divide-by-zero avoided."""
    w, hub, rim = _hub_rim_world()
    # Move rim 0 onto the hub.
    w.nodes.pos[rim[0]] = w.nodes.pos[hub]
    motor = make_motor(hub_node=hub, rim_nodes=rim, target_omega=1.0, max_torque=2.0)
    # Should not raise and not produce NaN.
    apply_motor(w, motor, dt=0.1)
    assert np.all(np.isfinite(w.nodes.vel))


# ── End-to-end: spec → solver → behaviour ───────────────────────────────────


def test_distance_spec_holds_two_nodes_at_rest_length():
    """A distance joint between two free nodes keeps them at rest_length after
    several solver steps. Emits a GIF of the resulting near-zero motion."""
    from python.tests._visual_snapshot import output_dir, save_softbody_sequence
    from pharos_engine.softbody import SoftBodyRenderConfig, SoftBodyRenderer

    w, a, b = _two_node_world()
    resolve_joint_specs(w, [make_distance(a, b, rest_length=1.0, stiffness=1.0e9)])
    w.config["gravity"] = [0.0, 0.0]
    w.config["contact"]["enabled"] = False
    w.config["floor_y"] = 100.0
    # Give the second node a small initial perpendicular velocity so the
    # GIF shows the constraint pulling it back.
    w.nodes.vel[b] = np.asarray([0.0, 2.0], dtype=np.float32)

    renderer = SoftBodyRenderer(config=SoftBodyRenderConfig.from_yaml(
        {"width": 320, "height": 200}))
    view_box = (-0.5, -1.5, 1.5, 1.5)
    frames = []
    for _ in range(40):
        softbody_step(w)
        frames.append(renderer.render(w, view_box=view_box))
    save_softbody_sequence(frames, output_dir("dynamics") / "distance_constraint.gif")

    d = float(np.linalg.norm(w.nodes.pos[b] - w.nodes.pos[a]))
    assert d == pytest.approx(1.0, abs=0.05)


def test_spring_spec_oscillates_when_stretched():
    """A spring released with one end fixed and a stretched offset should
    return some kinetic energy to the system within a few frames.
    Emits a GIF of the oscillation."""
    from python.tests._visual_snapshot import output_dir, save_softbody_sequence
    from pharos_engine.softbody import SoftBodyRenderConfig, SoftBodyRenderer

    w = SoftBodyWorld()
    pos = np.asarray([[0.0, 0.0], [1.5, 0.0]], dtype=np.float32)
    mass = np.asarray([100.0, 1.0], dtype=np.float32)
    fixed = np.asarray([True, False], dtype=bool)
    damping = np.asarray([0.05, 0.05], dtype=np.float32)
    w.nodes.append(pos=pos, mass=mass, body_id=0, layer=0,
                   damping=damping, fixed=fixed)
    resolve_joint_specs(w, [make_spring(0, 1, rest_length=1.0,
                                         stiffness=200.0, damping=0.01,
                                         damping_boost=1.0)])
    w.config["gravity"] = [0.0, 0.0]
    w.config["contact"]["enabled"] = False
    w.config["floor_y"] = 100.0

    renderer = SoftBodyRenderer(config=SoftBodyRenderConfig.from_yaml(
        {"width": 320, "height": 200}))
    view_box = (-0.5, -1.0, 2.0, 1.0)
    initial_d = float(np.linalg.norm(w.nodes.pos[1] - w.nodes.pos[0]))
    frames = []
    for _ in range(60):
        softbody_step(w)
        frames.append(renderer.render(w, view_box=view_box))
    save_softbody_sequence(frames, output_dir("dynamics") / "spring_oscillation.gif")
    final_d = float(np.linalg.norm(w.nodes.pos[1] - w.nodes.pos[0]))
    assert final_d < initial_d, (
        f"spring did not contract: initial {initial_d}, final {final_d}"
    )
