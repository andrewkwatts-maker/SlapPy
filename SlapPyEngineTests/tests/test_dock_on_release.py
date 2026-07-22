"""End-to-end tests for the dock-on-release flow.

These tests exercise the full lifecycle wired by the editor shell:
:class:`MovablePanelWindow` (which now exposes ``set_bounds`` and
``docked_to``) being repositioned + resized by :class:`DockZoneManager`
when a drag ends inside a dock zone, plus the viewport-resize hook the
shell calls when the OS reports a window resize.

Previously the shell handed ``None`` to ``on_drag_end`` so the dock
action computed the right bounds but never applied them. The fix
threads the actual :class:`MovablePanelWindow` through and remembers
which zone it ended up in via ``docked_to`` so future viewport resizes
can re-snap it.

All tests run headlessly — no ``dearpygui`` context required.
"""
from __future__ import annotations

import pytest

from pharos_editor.ui.editor.dock_zones import DockZone, DockZoneManager
from pharos_editor.ui.editor.movable_panel import MovablePanelWindow


VIEWPORT_W = 1600
VIEWPORT_H = 900


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _Panel:
    """Trivial panel object satisfying ``MovablePanelWindow``'s contract."""

    def build(self, parent_tag) -> None:  # noqa: D401
        pass


def _make_window(
    *, default_pos: tuple[int, int] = (100, 100),
    default_size: tuple[int, int] = (300, 200),
    min_size: tuple[int, int] = (50, 50),
    tag: str | None = None,
) -> MovablePanelWindow:
    return MovablePanelWindow(
        _Panel(),
        default_pos=default_pos,
        default_size=default_size,
        min_size=min_size,
        kind="sidebar",
        window_tag=tag,
    )


@pytest.fixture
def manager() -> DockZoneManager:
    return DockZoneManager((VIEWPORT_W, VIEWPORT_H))


# ---------------------------------------------------------------------------
# Per-zone dock-on-release
# ---------------------------------------------------------------------------


def test_dock_left_repositions_and_resizes(manager: DockZoneManager) -> None:
    """Drop in LEFT → panel at (0, 0) sized 25% × full viewport height."""
    win = _make_window(tag="left.panel", default_pos=(800, 400))
    manager.on_drag_start(win.get_window_tag())
    manager.on_drag_tick(win.get_window_tag(), (10, VIEWPORT_H // 2))
    resolved = manager.on_drag_end(win.get_window_tag(), win)
    assert resolved is DockZone.LEFT
    assert win.get_position() == (0, 0)
    assert win.get_size() == (
        int(VIEWPORT_W * DockZoneManager.DOCK_ZONE_FRACTION),
        VIEWPORT_H,
    )


def test_dock_right_repositions_and_resizes(manager: DockZoneManager) -> None:
    win = _make_window(tag="right.panel")
    manager.on_drag_start(win.get_window_tag())
    manager.on_drag_tick(
        win.get_window_tag(), (VIEWPORT_W - 5, VIEWPORT_H // 2)
    )
    resolved = manager.on_drag_end(win.get_window_tag(), win)
    assert resolved is DockZone.RIGHT
    expected_w = int(VIEWPORT_W * DockZoneManager.DOCK_ZONE_FRACTION)
    assert win.get_position() == (VIEWPORT_W - expected_w, 0)
    assert win.get_size() == (expected_w, VIEWPORT_H)


def test_dock_top_repositions_and_resizes(manager: DockZoneManager) -> None:
    win = _make_window(tag="top.panel")
    manager.on_drag_start(win.get_window_tag())
    manager.on_drag_tick(win.get_window_tag(), (VIEWPORT_W // 2, 8))
    resolved = manager.on_drag_end(win.get_window_tag(), win)
    assert resolved is DockZone.TOP
    expected_h = int(VIEWPORT_H * DockZoneManager.DOCK_ZONE_FRACTION)
    assert win.get_position() == (0, 0)
    assert win.get_size() == (VIEWPORT_W, expected_h)


def test_dock_bottom_repositions_to_three_quarter_y(
    manager: DockZoneManager,
) -> None:
    """Bottom dock y == viewport_h * (1 - DOCK_ZONE_FRACTION) == 75% of h."""
    win = _make_window(tag="bottom.panel")
    manager.on_drag_start(win.get_window_tag())
    manager.on_drag_tick(
        win.get_window_tag(), (VIEWPORT_W // 2, VIEWPORT_H - 4)
    )
    resolved = manager.on_drag_end(win.get_window_tag(), win)
    assert resolved is DockZone.BOTTOM
    expected_h = int(VIEWPORT_H * DockZoneManager.DOCK_ZONE_FRACTION)
    expected_y = VIEWPORT_H - expected_h
    # With DOCK_ZONE_FRACTION = 0.25 and viewport 900px that's 675 = 75% × 900.
    assert expected_y == int(VIEWPORT_H * 0.75)
    assert win.get_position() == (0, expected_y)
    assert win.get_size() == (VIEWPORT_W, expected_h)


def test_dock_center_uses_60_percent_box(manager: DockZoneManager) -> None:
    """CENTER docks to a tighter 60% × 60% rectangle centred in the viewport."""
    win = _make_window(tag="center.panel")
    manager.on_drag_start(win.get_window_tag())
    manager.on_drag_tick(
        win.get_window_tag(), (VIEWPORT_W // 2, VIEWPORT_H // 2)
    )
    resolved = manager.on_drag_end(win.get_window_tag(), win)
    assert resolved is DockZone.CENTER
    expected_w = int(VIEWPORT_W * DockZoneManager.CENTER_DOCK_FRACTION)
    expected_h = int(VIEWPORT_H * DockZoneManager.CENTER_DOCK_FRACTION)
    assert win.get_size() == (expected_w, expected_h)
    assert win.get_position() == (
        (VIEWPORT_W - expected_w) // 2,
        (VIEWPORT_H - expected_h) // 2,
    )


# ---------------------------------------------------------------------------
# Floating drop
# ---------------------------------------------------------------------------


def test_floating_drop_leaves_panel_in_place(manager: DockZoneManager) -> None:
    """Dropping outside any zone leaves the panel where the user released it."""
    win = _make_window(tag="float.panel", default_pos=(450, 320))
    manager.on_drag_start(win.get_window_tag())
    manager.on_drag_tick(win.get_window_tag(), (-50, -50))  # FLOATING
    resolved = manager.on_drag_end(win.get_window_tag(), win)
    assert resolved is DockZone.FLOATING
    # Position + size untouched.
    assert win.get_position() == (450, 320)
    assert win.get_size() == (300, 200)


def test_floating_drop_clears_docked_to(manager: DockZoneManager) -> None:
    win = _make_window(tag="float2.panel")
    win.docked_to = "left"  # simulate a stale prior dock
    manager.on_drag_start(win.get_window_tag())
    manager.on_drag_tick(win.get_window_tag(), (-100, -100))
    manager.on_drag_end(win.get_window_tag(), win)
    assert win.docked_to is None


# ---------------------------------------------------------------------------
# docked_to bookkeeping
# ---------------------------------------------------------------------------


def test_docked_to_records_zone_name(manager: DockZoneManager) -> None:
    win = _make_window(tag="dt.panel")
    assert win.docked_to is None
    manager.on_drag_start(win.get_window_tag())
    manager.on_drag_tick(win.get_window_tag(), (5, VIEWPORT_H // 2))
    manager.on_drag_end(win.get_window_tag(), win)
    assert win.docked_to == "left"


def test_docked_to_overwritten_on_redock(manager: DockZoneManager) -> None:
    """Drop LEFT then RIGHT → docked_to flips to ``right``."""
    win = _make_window(tag="multi.panel")

    manager.on_drag_start(win.get_window_tag())
    manager.on_drag_tick(win.get_window_tag(), (5, VIEWPORT_H // 2))
    manager.on_drag_end(win.get_window_tag(), win)
    assert win.docked_to == "left"
    left_pos, left_size = win.get_position(), win.get_size()

    # Re-drag and drop on the right.
    manager.on_drag_start(win.get_window_tag())
    manager.on_drag_tick(
        win.get_window_tag(), (VIEWPORT_W - 5, VIEWPORT_H // 2)
    )
    manager.on_drag_end(win.get_window_tag(), win)
    assert win.docked_to == "right"
    # Geometry actually moved off the left edge.
    assert win.get_position() != left_pos
    # Size is still the edge-dock size (same width as before, just on the
    # right) but the y-anchor matches the new zone.
    expected_w = int(VIEWPORT_W * DockZoneManager.DOCK_ZONE_FRACTION)
    assert win.get_size() == (expected_w, VIEWPORT_H)
    assert win.get_position()[0] == VIEWPORT_W - expected_w


# ---------------------------------------------------------------------------
# Viewport resize follow-through
# ---------------------------------------------------------------------------


def test_viewport_resize_updates_docked_panel(
    manager: DockZoneManager,
) -> None:
    """After dock, shrinking the viewport repositions the docked panel."""
    win = _make_window(tag="resize.left", min_size=(50, 50))
    manager.on_drag_start(win.get_window_tag())
    manager.on_drag_tick(win.get_window_tag(), (5, VIEWPORT_H // 2))
    manager.on_drag_end(win.get_window_tag(), win)
    # Now shrink the viewport.
    manager.update_viewport_size((800, 600))
    assert manager.redock_panel(win) is True
    assert win.get_size() == (
        int(800 * DockZoneManager.DOCK_ZONE_FRACTION),
        600,
    )
    assert win.get_position() == (0, 0)


def test_viewport_resize_leaves_floating_panels_alone(
    manager: DockZoneManager,
) -> None:
    """A panel that was never docked keeps its position on viewport resize."""
    win = _make_window(tag="resize.float", default_pos=(450, 320))
    # No drag → no dock slot.
    assert win.docked_to is None
    manager.update_viewport_size((800, 600))
    redocked = manager.redock_panel(win)
    assert redocked is False
    assert win.get_position() == (450, 320)
    assert win.get_size() == (300, 200)


# ---------------------------------------------------------------------------
# Shell integration — `_find_window_by_tag` + dock-end wiring
# ---------------------------------------------------------------------------


def _make_shell_with_panels(*windows: MovablePanelWindow):
    """Build an :class:`EditorShell` instance and inject *windows*.

    Uses a stub engine so we avoid spinning up the full notebook
    subsystem; the shell only touches ``self._panel_windows`` and
    ``self._dock_zones`` in the code path under test.
    """
    from pharos_editor.ui.editor.shell import EditorShell

    class _StubEngine:
        pass

    shell = EditorShell(
        engine=_StubEngine(), title="t", width=VIEWPORT_W, height=VIEWPORT_H,
    )
    shell._panel_windows = {
        f"p{i}": w for i, w in enumerate(windows)
    }
    return shell


def test_find_window_by_tag_returns_match() -> None:
    a = _make_window(tag="a.panel")
    b = _make_window(tag="b.panel")
    shell = _make_shell_with_panels(a, b)
    assert shell._find_window_by_tag("a.panel") is a
    assert shell._find_window_by_tag("b.panel") is b
    assert shell._find_window_by_tag("missing.panel") is None


def test_on_viewport_resize_redocks_docked_panels() -> None:
    docked = _make_window(tag="docked.panel", min_size=(50, 50))
    floating = _make_window(
        tag="floating.panel", default_pos=(500, 400), min_size=(50, 50),
    )
    shell = _make_shell_with_panels(docked, floating)

    # Dock the first panel to the LEFT zone of the initial viewport.
    dz = shell._dock_zones
    dz.on_drag_start(docked.get_window_tag())
    dz.on_drag_tick(docked.get_window_tag(), (5, VIEWPORT_H // 2))
    dz.on_drag_end(docked.get_window_tag(), docked)
    assert docked.docked_to == "left"

    # OS reports a viewport resize.
    shell.on_viewport_resize(800, 600)
    assert shell._width == 800 and shell._height == 600
    # Docked panel follows the new viewport bounds.
    assert docked.get_size() == (
        int(800 * DockZoneManager.DOCK_ZONE_FRACTION), 600,
    )
    # Floating panel is untouched.
    assert floating.get_position() == (500, 400)
    assert floating.get_size() == (300, 200)


def test_shell_dock_end_threads_real_window_through() -> None:
    """End-to-end: a drag tracked by the shell ends up docked, not no-op."""
    win = _make_window(tag="end.to.end")
    shell = _make_shell_with_panels(win)

    # Simulate the shell mid-drag: tag set, dock manager primed.
    tag = win.get_window_tag()
    shell._actively_dragging = tag
    shell._dock_zones.on_drag_start(tag)
    shell._dock_zones.on_drag_tick(tag, (5, VIEWPORT_H // 2))

    # Now mimic the "drag ended" branch of _tick_panel_drag without
    # spinning up DPG — directly call on_drag_end through the same
    # helper the shell uses.
    shell._dock_zones.on_drag_end(tag, shell._find_window_by_tag(tag))
    assert win.docked_to == "left"
    expected_w = int(VIEWPORT_W * DockZoneManager.DOCK_ZONE_FRACTION)
    assert win.get_size() == (expected_w, VIEWPORT_H)
    assert win.get_position() == (0, 0)
