"""Tests for Nova3D-legacy panels in ``EditorShell.compose_default_panel_layout``.

The 4 legacy-named panels (:class:`LayerPanel`, :class:`ViewportPanel`,
:class:`TagPainter`, :class:`BehaviorPanel`) are wrapped in
:class:`MovablePanelWindow` so they get the same docking, snap, and
theme behaviour as the notebook stack. These tests pin:

* construction — each wrapper appears (or doesn't) in the dict
  returned by ``compose_default_panel_layout``,
* visibility defaults — viewport visible, the rest hidden,
* close affordance — viewport is non-closable,
* optional-import gating — tag painter / behavior panel only
  materialise when the shell carries an instance, and
* toggle wiring — ``toggle_panel`` flips the wrapper state and the
  viewport toggle is a no-op.
"""
from __future__ import annotations

from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Stub panels — protocol-only, no DPG calls.
# ---------------------------------------------------------------------------


class _StubLayerPanel:
    """Minimal stand-in for :class:`LayerPanel`."""

    def __init__(self) -> None:
        self.builds: list[Any] = []

    def build(self, parent_tag: Any) -> None:
        self.builds.append(parent_tag)


class _StubViewportPanel:
    """Minimal stand-in for :class:`ViewportPanel`."""

    def __init__(self) -> None:
        self.builds: list[Any] = []

    def build(self, parent_tag: Any) -> None:
        self.builds.append(parent_tag)


class _StubTagPainter:
    def __init__(self) -> None:
        self.builds: list[Any] = []

    def build(self, parent_tag: Any) -> None:
        self.builds.append(parent_tag)


class _StubBehaviorPanel:
    def __init__(self) -> None:
        self.builds: list[Any] = []

    def build(self, parent_tag: Any) -> None:
        self.builds.append(parent_tag)


# ---------------------------------------------------------------------------
# Shell fixture — drive ``compose_default_panel_layout`` without DPG.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_theme_registry():
    """Drop the theme registry between tests."""
    from pharos_engine.ui.theme import _reset_registry_for_tests

    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


def _make_shell(*, with_layer: bool = True, with_viewport: bool = True,
                with_tag_painter: bool = True, with_behavior: bool = True):
    """Build an ``EditorShell`` with the chosen subset of legacy panels."""
    from pharos_engine.ui.editor.shell import EditorShell

    class _StubEngine:
        def __init__(self):
            self.scene = None

    shell = EditorShell(_StubEngine())
    shell.setup_theme_subsystem()
    shell.setup_notebook_panels()
    if with_layer:
        shell._layer_panel = _StubLayerPanel()
    if with_viewport:
        shell._viewport_panel = _StubViewportPanel()
    if with_tag_painter:
        shell._tag_painter = _StubTagPainter()
    if with_behavior:
        shell._behavior_panel = _StubBehaviorPanel()
    return shell


# ---------------------------------------------------------------------------
# Wrapper presence
# ---------------------------------------------------------------------------


class TestWrapperPresence:
    def test_layer_panel_wrapper_added(self):
        shell = _make_shell()
        windows = shell.compose_default_panel_layout()
        assert "layer_panel" in windows

    def test_viewport_panel_wrapper_added(self):
        shell = _make_shell()
        windows = shell.compose_default_panel_layout()
        assert "viewport_panel" in windows

    def test_tag_painter_wrapper_added(self):
        shell = _make_shell()
        windows = shell.compose_default_panel_layout()
        assert "tag_painter" in windows

    def test_behavior_panel_wrapper_added(self):
        shell = _make_shell()
        windows = shell.compose_default_panel_layout()
        assert "behavior_panel" in windows

    def test_tag_painter_omitted_when_optional_import_missing(self):
        shell = _make_shell(with_tag_painter=False)
        windows = shell.compose_default_panel_layout()
        assert "tag_painter" not in windows

    def test_behavior_panel_omitted_when_optional_import_missing(self):
        shell = _make_shell(with_behavior=False)
        windows = shell.compose_default_panel_layout()
        assert "behavior_panel" not in windows

    def test_layer_panel_omitted_when_not_wired(self):
        shell = _make_shell(with_layer=False)
        windows = shell.compose_default_panel_layout()
        assert "layer_panel" not in windows

    def test_viewport_panel_omitted_when_not_wired(self):
        shell = _make_shell(with_viewport=False)
        windows = shell.compose_default_panel_layout()
        assert "viewport_panel" not in windows


# ---------------------------------------------------------------------------
# Wrapper kind + close affordance
# ---------------------------------------------------------------------------


class TestWrapperFlags:
    def test_viewport_is_not_closable(self):
        """The viewport must never expose a close button."""
        shell = _make_shell()
        windows = shell.compose_default_panel_layout()
        vp = windows["viewport_panel"]
        assert vp.closable is False

    def test_layer_panel_is_closable(self):
        shell = _make_shell()
        windows = shell.compose_default_panel_layout()
        assert windows["layer_panel"].closable is True

    def test_tag_painter_is_closable(self):
        shell = _make_shell()
        windows = shell.compose_default_panel_layout()
        assert windows["tag_painter"].closable is True

    def test_behavior_panel_is_closable(self):
        shell = _make_shell()
        windows = shell.compose_default_panel_layout()
        assert windows["behavior_panel"].closable is True

    def test_viewport_kind_is_viewport(self):
        shell = _make_shell()
        windows = shell.compose_default_panel_layout()
        assert windows["viewport_panel"].kind == "viewport"

    def test_layer_panel_kind_is_sidebar(self):
        shell = _make_shell()
        windows = shell.compose_default_panel_layout()
        assert windows["layer_panel"].kind == "sidebar"


# ---------------------------------------------------------------------------
# Default visibility
# ---------------------------------------------------------------------------


class TestDefaultVisibility:
    def test_viewport_visible_by_default(self):
        shell = _make_shell()
        windows = shell.compose_default_panel_layout()
        assert windows["viewport_panel"].is_visible() is True

    def test_layer_panel_hidden_by_default(self):
        shell = _make_shell()
        windows = shell.compose_default_panel_layout()
        assert windows["layer_panel"].is_visible() is False

    def test_tag_painter_hidden_by_default(self):
        shell = _make_shell()
        windows = shell.compose_default_panel_layout()
        assert windows["tag_painter"].is_visible() is False

    def test_behavior_panel_hidden_by_default(self):
        shell = _make_shell()
        windows = shell.compose_default_panel_layout()
        assert windows["behavior_panel"].is_visible() is False


# ---------------------------------------------------------------------------
# Toggle hotkey wiring
# ---------------------------------------------------------------------------


class TestToggle:
    def test_toggle_layer_panel_shows_then_hides(self):
        shell = _make_shell()
        shell.compose_default_panel_layout()
        wrapper = shell._panel_windows["layer_panel"]
        assert wrapper.is_visible() is False
        shell.toggle_panel("layer_panel")
        assert wrapper.is_visible() is True
        shell.toggle_panel("layer_panel")
        assert wrapper.is_visible() is False

    def test_toggle_tag_painter_shows_then_hides(self):
        shell = _make_shell()
        shell.compose_default_panel_layout()
        wrapper = shell._panel_windows["tag_painter"]
        assert wrapper.is_visible() is False
        shell.toggle_panel("tag_painter")
        assert wrapper.is_visible() is True
        shell.toggle_panel("tag_painter")
        assert wrapper.is_visible() is False

    def test_toggle_behavior_panel_shows_then_hides(self):
        shell = _make_shell()
        shell.compose_default_panel_layout()
        wrapper = shell._panel_windows["behavior_panel"]
        assert wrapper.is_visible() is False
        shell.toggle_panel("behavior_panel")
        assert wrapper.is_visible() is True
        shell.toggle_panel("behavior_panel")
        assert wrapper.is_visible() is False

    def test_toggle_viewport_is_noop(self):
        """Viewport is always visible — toggle must not hide it."""
        shell = _make_shell()
        shell.compose_default_panel_layout()
        wrapper = shell._panel_windows["viewport_panel"]
        assert wrapper.is_visible() is True
        result = shell.toggle_panel("viewport_panel")
        assert result is True
        assert wrapper.is_visible() is True

    def test_dispatch_toggle_panel_layer_alias(self):
        """``editor.toggle_panel_layer`` resolves to the layer_panel wrapper."""
        shell = _make_shell()
        shell.compose_default_panel_layout()
        wrapper = shell._panel_windows["layer_panel"]
        assert wrapper.is_visible() is False
        shell._dispatch_editor_command("editor.toggle_panel_layer")
        assert wrapper.is_visible() is True

    def test_dispatch_toggle_panel_behavior_alias(self):
        """``editor.toggle_panel_behavior`` resolves to behavior_panel."""
        shell = _make_shell()
        shell.compose_default_panel_layout()
        wrapper = shell._panel_windows["behavior_panel"]
        assert wrapper.is_visible() is False
        shell._dispatch_editor_command("editor.toggle_panel_behavior")
        assert wrapper.is_visible() is True

    def test_dispatch_toggle_panel_tag_painter(self):
        shell = _make_shell()
        shell.compose_default_panel_layout()
        wrapper = shell._panel_windows["tag_painter"]
        assert wrapper.is_visible() is False
        shell._dispatch_editor_command("editor.toggle_panel_tag_painter")
        assert wrapper.is_visible() is True

    def test_dispatch_toggle_panel_viewport_noop(self):
        shell = _make_shell()
        shell.compose_default_panel_layout()
        wrapper = shell._panel_windows["viewport_panel"]
        shell._dispatch_editor_command("editor.toggle_panel_viewport")
        # Still visible.
        assert wrapper.is_visible() is True


# ---------------------------------------------------------------------------
# Shell slot initialisation
# ---------------------------------------------------------------------------


class TestShellSlots:
    def test_init_creates_layer_panel_slot(self):
        from pharos_engine.ui.editor.shell import EditorShell

        class _StubEngine:
            scene = None

        shell = EditorShell(_StubEngine())
        assert hasattr(shell, "_layer_panel")
        assert shell._layer_panel is None

    def test_init_creates_tag_painter_slot(self):
        from pharos_engine.ui.editor.shell import EditorShell

        class _StubEngine:
            scene = None

        shell = EditorShell(_StubEngine())
        assert hasattr(shell, "_tag_painter")
        assert shell._tag_painter is None

    def test_init_creates_behavior_panel_slot(self):
        from pharos_engine.ui.editor.shell import EditorShell

        class _StubEngine:
            scene = None

        shell = EditorShell(_StubEngine())
        assert hasattr(shell, "_behavior_panel")
        assert shell._behavior_panel is None

    def test_init_creates_viewport_panel_slot(self):
        from pharos_engine.ui.editor.shell import EditorShell

        class _StubEngine:
            scene = None

        shell = EditorShell(_StubEngine())
        assert hasattr(shell, "_viewport_panel")
        assert shell._viewport_panel is None
