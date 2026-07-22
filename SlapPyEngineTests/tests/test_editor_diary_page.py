"""Tests for :class:`NotebookDiaryPage` — the diary-page script editor.

The panel renders a live viewport on the left + a Python/Nodes editor
on the right, presented as a personal-diary page laid flat. These tests
exercise:

* Construction without ``dearpygui`` available (headless contract).
* Layout — the washi-tape title strip, viewport canvas, code input,
  nodes pane, and footer buttons all materialise under the parent tag.
* ``open_diary`` loads a .py file into the source buffer.
* Mode switch — :meth:`set_mode` flips the visible pane + preserves the
  per-file source across toggles.
* ``run_script`` forwards to the engine hook when present; falls back
  to a soft no-op + status hint when ``studio.Stage`` is missing.
* ``save`` writes the source + meta companion back to disk and triggers
  the optional ``on_save`` callback.
* Theme switch routes through :meth:`refresh_theme`.
* The companion ``.diary.meta.yaml`` round-trips ``last_mode``.
* The content-browser icon for ``*.diary.py`` is the new ``diary`` key.

Every ``dpg.*`` call is stubbed with a no-op recorder so the panel
builds cleanly in CI without a real GUI context.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub.
# ---------------------------------------------------------------------------


class _StubCM:
    def __init__(self, recorder: dict, name: str) -> None:
        self._recorder = recorder
        self._name = name

    def __enter__(self):
        self._recorder.setdefault("contexts", []).append(self._name)
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    """Minimal dearpygui surface with call tracking + tag bookkeeping."""

    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: set[str] = set()
        self.values: dict[str, Any] = {}
        self.configs: dict[str, dict] = {}

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    # context-manager primitives
    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM(self.calls, "group")

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM(self.calls, "child_window")

    def popup(self, *a, **kw):
        self._track("popup", a, kw)
        return _StubCM(self.calls, "popup")

    # primitives
    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)
        tag = kw.get("tag")
        if isinstance(tag, str) and a:
            self.values[tag] = a[0]

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)
        tag = kw.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    def add_input_text(self, *a, **kw):
        self._track("add_input_text", a, kw)
        tag = kw.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)
            self.values[tag] = kw.get("default_value", "")

    def add_drawlist(self, *a, **kw):
        self._track("add_drawlist", a, kw)
        tag = kw.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    def add_draw_layer(self, *a, **kw):
        self._track("add_draw_layer", a, kw)
        tag = kw.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def configure_item(self, tag, *a, **kw):
        self._track("configure_item", (tag,) + a, kw)
        if isinstance(tag, str):
            self.configs.setdefault(tag, {}).update(kw)

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.discard(tag)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def set_value(self, tag, value, *a, **kw):
        self._track("set_value", (tag, value), kw)
        if isinstance(tag, str):
            self.values[tag] = value

    def get_item_children(self, *a, **kw):
        return []


@pytest.fixture
def stub_dpg(monkeypatch):
    """Install a fresh stub DPG module."""
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")

    def _fallback(name: str):
        if hasattr(stub, name):
            return getattr(stub, name)

        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))

        return _noop

    mod.__getattr__ = _fallback
    for name in (
        "group", "child_window", "popup",
        "add_text", "add_button", "add_input_text", "add_separator",
        "add_drawlist", "add_draw_layer",
        "configure_item", "delete_item", "does_item_exist", "set_value",
        "get_item_children",
    ):
        setattr(mod, name, getattr(stub, name))

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


@pytest.fixture
def force_studio_missing(monkeypatch):
    """Force the studio module probe to soft-fail."""
    import pharos_engine.ui.editor.notebook_diary_page as ndp
    monkeypatch.setattr(ndp, "_try_import_studio", lambda: None)
    yield


# ---------------------------------------------------------------------------
# Import guard.
# ---------------------------------------------------------------------------


try:
    from pharos_engine.ui.editor.notebook_diary_page import (
        NODES_MODE,
        PYTHON_MODE,
        NotebookDiaryPage,
    )
except Exception as _err:  # pragma: no cover
    pytest.skip(
        f"NotebookDiaryPage not importable: {_err}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_constructs_without_dpg(self):
        """The panel must construct cleanly without a DPG module."""
        panel = NotebookDiaryPage()
        assert panel.TITLE == "Diary"
        assert panel.get_active_path() is None
        assert panel.get_source() == ""

    def test_default_mode_is_python(self):
        """The default mode is Python — Nodes is opt-in."""
        panel = NotebookDiaryPage()
        assert panel.get_mode() == PYTHON_MODE

    def test_engine_handle_stored(self):
        """The engine handle is retained for run/stop dispatch."""
        sentinel = object()
        panel = NotebookDiaryPage(engine=sentinel)
        assert panel._engine is sentinel


# ---------------------------------------------------------------------------
# Build / layout
# ---------------------------------------------------------------------------


class TestBuild:
    def test_build_runs_without_dpg_errors(self, stub_dpg):
        """``build()`` materialises tags under the parent without raising."""
        panel = NotebookDiaryPage()
        panel.build("parent_x")
        assert panel._panel_tag in stub_dpg.items

    def test_washi_tape_title_strip_renders(self, stub_dpg):
        """The washi-tape strip + filename + 2 stickers all render."""
        panel = NotebookDiaryPage()
        panel.open_diary(Path("hello.diary.py"))
        panel.build("parent_x")
        # Title strip group is registered.
        assert panel._tape_tag in stub_dpg.items
        # Heart + flower sticker tags are registered.
        assert panel._heart_tag in stub_dpg.items
        assert panel._flower_tag in stub_dpg.items
        # Title shows the filename.
        title_val = stub_dpg.values.get(panel._title_tag, "")
        assert "hello.diary.py" in str(title_val)

    def test_viewport_canvas_exists(self, stub_dpg):
        """The LEFT pane builds a drawlist viewport canvas."""
        panel = NotebookDiaryPage()
        panel.build("parent_x")
        assert panel._viewport_pane_tag in stub_dpg.items
        assert panel._viewport_canvas_tag in stub_dpg.items

    def test_code_input_exists(self, stub_dpg):
        """The RIGHT pane (Python mode) carries the multiline code input."""
        panel = NotebookDiaryPage()
        panel.build("parent_x")
        assert panel._code_input_tag in stub_dpg.items
        # The multiline kwarg is set on the code input.
        input_calls = stub_dpg.calls.get("add_input_text", [])
        code_calls = [
            (a, kw) for a, kw in input_calls
            if kw.get("tag") == panel._code_input_tag
        ]
        assert code_calls, "code input was never built"
        _, kwargs = code_calls[0]
        assert kwargs.get("multiline") is True

    def test_footer_has_run_stop_save_open_buttons(self, stub_dpg):
        """Footer ribbon contains Run / Stop / Save / Open + mode toggle."""
        panel = NotebookDiaryPage()
        panel.build("parent_x")
        buttons = stub_dpg.calls.get("add_button", [])
        labels = [kw.get("label") or (a[0] if a else "") for a, kw in buttons]
        for expected in ("Run", "Stop", "Save", "Open..."):
            assert expected in labels, f"missing footer button: {expected}"

    def test_default_placeholder_visible(self, stub_dpg):
        """An empty diary shows the 'Dear diary...' placeholder code."""
        panel = NotebookDiaryPage()
        panel.build("parent_x")
        # The code input was built with the placeholder as default_value.
        input_calls = stub_dpg.calls.get("add_input_text", [])
        code_call = [
            (a, kw) for a, kw in input_calls
            if kw.get("tag") == panel._code_input_tag
        ][0]
        default = code_call[1].get("default_value", "")
        assert "Dear diary" in default


# ---------------------------------------------------------------------------
# open_diary / source buffer
# ---------------------------------------------------------------------------


class TestOpenDiary:
    def test_open_diary_loads_source_from_disk(self, stub_dpg, tmp_path):
        """open_diary reads the .py file into the source buffer."""
        f = tmp_path / "hi.diary.py"
        f.write_text("def update(dt):\n    pass\n", encoding="utf-8")
        panel = NotebookDiaryPage()
        panel.open_diary(f)
        assert "def update" in panel.get_source()
        assert panel.get_active_path() == f

    def test_open_diary_missing_file_seeds_placeholder(self, stub_dpg, tmp_path):
        """Opening a non-existent file seeds the 'Dear diary' scaffold."""
        f = tmp_path / "fresh.diary.py"
        panel = NotebookDiaryPage()
        panel.open_diary(f)
        assert "Dear diary" in panel.get_source()
        assert panel.get_active_path() == f

    def test_open_diary_respects_last_mode_meta(self, stub_dpg, tmp_path):
        """When the .meta.yaml records nodes mode, open restores it."""
        f = tmp_path / "n.diary.py"
        f.write_text("pass\n", encoding="utf-8")
        meta = tmp_path / "n.diary.meta.yaml"
        meta.write_text("last_mode: nodes\n", encoding="utf-8")
        panel = NotebookDiaryPage()
        panel.open_diary(f)
        assert panel.get_mode() == NODES_MODE


# ---------------------------------------------------------------------------
# Mode switch
# ---------------------------------------------------------------------------


class TestModeSwitch:
    def test_set_mode_changes_right_pane(self, stub_dpg, tmp_path):
        """set_mode('nodes') hides the code pane + shows the nodes pane."""
        panel = NotebookDiaryPage()
        panel.build("parent_x")
        # Force tags to exist so configure_item paths are exercised.
        stub_dpg.items.add(panel._code_pane_tag)
        stub_dpg.items.add(panel._nodes_pane_tag)
        panel.set_mode(NODES_MODE)
        # configure_item was called with show kwargs reflecting the mode.
        code_config = stub_dpg.configs.get(panel._code_pane_tag, {})
        nodes_config = stub_dpg.configs.get(panel._nodes_pane_tag, {})
        assert code_config.get("show") is False
        assert nodes_config.get("show") is True

    def test_set_mode_rejects_invalid(self):
        """Unknown modes raise immediately — set_mode is the canonical entry."""
        panel = NotebookDiaryPage()
        with pytest.raises(ValueError):
            panel.set_mode("doodle")

    def test_source_preserved_per_mode(self, stub_dpg, tmp_path):
        """Toggling modes preserves the Python source independently."""
        panel = NotebookDiaryPage()
        panel.open_diary(tmp_path / "x.diary.py")
        panel.set_source("# python source\n")
        panel.set_mode(NODES_MODE)
        # Nodes source starts empty — Python source is untouched.
        assert panel.get_source() == ""
        panel.set_mode(PYTHON_MODE)
        assert "# python source" in panel.get_source()


# ---------------------------------------------------------------------------
# Run / Stop dispatch
# ---------------------------------------------------------------------------


class TestRunStop:
    def test_run_script_uses_engine_hook_when_present(self, stub_dpg, tmp_path):
        """run_script forwards to engine.run_script when the hook exists."""
        calls: list = []

        class _StubEngine:
            def run_script(self, panel):
                calls.append(panel)

        panel = NotebookDiaryPage(engine=_StubEngine())
        panel.open_diary(tmp_path / "e.diary.py")
        panel.run_script()
        assert len(calls) == 1
        assert "Running" in panel.status

    def test_run_script_soft_fallback_when_studio_missing(
        self, stub_dpg, force_studio_missing, tmp_path,
    ):
        """run_script reports a soft hint when studio.Stage is unimportable."""
        panel = NotebookDiaryPage()
        panel.open_diary(tmp_path / "s.diary.py")
        panel.run_script()
        assert "studio" in panel.status.lower() or "viewport" in panel.status.lower()

    def test_stop_script_resets_state(self, stub_dpg):
        """stop_script clears the running flag + drops the stage handle."""
        panel = NotebookDiaryPage()
        panel._script_running = True
        panel._stage = object()
        panel.stop_script()
        assert panel._script_running is False
        assert panel.stage is None
        assert "Stop" in panel.status


# ---------------------------------------------------------------------------
# Save / persistence
# ---------------------------------------------------------------------------


class TestSave:
    def test_save_writes_back_to_disk(self, stub_dpg, tmp_path):
        """save() persists the current source buffer to the active path."""
        target = tmp_path / "save_me.diary.py"
        panel = NotebookDiaryPage()
        panel.open_diary(target)
        panel.set_source("# updated\nprint('hi')\n")
        panel.save()
        assert target.exists()
        assert "updated" in target.read_text(encoding="utf-8")

    def test_save_invokes_on_save_callback(self, stub_dpg, tmp_path):
        """The optional on_save callback fires with (path, source)."""
        observed: list = []
        panel = NotebookDiaryPage(
            on_save=lambda p, s: observed.append((p, s)),
        )
        target = tmp_path / "callback.diary.py"
        panel.open_diary(target)
        panel.set_source("# tracked\n")
        panel.save()
        assert observed
        path, source = observed[0]
        assert path == target
        assert "tracked" in source

    def test_save_writes_meta_yaml(self, stub_dpg, tmp_path):
        """save() writes the companion .diary.meta.yaml with last_mode."""
        target = tmp_path / "m.diary.py"
        panel = NotebookDiaryPage()
        panel.open_diary(target)
        panel.set_source("# meta\n")
        panel.set_mode(NODES_MODE)
        panel.save()
        meta_path = tmp_path / "m.diary.meta.yaml"
        assert meta_path.exists()
        text = meta_path.read_text(encoding="utf-8")
        assert "nodes" in text


# ---------------------------------------------------------------------------
# Theme switch
# ---------------------------------------------------------------------------


class TestThemeSwitch:
    def test_refresh_theme_logs_call(self, stub_dpg):
        """refresh_theme() re-emits the status so listeners observe the flip."""
        panel = NotebookDiaryPage()
        panel.build("parent_x")
        panel.refresh_theme()
        events = [e[0] for e in panel.call_log]
        assert "refresh_theme" in events


# ---------------------------------------------------------------------------
# Content browser icon
# ---------------------------------------------------------------------------


class TestContentBrowserIcon:
    def test_diary_py_uses_diary_icon(self):
        """``*.diary.py`` files surface the new diary icon, not the script one."""
        from pharos_engine.ui.editor.notebook_content_browser import (
            icon_for_path,
        )
        assert icon_for_path(Path("notes.diary.py")) == "diary"
        # Regular .py still uses the script icon.
        assert icon_for_path(Path("player.py")) == "script"
