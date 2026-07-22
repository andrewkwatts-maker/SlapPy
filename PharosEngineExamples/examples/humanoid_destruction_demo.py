"""Humanoid destruction — bullets tear flesh from skeleton.

A humanoid skeleton is wrapped in two layers of flesh (muscle + skin)
attached to the bones with breakable distance joints. A sequence of
bullet traces (horizontal lines through the body at various heights)
cuts beams in their corridor. Skin layer tears first (lowest break_strain
on the radial flesh beams), then muscle, then bone — exactly the
user-visible layered damage. Per-layer break counts are reported.

Showcase: ``humanoid_stage()`` + ``record(..., post_step=…)`` — the
bullet schedule is just a callback.

Run:
    python examples/humanoid_destruction_demo.py

Output:
    examples/output/humanoid/humanoid_destruction.gif
"""
from __future__ import annotations

import numpy as np

from pharos_engine.dynamics import make_humanoid, wrap_in_flesh
from pharos_engine.softbody import SoftBodyWorld
from pharos_engine.studio import (
    Stage, humanoid_stage, output_path, record,
)


def _bullet_trace(world: SoftBodyWorld, start, end, corridor: float) -> dict[int, int]:
    """Break beams within ``corridor`` of the bullet line; return {layer: cuts}."""
    if world.beams.count == 0:
        return {}
    a = world.beams.node_a.astype(np.int64)
    b = world.beams.node_b.astype(np.int64)
    pa = world.nodes.pos[a]
    pb = world.nodes.pos[b]
    mid = 0.5 * (pa + pb)
    sx, sy = start
    ex, ey = end
    d = np.asarray([ex - sx, ey - sy], dtype=np.float32)
    L = float(np.linalg.norm(d)) or 1.0
    d /= L
    rel = mid - np.asarray([sx, sy], dtype=np.float32)
    t = rel @ d
    along = (t >= 0.0) & (t <= L)
    perp = rel - np.outer(t, d)
    perp_dist = np.linalg.norm(perp, axis=1)
    hit_mask = along & (perp_dist < corridor) & (~world.beams.broken)
    if not np.any(hit_mask):
        return {}
    hit_idx = np.where(hit_mask)[0]
    world.beams.broken[hit_idx] = True
    layers = world.nodes.layer[world.beams.node_a[hit_idx].astype(np.int64)]
    counts: dict[int, int] = {}
    for la in layers.tolist():
        counts[int(la)] = counts.get(int(la), 0) + 1
    return counts


def main(frames: int = 240) -> None:
    stage = humanoid_stage(view_box=(-1.5, 0.0, 1.5, 2.4),
                            width=360, height=480)
    skel = make_humanoid(stage.world, root_position=(0.0, 1.0))
    wrap_in_flesh(stage.world, skel,
                   muscle_offset=0.10, skin_offset=0.18,
                   muscle_stiffness=1.0e6, skin_stiffness=2.5e5,
                   flesh_break_strain=0.18)

    # Bullet schedule: frame -> (start_x, y, label)
    schedule: dict[int, tuple[float, float, str]] = {
        30:  (1.6,  0.40, "head"),
        70:  (1.6,  0.70, "chest"),
        110: (1.6,  1.10, "belly"),
        150: (1.6,  1.55, "thigh"),
        190: (1.6,  1.90, "shin"),
    }
    end_x = -1.6
    corridor = 0.20
    cumulative: dict[int, int] = {0: 0, 1: 0, 2: 0}

    def shoot(s: Stage, f: int) -> None:
        if f not in schedule:
            return
        sx, sy, label = schedule[f]
        cuts = _bullet_trace(s.world, (sx, sy), (end_x, sy), corridor)
        for la, c in cuts.items():
            cumulative[la] = cumulative.get(la, 0) + c
        tally = ", ".join(f"L{k}+{v}" for k, v in sorted(cuts.items()))
        print(f"frame {f}: bullet @ {label} y={sy:.2f} -> {tally or '(no hit)'}")

    out = output_path("humanoid_destruction", __file__, subdir="humanoid")
    record(stage, frames=frames, output=out, post_step=shoot)
    print(f"wrote {out}")
    print(f"cumulative cuts  bone(L0)={cumulative.get(0, 0)}  "
          f"muscle(L1)={cumulative.get(1, 0)}  skin(L2)={cumulative.get(2, 0)}")


if __name__ == "__main__":
    main()
