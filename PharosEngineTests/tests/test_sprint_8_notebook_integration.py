"""Sprint 8 shell-wiring integration test.

Proves that `pharos_editor.notebook_integration.install_all(shell)`
correctly binds every Sprint 9 UI polish primitive onto a mock shell.
"""
from __future__ import annotations

import types

import pytest


def _make_mock_shell():
    """Build a minimal shell with attached panel doubles.

    We use plain SimpleNamespace instances so the integration is exercised
    against the real duck-type expectations without needing a live
    DearPyGui context.
    """
    shell = types.SimpleNamespace()
    shell._outliner = types.SimpleNamespace()
    shell._content_browser = types.SimpleNamespace()
    shell._spawn_menu = types.SimpleNamespace()
    shell._inspector = types.SimpleNamespace()
    shell._edit_menu = types.SimpleNamespace(refresh_undo_state=lambda _s: None)
    return shell


def test_install_outliner_binds_context_menu_multiselect_tooltips():
    from pharos_editor.notebook_integration import install_outliner

    shell = _make_mock_shell()
    result = install_outliner(shell)

    assert "context_menu" in result
    assert "multiselect" in result
    assert "tooltips" in result
    # Idempotency — a second install re-uses the existing bindings.
    result2 = install_outliner(shell)
    assert result2["context_menu"] is result["context_menu"]
    assert result2["multiselect"] is result["multiselect"]


def test_install_content_browser_binds_breadcrumbs(tmp_path):
    from pharos_editor.notebook_integration import install_content_browser

    shell = _make_mock_shell()
    bc = install_content_browser(shell, project_root=tmp_path)
    assert bc is not None
    assert getattr(shell._content_browser, "_breadcrumbs", None) is bc


def test_install_spawn_menu_binds_recent_spawns():
    from pharos_editor.notebook_integration import install_spawn_menu

    shell = _make_mock_shell()
    recent = install_spawn_menu(shell, project="test-project")
    assert recent is not None
    assert getattr(shell._spawn_menu, "_recent", None) is recent


def test_install_inspector_binds_clipboard():
    from pharos_editor.clipboard import Clipboard
    from pharos_editor.notebook_integration import install_inspector

    shell = _make_mock_shell()
    result = install_inspector(shell)
    assert result is Clipboard
    assert getattr(shell._inspector, "_clipboard", None) is Clipboard


def test_install_hotkeys_registers_expected_keymap():
    from pharos_editor.notebook_integration import install_hotkeys

    shell = _make_mock_shell()
    keymap = install_hotkeys(shell)
    for k in ("Ctrl+Z", "Ctrl+Shift+Z", "Ctrl+C", "Ctrl+V"):
        assert k in keymap
    # CommandStack must be attached.
    assert getattr(shell, "_command_stack", None) is not None


def test_install_all_returns_full_binding_map(tmp_path):
    from pharos_editor.notebook_integration import install_all

    shell = _make_mock_shell()
    bound = install_all(shell, project="p", project_root=tmp_path)
    for key in ("outliner", "content_browser", "spawn_menu", "inspector", "hotkeys"):
        assert key in bound
    assert bound["outliner"]["multiselect"] is not None


def test_install_all_tolerates_missing_panels():
    """A shell with only some panels attached still installs the rest."""
    from pharos_editor.notebook_integration import install_all

    partial = types.SimpleNamespace()
    partial._outliner = types.SimpleNamespace()
    bound = install_all(partial)
    assert bound["outliner"]  # outliner installed
    assert bound["content_browser"] is None
    assert bound["hotkeys"]  # hotkeys install even without panels
