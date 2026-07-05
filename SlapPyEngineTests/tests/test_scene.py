"""Tests for the ``slappyengine.scenes`` YAML scene serialisation subpackage
(sprint FF3).

Covers:

* :class:`Scene` add / remove / find / list_by_kind.
* YAML round-trip via :meth:`Scene.to_yaml` / :meth:`Scene.from_yaml`.
* :meth:`Scene.apply_to_world` + :meth:`Scene.snapshot_from_world`
  round-trip.
* :class:`SceneFile` read / write / validate.
* :class:`SceneFile` atomic-write crash-survival.
* :class:`SceneRegistry` discovery + load / save / list_all.
* Validation errors (missing fields, unknown kinds, unbalanced YAML).
* Corrupt YAML raises :class:`SceneValidationError` with a line number.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from slappyengine.dynamics import Body, World
from slappyengine.scenes import (
    SCENE_SUFFIX,
    SCHEMA_VERSION,
    Scene,
    SceneFile,
    SceneRegistry,
    SceneValidationError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_scene() -> Scene:
    scene = Scene(name="simple")
    scene.add_entity({
        "kind": "box",
        "position": [1.0, 2.0],
        "params": {"width": 1.0, "height": 1.0, "mass": 5.0},
    })
    scene.add_entity({
        "kind": "point",
        "position": [0.0, 0.0],
        "params": {"mass": 1.0},
    })
    return scene


# ---------------------------------------------------------------------------
# Scene dataclass basics
# ---------------------------------------------------------------------------


def test_scene_default_construction() -> None:
    scene = Scene()
    assert scene.name == "Scene"
    assert scene.entities == []
    assert scene.layers == ["default"]
    assert scene.metadata == {}


def test_scene_name_must_be_non_empty() -> None:
    with pytest.raises(ValueError):
        Scene(name="")


def test_scene_add_entity_mints_unique_id() -> None:
    scene = Scene()
    e0 = scene.add_entity({
        "kind": "point", "position": [0.0, 0.0], "params": {"mass": 1.0},
    })
    e1 = scene.add_entity({
        "kind": "point", "position": [1.0, 0.0], "params": {"mass": 1.0},
    })
    assert e0 != e1
    assert e0.startswith("entity_")
    assert e1.startswith("entity_")


def test_scene_add_entity_respects_supplied_id() -> None:
    scene = Scene()
    eid = scene.add_entity({
        "id": "player_start",
        "kind": "point",
        "position": [0.0, 0.0],
        "params": {"mass": 1.0},
    })
    assert eid == "player_start"


def test_scene_add_entity_rejects_duplicate_id() -> None:
    scene = Scene()
    scene.add_entity({
        "id": "player", "kind": "point", "position": [0, 0], "params": {},
    })
    with pytest.raises(SceneValidationError):
        scene.add_entity({
            "id": "player", "kind": "point", "position": [1, 1], "params": {},
        })


def test_scene_add_entity_rejects_unknown_kind_without_prefab_ref() -> None:
    scene = Scene()
    with pytest.raises(SceneValidationError):
        scene.add_entity({
            "kind": "spaceship",
            "position": [0.0, 0.0],
            "params": {},
        })


def test_scene_add_entity_accepts_prefab_ref_with_custom_kind() -> None:
    scene = Scene()
    eid = scene.add_entity({
        "kind": "spaceship",  # arbitrary kind is fine with prefab_ref
        "position": [0.0, 0.0],
        "params": {},
        "prefab_ref": "spaceship_prefab",
    })
    assert scene.get(eid) is not None


def test_scene_remove_entity_returns_true_when_found() -> None:
    scene = Scene()
    eid = scene.add_entity({
        "kind": "point", "position": [0, 0], "params": {},
    })
    assert scene.remove_entity(eid) is True
    assert scene.get(eid) is None


def test_scene_remove_entity_returns_false_when_missing() -> None:
    scene = Scene()
    assert scene.remove_entity("does_not_exist") is False


def test_scene_find_by_name_matches_metadata_name() -> None:
    scene = Scene()
    scene.add_entity({
        "id": "e0",
        "kind": "point",
        "position": [0, 0],
        "params": {},
        "metadata": {"name": "player_spawn"},
    })
    hits = scene.find_by_name("player_spawn")
    assert len(hits) == 1
    assert hits[0]["id"] == "e0"


def test_scene_find_by_name_falls_back_to_id() -> None:
    scene = Scene()
    scene.add_entity({
        "id": "boss_gate",
        "kind": "point",
        "position": [0, 0],
        "params": {},
    })
    hits = scene.find_by_name("boss_gate")
    assert len(hits) == 1


def test_scene_list_by_kind_filters(simple_scene: Scene) -> None:
    boxes = simple_scene.list_by_kind("box")
    points = simple_scene.list_by_kind("point")
    assert len(boxes) == 1
    assert len(points) == 1
    assert boxes[0]["kind"] == "box"


# ---------------------------------------------------------------------------
# YAML round-trip
# ---------------------------------------------------------------------------


def test_scene_yaml_round_trip_preserves_fields(simple_scene: Scene) -> None:
    simple_scene.metadata["author"] = "ff3"
    simple_scene.layers = ["background", "gameplay", "hud"]
    text = simple_scene.to_yaml()
    restored = Scene.from_yaml(text)
    assert restored.name == simple_scene.name
    assert restored.metadata == simple_scene.metadata
    assert restored.layers == simple_scene.layers
    assert len(restored.entities) == len(simple_scene.entities)


def test_scene_yaml_starts_with_schema_version(simple_scene: Scene) -> None:
    text = simple_scene.to_yaml()
    assert text.startswith("schema_version:")


def test_scene_from_yaml_rejects_wrong_schema() -> None:
    text = "schema_version: 999\nname: bad\nentities: []\n"
    with pytest.raises(SceneValidationError):
        Scene.from_yaml(text)


def test_scene_from_yaml_rejects_non_str_input() -> None:
    with pytest.raises(SceneValidationError):
        Scene.from_yaml(12345)  # type: ignore[arg-type]


def test_scene_from_yaml_rejects_non_dict_payload() -> None:
    with pytest.raises(SceneValidationError):
        Scene.from_yaml("- just\n- a\n- list\n")


def test_scene_from_yaml_rejects_empty_document() -> None:
    with pytest.raises(SceneValidationError):
        Scene.from_yaml("")


def test_scene_from_yaml_reports_line_for_bad_yaml() -> None:
    # Mismatched braces on line 3 — PyYAML should report a mark here.
    bad = "schema_version: 1\nname: broken\nentities: [ {oops\n"
    with pytest.raises(SceneValidationError) as excinfo:
        Scene.from_yaml(bad)
    assert excinfo.value.line is not None
    assert excinfo.value.line >= 1


# ---------------------------------------------------------------------------
# apply_to_world / snapshot_from_world
# ---------------------------------------------------------------------------


def test_apply_to_world_creates_bodies(simple_scene: Scene) -> None:
    world = World()
    out = simple_scene.apply_to_world(world)
    assert len(world.bodies) == 2
    assert set(out.keys()) == {"entity_0", "entity_1"}


def test_apply_to_world_point_position_matches(simple_scene: Scene) -> None:
    world = World()
    simple_scene.apply_to_world(world)
    point_body = [b for b in world.bodies if b.kind == "point"][0]
    # The point-body position is exactly the scene entity position.
    px, py = world.positions[point_body.node_offset]
    assert (float(px), float(py)) == (0.0, 0.0)


def test_apply_to_world_unknown_kind_returns_empty_list() -> None:
    scene = Scene()
    # Use prefab_ref bypass so the kind isn't rejected up front.
    scene.add_entity({
        "kind": "exotic",
        "position": [0.0, 0.0],
        "params": {},
        "prefab_ref": "nonexistent",
    })
    world = World()
    out = scene.apply_to_world(world)
    # No prefab library supplied → prefab lookup misses → empty handles.
    assert list(out.values())[0] == []
    assert len(world.bodies) == 0


def test_snapshot_from_world_round_trip() -> None:
    world = World()
    # Seed the world with two labelled point-bodies.
    for i, (x, y) in enumerate([(1.0, 2.0), (-3.5, 4.25)]):
        idx = world.add_node((x, y), 1.0)
        world.register_body(Body(
            kind="point",
            parameters={"mass": 1.0},
            node_offset=idx,
            node_count=1,
            label=f"seed_{i}",
        ))
    scene = Scene(name="from_world")
    scene.snapshot_from_world(world)
    assert len(scene.entities) == 2
    ids = {e["id"] for e in scene.entities}
    assert ids == {"seed_0", "seed_1"}
    kinds = {e["kind"] for e in scene.entities}
    assert kinds == {"point"}


def test_apply_then_snapshot_preserves_kind_and_id() -> None:
    scene = Scene(name="round_trip")
    scene.add_entity({
        "id": "ball",
        "kind": "point",
        "position": [3.5, -1.25],
        "params": {"mass": 2.0},
    })
    world = World()
    scene.apply_to_world(world)
    snap = Scene(name="round_trip")
    snap.snapshot_from_world(world)
    assert len(snap.entities) == 1
    assert snap.entities[0]["id"] == "ball"
    assert snap.entities[0]["kind"] == "point"
    assert snap.entities[0]["position"] == [3.5, -1.25]


def test_snapshot_from_world_deduplicates_labels() -> None:
    world = World()
    for _ in range(3):
        idx = world.add_node((0.0, 0.0), 1.0)
        world.register_body(Body(
            kind="point", parameters={"mass": 1.0},
            node_offset=idx, node_count=1, label="duplicate",
        ))
    scene = Scene()
    scene.snapshot_from_world(world)
    ids = [e["id"] for e in scene.entities]
    assert len(ids) == 3
    assert len(set(ids)) == 3  # every id is unique


# ---------------------------------------------------------------------------
# SceneFile read / write / validate
# ---------------------------------------------------------------------------


def test_scene_file_write_then_read(simple_scene: Scene, tmp_path: Path) -> None:
    p = tmp_path / "level.scene.yaml"
    SceneFile.write(simple_scene, p)
    assert p.exists()
    restored = SceneFile.read(p)
    assert restored.name == simple_scene.name
    assert len(restored.entities) == len(simple_scene.entities)


def test_scene_file_write_rejects_bad_suffix(
    simple_scene: Scene, tmp_path: Path,
) -> None:
    p = tmp_path / "level.yaml"  # missing .scene prefix
    with pytest.raises(SceneValidationError):
        SceneFile.write(simple_scene, p)


def test_scene_file_read_rejects_bad_suffix(tmp_path: Path) -> None:
    p = tmp_path / "not_a_scene.yaml"
    p.write_text("schema_version: 1\nname: x\nentities: []\n")
    with pytest.raises(SceneValidationError):
        SceneFile.read(p)


def test_scene_file_read_missing_file_raises(tmp_path: Path) -> None:
    p = tmp_path / "missing.scene.yaml"
    with pytest.raises(FileNotFoundError):
        SceneFile.read(p)


def test_scene_file_validate_reports_missing_id() -> None:
    scene = Scene()
    # Bypass validation by direct list mutation.
    scene.entities.append(
        {"kind": "point", "position": [0, 0], "params": {}}
    )
    problems = SceneFile.validate(scene)
    assert any("missing required key" in p for p in problems)


def test_scene_file_validate_reports_duplicate_ids() -> None:
    scene = Scene()
    scene.entities.append(
        {"id": "dup", "kind": "point", "position": [0, 0], "params": {}}
    )
    scene.entities.append(
        {"id": "dup", "kind": "point", "position": [1, 1], "params": {}}
    )
    problems = SceneFile.validate(scene)
    assert any("duplicate id" in p for p in problems)


def test_scene_file_validate_clean_scene_empty(simple_scene: Scene) -> None:
    problems = SceneFile.validate(simple_scene)
    assert problems == []


def test_scene_file_atomic_write_preserves_prior_on_crash(
    tmp_path: Path, monkeypatch,
) -> None:
    p = tmp_path / "level.scene.yaml"
    good = Scene(name="good")
    SceneFile.write(good, p)
    assert p.read_text().count("good") >= 1

    # Force os.replace to blow up mid-write.
    def boom(*args, **kwargs):
        raise OSError("simulated crash before atomic rename")

    monkeypatch.setattr(os, "replace", boom)

    bad = Scene(name="corrupted")
    with pytest.raises(OSError):
        SceneFile.write(bad, p)
    # Original file must be intact — we never got past the rename.
    assert p.exists()
    text = p.read_text()
    assert "name: good" in text
    assert "corrupted" not in text
    # And the temp file must have been cleaned up.
    tmps = list(tmp_path.glob("*.tmp"))
    assert tmps == []


# ---------------------------------------------------------------------------
# SceneRegistry
# ---------------------------------------------------------------------------


def test_registry_discover_finds_scene_files(tmp_path: Path) -> None:
    scenes_dir = tmp_path / "scenes"
    scenes_dir.mkdir()
    (scenes_dir / "level_a.scene.yaml").write_text(
        Scene(name="a").to_yaml()
    )
    (scenes_dir / "sub").mkdir()
    (scenes_dir / "sub" / "level_b.scene.yaml").write_text(
        Scene(name="b").to_yaml()
    )
    # Non-scene YAML should not be discovered.
    (scenes_dir / "notes.yaml").write_text("hello: world\n")
    hits = SceneRegistry.discover(scenes_dir)
    assert len(hits) == 2
    assert all(str(h).endswith(SCENE_SUFFIX) for h in hits)


def test_registry_discover_missing_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        SceneRegistry.discover(tmp_path / "does_not_exist")


def test_registry_load_and_list_all(tmp_path: Path) -> None:
    scenes_dir = tmp_path / "scenes"
    scenes_dir.mkdir()
    for n in ("alpha", "bravo", "charlie"):
        (scenes_dir / f"{n}.scene.yaml").write_text(
            Scene(name=n).to_yaml()
        )
    reg = SceneRegistry()
    names = reg.load_dir(scenes_dir)
    assert set(names) == {"alpha", "bravo", "charlie"}
    assert reg.list_all() == ["alpha", "bravo", "charlie"]
    assert reg.get("alpha") is not None
    assert reg.source_of("alpha") is not None


def test_registry_save_registers_and_writes(tmp_path: Path) -> None:
    reg = SceneRegistry()
    scene = Scene(name="fresh")
    p = tmp_path / "fresh.scene.yaml"
    final = reg.save(scene, p)
    assert final.exists()
    assert "fresh" in reg
    assert reg.get("fresh") is scene


def test_registry_load_dir_skips_broken_files(tmp_path: Path) -> None:
    scenes_dir = tmp_path / "scenes"
    scenes_dir.mkdir()
    (scenes_dir / "good.scene.yaml").write_text(Scene(name="good").to_yaml())
    # Broken: mis-indented YAML.
    (scenes_dir / "broken.scene.yaml").write_text(
        "schema_version: 1\nname: broken\nentities: [ {oops\n"
    )
    reg = SceneRegistry()
    names = reg.load_dir(scenes_dir)
    assert names == ["good"]
    assert "broken" not in reg


def test_registry_clear_empties_state(tmp_path: Path) -> None:
    reg = SceneRegistry()
    reg.save(Scene(name="one"), tmp_path / "one.scene.yaml")
    assert len(reg) == 1
    reg.clear()
    assert len(reg) == 0
    assert reg.list_all() == []


def test_registry_get_returns_none_for_missing() -> None:
    reg = SceneRegistry()
    assert reg.get("nope") is None
    assert reg.get("") is None
    assert reg.get(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# SceneValidationError details
# ---------------------------------------------------------------------------


def test_validation_error_carries_line_when_available() -> None:
    err = SceneValidationError("bad thing", line=42)
    assert err.line == 42
    assert "[line 42]" in str(err)


def test_validation_error_line_is_optional() -> None:
    err = SceneValidationError("no line here")
    assert err.line is None
    assert "[line" not in str(err)


def test_scene_from_dict_missing_entity_key_raises() -> None:
    payload = {
        "schema_version": 1,
        "name": "bad",
        "entities": [{"kind": "point"}],  # missing id / position / params
    }
    with pytest.raises(SceneValidationError) as excinfo:
        Scene.from_dict(payload)
    assert "missing required keys" in str(excinfo.value)


def test_scene_from_dict_rejects_non_finite_position() -> None:
    payload = {
        "schema_version": 1,
        "name": "bad",
        "entities": [{
            "id": "e0", "kind": "point",
            "position": [float("inf"), 0.0], "params": {},
        }],
    }
    with pytest.raises(SceneValidationError):
        Scene.from_dict(payload)


def test_scene_schema_version_constant_matches_yaml_output() -> None:
    scene = Scene(name="v")
    payload = scene.to_dict()
    assert payload["schema_version"] == SCHEMA_VERSION
