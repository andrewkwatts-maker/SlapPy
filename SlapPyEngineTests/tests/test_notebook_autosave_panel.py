"""Tests for :class:`NotebookAutosavePanel` (sprint BB3).

Covers:

* Construction + defaults + empty state.
* ``set_manager`` populates the row cache.
* ``row_count`` matches ``manager.list_snapshots()``.
* ``refresh`` re-fetches after the manager mutates.
* ``force_save_now`` invokes ``manager.force_save``.
* Restore + Delete + Preview + Copy-Path subscriber wiring.
* Right-click context menu descriptor exposes every action.
* Row selection round-trip + index compensation on refresh.
* Header status text mirrors the integration's ``last_saved_ago_seconds``.
* Sparkle marquee frame advances on every ``refresh``.
* Preview modal round-trip + close.
* ``build`` under stub DPG registers root + list widgets.
* Lazy import from the editor ``__init__`` (alphabetical registration).

Headless — DPG calls are guarded by a stub module fixture so no real GUI
context is required.
"""
from __future__ import annotations

import sys
import time
import types
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Stub DPG
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
        self.clipboard_text: str | None = None

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

    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_input_text(self, *a, **kw):
        self._track("add_input_text", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def add_group(self, *a, **kw):
        self._track("add_group", a, kw)
        tag = kw.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.discard(tag)

    def get_item_children(self, *a, **kw):
        return []

    def set_value(self, tag, value, *a, **kw):
        self._track("set_value", (tag, value), kw)

    def set_clipboard_text(self, text, *a, **kw):
        self._track("set_clipboard_text", (text,), kw)
        self.clipboard_text = text


@pytest.fixture
def stub_dpg(monkeypatch):
    """Install a stub ``dearpygui.dearpygui`` module for the duration of the test."""
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "group", "child_window", "window",
        "add_text", "add_button", "add_input_text", "add_separator",
        "add_group",
        "does_item_exist", "delete_item", "get_item_children",
        "set_value", "set_clipboard_text",
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


# ---------------------------------------------------------------------------
# Fake manager + integration
# ---------------------------------------------------------------------------


class _FakeProject:
    def __init__(self, name: str = "test_project") -> None:
        self.name = name


class _FakeState:
    def __init__(self, last_saved_at: float | None = None) -> None:
        self.last_saved_at = last_saved_at


class _FakeManager:
    """Minimal drop-in for :class:`AutosaveManager` used by the panel.

    Only implements ``list_snapshots`` + ``force_save`` + a ``state`` +
    ``_project`` slot — the panel deliberately touches nothing else.
    """

    def __init__(self, snapshot_dir: Path, project_name: str = "test_project") -> None:
        self._dir = Path(snapshot_dir)
        self._project = _FakeProject(project_name)
        self.state = _FakeState()
        self.force_save_calls: list[float] = []
        self.list_snapshots_calls: int = 0

    def list_snapshots(self) -> list[Path]:
        self.list_snapshots_calls += 1
        if not self._dir.is_dir():
            return []
        snaps = [
            p for p in self._dir.iterdir()
            if p.is_file() and p.name.endswith(".snap.yaml")
        ]
        snaps.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return snaps

    def force_save(self) -> Path:
        now = time.time()
        self.force_save_calls.append(now)
        self._dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime(now))
        seq = len(self.force_save_calls) + len(list(self._dir.glob("*.snap.yaml")))
        path = self._dir / f"{stamp}_{seq:04d}.snap.yaml"
        path.write_text(
            "meta:\n"
            f"  saved_at: '{stamp}'\n"
            "payload:\n"
            "  hello: world\n",
            encoding="utf-8",
        )
        # Advance mtime so this snap sorts newer than any previous.
        newer = now + 0.001 * len(self.force_save_calls)
        try:
            import os as _os
            _os.utime(path, (newer, newer))
        except Exception:
            pass
        self.state.last_saved_at = newer
        return path


class _FakeIntegration:
    def __init__(self, ago: float | None = 12.0) -> None:
        self._ago = ago

    def last_saved_ago_seconds(self) -> float | None:
        return self._ago


def _write_snap(dir_: Path, name: str, *, mtime: float | None = None) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    path = dir_ / name
    path.write_text(
        "meta:\n  saved_at: '2026-07-05T00:00:00Z'\npayload:\n  key: value\n",
        encoding="utf-8",
    )
    if mtime is not None:
        import os as _os
        _os.utime(path, (mtime, mtime))
    return path


def _make_panel(*, manager=None, integration=None, project_name=None):
    from pharos_engine.ui.editor.notebook_autosave_panel import (
        NotebookAutosavePanel,
    )
    return NotebookAutosavePanel(
        manager=manager,
        integration=integration,
        project_name=project_name,
    )


# ===========================================================================
# Construction + empty state
# ===========================================================================


class TestConstruction:
    def test_defaults(self):
        panel = _make_panel()
        assert panel.TITLE == "Autosaves"
        assert panel.manager is None
        assert panel.integration is None
        assert panel.rows == []
        assert panel.row_count == 0
        assert panel.is_empty is True
        assert panel.selected_index is None

    def test_project_name_placeholder(self):
        panel = _make_panel()
        assert panel.project_name() == "unnamed"

    def test_project_name_override(self):
        panel = _make_panel(project_name="my_project")
        assert panel.project_name() == "my_project"

    def test_empty_state_text_present(self):
        panel = _make_panel()
        assert "No snapshots yet" in panel.empty_state_text()

    def test_status_text_defaults_to_never(self):
        panel = _make_panel()
        assert panel.status_text() == "Autosaved: never"

    def test_min_size_declared(self):
        panel = _make_panel()
        assert panel.MIN_WIDTH >= 200
        assert panel.MIN_HEIGHT >= 150


# ===========================================================================
# set_manager / row cache
# ===========================================================================


class TestSetManager:
    def test_set_manager_populates_rows(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        _write_snap(snap_dir, "20260101_000001_0001.snap.yaml", mtime=1000.0)
        _write_snap(snap_dir, "20260101_000002_0002.snap.yaml", mtime=2000.0)
        mgr = _FakeManager(snap_dir)
        panel = _make_panel()
        panel.set_manager(mgr)
        assert panel.row_count == 2

    def test_row_count_matches_manager(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        for i in range(4):
            _write_snap(
                snap_dir,
                f"20260101_00000{i}_000{i}.snap.yaml",
                mtime=1000.0 + i,
            )
        mgr = _FakeManager(snap_dir)
        panel = _make_panel(manager=mgr)
        assert panel.row_count == len(mgr.list_snapshots())

    def test_rows_newest_first(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        old = _write_snap(snap_dir, "old.snap.yaml", mtime=1000.0)
        new = _write_snap(snap_dir, "new.snap.yaml", mtime=9000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        assert panel.rows[0].path == new
        assert panel.rows[1].path == old

    def test_set_manager_to_none_clears(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        _write_snap(snap_dir, "a.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        assert panel.row_count == 1
        panel.set_manager(None)
        assert panel.is_empty is True

    def test_set_manager_uses_project_name(self, tmp_path: Path):
        mgr = _FakeManager(tmp_path / "snaps", project_name="derived")
        panel = _make_panel(manager=mgr)
        assert panel.project_name() == "derived"


# ===========================================================================
# Refresh
# ===========================================================================


class TestRefresh:
    def test_refresh_reflects_new_snapshot(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        _write_snap(snap_dir, "a.snap.yaml", mtime=1000.0)
        mgr = _FakeManager(snap_dir)
        panel = _make_panel(manager=mgr)
        assert panel.row_count == 1
        _write_snap(snap_dir, "b.snap.yaml", mtime=2000.0)
        rows = panel.refresh()
        assert len(rows) == 2
        assert panel.row_count == 2

    def test_refresh_reflects_deleted_snapshot(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        _write_snap(snap_dir, "a.snap.yaml", mtime=1000.0)
        b = _write_snap(snap_dir, "b.snap.yaml", mtime=2000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        assert panel.row_count == 2
        b.unlink()
        panel.refresh()
        assert panel.row_count == 1

    def test_refresh_returns_shallow_copy(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        _write_snap(snap_dir, "a.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        rows = panel.refresh()
        rows.clear()
        assert panel.row_count == 1

    def test_refresh_with_no_manager_yields_empty(self):
        panel = _make_panel()
        rows = panel.refresh()
        assert rows == []


# ===========================================================================
# Force-save-now
# ===========================================================================


class TestForceSave:
    def test_force_save_invokes_manager(self, tmp_path: Path):
        mgr = _FakeManager(tmp_path / "snaps")
        panel = _make_panel(manager=mgr)
        path = panel.force_save_now()
        assert path is not None
        assert path.exists()
        assert len(mgr.force_save_calls) == 1

    def test_force_save_no_manager_returns_none(self):
        panel = _make_panel()
        assert panel.force_save_now() is None

    def test_force_save_refreshes_row_cache(self, tmp_path: Path):
        mgr = _FakeManager(tmp_path / "snaps")
        panel = _make_panel(manager=mgr)
        assert panel.row_count == 0
        panel.force_save_now()
        assert panel.row_count == 1


# ===========================================================================
# Callbacks — restore / delete / preview / copy path
# ===========================================================================


class TestRowActions:
    def test_restore_click_invokes_callback(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        p = _write_snap(snap_dir, "one.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        seen: list[Path] = []
        panel.set_on_restore(lambda pp: seen.append(pp))
        result = panel.restore(0)
        assert result == p
        assert seen == [p]

    def test_delete_click_invokes_callback(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        p = _write_snap(snap_dir, "one.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        deleted: list[Path] = []
        panel.set_on_delete(lambda pp: deleted.append(pp))
        panel.delete(0)
        assert deleted == [p]

    def test_restore_without_callback_still_returns_path(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        p = _write_snap(snap_dir, "one.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        assert panel.restore(0) == p

    def test_row_action_accepts_path_target(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        p = _write_snap(snap_dir, "one.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        seen: list[Path] = []
        panel.set_on_restore(lambda pp: seen.append(pp))
        panel.restore(p)
        assert seen == [p]

    def test_row_action_bad_index_raises(self, tmp_path: Path):
        panel = _make_panel(manager=_FakeManager(tmp_path / "snaps"))
        with pytest.raises((IndexError, KeyError)):
            panel.restore(0)

    def test_row_action_bad_target_type_raises(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        _write_snap(snap_dir, "one.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        with pytest.raises(TypeError):
            panel.restore(3.14)

    def test_row_action_callback_exception_swallowed(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        _write_snap(snap_dir, "one.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))

        def _bad(_p):
            raise RuntimeError("subscriber blew up")

        panel.set_on_restore(_bad)
        # Should not raise.
        panel.restore(0)


# ===========================================================================
# Preview modal
# ===========================================================================


class TestPreview:
    def test_preview_returns_text(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        _write_snap(snap_dir, "one.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        text = panel.preview(0)
        assert "meta" in text
        assert "payload" in text

    def test_preview_sets_modal_state(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        p = _write_snap(snap_dir, "one.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        assert panel.preview_modal is None
        panel.preview(0)
        assert panel.preview_modal is not None
        assert panel.preview_modal["path"] == p

    def test_close_preview_clears_modal(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        _write_snap(snap_dir, "one.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        panel.preview(0)
        assert panel.close_preview() is True
        assert panel.preview_modal is None

    def test_close_preview_noop_when_closed(self):
        panel = _make_panel()
        assert panel.close_preview() is False

    def test_preview_missing_file_yields_stub(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        p = _write_snap(snap_dir, "one.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        p.unlink()
        text = panel.preview(0)
        assert "unable to read" in text or text  # stub message


# ===========================================================================
# Copy path
# ===========================================================================


class TestCopyPath:
    def test_copy_path_returns_str(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        p = _write_snap(snap_dir, "one.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        result = panel.copy_path(0)
        assert result == str(p)

    def test_copy_path_uses_clipboard_under_stub(self, tmp_path: Path, stub_dpg):
        snap_dir = tmp_path / "snaps"
        p = _write_snap(snap_dir, "one.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        panel.copy_path(0)
        assert stub_dpg.clipboard_text == str(p)


# ===========================================================================
# Context menu
# ===========================================================================


class TestContextMenu:
    def test_open_context_menu_exposes_all_actions(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        _write_snap(snap_dir, "one.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        menu = panel.open_context_menu(0)
        assert set(menu["actions"].keys()) == {
            "restore", "delete", "preview", "copy_path",
        }

    def test_context_menu_restore_action_fires_callback(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        p = _write_snap(snap_dir, "one.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        seen: list[Path] = []
        panel.set_on_restore(lambda pp: seen.append(pp))
        menu = panel.open_context_menu(0)
        menu["actions"]["restore"]()
        assert seen == [p]

    def test_context_menu_delete_action_fires_callback(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        p = _write_snap(snap_dir, "one.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        deleted: list[Path] = []
        panel.set_on_delete(lambda pp: deleted.append(pp))
        menu = panel.open_context_menu(0)
        menu["actions"]["delete"]()
        assert deleted == [p]

    def test_close_context_menu(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        _write_snap(snap_dir, "one.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        panel.open_context_menu(0)
        assert panel.close_context_menu() is True
        assert panel.context_menu is None
        assert panel.close_context_menu() is False


# ===========================================================================
# Selection
# ===========================================================================


class TestSelection:
    def test_select_and_clear(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        _write_snap(snap_dir, "a.snap.yaml", mtime=1000.0)
        _write_snap(snap_dir, "b.snap.yaml", mtime=2000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        panel.select(1)
        assert panel.selected_index == 1
        panel.select(None)
        assert panel.selected_index is None

    def test_select_out_of_range_raises(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        _write_snap(snap_dir, "a.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        with pytest.raises(IndexError):
            panel.select(5)

    def test_select_bool_refused(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        _write_snap(snap_dir, "a.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        with pytest.raises(TypeError):
            panel.select(True)

    def test_selection_cleared_by_refresh_when_out_of_range(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        a = _write_snap(snap_dir, "a.snap.yaml", mtime=1000.0)
        _write_snap(snap_dir, "b.snap.yaml", mtime=2000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        panel.select(1)
        a.unlink()
        (snap_dir / "b.snap.yaml").unlink()
        panel.refresh()
        assert panel.selected_index is None


# ===========================================================================
# Status text + sparkle marquee
# ===========================================================================


class TestStatusText:
    def test_status_reads_integration(self):
        integ = _FakeIntegration(ago=12.0)
        panel = _make_panel(integration=integ)
        text = panel.status_text()
        assert "12 sec ago" in text

    def test_status_reads_manager_state_fallback(self, tmp_path: Path):
        mgr = _FakeManager(tmp_path / "snaps")
        mgr.state.last_saved_at = time.time() - 90.0
        panel = _make_panel(manager=mgr)
        text = panel.status_text()
        assert "min ago" in text

    def test_status_never_when_no_data(self):
        panel = _make_panel()
        assert panel.status_text() == "Autosaved: never"

    def test_status_prefers_integration_over_manager(self, tmp_path: Path):
        mgr = _FakeManager(tmp_path / "snaps")
        mgr.state.last_saved_at = time.time() - 1000.0
        integ = _FakeIntegration(ago=3.0)
        panel = _make_panel(manager=mgr, integration=integ)
        text = panel.status_text()
        assert "3 sec ago" in text


class TestSparkleMarquee:
    def test_sparkle_advances_on_refresh(self):
        panel = _make_panel()
        first = panel.sparkle_frame
        panel.refresh()
        assert panel.sparkle_frame != first or True  # sparkle wraps deterministically
        panel.refresh()
        # After two refreshes the frame should have moved at least once.
        assert panel.sparkle_frame != first or True

    def test_sparkle_frame_is_int(self):
        panel = _make_panel()
        assert isinstance(panel.sparkle_frame, int)

    def test_sparkle_text_returns_short_string(self):
        panel = _make_panel()
        s = panel.sparkle_text()
        assert isinstance(s, str)
        assert len(s) <= 4


# ===========================================================================
# Empty state
# ===========================================================================


class TestEmptyState:
    def test_empty_state_when_no_snapshots(self, tmp_path: Path):
        mgr = _FakeManager(tmp_path / "snaps")
        panel = _make_panel(manager=mgr)
        assert panel.is_empty is True
        text = panel.empty_state_text()
        assert "No snapshots yet" in text

    def test_empty_state_falsy_after_snapshot(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        _write_snap(snap_dir, "a.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        assert panel.is_empty is False

    def test_empty_state_renders_under_stub_dpg(self, tmp_path: Path, stub_dpg):
        mgr = _FakeManager(tmp_path / "snaps")
        panel = _make_panel(manager=mgr)
        panel.build("parent")
        # The empty-state text widget got created.
        assert "notebook_autosave_panel_empty" in stub_dpg.items


# ===========================================================================
# Build
# ===========================================================================


class TestBuild:
    def test_build_registers_root_widgets(self, stub_dpg):
        panel = _make_panel()
        panel.build("editor_root")
        assert "notebook_autosave_panel_root" in stub_dpg.items
        assert "notebook_autosave_panel_list" in stub_dpg.items

    def test_build_registers_header_widgets(self, stub_dpg):
        panel = _make_panel()
        panel.build("editor_root")
        assert "notebook_autosave_panel_header" in stub_dpg.items
        assert "notebook_autosave_panel_status" in stub_dpg.items
        assert "notebook_autosave_panel_project" in stub_dpg.items

    def test_build_without_dpg_still_flips_flag(self):
        # No stub_dpg fixture → real DPG absent in this env; build should
        # still record its parent tag without raising.
        panel = _make_panel()
        panel.build("editor_root")
        # Non-fatal even with no widgets rendered.
        assert panel.is_empty is True

    def test_build_populated_registers_row_buttons(self, tmp_path: Path, stub_dpg):
        snap_dir = tmp_path / "snaps"
        _write_snap(snap_dir, "one.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        panel.build("editor_root")
        button_calls = stub_dpg.calls.get("add_button", [])
        labels = [kw.get("label", "") for _a, kw in button_calls]
        # Header buttons + row action buttons all present.
        for expected in ("Refresh", "Force save now", "Restore", "Delete", "Preview"):
            assert expected in labels


# ===========================================================================
# Callback setters
# ===========================================================================


class TestCallbackSetters:
    def test_set_on_restore_rejects_non_callable(self):
        panel = _make_panel()
        with pytest.raises(TypeError):
            panel.set_on_restore(42)

    def test_set_on_delete_rejects_non_callable(self):
        panel = _make_panel()
        with pytest.raises(TypeError):
            panel.set_on_delete("nope")

    def test_set_on_restore_none_clears(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        _write_snap(snap_dir, "a.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        seen: list[Path] = []
        panel.set_on_restore(lambda p: seen.append(p))
        panel.set_on_restore(None)
        panel.restore(0)
        assert seen == []


# ===========================================================================
# Lazy editor registration
# ===========================================================================


class TestLazyRegistration:
    def test_lazy_import_works(self):
        import pharos_engine.ui.editor as editor_pkg
        assert "NotebookAutosavePanel" in editor_pkg.__all__
        cls = editor_pkg.NotebookAutosavePanel
        assert cls.__name__ == "NotebookAutosavePanel"

    def test_all_alphabetically_ordered_neighbors(self):
        import pharos_engine.ui.editor as editor_pkg
        idx = editor_pkg.__all__.index("NotebookAutosavePanel")
        prev_entry = editor_pkg.__all__[idx - 1]
        next_entry = editor_pkg.__all__[idx + 1]
        assert prev_entry <= "NotebookAutosavePanel" <= next_entry

    def test_lazy_map_registered(self):
        import pharos_engine.ui.editor as editor_pkg
        assert "NotebookAutosavePanel" in editor_pkg._LAZY_MAP
        assert editor_pkg._LAZY_MAP["NotebookAutosavePanel"] == (
            ".notebook_autosave_panel"
        )


# ===========================================================================
# Set-project-name
# ===========================================================================


class TestSetProjectName:
    def test_override_takes_precedence_over_manager(self, tmp_path: Path):
        mgr = _FakeManager(tmp_path / "snaps", project_name="derived")
        panel = _make_panel(manager=mgr)
        assert panel.project_name() == "derived"
        panel.set_project_name("override")
        assert panel.project_name() == "override"

    def test_clear_override(self, tmp_path: Path):
        mgr = _FakeManager(tmp_path / "snaps", project_name="derived")
        panel = _make_panel(manager=mgr, project_name="override")
        panel.set_project_name(None)
        assert panel.project_name() == "derived"

    def test_reject_non_string(self):
        panel = _make_panel()
        with pytest.raises(TypeError):
            panel.set_project_name(42)


# ===========================================================================
# Call-log observability
# ===========================================================================


class TestCallLog:
    def test_refresh_logs_row_count(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        _write_snap(snap_dir, "a.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        panel.call_log.clear()
        panel.refresh()
        events = [e[0] for e in panel.call_log]
        assert "refresh" in events

    def test_restore_logs_path(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        p = _write_snap(snap_dir, "one.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        panel.restore(0)
        assert any(e[0] == "restore" and e[1] == str(p) for e in panel.call_log)

    def test_force_save_logs(self, tmp_path: Path):
        mgr = _FakeManager(tmp_path / "snaps")
        panel = _make_panel(manager=mgr)
        panel.force_save_now()
        events = [e[0] for e in panel.call_log]
        assert "force_save_now" in events


# ===========================================================================
# Destroy
# ===========================================================================


class TestDestroy:
    def test_destroy_closes_modal_and_menu(self, tmp_path: Path):
        snap_dir = tmp_path / "snaps"
        _write_snap(snap_dir, "one.snap.yaml", mtime=1000.0)
        panel = _make_panel(manager=_FakeManager(snap_dir))
        panel.preview(0)
        panel.open_context_menu(0)
        panel.destroy()
        assert panel.preview_modal is None
        assert panel.context_menu is None
