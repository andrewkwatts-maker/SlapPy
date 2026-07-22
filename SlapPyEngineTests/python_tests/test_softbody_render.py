"""Rendering tests for :class:`SoftBodyRenderer`."""
from __future__ import annotations

import warnings

import numpy as np
import pytest

from pharos_engine.softbody import (
    MATERIALS,
    SoftBodyRenderer,
    SoftBodyWorld,
    make_lattice_body,
    make_layered_creature,
    step,
)


@pytest.fixture(autouse=True)
def _no_runtime_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=RuntimeWarning)
        yield


def _pixels_near(img: np.ndarray, color, tol: int = 60) -> int:
    rgb = img[..., :3].astype(np.int32)
    diff = (
        np.abs(rgb[..., 0] - int(color[0]))
        + np.abs(rgb[..., 1] - int(color[1]))
        + np.abs(rgb[..., 2] - int(color[2]))
    )
    return int((diff < tol).sum())


def test_renders_steel_block():
    w = SoftBodyWorld()
    w.config["floor_y"] = 5.0
    meta = make_lattice_body(
        w, "steel", width_cells=5, height_cells=5, cell_size=0.1,
        position=(0.0, 4.0),
    )
    r = SoftBodyRenderer()
    r.bind_body(meta.body_id, "steel")
    for _ in range(20):
        step(w)
    img = r.render(w)

    assert img.shape[2] == 4
    assert img.dtype == np.uint8
    assert img.max() > 30
    near_steel = _pixels_near(img, MATERIALS["steel"].render_color, tol=120)
    assert near_steel > 200, f"steel-ish pixel count too low: {near_steel}"


def test_broken_beams_show_damage():
    w = SoftBodyWorld()
    w.config["floor_y"] = 5.0
    meta = make_lattice_body(
        w, "steel", width_cells=5, height_cells=5, cell_size=0.1,
        position=(0.0, 3.5),
    )
    s, e = meta.node_slice
    w.nodes.vel[s:e, 1] = 18.0
    r = SoftBodyRenderer()
    r.bind_body(meta.body_id, "steel")
    for _ in range(60):
        step(w)
    img = r.render(w)

    broken = int(w.beams.broken.sum())
    dmg_color = MATERIALS["steel"].damage_color
    dmg_pixels = _pixels_near(img, dmg_color, tol=70)
    if broken == 0:
        rest_shift = np.abs(w.beams.rest_length - w.beams.initial_rest_length)
        assert float(rest_shift.max()) > 0.0, "no plastic deformation, no broken beams"
    else:
        assert dmg_pixels > 30, (
            f"broken={broken} but only {dmg_pixels} damage-coloured pixels"
        )


def test_layered_creature_renders_three_layers():
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
    from pharos_engine.softbody import SoftBodyRenderConfig
    # This test inspects the *per-layer* render colours (bone/muscle/skin).
    # The flat-colour skin fill only paints the outermost layer, so we
    # disable it and opt the per-beam + per-node wireframe back on so
    # every layer shows up. (Beams/nodes are off by default in v2.)
    cfg = SoftBodyRenderConfig.from_yaml({
        "draw_skin_fill": False,
        "debug_show_beams": True,
        "debug_show_nodes": True,
    })
    r = SoftBodyRenderer(config=cfg)
    img = r.render(w, view_box=(-0.5, -0.5, 0.5, 0.5))

    rgb = img[..., :3].astype(np.int32)
    warm_red = (rgb[..., 0] > rgb[..., 2] + 30) & (rgb[..., 0] > rgb[..., 1] + 30)
    bright_neutral = (rgb[..., 0] > 130) & (rgb[..., 1] > 130) & (
        np.abs(rgb[..., 0] - rgb[..., 1]) < 25
    )
    skin_tone = (rgb[..., 0] > rgb[..., 1] + 5) & (rgb[..., 1] > rgb[..., 2] + 5) & (rgb[..., 0] > 120)
    assert int(bright_neutral.sum()) > 30, (
        f"no bright bone-like pixels: {int(bright_neutral.sum())}"
    )
    assert int(warm_red.sum()) > 30, (
        f"no muscle-red pixels: {int(warm_red.sum())}"
    )
    assert int(skin_tone.sum()) > 30, (
        f"no skin-tone pixels: {int(skin_tone.sum())}"
    )
