"""Regression tests for Nova3D pillar 5 — SceneNode + Prefab + Rust walk.

Covers:
* SceneNode.add_child + world_transform composition
* SceneNode.world_matrix on translations + rotations
* SceneNode.walk depth-first order
* Cycle-guard raises ValueError
* Prefab YAML round-trip preserves structure
* Prefab.instantiate produces independent copies
* _core.scene_walk.walk_transforms sanity (soft-import, skip if unbuilt)
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from pharos_engine.prefab import Prefab
from pharos_engine.scene import Scene
from pharos_engine.scene_node import SceneNode, Transform3D


# ---------------------------------------------------------------------------
# SceneNode fundamentals
# ---------------------------------------------------------------------------


def test_add_child_and_world_transform_translation():
    """Child at (1,0,0) under parent at (2,0,0) should have world x=3."""
    parent = SceneNode("parent", Transform3D(position=(2.0, 0.0, 0.0)))
    child = SceneNode("child", Transform3D(position=(1.0, 0.0, 0.0)))
    parent.add_child(child)

    world = child.world_transform()
    assert world.position == pytest.approx((3.0, 0.0, 0.0), abs=1e-6)


def test_world_matrix_pure_translation():
    node = SceneNode("t", Transform3D(position=(5.0, -2.0, 7.0)))
    m = node.world_matrix()
    assert m[0, 3] == pytest.approx(5.0)
    assert m[1, 3] == pytest.approx(-2.0)
    assert m[2, 3] == pytest.approx(7.0)
    # rotation block is identity
    np.testing.assert_allclose(m[:3, :3], np.eye(3), atol=1e-6)


def test_world_matrix_rotation_90_z_transforms_x_to_y():
    """Rotating a child at (1,0,0) 90 degrees about Z under identity parent
    should place it at (0,1,0)."""
    parent = SceneNode("p", Transform3D(rotation_euler=(0.0, 0.0, math.pi / 2)))
    child = SceneNode("c", Transform3D(position=(1.0, 0.0, 0.0)))
    parent.add_child(child)
    world = child.world_transform()
    assert world.position[0] == pytest.approx(0.0, abs=1e-6)
    assert world.position[1] == pytest.approx(1.0, abs=1e-6)
    assert world.position[2] == pytest.approx(0.0, abs=1e-6)


def test_world_matrix_scale_composition():
    parent = SceneNode("p", Transform3D(scale=(2.0, 2.0, 2.0)))
    child = SceneNode("c", Transform3D(position=(1.0, 0.0, 0.0), scale=(3.0, 3.0, 3.0)))
    parent.add_child(child)
    world = child.world_transform()
    # child's position gets scaled by parent's scale
    assert world.position[0] == pytest.approx(2.0, abs=1e-6)
    # scales multiply
    assert world.scale == pytest.approx((6.0, 6.0, 6.0), abs=1e-6)


def test_walk_depth_first_order():
    root = SceneNode("root")
    a = SceneNode("a")
    b = SceneNode("b")
    a1 = SceneNode("a1")
    a2 = SceneNode("a2")
    root.add_child(a)
    root.add_child(b)
    a.add_child(a1)
    a.add_child(a2)

    names = [n.name for n in root.walk()]
    assert names == ["root", "a", "a1", "a2", "b"]


def test_find_by_name():
    root = SceneNode("root")
    child = SceneNode("target")
    grand = SceneNode("grand")
    root.add_child(child)
    child.add_child(grand)
    assert root.find_by_name("grand") is grand
    assert root.find_by_name("missing") is None


# ---------------------------------------------------------------------------
# Cycle guard
# ---------------------------------------------------------------------------


def test_cycle_guard_self():
    node = SceneNode("self")
    with pytest.raises(ValueError):
        node.add_child(node)


def test_cycle_guard_ancestor():
    a = SceneNode("a")
    b = SceneNode("b")
    a.add_child(b)
    with pytest.raises(ValueError):
        b.add_child(a)


# ---------------------------------------------------------------------------
# Scene integration (backwards-compat)
# ---------------------------------------------------------------------------


def test_scene_has_root_node_and_add_node():
    scene = Scene("test")
    assert isinstance(scene.root_node, SceneNode)
    n = SceneNode("world")
    scene.add_node(n)
    assert n.parent is scene.root_node
    assert n in scene.root_node.children


def test_scene_flat_entity_api_still_works():
    """Backwards-compat: existing Entity dict API must be untouched."""
    from pharos_engine.entity import Entity
    scene = Scene("test")
    e = Entity(name="ghost")
    scene.add(e)
    assert scene.get(e.id) is e
    assert e in scene.entities


# ---------------------------------------------------------------------------
# Prefab YAML round-trip + instantiate
# ---------------------------------------------------------------------------


def test_prefab_yaml_roundtrip_preserves_structure(tmp_path: Path):
    root = SceneNode("root", Transform3D(position=(1.0, 2.0, 3.0)))
    child = SceneNode(
        "child",
        Transform3D(position=(0.5, 0.0, 0.0), rotation_euler=(0.1, 0.2, 0.3)),
        metadata={"tag": "npc", "team": 2},
    )
    root.add_child(child)
    pf = Prefab(root=root, overrides={"variant": "hero"})

    path = tmp_path / "prefab.yaml"
    pf.save(path)
    loaded = Prefab.load(path)

    assert loaded.root.name == "root"
    assert loaded.root.local_transform.position == pytest.approx((1.0, 2.0, 3.0))
    assert len(loaded.root.children) == 1
    c = loaded.root.children[0]
    assert c.name == "child"
    assert c.local_transform.rotation_euler == pytest.approx((0.1, 0.2, 0.3), abs=1e-9)
    assert c.metadata == {"tag": "npc", "team": 2}
    assert loaded.overrides == {"variant": "hero"}


def test_prefab_instantiate_is_independent():
    root = SceneNode("root", Transform3D(position=(0.0, 0.0, 0.0)))
    child = SceneNode("child", Transform3D(position=(1.0, 0.0, 0.0)))
    root.add_child(child)
    pf = Prefab(root=root)

    inst1 = pf.instantiate()
    inst2 = pf.instantiate()

    # Independent trees
    assert inst1 is not inst2
    assert inst1 is not pf.root
    assert inst1.children[0] is not inst2.children[0]
    assert inst1.children[0] is not child

    # Mutating one does not affect the other
    inst1.children[0].local_transform = Transform3D(position=(99.0, 0.0, 0.0))
    assert inst2.children[0].local_transform.position == (1.0, 0.0, 0.0)
    assert pf.root.children[0].local_transform.position == (1.0, 0.0, 0.0)


def test_prefab_instantiate_under_parent():
    parent = SceneNode("world")
    root = SceneNode("prefab_root")
    root.add_child(SceneNode("leaf"))
    pf = Prefab(root=root)

    inst = pf.instantiate(parent=parent)
    assert inst.parent is parent
    assert inst in parent.children


# ---------------------------------------------------------------------------
# Rust scene_walk kernel (soft-imported)
# ---------------------------------------------------------------------------


def test_rust_walk_transforms_matches_python():
    """Skip cleanly if _core.scene_walk isn't compiled in."""
    try:
        from pharos_engine import _core
        scene_walk = getattr(_core, "scene_walk", None)
    except Exception:
        pytest.skip("_core not importable in this build")

    if scene_walk is None or not hasattr(scene_walk, "walk_transforms"):
        pytest.skip("_core.scene_walk.walk_transforms not compiled in this build")

    # parent at (2,0,0), child at (1,0,0) under parent → world (3,0,0)
    T = scene_walk.Transform3D
    parent_t = T(2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
    child_t = T(1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0)

    matrices = scene_walk.walk_transforms([parent_t, child_t], [-1, 0])
    assert len(matrices) == 2
    # Row-major layout: world position is at indices 3, 7, 11
    child_world = matrices[1]
    assert child_world[3] == pytest.approx(3.0, abs=1e-5)
    assert child_world[7] == pytest.approx(0.0, abs=1e-5)
    assert child_world[11] == pytest.approx(0.0, abs=1e-5)
