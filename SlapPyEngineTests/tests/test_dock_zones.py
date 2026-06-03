"""Tests for :mod:`slappyengine.ui.editor.dock_zones`.

The dock zone manager owns three concerns: zone geometry, drag-lifecycle
state, and DPG overlay rendering. The first two are pure Python and the
tests below exercise them deterministically. Rendering is wrapped in
``try/except`` so we only assert it's safe to call without DPG present
(and that a no-op happens on FLOATING).
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from typing import Any

import pytest

from slappyengine.ui.editor.dock_zones import (
    DockZone,
    DockZoneManager,
    DockZoneTarget,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


VIEWPORT_W = 1600
VIEWPORT_H = 900


@pytest.fixture
def manager() -> DockZoneManager:
    return DockZoneManager((VIEWPORT_W, VIEWPORT_H))


@dataclass
class FakePanel:
    """Duck-typed stand-in for the editor's MovablePanelWindow."""

    tag: str = "fake.panel"
    position: tuple[int, int] = (0, 0)
    size: tuple[int, int] = (300, 200)
    bounds_calls: list[tuple[int, int, int, int]] = field(default_factory=list)

    def set_bounds(self, x: int, y: int, w: int, h: int) -> None:
        self.bounds_calls.append((x, y, w, h))
        self.position = (x, y)
        self.size = (w, h)


@dataclass
class PropertyPanel:
    """Panel that only exposes ``position`` / ``size`` (no set_bounds)."""

    position: tuple[int, int] = (10, 10)
    size: tuple[int, int] = (100, 100)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def test_compute_zones_returns_five_targets(manager: DockZoneManager) -> None:
    zones = manager.compute_zones()
    assert len(zones) == 5
    kinds = {z.zone for z in zones}
    assert kinds == {
        DockZone.LEFT,
        DockZone.RIGHT,
        DockZone.TOP,
        DockZone.BOTTOM,
        DockZone.CENTER,
    }


def test_compute_zones_geometry_matches_fractions(
    manager: DockZoneManager,
) -> None:
    by_kind = {z.zone: z for z in manager.compute_zones()}
    expected_zw = int(VIEWPORT_W * DockZoneManager.DOCK_ZONE_FRACTION)
    expected_zh = int(VIEWPORT_H * DockZoneManager.DOCK_ZONE_FRACTION)

    assert by_kind[DockZone.LEFT].bounds == (0, 0, expected_zw, VIEWPORT_H)
    assert by_kind[DockZone.RIGHT].bounds == (
        VIEWPORT_W - expected_zw, 0, expected_zw, VIEWPORT_H,
    )
    assert by_kind[DockZone.TOP].bounds == (0, 0, VIEWPORT_W, expected_zh)
    assert by_kind[DockZone.BOTTOM].bounds == (
        0, VIEWPORT_H - expected_zh, VIEWPORT_W, expected_zh,
    )

    cw = int(VIEWPORT_W * DockZoneManager.CENTER_FRACTION)
    ch = int(VIEWPORT_H * DockZoneManager.CENTER_FRACTION)
    cx = int(VIEWPORT_W * (1.0 - DockZoneManager.CENTER_FRACTION) / 2.0)
    cy = int(VIEWPORT_H * (1.0 - DockZoneManager.CENTER_FRACTION) / 2.0)
    assert by_kind[DockZone.CENTER].bounds == (cx, cy, cw, ch)


def test_zone_at_viewport_center_is_center(manager: DockZoneManager) -> None:
    assert manager.zone_at(
        (VIEWPORT_W // 2, VIEWPORT_H // 2)
    ) is DockZone.CENTER


def test_zone_at_left_edge_is_left(manager: DockZoneManager) -> None:
    assert manager.zone_at((0, VIEWPORT_H // 2)) is DockZone.LEFT


def test_zone_at_right_edge_is_right(manager: DockZoneManager) -> None:
    assert manager.zone_at(
        (VIEWPORT_W - 1, VIEWPORT_H // 2)
    ) is DockZone.RIGHT


def test_zone_at_top_edge_is_top(manager: DockZoneManager) -> None:
    assert manager.zone_at((VIEWPORT_W // 2, 0)) is DockZone.TOP


def test_zone_at_bottom_edge_is_bottom(manager: DockZoneManager) -> None:
    assert manager.zone_at(
        (VIEWPORT_W // 2, VIEWPORT_H - 1)
    ) is DockZone.BOTTOM


def test_zone_at_outside_viewport_is_floating(
    manager: DockZoneManager,
) -> None:
    assert manager.zone_at((-5, VIEWPORT_H // 2)) is DockZone.FLOATING
    assert manager.zone_at(
        (VIEWPORT_W + 10, VIEWPORT_H // 2)
    ) is DockZone.FLOATING
    assert manager.zone_at((VIEWPORT_W // 2, -1)) is DockZone.FLOATING
    assert manager.zone_at(
        (VIEWPORT_W // 2, VIEWPORT_H + 50)
    ) is DockZone.FLOATING


def test_edge_zone_wins_over_center_when_overlapping(
    manager: DockZoneManager,
) -> None:
    # A point near the left edge but still vertically central should
    # resolve to LEFT, not CENTER.
    assert manager.zone_at((10, VIEWPORT_H // 2)) is DockZone.LEFT


# ---------------------------------------------------------------------------
# Drag lifecycle
# ---------------------------------------------------------------------------


def test_on_drag_tick_without_start_returns_none(
    manager: DockZoneManager,
) -> None:
    assert manager.on_drag_tick("ghost.panel", (10, 10)) is None


def test_on_drag_tick_returns_active_zone(
    manager: DockZoneManager,
) -> None:
    manager.on_drag_start("panel.a")
    zone = manager.on_drag_tick("panel.a", (10, VIEWPORT_H // 2))
    assert zone is DockZone.LEFT


def test_on_drag_tick_returns_none_when_floating(
    manager: DockZoneManager,
) -> None:
    manager.on_drag_start("panel.a")
    zone = manager.on_drag_tick("panel.a", (-50, -50))
    assert zone is None


def test_on_drag_end_docks_panel_to_left(manager: DockZoneManager) -> None:
    panel = FakePanel(tag="panel.left")
    manager.on_drag_start(panel.tag)
    manager.on_drag_tick(panel.tag, (5, VIEWPORT_H // 2))
    resolved = manager.on_drag_end(panel.tag, panel)
    assert resolved is DockZone.LEFT
    assert panel.bounds_calls, "set_bounds should have been invoked"
    x, y, w, h = panel.bounds_calls[-1]
    assert (x, y) == (0, 0)
    assert w == int(VIEWPORT_W * DockZoneManager.DOCK_ZONE_FRACTION)
    assert h == VIEWPORT_H


def test_on_drag_end_docks_panel_to_right(manager: DockZoneManager) -> None:
    panel = FakePanel(tag="panel.right")
    manager.on_drag_start(panel.tag)
    manager.on_drag_tick(panel.tag, (VIEWPORT_W - 5, VIEWPORT_H // 2))
    resolved = manager.on_drag_end(panel.tag, panel)
    assert resolved is DockZone.RIGHT
    x, y, w, h = panel.bounds_calls[-1]
    expected_w = int(VIEWPORT_W * DockZoneManager.DOCK_ZONE_FRACTION)
    assert (x, y, w, h) == (
        VIEWPORT_W - expected_w, 0, expected_w, VIEWPORT_H,
    )


def test_on_drag_end_docks_panel_to_top(manager: DockZoneManager) -> None:
    panel = FakePanel(tag="panel.top")
    manager.on_drag_start(panel.tag)
    manager.on_drag_tick(panel.tag, (VIEWPORT_W // 2, 4))
    resolved = manager.on_drag_end(panel.tag, panel)
    assert resolved is DockZone.TOP
    x, y, w, h = panel.bounds_calls[-1]
    expected_h = int(VIEWPORT_H * DockZoneManager.DOCK_ZONE_FRACTION)
    assert (x, y, w, h) == (0, 0, VIEWPORT_W, expected_h)


def test_on_drag_end_docks_panel_to_bottom(manager: DockZoneManager) -> None:
    panel = FakePanel(tag="panel.bottom")
    manager.on_drag_start(panel.tag)
    manager.on_drag_tick(panel.tag, (VIEWPORT_W // 2, VIEWPORT_H - 2))
    resolved = manager.on_drag_end(panel.tag, panel)
    assert resolved is DockZone.BOTTOM
    x, y, w, h = panel.bounds_calls[-1]
    expected_h = int(VIEWPORT_H * DockZoneManager.DOCK_ZONE_FRACTION)
    assert (x, y, w, h) == (
        0, VIEWPORT_H - expected_h, VIEWPORT_W, expected_h,
    )


def test_on_drag_end_docks_panel_to_center(manager: DockZoneManager) -> None:
    panel = FakePanel(tag="panel.center")
    manager.on_drag_start(panel.tag)
    manager.on_drag_tick(panel.tag, (VIEWPORT_W // 2, VIEWPORT_H // 2))
    resolved = manager.on_drag_end(panel.tag, panel)
    assert resolved is DockZone.CENTER
    x, y, w, h = panel.bounds_calls[-1]
    expected_w = int(VIEWPORT_W * DockZoneManager.CENTER_DOCK_FRACTION)
    expected_h = int(VIEWPORT_H * DockZoneManager.CENTER_DOCK_FRACTION)
    assert (w, h) == (expected_w, expected_h)
    assert x == (VIEWPORT_W - expected_w) // 2
    assert y == (VIEWPORT_H - expected_h) // 2


def test_on_drag_end_floating_leaves_panel_untouched(
    manager: DockZoneManager,
) -> None:
    panel = FakePanel(tag="panel.float", position=(123, 45), size=(300, 200))
    manager.on_drag_start(panel.tag)
    manager.on_drag_tick(panel.tag, (-100, -100))
    resolved = manager.on_drag_end(panel.tag, panel)
    assert resolved is DockZone.FLOATING
    assert panel.bounds_calls == []
    assert panel.position == (123, 45)
    assert panel.size == (300, 200)


def test_on_drag_end_with_property_panel(manager: DockZoneManager) -> None:
    # Panels that only expose position/size still get docked correctly.
    panel = PropertyPanel()
    manager.on_drag_start("prop.panel")
    manager.on_drag_tick("prop.panel", (5, VIEWPORT_H // 2))
    resolved = manager.on_drag_end("prop.panel", panel)
    assert resolved is DockZone.LEFT
    assert panel.position == (0, 0)
    assert panel.size == (
        int(VIEWPORT_W * DockZoneManager.DOCK_ZONE_FRACTION),
        VIEWPORT_H,
    )


def test_on_drag_end_without_start_is_safe(
    manager: DockZoneManager,
) -> None:
    panel = FakePanel(tag="orphan")
    resolved = manager.on_drag_end(panel.tag, panel)
    assert resolved is DockZone.FLOATING
    assert panel.bounds_calls == []


def test_on_drag_end_clears_active_state(manager: DockZoneManager) -> None:
    panel = FakePanel(tag="panel.a")
    manager.on_drag_start(panel.tag)
    manager.on_drag_tick(panel.tag, (5, VIEWPORT_H // 2))
    manager.on_drag_end(panel.tag, panel)
    # Subsequent tick (without a fresh start) is rejected.
    assert manager.on_drag_tick(panel.tag, (5, VIEWPORT_H // 2)) is None


# ---------------------------------------------------------------------------
# Viewport resize + theme switch
# ---------------------------------------------------------------------------


def test_update_viewport_size_updates_bounds(
    manager: DockZoneManager,
) -> None:
    manager.update_viewport_size((800, 600))
    assert manager.viewport_size == (800, 600)
    by_kind = {z.zone: z for z in manager.compute_zones()}
    assert by_kind[DockZone.LEFT].bounds == (
        0, 0, int(800 * DockZoneManager.DOCK_ZONE_FRACTION), 600,
    )
    assert by_kind[DockZone.BOTTOM].bounds[3] == int(
        600 * DockZoneManager.DOCK_ZONE_FRACTION
    )


def test_update_viewport_size_repoints_dock_target(
    manager: DockZoneManager,
) -> None:
    manager.update_viewport_size((800, 600))
    panel = FakePanel(tag="panel.r")
    manager.on_drag_start(panel.tag)
    manager.on_drag_tick(panel.tag, (795, 300))
    manager.on_drag_end(panel.tag, panel)
    x, y, w, h = panel.bounds_calls[-1]
    expected_w = int(800 * DockZoneManager.DOCK_ZONE_FRACTION)
    assert (x, y, w, h) == (800 - expected_w, 0, expected_w, 600)


def test_theme_switch_updates_preview_color(
    manager: DockZoneManager, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Swapping the active theme reroutes the next preview's tint."""

    # Active theme path: stub get_active_theme to return a fake theme
    # whose semantic.primary is bright magenta.
    @dataclass
    class _Color:
        r: int
        g: int
        b: int

    @dataclass
    class _Semantic:
        primary: _Color
        accent: _Color

    @dataclass
    class _Theme:
        semantic: _Semantic

    fake_theme = _Theme(
        semantic=_Semantic(
            primary=_Color(255, 0, 128),
            accent=_Color(0, 200, 255),
        )
    )

    from slappyengine.ui.editor import dock_zones as dz_mod

    monkeypatch.setattr(
        "slappyengine.ui.theme.get_active_theme",
        lambda: fake_theme,
        raising=False,
    )
    # Ensure the module-level import path also resolves to the patched fn.
    import slappyengine.ui.theme as theme_pkg
    monkeypatch.setattr(theme_pkg, "get_active_theme", lambda: fake_theme)

    zones = manager.compute_zones()
    for target in zones:
        r, g, b, a = target.color
        assert (r, g, b) == (255, 0, 128)
        assert a == DockZoneManager.PREVIEW_ALPHA


def test_render_previews_is_safe_when_draw_fails(
    manager: DockZoneManager, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """render_previews must not propagate when DPG's drawlist call fails."""
    # Install a stub for dearpygui.dearpygui whose draw_rectangle raises
    # (mirroring the headless / detached-drawlist failure mode).
    failing = types.ModuleType("dearpygui.dearpygui")

    def _boom(*_a, **_kw):
        raise RuntimeError("no live drawlist")

    failing.draw_rectangle = _boom
    # Patch both the submodule AND the parent attribute so
    # ``import dearpygui.dearpygui as dpg`` resolves to our stub even
    # when the real package has already been imported by another test.
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", failing)
    if "dearpygui" in sys.modules:
        monkeypatch.setattr(
            sys.modules["dearpygui"], "dearpygui", failing, raising=False
        )

    # Should swallow the RuntimeError and return cleanly.
    manager.on_drag_start("panel.a")
    manager.on_drag_tick("panel.a", (5, VIEWPORT_H // 2))
    manager.render_previews(draw_list="vp.drawlist", active_zone=DockZone.LEFT)


def test_render_previews_noop_on_floating(
    manager: DockZoneManager,
) -> None:
    # FLOATING / None should never touch DPG (no exception raised).
    manager.render_previews(draw_list="vp.drawlist", active_zone=None)
    manager.render_previews(
        draw_list="vp.drawlist", active_zone=DockZone.FLOATING
    )


def test_render_previews_invokes_draw_rectangle(
    manager: DockZoneManager, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Smoke-test the happy path: DPG present + zone active → draw call."""
    calls: list[dict[str, Any]] = []
    stub = types.ModuleType("dearpygui.dearpygui")

    def _draw_rectangle(**kwargs: Any) -> None:
        calls.append(kwargs)

    stub.draw_rectangle = _draw_rectangle
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", stub)
    if "dearpygui" in sys.modules:
        monkeypatch.setattr(
            sys.modules["dearpygui"], "dearpygui", stub, raising=False
        )

    manager.render_previews(
        draw_list="vp.drawlist", active_zone=DockZone.CENTER
    )
    assert len(calls) == 1
    kw = calls[0]
    assert kw["parent"] == "vp.drawlist"
    assert "pmin" in kw and "pmax" in kw
    # The fill colour should carry the configured preview alpha.
    assert kw["fill"][3] == DockZoneManager.PREVIEW_ALPHA


def test_dock_zone_target_dataclass_carries_fields() -> None:
    t = DockZoneTarget(
        zone=DockZone.LEFT,
        bounds=(0, 0, 100, 200),
        color=(10, 20, 30, 80),
    )
    assert t.zone is DockZone.LEFT
    assert t.bounds == (0, 0, 100, 200)
    assert t.color == (10, 20, 30, 80)
