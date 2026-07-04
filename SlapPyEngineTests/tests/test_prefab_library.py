"""Tests for :mod:`slappyengine.prefabs` — Prefab dataclass + PrefabLibrary."""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from slappyengine.dynamics import Body, World
from slappyengine.prefabs import CATEGORIES, Prefab, PrefabLibrary


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def crate_prefab() -> Prefab:
    return Prefab(
        name="crate",
        category="props",
        body_spec={"kind": "box", "width": 1.0, "height": 1.0, "mass": 4.0},
    )


@pytest.fixture
def library_with_baked() -> PrefabLibrary:
    lib = PrefabLibrary()
    lib.load_baked()
    return lib


# ---------------------------------------------------------------------------
# 1. Prefab dataclass validation
# ---------------------------------------------------------------------------


def test_prefab_construct_ok(crate_prefab: Prefab) -> None:
    assert crate_prefab.name == "crate"
    assert crate_prefab.category == "props"
    assert crate_prefab.body_spec["kind"] == "box"
    assert crate_prefab.joint_specs == []
    assert crate_prefab.child_prefabs == []


def test_prefab_empty_name_rejected() -> None:
    with pytest.raises(ValueError):
        Prefab(name="", category="props", body_spec={"kind": "point"})


def test_prefab_unknown_category_rejected() -> None:
    with pytest.raises(ValueError):
        Prefab(name="x", category="bogus", body_spec={"kind": "point"})


def test_prefab_missing_body_kind_rejected() -> None:
    with pytest.raises(ValueError):
        Prefab(name="x", category="props", body_spec={})


def test_prefab_unknown_body_kind_rejected() -> None:
    with pytest.raises(ValueError):
        Prefab(name="x", category="props", body_spec={"kind": "banana"})


def test_prefab_bad_joint_specs_type_rejected() -> None:
    with pytest.raises(TypeError):
        Prefab(
            name="x",
            category="props",
            body_spec={"kind": "point"},
            joint_specs="oops",  # type: ignore[arg-type]
        )


def test_prefab_bad_metadata_type_rejected() -> None:
    with pytest.raises(TypeError):
        Prefab(
            name="x",
            category="props",
            body_spec={"kind": "point"},
            metadata=[1, 2, 3],  # type: ignore[arg-type]
        )


def test_prefab_categories_exposed() -> None:
    assert "props" in CATEGORIES
    assert "characters" in CATEGORIES
    assert "vehicles" in CATEGORIES
    assert "particles" in CATEGORIES
    assert "structural" in CATEGORIES


# ---------------------------------------------------------------------------
# 2. YAML round-trip
# ---------------------------------------------------------------------------


def test_yaml_round_trip_preserves_fields(crate_prefab: Prefab) -> None:
    text = crate_prefab.to_yaml()
    clone = Prefab.from_yaml(text)
    assert clone.name == crate_prefab.name
    assert clone.category == crate_prefab.category
    assert clone.body_spec == crate_prefab.body_spec
    assert clone.joint_specs == crate_prefab.joint_specs
    assert clone.child_prefabs == crate_prefab.child_prefabs
    assert clone.metadata == crate_prefab.metadata


def test_yaml_round_trip_with_joints_and_children() -> None:
    p = Prefab(
        name="parent",
        category="structural",
        body_spec={"kind": "point"},
        joint_specs=[
            {
                "kind": "distance",
                "node_a": 0,
                "node_b": 1,
                "rest_length": 1.0,
                "stiffness": 1.0e6,
                "damping": 0.05,
            }
        ],
        child_prefabs=["crate", "ball"],
        metadata={"tag": "hero", "hits": 3},
    )
    clone = Prefab.from_yaml(p.to_yaml())
    assert clone.joint_specs[0]["kind"] == "distance"
    assert clone.child_prefabs == ["crate", "ball"]
    assert clone.metadata == {"tag": "hero", "hits": 3}


def test_from_yaml_rejects_non_dict() -> None:
    with pytest.raises(ValueError):
        Prefab.from_yaml("- 1\n- 2\n")


def test_from_dict_rejects_non_dict() -> None:
    with pytest.raises(TypeError):
        Prefab.from_dict("not a dict")  # type: ignore[arg-type]


def test_from_dict_missing_keys_rejected() -> None:
    with pytest.raises(ValueError):
        Prefab.from_dict({"name": "x"})


# ---------------------------------------------------------------------------
# 3. PrefabLibrary basics
# ---------------------------------------------------------------------------


def test_library_register_get() -> None:
    lib = PrefabLibrary()
    p = Prefab(name="x", category="props", body_spec={"kind": "point"})
    lib.register(p)
    assert lib.get("x") is p
    assert "x" in lib
    assert len(lib) == 1


def test_library_get_missing_returns_none() -> None:
    lib = PrefabLibrary()
    assert lib.get("nope") is None


def test_library_register_type_check() -> None:
    lib = PrefabLibrary()
    with pytest.raises(TypeError):
        lib.register("not a prefab")  # type: ignore[arg-type]


def test_library_list_all_sorted() -> None:
    lib = PrefabLibrary()
    lib.register(Prefab(name="zebra", category="props", body_spec={"kind": "point"}))
    lib.register(Prefab(name="alpha", category="props", body_spec={"kind": "point"}))
    lib.register(Prefab(name="mango", category="props", body_spec={"kind": "point"}))
    names = [p.name for p in lib.list_all()]
    assert names == ["alpha", "mango", "zebra"]


def test_library_list_by_category() -> None:
    lib = PrefabLibrary()
    lib.register(Prefab(name="a", category="props", body_spec={"kind": "point"}))
    lib.register(Prefab(name="b", category="characters", body_spec={"kind": "point"}))
    lib.register(Prefab(name="c", category="props", body_spec={"kind": "point"}))
    props = [p.name for p in lib.list_by_category("props")]
    assert props == ["a", "c"]
    chars = [p.name for p in lib.list_by_category("characters")]
    assert chars == ["b"]


def test_library_list_by_category_unknown() -> None:
    lib = PrefabLibrary()
    with pytest.raises(ValueError):
        lib.list_by_category("mystery")


def test_library_register_replaces() -> None:
    lib = PrefabLibrary()
    lib.register(Prefab(name="x", category="props", body_spec={"kind": "point"}))
    p2 = Prefab(name="x", category="characters", body_spec={"kind": "point"})
    lib.register(p2)
    assert lib.get("x") is p2
    assert lib.get("x").category == "characters"


def test_library_clear() -> None:
    lib = PrefabLibrary()
    lib.register(Prefab(name="x", category="props", body_spec={"kind": "point"}))
    lib.clear()
    assert len(lib) == 0
    assert lib.get("x") is None


# ---------------------------------------------------------------------------
# 4. load_from_dir
# ---------------------------------------------------------------------------


def test_load_from_dir_reads_yaml_files(tmp_path: Path) -> None:
    (tmp_path / "a.prefab.yaml").write_text(
        Prefab(name="a", category="props", body_spec={"kind": "point"}).to_yaml(),
        encoding="utf-8",
    )
    (tmp_path / "b.prefab.yaml").write_text(
        Prefab(name="b", category="structural", body_spec={"kind": "point"}).to_yaml(),
        encoding="utf-8",
    )
    lib = PrefabLibrary()
    loaded = lib.load_from_dir(tmp_path)
    assert set(loaded) == {"a", "b"}
    assert lib.get("a") is not None
    assert lib.get("b") is not None


def test_load_from_dir_recurses_subdirs(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deep.prefab.yaml").write_text(
        Prefab(
            name="deep", category="props", body_spec={"kind": "point"},
        ).to_yaml(),
        encoding="utf-8",
    )
    lib = PrefabLibrary()
    loaded = lib.load_from_dir(tmp_path)
    assert loaded == ["deep"]


def test_load_from_dir_ignores_non_matching_files(tmp_path: Path) -> None:
    (tmp_path / "ignored.yaml").write_text("noise: 1\n", encoding="utf-8")
    (tmp_path / "keep.prefab.yaml").write_text(
        Prefab(name="keep", category="props", body_spec={"kind": "point"}).to_yaml(),
        encoding="utf-8",
    )
    lib = PrefabLibrary()
    loaded = lib.load_from_dir(tmp_path)
    assert loaded == ["keep"]


def test_load_from_dir_missing_raises(tmp_path: Path) -> None:
    lib = PrefabLibrary()
    with pytest.raises(FileNotFoundError):
        lib.load_from_dir(tmp_path / "does_not_exist")


def test_load_from_dir_skips_corrupt_files(tmp_path: Path) -> None:
    (tmp_path / "broken.prefab.yaml").write_text(
        "name: x\ncategory: props\nbody_spec:\n  kind: banana\n",
        encoding="utf-8",
    )
    (tmp_path / "ok.prefab.yaml").write_text(
        Prefab(name="ok", category="props", body_spec={"kind": "point"}).to_yaml(),
        encoding="utf-8",
    )
    lib = PrefabLibrary()
    loaded = lib.load_from_dir(tmp_path)
    assert loaded == ["ok"]


# ---------------------------------------------------------------------------
# 5. bake_defaults
# ---------------------------------------------------------------------------


def test_bake_defaults_copies_files(tmp_path: Path) -> None:
    lib = PrefabLibrary()
    written = lib.bake_defaults(user_dir=tmp_path)
    # We ship 6 baked prefabs.
    assert len(written) == 6
    names = sorted(p.name for p in written)
    assert names == sorted([
        "ball.prefab.yaml",
        "bridge.prefab.yaml",
        "chain.prefab.yaml",
        "crate.prefab.yaml",
        "ragdoll.prefab.yaml",
        "windmill.prefab.yaml",
    ])


def test_bake_defaults_idempotent(tmp_path: Path) -> None:
    lib = PrefabLibrary()
    first = lib.bake_defaults(user_dir=tmp_path)
    second = lib.bake_defaults(user_dir=tmp_path)
    assert len(first) == 6
    # Second call must copy nothing new — every file already exists.
    assert second == []


def test_bake_defaults_preserves_user_edits(tmp_path: Path) -> None:
    lib = PrefabLibrary()
    lib.bake_defaults(user_dir=tmp_path)
    user_crate = tmp_path / "crate.prefab.yaml"
    user_crate.write_text("EDITED BY USER\n", encoding="utf-8")
    lib.bake_defaults(user_dir=tmp_path)
    assert user_crate.read_text(encoding="utf-8") == "EDITED BY USER\n"


def test_bake_defaults_returns_empty_for_missing_baked(tmp_path: Path) -> None:
    lib = PrefabLibrary()
    written = lib.bake_defaults(
        user_dir=tmp_path / "user",
        baked_dir=tmp_path / "no_baked",
    )
    assert written == []


# ---------------------------------------------------------------------------
# 6. Six baked prefabs parse cleanly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["crate", "ball", "bridge", "ragdoll", "windmill", "chain"],
)
def test_baked_prefab_parses(library_with_baked: PrefabLibrary, name: str) -> None:
    prefab = library_with_baked.get(name)
    assert prefab is not None, f"prefab {name!r} missing from baked library"
    assert prefab.name == name
    assert prefab.category in CATEGORIES
    assert "kind" in prefab.body_spec


def test_baked_library_has_six_entries(library_with_baked: PrefabLibrary) -> None:
    assert len(library_with_baked) == 6


def test_baked_categories_cover_expected(library_with_baked: PrefabLibrary) -> None:
    cats = {p.category for p in library_with_baked.list_all()}
    # We ship props + characters + structural at minimum.
    assert {"props", "characters", "structural"} <= cats


# ---------------------------------------------------------------------------
# 7. Prefab.spawn creates expected body counts
# ---------------------------------------------------------------------------


def test_spawn_point_creates_one_body() -> None:
    world = World(gravity=(0.0, -9.81))
    p = Prefab(name="mote", category="particles", body_spec={"kind": "point"})
    bodies = p.spawn(world, (0.0, 0.0))
    assert len(bodies) == 1
    assert isinstance(bodies[0], Body)
    assert world.positions.shape[0] == 1


def test_spawn_box_creates_four_nodes_six_joints() -> None:
    world = World(gravity=(0.0, -9.81))
    p = Prefab(
        name="crate", category="props",
        body_spec={"kind": "box", "width": 1.0, "height": 1.0, "mass": 4.0},
    )
    bodies = p.spawn(world, (0.0, 0.0))
    assert len(bodies) == 1
    # Box = 4 corner nodes.
    assert world.positions.shape[0] == 4
    # 4 perimeter + 2 diagonal = 6 joints.
    assert len(world.joints) == 6


def test_spawn_baked_crate(library_with_baked: PrefabLibrary) -> None:
    world = World(gravity=(0.0, -9.81))
    prefab = library_with_baked.get("crate")
    bodies = prefab.spawn(world, (0.0, 5.0))
    assert len(bodies) == 1
    assert world.positions.shape[0] == 4


def test_spawn_baked_ball(library_with_baked: PrefabLibrary) -> None:
    world = World(gravity=(0.0, -9.81))
    prefab = library_with_baked.get("ball")
    bodies = prefab.spawn(world, (0.0, 5.0))
    assert len(bodies) == 1
    assert world.positions.shape[0] == 1


def test_spawn_baked_bridge_rope(library_with_baked: PrefabLibrary) -> None:
    world = World(gravity=(0.0, -9.81))
    prefab = library_with_baked.get("bridge")
    bodies = prefab.spawn(world, (0.0, 5.0))
    assert len(bodies) == 1
    # node_count = 3 for the shipped bridge.
    assert world.positions.shape[0] == 3


def test_spawn_baked_chain_five_links(library_with_baked: PrefabLibrary) -> None:
    world = World(gravity=(0.0, -9.81))
    prefab = library_with_baked.get("chain")
    bodies = prefab.spawn(world, (0.0, 5.0))
    assert len(bodies) == 1
    assert world.positions.shape[0] == 5
    assert len(world.joints) == 4


def test_spawn_baked_windmill_cross(library_with_baked: PrefabLibrary) -> None:
    world = World(gravity=(0.0, -9.81))
    prefab = library_with_baked.get("windmill")
    bodies = prefab.spawn(world, (0.0, 5.0))
    assert len(bodies) == 1
    # hub + 4 arm tips = 5 nodes, 4 spokes + 2 rim braces = 6 joints.
    assert world.positions.shape[0] == 5
    assert len(world.joints) == 6


def test_spawn_baked_ragdoll(library_with_baked: PrefabLibrary) -> None:
    world = World(gravity=(0.0, -9.81))
    prefab = library_with_baked.get("ragdoll")
    bodies = prefab.spawn(world, (0.0, 5.0))
    assert len(bodies) == 1
    # 7 bones => 1 root + 7 child endpoints = 8 nodes.
    assert world.positions.shape[0] == 8


def test_spawn_rotation_offsets_nodes() -> None:
    world = World(gravity=(0.0, -9.81))
    p = Prefab(
        name="c", category="structural",
        body_spec={"kind": "chain", "link_count": 3, "link_length": 1.0},
    )
    p.spawn(world, (0.0, 0.0), rotation=math.pi / 2.0)
    # After 90-degree rotation the chain lies along +y.
    positions = world.positions
    assert math.isclose(positions[1, 0], 0.0, abs_tol=1e-9)
    assert math.isclose(positions[1, 1], 1.0, abs_tol=1e-9)


def test_spawn_bad_position_rejected() -> None:
    world = World(gravity=(0.0, -9.81))
    p = Prefab(name="x", category="props", body_spec={"kind": "point"})
    with pytest.raises(TypeError):
        p.spawn(world, "not a position")  # type: ignore[arg-type]


def test_spawn_nonfinite_position_rejected() -> None:
    world = World(gravity=(0.0, -9.81))
    p = Prefab(name="x", category="props", body_spec={"kind": "point"})
    with pytest.raises(ValueError):
        p.spawn(world, (float("nan"), 0.0))


def test_spawn_composite_child_prefabs() -> None:
    lib = PrefabLibrary()
    child = Prefab(name="mote", category="particles", body_spec={"kind": "point"})
    lib.register(child)
    parent = Prefab(
        name="host",
        category="props",
        body_spec={"kind": "composite"},
        child_prefabs=["mote", "mote"],
    )
    lib.register(parent)
    world = World(gravity=(0.0, -9.81))
    bodies = parent.spawn(world, (0.0, 0.0), library=lib)
    # 1 composite marker + 2 mote children = 3 bodies.
    assert len(bodies) == 3


def test_spawn_returns_body_instances() -> None:
    world = World(gravity=(0.0, -9.81))
    p = Prefab(
        name="c", category="props",
        body_spec={"kind": "box", "width": 2.0, "height": 2.0, "mass": 1.0},
    )
    bodies = p.spawn(world, (0.0, 0.0))
    for b in bodies:
        assert isinstance(b, Body)


def test_spawn_can_step_world_without_errors(
    library_with_baked: PrefabLibrary,
) -> None:
    for name in library_with_baked.list_names():
        world = World(gravity=(0.0, -9.81))
        library_with_baked.get(name).spawn(world, (0.0, 10.0))
        # Ten sub-steps of a small dt — the world must not blow up.
        for _ in range(10):
            world.step(1.0 / 240.0)


# ---------------------------------------------------------------------------
# 8. Public surface
# ---------------------------------------------------------------------------


def test_public_surface_exports() -> None:
    import slappyengine.prefabs as pkg
    assert hasattr(pkg, "Prefab")
    assert hasattr(pkg, "PrefabLibrary")
    assert hasattr(pkg, "CATEGORIES")


def test_library_iteration_yields_prefabs() -> None:
    lib = PrefabLibrary()
    lib.register(Prefab(name="one", category="props", body_spec={"kind": "point"}))
    lib.register(Prefab(name="two", category="props", body_spec={"kind": "point"}))
    seen = list(lib)
    assert len(seen) == 2
    assert all(isinstance(p, Prefab) for p in seen)


def test_library_contains_operator() -> None:
    lib = PrefabLibrary()
    lib.register(Prefab(name="present", category="props", body_spec={"kind": "point"}))
    assert "present" in lib
    assert "missing" not in lib
    assert 123 not in lib  # non-str never contained
