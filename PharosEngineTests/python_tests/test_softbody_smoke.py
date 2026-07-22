"""Smoke tests for the soft-body lattice physics foundation.

Each test instantiates a small :class:`SoftBodyWorld`, drops a body, and
asserts plausible behaviour. A 60-frame GIF is emitted per test under
``tests/output/softbody/`` for visual inspection.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pytest

from pharos_engine.media import save_frames
from pharos_engine.softbody import (
    SoftBodyRenderConfig,
    SoftBodyRenderer,
    SoftBodyWorld,
    make_layered_creature,
    make_lattice_body,
    step,
)

_OUT_DIR = Path(__file__).resolve().parent.parent.parent / "tests" / "output" / "softbody"
_OUT_DIR.mkdir(parents=True, exist_ok=True)


def _make_renderer(size: tuple[int, int]) -> SoftBodyRenderer:
    cfg = SoftBodyRenderConfig.from_yaml({"width": size[0], "height": size[1]})
    return SoftBodyRenderer(config=cfg)


def _render_frame(world: SoftBodyWorld, view_box: tuple[float, float, float, float],
                  size: tuple[int, int] = (320, 240),
                  renderer: SoftBodyRenderer | None = None):
    from PIL import Image
    r = renderer or _make_renderer(size)
    arr = r.render(world, view_box=view_box)
    return Image.fromarray(arr, mode="RGBA").convert("RGB")


def _run(world: SoftBodyWorld, frames: int, view_box, gif_name: str,
         dt: float = 1.0 / 60.0):
    renderer = _make_renderer((320, 240))
    out_frames = []
    for _ in range(frames):
        step(world, dt=dt)
        out_frames.append(_render_frame(world, view_box, renderer=renderer))
    save_frames(out_frames, _OUT_DIR / gif_name, fps=30)
    return out_frames


@pytest.fixture(autouse=True)
def _no_runtime_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=RuntimeWarning)
        yield


def test_steel_block_drops_and_rests_on_floor():
    w = SoftBodyWorld()
    w.config["floor_y"] = 5.0
    make_lattice_body(w, "steel", width_cells=6, height_cells=6,
                      cell_size=0.08, position=(0.0, 4.3))
    initial_beams = w.beams.count
    assert initial_beams > 100
    _run(w, frames=180, view_box=(-1.2, 4.0, 1.2, 5.3),
         gif_name="steel_block_rests.gif")

    speeds = np.linalg.norm(w.nodes.vel, axis=1)
    assert speeds.max() < 0.5, f"steel still moving: vmax={speeds.max()}"
    assert not np.any(np.isnan(w.nodes.pos))
    broken = int(w.beams.broken.sum())
    assert broken == 0, (
        f"steel block should not shatter on a low-velocity drop: {broken} broken"
    )
    assert w.nodes.pos[:, 1].max() <= w.config["floor_y"] + 1e-3


def test_steel_block_plastically_crumples():
    w = SoftBodyWorld()
    w.config["floor_y"] = 5.0
    meta = make_lattice_body(w, "steel", width_cells=6, height_cells=6,
                             cell_size=0.08, position=(0.0, 3.5))
    s, e = meta.node_slice
    w.nodes.vel[s:e, 1] = 15.0
    initial_beams = w.beams.count

    _run(w, frames=120, view_box=(-1.2, 3.2, 1.2, 5.3),
         gif_name="steel_block_plastically_crumples.gif")

    initial_rest = w.beams.initial_rest_length
    rest_shift = np.abs(w.beams.rest_length - initial_rest) / np.maximum(initial_rest, 1e-9)
    shifted = int(np.sum(rest_shift > 0.01))
    broken = int(w.beams.broken.sum())
    assert shifted > 0, "no plastic deformation occurred"
    assert broken < initial_beams * 0.1, (
        f"steel block shattered instead of crumpling: {broken}/{initial_beams}"
    )
    assert not np.any(np.isnan(w.nodes.pos))


def test_repeated_impacts_accumulate_deformation():
    w = SoftBodyWorld()
    w.config["floor_y"] = 5.0
    meta = make_lattice_body(w, "steel", width_cells=6, height_cells=6,
                             cell_size=0.08, position=(0.0, 4.3))
    initial_rest = w.beams.initial_rest_length.copy()

    frames = []
    for _ in range(120):
        step(w)
        frames.append(_render_frame(w, view_box=(-1.2, 3.2, 1.2, 5.3)))

    first_shift = float(np.mean(np.abs(w.beams.rest_length - initial_rest)
                                / np.maximum(initial_rest, 1e-9)))

    s, e = meta.node_slice
    top_row_y = float(w.nodes.pos[s:e, 1].min())
    top_mask = np.abs(w.nodes.pos[s:e, 1] - top_row_y) < 1e-3
    indices = np.where(top_mask)[0] + s
    w.nodes.mass[indices] *= 20.0
    w.nodes.inv_mass[indices] = np.where(
        w.nodes.fixed[indices], 0.0,
        1.0 / np.maximum(w.nodes.mass[indices], 1e-12),
    ).astype(np.float32)
    w.nodes.vel[indices, 1] = 12.0

    for _ in range(120):
        step(w)
        frames.append(_render_frame(w, view_box=(-1.2, 3.2, 1.2, 5.3)))

    final_shift = float(np.mean(np.abs(w.beams.rest_length - initial_rest)
                                / np.maximum(initial_rest, 1e-9)))

    save_frames(frames, _OUT_DIR / "repeated_impacts_accumulate_deformation.gif",
                fps=30)

    assert first_shift > 0.0, "no deformation after first drop"
    assert final_shift > first_shift, (
        f"second impact did not accumulate: first={first_shift:.4f} final={final_shift:.4f}"
    )
    assert not np.any(np.isnan(w.nodes.pos))


def test_rubber_block_squishes():
    w = SoftBodyWorld()
    w.config["floor_y"] = 5.0
    initial_h = 0.4
    make_lattice_body(w, "rubber", width_cells=4, height_cells=4,
                      cell_size=initial_h / 4.0, position=(0.0, 2.0))
    initial_top = float(w.nodes.pos[:, 1].min())
    initial_bot = float(w.nodes.pos[:, 1].max())
    initial_height = initial_bot - initial_top

    frames = _run(w, frames=120, view_box=(-0.6, 1.8, 0.6, 5.2),
                  gif_name="rubber_block_squishes.gif")
    assert frames

    min_height_seen = initial_height
    w2 = SoftBodyWorld()
    w2.config["floor_y"] = 5.0
    make_lattice_body(w2, "rubber", width_cells=4, height_cells=4,
                      cell_size=initial_h / 4.0, position=(0.0, 2.0))
    for _ in range(120):
        step(w2)
        ys = w2.nodes.pos[:, 1]
        h = float(ys.max() - ys.min())
        if h < min_height_seen:
            min_height_seen = h
    compression = (initial_height - min_height_seen) / initial_height
    assert compression > 0.05, (
        f"rubber block barely squished: {compression*100:.1f}% < 5%"
    )
    assert not np.any(np.isnan(w2.nodes.pos))


def test_stone_block_breaks_on_high_impact():
    w = SoftBodyWorld()
    w.config["floor_y"] = 5.0
    meta = make_lattice_body(w, "stone", width_cells=5, height_cells=5,
                             cell_size=0.1, position=(0.0, 1.0))
    s, e = meta.node_slice
    w.nodes.vel[s:e, 1] = 25.0

    _run(w, frames=60, view_box=(-0.8, 0.5, 0.8, 5.3),
         gif_name="stone_block_breaks.gif")

    broken = int(w.beams.broken.sum())
    assert broken > 5, f"stone block barely cracked: {broken} broken beams"
    components = w.connected_components(body_id=meta.body_id)
    sizable = [c for c in components if len(c) >= 2]
    assert len(sizable) >= 2, (
        f"stone block did not split: {len(sizable)} sizable components"
    )
    assert not np.any(np.isnan(w.nodes.pos))


def test_two_blocks_stack():
    """Body-body contact smoke: a steel block lands on a resting steel block."""
    w = SoftBodyWorld()
    w.config["floor_y"] = 5.0
    cell = 0.08
    w.config["contact"] = {
        "enabled": True,
        "default_thickness": cell * 0.5,
        "default_stiffness": 1.0e9,
        "broadphase_cell_factor": 1.5,
    }
    make_lattice_body(w, "steel", width_cells=6, height_cells=3, cell_size=cell,
                      position=(0.0, 4.76), name="bottom")
    make_lattice_body(w, "steel", width_cells=6, height_cells=3, cell_size=cell,
                      position=(0.0, 4.26), name="top")

    frames = _run(w, frames=180, view_box=(-0.6, 4.0, 0.6, 5.2),
                  gif_name="two_blocks_stack.gif")
    assert len(frames) == 180
    assert not np.any(np.isnan(w.nodes.pos))


def test_layered_creature_takes_skin_damage():
    w = SoftBodyWorld()
    w.config["floor_y"] = 100.0
    w.config["gravity"] = (0.0, 0.0)

    meta = make_layered_creature(
        w,
        materials_per_layer=["bone", "muscle", "skin"],
        ring_counts=[8, 12, 16],
        radii=[0.10, 0.20, 0.30],
        position=(0.0, 0.0),
    )

    bullet_x, bullet_y0 = 0.0, -0.5
    velocity = 8.0

    def beam_intersects_segment(pa, pb, s0, s1) -> bool:
        # segment-segment intersection in 2D
        r = pb - pa
        s = s1 - s0
        denom = r[0] * s[1] - r[1] * s[0]
        if abs(denom) < 1e-9:
            return False
        qp = s0 - pa
        t = (qp[0] * s[1] - qp[1] * s[0]) / denom
        u = (qp[0] * r[1] - qp[1] * r[0]) / denom
        return 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0

    bullet_y = bullet_y0
    layer_breaks = {0: 0, 1: 0, 2: 0}
    sim_dt = 1.0 / 120.0
    frames = []
    for fi in range(120):
        new_bullet_y = bullet_y + velocity * sim_dt
        s0 = np.array([bullet_x, bullet_y], dtype=np.float32)
        s1 = np.array([bullet_x, new_bullet_y], dtype=np.float32)
        for i in range(w.beams.count):
            if w.beams.broken[i]:
                continue
            pa = w.nodes.pos[int(w.beams.node_a[i])]
            pb = w.nodes.pos[int(w.beams.node_b[i])]
            if beam_intersects_segment(pa, pb, s0, s1):
                w.beams.broken[i] = True
                layer = int(w.nodes.layer[int(w.beams.node_a[i])])
                layer_breaks[layer] = layer_breaks.get(layer, 0) + 1
        bullet_y = new_bullet_y
        step(w, dt=sim_dt)
        frames.append(_render_frame(w, view_box=(-0.5, -0.6, 0.5, 0.6)))

    save_frames(frames, _OUT_DIR / "creature_skin_damage.gif", fps=30)

    assert layer_breaks[2] > 0, f"no skin beams broken: {layer_breaks}"
    assert layer_breaks[1] > 0, f"no muscle beams broken: {layer_breaks}"
    assert layer_breaks[2] >= layer_breaks[0], (
        f"skin should take more damage than bone: {layer_breaks}"
    )
    assert not np.any(np.isnan(w.nodes.pos))
