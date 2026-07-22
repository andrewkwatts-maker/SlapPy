"""Visual test: bullets tear flesh from a humanoid skeleton.

Mirror of ``examples/humanoid_destruction_demo.py``. Wraps a humanoid in
muscle + skin layers, fires bullets at five vertical heights, counts
broken beams by layer. Asserts:

  * each of the three layers (bone L0, muscle L1, skin L2) records cuts
  * total cuts > 50 (otherwise the bullet corridor missed)
  * the final rendered frame still contains skeleton silhouette pixels

Covers the dynamics.humanoid stack: bone topology, flesh wrap, breakable
distance joints, layered destruction labelling.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from slappyengine.dynamics import make_humanoid, wrap_in_flesh
from slappyengine.softbody import (
    SoftBodyRenderConfig, SoftBodyRenderer, SoftBodyWorld, step,
)

from tests.visual.harness import make_test_output_dir

TEST_NAME = "humanoid_destruction"
FRAME_WIDTH = 360
FRAME_HEIGHT = 480
FRAMES = 240


def _bullet_trace(world: SoftBodyWorld, start, end, corridor: float) -> dict[int, int]:
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


def test_humanoid_layered_destruction_records_cuts_in_all_layers():
    world = SoftBodyWorld()
    world.config["floor_y"] = 100.0
    world.config["contact"]["enabled"] = False
    world.config["gravity"] = [0.0, 0.0]

    skel = make_humanoid(world, root_position=(0.0, 1.0))
    wrap_in_flesh(world, skel,
                   muscle_offset=0.10, skin_offset=0.18,
                   muscle_stiffness=1.0e6, skin_stiffness=2.5e5,
                   flesh_break_strain=0.18)

    schedule: dict[int, tuple[float, float]] = {
        30:  (1.6, 0.40), 70:  (1.6, 0.70), 110: (1.6, 1.10),
        150: (1.6, 1.55), 190: (1.6, 1.90),
    }
    cumulative: dict[int, int] = {0: 0, 1: 0, 2: 0}

    for f in range(FRAMES):
        if f in schedule:
            sx, sy = schedule[f]
            cuts = _bullet_trace(world, (sx, sy), (-1.6, sy), corridor=0.20)
            for la, c in cuts.items():
                cumulative[la] = cumulative.get(la, 0) + c
        step(world)

    # Every layer must record SOME cuts — the demonstrated invariant is
    # that bullets tear through flesh AND bone.
    assert cumulative[0] > 0, f"no bone cuts: {cumulative}"
    assert cumulative[1] > 0, f"no muscle cuts: {cumulative}"
    assert cumulative[2] > 0, f"no skin cuts: {cumulative}"

    total = sum(cumulative.values())
    assert total >= 50, f"too few cuts overall (corridor missed?): {cumulative}"

    # Render final frame and assert there's still skeleton silhouette.
    renderer = SoftBodyRenderer(
        config=SoftBodyRenderConfig.from_yaml(
            {"width": FRAME_WIDTH, "height": FRAME_HEIGHT}))
    view_box = (-1.5, 0.0, 1.5, 2.4)
    arr = renderer.render(world, view_box=view_box)
    img = Image.fromarray(arr, mode="RGBA")
    out_dir = make_test_output_dir(TEST_NAME)
    img.save(out_dir / "final_frame.png")

    rgb = np.asarray(img.convert("RGB"))
    bright_pixels = int(((rgb.sum(axis=-1) // 3) > 50).sum())
    # Even with most flesh torn, the body should still have a visible
    # outline of bones, muscle ribbon, and skin
    assert bright_pixels > 500, (
        f"frame nearly empty after destruction: {bright_pixels} bright pixels"
    )
