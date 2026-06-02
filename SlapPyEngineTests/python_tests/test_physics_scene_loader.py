"""Tests for the YAML-driven physics scene loader."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from slappyengine.physics import (
    PhysicsBody,
    PhysicsWorld,
    SceneSpec,
    build_world_from_scene,
    load_and_build,
    load_scene_spec,
)


# Locate the project-root tests/fixtures/scenes directory.
# We walk up from this test file (python/tests/) to the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "scenes"


def _fixture(name: str) -> Path:
    p = _FIXTURES / name
    assert p.exists(), f"Missing fixture: {p}"
    return p


# -- parsing -----------------------------------------------------------------

def test_load_scene_yaml_returns_spec():
    spec = load_scene_spec(_fixture("drop_steel_into_stone.yml"))
    assert isinstance(spec, SceneSpec)
    assert len(spec.bodies) == 2
    names = {b.name for b in spec.bodies}
    assert names == {"ground", "ball"}
    ground = next(b for b in spec.bodies if b.name == "ground")
    assert ground.material == "stone"
    assert ground.shape == "rect"
    assert ground.width == 240
    assert ground.height == 16
    assert ground.fixed is True


# -- build -------------------------------------------------------------------

def test_build_world_creates_all_bodies():
    spec = load_scene_spec(_fixture("drop_steel_into_stone.yml"))
    world = build_world_from_scene(spec)
    assert isinstance(world, PhysicsWorld)
    assert len(world.bodies) == 2
    assert all(isinstance(b, PhysicsBody) for b in world.bodies)


def test_body_position_and_velocity_applied():
    world = load_and_build(_fixture("splash.yml"))
    ball = world.body_by_name("ball")
    pool = world.body_by_name("pool")
    assert ball.position == pytest.approx((0.0, -50.0))
    assert ball.velocity == pytest.approx((0.0, 30.0))
    assert pool.position == pytest.approx((0.0, 150.0))


def test_fixed_flag_honoured():
    world = load_and_build(_fixture("drop_steel_into_stone.yml"))
    ground = world.body_by_name("ground")
    ball = world.body_by_name("ball")
    assert ground.fixed is True
    # Hull-level fixed flag too.
    assert bool(world.hulls.fixed[ground.root_hull_id]) is True
    assert ball.fixed is False
    assert bool(world.hulls.fixed[ball.root_hull_id]) is False


def test_world_gravity_override_applied():
    world = load_and_build(_fixture("splash.yml"))
    # splash.yml sets gravity to [0.0, 250.0]
    assert world.config.world.gravity == pytest.approx((0.0, 250.0))


def test_body_by_name_lookup():
    world = load_and_build(_fixture("drop_steel_into_stone.yml"))
    ground = world.body_by_name("ground")
    assert isinstance(ground, PhysicsBody)
    assert ground.material_name == "stone"
    # Lookup table also exposed as a dict for iteration.
    assert set(world.body_by_name_map.keys()) == {"ground", "ball"}


def test_multi_body_scene_creates_three():
    world = load_and_build(_fixture("multi_body.yml"))
    assert len(world.bodies) == 3
    floor = world.body_by_name("floor")
    steel_ball = world.body_by_name("steel_ball")
    mud_block = world.body_by_name("mud_block")
    assert floor.material_name == "stone"
    assert steel_ball.material_name == "steel"
    assert mud_block.material_name == "mud"
    assert mud_block.velocity == pytest.approx((-5.0, 0.0))


def test_unknown_material_raises():
    with pytest.raises(ValueError) as excinfo:
        load_and_build(_fixture("bad_material.yml"))
    msg = str(excinfo.value)
    assert "unobtanium" in msg


def test_unknown_shape_raises(tmp_path):
    bad = tmp_path / "bad_shape.yml"
    bad.write_text(
        "bodies:\n"
        "  - name: thing\n"
        "    material: stone\n"
        "    shape: trapezoid\n"
        "    position: [0, 0]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="trapezoid"):
        load_scene_spec(bad)


def test_custom_silhouette_png_load(tmp_path):
    # Author a 32x32 PNG with an L-shaped alpha mask.
    pytest.importorskip("PIL")
    from PIL import Image

    arr = np.zeros((32, 32, 4), dtype=np.uint8)
    # Solid alpha in an L-shape (top-left vertical bar + bottom horizontal).
    arr[..., :3] = 255
    arr[0:32, 0:8, 3] = 255   # vertical bar
    arr[24:32, 0:32, 3] = 255  # horizontal bar
    png_path = tmp_path / "L_shape.png"
    Image.fromarray(arr, mode="RGBA").save(png_path)

    yml_path = tmp_path / "L_scene.yml"
    yml_path.write_text(
        f"bodies:\n"
        f"  - name: ell\n"
        f"    material: steel\n"
        f"    shape: custom_silhouette\n"
        f"    silhouette_path: {png_path.as_posix()}\n"
        f"    position: [0, 0]\n",
        encoding="utf-8",
    )

    world = load_and_build(yml_path)
    ell = world.body_by_name("ell")
    cells = ell.cells
    assert cells is not None, "T2 body should have a cell grid"
    density = cells[..., 9]  # _IDX_DENSITY
    # Cells inside the L-shape should be non-zero; cells in the empty
    # quadrant (top-right area) should be zero.
    # The L's empty region is the top-right block from row 0..24, col 8..32.
    empty_block = density[0:20, 16:32]
    assert empty_block.sum() == 0.0, "Empty area must have zero density"
    # And the filled region (e.g. top-left vertical bar) should have density.
    filled_block = density[0:20, 0:8]
    assert filled_block.sum() > 0.0, "Filled vertical bar must seed density"
