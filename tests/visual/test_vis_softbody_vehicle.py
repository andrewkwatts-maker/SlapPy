"""Visual test: softbody vehicle drives across the screen and stays intact.

Drives a softbody vehicle (XPBD chassis + 2 wheels + suspension) at full
throttle for 120 frames over a flat slope. Asserts:

  * the chassis traverses ≥ 1.0 world unit in +x over the run
  * the chassis lattice remains connected (no exploded beams) at the end
  * the rendered frame contains a non-trivial number of non-background pixels

This is the canonical visual regression for the rebuild softbody stack —
exercises softbody solver, vehicle drivetrain, suspension contact, and
SoftBodyRenderer in one pass.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from pharos_engine.softbody import (
    SoftBodyRenderConfig, SoftBodyRenderer, SoftBodyWorld,
    VehicleSpec, build_vehicle, make_lattice_body, step,
)

from tests.visual.harness import make_test_output_dir

TEST_NAME = "softbody_vehicle"
FRAME_WIDTH = 480
FRAME_HEIGHT = 270
SETTLE_FRAMES = 60
DRIVE_FRAMES = 120


def _anchor_slice(world: SoftBodyWorld, ns: int, ne: int) -> None:
    for nid in range(ns, ne):
        world.nodes.fixed[nid] = True
        world.nodes.inv_mass[nid] = 0.0


def _connected_node_count(world: SoftBodyWorld, body_id: int) -> int:
    """Largest connected node-group inside the given body (via live beams)."""
    groups = world.connected_components(body_id=body_id)
    return max((len(g) for g in groups), default=0)


def test_softbody_vehicle_traverses_and_stays_intact():
    world = SoftBodyWorld()
    world.config["floor_y"] = 6.0

    # Flat ground built from an anchored steel lattice for the wheels to grip.
    slope = make_lattice_body(
        world, "steel", width_cells=12, height_cells=2,
        cell_size=0.20, position=(-3.0, 5.4), name="slope",
    )
    _anchor_slice(world, *slope.node_slice)

    spec = VehicleSpec(drivetrain_mode="awd")
    veh = build_vehicle(world, spec, position=(-2.5, 0.2))
    chassis_body_id = veh.chassis_body_id if hasattr(veh, "chassis_body_id") \
        else world.bodies[-1].body_id

    # Initial chassis x — used as the traversal baseline.
    x0 = float(veh.chassis_position(world)[0])

    # Settle on the ground.
    dt = 1.0 / 60.0
    for _ in range(SETTLE_FRAMES):
        step(world, dt=dt)

    # Drive forward.
    for _ in range(DRIVE_FRAMES):
        veh.apply_throttle(world, throttle=1.0, dt=dt)
        step(world, dt=dt)

    x_end = float(veh.chassis_position(world)[0])
    traversed = x_end - x0
    assert traversed >= 1.0, (
        f"vehicle barely moved: x0={x0:.3f} x_end={x_end:.3f} "
        f"delta={traversed:.3f} (expected >= 1.0)"
    )

    # Chassis lattice must remain connected: the largest body component
    # should include almost every chassis node.
    chassis_meta = next(
        (b for b in world.bodies if b.name not in ("slope", "tire_front", "tire_rear")),
        None,
    )
    if chassis_meta is not None:
        ns, ne = chassis_meta.node_slice
        total = ne - ns
        # Allow up to 10% of chassis nodes to be in detached fragments
        biggest = _connected_node_count(world, chassis_meta.body_id)
        assert biggest >= int(total * 0.9), (
            f"chassis fragmented: biggest component {biggest}/{total} nodes"
        )

    # Render a single frame and assert non-trivial content.
    renderer = SoftBodyRenderer(
        config=SoftBodyRenderConfig.from_yaml(
            {"width": FRAME_WIDTH, "height": FRAME_HEIGHT}))
    cx = float(veh.chassis_position(world)[0])
    view_box = (cx - 4.0, -0.5, cx + 4.0, world.config["floor_y"] + 0.3)
    arr = renderer.render(world, view_box=view_box)

    # Save snapshot for visual inspection.
    out_dir = make_test_output_dir(TEST_NAME)
    img = Image.fromarray(arr, mode="RGBA")
    img.save(out_dir / "final_frame.png")

    # Frame must contain something — the renderer fills with a dark gradient
    # background, so the body pixels show as significantly brighter.
    rgb = np.asarray(img.convert("RGB"))
    mean_brightness = float(rgb.mean())
    bright_pixels = int(((rgb.sum(axis=-1) // 3) > 90).sum())
    assert mean_brightness > 25.0, (
        f"final frame is suspiciously dark (mean={mean_brightness:.1f})"
    )
    assert bright_pixels > 200, (
        f"final frame has too few body pixels: {bright_pixels}"
    )
