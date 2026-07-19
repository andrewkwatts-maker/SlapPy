"""Regression tests for the notebook editor's panel-tile layout (BBB1).

The 2026-07-19 user screenshot exposed a stack of layout bugs:

* the Scene panel drifted RIGHT of ``LEFT_W`` and painted on top of
  the centre viewport tabs (min_size clamp exceeded LEFT_W);
* the Toolbar row rendered as a single tall black rectangle because
  its ``MIN_WIDTH=800`` forced the wrapper past the centre column;
* the Viewport panel started at ``LEFT_W + 8`` even though the Scene
  panel was ``LEFT_W + 40`` wide — 32 px of visible overlap;
* the "custom_titlebar" empty group + orphaned "Ready" ``status_bar``
  text painted a garbled strip in the upper-left of ``editor_root``;
* the Content Browser folder tree clipped ``temp_20260719_...`` names
  at 150 px.

This module locks the corrected layout in with introspection-level
assertions against ``EditorShell.compose_default_panel_layout()`` —
every notebook column tiles without overlap, the toolbar wrapper
receives a build call that emits at least four sticker buttons, and
the ``editor_root`` compat shims are marked ``show=False``.
"""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub — shares the shape used by ``test_panel_setup_audit``.
# ---------------------------------------------------------------------------


class _StubCM:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: dict[str, dict[str, Any]] = {}

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items[tag] = dict(kwargs)

    def window(self, *args, **kwargs):
        self._track("window", args, kwargs)
        return _StubCM()

    def group(self, *args, **kwargs):
        self._track("group", args, kwargs)
        return _StubCM()

    def child_window(self, *args, **kwargs):
        self._track("child_window", args, kwargs)
        return _StubCM()

    def configure_item(self, tag, *args, **kwargs):
        self._track("configure_item", (tag,) + args, kwargs)
        if isinstance(tag, str) and tag in self.items:
            self.items[tag].update(kwargs)

    def does_item_exist(self, tag, *args, **kwargs):
        return isinstance(tag, str) and tag in self.items

    def bind_item_theme(self, *args, **kwargs):
        self._track("bind_item_theme", args, kwargs)

    def __getattr__(self, name: str):
        def _noop(*a, **k):
            self._track(name, a, k)
            tag = k.get("tag")
            if isinstance(tag, str):
                self.items.setdefault(tag, dict(k))
            return tag
        return _noop


@pytest.fixture
def stub_dpg(monkeypatch):
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    # Explicit forwarders so getattr(mod, "window") works cleanly.
    for name in (
        "window", "group", "child_window", "configure_item",
        "does_item_exist", "bind_item_theme",
    ):
        setattr(mod, name, getattr(stub, name))
    mod.__getattr__ = lambda name: getattr(stub, name)
    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    return stub


# ---------------------------------------------------------------------------
# Theme registry reset — every EditorShell wires theme listeners.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_theme_registry():
    from slappyengine.ui.theme import _reset_registry_for_tests
    from slappyengine.ui.theme import dpg_bridge
    from slappyengine.ui.widgets import notebook_theme
    from slappyengine.ui.theme.creatures import (
        _reset_default_scheduler_for_tests,
    )

    def _wipe():
        _reset_registry_for_tests()
        notebook_theme._active_theme = None
        notebook_theme._theme_listeners.clear()
        _reset_default_scheduler_for_tests()
        # Cross-test residue: an earlier test may have flipped this
        # to ``True`` without a matching ``False``; leaving it True
        # while our real DPG lacks a context wins access violations
        # from ``_bind_paper_texture``.
        dpg_bridge._DPG_CONTEXT_READY = False

    _wipe()
    yield
    _wipe()


# ---------------------------------------------------------------------------
# Shell factory — mirrors ``test_panel_setup_audit._make_shell``.
# ---------------------------------------------------------------------------


def _make_shell():
    from slappyengine.ui.editor.shell import EditorShell

    class _StubEngine:
        def __init__(self):
            self.scene = None

    return EditorShell(_StubEngine())


def _wire_default_panels(shell):
    shell.setup_theme_subsystem()
    shell.setup_notebook_panels()
    from slappyengine.ui.editor.notebook_content_browser import (
        NotebookContentBrowser,
    )
    shell._content_browser = NotebookContentBrowser(
        on_open_scene=lambda *_: None,
        on_open_script=lambda *_: None,
        on_open_asset=lambda *_: None,
    )
    return shell


# ---------------------------------------------------------------------------
# Rect + no-overlap helper — used by every layout assertion below.
# ---------------------------------------------------------------------------


def _rect(win) -> tuple[int, int, int, int]:
    x, y = win.get_position()
    w, h = win.get_size()
    return (x, y, w, h)


def _rects_overlap(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if ax + aw <= bx or bx + bw <= ax:
        return False
    if ay + ah <= by or by + bh <= ay:
        return False
    return True


# ---------------------------------------------------------------------------
# Layout no-overlap suite
# ---------------------------------------------------------------------------


class TestNoOverlap:
    """The dockable columns must tile — no panel paints over another."""

    _CORE_KEYS = (
        "toolbar",
        "outliner",
        "inspector",
        "viewport_panel",
        "content_browser",
        "status_bar",
    )

    def test_all_core_panels_present(self):
        shell = _wire_default_panels(_make_shell())
        # Register a viewport panel so ``viewport_panel`` shows up.
        shell._viewport_panel = _StubViewport()
        windows = shell.compose_default_panel_layout()
        for key in self._CORE_KEYS:
            assert key in windows, f"missing {key!r} in default layout"

    def test_no_pairwise_overlap_between_core_panels(self):
        shell = _wire_default_panels(_make_shell())
        shell._viewport_panel = _StubViewport()
        windows = shell.compose_default_panel_layout()
        rects = {k: _rect(windows[k]) for k in self._CORE_KEYS}
        offenders: list[tuple[str, str]] = []
        seen = list(rects.items())
        for i, (name_a, ra) in enumerate(seen):
            for name_b, rb in seen[i + 1:]:
                if _rects_overlap(ra, rb):
                    offenders.append((name_a, name_b))
        assert not offenders, (
            f"panels overlap: {offenders}; rects={rects}"
        )

    def test_toolbar_sits_over_center_column_not_scene(self):
        """Toolbar must start at ``LEFT_W`` — not at ``0``."""
        from slappyengine.ui.editor.shell import LEFT_W

        shell = _wire_default_panels(_make_shell())
        windows = shell.compose_default_panel_layout()
        tb = windows["toolbar"]
        x, _ = tb.get_position()
        assert x == LEFT_W, (
            f"toolbar.x={x} but expected LEFT_W={LEFT_W}"
        )

    def test_toolbar_width_does_not_spill_into_inspector(self):
        from slappyengine.ui.editor.shell import LEFT_W, RIGHT_W

        shell = _wire_default_panels(_make_shell())
        windows = shell.compose_default_panel_layout()
        tb = windows["toolbar"]
        x, _ = tb.get_position()
        w, _ = tb.get_size()
        insp = windows["inspector"]
        ix, _ = insp.get_position()
        assert x + w <= ix, (
            f"toolbar right={x + w} spills into inspector.x={ix}"
        )
        assert ix == shell._width - RIGHT_W, (
            f"inspector.x={ix} != viewport_width - RIGHT_W"
        )

    def test_scene_panel_spans_full_sidebar_height(self):
        """Scene panel (Outliner) sits FROM titlebar TO content browser."""
        from slappyengine.ui.editor.shell import LEFT_W

        shell = _wire_default_panels(_make_shell())
        windows = shell.compose_default_panel_layout()
        out = windows["outliner"]
        x, y = out.get_position()
        w, _ = out.get_size()
        assert x == 0
        assert w == LEFT_W, (
            f"outliner.width={w} != LEFT_W={LEFT_W} — the "
            f"min_size clamp is still wider than the constant"
        )
        # y == TITLEBAR_H (28 by constant).
        assert y == 28

    def test_inspector_pinned_to_right_edge(self):
        from slappyengine.ui.editor.shell import RIGHT_W

        shell = _wire_default_panels(_make_shell())
        windows = shell.compose_default_panel_layout()
        insp = windows["inspector"]
        x, _ = insp.get_position()
        w, _ = insp.get_size()
        assert x + w == shell._width, (
            f"inspector right edge={x + w} != viewport width "
            f"{shell._width}"
        )
        assert w == RIGHT_W

    def test_content_browser_full_width_bottom(self):
        shell = _wire_default_panels(_make_shell())
        windows = shell.compose_default_panel_layout()
        cb = windows["content_browser"]
        x, y = cb.get_position()
        w, _ = cb.get_size()
        assert x == 0
        assert w == max(320, shell._width)
        # y == viewport_h - BOTTOM_H - STATUS_H
        assert y == shell._height - 220 - 24


class _StubViewport:
    """Minimal viewport panel — the shell wraps this into ``viewport_panel``."""

    TITLE = "Viewport"

    def build(self, parent_tag) -> None:
        return None


# ---------------------------------------------------------------------------
# Toolbar contents — build must emit at least 4 sticker buttons.
# ---------------------------------------------------------------------------


class TestToolbarContents:
    def test_toolbar_min_width_fits_center_column(self):
        """Toolbar MIN_WIDTH <= centre column width so the sticker
        buttons render instead of being crushed to a single black rect."""
        from slappyengine.ui.editor.notebook_toolbar import NotebookToolbar
        from slappyengine.ui.editor.shell import LEFT_W, RIGHT_W

        shell = _make_shell()
        centre = shell._width - LEFT_W - RIGHT_W
        assert NotebookToolbar.MIN_WIDTH <= centre, (
            f"toolbar MIN_WIDTH={NotebookToolbar.MIN_WIDTH} > "
            f"center_w={centre} — the wrapper will overflow the "
            f"centre column"
        )

    def test_toolbar_build_emits_four_buttons(self, stub_dpg):
        """After ``build()`` the toolbar's parent tag must hold at
        least four widgets — the Select / Move / Rotate / Scale row."""
        from slappyengine.ui.editor.notebook_toolbar import NotebookToolbar

        tb = NotebookToolbar()
        tb.build("toolbar_root")
        # Each sticker button contributes at least one add_button /
        # add_child_window / group call.  We assert that the number
        # of tracked emissions during build is >= 4.
        button_count = 0
        for name in ("add_button", "add_child_window", "group"):
            button_count += len(stub_dpg.calls.get(name, []))
        assert button_count >= 4, (
            f"toolbar build emitted only {button_count} widgets; "
            f"expected >= 4 for the Select/Move/Rotate/Scale row. "
            f"Calls: {list(stub_dpg.calls.keys())}"
        )

    def test_toolbar_has_four_registered_tools(self):
        from slappyengine.ui.editor.notebook_toolbar import NotebookToolbar

        tb = NotebookToolbar()
        assert len(tb.tools) == 4
        ids = {t[0] for t in tb.tools}
        assert ids == {"select", "move", "rotate", "scale"}


# ---------------------------------------------------------------------------
# editor_root compat shims — must be hidden so they don't paint garbage.
# ---------------------------------------------------------------------------


class TestEditorRootShims:
    def test_custom_titlebar_group_is_hidden(self):
        """The compat ``custom_titlebar`` group must be created with
        ``show=False`` so the upper-left of the primary window stays
        empty (Nova3D-era external code still expects the tag)."""
        import inspect

        from slappyengine.ui.editor import shell as shell_mod

        source = inspect.getsource(shell_mod.EditorShell.setup)
        # The tag must be created inside setup...
        assert 'tag="custom_titlebar"' in source
        # ...and every occurrence of it must be paired with ``show=False``.
        # We verify by locating the ``add_group`` call and the four lines
        # around it; a raw ``add_group(tag="custom_titlebar")`` (no show
        # argument) was the regression.
        idx = source.find('tag="custom_titlebar"')
        window = source[max(0, idx - 40): idx + 80]
        assert "show=False" in window, (
            f"custom_titlebar group missing show=False; window: {window!r}"
        )

    def test_status_bar_text_is_hidden(self):
        import inspect

        from slappyengine.ui.editor import shell as shell_mod

        source = inspect.getsource(shell_mod.EditorShell.setup)
        idx = source.find('tag="status_bar"')
        assert idx != -1
        window = source[max(0, idx - 60): idx + 120]
        assert "show=False" in window, (
            f"status_bar text missing show=False; window: {window!r}"
        )
