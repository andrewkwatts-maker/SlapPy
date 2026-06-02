"""Tests for the high-level :mod:`slappyengine.studio` helpers.

The studio module is sugar over softbody/fluid/render — these tests verify
the helpers wire things up correctly without trying to re-test the underlying
physics (which has its own coverage).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from slappyengine.softbody import SoftBodyWorld, make_lattice_body
from slappyengine.studio import (
    Stage,
    anchor,
    centroid,
    fluid_stage,
    fluid_with_softbody_stage,
    humanoid_stage,
    kick,
    output_path,
    record,
    softbody_stage,
    terrain_overlay,
    translate,
)


def test_output_path_with_demo_file(tmp_path):
    demo = tmp_path / "demo.py"
    demo.write_text("# stub")
    p = output_path("foo", str(demo), subdir="bar")
    assert p.name == "foo.gif"
    assert p.parent.name == "bar"
    assert p.parent.parent.name == "output"
    assert p.parent.exists()


def test_output_path_respects_explicit_extension(tmp_path):
    demo = tmp_path / "demo.py"
    p = output_path("frame.png", str(demo), ext="png")
    assert p.name == "frame.png"


def test_stage_softbody_defaults_are_usable():
    stage = softbody_stage(floor_y=4.0)
    assert stage.softbody is stage.world
    assert stage.fluid is None
    assert stage.world.config["floor_y"] == 4.0
    assert stage.renderer is not None
    assert stage.view_box == (-2.0, -1.0, 2.0, 5.0)


def test_stage_softbody_overrides_apply():
    stage = softbody_stage(
        view_box=(-1, 0, 1, 4),
        gravity=(0.0, 0.0),
        contact_enabled=False,
        floor_friction=0.1,
        width=120, height=100,
    )
    assert stage.world.config["gravity"] == [0.0, 0.0]
    assert stage.world.config["contact"]["enabled"] is False
    assert stage.world.config["floor_friction"] == pytest.approx(0.1)


def test_stage_fluid_settles_and_reports_surface():
    stage = fluid_stage(
        view_box=(-1.5, 2.0, 1.5, 5.5),
        walls=(-1.0, 1.0), floor_y=5.0,
        pool=dict(material="water", nx=6, ny=6, spacing=0.06,
                   origin=(-0.18, 2.6)),
        settle_steps=10,
        width=160, height=120,
    )
    assert stage.fluid is stage.world
    assert stage.softbody is None
    assert stage.surface_y is not None
    assert 2.0 < stage.surface_y < 5.5


def test_stage_fluid_with_softbody_composes_both():
    stage = fluid_with_softbody_stage(
        pool=dict(material="water", nx=6, ny=6, spacing=0.06,
                   origin=(-0.18, 3.0)),
        settle_steps=10, width=160, height=120,
    )
    assert stage.fluid is not None
    assert stage.softbody is not None
    assert stage.surface_y is not None
    # Default coupling off so explicit Archimedes is the buoyancy path
    assert stage.fluid.config["contact"]["enabled"] is False


def test_kick_anchor_centroid_translate_round_trip():
    world = SoftBodyWorld()
    body = make_lattice_body(world, "wood",
                              width_cells=2, height_cells=2, cell_size=0.10,
                              position=(0.0, 0.0))

    # Centroid before any motion: ~ (0.10, 0.10) for a 2x2 cell lattice at origin
    cx, cy = centroid(world, body.node_slice)
    assert cx == pytest.approx(0.10, abs=1e-3)
    assert cy == pytest.approx(0.10, abs=1e-3)

    # Translate
    translate(world, body.node_slice, dx=1.0, dy=-0.5)
    cx2, cy2 = centroid(world, body.node_slice)
    assert cx2 == pytest.approx(1.10, abs=1e-3)
    assert cy2 == pytest.approx(-0.40, abs=1e-3)

    # Kick — uniform velocity + twist
    kick(world, body.node_slice, vx=2.0, vy=-3.0, twist=0.5)
    ns, ne = body.node_slice
    assert np.allclose(world.nodes.vel[ns:ne, 1], -3.0)
    # vy not affected by twist; vx has uniform 2.0 + per-node spread
    assert world.nodes.vel[ns:ne, 0].mean() == pytest.approx(2.0, abs=1e-3)
    assert world.nodes.vel[ns:ne, 0].std() > 0.0   # spread from twist

    # Anchor
    anchor(world, body.node_slice)
    assert bool(world.nodes.fixed[ns:ne].all())
    assert float(world.nodes.inv_mass[ns:ne].max()) == 0.0


def test_bodymeta_methods_match_module_functions():
    """BodyMeta.kick / .anchor / .centroid / .translate are the chainable
    duals of the module-level helpers — same effect, no surprises."""
    world = SoftBodyWorld()
    a = make_lattice_body(world, "wood", width_cells=2, height_cells=2,
                          cell_size=0.10, position=(0.0, 0.0))
    b = make_lattice_body(world, "wood", width_cells=2, height_cells=2,
                          cell_size=0.10, position=(0.0, 0.0))

    kick(world, a.node_slice, vx=1.0, vy=2.0)
    b.kick(world, vx=1.0, vy=2.0)
    ans, ane = a.node_slice
    bns, bne = b.node_slice
    assert np.allclose(world.nodes.vel[ans:ane], world.nodes.vel[bns:bne])

    a.translate(world, 0.5, -0.5)
    translate(world, b.node_slice, 0.5, -0.5)
    assert np.allclose(world.nodes.pos[ans:ane], world.nodes.pos[bns:bne])

    a_ctr = a.centroid(world)
    assert a_ctr == centroid(world, a.node_slice)

    a.anchor(world)
    anchor(world, b.node_slice)
    assert bool(world.nodes.fixed[ans:ane].all())
    assert bool(world.nodes.fixed[bns:bne].all())


def test_bodymeta_methods_are_chainable():
    world = SoftBodyWorld()
    body = (make_lattice_body(world, "wood",
                              width_cells=2, height_cells=2, cell_size=0.10,
                              position=(0.0, 0.0))
            .translate(world, 1.0, 0.0)
            .kick(world, vy=5.0)
            .anchor(world))
    ns, ne = body.node_slice
    assert world.nodes.pos[ns:ne, 0].mean() == pytest.approx(1.10, abs=1e-3)
    # Anchor was the last call — inv_mass should be zeroed
    assert float(world.nodes.inv_mass[ns:ne].max()) == 0.0


def test_record_softbody_writes_gif(tmp_path):
    stage = softbody_stage(view_box=(-1, -1, 1, 4),
                            width=80, height=60, floor_y=3.0)
    body = make_lattice_body(stage.world, "wood",
                              width_cells=2, height_cells=2, cell_size=0.10,
                              position=(-0.10, 1.0))
    body.kick(stage.world, vy=2.0)
    out = tmp_path / "test_record.gif"
    result = record(stage, frames=8, output=out, fps=30)
    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0


def test_humanoid_stage_defaults_kinematic():
    """humanoid_stage() yields a world with no gravity, contact off, floor
    effectively disabled — the kinematic configuration the IK demos need."""
    stage = humanoid_stage()
    assert stage.world.config["gravity"] == [0.0, 0.0]
    assert stage.world.config["contact"]["enabled"] is False
    assert stage.world.config["floor_y"] == pytest.approx(100.0)
    assert stage.softbody is stage.world


def test_humanoid_stage_overrides_propagate():
    stage = humanoid_stage(view_box=(-1, 0, 1, 4),
                            gravity=(0.0, 9.81),
                            contact_enabled=True,
                            floor_y_far_below=5.0)
    assert stage.world.config["gravity"] == [0.0, 9.81]
    assert stage.world.config["contact"]["enabled"] is True
    assert stage.world.config["floor_y"] == pytest.approx(5.0)


def test_record_step_world_false_freezes_world(tmp_path):
    """With step_world=False the world is unchanged across frames — used by
    the standing-pose demo to capture the same frame N times."""
    stage = softbody_stage(view_box=(-1, -1, 1, 4),
                            width=80, height=60, floor_y=3.0)
    body = make_lattice_body(stage.world, "wood",
                              width_cells=2, height_cells=2, cell_size=0.10,
                              position=(-0.10, 1.0))
    body.kick(stage.world, vy=5.0)
    snapshot = stage.world.nodes.pos.copy()
    out = tmp_path / "static.gif"
    record(stage, frames=6, output=out, step_world=False)
    # No step ran → positions identical to snapshot
    assert np.allclose(stage.world.nodes.pos, snapshot)


def test_terrain_overlay_renders_visible_line(tmp_path):
    """terrain_overlay paints a visible non-background line in the result."""
    import math
    from PIL import Image

    stage = softbody_stage(view_box=(-2, -1, 2, 4),
                            width=80, height=60, floor_y=3.0)
    out = tmp_path / "overlay.gif"
    record(stage, frames=2, output=out,
           overlay=terrain_overlay(lambda x: 2.0 + 0.5 * math.sin(x),
                                    color=(0, 255, 0), width_px=2))
    # GIF should exist and contain a green pixel from the overlay
    img = Image.open(out).convert("RGB")
    found_green = False
    for px in img.getdata():
        if px[1] > 100 and px[0] < 50 and px[2] < 50:
            found_green = True
            break
    assert found_green, "terrain_overlay should paint green pixels"


def test_record_passes_pre_and_post_step_callbacks():
    stage = softbody_stage(view_box=(-1, -1, 1, 4),
                            width=64, height=48, floor_y=3.0)
    make_lattice_body(stage.world, "wood",
                       width_cells=2, height_cells=2, cell_size=0.10,
                       position=(-0.10, 1.0))
    seen_pre, seen_post = [], []

    def pre(s): seen_pre.append(s.world.nodes.count)
    def post(s, f): seen_post.append(f)

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        record(stage, frames=4, output=Path(td) / "cb.gif",
               pre_step=pre, post_step=post)
    assert len(seen_pre) == 4
    assert seen_post == [0, 1, 2, 3]
