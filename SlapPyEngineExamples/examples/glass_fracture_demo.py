"""Glass fracture — brittle stone cube shatters on floor impact.

A small "glass" cube (brittle ``stone`` material: yield_strain ==
break_strain, plasticity_rate == 0) is released from height. On impact
the high local strain exceeds the break threshold and the cube splits
into multiple connected components.

Showcase of the high-level helpers in :mod:`slappyengine.studio`:
the entire scene fits in ~15 lines instead of ~50 of boilerplate.

Run:
    python examples/glass_fracture_demo.py

Output:
    examples/output/fracture/glass_fracture.gif
"""
from __future__ import annotations

import numpy as np

from slappyengine.softbody import SoftBodyWorld, make_lattice_body
from slappyengine.studio import output_path, record, softbody_stage
from slappyengine.topology import connected_components


def _fragment_count(world: SoftBodyWorld) -> int:
    if world.beams.count == 0:
        return 0
    edges = np.stack([world.beams.node_a.astype(np.int64),
                      world.beams.node_b.astype(np.int64)], axis=1)
    _, n = connected_components(
        n_nodes=int(world.nodes.count),
        edges=edges,
        active=(~world.beams.broken).copy(),
    )
    return n


def main(frames: int = 180) -> None:
    stage = softbody_stage(view_box=(-1.6, 1.0, 1.6, 5.3),
                            width=320, height=240,
                            floor_y=5.0, floor_friction=0.2,
                            contact_enabled=True)
    # Use the "glass" material (10x break_strain vs stone) so the impact
    # produces visible cracking lines between surviving shards instead of
    # atomising every beam and collapsing to a flat line.
    cube = make_lattice_body(stage.world, "glass",
                              width_cells=5, height_cells=5, cell_size=0.10,
                              position=(-0.25, 1.8))
    cube.kick(stage.world, vy=8.0, twist=-0.6)

    out = output_path("glass_fracture", __file__, subdir="fracture")
    record(stage, frames=frames, output=out)

    print(f"wrote {out}")
    print(f"broken beams: {int(stage.world.beams.broken.sum())}/{stage.world.beams.count}")
    print(f"connected components after impact: {_fragment_count(stage.world)}")


if __name__ == "__main__":
    main()
