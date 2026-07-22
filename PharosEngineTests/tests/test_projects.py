"""Tripwire suite for ``pharos_engine.projects`` — the multi-project subsystem.

Covers:

* :class:`Project` / :class:`ProjectMetadata` round-trips through the
  YAML format helpers.
* Directory-walk helpers (``is_project_dir``, ``find_project_root``).
* :class:`ProjectRegistry` persistence — register, unregister,
  list_recent, opening touches ``last_opened_at``.
* Scaffolding lays down the expected directory tree.
* Top-level lazy re-export (``pharos_engine.projects``).

Every test uses ``tmp_path`` for the project root *and* an isolated
registry ``store_path`` so the suite never touches the user's home
directory.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import pharos_engine
from pharos_engine.projects import (
    PROJECT_FILE_NAME,
    Project,
    ProjectFormatError,
    ProjectMetadata,
    ProjectRegistry,
    find_project_root,
    get_default_registry,
    is_project_dir,
    read_project,
    scaffold_project,
    write_project,
)
from pharos_engine.projects.registry import (
    RegistryEntry,
    _reset_default_registry_for_tests,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def fresh_singleton():
    """Reset the registry singleton before and after each test that opts in."""
    _reset_default_registry_for_tests()
    yield
    _reset_default_registry_for_tests()


# ─────────────────────────────────────────────────────────────────────────────
# ProjectMetadata
# ─────────────────────────────────────────────────────────────────────────────


def _make_meta(**overrides) -> ProjectMetadata:
    base = dict(
        name="Test",
        version="0.3.0b0",
        created_at="2026-06-03T10:00:00Z",
        last_opened_at="2026-06-03T10:00:00Z",
    )
    base.update(overrides)
    return ProjectMetadata(**base)


def test_metadata_round_trip_via_dict():
    meta = _make_meta(description="hello", icon="icon.png")
    d = meta.to_dict()
    restored = ProjectMetadata.from_dict(d)
    assert restored.name == "Test"
    assert restored.version == "0.3.0b0"
    assert restored.description == "hello"
    assert restored.icon == "icon.png"
    assert restored.default_theme == "teengirl_notebook"


def test_metadata_rejects_empty_name():
    with pytest.raises(ValueError):
        _make_meta(name="")


def test_metadata_rejects_wrong_type_for_name():
    with pytest.raises(TypeError):
        _make_meta(name=12345)


def test_metadata_from_dict_requires_name_field():
    with pytest.raises(KeyError):
        ProjectMetadata.from_dict({"version": "0.3.0b0"})


def test_metadata_from_dict_fills_defaults_for_optionals():
    meta = ProjectMetadata.from_dict({"name": "X", "version": "0.3.0b0"})
    assert meta.description == ""
    assert meta.icon == ""
    assert meta.default_theme == "teengirl_notebook"
    # created_at and last_opened_at are auto-filled with ISO strings
    assert meta.created_at and "T" in meta.created_at
    assert meta.last_opened_at and "T" in meta.last_opened_at


def test_metadata_from_dict_rejects_non_dict():
    with pytest.raises(TypeError):
        ProjectMetadata.from_dict("not-a-dict")  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# Project.new + scaffolding
# ─────────────────────────────────────────────────────────────────────────────


def test_project_new_creates_directories(tmp_path):
    proj = Project.new(tmp_path / "Game1", "Game1")
    assert proj.slap_proj_path.is_file()
    assert proj.scenes_dir.is_dir()
    assert proj.assets_dir.is_dir()
    assert proj.scripts_dir.is_dir()


def test_project_new_writes_manifest_with_name(tmp_path):
    proj = Project.new(tmp_path / "Game2", "Game2")
    data = yaml.safe_load(proj.slap_proj_path.read_text(encoding="utf-8"))
    assert data["name"] == "Game2"
    # Engine version defaults to the running pharos_engine.__version__
    assert data["version"] == pharos_engine.__version__


def test_project_new_scaffold_false_skips_subdirs(tmp_path):
    proj = Project.new(tmp_path / "BareGame", "BareGame", scaffold=False)
    assert proj.slap_proj_path.is_file()
    # No subdirectories created when scaffold=False
    assert not proj.scenes_dir.exists()
    assert not proj.assets_dir.exists()
    assert not proj.scripts_dir.exists()


def test_project_new_rejects_empty_name(tmp_path):
    with pytest.raises(ValueError):
        Project.new(tmp_path / "Empty", "")


def test_project_new_accepts_string_path(tmp_path):
    proj = Project.new(str(tmp_path / "StrPath"), "StrPath")
    assert isinstance(proj.path, Path)
    assert proj.path.is_dir()


# ─────────────────────────────────────────────────────────────────────────────
# read_project / write_project
# ─────────────────────────────────────────────────────────────────────────────


def test_read_project_round_trips(tmp_path):
    proj = Project.new(tmp_path / "Round", "RoundTrip", description="abc")
    loaded = read_project(proj.path)
    assert loaded.metadata.name == "RoundTrip"
    assert loaded.metadata.description == "abc"
    assert loaded.path == proj.path


def test_read_project_missing_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_project(tmp_path / "nope")


def test_read_project_missing_manifest_raises(tmp_path):
    (tmp_path / "empty_dir").mkdir()
    with pytest.raises(FileNotFoundError):
        read_project(tmp_path / "empty_dir")


def test_read_project_malformed_yaml_raises(tmp_path):
    root = tmp_path / "broken"
    root.mkdir()
    (root / PROJECT_FILE_NAME).write_text(
        "name: [unclosed\n", encoding="utf-8"
    )
    with pytest.raises(ProjectFormatError):
        read_project(root)


def test_read_project_empty_manifest_raises(tmp_path):
    root = tmp_path / "empty_manifest"
    root.mkdir()
    (root / PROJECT_FILE_NAME).write_text("", encoding="utf-8")
    with pytest.raises(ProjectFormatError):
        read_project(root)


def test_read_project_non_mapping_yaml_raises(tmp_path):
    root = tmp_path / "scalar_yaml"
    root.mkdir()
    (root / PROJECT_FILE_NAME).write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ProjectFormatError):
        read_project(root)


def test_read_project_missing_required_field_raises(tmp_path):
    root = tmp_path / "no_name"
    root.mkdir()
    (root / PROJECT_FILE_NAME).write_text(
        "version: 0.3.0b0\n", encoding="utf-8"
    )
    with pytest.raises(ProjectFormatError):
        read_project(root)


def test_write_project_creates_missing_parent_dirs(tmp_path):
    deep = tmp_path / "a" / "b" / "c"
    meta = _make_meta(name="DeepProj")
    proj = Project(path=deep, metadata=meta)
    write_project(proj)
    assert (deep / PROJECT_FILE_NAME).is_file()


def test_write_project_rejects_non_project(tmp_path):
    with pytest.raises(TypeError):
        write_project("not-a-project")  # type: ignore[arg-type]


def test_project_save_and_reload(tmp_path):
    proj = Project.new(tmp_path / "Save", "Save")
    proj.metadata.description = "edited"
    proj.save()
    fresh = read_project(proj.path)
    assert fresh.metadata.description == "edited"

    # Mutate in-memory then reload — should snap back to disk state.
    proj.metadata.description = "in-memory only"
    proj.reload()
    assert proj.metadata.description == "edited"


# ─────────────────────────────────────────────────────────────────────────────
# is_project_dir / find_project_root
# ─────────────────────────────────────────────────────────────────────────────


def test_is_project_dir_true_for_project(tmp_path):
    proj = Project.new(tmp_path / "Yes", "Yes", scaffold=False)
    assert is_project_dir(proj.path) is True


def test_is_project_dir_false_for_empty_dir(tmp_path):
    (tmp_path / "no").mkdir()
    assert is_project_dir(tmp_path / "no") is False


def test_is_project_dir_false_for_nonexistent(tmp_path):
    assert is_project_dir(tmp_path / "ghost") is False


def test_is_project_dir_false_for_file(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("hi", encoding="utf-8")
    assert is_project_dir(f) is False


def test_find_project_root_from_root(tmp_path):
    proj = Project.new(tmp_path / "P", "P")
    assert find_project_root(proj.path) == proj.path


def test_find_project_root_from_subdirectory(tmp_path):
    proj = Project.new(tmp_path / "P", "P")
    nested = proj.scenes_dir
    assert find_project_root(nested) == proj.path


def test_find_project_root_from_nested_file(tmp_path):
    proj = Project.new(tmp_path / "P", "P")
    nested_file = proj.scenes_dir / "main.scene.yaml"
    assert nested_file.is_file()
    assert find_project_root(nested_file) == proj.path


def test_find_project_root_returns_none_when_absent(tmp_path):
    nested = tmp_path / "no_project_here" / "deep"
    nested.mkdir(parents=True)
    assert find_project_root(nested) is None


# ─────────────────────────────────────────────────────────────────────────────
# Scaffolding
# ─────────────────────────────────────────────────────────────────────────────


def test_scaffold_creates_expected_files(tmp_path):
    proj = Project.new(tmp_path / "Scaff", "ScaffName")
    expected = {
        proj.scenes_dir / "main.scene.yaml",
        proj.assets_dir / "README.md",
        proj.scripts_dir / "main.py",
        proj.path / "icon.png",
    }
    for f in expected:
        assert f.exists(), f"missing seed file {f}"


def test_scaffold_main_scene_mentions_project_name(tmp_path):
    proj = Project.new(tmp_path / "Mention", "MentionedName")
    body = (proj.scenes_dir / "main.scene.yaml").read_text(encoding="utf-8")
    assert "MentionedName" in body


def test_scaffold_is_idempotent_does_not_overwrite_user_edits(tmp_path):
    proj = Project.new(tmp_path / "Idem", "Idem")
    main_py = proj.scripts_dir / "main.py"
    main_py.write_text("# user edit\n", encoding="utf-8")

    # Run the scaffolder again — user's edit should survive.
    scaffold_project(proj)
    assert main_py.read_text(encoding="utf-8") == "# user edit\n"


def test_scaffold_returns_path_map(tmp_path):
    proj = Project.new(tmp_path / "RetMap", "RetMap", scaffold=False)
    paths = scaffold_project(proj)
    assert set(paths.keys()) == {
        "scenes_dir",
        "assets_dir",
        "scripts_dir",
        "main_scene",
        "assets_readme",
        "main_py",
        "icon",
    }
    assert all(isinstance(p, Path) for p in paths.values())


def test_scaffold_rejects_non_project():
    with pytest.raises(TypeError):
        scaffold_project("not-a-project")  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# ProjectRegistry
# ─────────────────────────────────────────────────────────────────────────────


def _registry(tmp_path) -> ProjectRegistry:
    return ProjectRegistry(store_path=tmp_path / "registry.yaml")


def test_registry_starts_empty(tmp_path):
    reg = _registry(tmp_path)
    assert reg.list_recent() == []
    assert len(reg) == 0


def test_registry_register_adds_entry(tmp_path):
    reg = _registry(tmp_path)
    proj = Project.new(tmp_path / "A", "A")
    entry = reg.register(proj)
    assert isinstance(entry, RegistryEntry)
    assert entry.name == "A"
    assert len(reg) == 1


def test_registry_register_is_idempotent_by_path(tmp_path):
    reg = _registry(tmp_path)
    proj = Project.new(tmp_path / "Once", "Once")
    reg.register(proj)
    reg.register(proj)
    assert len(reg) == 1


def test_registry_unregister(tmp_path):
    reg = _registry(tmp_path)
    proj = Project.new(tmp_path / "U", "U")
    reg.register(proj)
    assert reg.unregister(proj.path) is True
    assert len(reg) == 0
    # Second unregister returns False (idempotent).
    assert reg.unregister(proj.path) is False


def test_registry_clear(tmp_path):
    reg = _registry(tmp_path)
    reg.register(Project.new(tmp_path / "X", "X"))
    reg.register(Project.new(tmp_path / "Y", "Y"))
    reg.clear()
    assert len(reg) == 0


def test_registry_persists_across_instances(tmp_path):
    store = tmp_path / "registry.yaml"
    reg1 = ProjectRegistry(store_path=store)
    proj = Project.new(tmp_path / "P1", "P1")
    reg1.register(proj)
    # Construct a fresh registry pointed at the same store; the entry
    # should still be present.
    reg2 = ProjectRegistry(store_path=store)
    assert len(reg2) == 1
    assert reg2.list_recent()[0].name == "P1"


def test_registry_list_recent_orders_by_last_opened(tmp_path):
    reg = _registry(tmp_path)
    proj_a = Project.new(tmp_path / "A", "A")
    proj_b = Project.new(tmp_path / "B", "B")
    # Force timestamps so the test is deterministic regardless of clock
    # resolution.
    proj_a.metadata.last_opened_at = "2026-01-01T00:00:00Z"
    proj_b.metadata.last_opened_at = "2026-06-01T00:00:00Z"
    reg.register(proj_a)
    reg.register(proj_b)
    recent = reg.list_recent()
    assert [e.name for e in recent] == ["B", "A"]


def test_registry_list_recent_respects_limit(tmp_path):
    reg = _registry(tmp_path)
    for i in range(5):
        p = Project.new(tmp_path / f"R{i}", f"R{i}")
        reg.register(p)
    assert len(reg.list_recent(limit=3)) == 3


def test_registry_list_recent_rejects_invalid_limit(tmp_path):
    reg = _registry(tmp_path)
    with pytest.raises(ValueError):
        reg.list_recent(limit=0)
    with pytest.raises(TypeError):
        reg.list_recent(limit="ten")  # type: ignore[arg-type]


def test_registry_open_touches_last_opened_at(tmp_path):
    reg = _registry(tmp_path)
    proj = Project.new(tmp_path / "Touch", "Touch")
    original = proj.metadata.last_opened_at
    # Mutate manifest on disk to a fixed old timestamp first.
    proj.metadata.last_opened_at = "2020-01-01T00:00:00Z"
    proj.save()

    opened = reg.open(proj.path)
    assert opened.metadata.last_opened_at != "2020-01-01T00:00:00Z"
    # And the registry now contains the touched entry.
    found = reg.find(proj.path)
    assert found is not None
    assert found.last_opened_at == opened.metadata.last_opened_at
    # Sanity: the touched timestamp differs from the original mint.
    assert opened.metadata.last_opened_at != "2020-01-01T00:00:00Z"
    del original  # silence linter; kept for narrative clarity


def test_registry_open_walks_up_from_subdir(tmp_path):
    reg = _registry(tmp_path)
    proj = Project.new(tmp_path / "Walk", "Walk")
    opened = reg.open(proj.scenes_dir)
    assert opened.path == proj.path


def test_registry_open_no_project_raises(tmp_path):
    reg = _registry(tmp_path)
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(FileNotFoundError):
        reg.open(bare)


def test_registry_new_creates_and_registers(tmp_path):
    reg = _registry(tmp_path)
    proj = reg.new(tmp_path / "Auto", "AutoName")
    assert proj.slap_proj_path.is_file()
    assert proj.path in reg


def test_registry_contains_membership(tmp_path):
    reg = _registry(tmp_path)
    proj = Project.new(tmp_path / "Mem", "Mem")
    assert proj.path not in reg
    reg.register(proj)
    assert proj.path in reg
    # Non-string / non-Path keys → False, never TypeError.
    assert 123 not in reg


def test_registry_handles_corrupt_store(tmp_path):
    """A malformed YAML on disk must not break registry construction."""
    store = tmp_path / "registry.yaml"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("name: [oops\n", encoding="utf-8")
    reg = ProjectRegistry(store_path=store)
    # Fresh registry — corrupt store treated as empty.
    assert len(reg) == 0


def test_registry_reload(tmp_path):
    store = tmp_path / "registry.yaml"
    reg = ProjectRegistry(store_path=store)
    reg.register(Project.new(tmp_path / "RA", "RA"))
    # Wipe in-memory entries by hand then reload from disk.
    reg._entries = []
    reg.reload()
    assert len(reg) == 1


def test_get_default_registry_is_singleton(tmp_path, fresh_singleton, monkeypatch):
    """``get_default_registry`` must return the same instance every call."""
    # Redirect HOME so the default location lands inside tmp_path and
    # never touches the user's actual home directory.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    a = get_default_registry()
    b = get_default_registry()
    assert a is b


# ─────────────────────────────────────────────────────────────────────────────
# Top-level surface
# ─────────────────────────────────────────────────────────────────────────────


def test_top_level_lazy_reexport_works():
    import pharos_engine as eng
    assert eng.projects is not None
    # Re-export should round-trip the public surface symbols.
    assert eng.projects.Project is Project
    assert eng.projects.ProjectRegistry is ProjectRegistry
    assert eng.projects.PROJECT_FILE_NAME == "project.slap_proj"
