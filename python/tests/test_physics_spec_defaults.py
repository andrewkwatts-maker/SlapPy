"""Invariant: every physics input Spec must be constructible with minimal args.

The user contract: "helpful default values in inputs/input structs so we
don't have to supply them if we don't want to." This test pins that —
each Spec gets a no-arg or near-no-arg construction path and the
resulting instance must be a valid value the engine can consume.
"""
from __future__ import annotations

import warnings

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _no_runtime_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=RuntimeWarning)
        yield


# ── Dynamics specs ──────────────────────────────────────────────────────────


def test_joint_spec_minimal_construction():
    """Only kind + two node indices required."""
    from slappyengine.dynamics import JointSpec
    s = JointSpec(kind="distance", node_a=0, node_b=1)
    assert s.rest_length == 0.0
    assert s.stiffness > 0
    assert s.damping >= 0
    assert s.enabled


def test_rope_spec_minimal_construction():
    """Start + end required (geometric anchors); rest defaults."""
    from slappyengine.dynamics import RopeSpec
    s = RopeSpec(start=(0.0, 0.0), end=(1.0, 0.0))
    assert s.segment_count > 0
    assert s.mass_per_node > 0
    assert s.segment_stiffness > 0
    assert 0.0 <= s.segment_damping <= 1.0


def test_bone_spec_minimal_construction():
    """Name + head + tail required (no sensible default skeleton geometry)."""
    from slappyengine.dynamics import BoneSpec
    s = BoneSpec(name="bone", head=(0.0, 0.0), tail=(0.0, 1.0))
    assert s.stiffness > 0
    assert s.break_strain > 0
    assert 0.0 <= s.yield_strain <= s.break_strain


def test_ragdoll_spec_minimal_construction():
    """At least one bone required; welds/anchors default to empty lists."""
    from slappyengine.dynamics import BoneSpec, RagdollSpec
    s = RagdollSpec(bones=[BoneSpec(name="b", head=(0, 0), tail=(0, 1))])
    assert s.welds == []
    assert s.anchors == []
    assert s.body_id == 0
    assert s.node_damping >= 0


def test_ik_chain_spec_minimal_construction():
    """chain_nodes + target required; iters/tolerance default."""
    from slappyengine.dynamics import IKChainSpec
    s = IKChainSpec(chain_nodes=[0, 1, 2], target=(1.0, 1.0))
    assert s.iters > 0
    assert s.tolerance > 0
    assert s.lengths is None  # auto-derive from current positions


def test_motor_handle_minimal_construction():
    from slappyengine.dynamics import MotorHandle
    h = MotorHandle(hub_node=0, rim_nodes=np.asarray([1, 2, 3], dtype=np.int32))
    assert h.target_omega == 0.0
    assert h.max_torque == 0.0
    assert h.enabled


# ── Softbody vehicle specs ──────────────────────────────────────────────────


def test_wheel_spec_no_arg_construction():
    """The user explicitly wanted all input structs constructible without args."""
    from slappyengine.softbody.vehicle import WheelSpec
    w = WheelSpec()
    assert w.x_offset == 0.0
    # None means "resolve from config at build time" — valid.
    assert w.radius is None
    assert w.rim_count is None
    assert w.tire_material is None


def test_vehicle_spec_no_arg_construction():
    from slappyengine.softbody.vehicle import VehicleSpec
    v = VehicleSpec()
    assert v.wheels == []
    # All None → resolve from config at build time.
    assert v.chassis_width is None
    assert v.chassis_height is None
    assert v.chassis_material is None
    assert v.drivetrain_mode is None


def test_vehicle_handle_required_fields_only():
    """VehicleHandle is a *result* type, not an input Spec — it has no
    sensible no-arg construction. Just verify it imports clean."""
    from slappyengine.softbody.vehicle import VehicleHandle
    assert VehicleHandle is not None


# ── Fluid materials ─────────────────────────────────────────────────────────


def test_fluid_material_construction_with_essentials_only():
    """A FluidMaterial needs name + a handful of physical params; everything
    else has a sensible default."""
    from slappyengine.fluid import FluidMaterial
    m = FluidMaterial(
        name="custom",
        rest_density=1000.0,
        kernel_radius=0.1,
        relaxation_eps=600.0,
        viscosity=0.01,
        surface_tension=0.0,
        surface_tension_n=4.0,
    )
    assert m.particle_mass == 1.0  # default
    assert m.friction_coef == 0.0  # default
    assert not m.is_granular
    assert m.thermal_conductivity == 0.0
    assert m.melt_to == ""
    assert m.freeze_to == ""


# ── Iso combat specs ───────────────────────────────────────────────────────


def test_combatant_minimal_construction():
    from slappyengine.iso.combat import Combatant
    c = Combatant(name="grunt", grid_x=0.0, grid_y=0.0)
    assert c.hp == 100.0
    assert c.max_hp == 100.0
    assert c.attack_damage > 0
    assert c.attack_range > 0
    assert c.armor == 0.0


def test_wave_spec_minimal_construction():
    """Just attacker_count + interval + at least one spawn point."""
    from slappyengine.iso.combat import WaveSpec
    s = WaveSpec(attacker_count=5, spawn_interval=1.0,
                 spawn_points=[(0.0, 0.0, 0.0)])
    assert s.attacker_hp > 0
    assert s.attacker_damage > 0
    assert s.attacker_speed > 0
    assert s.attacker_armor >= 0
    assert s.attacker_kind == "grunt"


# ── World / config containers ───────────────────────────────────────────────


def test_softbody_world_no_arg_construction():
    from slappyengine.softbody import SoftBodyWorld
    w = SoftBodyWorld()
    assert w.nodes.count == 0
    assert w.beams.count == 0


def test_fluid_world_no_arg_construction():
    from slappyengine.fluid import FluidWorld
    w = FluidWorld()
    assert w.particles.count == 0
    # Default material catalog contains at least water.
    assert any(m.name == "water" for m in w.materials)


# ── Plan-required invariant: WaveSpec validation ────────────────────────────


def test_wave_spec_rejects_negative_count():
    from slappyengine.iso.combat import WaveSpec
    with pytest.raises(ValueError):
        WaveSpec(attacker_count=-1, spawn_interval=1.0,
                 spawn_points=[(0, 0, 0)])


def test_wave_spec_rejects_empty_spawn_points():
    from slappyengine.iso.combat import WaveSpec
    with pytest.raises(ValueError):
        WaveSpec(attacker_count=1, spawn_interval=1.0, spawn_points=[])
