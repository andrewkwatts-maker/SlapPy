"""Tripwire suite for :mod:`pharos_engine.project_scene_bridge` (GG2).

Covers the surface exposed to the notebook editor:

* :class:`ProjectSceneIndex` — dataclass sanity, name lookup.
* :class:`ProjectSceneBridge` — save / load round-trip, sorted
  listing, delete, default scene persistence, manifest resilience.
* :func:`create_project_with_scene` — end-to-end factory that registers
  a project *and* stamps its first scene in one call.

Every test uses ``tmp_path`` for both the project directory *and* an
isolated :class:`ProjectRegistry` ``store_path`` so the suite never
touches the user's ``~/.pharos_engine/projects.yaml``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pharos_engine.project_registry import (
    ProjectRegistry,
    RegisteredProject,
)
from pharos_engine.project_scene_bridge import (
    PROJECT_MANIFEST_NAME,
    SCENES_SUBDIR,
    ProjectSceneBridge,
    ProjectSceneIndex,
    create_project_with_scene,
)
from pharos_engine.scenes import SCENE_SUFFIX, Scene, SceneFile


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def project_dir(tmp_path) -> Path:
    """Return a freshly-created project root directory."""
    root = tmp_path / "MyProject"
    root.mkdir()
    return root


@pytest.fixture()
def registered(project_dir) -> RegisteredProject:
    """Return a :class:`RegisteredProject` pointing at ``project_dir``."""
    return RegisteredProject(name="MyProject", path=project_dir)


@pytest.fixture()
def bridge(registered) -> ProjectSceneBridge:
    """Return a bridge for the freshly-created project."""
    return ProjectSceneBridge(registered)


@pytest.fixture()
def isolated_registry(tmp_path) -> ProjectRegistry:
    """A :class:`ProjectRegistry` whose YAML store lives in ``tmp_path``."""
    return ProjectRegistry(path=tmp_path / "projects.yaml")


def _make_scene(name: str = "level_1", *, points: int = 1) -> Scene:
    """Construct a minimal valid :class:`Scene` for the tests."""
    scene = Scene(name=name)
    for i in range(points):
        scene.add_entity(
            {
                "id": f"pt_{i}",
                "kind": "point",
                "position": [float(i), 0.0],
                "params": {"mass": 1.0},
            }
        )
    return scene


# ─────────────────────────────────────────────────────────────────────────────
# ProjectSceneIndex
# ─────────────────────────────────────────────────────────────────────────────


def test_scene_index_defaults():
    idx = ProjectSceneIndex(project_name="P")
    assert idx.project_name == "P"
    assert idx.scenes == {}
    assert idx.default_scene is None
    assert idx.last_opened is None
    assert len(idx) == 0


def test_scene_index_names_sorted(tmp_path):
    idx = ProjectSceneIndex(
        project_name="P",
        scenes={"b": tmp_path / "b", "a": tmp_path / "a"},
    )
    assert idx.names() == ["a", "b"]
    assert "a" in idx
    assert "z" not in idx


# ─────────────────────────────────────────────────────────────────────────────
# ProjectSceneBridge — construction
# ─────────────────────────────────────────────────────────────────────────────


def test_bridge_rejects_non_registered_project():
    with pytest.raises(TypeError):
        ProjectSceneBridge("not-a-project")  # type: ignore[arg-type]


def test_bridge_project_property(bridge, registered):
    assert bridge.project is registered
    assert bridge.project_path == Path(registered.path)
    assert bridge.scenes_dir == Path(registered.path) / SCENES_SUBDIR
    assert bridge.manifest_path == Path(registered.path) / PROJECT_MANIFEST_NAME


def test_bridge_boots_without_scenes_dir(bridge):
    # No scenes/ folder yet — index_scenes must not raise.
    idx = bridge.index_scenes()
    assert isinstance(idx, ProjectSceneIndex)
    assert idx.scenes == {}
    assert idx.default_scene is None


# ─────────────────────────────────────────────────────────────────────────────
# index_scenes / list_scene_names
# ─────────────────────────────────────────────────────────────────────────────


def test_index_scenes_empty_project_when_scenes_dir_present(bridge):
    (bridge.project_path / SCENES_SUBDIR).mkdir()
    idx = bridge.index_scenes()
    assert idx.project_name == "MyProject"
    assert idx.scenes == {}


def test_list_scene_names_empty(bridge):
    assert bridge.list_scene_names() == []


def test_list_scene_names_sorted(bridge):
    for name in ("zeta", "alpha", "middle"):
        bridge.save_scene(_make_scene(name))
    assert bridge.list_scene_names() == ["alpha", "middle", "zeta"]


def test_index_scenes_records_absolute_paths(bridge):
    bridge.save_scene(_make_scene("only"))
    idx = bridge.index_scenes()
    path = idx.scenes["only"]
    assert path.is_absolute()
    assert path.name.endswith(SCENE_SUFFIX)


# ─────────────────────────────────────────────────────────────────────────────
# save_scene / load_scene round-trip
# ─────────────────────────────────────────────────────────────────────────────


def test_save_scene_round_trip(bridge):
    original = _make_scene("intro", points=3)
    path = bridge.save_scene(original)
    assert path.exists()
    assert path.name == f"intro{SCENE_SUFFIX}"
    loaded = bridge.load_scene("intro")
    assert loaded.name == "intro"
    assert len(loaded.entities) == 3
    assert loaded.entities[0]["kind"] == "point"


def test_save_scene_uses_name_argument_when_given(bridge):
    scene = _make_scene("original")
    path = bridge.save_scene(scene, name="renamed")
    assert path.name == f"renamed{SCENE_SUFFIX}"
    # The scene object itself is untouched — it keeps its original name.
    assert scene.name == "original"
    assert bridge.list_scene_names() == ["renamed"]


def test_save_scene_rejects_non_scene(bridge):
    with pytest.raises(TypeError):
        bridge.save_scene("not-a-scene")  # type: ignore[arg-type]


def test_save_scene_rejects_empty_name(bridge):
    with pytest.raises((TypeError, ValueError)):
        bridge.save_scene(_make_scene(), name="")


def test_load_scene_missing_raises(bridge):
    with pytest.raises(FileNotFoundError):
        bridge.load_scene("nope")


def test_load_scene_updates_last_opened(bridge):
    bridge.save_scene(_make_scene("a"))
    bridge.save_scene(_make_scene("b"))
    bridge.load_scene("a")
    assert bridge.last_opened_scene_name == "a"
    bridge.load_scene("b")
    assert bridge.last_opened_scene_name == "b"


# ─────────────────────────────────────────────────────────────────────────────
# delete_scene
# ─────────────────────────────────────────────────────────────────────────────


def test_delete_scene_returns_true_when_removed(bridge):
    bridge.save_scene(_make_scene("gone"))
    assert bridge.delete_scene("gone") is True
    assert "gone" not in bridge.list_scene_names()


def test_delete_scene_returns_false_when_missing(bridge):
    assert bridge.delete_scene("never-existed") is False


def test_delete_scene_clears_default_when_matching(bridge):
    bridge.save_scene(_make_scene("boss"))
    bridge.set_default_scene("boss")
    assert bridge.default_scene_name == "boss"
    bridge.delete_scene("boss")
    assert bridge.default_scene_name is None


def test_delete_scene_leaves_other_default_alone(bridge):
    bridge.save_scene(_make_scene("keep"))
    bridge.save_scene(_make_scene("drop"))
    bridge.set_default_scene("keep")
    bridge.delete_scene("drop")
    assert bridge.default_scene_name == "keep"


# ─────────────────────────────────────────────────────────────────────────────
# set_default_scene / get_default_scene
# ─────────────────────────────────────────────────────────────────────────────


def test_default_scene_round_trip_via_manifest(bridge, registered):
    bridge.save_scene(_make_scene("main"))
    bridge.set_default_scene("main")
    # Reload the bridge from scratch to prove the manifest persisted.
    fresh = ProjectSceneBridge(registered)
    assert fresh.default_scene_name == "main"
    got = fresh.get_default_scene()
    assert got is not None
    assert got.name == "main"


def test_get_default_scene_none_when_unset(bridge):
    assert bridge.get_default_scene() is None


def test_get_default_scene_none_when_default_missing(bridge):
    bridge.save_scene(_make_scene("temp"))
    bridge.set_default_scene("temp")
    bridge.delete_scene("temp")
    # After deletion the default was cleared automatically.
    assert bridge.get_default_scene() is None


def test_get_default_scene_survives_manual_manifest_dangle(bridge, registered):
    # Simulate someone hand-editing the YAML to point at a nonexistent scene.
    bridge.set_default_scene("ghost")
    fresh = ProjectSceneBridge(registered)
    assert fresh.default_scene_name == "ghost"
    assert fresh.get_default_scene() is None


def test_clear_default_scene(bridge):
    bridge.save_scene(_make_scene("x"))
    bridge.set_default_scene("x")
    bridge.clear_default_scene()
    assert bridge.default_scene_name is None


def test_set_default_scene_rejects_empty(bridge):
    with pytest.raises((TypeError, ValueError)):
        bridge.set_default_scene("")


# ─────────────────────────────────────────────────────────────────────────────
# Auto-rename collision handling
# ─────────────────────────────────────────────────────────────────────────────


def test_save_scene_auto_renames_on_collision(bridge):
    p1 = bridge.save_scene(_make_scene("dup"))
    p2 = bridge.save_scene(_make_scene("dup"))
    p3 = bridge.save_scene(_make_scene("dup"))
    assert p1.name == f"dup{SCENE_SUFFIX}"
    assert p2.name == f"dup_1{SCENE_SUFFIX}"
    assert p3.name == f"dup_2{SCENE_SUFFIX}"
    names = bridge.list_scene_names()
    assert set(names) == {"dup", "dup_1", "dup_2"}


def test_save_scene_collision_uses_explicit_name(bridge):
    bridge.save_scene(_make_scene("boss"))
    p2 = bridge.save_scene(_make_scene("other"), name="boss")
    assert p2.name == f"boss_1{SCENE_SUFFIX}"


# ─────────────────────────────────────────────────────────────────────────────
# Manifest resilience
# ─────────────────────────────────────────────────────────────────────────────


def test_missing_project_yaml_handled_gracefully(bridge):
    # No manifest at all — bridge boots with None defaults.
    assert not bridge.manifest_path.exists()
    assert bridge.default_scene_name is None
    assert bridge.last_opened_scene_name is None


def test_corrupt_project_yaml_treated_as_empty(bridge, registered):
    bridge.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    bridge.manifest_path.write_text("this is: not valid: yaml: [][", encoding="utf-8")
    fresh = ProjectSceneBridge(registered)
    assert fresh.default_scene_name is None
    assert fresh.last_opened_scene_name is None


def test_manifest_preserves_unknown_keys(bridge, registered):
    bridge.manifest_path.write_text(
        "author: someone\nnotes: hi\n", encoding="utf-8",
    )
    bridge_2 = ProjectSceneBridge(registered)
    bridge_2.save_scene(_make_scene("s"))
    bridge_2.set_default_scene("s")
    raw = bridge.manifest_path.read_text(encoding="utf-8")
    assert "author" in raw
    assert "notes" in raw
    assert "default_scene" in raw


def test_manifest_updates_last_opened_across_saves(bridge, registered):
    bridge.save_scene(_make_scene("a"))
    bridge.save_scene(_make_scene("b"))
    fresh = ProjectSceneBridge(registered)
    assert fresh.last_opened_scene_name == "b"


# ─────────────────────────────────────────────────────────────────────────────
# create_project_with_scene factory
# ─────────────────────────────────────────────────────────────────────────────


def test_create_project_with_scene_registers_and_saves(
    tmp_path, isolated_registry,
):
    root = tmp_path / "FactoryProj"
    root.mkdir()
    project = RegisteredProject(name="FactoryProj", path=root)
    scene = _make_scene("intro")
    bridge = create_project_with_scene(
        project, scene, registry=isolated_registry,
    )
    assert isinstance(bridge, ProjectSceneBridge)
    assert "FactoryProj" in isolated_registry
    assert bridge.list_scene_names() == ["intro"]
    assert bridge.default_scene_name == "intro"


def test_create_project_with_scene_respects_set_as_default_false(
    tmp_path, isolated_registry,
):
    root = tmp_path / "NoDefaultProj"
    root.mkdir()
    project = RegisteredProject(name="NoDefaultProj", path=root)
    scene = _make_scene("bare")
    bridge = create_project_with_scene(
        project, scene, registry=isolated_registry, set_as_default=False,
    )
    assert bridge.default_scene_name is None
    assert bridge.list_scene_names() == ["bare"]


def test_create_project_with_scene_type_checks(tmp_path, isolated_registry):
    root = tmp_path / "TypeCheck"
    root.mkdir()
    project = RegisteredProject(name="TypeCheck", path=root)
    with pytest.raises(TypeError):
        create_project_with_scene(
            "not-a-project", _make_scene(), registry=isolated_registry,  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError):
        create_project_with_scene(
            project, "not-a-scene", registry=isolated_registry,  # type: ignore[arg-type]
        )


# ─────────────────────────────────────────────────────────────────────────────
# Integration surface — bridge cooperates with FF3 SceneFile directly
# ─────────────────────────────────────────────────────────────────────────────


def test_scene_written_via_bridge_readable_by_scenefile(bridge):
    scene = _make_scene("io", points=2)
    path = bridge.save_scene(scene)
    # FF3 SceneFile should read the file the bridge just wrote.
    round_tripped = SceneFile.read(path)
    assert round_tripped.name == "io"
    assert len(round_tripped.entities) == 2


def test_bridge_handles_stem_with_forbidden_chars(bridge):
    # Names with slashes / spaces should be sanitised, not escape the dir.
    path = bridge.save_scene(_make_scene(), name="weird/name with spaces")
    assert path.parent == bridge.scenes_dir
    assert " " not in path.name
    assert "/" not in path.name
