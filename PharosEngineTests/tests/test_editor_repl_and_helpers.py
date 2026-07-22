"""Tests for the CCC2 REPL panel + editor helper suite.

Covers:

* Every helper in :mod:`pharos_editor.editor.helpers` is importable,
  carries a non-empty docstring, and (for spawn helpers) returns a
  handle with the requested initial state.
* ``clear_scene`` empties the app; ``save_scene`` / ``load_scene``
  round-trip through YAML on disk.
* The REPL panel builds cleanly under a stub DPG module.
* ``REPLPanel.submit("1+1")`` renders ``"2"`` into the output buffer.
* ``REPLPanel.submit('raise ValueError("test")')`` records the
  traceback with kind ``"error"``.
* History navigation walks Up/Down through submitted commands.
* Tab completion offers attribute candidates on ``app.`` and
  ``helpers.``.
"""
from __future__ import annotations

import inspect
import sys
import types
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# DPG stub — modelled after ``test_editor_content_browser`` so the panel
# builds without a real GUI context.
# ---------------------------------------------------------------------------


class _StubCM:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: dict[str, Any] = {}
        # DPG key-code constants used by the REPL panel.
        self.mvKey_Up = 265
        self.mvKey_Down = 264
        self.mvKey_Tab = 258

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items[tag] = kwargs

    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM()

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM()

    def add_child_window(self, *a, **kw):
        self._track("add_child_window", a, kw)

    def handler_registry(self, *a, **kw):
        self._track("handler_registry", a, kw)
        return _StubCM()

    def add_key_press_handler(self, *a, **kw):
        self._track("add_key_press_handler", a, kw)

    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def add_input_text(self, *a, **kw):
        self._track("add_input_text", a, kw)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)

    def get_value(self, tag):
        return self.items.get(tag, {}).get("_value", "")

    def set_value(self, tag, value):
        self.items.setdefault(tag, {})["_value"] = value


@pytest.fixture
def stub_dpg(monkeypatch):
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "group", "child_window", "add_child_window", "handler_registry",
        "add_key_press_handler", "add_text", "add_separator",
        "add_input_text", "does_item_exist", "delete_item",
        "get_value", "set_value",
        "mvKey_Up", "mvKey_Down", "mvKey_Tab",
    ):
        setattr(mod, name, getattr(stub, name))

    def _fallback(name: str):
        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))
            return _StubCM()
        return _noop

    mod.__getattr__ = _fallback  # type: ignore[attr-defined]

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


@pytest.fixture
def fresh_app():
    """Return a fresh :class:`App` with the implicit-global cleared."""
    from pharos_engine.app import App

    App._clear_implicit()
    app = App()
    App._implicit = app
    yield app
    try:
        app.close()
    except Exception:
        pass
    App._clear_implicit()


# ---------------------------------------------------------------------------
# Helper surface
# ---------------------------------------------------------------------------


EXPECTED_HELPERS = [
    "spawn_cube",
    "spawn_sphere",
    "spawn_plane",
    "spawn_light",
    "set_camera",
    "load_model",
    "load_texture",
    "load_shader",
    "list_entities",
    "select",
    "move",
    "rotate",
    "scale",
    "delete",
    "clear_scene",
    "save_scene",
    "load_scene",
    "set_background",
    "screenshot",
    "record_gif",
    "help",
]


class TestHelperSurface:
    def test_module_importable(self):
        from pharos_editor.editor import helpers

        assert helpers is not None

    def test_editor_package_importable(self):
        import pharos_editor.editor as ed

        assert hasattr(ed, "helpers")

    def test_all_expected_helpers_exported(self):
        from pharos_editor.editor import helpers

        for name in EXPECTED_HELPERS:
            assert hasattr(helpers, name), f"missing helper: {name}"
            assert name in helpers.__all__, f"{name} not in __all__"

    def test_at_least_20_public_helpers(self):
        from pharos_editor.editor import helpers

        publics = [n for n in helpers.__all__ if not n.startswith("_")
                   and callable(getattr(helpers, n))]
        assert len(publics) >= 20, f"only {len(publics)} public helpers"

    def test_every_helper_has_docstring(self):
        from pharos_editor.editor import helpers

        for name in EXPECTED_HELPERS:
            fn = getattr(helpers, name)
            doc = inspect.getdoc(fn) or ""
            assert doc.strip(), f"{name} has no docstring"


# ---------------------------------------------------------------------------
# Spawning behaviour
# ---------------------------------------------------------------------------


class TestSpawning:
    def test_spawn_cube_returns_model_handle_with_position(self, fresh_app):
        from pharos_engine.app import ModelHandle
        from pharos_editor.editor.helpers import spawn_cube

        h = spawn_cube(position=(1.0, 2.0, 3.0), size=2.0, app=fresh_app)
        assert isinstance(h, ModelHandle)
        assert h.position == (1.0, 2.0, 3.0)
        assert h.scale == (2.0, 2.0, 2.0)
        assert h in fresh_app.models

    def test_spawn_sphere_uses_radius_as_scale(self, fresh_app):
        from pharos_editor.editor.helpers import spawn_sphere

        h = spawn_sphere(position=(0.0, 5.0, 0.0), radius=0.25, app=fresh_app)
        assert h.position == (0.0, 5.0, 0.0)
        assert h.scale == (0.25, 0.25, 0.25)

    def test_spawn_plane_maps_size_to_xz(self, fresh_app):
        from pharos_editor.editor.helpers import spawn_plane

        h = spawn_plane(size=(20.0, 30.0), app=fresh_app)
        assert h.scale == (20.0, 1.0, 30.0)

    def test_spawn_light_returns_light_handle(self, fresh_app):
        from pharos_engine.app import LightHandle
        from pharos_editor.editor.helpers import spawn_light

        h = spawn_light(
            position=(4.0, 4.0, 4.0), color=(1.0, 0.5, 0.0),
            intensity=2.5, app=fresh_app,
        )
        assert isinstance(h, LightHandle)
        assert h.intensity == 2.5
        assert h in fresh_app.lights

    def test_set_camera_marks_active(self, fresh_app):
        from pharos_editor.editor.helpers import set_camera

        cam = set_camera(position=(0.0, 0.0, 10.0), app=fresh_app)
        assert cam.position == (0.0, 0.0, 10.0)
        assert fresh_app.active_camera is cam


# ---------------------------------------------------------------------------
# Transform + lifecycle
# ---------------------------------------------------------------------------


class TestTransforms:
    def test_move_translates(self, fresh_app):
        from pharos_editor.editor.helpers import move, spawn_cube

        h = spawn_cube(app=fresh_app)
        move(h, dx=1, dy=2, dz=3)
        assert h.position == (1.0, 2.0, 3.0)

    def test_rotate_adds(self, fresh_app):
        from pharos_editor.editor.helpers import rotate, spawn_cube

        h = spawn_cube(app=fresh_app)
        rotate(h, ry=1.5)
        assert h.rotation == (0.0, 1.5, 0.0)

    def test_scale_multiplies(self, fresh_app):
        from pharos_editor.editor.helpers import scale, spawn_cube

        h = spawn_cube(size=2.0, app=fresh_app)
        scale(h, factor=3.0)
        assert h.scale == (6.0, 6.0, 6.0)

    def test_delete_removes_from_app(self, fresh_app):
        from pharos_editor.editor.helpers import delete, spawn_cube

        h = spawn_cube(app=fresh_app)
        assert h in fresh_app.models
        delete(h, app=fresh_app)
        assert h not in fresh_app.models

    def test_clear_scene_empties_everything(self, fresh_app):
        from pharos_editor.editor.helpers import (
            clear_scene, set_camera, spawn_cube, spawn_light,
        )

        spawn_cube(app=fresh_app)
        spawn_light(app=fresh_app)
        set_camera(app=fresh_app)
        clear_scene(app=fresh_app)
        assert fresh_app.models == []
        assert fresh_app.lights == []
        assert fresh_app.cameras == []
        assert fresh_app.active_camera is None


# ---------------------------------------------------------------------------
# Discovery + selection
# ---------------------------------------------------------------------------


class TestSelection:
    def test_list_entities_returns_flat_list(self, fresh_app):
        from pharos_editor.editor.helpers import (
            list_entities, spawn_cube, spawn_light,
        )

        spawn_cube(app=fresh_app)
        spawn_light(app=fresh_app)
        entities = list_entities(app=fresh_app)
        assert len(entities) == 2

    def test_select_finds_by_id(self, fresh_app):
        from pharos_editor.editor.helpers import select, spawn_cube

        h = spawn_cube(app=fresh_app)
        found = select(h.id, app=fresh_app)
        assert found is h

    def test_select_none_on_miss(self, fresh_app):
        from pharos_editor.editor.helpers import select

        assert select(9999, app=fresh_app) is None


# ---------------------------------------------------------------------------
# Scene IO + capture
# ---------------------------------------------------------------------------


class TestSceneIO:
    def test_save_and_load_scene_roundtrip(self, fresh_app, tmp_path):
        from pharos_editor.editor.helpers import (
            clear_scene, list_entities, load_scene,
            save_scene, spawn_cube, spawn_light,
        )

        spawn_cube(position=(1.0, 0.0, 0.0), app=fresh_app)
        spawn_light(position=(2.0, 0.0, 0.0), app=fresh_app)
        out = save_scene(tmp_path / "scene.yaml", app=fresh_app)
        assert out.exists()

        clear_scene(app=fresh_app)
        assert list_entities(app=fresh_app) == []

        load_scene(out, app=fresh_app)
        entities = list_entities(app=fresh_app)
        assert len(entities) == 2

    def test_set_background_updates_config(self, fresh_app):
        from pharos_editor.editor.helpers import set_background

        set_background((0.2, 0.3, 0.4), app=fresh_app)
        assert fresh_app.config.clear_color[:3] == (0.2, 0.3, 0.4)

    def test_load_shader_reads_file(self, fresh_app, tmp_path):
        from pharos_editor.editor.helpers import ShaderHandle, load_shader

        src = "@compute fn main() {}"
        p = tmp_path / "test.wgsl"
        p.write_text(src, encoding="utf-8")
        h = load_shader(p, app=fresh_app)
        assert isinstance(h, ShaderHandle)
        assert h.source == src


# ---------------------------------------------------------------------------
# help() cheat sheet
# ---------------------------------------------------------------------------


class TestHelpCheatSheet:
    def test_help_returns_markdown_with_every_helper(self):
        from pharos_editor.editor.helpers import help as helpers_help

        text = helpers_help()
        assert isinstance(text, str)
        assert text.startswith("# Pharos Engine editor helpers")
        for name in EXPECTED_HELPERS:
            if name == "help":
                continue  # help skips itself
            assert f"`{name}" in text, f"help() missing {name}"


# ---------------------------------------------------------------------------
# REPL panel — build + submit + traceback
# ---------------------------------------------------------------------------


class TestREPLPanel:
    def test_panel_builds_under_dpg_stub(self, stub_dpg, fresh_app):
        from pharos_editor.ui.editor.repl_panel import REPLPanel

        panel = REPLPanel(app=fresh_app)
        panel.build(parent_tag="parent_container")
        assert panel._built is True
        # Group + input widget landed.
        assert stub_dpg.calls.get("group") or stub_dpg.calls.get("add_text")
        assert stub_dpg.calls.get("add_input_text")

    def test_submit_expression_returns_repr(self, fresh_app):
        from pharos_editor.ui.editor.repl_panel import REPLPanel

        panel = REPLPanel(app=fresh_app)
        out = panel.submit("1 + 1")
        assert out == "2"
        # Output buffer should hold a prompt + a result entry.
        kinds = [k for k, _ in panel.output]
        assert "prompt" in kinds
        assert "result" in kinds

    def test_submit_statement_persists_binding(self, fresh_app):
        from pharos_editor.ui.editor.repl_panel import REPLPanel

        panel = REPLPanel(app=fresh_app)
        panel.submit("x = 42")
        result = panel.submit("x")
        assert result == "42"

    def test_submit_traceback_captured(self, fresh_app):
        from pharos_editor.ui.editor.repl_panel import REPLPanel

        panel = REPLPanel(app=fresh_app)
        out = panel.submit('raise ValueError("test")')
        assert "ValueError" in out
        assert "test" in out
        # Error entry recorded.
        errors = [t for k, t in panel.output if k == "error"]
        assert errors, "no error captured in output"
        assert "ValueError" in errors[-1]

    def test_history_navigation(self, fresh_app):
        from pharos_editor.ui.editor.repl_panel import REPLPanel

        panel = REPLPanel(app=fresh_app)
        panel.submit("a = 1")
        panel.submit("b = 2")
        panel.submit("c = 3")

        assert panel.previous() == "c = 3"
        assert panel.previous() == "b = 2"
        assert panel.previous() == "a = 1"
        assert panel.previous() == "a = 1"  # clamps at head
        assert panel.next() == "b = 2"
        assert panel.next() == "c = 3"
        assert panel.next() == ""  # back at the live line

    def test_tab_completion_on_helpers(self, fresh_app):
        from pharos_editor.ui.editor.repl_panel import REPLPanel

        panel = REPLPanel(app=fresh_app)
        # Force ns build so helpers are bound.
        panel._get_namespace()
        candidates = panel.complete("helpers.spawn_cu")
        assert any("spawn_cube" in c for c in candidates)

    def test_tab_completion_top_level(self, fresh_app):
        from pharos_editor.ui.editor.repl_panel import REPLPanel

        panel = REPLPanel(app=fresh_app)
        panel._get_namespace()
        candidates = panel.complete("spawn_cu")
        assert any("spawn_cube" in c for c in candidates)

    def test_slash_help_command(self, fresh_app):
        from pharos_editor.ui.editor.repl_panel import REPLPanel

        panel = REPLPanel(app=fresh_app)
        panel.submit("/help")
        info_entries = [t for k, t in panel.output if k == "info"]
        # Banner + /help both info-tagged.
        assert any("Panel commands" in t for t in info_entries)

    def test_slash_clear_empties_output(self, fresh_app):
        from pharos_editor.ui.editor.repl_panel import REPLPanel

        panel = REPLPanel(app=fresh_app)
        panel.submit("1 + 1")
        panel.submit("/clear")
        # After clear only the banner remains.
        assert len(panel.output) == 1
        assert panel.output[0][0] == "info"

    def test_namespace_includes_app_and_helpers(self, fresh_app):
        from pharos_editor.ui.editor.repl_panel import REPLPanel

        panel = REPLPanel(app=fresh_app)
        ns = panel._get_namespace()
        assert ns["app"] is fresh_app
        assert "helpers" in ns
        assert "pharos_engine" in ns
        assert "spawn_cube" in ns


# ---------------------------------------------------------------------------
# End-to-end — REPL drives a helper against the app
# ---------------------------------------------------------------------------


class TestREPLEndToEnd:
    def test_repl_can_spawn_cube_into_app(self, fresh_app):
        from pharos_editor.ui.editor.repl_panel import REPLPanel

        panel = REPLPanel(app=fresh_app)
        panel.submit("spawn_cube(position=(3, 0, 0))")
        assert len(fresh_app.models) == 1
        assert fresh_app.models[0].position == (3.0, 0.0, 0.0)
