"""Character damage — bullets shred a layered creature over time.

A 3-ring layered creature (bone / muscle / skin) is shot repeatedly
by a sequence of bullets along varying y-lines. Each bullet trace cuts
beams in its corridor; layer damage accumulates frame by frame. The
gif shows skin tearing first, then muscle exposure, finally bone breaks.

Run:
    python examples/character_damage_demo.py

Output:
    examples/output/character/character_damage.gif
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from slappyengine.media import save_frames
from slappyengine.softbody import (
    SoftBodyRenderConfig,
    SoftBodyRenderer,
    SoftBodyWorld,
    make_layered_creature,
    step,
)


def _bullet_corridor(world: SoftBodyWorld, start, end, corridor: float) -> dict[int, int]:
    """Break beams within `corridor` of the bullet line. Returns {layer: count}."""
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
    d = d / L
    rel = mid - np.asarray([sx, sy], dtype=np.float32)
    t = rel @ d
    along = (t >= 0.0) & (t <= L)
    perp = rel - np.outer(t, d)
    perp_dist = np.linalg.norm(perp, axis=1)
    hit_mask = along & (perp_dist < corridor) & (~world.beams.broken)
    if not np.any(hit_mask):
        return {}
    # Tally by layer (use node_a's layer)
    hit_beams = np.where(hit_mask)[0]
    world.beams.broken[hit_beams] = True
    layers = world.nodes.layer[world.beams.node_a[hit_beams].astype(np.int64)]
    counts: dict[int, int] = {}
    for la in layers.tolist():
        counts[int(la)] = counts.get(int(la), 0) + 1
    return counts


def main(out_path: Path | None = None, frames: int = 200) -> Path:
    out_path = out_path or Path(__file__).parent / "output" / "character" / "character_damage.gif"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    world = SoftBodyWorld()
    world.config["floor_y"] = 5.0
    world.config["contact"]["enabled"] = False
    world.config["gravity"] = [0.0, 0.0]   # weightless so the body stays put for clarity

    make_layered_creature(
        world,
        materials_per_layer=["bone", "muscle", "skin"],
        ring_counts=[6, 12, 18],
        radii=[0.30, 0.70, 1.05],
        position=(0.0, 2.0),
    )

    renderer = SoftBodyRenderer(
        config=SoftBodyRenderConfig.from_yaml({"width": 360, "height": 270})
    )
    view_box = (-2.0, 0.5, 2.0, 3.5)

    # Bullet schedule: shot every 25 frames at varying y heights through the body.
    schedule = {
        25:  (-1.8, 2.05),
        60:  (-1.8, 1.85),
        100: (-1.8, 2.25),
        135: (-1.8, 1.95),
        170: (-1.8, 2.10),
    }
    end_x = 1.8
    corridor = 0.07

    cumulative = {0: 0, 1: 0, 2: 0}   # bone=0, muscle=1, skin=2
    pil_frames: list[Image.Image] = []
    for f in range(frames):
        if f in schedule:
            sx, sy = schedule[f]
            counts = _bullet_corridor(world, (sx, sy), (end_x, sy), corridor)
            for la, c in counts.items():
                cumulative[la] = cumulative.get(la, 0) + c
            label = ", ".join(f"L{la}+{c}" for la, c in sorted(counts.items()))
            print(f"frame {f}: bullet at y={sy:.2f} cut {sum(counts.values())} beams ({label})")
        step(world)
        arr = renderer.render(world, view_box=view_box)
        pil_frames.append(Image.fromarray(arr, mode="RGBA").convert("RGB"))

    save_frames(pil_frames, out_path, fps=30)
    print(f"wrote {out_path}")
    print(f"cumulative cuts  bone={cumulative.get(0, 0)} "
          f"muscle={cumulative.get(1, 0)}  skin={cumulative.get(2, 0)}")
    return out_path


if __name__ == "__main__":
    main()
