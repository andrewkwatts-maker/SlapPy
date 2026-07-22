"""BB1 STUB-triage tests — fifth round of feature-map wiring.

Covers the five new action ids added by the 2026-07-05 BB1 sprint tick
(``docs/engine_feature_map_2026_07_04.md`` §"BB1 STUB-triage patch"):

* ``theme.import_from_file`` — read a ``*.theme.yaml`` file, register
  it, and (optionally) activate it.
* ``file.save_layout_as`` — snapshot the current shell layout and write
  it to a caller-picked YAML file.
* ``file.load_layout_from_file`` — read a layout YAML and apply it to
  the shell.
* ``edit.undo`` — pop + reverse the newest ``UndoStack`` entry.
* ``edit.redo`` — reapply the newest redo entry.

Every test dispatches through :class:`~pharos_editor.tool_router.ToolRouter`
so the wire-up (``action_id`` → Python fallback) is exercised end-to-end.
No DPG context is required — themes are constructed directly and layouts
travel through ``EditorLayout`` mocks so the suite is fully headless.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pharos_editor.tool_router import (
    REGISTRY,
    ToolRouter,
    register_default_actions,
)


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def router() -> ToolRouter:
    """A router seeded with the canonical action registry."""
    r = ToolRouter()
    register_default_actions(r)
    return r


@pytest.fixture(autouse=True)
def _reset_theme_registry() -> None:
    """Drop the process-wide theme registry between tests."""
    from pharos_editor.ui.theme import _reset_registry_for_tests
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


def _make_theme(name: str = "bb1_test"):
    """Build a minimal :class:`ThemeSpec` for round-trip tests."""
    from pharos_editor.ui.theme import (
        Color,
        Gradient,
        SemanticTokens,
        ThemeSpec,
    )
    ink = Color(50, 50, 60, 1.0)
    primary = Color(122, 100, 168, 1.0)
    accent = Color(240, 180, 90, 1.0)
    background = Color(248, 244, 233, 1.0)
    semantic = SemanticTokens(
        primary=primary,
        primary_gradient=Gradient(
            start=primary, end=ink, angle_deg=135.0,
        ),
        secondary=primary,
        accent=accent,
        background=background,
        surface=background,
        surface_hover=Color(231, 221, 241, 1.0),
        border=Color(184, 176, 160, 1.0),
        text_primary=ink,
        text_secondary=Color(59, 59, 69, 1.0),
        text_disabled=Color(177, 172, 184, 1.0),
        success=Color(91, 193, 138, 1.0),
        warning=Color(242, 187, 85, 1.0),
        error=Color(232, 90, 108, 1.0),
        info=Color(127, 200, 232, 1.0),
        focus_ring=primary,
        glass_bg=background,
        glass_blur_px=12.0,
    )
    return ThemeSpec(name=name, semantic=semantic)


def _make_layout(theme: str = "bb1_test") -> Any:
    """Build a minimal :class:`EditorLayout` snapshot."""
    from pharos_editor.ui.editor.layout_persistence import (
        EditorLayout,
        PanelLayoutState,
        SCHEMA_VERSION,
    )
    panels = {
        "notebook_outliner": PanelLayoutState(
            panel_id="notebook_outliner",
            position=(0, 80),
            size=(260, 480),
            visible=True,
            z_order=0,
            docked_to="left",
        ),
        "notebook_inspector": PanelLayoutState(
            panel_id="notebook_inspector",
            position=(1000, 80),
            size=(280, 480),
            visible=True,
            z_order=1,
            docked_to="right",
        ),
    }
    return EditorLayout(
        schema_version=SCHEMA_VERSION,
        theme=theme,
        viewport_size=(1280, 800),
        panels=panels,
    )


# ---------------------------------------------------------------------------
# Router registration checks (5 tests)
# ---------------------------------------------------------------------------


class TestRegistration:
    """Confirm the 5 BB1 action ids are on the canonical router."""

    def test_theme_import_from_file_registered(self, router: ToolRouter) -> None:
        assert router.has_action("theme.import_from_file")

    def test_file_save_layout_as_registered(self, router: ToolRouter) -> None:
        assert router.has_action("file.save_layout_as")

    def test_file_load_layout_from_file_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("file.load_layout_from_file")

    def test_edit_undo_registered(self, router: ToolRouter) -> None:
        assert router.has_action("edit.undo")

    def test_edit_redo_registered(self, router: ToolRouter) -> None:
        assert router.has_action("edit.redo")

    def test_all_bb1_on_module_singleton(self) -> None:
        for aid in (
            "theme.import_from_file",
            "file.save_layout_as",
            "file.load_layout_from_file",
            "edit.undo",
            "edit.redo",
        ):
            assert REGISTRY.has_action(aid), aid


# ---------------------------------------------------------------------------
# theme.import_from_file (7 tests)
# ---------------------------------------------------------------------------


class TestThemeImport:
    """Cover the theme.import_from_file wiring."""

    def test_import_registers_and_activates(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        theme = _make_theme("imported_alpha")
        path = tmp_path / "imported_alpha.theme.yaml"
        path.write_text(theme.to_yaml(), encoding="utf-8")

        result = router.dispatch(
            "theme.import_from_file",
            {"path": str(path)},
        )
        assert result["status"] == "imported"
        assert result["theme"] == "imported_alpha"
        assert result["activated"] is True

        from pharos_editor.ui.theme import (
            get_active_theme,
            list_registered_themes,
        )
        assert "imported_alpha" in list_registered_themes()
        assert get_active_theme().name == "imported_alpha"

    def test_import_without_activate(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        theme = _make_theme("registered_only")
        path = tmp_path / "registered_only.theme.yaml"
        path.write_text(theme.to_yaml(), encoding="utf-8")

        result = router.dispatch(
            "theme.import_from_file",
            {"path": str(path), "activate": False},
        )
        assert result["status"] == "imported"
        assert result["activated"] is False

        from pharos_editor.ui.theme import list_registered_themes
        assert "registered_only" in list_registered_themes()

    def test_import_missing_file(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        ghost = tmp_path / "nope.theme.yaml"
        result = router.dispatch(
            "theme.import_from_file",
            {"path": str(ghost)},
        )
        assert result["status"] == "missing"
        assert result["path"] == str(ghost)

    def test_import_no_path_no_shell(self, router: ToolRouter) -> None:
        result = router.dispatch("theme.import_from_file", {})
        assert result["status"] == "no_path"

    def test_import_css_unsupported(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        path = tmp_path / "old.theme.css"
        path.write_text("/* css theme */", encoding="utf-8")
        result = router.dispatch(
            "theme.import_from_file",
            {"path": str(path)},
        )
        assert result["status"] == "unsupported"
        assert result["format"] == "css"

    def test_import_unknown_extension(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        path = tmp_path / "junk.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        result = router.dispatch(
            "theme.import_from_file",
            {"path": str(path)},
        )
        assert result["status"] == "unsupported"

    def test_import_malformed_yaml(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        path = tmp_path / "bad.theme.yaml"
        path.write_text("name: [unclosed", encoding="utf-8")
        result = router.dispatch(
            "theme.import_from_file",
            {"path": str(path)},
        )
        assert result["status"] == "error"
        assert "message" in result

    def test_import_prompt_hook_invoked(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        theme = _make_theme("via_prompt")
        path = tmp_path / "via_prompt.theme.yaml"
        path.write_text(theme.to_yaml(), encoding="utf-8")

        picked: list[str] = []

        def prompt_open_path(default_ext: str) -> str:
            picked.append(default_ext)
            return str(path)

        shell = SimpleNamespace(prompt_open_path=prompt_open_path)
        result = router.dispatch(
            "theme.import_from_file",
            {"shell": shell},
        )
        assert result["status"] == "imported"
        assert picked == [".theme.yaml"]


# ---------------------------------------------------------------------------
# file.save_layout_as (5 tests)
# ---------------------------------------------------------------------------


class TestSaveLayoutAs:
    """Cover the file.save_layout_as wiring."""

    def test_save_writes_valid_yaml(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        layout = _make_layout("teengirl_notebook")
        path = tmp_path / "combat.layout.yaml"
        result = router.dispatch(
            "file.save_layout_as",
            {"layout": layout, "path": str(path)},
        )
        assert result["status"] == "saved"
        assert result["path"] == str(path)
        assert result["size_bytes"] > 0
        assert path.is_file()

        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["theme"] == "teengirl_notebook"
        assert data["schema_version"] == 1

    def test_save_no_layout_no_shell(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        result = router.dispatch(
            "file.save_layout_as",
            {"path": str(tmp_path / "x.layout.yaml")},
        )
        assert result["status"] == "no_layout"

    def test_save_no_path_no_prompter(
        self, router: ToolRouter,
    ) -> None:
        layout = _make_layout()
        result = router.dispatch(
            "file.save_layout_as",
            {"layout": layout},
        )
        assert result["status"] == "no_path"

    def test_save_prompt_hook_default_name(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        layout = _make_layout()
        seen: list[str] = []

        def prompt_save_path(default_name: str) -> str:
            seen.append(default_name)
            return str(tmp_path / default_name)

        shell = SimpleNamespace(prompt_save_path=prompt_save_path)
        result = router.dispatch(
            "file.save_layout_as",
            {"layout": layout, "shell": shell},
        )
        assert result["status"] == "saved"
        assert seen == ["layout.layout.yaml"]

    def test_save_atomic_no_partial_file(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        layout = _make_layout()
        path = tmp_path / "atomic.layout.yaml"
        result = router.dispatch(
            "file.save_layout_as",
            {"layout": layout, "path": str(path)},
        )
        assert result["status"] == "saved"
        # No leftover .tmp siblings.
        stragglers = [
            p for p in tmp_path.iterdir()
            if p.suffix == ".tmp"
        ]
        assert stragglers == []


# ---------------------------------------------------------------------------
# file.load_layout_from_file (5 tests)
# ---------------------------------------------------------------------------


class TestLoadLayoutFromFile:
    """Cover the file.load_layout_from_file wiring."""

    def test_load_round_trip(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        layout = _make_layout("bb1_theme")
        path = tmp_path / "roundtrip.layout.yaml"
        router.dispatch(
            "file.save_layout_as",
            {"layout": layout, "path": str(path)},
        )
        result = router.dispatch(
            "file.load_layout_from_file",
            {"path": str(path)},
        )
        assert result["status"] == "loaded"
        assert result["theme"] == "bb1_theme"
        assert result["panel_count"] == 2
        assert result["applied"] is False  # no shell

    def test_load_no_path_no_shell(self, router: ToolRouter) -> None:
        result = router.dispatch("file.load_layout_from_file", {})
        assert result["status"] == "no_path"

    def test_load_missing_file(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        result = router.dispatch(
            "file.load_layout_from_file",
            {"path": str(tmp_path / "ghost.layout.yaml")},
        )
        assert result["status"] == "missing"

    def test_load_malformed_yaml(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        path = tmp_path / "bad.layout.yaml"
        path.write_text("just a string, not a dict", encoding="utf-8")
        result = router.dispatch(
            "file.load_layout_from_file",
            {"path": str(path)},
        )
        assert result["status"] == "malformed"

    def test_load_wrong_schema_version(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        import yaml
        path = tmp_path / "future.layout.yaml"
        path.write_text(
            yaml.safe_dump(
                {"schema_version": 99, "theme": "x", "panels": {}},
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        result = router.dispatch(
            "file.load_layout_from_file",
            {"path": str(path)},
        )
        assert result["status"] == "malformed"

    def test_load_applies_to_shell(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        layout = _make_layout("applied_theme")
        path = tmp_path / "apply.layout.yaml"
        router.dispatch(
            "file.save_layout_as",
            {"layout": layout, "path": str(path)},
        )
        shell = SimpleNamespace(
            _width=1280,
            _height=800,
            _ui_settings=SimpleNamespace(default_theme="old"),
        )
        result = router.dispatch(
            "file.load_layout_from_file",
            {"path": str(path), "shell": shell},
        )
        assert result["status"] == "loaded"
        assert result["applied"] is True
        # The persistence layer stashes the layout on the shell.
        assert getattr(shell, "_layout_state", None) is not None


# ---------------------------------------------------------------------------
# edit.undo / edit.redo (10 tests)
# ---------------------------------------------------------------------------


class TestEditUndoRedo:
    """Cover the edit.undo / edit.redo wiring."""

    def _stack_with_entry(self, sink: list[str]):
        from pharos_editor.ui.editor.editor_undo import UndoStack
        stack = UndoStack(capacity=8)
        stack.push(
            "test.mutate",
            forward=lambda: sink.append("F"),
            reverse=lambda: sink.append("R"),
            label="Mutate Thing",
        )
        return stack

    def test_undo_reverses_entry(self, router: ToolRouter) -> None:
        sink: list[str] = []
        stack = self._stack_with_entry(sink)
        result = router.dispatch("edit.undo", {"stack": stack})
        assert result["status"] == "undone"
        assert result["action_id"] == "test.mutate"
        assert result["label"] == "Mutate Thing"
        assert sink == ["R"]
        assert result["undo_depth"] == 0
        assert result["redo_depth"] == 1

    def test_redo_reapplies_entry(self, router: ToolRouter) -> None:
        sink: list[str] = []
        stack = self._stack_with_entry(sink)
        router.dispatch("edit.undo", {"stack": stack})
        result = router.dispatch("edit.redo", {"stack": stack})
        assert result["status"] == "redone"
        assert sink == ["R", "F"]
        assert result["undo_depth"] == 1
        assert result["redo_depth"] == 0

    def test_undo_empty_stack(self, router: ToolRouter) -> None:
        from pharos_editor.ui.editor.editor_undo import UndoStack
        stack = UndoStack()
        result = router.dispatch("edit.undo", {"stack": stack})
        assert result["status"] == "empty"

    def test_redo_empty_stack(self, router: ToolRouter) -> None:
        from pharos_editor.ui.editor.editor_undo import UndoStack
        stack = UndoStack()
        result = router.dispatch("edit.redo", {"stack": stack})
        assert result["status"] == "empty"

    def test_undo_no_shell_no_stack(self, router: ToolRouter) -> None:
        result = router.dispatch("edit.undo", {})
        assert result["status"] == "no_stack"

    def test_redo_no_shell_no_stack(self, router: ToolRouter) -> None:
        result = router.dispatch("edit.redo", {})
        assert result["status"] == "no_stack"

    def test_undo_via_shell_direct(self, router: ToolRouter) -> None:
        sink: list[str] = []
        stack = self._stack_with_entry(sink)
        shell = SimpleNamespace(_undo_stack=stack)
        result = router.dispatch("edit.undo", {"shell": shell})
        assert result["status"] == "undone"
        assert sink == ["R"]

    def test_redo_via_shell_engine_legacy(self, router: ToolRouter) -> None:
        sink: list[str] = []
        stack = self._stack_with_entry(sink)
        # Legacy path — engine holds the stack under _undo_manager.
        engine = SimpleNamespace(_undo_manager=stack)
        shell = SimpleNamespace(_engine=engine)
        router.dispatch("edit.undo", {"shell": shell})
        result = router.dispatch("edit.redo", {"shell": shell})
        assert result["status"] == "redone"

    def test_undo_multiple_entries(self, router: ToolRouter) -> None:
        from pharos_editor.ui.editor.editor_undo import UndoStack
        stack = UndoStack()
        stack.push("a", lambda: None, lambda: None, label="A")
        stack.push("b", lambda: None, lambda: None, label="B")
        result = router.dispatch("edit.undo", {"stack": stack})
        assert result["action_id"] == "b"
        assert result["undo_depth"] == 1
        assert result["redo_depth"] == 1

    def test_undo_redo_action_ids_are_distinct(
        self, router: ToolRouter,
    ) -> None:
        # Sanity: the BB1 pair must not collide with the legacy
        # editor.undo / editor.redo router entries.
        assert router.has_action("edit.undo")
        assert router.has_action("editor.undo")
        assert router.has_action("edit.redo")
        assert router.has_action("editor.redo")
        # And they route to different fallbacks.
        legacy_u = router.get("editor.undo")
        new_u = router.get("edit.undo")
        assert legacy_u.python_fallback is not new_u.python_fallback


# ---------------------------------------------------------------------------
# Round-trip integration test
# ---------------------------------------------------------------------------


class TestBB1RoundTrip:
    """End-to-end: export theme, then import it back."""

    def test_theme_export_then_import(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        theme = _make_theme("roundtripper")
        from pharos_editor.ui.theme import apply_theme, register_theme
        register_theme(theme)
        apply_theme("roundtripper")

        path = tmp_path / "roundtripper.theme.yaml"
        export = router.dispatch(
            "theme.export_current",
            {"path": str(path)},
        )
        assert export["status"] == "exported"

        from pharos_editor.ui.theme import _reset_registry_for_tests
        _reset_registry_for_tests()

        import_result = router.dispatch(
            "theme.import_from_file",
            {"path": str(path)},
        )
        assert import_result["status"] == "imported"
        assert import_result["theme"] == "roundtripper"

    def test_layout_save_then_load(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        original = _make_layout("integration_theme")
        path = tmp_path / "roundtrip.layout.yaml"
        router.dispatch(
            "file.save_layout_as",
            {"layout": original, "path": str(path)},
        )
        loaded = router.dispatch(
            "file.load_layout_from_file",
            {"path": str(path)},
        )
        assert loaded["status"] == "loaded"
        assert loaded["theme"] == "integration_theme"
        assert loaded["panel_count"] == 2
