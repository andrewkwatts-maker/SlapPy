"""Softbody vehicle clears two stone humps on a flat steel ground.

showcase: VehicleSpec(awd) + anchored stone lattices + chase camera via studio.

Builds an AWD softbody vehicle, drops it onto a flat steel strip, and slams
360 frames of full throttle through two small anchored stone humps. The
chase camera follows the chassis centroid.

Run:
    PYTHONPATH=python python examples/vehicle_obstacle_course.py

Output:
    examples/output/softbody/vehicle_course.gif
"""
from __future__ import annotations

from slappyengine.softbody import (
    VehicleSpec, build_vehicle, make_lattice_body,
)
from slappyengine.studio import anchor, output_path, record, softbody_stage


SETTLE_FRAMES = 60  # let the vehicle land before flooring the throttle


def main(frames: int = 360) -> None:
    stage = softbody_stage(view_box=(-3.0, -0.5, 5.0, 6.3),
                           width=640, height=360, floor_y=6.0)
    w = stage.world

    # Flat steel ground strip (anchored). cell_size matches existing demos.
    ground = make_lattice_body(w, "steel", width_cells=80, height_cells=2,
                               cell_size=0.20, position=(-8.0, 5.6), name="ground")
    anchor(w, ground.node_slice)

    # Two small anchored stone humps protruding above the steel strip.
    for hump_x in (2.0, 4.5):
        hump = make_lattice_body(w, "stone", width_cells=3, height_cells=1,
                                 cell_size=0.12, position=(hump_x, 5.48),
                                 name=f"hump_{hump_x}")
        anchor(w, hump.node_slice)

    # Spawn the vehicle above the ground; gravity provides landing momentum.
    veh = build_vehicle(w, VehicleSpec(drivetrain_mode="awd"),
                        position=(-2.5, 0.2))

    def chase(stage_, _f):
        cx = float(veh.chassis_position(w)[0])
        stage_.view_box = (cx - 4.0, -0.5, cx + 4.0, 6.3)

    state = {"frame": 0}

    def throttle(stage_):
        if state["frame"] >= SETTLE_FRAMES:
            veh.apply_throttle(w, throttle=1.0, dt=stage_.dt)
        state["frame"] += 1

    out = output_path("vehicle_course", __file__, subdir="softbody")
    record(stage, frames=frames + SETTLE_FRAMES, output=out,
           pre_step=throttle, post_step=chase)

    cx = float(veh.chassis_position(w)[0])
    broken = int(w.beams.broken.sum())
    print(f"wrote {out}")
    print(f"final chassis x={cx:.3f}")
    print(f"broken beams: {broken}/{w.beams.count}")


if __name__ == "__main__":
    main()
