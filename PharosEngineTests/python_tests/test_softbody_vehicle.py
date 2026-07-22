"""Vehicle topology + drivetrain tests for the softbody module.

A vehicle is a single ``SoftBodyWorld`` body composed of a chassis
lattice, two (or more) wheels each built from a hub + ring of rim nodes,
and suspension beams that glue the wheels to the chassis. See
``python/pharos_engine/softbody/vehicle.py``.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pytest

from pharos_engine.softbody import (
    SoftBodyWorld,
    VehicleSpec,
    WheelSpec,
    build_vehicle,
    make_lattice_body,
    step,
)


@pytest.fixture(autouse=True)
def _no_runtime_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=RuntimeWarning)
        yield


def test_vehicle_lands_upright_on_flat_ground():
    w = SoftBodyWorld()
    w.config["floor_y"] = 5.0
    v = build_vehicle(w, VehicleSpec(), position=(-1.2, 2.0))

    for _ in range(200):
        step(w)

    chassis_vel = v.chassis_velocity(w)
    assert abs(float(chassis_vel[1])) < 0.5, (
        f"chassis still falling/bouncing: vy={chassis_vel[1]:.3f}"
    )
    assert abs(float(chassis_vel[0])) < 0.5, (
        f"chassis drifting horizontally: vx={chassis_vel[0]:.3f}"
    )
    assert not v.is_inverted(w), "vehicle landed upside down"
    assert not np.any(np.isnan(w.nodes.pos))
    chassis_y_max = float(w.nodes.pos[v.chassis_node_ids, 1].max())
    assert chassis_y_max <= w.config["floor_y"] + 1e-3
    # Wheels still attached: one connected component.
    groups = w.connected_components(body_id=v.body_id)
    big = [g for g in groups if len(g) >= 5]
    assert len(big) == 1, f"vehicle disintegrated on landing: {[len(g) for g in groups]}"


def test_throttle_drives_vehicle_forward():
    w = SoftBodyWorld()
    w.config["floor_y"] = 5.0
    v = build_vehicle(
        w, VehicleSpec(drivetrain_mode="awd"), position=(-1.2, 2.0)
    )
    for _ in range(60):
        step(w)
    start_x = float(v.chassis_position(w)[0])

    dt = 1.0 / 60.0
    for _ in range(200):
        v.apply_throttle(w, throttle=1.0, dt=dt)
        step(w)

    end_x = float(v.chassis_position(w)[0])
    delta = end_x - start_x
    assert delta > 0.5, (
        f"vehicle did not move forward under throttle: delta_x={delta:.3f}"
    )
    assert not np.any(np.isnan(w.nodes.pos))
    assert not v.is_inverted(w)


def test_chassis_crumples_on_ramp_drop():
    w = SoftBodyWorld()
    w.config["floor_y"] = 5.0
    ramp = make_lattice_body(
        w, "steel", width_cells=10, height_cells=2,
        cell_size=0.15, position=(-0.5, 4.6), name="ramp",
    )
    rs, re = ramp.node_slice
    for nid in range(rs, re):
        w.nodes.fixed[nid] = True
        w.nodes.inv_mass[nid] = 0.0

    v = build_vehicle(w, VehicleSpec(), position=(-1.2, 0.0))
    initial_rest = w.beams.initial_rest_length.copy()

    for _ in range(240):
        step(w)

    chassis_ids = set(v.chassis_node_ids.tolist())
    a = w.beams.node_a.astype(np.int64)
    b = w.beams.node_b.astype(np.int64)
    chassis_beam_mask = np.array([
        int(a[i]) in chassis_ids and int(b[i]) in chassis_ids
        for i in range(w.beams.count)
    ])
    chassis_rest = w.beams.rest_length[chassis_beam_mask]
    chassis_init = initial_rest[chassis_beam_mask]
    shift = np.abs(chassis_rest - chassis_init) / np.maximum(chassis_init, 1e-9)
    shifted = int((shift > 0.01).sum())
    assert shifted > 0, (
        f"no chassis crumple: 0/{int(chassis_beam_mask.sum())} chassis beams "
        "shifted by >1%"
    )

    # Vehicle still drivable: wheel hubs are still in the same connected component
    # as the chassis nodes.
    groups = w.connected_components(body_id=v.body_id)
    chassis_node_set = chassis_ids
    chassis_group = None
    for g in groups:
        if g & chassis_node_set:
            chassis_group = g
            break
    assert chassis_group is not None, "chassis nodes were not classified"
    for hub in v.wheel_hubs:
        assert hub in chassis_group, (
            f"wheel hub {hub} detached from chassis after ramp drop"
        )

    assert not np.any(np.isnan(w.nodes.pos))


def test_wheel_can_break_off():
    w = SoftBodyWorld()
    w.config["floor_y"] = 5.0
    v = build_vehicle(w, VehicleSpec(), position=(-1.2, 2.0))

    # Settle on floor.
    for _ in range(60):
        step(w)

    # Force-break the suspension beams of wheel 0.
    target_susp = v.suspension_beams[0]
    w.beams.broken[target_susp] = True

    # Simulate further; vehicle keeps running and the rim/hub of wheel 0
    # are no longer connected to the chassis.
    for _ in range(120):
        step(w)

    chassis_ids = set(v.chassis_node_ids.tolist())
    groups = w.connected_components(body_id=v.body_id)
    chassis_group: set[int] | None = None
    for g in groups:
        if g & chassis_ids:
            chassis_group = g
            break
    assert chassis_group is not None
    assert v.wheel_hubs[0] not in chassis_group, (
        "wheel 0 hub still attached to chassis after suspension broke"
    )
    assert v.wheel_hubs[1] in chassis_group, (
        "wheel 1 should still be attached to chassis"
    )
    assert not np.any(np.isnan(w.nodes.pos))
    # Vehicle hasn't exploded — positions stay bounded.
    pos = w.nodes.pos
    assert float(pos[:, 0].min()) > -50.0 and float(pos[:, 0].max()) < 50.0
    assert float(pos[:, 1].min()) > -50.0
