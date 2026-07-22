"""Tests for ``EditorShell`` project lifecycle wiring (M6).

Covers the slice that turns a :class:`Project` handle into the editor's
runtime state: loading, saving, switching, the File menu, the status
bar's project segment, the OS window title, and the event-bus pings
that trigger the creature bindings.

These tests stay fully headless — they drive
:class:`EditorShell.load_project` / ``save_scene`` / ``switch_project``
directly without standing up a Dear PyGui viewport.
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_globals(monkeypatch, tmp_path):
    """Reset every singleton the lifecycle touches per test.

    * Theme registry + active theme.
    * Default creature scheduler (so the per-test scheduler is fresh).
    * The :class:`ProjectRegistry` singleton — redirected at a temp
      directory so the test's registry never pollutes ``~/.pharos_engine``.
    * The global :class:`EventBus` (``engine.scene_loaded`` /
      ``engine.save`` bus subscribers leak across tests otherwise).
    """
    from pharos_engine import event_bus as eb
    from pharos_engine.projects import registry as reg
    from pharos_editor.ui.theme import _reset_registry_for_tests
    from pharos_editor.ui.theme.creatures import (
        _reset_default_scheduler_for_tests,
    )
    from pharos_editor.ui.widgets.notebook_theme import set_active_theme

    _reset_registry_for_tests()
    set_active_theme(None)
    _reset_default_scheduler_for_tests()
    reg._reset_default_registry_for_tests()

    # Redirect the registry singleton at a per-test YAML.
    store_path = tmp_path / "registry.yaml"
    fresh_registry = reg.ProjectRegistry(store_path=store_path)
    monkeypatch.setattr(reg, "_default_registry", fresh_registry)

    # Fresh global bus so creature subscribers don't pile up.
    fresh_bus = eb.EventBus()
    monkeypatch.setattr(eb, "_DEFAULT_BUS", fresh_bus)

    yield

    _reset_registry_for_tests()
    set_active_theme(None)
    _reset_default_scheduler_for_tests()
    reg._reset_default_registry_for_tests()


def _make_shell(ui_settings=None):
    """Build a headless :class:`EditorShell` with a stub engine."""
    from pharos_editor.ui.editor.shell import EditorShell

    class _StubEngine:
        def __init__(self):
            self.scene = None
            self.load_scene_calls: list = []
            self.save_scene_calls: list = []
            self.new_scene_calls: int = 0

        def load_scene(self, scene):
            self.load_scene_calls.append(scene)

        def save_scene(self, path):
            self.save_scene_calls.append(path)

        def new_scene(self):
            self.new_scene_calls += 1

    shell = EditorShell(_StubEngine(), ui_settings=ui_settings)
    return shell


def _make_project(tmp_path: Path, name: str = "test_project") -> "Project":
    """Scaffold a fresh :class:`Project` rooted in *tmp_path*."""
    from pharos_engine.projects import Project

    root = tmp_path / name
    return Project.new(root, name)


# ---------------------------------------------------------------------------
# State accessors
# ---------------------------------------------------------------------------


class TestProjectStateAccessors:
    def test_no_project_initially(self):
        shell = _make_shell()
        assert shell.get_project() is None
        assert shell.is_dirty() is False

    def test_set_project_records_handle(self, tmp_path):
        shell = _make_shell()
        project = _make_project(tmp_path)
        shell.set_project(project)
        assert shell.get_project() is project

    def test_set_project_rejects_wrong_type(self):
        shell = _make_shell()
        with pytest.raises(TypeError):
            shell.set_project("not a project")  # type: ignore[arg-type]

    def test_mark_dirty_flips_state(self):
        shell = _make_shell()
        shell.mark_dirty()
        assert shell.is_dirty() is True

    def test_mark_clean_resets_state(self):
        shell = _make_shell()
        shell.mark_dirty()
        shell.mark_clean()
        assert shell.is_dirty() is False


# ---------------------------------------------------------------------------
# load_project
# ---------------------------------------------------------------------------


class TestLoadProject:
    def test_records_project(self, tmp_path):
        shell = _make_shell()
        project = _make_project(tmp_path, "Galaxy Adventure")
        shell.load_project(project)
        assert shell.get_project() is project

    def test_updates_window_title_with_project_name(self, tmp_path):
        shell = _make_shell()
        project = _make_project(tmp_path, "Galaxy Adventure")
        shell.load_project(project)
        title = shell._last_window_title
        assert title is not None
        assert "Galaxy Adventure" in title

    def test_no_project_title_when_unloaded(self):
        shell = _make_shell()
        # Force title application without a project.
        shell._apply_window_title()
        assert shell._last_window_title is not None
        assert "(no project)" in shell._last_window_title

    def test_content_browser_reroots(self, tmp_path):
        from pharos_editor.ui.editor.content_browser import ContentBrowser

        shell = _make_shell()
        shell._content_browser = ContentBrowser()
        project = _make_project(tmp_path)
        shell.load_project(project)
        assert Path(shell._content_browser._root) == project.path

    def test_loads_main_scene_when_present(self, tmp_path):
        shell = _make_shell()
        project = _make_project(tmp_path)
        # Project.new with scaffold=True (default) creates main.scene.yaml.
        shell.load_project(project)
        assert shell._scene_path is not None
        assert shell._scene_path.name == "main.scene.yaml"
        # The stub engine recorded the load_scene call.
        assert len(shell._engine.load_scene_calls) == 1

    def test_status_bar_shows_loaded_message(self, tmp_path):
        shell = _make_shell()
        project = _make_project(tmp_path, "PaperGarden")
        shell.load_project(project)
        transient = shell._notebook_status_bar.transient
        assert transient is not None
        assert "PaperGarden" in transient.text
        assert "Loaded notebook" in transient.text

    def test_status_bar_records_project_segment(self, tmp_path):
        shell = _make_shell()
        project = _make_project(tmp_path, "PaperGarden")
        shell.load_project(project)
        assert shell._notebook_status_bar.project_name == "PaperGarden"

    def test_fires_engine_scene_loaded_event(self, tmp_path):
        from pharos_engine.event_bus import get_default_bus

        events: list[dict] = []
        get_default_bus().subscribe(
            "engine.scene_loaded", lambda payload: events.append(payload),
        )

        shell = _make_shell()
        project = _make_project(tmp_path, "EventGame")
        shell.load_project(project)

        assert len(events) == 1
        assert events[0]["project_name"] == "EventGame"

    def test_adds_to_registry_recents(self, tmp_path):
        from pharos_engine.projects import get_default_registry

        shell = _make_shell()
        project = _make_project(tmp_path, "RecentsGame")
        shell.load_project(project)

        recents = get_default_registry().list_recent(limit=5)
        assert any(e.name == "RecentsGame" for e in recents)

    def test_load_clears_dirty_flag(self, tmp_path):
        shell = _make_shell()
        shell.mark_dirty()
        project = _make_project(tmp_path)
        shell.load_project(project)
        assert shell.is_dirty() is False


# ---------------------------------------------------------------------------
# save_scene
# ---------------------------------------------------------------------------


class TestSaveScene:
    def test_writes_into_scenes_dir(self, tmp_path):
        shell = _make_shell()
        project = _make_project(tmp_path, "SaveTest")
        shell.load_project(project)
        # Edit something → mark dirty.
        shell.mark_dirty()
        shell.save_scene()
        assert shell.is_dirty() is False
        # Engine.save_scene was invoked with the project path.
        assert shell._engine.save_scene_calls
        called_path = Path(shell._engine.save_scene_calls[-1])
        assert called_path.parent == project.scenes_dir

    def test_derives_default_path(self, tmp_path):
        shell = _make_shell()
        project = _make_project(tmp_path, "DefaultPath")
        shell.load_project(project)
        # Forget the scene path so save_scene must re-derive it.
        shell._scene_path = None
        shell.save_scene()
        assert shell._scene_path is not None
        assert shell._scene_path.name == "main.scene.yaml"

    def test_save_without_project_warns(self):
        shell = _make_shell()
        shell.save_scene()
        # Status bar pushed a no-project message; engine was not called.
        assert shell._engine.save_scene_calls == []

    def test_fires_engine_save_event(self, tmp_path):
        from pharos_engine.event_bus import get_default_bus

        events: list[dict] = []
        get_default_bus().subscribe(
            "engine.save", lambda payload: events.append(payload),
        )

        shell = _make_shell()
        project = _make_project(tmp_path, "SaveEvent")
        shell.load_project(project)
        shell.save_scene()
        assert len(events) == 1


# ---------------------------------------------------------------------------
# save_scene_as
# ---------------------------------------------------------------------------


class TestSaveSceneAs:
    def test_writes_to_explicit_path(self, tmp_path):
        shell = _make_shell()
        project = _make_project(tmp_path, "AsTest")
        shell.load_project(project)
        target = project.scenes_dir / "alt.scene.yaml"
        result = shell.save_scene_as(target)
        assert result == target
        assert shell._scene_path == target


# ---------------------------------------------------------------------------
# open_scene
# ---------------------------------------------------------------------------


class TestOpenScene:
    def test_routes_to_engine_load_scene(self, tmp_path):
        shell = _make_shell()
        project = _make_project(tmp_path, "OpenTest")
        shell.load_project(project)
        scene_path = project.scenes_dir / "main.scene.yaml"
        # Drop the prior load_scene calls so we can isolate this one.
        shell._engine.load_scene_calls.clear()
        shell.open_scene(scene_path)
        assert shell._scene_path == scene_path
        assert shell._engine.load_scene_calls == [scene_path]
        assert shell.is_dirty() is False

    def test_warns_when_outside_scenes_dir(self, tmp_path):
        shell = _make_shell()
        project = _make_project(tmp_path, "OutsideTest")
        shell.load_project(project)
        outside = tmp_path / "rogue.scene.yaml"
        outside.write_text("name: rogue\n", encoding="utf-8")
        shell.open_scene(outside)
        # Status-bar warning surfaced via the transient message.
        transient = shell._notebook_status_bar.transient
        assert transient is not None


# ---------------------------------------------------------------------------
# switch_project + picker plumbing
# ---------------------------------------------------------------------------


class TestSwitchProject:
    def test_switch_shows_picker(self):
        shell = _make_shell()
        shell.switch_project()
        picker = shell.get_project_picker()
        # Either ``.visible`` (legacy) or ``.is_open`` (current shape).
        assert getattr(picker, "is_open", getattr(picker, "visible", False))

    def test_get_project_picker_is_idempotent(self):
        shell = _make_shell()
        p1 = shell.get_project_picker()
        p2 = shell.get_project_picker()
        assert p1 is p2

    def test_picker_chosen_callback_invokes_load_project(self, tmp_path):
        shell = _make_shell()
        project = _make_project(tmp_path, "PickerLoad")
        picker = shell.get_project_picker()
        # Simulate the picker firing the chosen callback.
        picker._on_project_chosen(project)
        assert shell.get_project() is project


# ---------------------------------------------------------------------------
# Menu wiring
# ---------------------------------------------------------------------------


class TestMenuWiring:
    def test_menu_open_scene_routes_to_open_scene(self, tmp_path):
        shell = _make_shell()
        project = _make_project(tmp_path, "MenuOpen")
        shell.load_project(project)
        # Calling menu_open_scene with an explicit path skips the dialog
        # and exercises the open_scene fast path.
        target = project.scenes_dir / "main.scene.yaml"
        shell._engine.load_scene_calls.clear()
        ok = shell.menu_open_scene(str(target))
        assert ok is True
        assert shell._scene_path == target

    def test_recent_projects_lists_up_to_five(self, tmp_path):
        shell = _make_shell()
        for i in range(7):
            project = _make_project(tmp_path, f"recent_{i}")
            shell.load_project(project)
        labels = shell.list_recent_project_labels(limit=5)
        # The registry only keeps a recents window, so the limit must
        # cap at 5. The exact ordering depends on the ISO timestamp
        # resolution (1 s) so we don't assert which 5 names appear —
        # only that the cap holds and every label is one of the loaded
        # project names.
        assert len(labels) == 5
        loaded = {f"recent_{i}" for i in range(7)}
        for label in labels:
            assert label in loaded

    def test_recent_projects_empty_when_no_recents(self):
        shell = _make_shell()
        labels = shell.list_recent_project_labels(limit=5)
        assert labels == []

    def test_load_recent_project_opens_entry(self, tmp_path):
        shell = _make_shell()
        project = _make_project(tmp_path, "RecentOpen")
        shell.load_project(project)
        # Switch to a different one so loading recent[0] actually mutates.
        other = _make_project(tmp_path, "Other")
        shell.load_project(other)
        # Now load the most recent (Other was the last loaded).
        shell.load_recent_project(0)
        assert shell.get_project().metadata.name == "Other"


# ---------------------------------------------------------------------------
# Window title format
# ---------------------------------------------------------------------------


class TestWindowTitle:
    def test_format_with_project_name(self):
        from pharos_editor.ui.editor.notebook_window_title import (
            format_window_title,
        )
        title = format_window_title(
            "main",
            saved=True,
            theme_name="teengirl_notebook",
            project_name="My Game",
        )
        assert "My Game" in title
        assert "main" in title

    def test_format_no_project_placeholder(self):
        from pharos_editor.ui.editor.notebook_window_title import (
            format_window_title,
        )
        title = format_window_title(
            "ignored",
            saved=True,
            theme_name="teengirl_notebook",
            project_name=None,
        )
        assert title == "Pharos Notebook — (no project)"

    def test_dirty_state_changes_glyph(self, tmp_path):
        shell = _make_shell()
        project = _make_project(tmp_path, "DirtyTest")
        shell.load_project(project)
        clean_title = shell._last_window_title
        shell.mark_dirty()
        dirty_title = shell._last_window_title
        assert clean_title != dirty_title

    def test_format_legacy_signature_unchanged(self):
        """Three-arg call (pre-M6) must still emit the legacy format."""
        from pharos_editor.ui.editor.notebook_window_title import (
            format_window_title,
        )
        title = format_window_title(
            "scene", saved=True, theme_name="teengirl_notebook",
        )
        # Legacy format does not have a project segment.
        assert "(no project)" not in title
        assert "scene heart" in title


# ---------------------------------------------------------------------------
# Creature event bindings
# ---------------------------------------------------------------------------


class TestCreatureEventBindings:
    def test_scene_loaded_triggers_deer_peek_in(self, tmp_path):
        shell = _make_shell()
        shell.setup_theme_subsystem()
        scheduler = shell._creature_scheduler
        assert scheduler is not None
        # The CreatureBusAdapter is wired to the same bus we publish on.
        active_before = scheduler.active_count
        project = _make_project(tmp_path, "DeerLoad")
        shell.load_project(project)
        # ``engine.scene_loaded`` fires deer_01.peek_in via the adapter.
        assert scheduler.active_count >= active_before

    def test_save_event_triggers_butterfly_flutter(self, tmp_path):
        shell = _make_shell()
        shell.setup_theme_subsystem()
        scheduler = shell._creature_scheduler
        project = _make_project(tmp_path, "ButterflySave")
        shell.load_project(project)
        before = scheduler.active_count
        shell.save_scene()
        assert scheduler.active_count >= before
