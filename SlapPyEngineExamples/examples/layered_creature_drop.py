"""3-layer rubber creature drops into a stone bowl and bounces.

showcase: make_layered_creature + anchored stone hemispheres = squash & bounce.

A 3-ring rubber creature (radius 0.5, 12 nodes per ring) falls into a
shallow bowl built from two anchored stone "hemispheres" (tilted lattices).
Run with ``PYTHONPATH=python python examples/layered_creature_drop.py``.
Output: ``examples/output/softbody/creature_drop.gif``.
"""
from __future__ import annotations

import numpy as np

from slappyengine.softbody import make_lattice_body, make_layered_creature
from slappyengine.studio import (
    anchor, centroid, output_path, record, softbody_stage,
)


def _tilt_wall(w, body, sign: float, pivot_y: float, slope: float) -> None:
    """Shear a wall lattice outward + re-bake beam rest_lengths in place."""
    ns, ne = body.node_slice
    pos = w.nodes.pos
    shift = sign * (pivot_y - pos[ns:ne, 1]) * slope
    pos[ns:ne, 0] += shift
    w.nodes.prev_pos[ns:ne, 0] = pos[ns:ne, 0]
    bs, be = body.beam_slice
    a = w.beams.node_a[bs:be].astype(np.int64)
    b = w.beams.node_b[bs:be].astype(np.int64)
    w.beams.rest_length[bs:be] = np.linalg.norm(
        pos[b] - pos[a], axis=1).astype(w.beams.rest_length.dtype)


def main(frames: int = 240) -> None:
    stage = softbody_stage(view_box=(-2.5, 0.0, 2.5, 4.2),
                           width=480, height=360, floor_y=4.0)
    w = stage.world

    # Bowl floor — flat stone slab at the bottom.
    slab = make_lattice_body(w, "stone", width_cells=14, height_cells=1,
                             cell_size=0.14, position=(-0.98, 3.7), name="slab")
    anchor(w, slab.node_slice)

    # Left + right curved walls (tilted lattices forming a bowl).
    for sign, x0 in ((-1.0, -1.26), (+1.0, 0.98)):
        wall = make_lattice_body(w, "stone", width_cells=2, height_cells=8,
                                 cell_size=0.14, position=(x0, 2.58))
        _tilt_wall(w, wall, sign=sign, pivot_y=3.70, slope=0.45)
        anchor(w, wall.node_slice)

    # 3-layer rubber creature: ring_count=12 per layer, outer radius 0.5.
    # Spawn just above the bowl so the impact velocity stays modest.
    creature = make_layered_creature(
        w, materials_per_layer=["rubber", "rubber", "rubber"],
        ring_counts=[12, 12, 12], radii=[0.18, 0.34, 0.50],
        position=(0.0, 2.4),
    )
    start_c = centroid(w, creature.node_slice)

    out = output_path("creature_drop", __file__, subdir="softbody")
    record(stage, frames=frames, output=out)

    end_c = centroid(w, creature.node_slice)
    drift = float(np.hypot(end_c[0] - start_c[0], end_c[1] - start_c[1]))
    broken = int(w.beams.broken.sum())
    print(f"wrote {out}")
    print(f"broken beams: {broken}/{w.beams.count}")
    print(f"centroid drift: {drift:.3f}  "
          f"(start={start_c}, end={end_c})")


if __name__ == "__main__":
    main()
