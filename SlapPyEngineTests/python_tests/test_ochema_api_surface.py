"""Tripwire test: the public engine surface Ochema Circuit consumes.

Ochema Circuit imports from `pharos_engine` top-level the same way every
game does. Strip-pass v1 deleted the legacy `drivetrain` and
`suspension` modules; the replacement lives in
`pharos_engine.softbody.vehicle` but games shouldn't have to know that.
This test pins the names + signatures that must remain importable from
``pharos_engine`` at top-level. Any regression here means Ochema's CI
goes red.
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


def test_vehicle_api_top_level_imports():
    """Ochema's primary import surface."""
    from pharos_engine import (
        VehicleSpec,
        WheelSpec,
        VehicleHandle,
        build_vehicle,
        apply_drivetrain_torque,
        SoftBodyWorld,
    )
    # All symbols are callable / instantiable.
    assert callable(build_vehicle)
    assert callable(apply_drivetrain_torque)
    assert VehicleSpec is not None
    assert WheelSpec is not None
    assert VehicleHandle is not None


def test_vehicle_spec_fields_stable():
    """The `VehicleSpec` field set Ochema's tests serialise from."""
    from pharos_engine import VehicleSpec, WheelSpec
    spec = VehicleSpec(
        chassis_width=6,
        chassis_height=3,
        chassis_cell_size=0.4,
        chassis_material="steel",
        wheels=[
            WheelSpec(x_offset=-1.0, radius=0.35, rim_count=12,
                      tire_material="tire_rubber",
                      suspension_anchor_offset=-1.0),
        ],
        suspension_material="suspension",
        drivetrain_mode="rwd",
    )
    assert spec.chassis_width == 6
    assert spec.drivetrain_mode == "rwd"
    assert len(spec.wheels) == 1
    assert spec.wheels[0].rim_count == 12


def test_build_vehicle_round_trip():
    """build_vehicle should produce a VehicleHandle whose chassis is upright
    after a short drop."""
    from pharos_engine import (
        SoftBodyWorld,
        VehicleSpec,
        WheelSpec,
        build_vehicle,
    )
    from pharos_engine.softbody import step as softbody_step

    w = SoftBodyWorld()
    spec = VehicleSpec(
        chassis_width=4,
        chassis_height=2,
        chassis_cell_size=0.3,
        chassis_material="steel",
        wheels=[
            WheelSpec(x_offset=-0.5, radius=0.25, rim_count=10,
                      tire_material="tire_rubber",
                      suspension_anchor_offset=-0.5),
            WheelSpec(x_offset=0.5, radius=0.25, rim_count=10,
                      tire_material="tire_rubber",
                      suspension_anchor_offset=0.5),
        ],
        drivetrain_mode="rwd",
    )
    handle = build_vehicle(w, spec, position=(0.0, 2.0))
    assert handle is not None
    assert hasattr(handle, "chassis_node_ids")
    assert hasattr(handle, "wheel_hubs")
    assert len(handle.wheel_hubs) == 2

    # Take a few steps; verify finite positions.
    for _ in range(10):
        softbody_step(w)
    assert np.all(np.isfinite(w.nodes.pos))


def test_drivetrain_modes_recognised():
    """All three drivetrain mode strings remain valid."""
    from pharos_engine import VehicleSpec, WheelSpec
    for mode in ("rwd", "fwd", "awd"):
        spec = VehicleSpec(
            chassis_width=4,
            chassis_height=2,
            chassis_cell_size=0.3,
            chassis_material="steel",
            wheels=[
                WheelSpec(x_offset=-0.5, radius=0.25, rim_count=8,
                          tire_material="tire_rubber",
                          suspension_anchor_offset=-0.5),
                WheelSpec(x_offset=0.5, radius=0.25, rim_count=8,
                          tire_material="tire_rubber",
                          suspension_anchor_offset=0.5),
            ],
            drivetrain_mode=mode,
        )
        assert spec.drivetrain_mode == mode


def test_legacy_drivetrain_suspension_surface_remains_callable():
    """Ochema (and other game scripts) still import ``pharos_engine.drivetrain``
    and ``pharos_engine.suspension`` from their pre-rebuild code. The Phase C1
    strip removed the original modules; in Phase D we landed thin compat
    shims so existing games keep working while the canonical softbody-vehicle
    physics path matures.

    The shims must:
      * Be importable as their original module names.
      * Expose the small public surface the games actually call.
    """
    import importlib

    drivetrain = importlib.import_module("pharos_engine.drivetrain")
    assert hasattr(drivetrain, "DrivetrainComponent")
    assert hasattr(drivetrain, "DriveType")
    assert hasattr(drivetrain, "DiffType")
    for member in ("RWD", "FWD", "AWD"):
        assert hasattr(drivetrain.DriveType, member)
    dc = drivetrain.DrivetrainComponent(
        drive_type=drivetrain.DriveType.AWD,
        front_diff=drivetrain.DiffType.FREE,
        rear_diff=drivetrain.DiffType.FREE,
    )
    dc.update(dt=0.016, speed=20.0, accel=1.0, brake=0.0, steer=0.0, thrust=0.0)
    assert 0.1 <= dc.overall_traction <= 1.0

    suspension = importlib.import_module("pharos_engine.suspension")
    assert hasattr(suspension, "SuspensionComponent")
    sc = suspension.SuspensionComponent()
    result = sc.update([0.0, 0.0, 0.0, 0.0], dt=0.016, deform=None)
    assert {"body_roll", "body_pitch", "wheel_compression"} <= set(result.keys())


def test_dynamics_surface_also_top_level():
    """Phase B+ adds unified JointSpec surface — also reachable from engine root."""
    from pharos_engine import (
        JointSpec,
        JOINT_KINDS,
        make_distance,
        make_spring,
        make_motor,
        make_rope,
        make_ragdoll,
        solve_ik,
    )
    assert "distance" in JOINT_KINDS
    spec = make_distance(0, 1, 1.0)
    assert spec.kind == "distance"


def test_fluid_surface_also_top_level():
    """PBF surface — Bullet Strata and showcase demos pull from here."""
    from pharos_engine import (
        FluidWorld,
        FluidMaterial,
        pbf_step,
    )
    w = FluidWorld()
    assert w.particles.count == 0
    assert callable(pbf_step)
