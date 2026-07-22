"""Body-body contact tests for the soft-body solver.

Each test instantiates a multi-body :class:`SoftBodyWorld`, runs a contact
scenario, and emits a GIF under ``tests/output/softbody/``.
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


def _make_renderer(size: tuple[int, int] = (320, 240)) -> SoftBodyRenderer:
    cfg = SoftBodyRenderConfig.from_yaml({"width": size[0], "height": size[1]})
    return SoftBodyRenderer(config=cfg)


def _render_frame(world: SoftBodyWorld, view_box, renderer: SoftBodyRenderer):
    from PIL import Image
    arr = renderer.render(world, view_box=view_box)
    return Image.fromarray(arr, mode="RGBA").convert("RGB")


@pytest.fixture(autouse=True)
def _no_runtime_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=RuntimeWarning)
        yield


def _configure_contact(w: SoftBodyWorld, thickness: float, stiffness: float = 1.0e9):
    w.config["contact"] = {
        "enabled": True,
        "default_thickness": float(thickness),
        "default_stiffness": float(stiffness),
        "broadphase_cell_factor": 1.5,
    }


def test_block_on_block_stacks():
    w = SoftBodyWorld()
    w.config["floor_y"] = 5.0
    cell = 0.08
    _configure_contact(w, thickness=cell * 0.5)
    bottom = make_lattice_body(
        w, "steel", width_cells=6, height_cells=3, cell_size=cell,
        position=(0.0, 4.76), name="bottom",
    )
    top = make_lattice_body(
        w, "steel", width_cells=6, height_cells=3, cell_size=cell,
        position=(0.0, 4.26), name="top",
    )

    renderer = _make_renderer()
    frames = []
    for _ in range(200):
        step(w)
        frames.append(_render_frame(w, view_box=(-0.6, 4.0, 0.6, 5.2),
                                    renderer=renderer))
    save_frames(frames, _OUT_DIR / "two_blocks_stack.gif", fps=30)

    bs, be = bottom.node_slice
    ts, te = top.node_slice

    top_lowest_y = float(w.nodes.pos[ts:te, 1].max())
    bottom_highest_y = float(w.nodes.pos[bs:be, 1].min())
    penetration = top_lowest_y - bottom_highest_y
    allowed = 0.10 * 2.0 * (cell * 0.5)
    assert penetration < allowed, (
        f"penetration {penetration:.4f} exceeded {allowed:.4f}"
    )

    speeds = np.linalg.norm(w.nodes.vel, axis=1)
    assert float(speeds.max()) < 1.0, f"bodies still moving: vmax={speeds.max()}"
    assert not np.any(np.isnan(w.nodes.pos))


def test_ball_bounces_off_floor():
    w = SoftBodyWorld()
    w.config["floor_y"] = 5.0
    _configure_contact(w, thickness=0.04)

    meta = make_layered_creature(
        w,
        materials_per_layer=["rubber", "rubber", "rubber"],
        ring_counts=[6, 10, 14],
        radii=[0.06, 0.13, 0.20],
        position=(0.0, 3.8),
    )

    renderer = _make_renderer()
    frames = []
    centroid_y_history: list[float] = []
    for _ in range(240):
        step(w)
        s, e = meta.node_slice
        centroid_y_history.append(float(w.nodes.pos[s:e, 1].mean()))
        frames.append(_render_frame(w, view_box=(-0.6, 3.0, 0.6, 5.2),
                                    renderer=renderer))
    save_frames(frames, _OUT_DIR / "ball_bounces_off_floor.gif", fps=30)

    series = np.asarray(centroid_y_history, dtype=np.float32)
    minima = 0
    for i in range(2, len(series) - 2):
        if series[i] > series[i - 1] and series[i] > series[i + 1]:
            minima += 1
    assert minima >= 3, f"expected >=3 bounces, saw {minima} local-max points"
    assert w.nodes.pos[:, 1].max() <= w.config["floor_y"] + 1e-3
    assert not np.any(np.isnan(w.nodes.pos))


def test_block_slides_off_block():
    w = SoftBodyWorld()
    w.config["floor_y"] = 5.0
    cell = 0.08
    _configure_contact(w, thickness=cell * 0.5)

    bottom = make_lattice_body(
        w, "steel", width_cells=6, height_cells=3, cell_size=cell,
        position=(-0.24, 4.76), name="bottom",
    )
    top = make_lattice_body(
        w, "steel", width_cells=4, height_cells=2, cell_size=cell,
        position=(0.16, 4.30), name="top",
    )
    ts, te = top.node_slice
    w.nodes.vel[ts:te, 0] = 0.5

    renderer = _make_renderer()
    frames = []
    for _ in range(200):
        step(w)
        frames.append(_render_frame(w, view_box=(-0.6, 4.0, 0.8, 5.2),
                                    renderer=renderer))
    save_frames(frames, _OUT_DIR / "block_slides_off_block.gif", fps=30)

    top_centroid_x = float(w.nodes.pos[ts:te, 0].mean())
    bs, be = bottom.node_slice
    bottom_right_x = float(w.nodes.pos[bs:be, 0].max())
    assert top_centroid_x > 0.1, (
        f"top block did not move rightward: centroid_x={top_centroid_x:.3f}"
    )
    top_lowest = float(w.nodes.pos[ts:te, 1].max())
    bottom_highest = float(w.nodes.pos[bs:be, 1].min())
    if top_centroid_x > bottom_right_x:
        assert top_lowest > bottom_highest - 0.02, (
            "top block looks stuck inside bottom block after sliding off"
        )
    assert not np.any(np.isnan(w.nodes.pos))


def test_two_creatures_collide():
    w = SoftBodyWorld()
    w.config["floor_y"] = 100.0
    w.config["gravity"] = (0.0, 0.0)
    _configure_contact(w, thickness=0.05)

    left = make_layered_creature(
        w,
        materials_per_layer=["bone", "muscle", "skin"],
        ring_counts=[6, 10, 14],
        radii=[0.08, 0.16, 0.24],
        position=(-0.35, 0.0),
        name="left",
    )
    right = make_layered_creature(
        w,
        materials_per_layer=["bone", "muscle", "skin"],
        ring_counts=[6, 10, 14],
        radii=[0.08, 0.16, 0.24],
        position=(0.35, 0.0),
        name="right",
    )
    ls, le = left.node_slice
    rs, re = right.node_slice
    w.nodes.vel[ls:le, 0] = 1.5
    w.nodes.vel[rs:re, 0] = -1.5

    renderer = _make_renderer()
    frames = []
    initial_left_x = float(w.nodes.pos[ls:le, 0].mean())
    initial_right_x = float(w.nodes.pos[rs:re, 0].mean())
    for _ in range(180):
        step(w)
        frames.append(_render_frame(w, view_box=(-0.8, -0.5, 0.8, 0.5),
                                    renderer=renderer))
    save_frames(frames, _OUT_DIR / "two_creatures_collide.gif", fps=30)

    final_left_x = float(w.nodes.pos[ls:le, 0].mean())
    final_right_x = float(w.nodes.pos[rs:re, 0].mean())

    assert final_left_x < final_right_x, (
        f"creatures tunnelled through each other: "
        f"left_x={final_left_x:.3f} >= right_x={final_right_x:.3f}"
    )
    assert (final_left_x - initial_left_x) < (initial_right_x - initial_left_x), (
        "left creature should not have crossed initial right position"
    )

    skin_layer = 2
    left_skin_mask = (w.nodes.body_id == left.body_id) & (w.nodes.layer == skin_layer)
    right_skin_mask = (w.nodes.body_id == right.body_id) & (w.nodes.layer == skin_layer)
    left_skin_x = w.nodes.pos[left_skin_mask, 0]
    right_skin_x = w.nodes.pos[right_skin_mask, 0]
    if left_skin_x.size and right_skin_x.size:
        assert float(left_skin_x.max()) < float(right_skin_x.max()) + 0.01, (
            "left skin punctured right body's right edge"
        )
    assert not np.any(np.isnan(w.nodes.pos))
