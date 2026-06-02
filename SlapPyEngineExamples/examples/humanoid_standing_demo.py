"""Humanoid standing — skeleton planted upright on a flat floor via IK.

2D skeletons have no out-of-plane rotational stability — a free-fall under
gravity would tip them over because nothing resists rotation about the
contact point. Instead this demo uses ``place_feet_on_terrain`` with a
flat-floor terrain function to plant both feet and IK the legs into a
standing pose. The result is a stable anatomical silhouette suitable as
the baseline pose for the IK-terrain and destruction demos.

Showcase: ``humanoid_stage()`` builds the kinematic world (no gravity,
no contact), and ``record(..., step_world=False)`` captures the same
pose for N frames.

Run:
    python examples/humanoid_standing_demo.py

Output:
    examples/output/humanoid/humanoid_standing.gif
"""
from __future__ import annotations

from slappyengine.dynamics import make_humanoid, place_feet_on_terrain
from slappyengine.studio import humanoid_stage, output_path, record


def main(frames: int = 60) -> None:
    stage = humanoid_stage(view_box=(-1.2, 0.0, 1.2, 4.0),
                            width=320, height=400)
    skel = make_humanoid(stage.world, root_position=(0.0, 1.5))

    flat_y = 3.5
    place_feet_on_terrain(stage.world, skel, lambda x: flat_y,
                           pelvis_height_above_terrain=0.95)

    out = output_path("humanoid_standing", __file__, subdir="humanoid")
    record(stage, frames=frames, output=out, step_world=False)

    pelvis_y = float(stage.world.nodes.pos[skel.pelvis, 1])
    head_y = float(stage.world.nodes.pos[skel.head, 1])
    ankle_l_y = float(stage.world.nodes.pos[skel.ankle_l, 1])
    print(f"wrote {out}")
    print(f"pose:  head y={head_y:.3f}  pelvis y={pelvis_y:.3f}  "
          f"ankle_l y={ankle_l_y:.3f}  floor y={flat_y}")


if __name__ == "__main__":
    main()
