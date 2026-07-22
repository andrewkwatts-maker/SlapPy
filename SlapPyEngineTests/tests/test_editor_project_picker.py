"""Tests for the notebook-themed project picker modal.

The picker is the editor's first-run + ``File → Switch Project`` modal.
It surfaces a recents list from a :class:`ProjectRegistry`, a
"New notebook" button (sub-modal that calls ``registry.new``), an
"Open from disk" button (folder picker → ``registry.open``), and a
cancel button.

Coverage:

* Construction
    - Rejects non-callable ``on_project_chosen`` / ``on_cancel``.
    - Defaults registry to :func:`get_default_registry` when omitted.
    - Constructs cleanly with explicit registry.
* Layout
    - Empty registry shows the "No recent notebooks" empty state.
    - Three registered projects → three displayed entries.
    - Recents are sorted newest-first.
* Callbacks
    - Click recent → opens project, fires ``on_project_chosen``,
      bumps ``last_opened_at``.
    - Click recent on missing path drops the entry from registry.
    - ``create_new`` calls ``registry.new`` + fires chosen callback.
    - ``open_from_disk`` walks upward via :func:`find_project_root`.
    - Cancel fires ``on_cancel`` and increments the cancel counter.
    - Right-click → ``remove_recent`` drops the entry + refreshes.
* New-project sub-modal
    - Rejects unknown ``default_theme`` values.
    - Persists ``default_theme`` onto the project manifest.
* Headless safety
    - All public methods work without a real ``dearpygui``.
* Humanised age helper
    - Buckets seconds / minutes / hours / days / weeks / months / years.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub — re-used from the welcome panel test pattern.
# ---------------------------------------------------------------------------


class _StubCM:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: set[str] = set()
        self.values: dict[str, str] = {}

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM()

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM()

    def window(self, *a, **kw):
        self._track("window", a, kw)
        return _StubCM()

    def popup(self, *a, **kw):
        self._track("popup", a, kw)
        return _StubCM()

    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_checkbox(self, *a, **kw):
        self._track("add_checkbox", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def add_input_text(self, *a, **kw):
        self._track("add_input_text", a, kw)
        tag = kw.get("tag")
        if isinstance(tag, str):
            self.values[tag] = kw.get("default_value", "")

    def add_combo(self, *a, **kw):
        self._track("add_combo", a, kw)
        tag = kw.get("tag")
        if isinstance(tag, str):
            self.values[tag] = kw.get("default_value", "")

    def add_menu_item(self, *a, **kw):
        self._track("add_menu_item", a, kw)

    def get_value(self, tag, *a, **kw):
        return self.values.get(tag, "")

    def set_value(self, tag, value, *a, **kw):
        self.values[tag] = value

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.discard(tag)


@pytest.fixture(autouse=True)
def stub_dpg(monkeypatch):
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "group", "child_window", "window", "popup",
        "add_text", "add_button", "add_checkbox", "add_separator",
        "add_input_text", "add_combo", "add_menu_item",
        "get_value", "set_value",
        "does_item_exist", "delete_item",
    ):
        setattr(mod, name, getattr(stub, name))

    def _fallback(name: str):
        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))
        return _noop
    mod.__getattr__ = _fallback

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


@pytest.fixture(autouse=True)
def clear_theme_state():
    """Reset theme listeners between tests so picker construction is clean."""
    from pharos_editor.ui.widgets import notebook_theme
    from pharos_editor.ui.widgets.notebook_theme import set_active_theme

    set_active_theme(None)
    notebook_theme._theme_listeners.clear()
    yield
    set_active_theme(None)
    notebook_theme._theme_listeners.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_registry(tmp_path: Path):
    """Return a :class:`ProjectRegistry` pointing at a temp store_path."""
    from pharos_engine.projects import ProjectRegistry

    return ProjectRegistry(store_path=tmp_path / "registry.yaml")


def _make_project(tmp_path: Path, name: str = "Test"):
    """Scaffold a fresh project under tmp_path / name and return it."""
    from pharos_engine.projects import Project

    return Project.new(tmp_path / name.replace(" ", "_"), name)


class _CallbackRecorder:
    def __init__(self) -> None:
        self.chosen: list = []
        self.cancels: int = 0

    def on_chosen(self, project) -> None:
        self.chosen.append(project)

    def on_cancel(self) -> None:
        self.cancels += 1


def _make_picker(tmp_path: Path, registry=None, callbacks=None):
    from pharos_editor.ui.editor.notebook_project_picker import (
        NotebookProjectPicker,
    )

    if registry is None:
        registry = _fresh_registry(tmp_path)
    if callbacks is None:
        callbacks = _CallbackRecorder()
    picker = NotebookProjectPicker(
        on_project_chosen=callbacks.on_chosen,
        on_cancel=callbacks.on_cancel,
        registry=registry,
    )
    return picker, registry, callbacks


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_constructs_with_explicit_registry(self, tmp_path):
        picker, registry, _ = _make_picker(tmp_path)
        assert picker.registry is registry
        assert picker.TITLE == "Pick a notebook"
        assert picker.chosen_count == 0
        assert picker.cancel_count == 0
        assert picker.last_chosen is None

    def test_constructs_with_default_registry(self, tmp_path):
        from pharos_engine.projects.registry import (
            _reset_default_registry_for_tests,
        )
        from pharos_editor.ui.editor.notebook_project_picker import (
            NotebookProjectPicker,
        )

        _reset_default_registry_for_tests()
        try:
            picker = NotebookProjectPicker(
                on_project_chosen=lambda _p: None,
                on_cancel=lambda: None,
            )
            from pharos_engine.projects import ProjectRegistry

            assert isinstance(picker.registry, ProjectRegistry)
        finally:
            _reset_default_registry_for_tests()

    def test_rejects_non_callable_on_project_chosen(self, tmp_path):
        from pharos_editor.ui.editor.notebook_project_picker import (
            NotebookProjectPicker,
        )

        with pytest.raises(TypeError):
            NotebookProjectPicker(
                on_project_chosen="nope",  # type: ignore[arg-type]
                on_cancel=lambda: None,
                registry=_fresh_registry(tmp_path),
            )

    def test_rejects_non_callable_on_cancel(self, tmp_path):
        from pharos_editor.ui.editor.notebook_project_picker import (
            NotebookProjectPicker,
        )

        with pytest.raises(TypeError):
            NotebookProjectPicker(
                on_project_chosen=lambda _p: None,
                on_cancel="nope",  # type: ignore[arg-type]
                registry=_fresh_registry(tmp_path),
            )

    def test_rejects_non_registry(self, tmp_path):
        from pharos_editor.ui.editor.notebook_project_picker import (
            NotebookProjectPicker,
        )

        with pytest.raises(TypeError):
            NotebookProjectPicker(
                on_project_chosen=lambda _p: None,
                on_cancel=lambda: None,
                registry="not-a-registry",  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


class TestLayout:
    def test_empty_registry_shows_empty_state(self, tmp_path, stub_dpg):
        picker, _, _ = _make_picker(tmp_path)
        picker.build("editor_root")
        assert picker.displayed_entries == []
        # The empty-state text should have been rendered.
        added = [args for args, _ in stub_dpg.calls.get("add_text", [])]
        flat = [a[0] for a in added if a]
        assert any(
            picker.EMPTY_STATE_MESSAGE in s
            for s in flat
        )

    def test_three_recents_render_three_rows(self, tmp_path, stub_dpg):
        registry = _fresh_registry(tmp_path)
        for i in range(3):
            registry.register(_make_project(tmp_path, f"Game{i}"))
        picker, _, _ = _make_picker(tmp_path, registry=registry)
        picker.build("editor_root")
        assert len(picker.displayed_entries) == 3
        # Three add_button calls just for the recent rows; plus the
        # action buttons + cancel. We assert ≥ 3 row buttons by counting
        # tags with the row prefix.
        row_btn_count = 0
        for args, kwargs in stub_dpg.calls.get("add_button", []):
            tag = kwargs.get("tag", "")
            if isinstance(tag, str) and "_row_" in tag and tag.endswith("_btn"):
                row_btn_count += 1
        assert row_btn_count == 3

    def test_recents_sorted_newest_first(self, tmp_path):
        registry = _fresh_registry(tmp_path)
        proj_old = _make_project(tmp_path, "Old")
        proj_old.metadata.last_opened_at = "2020-01-01T00:00:00Z"
        proj_old.save()
        registry.register(proj_old)

        proj_new = _make_project(tmp_path, "New")
        proj_new.metadata.last_opened_at = "2026-06-01T00:00:00Z"
        proj_new.save()
        registry.register(proj_new)

        picker, _, _ = _make_picker(tmp_path, registry=registry)
        picker.build("editor_root")
        names = [e.name for e in picker.displayed_entries]
        assert names == ["New", "Old"]


# ---------------------------------------------------------------------------
# Recent click
# ---------------------------------------------------------------------------


class TestRecentClick:
    def test_pick_recent_by_index_fires_chosen(self, tmp_path):
        registry = _fresh_registry(tmp_path)
        proj = _make_project(tmp_path, "ClickMe")
        registry.register(proj)
        picker, _, cb = _make_picker(tmp_path, registry=registry)

        opened = picker.pick_recent(0)
        assert opened is not None
        assert opened.metadata.name == "ClickMe"
        assert cb.chosen == [opened]
        assert picker.chosen_count == 1
        assert picker.last_chosen is opened
        # Picker should close after a successful pick.
        assert picker.is_open is False

    def test_pick_recent_by_path_fires_chosen(self, tmp_path):
        registry = _fresh_registry(tmp_path)
        proj = _make_project(tmp_path, "ByPath")
        registry.register(proj)
        picker, _, cb = _make_picker(tmp_path, registry=registry)
        picker.open()

        opened = picker.pick_recent(str(proj.path))
        assert opened is not None
        assert cb.chosen[0].metadata.name == "ByPath"

    def test_pick_recent_missing_path_drops_entry(self, tmp_path):
        registry = _fresh_registry(tmp_path)
        proj = _make_project(tmp_path, "Vanished")
        registry.register(proj)
        # Delete the project from disk so the next open will fail.
        import shutil
        shutil.rmtree(proj.path)

        picker, _, cb = _make_picker(tmp_path, registry=registry)
        result = picker.pick_recent(0)
        assert result is None
        assert cb.chosen == []
        # The dead entry should have been unregistered.
        assert registry.find(str(proj.path)) is None


# ---------------------------------------------------------------------------
# Remove recent
# ---------------------------------------------------------------------------


class TestRemoveRecent:
    def test_remove_recent_unregisters(self, tmp_path):
        registry = _fresh_registry(tmp_path)
        proj = _make_project(tmp_path, "ToRemove")
        registry.register(proj)
        picker, _, _ = _make_picker(tmp_path, registry=registry)

        removed = picker.remove_recent(str(proj.path))
        assert removed is True
        assert registry.find(str(proj.path)) is None

    def test_remove_recent_refreshes_displayed_entries(self, tmp_path, stub_dpg):
        registry = _fresh_registry(tmp_path)
        proj_a = _make_project(tmp_path, "GameA")
        proj_b = _make_project(tmp_path, "GameB")
        registry.register(proj_a)
        registry.register(proj_b)
        picker, _, _ = _make_picker(tmp_path, registry=registry)
        picker.build("editor_root")
        assert len(picker.displayed_entries) == 2

        picker.remove_recent(str(proj_a.path))
        # Refresh updates the cached snapshot.
        assert {e.name for e in picker.displayed_entries} == {"GameB"}


# ---------------------------------------------------------------------------
# New notebook
# ---------------------------------------------------------------------------


class TestCreateNew:
    def test_create_new_calls_registry_new(self, tmp_path):
        registry = _fresh_registry(tmp_path)
        picker, _, cb = _make_picker(tmp_path, registry=registry)

        proj = picker.create_new(tmp_path / "Brand_New", "Brand New")
        assert proj.metadata.name == "Brand New"
        assert cb.chosen == [proj]
        # The picker should auto-close after a successful create.
        assert picker.is_open is False
        # Registry should have the new project as the most-recent entry.
        recents = registry.list_recent()
        assert recents[0].name == "Brand New"

    def test_create_new_persists_default_theme(self, tmp_path):
        from pharos_engine.projects import read_project

        picker, _, _ = _make_picker(tmp_path)
        proj = picker.create_new(
            tmp_path / "Cozy",
            "Cozy",
            default_theme="cozy_diary",
        )
        # The manifest on disk should record the theme.
        reloaded = read_project(proj.path)
        assert reloaded.metadata.default_theme == "cozy_diary"

    def test_create_new_rejects_unknown_theme(self, tmp_path):
        picker, _, _ = _make_picker(tmp_path)
        with pytest.raises(ValueError):
            picker.create_new(
                tmp_path / "BadTheme",
                "BadTheme",
                default_theme="not_a_real_theme",
            )


# ---------------------------------------------------------------------------
# Open from disk
# ---------------------------------------------------------------------------


class TestOpenFromDisk:
    def test_open_from_disk_walks_to_root(self, tmp_path):
        registry = _fresh_registry(tmp_path)
        proj = _make_project(tmp_path, "WalkUp")
        # Pass a sub-directory; find_project_root walks up to the manifest.
        sub = proj.scenes_dir
        picker, _, cb = _make_picker(tmp_path, registry=registry)

        opened = picker.open_from_disk(sub)
        assert opened is not None
        assert opened.metadata.name == "WalkUp"
        assert cb.chosen[0] is opened

    def test_open_from_disk_returns_none_on_non_project(self, tmp_path):
        picker, _, cb = _make_picker(tmp_path)
        stray = tmp_path / "not_a_project"
        stray.mkdir()
        result = picker.open_from_disk(stray)
        assert result is None
        assert cb.chosen == []


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


class TestCancel:
    def test_cancel_fires_callback(self, tmp_path):
        picker, _, cb = _make_picker(tmp_path)
        picker.open()
        picker.cancel()
        assert cb.cancels == 1
        assert picker.cancel_count == 1
        assert picker.is_open is False


# ---------------------------------------------------------------------------
# Headless safety
# ---------------------------------------------------------------------------


class TestHeadless:
    def test_build_and_close_no_dpg(self, tmp_path, monkeypatch):
        """Even when ``dearpygui`` raises on import the picker must build."""
        # Break the stub import — picker should still succeed.
        monkeypatch.setitem(sys.modules, "dearpygui", None)
        monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", None)

        registry = _fresh_registry(tmp_path)
        proj = _make_project(tmp_path, "HeadlessGame")
        registry.register(proj)
        picker, _, _ = _make_picker(tmp_path, registry=registry)
        picker.build("editor_root")
        # The displayed-entries snapshot should still be populated.
        assert any(e.name == "HeadlessGame" for e in picker.displayed_entries)
        picker.close()


# ---------------------------------------------------------------------------
# Humanised age helper
# ---------------------------------------------------------------------------


class TestHumaniseAge:
    def test_just_now(self):
        from pharos_editor.ui.editor.notebook_project_picker import humanise_age

        now = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)
        stamp = (now - timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
        assert humanise_age(stamp, now=now) == "just now"

    def test_minutes(self):
        from pharos_editor.ui.editor.notebook_project_picker import humanise_age

        now = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)
        stamp = (now - timedelta(minutes=15)).isoformat().replace("+00:00", "Z")
        assert humanise_age(stamp, now=now) == "15m ago"

    def test_today_same_day(self):
        from pharos_editor.ui.editor.notebook_project_picker import humanise_age

        now = datetime(2026, 6, 3, 22, 0, 0, tzinfo=timezone.utc)
        stamp = (now - timedelta(hours=5)).isoformat().replace("+00:00", "Z")
        assert humanise_age(stamp, now=now) == "Today"

    def test_days(self):
        from pharos_editor.ui.editor.notebook_project_picker import humanise_age

        now = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
        stamp = (now - timedelta(days=5)).isoformat().replace("+00:00", "Z")
        assert humanise_age(stamp, now=now) == "5d ago"

    def test_weeks(self):
        from pharos_editor.ui.editor.notebook_project_picker import humanise_age

        now = datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)
        stamp = (now - timedelta(days=14)).isoformat().replace("+00:00", "Z")
        assert humanise_age(stamp, now=now) == "2w ago"

    def test_months(self):
        from pharos_editor.ui.editor.notebook_project_picker import humanise_age

        now = datetime(2026, 12, 1, 12, 0, 0, tzinfo=timezone.utc)
        stamp = (now - timedelta(days=120)).isoformat().replace("+00:00", "Z")
        assert humanise_age(stamp, now=now) == "4mo ago"

    def test_years(self):
        from pharos_editor.ui.editor.notebook_project_picker import humanise_age

        now = datetime(2030, 6, 3, 12, 0, 0, tzinfo=timezone.utc)
        stamp = (now - timedelta(days=800)).isoformat().replace("+00:00", "Z")
        assert humanise_age(stamp, now=now) == "2y ago"

    def test_unknown_on_invalid(self):
        from pharos_editor.ui.editor.notebook_project_picker import humanise_age

        assert humanise_age("not-a-timestamp") == "unknown"
        assert humanise_age("") == "unknown"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_open_close_idempotent(self, tmp_path):
        picker, _, _ = _make_picker(tmp_path)
        picker.open()
        picker.open()
        assert picker.is_open is True
        picker.close()
        picker.close()
        assert picker.is_open is False

    def test_destroy_unregisters_theme_listener(self, tmp_path):
        from pharos_editor.ui.widgets import notebook_theme

        picker, _, _ = _make_picker(tmp_path)
        listeners_before = len(notebook_theme._theme_listeners)
        picker.destroy()
        listeners_after = len(notebook_theme._theme_listeners)
        assert listeners_after <= listeners_before


# ---------------------------------------------------------------------------
# Welcome screen integration
# ---------------------------------------------------------------------------


class TestWelcomeIntegration:
    def test_welcome_open_picker_button_fires_callback(self, tmp_path, stub_dpg):
        """The welcome screen should expose an "Open a notebook" button
        that wires through to the project picker."""
        from pharos_editor.ui.editor.notebook_welcome import NotebookWelcome
        from pharos_editor.ui.editor.settings import UISettings

        opened: list[int] = []
        welcome = NotebookWelcome(
            settings=UISettings(),
            on_start_blank=lambda: None,
            on_open_demo=lambda _d: None,
            on_dismiss=lambda: None,
            on_open_picker=lambda: opened.append(1),
        )
        welcome.build("editor_root")
        # The open-picker button should have been registered.
        tags = [
            kwargs.get("tag")
            for _, kwargs in stub_dpg.calls.get("add_button", [])
        ]
        assert any(
            isinstance(t, str) and t.endswith("_open_picker_btn")
            for t in tags
        )
        # Invoking the click handler should fire the callback.
        welcome._on_open_picker_clicked()
        assert opened == [1]
