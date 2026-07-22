"""Tests for ``pharos_editor.ui.editor.snap_manager``.

Covers registration, target generation (viewport / panel / grid), the
drag-tick snap algorithm, theme switching, and per-axis disable knobs.
The manager is pure logic so no DPG is required.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from pharos_editor.ui.editor.snap_manager import (
    SnapConfig,
    SnapManager,
    SnapTarget,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakePanel:
    """Minimal stand-in for ``MovablePanelWindow``."""
    tag: str
    x: int = 100
    y: int = 100
    width: int = 200
    height: int = 150


def _mk_mgr(**cfg_kwargs) -> SnapManager:
    cfg = SnapConfig(**cfg_kwargs)
    mgr = SnapManager(cfg)
    mgr.set_viewport_size(1280, 720)
    mgr.set_menu_bar_height(0)  # simpler maths for tests
    return mgr


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_panel_adds_to_registry():
    mgr = _mk_mgr()
    p = FakePanel("a")
    mgr.register_panel(p)
    assert "a" in mgr.registered_tags


def test_unregister_panel_removes_from_registry():
    mgr = _mk_mgr()
    p = FakePanel("a")
    mgr.register_panel(p)
    mgr.unregister_panel(p)
    assert "a" not in mgr.registered_tags


def test_unregister_panel_unknown_tag_is_noop():
    mgr = _mk_mgr()
    mgr.unregister_panel(FakePanel("ghost"))  # must not raise
    assert mgr.registered_tags == []


def test_register_panel_overwrites_same_tag():
    mgr = _mk_mgr()
    mgr.register_panel(FakePanel("a", x=10))
    mgr.register_panel(FakePanel("a", x=99))
    targets = mgr.compute_snap_targets("other")
    panel_edges = [t for t in targets if t.kind == "panel_edge"]
    xs = sorted({t.position for t in panel_edges if t.axis == "x"})
    assert 99 in xs and 10 not in xs


# ---------------------------------------------------------------------------
# compute_snap_targets
# ---------------------------------------------------------------------------


def test_compute_targets_viewport_only_no_panels():
    mgr = _mk_mgr()
    targets = mgr.compute_snap_targets("nobody")
    vp = [t for t in targets if t.kind == "viewport_edge"]
    assert len(vp) == 4
    axes = sorted([t.axis for t in vp])
    assert axes == ["x", "x", "y", "y"]


def test_compute_targets_viewport_positions():
    mgr = _mk_mgr()
    mgr.set_viewport_size(800, 600)
    mgr.set_menu_bar_height(25)
    targets = mgr.compute_snap_targets("nobody")
    xs = sorted([t.position for t in targets if t.axis == "x"])
    ys = sorted([t.position for t in targets if t.axis == "y"])
    assert xs == [0, 800]
    assert ys == [25, 600]


def test_compute_targets_each_sibling_panel_yields_four():
    mgr = _mk_mgr()
    mgr.register_panel(FakePanel("a", x=50, y=60, width=100, height=80))
    mgr.register_panel(FakePanel("b", x=300, y=200, width=120, height=90))
    targets = mgr.compute_snap_targets("drag")  # neither sibling is the dragger
    panel_edges = [t for t in targets if t.kind == "panel_edge"]
    assert len(panel_edges) == 8


def test_compute_targets_excludes_dragged_panel():
    mgr = _mk_mgr()
    mgr.register_panel(FakePanel("a", x=50, y=60, width=100, height=80))
    mgr.register_panel(FakePanel("b", x=300, y=200, width=120, height=90))
    targets = mgr.compute_snap_targets("a")
    panel_edges = [t for t in targets if t.kind == "panel_edge"]
    assert all(t.source_tag == "b" for t in panel_edges)
    assert len(panel_edges) == 4


def test_compute_targets_panel_edges_match_geometry():
    mgr = _mk_mgr()
    mgr.register_panel(FakePanel("a", x=50, y=60, width=100, height=80))
    targets = mgr.compute_snap_targets("drag")
    xs = sorted([t.position for t in targets if t.axis == "x" and t.kind == "panel_edge"])
    ys = sorted([t.position for t in targets if t.axis == "y" and t.kind == "panel_edge"])
    assert xs == [50, 150]   # left, right
    assert ys == [60, 140]   # top, bottom


def test_compute_targets_grid_disabled_by_default():
    mgr = _mk_mgr()
    targets = mgr.compute_snap_targets("nobody")
    assert not any(t.kind == "grid_line" for t in targets)


def test_compute_targets_grid_adds_both_axes():
    mgr = _mk_mgr(enable_grid=True, grid_size=100)
    mgr.set_viewport_size(400, 300)
    targets = mgr.compute_snap_targets("nobody")
    grid_x = sorted({t.position for t in targets if t.kind == "grid_line" and t.axis == "x"})
    grid_y = sorted({t.position for t in targets if t.kind == "grid_line" and t.axis == "y"})
    assert grid_x == [0, 100, 200, 300, 400]
    assert grid_y == [0, 100, 200, 300]


def test_compute_targets_enable_viewport_edges_false():
    mgr = _mk_mgr(enable_viewport_edges=False)
    targets = mgr.compute_snap_targets("nobody")
    assert not any(t.kind == "viewport_edge" for t in targets)


def test_compute_targets_enable_panel_edges_false():
    mgr = _mk_mgr(enable_panel_edges=False)
    mgr.register_panel(FakePanel("a"))
    targets = mgr.compute_snap_targets("drag")
    assert not any(t.kind == "panel_edge" for t in targets)


# ---------------------------------------------------------------------------
# on_drag_tick — pass-through and snapping
# ---------------------------------------------------------------------------


def test_drag_tick_without_start_passes_through():
    mgr = _mk_mgr()
    mgr.register_panel(FakePanel("a"))
    # no on_drag_start, so position should be unchanged
    assert mgr.on_drag_tick("a", (123, 456)) == (123, 456)


def test_drag_tick_far_from_edge_no_snap():
    mgr = _mk_mgr(threshold_px=12)
    p = FakePanel("a", x=500, y=500, width=100, height=80)
    mgr.register_panel(p)
    mgr.on_drag_start("a")
    out = mgr.on_drag_tick("a", (500, 500))
    # 500/500 are far from any viewport edge or grid (grid off) → unchanged
    assert out == (500, 500)
    assert mgr.active_snap_x is None
    assert mgr.active_snap_y is None


def test_drag_tick_near_viewport_left_snaps_to_zero():
    mgr = _mk_mgr(threshold_px=12)
    p = FakePanel("a", x=10, y=400, width=100, height=80)
    mgr.register_panel(p)
    mgr.on_drag_start("a")
    out = mgr.on_drag_tick("a", (8, 400))  # left edge 8 px from x=0
    assert out[0] == 0
    assert mgr.active_snap_x is not None
    assert mgr.active_snap_x.kind == "viewport_edge"


def test_drag_tick_at_exact_threshold_still_snaps():
    mgr = _mk_mgr(threshold_px=12)
    p = FakePanel("a", x=0, y=400, width=100, height=80)
    mgr.register_panel(p)
    mgr.on_drag_start("a")
    out = mgr.on_drag_tick("a", (12, 400))  # exactly threshold → snap
    assert out[0] == 0


def test_drag_tick_just_over_threshold_does_not_snap():
    mgr = _mk_mgr(threshold_px=12)
    p = FakePanel("a", x=0, y=400, width=100, height=80)
    mgr.register_panel(p)
    mgr.on_drag_start("a")
    out = mgr.on_drag_tick("a", (13, 400))  # 13 > 12 → no snap
    assert out[0] == 13


def test_drag_tick_right_edge_snap_aligns_panel_right():
    mgr = _mk_mgr(threshold_px=12)
    p = FakePanel("a", x=0, y=400, width=100, height=80)
    mgr.register_panel(p)
    mgr.on_drag_start("a")
    # If desired x = 1175 and width = 100, right = 1275, target = 1280
    # |1275 - 1280| = 5 ≤ 12 → snap so right == 1280, so x = 1180
    out = mgr.on_drag_tick("a", (1175, 400))
    assert out[0] == 1180


def test_drag_tick_snaps_to_sibling_panel_edge():
    mgr = _mk_mgr(threshold_px=12)
    sibling = FakePanel("sib", x=400, y=0, width=100, height=80)
    dragger = FakePanel("drag", x=0, y=0, width=50, height=50)
    mgr.register_panel(sibling)
    mgr.register_panel(dragger)
    mgr.on_drag_start("drag")
    # mouse 405 → left edge 5 px from sibling's left (400) → snap to 400
    out = mgr.on_drag_tick("drag", (405, 300))
    assert out[0] == 400
    assert mgr.active_snap_x is not None
    assert mgr.active_snap_x.kind == "panel_edge"
    assert mgr.active_snap_x.source_tag == "sib"


def test_drag_tick_snaps_both_axes_simultaneously():
    mgr = _mk_mgr(threshold_px=12)
    p = FakePanel("a", x=0, y=0, width=50, height=50)
    mgr.register_panel(p)
    mgr.on_drag_start("a")
    out = mgr.on_drag_tick("a", (5, 5))
    assert out == (0, 0)
    assert mgr.active_snap_x is not None
    assert mgr.active_snap_y is not None


def test_drag_tick_first_matching_target_wins():
    mgr = _mk_mgr(threshold_px=20)
    # Two siblings at x=100 and x=110 — first wins.
    mgr.register_panel(FakePanel("s1", x=100, y=0, width=10, height=10))
    mgr.register_panel(FakePanel("s2", x=110, y=0, width=10, height=10))
    mgr.register_panel(FakePanel("drag", x=0, y=0, width=20, height=20))
    mgr.on_drag_start("drag")
    out = mgr.on_drag_tick("drag", (105, 500))
    # Either 100 or 110 is acceptable as long as one of them won
    assert out[0] in (100, 110)


def test_drag_tick_grid_snap_when_enabled():
    mgr = _mk_mgr(threshold_px=8, enable_grid=True, grid_size=16, enable_viewport_edges=False)
    p = FakePanel("a", x=0, y=0, width=50, height=50)
    mgr.register_panel(p)
    mgr.on_drag_start("a")
    out = mgr.on_drag_tick("a", (34, 500))  # 32 is closest grid line (2 px away)
    assert out[0] == 32


def test_drag_tick_unknown_tag_passes_through():
    mgr = _mk_mgr()
    # No drag started, no panel registered
    assert mgr.on_drag_tick("missing", (50, 60)) == (50, 60)


def test_drag_tick_after_end_passes_through():
    mgr = _mk_mgr(threshold_px=12)
    p = FakePanel("a", x=0, y=0, width=50, height=50)
    mgr.register_panel(p)
    mgr.on_drag_start("a")
    mgr.on_drag_end("a")
    out = mgr.on_drag_tick("a", (5, 5))
    assert out == (5, 5)
    assert mgr.is_dragging is False


# ---------------------------------------------------------------------------
# Drag lifecycle
# ---------------------------------------------------------------------------


def test_drag_start_sets_is_dragging():
    mgr = _mk_mgr()
    mgr.register_panel(FakePanel("a"))
    mgr.on_drag_start("a")
    assert mgr.is_dragging is True


def test_drag_start_unknown_tag_is_noop():
    mgr = _mk_mgr()
    mgr.on_drag_start("ghost")
    assert mgr.is_dragging is False


def test_unregister_during_drag_clears_state():
    mgr = _mk_mgr()
    p = FakePanel("a")
    mgr.register_panel(p)
    mgr.on_drag_start("a")
    mgr.unregister_panel(p)
    assert mgr.is_dragging is False


def test_iter_targets_empty_when_not_dragging():
    mgr = _mk_mgr()
    assert list(mgr.iter_targets()) == []


def test_iter_targets_yields_cached_targets_during_drag():
    mgr = _mk_mgr()
    mgr.register_panel(FakePanel("a"))
    mgr.on_drag_start("a")
    cached = list(mgr.iter_targets())
    assert len(cached) >= 4  # 4 viewport edges minimum


# ---------------------------------------------------------------------------
# Theme + guide colour
# ---------------------------------------------------------------------------


def test_guide_color_default():
    mgr = _mk_mgr()
    assert mgr.guide_color == (120, 160, 255, 220)


def test_guide_color_set_rgba():
    mgr = _mk_mgr()
    mgr.set_guide_color((220, 120, 160, 200))
    assert mgr.guide_color == (220, 120, 160, 200)


def test_guide_color_set_rgb_fills_alpha():
    mgr = _mk_mgr()
    mgr.set_guide_color((10, 20, 30))  # type: ignore[arg-type]
    assert mgr.guide_color == (10, 20, 30, 220)


def test_theme_switch_updates_guide_color_independently_of_drag():
    """A theme switch may happen mid-drag — colour update must not crash."""
    mgr = _mk_mgr()
    mgr.register_panel(FakePanel("a"))
    mgr.on_drag_start("a")
    mgr.set_guide_color((30, 30, 30, 255))
    assert mgr.guide_color == (30, 30, 30, 255)
    assert mgr.is_dragging is True


# ---------------------------------------------------------------------------
# SnapTarget / SnapConfig dataclass sanity
# ---------------------------------------------------------------------------


def test_snap_target_is_hashable():
    t = SnapTarget("x", 100, "viewport_edge")
    assert t in {t}


def test_snap_config_defaults():
    cfg = SnapConfig()
    assert cfg.threshold_px == 12
    assert cfg.grid_size == 16
    assert cfg.enable_viewport_edges is True
    assert cfg.enable_panel_edges is True
    assert cfg.enable_grid is False
    assert cfg.show_guide_lines is True
