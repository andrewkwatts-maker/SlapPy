"""Tests for :meth:`EditorShell._render_drag_overlay`.

The overlay paints snap guide lines and dock-zone preview rectangles on
a viewport drawlist while the user drags a panel. The shell's render
method is headless-safe — every DPG call is wrapped in ``try/except`` —
so we exercise it by stubbing ``dearpygui.dearpygui`` with a recording
``ModuleType`` and asserting the recorded calls match the snap +
dock manager state. No live Dear PyGui context is required.
"""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from pharos_engine.ui.editor.dock_zones import DockZone
from pharos_engine.ui.editor.snap_manager import SnapTarget


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_shell():
    """Build an :class:`EditorShell` with a minimal engine stub."""
    from pharos_engine.ui.editor.shell import EditorShell

    class _StubEngine:
        def __init__(self):
            self.scene = None

    return EditorShell(_StubEngine(), width=1280, height=720)


class _DpgRecorder(types.ModuleType):
    """Recording stand-in for the ``dearpygui.dearpygui`` module.

    Records every API call so tests can assert on what
    :meth:`EditorShell._render_drag_overlay` emitted without needing
    a live Dear PyGui context.
    """

    def __init__(self) -> None:
        super().__init__("dearpygui.dearpygui")
        self.calls: list[tuple[str, dict[str, Any]]] = []
        # Items the recorder pretends already exist; the overlay only
        # creates the drawlist when it isn't here yet.
        self._existing: set[str] = set()

    # The methods below are accessed via attribute lookup by the
    # production code (``import dearpygui.dearpygui as dpg``); they
    # all simply log the call.

    def does_item_exist(self, tag: str) -> bool:  # noqa: D401
        self.calls.append(("does_item_exist", {"tag": tag}))
        return tag in self._existing

    def add_viewport_drawlist(self, **kwargs: Any) -> str:
        self.calls.append(("add_viewport_drawlist", kwargs))
        tag = kwargs.get("tag", "vp.drawlist")
        self._existing.add(tag)
        return tag

    def delete_item(self, tag: str, **kwargs: Any) -> None:
        self.calls.append(("delete_item", {"tag": tag, **kwargs}))

    def draw_line(self, **kwargs: Any) -> None:
        self.calls.append(("draw_line", kwargs))

    def draw_rectangle(self, **kwargs: Any) -> None:
        self.calls.append(("draw_rectangle", kwargs))

    # Convenience — list every call name for quick assertions.
    @property
    def names(self) -> list[str]:
        return [n for (n, _) in self.calls]

    def calls_of(self, name: str) -> list[dict[str, Any]]:
        return [kw for (n, kw) in self.calls if n == name]


@pytest.fixture
def dpg_stub(monkeypatch) -> _DpgRecorder:
    """Install a recording DPG stub for the lifetime of one test."""
    rec = _DpgRecorder()
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", rec)
    if "dearpygui" in sys.modules:
        monkeypatch.setattr(
            sys.modules["dearpygui"], "dearpygui", rec, raising=False
        )
    return rec


# ---------------------------------------------------------------------------
# Early-out guards
# ---------------------------------------------------------------------------


def test_render_drag_overlay_returns_early_when_not_running(dpg_stub):
    shell = _make_shell()
    assert shell._running is False
    shell._render_drag_overlay()
    # No DPG calls at all because the method must short-circuit.
    assert dpg_stub.calls == []


def test_render_drag_overlay_returns_early_without_dearpygui(monkeypatch):
    """If ``dearpygui.dearpygui`` import fails, the method must no-op."""
    shell = _make_shell()
    shell._running = True

    # Force the import to fail by injecting a broken module.
    failing = types.ModuleType("dearpygui.dearpygui")

    def _raise(*_a, **_kw):
        raise RuntimeError("no dpg here")

    failing.does_item_exist = _raise
    failing.add_viewport_drawlist = _raise
    failing.delete_item = _raise
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", failing)
    if "dearpygui" in sys.modules:
        monkeypatch.setattr(
            sys.modules["dearpygui"], "dearpygui", failing, raising=False
        )
    # Must not raise.
    shell._render_drag_overlay()


# ---------------------------------------------------------------------------
# Drawlist lifecycle
# ---------------------------------------------------------------------------


def test_ensure_overlay_drawlist_creates_drawlist_on_first_call(dpg_stub):
    shell = _make_shell()
    shell._running = True
    tag = shell._ensure_overlay_drawlist()
    assert tag == shell._OVERLAY_DRAWLIST_TAG
    add_calls = dpg_stub.calls_of("add_viewport_drawlist")
    assert len(add_calls) == 1
    assert add_calls[0].get("front") is True
    assert add_calls[0].get("tag") == shell._OVERLAY_DRAWLIST_TAG


def test_ensure_overlay_drawlist_is_idempotent(dpg_stub):
    shell = _make_shell()
    shell._running = True
    shell._ensure_overlay_drawlist()
    # Second call: drawlist now exists, so no new creation.
    shell._ensure_overlay_drawlist()
    assert len(dpg_stub.calls_of("add_viewport_drawlist")) == 1


def test_render_drag_overlay_clears_children_each_frame(dpg_stub):
    shell = _make_shell()
    shell._running = True
    shell._render_drag_overlay()
    shell._render_drag_overlay()
    delete_calls = dpg_stub.calls_of("delete_item")
    assert len(delete_calls) == 2
    for kw in delete_calls:
        assert kw.get("children_only") is True
        assert kw.get("tag") == shell._OVERLAY_DRAWLIST_TAG


# ---------------------------------------------------------------------------
# Snap guide lines
# ---------------------------------------------------------------------------


def _start_fake_drag(shell, *, ax: int | None, ay: int | None) -> None:
    """Force the SnapManager into a fake-dragging state with given snaps."""
    mgr = shell._snap_manager
    assert mgr is not None
    # Push a panel into the registry so on_drag_start has something
    # to remember (state is otherwise self-contained).
    from dataclasses import dataclass

    @dataclass
    class _P:
        tag: str = "panel.a"
        x: int = 0
        y: int = 0
        width: int = 100
        height: int = 100

    mgr.register_panel(_P())
    mgr.on_drag_start("panel.a")
    # _drag was just built; poke active snap targets directly.
    assert mgr._drag is not None
    mgr._drag.active_x = (
        SnapTarget("x", ax, "viewport_edge") if ax is not None else None
    )
    mgr._drag.active_y = (
        SnapTarget("y", ay, "viewport_edge") if ay is not None else None
    )


def test_render_drag_overlay_draws_vertical_guide_at_active_snap_x(dpg_stub):
    shell = _make_shell()
    shell._running = True
    _start_fake_drag(shell, ax=480, ay=None)

    shell._render_drag_overlay()

    lines = dpg_stub.calls_of("draw_line")
    assert len(lines) == 1
    kw = lines[0]
    assert kw["p1"] == (480, 0)
    assert kw["p2"] == (480, shell._height)


def test_render_drag_overlay_draws_horizontal_guide_at_active_snap_y(dpg_stub):
    shell = _make_shell()
    shell._running = True
    _start_fake_drag(shell, ax=None, ay=360)

    shell._render_drag_overlay()

    lines = dpg_stub.calls_of("draw_line")
    assert len(lines) == 1
    kw = lines[0]
    assert kw["p1"] == (0, 360)
    assert kw["p2"] == (shell._width, 360)


def test_render_drag_overlay_draws_both_guides_when_both_snaps_active(dpg_stub):
    shell = _make_shell()
    shell._running = True
    _start_fake_drag(shell, ax=200, ay=150)

    shell._render_drag_overlay()

    lines = dpg_stub.calls_of("draw_line")
    assert len(lines) == 2
    # First vertical, then horizontal (implementation order).
    assert lines[0]["p1"] == (200, 0)
    assert lines[1]["p1"] == (0, 150)


def test_render_drag_overlay_no_guides_when_not_dragging(dpg_stub):
    shell = _make_shell()
    shell._running = True
    # SnapManager is idle — no on_drag_start called.
    shell._render_drag_overlay()
    assert dpg_stub.calls_of("draw_line") == []


def test_render_drag_overlay_uses_theme_accent_color(dpg_stub, monkeypatch):
    """Guide colour pulls (r, g, b) from theme.semantic.accent at alpha 220."""
    shell = _make_shell()
    shell._running = True
    _start_fake_drag(shell, ax=300, ay=None)

    # Stub the theme accessor on the shell to return a deterministic
    # theme with a known accent colour.
    class _Color:
        def __init__(self, r, g, b):
            self.r, self.g, self.b = r, g, b

    class _Semantic:
        accent = _Color(11, 22, 33)

    class _Theme:
        semantic = _Semantic()

    monkeypatch.setattr(shell, "_get_active_theme", lambda: _Theme())

    shell._render_drag_overlay()

    lines = dpg_stub.calls_of("draw_line")
    assert len(lines) == 1
    assert lines[0]["color"] == (11, 22, 33, 220)


def test_render_drag_overlay_falls_back_when_theme_missing(dpg_stub, monkeypatch):
    """A None / broken theme must not crash — fall back to default pink."""
    shell = _make_shell()
    shell._running = True
    _start_fake_drag(shell, ax=300, ay=None)

    monkeypatch.setattr(shell, "_get_active_theme", lambda: None)

    shell._render_drag_overlay()

    lines = dpg_stub.calls_of("draw_line")
    assert len(lines) == 1
    # Default bubblegum pink per implementation contract.
    assert lines[0]["color"] == (255, 111, 181, 220)


# ---------------------------------------------------------------------------
# Dock zone previews
# ---------------------------------------------------------------------------


def _start_fake_dock(shell, zone: DockZone) -> None:
    """Force the DockZoneManager into an active state at *zone*."""
    dz = shell._dock_zones
    assert dz is not None
    dz._dragging_tag = "panel.a"  # type: ignore[attr-defined]
    dz._active_zone = zone  # type: ignore[attr-defined]


def test_render_drag_overlay_draws_zone_preview_rectangle(dpg_stub):
    shell = _make_shell()
    shell._running = True
    _start_fake_dock(shell, DockZone.LEFT)

    shell._render_drag_overlay()

    rects = dpg_stub.calls_of("draw_rectangle")
    assert len(rects) == 1
    kw = rects[0]
    # LEFT zone is anchored at (0, 0) and spans 25% × 100% of the
    # viewport per :attr:`DockZoneManager.DOCK_ZONE_FRACTION`.
    assert kw["pmin"] == (0, 0)
    expected_w = int(shell._width * 0.25)
    assert kw["pmax"] == (expected_w, shell._height)
    # The fill colour must match the zone's preview tint exactly.
    assert kw["fill"] == kw["color"]


def test_render_drag_overlay_no_rectangle_when_dock_idle(dpg_stub):
    shell = _make_shell()
    shell._running = True
    # DockZoneManager is idle (no on_drag_start called).
    shell._render_drag_overlay()
    assert dpg_stub.calls_of("draw_rectangle") == []


def test_render_drag_overlay_no_rectangle_when_zone_is_none(dpg_stub):
    """is_active=True but current_zone=None → no rectangle drawn."""
    shell = _make_shell()
    shell._running = True
    dz = shell._dock_zones
    assert dz is not None
    dz._dragging_tag = "panel.a"  # type: ignore[attr-defined]
    dz._active_zone = None  # type: ignore[attr-defined]

    shell._render_drag_overlay()

    assert dpg_stub.calls_of("draw_rectangle") == []


def test_render_drag_overlay_draws_correct_zone_among_five(dpg_stub):
    """Only the matching zone rectangle is emitted, never the other four."""
    shell = _make_shell()
    shell._running = True
    _start_fake_dock(shell, DockZone.RIGHT)

    shell._render_drag_overlay()

    rects = dpg_stub.calls_of("draw_rectangle")
    assert len(rects) == 1
    kw = rects[0]
    expected_w = int(shell._width * 0.25)
    assert kw["pmin"] == (shell._width - expected_w, 0)


# ---------------------------------------------------------------------------
# DockZoneManager introspection contract
# ---------------------------------------------------------------------------


def test_dock_zone_manager_is_active_reflects_drag_state():
    from pharos_engine.ui.editor.dock_zones import DockZoneManager

    dz = DockZoneManager((800, 600))
    assert dz.is_active() is False
    dz.on_drag_start("panel.a")
    assert dz.is_active() is True
    dz.on_drag_end("panel.a", None)  # type: ignore[arg-type]
    assert dz.is_active() is False


def test_dock_zone_manager_current_zone_tracks_on_drag_tick():
    from pharos_engine.ui.editor.dock_zones import DockZoneManager

    dz = DockZoneManager((800, 600))
    dz.on_drag_start("panel.a")
    # Cursor at the very left edge → LEFT zone.
    dz.on_drag_tick("panel.a", (5, 300))
    assert dz.current_zone() is DockZone.LEFT
    # Cursor in the centre → CENTER zone.
    dz.on_drag_tick("panel.a", (400, 300))
    assert dz.current_zone() is DockZone.CENTER
