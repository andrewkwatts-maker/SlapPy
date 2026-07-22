"""Tests for ``pharos_editor.ui.editor.resize_handles``.

Covers the contract in the sprint brief:

* eight handles per panel (four corners + four edges),
* cursor name mapping per direction,
* per-direction grow/shrink behaviour in ``on_resize_tick``,
* per-panel min size enforcement,
* snap-aware tick integration,
* theme-switch updates the corner sticker kind,
* lifecycle: ``on_resize_start`` / ``on_resize_end`` toggle state.

The module is framework-free in its hot paths so every test runs without
dearpygui (or any GPU). A tiny ``DummyPanel`` provides the duck-typed
``rect`` accessor; a ``RecordingDrawList`` stub records the calls
``render_handles`` makes so we can assert which handle was drawn and
how.
"""
from __future__ import annotations

import pytest

try:
    from pharos_editor.ui.editor.resize_handles import (
        MinSize,
        PANEL_MIN_SIZES,
        ResizeHandle,
        ResizeHandleManager,
        clamp_to_min_size,
        compute_handle_rects,
        min_size_for_panel,
    )
except Exception as exc:  # pragma: no cover - skip when deps missing
    pytest.skip(
        f"resize_handles dependencies unavailable: {exc}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


class DummyPanel:
    """Duck-typed :class:`MovablePanelWindow` stand-in."""

    def __init__(self, rect: tuple[int, int, int, int]) -> None:
        self.rect = rect


class RecordingDrawList:
    """A stub draw list that just records each call."""

    def __init__(self) -> None:
        self.rects: list[tuple] = []
        self.stickers: list[dict] = []

    def add_rect_filled(self, pmin, pmax, color) -> None:
        self.rects.append((tuple(pmin), tuple(pmax), tuple(color)))

    def add_sticker(self, kind, rect, direction, color) -> None:
        self.stickers.append(
            {"kind": kind, "rect": rect, "direction": direction, "color": color}
        )


class SimpleSnap:
    """A snap manager that always pulls width up to a fixed grid step."""

    def __init__(self, grid: int = 100) -> None:
        self.grid = grid

    def snap_rect(self, rect):
        x, y, w, h = rect
        snapped_w = ((w + self.grid // 2) // self.grid) * self.grid
        return (x, y, snapped_w, h)


@pytest.fixture
def mgr() -> ResizeHandleManager:
    panel = DummyPanel((100, 100, 400, 300))
    return ResizeHandleManager(panel, MinSize(width=200, height=150))


# ---------------------------------------------------------------------------
# 1. MinSize dataclass
# ---------------------------------------------------------------------------


def test_min_size_defaults():
    ms = MinSize()
    assert ms.width == 200 and ms.height == 150


def test_min_size_rejects_zero():
    with pytest.raises((TypeError, ValueError)):
        MinSize(width=0, height=100)


def test_min_size_rejects_negative():
    with pytest.raises((TypeError, ValueError)):
        MinSize(width=100, height=-1)


# ---------------------------------------------------------------------------
# 2. Per-panel min-size table
# ---------------------------------------------------------------------------


def test_panel_min_sizes_carry_all_eleven_entries():
    expected = {
        "NotebookToolbar":         (800, 40),
        "NotebookOutliner":        (240, 300),
        "NotebookInspector":       (280, 400),
        "NotebookContentBrowser":  (320, 180),
        "NotebookCodePanel":       (480, 320),
        "NotebookSpawnMenu":       (600, 400),
        "NotebookMaterialEditor":  (280, 400),
        "ThemeSwitcherPanel":      (280, 360),
        "NotebookStatusBar":       (400, 24),
        "NotebookWelcome":         (600, 500),
        "NotebookProjectPicker":   (480, 420),
    }
    for name, (w, h) in expected.items():
        ms = PANEL_MIN_SIZES[name]
        assert ms.width == w, f"{name} width mismatch: {ms.width} != {w}"
        assert ms.height == h, f"{name} height mismatch: {ms.height} != {h}"


def test_min_size_for_panel_returns_registered_value():
    class NotebookToolbar:
        pass

    ms = min_size_for_panel(NotebookToolbar())
    assert (ms.width, ms.height) == (800, 40)


def test_min_size_for_panel_falls_back_to_default():
    class SomeRandomThing:
        pass

    ms = min_size_for_panel(SomeRandomThing())
    assert (ms.width, ms.height) == (200, 150)


def test_min_size_for_panel_respects_inheritance():
    class NotebookOutliner:
        pass

    class FancyOutliner(NotebookOutliner):
        pass

    ms = min_size_for_panel(FancyOutliner())
    assert (ms.width, ms.height) == (240, 300)


def test_min_size_for_panel_prefers_direct_attribute():
    class WeirdPanel:
        MIN_SIZE = MinSize(width=321, height=123)

    ms = min_size_for_panel(WeirdPanel())
    assert (ms.width, ms.height) == (321, 123)


# ---------------------------------------------------------------------------
# 3. ResizeHandle dataclass
# ---------------------------------------------------------------------------


def test_resize_handle_validates_direction():
    with pytest.raises(ValueError):
        ResizeHandle(direction="middle", cursor_kind="ew-resize", bounds=(0, 0, 1, 1))


def test_resize_handle_contains_inside_outside():
    h = ResizeHandle(direction="se", cursor_kind="nwse-resize", bounds=(50, 50, 10, 10))
    assert h.contains(55, 55)
    assert not h.contains(49, 49)
    assert not h.contains(60, 60)  # upper edge exclusive


# ---------------------------------------------------------------------------
# 4. compute_handle_rects pure math
# ---------------------------------------------------------------------------


def test_compute_handle_rects_returns_eight_entries():
    rects = compute_handle_rects((0, 0, 400, 300), handle_size=12)
    assert set(rects.keys()) == {"nw", "ne", "sw", "se", "n", "s", "e", "w"}


def test_compute_handle_rects_corner_positions():
    rects = compute_handle_rects((0, 0, 400, 300), handle_size=12)
    assert rects["nw"] == (0, 0, 12, 12)
    assert rects["ne"] == (388, 0, 12, 12)
    assert rects["sw"] == (0, 288, 12, 12)
    assert rects["se"] == (388, 288, 12, 12)


def test_compute_handle_rects_edges_span_between_corners():
    rects = compute_handle_rects((0, 0, 400, 300), handle_size=12)
    # North edge spans from x=12 to x=388 → width 376
    assert rects["n"] == (12, 0, 376, 12)
    assert rects["s"] == (12, 288, 376, 12)
    # West edge runs from y=12 to y=288 → height 276
    assert rects["w"] == (0, 12, 12, 276)
    assert rects["e"] == (388, 12, 12, 276)


def test_compute_handle_rects_tiny_panel_collapses_safely():
    # A 10×10 panel is smaller than 2*handle_size; edges collapse to 0
    # width / height but corners still fit.
    rects = compute_handle_rects((0, 0, 10, 10), handle_size=12)
    assert rects["n"][2] == 0
    assert rects["s"][2] == 0
    assert rects["w"][3] == 0
    assert rects["e"][3] == 0


# ---------------------------------------------------------------------------
# 5. ResizeHandleManager.compute_handles
# ---------------------------------------------------------------------------


def test_compute_handles_returns_eight_handles(mgr):
    handles = mgr.compute_handles((100, 100, 400, 300))
    assert len(handles) == 8
    directions = [h.direction for h in handles]
    # Corners first, edges second.
    assert directions == ["nw", "ne", "sw", "se", "n", "s", "e", "w"]


def test_compute_handles_cursor_names(mgr):
    handles = {h.direction: h.cursor_kind for h in mgr.compute_handles((0, 0, 400, 300))}
    assert handles["n"] == "ns-resize"
    assert handles["s"] == "ns-resize"
    assert handles["e"] == "ew-resize"
    assert handles["w"] == "ew-resize"
    assert handles["ne"] == "nesw-resize"
    assert handles["sw"] == "nesw-resize"
    assert handles["nw"] == "nwse-resize"
    assert handles["se"] == "nwse-resize"


# ---------------------------------------------------------------------------
# 6. ResizeHandleManager.handle_at
# ---------------------------------------------------------------------------


def test_handle_at_returns_se_corner(mgr):
    # Panel rect is (100, 100, 400, 300) — SE corner is at (488, 388) in
    # viewport coordinates, size 12×12.
    h = mgr.handle_at((490, 390))
    assert h is not None
    assert h.direction == "se"


def test_handle_at_returns_nw_corner(mgr):
    h = mgr.handle_at((102, 102))
    assert h is not None
    assert h.direction == "nw"


def test_handle_at_returns_n_edge(mgr):
    # North edge midpoint: panel x range [112, 488] at y=100.
    h = mgr.handle_at((250, 102))
    assert h is not None
    assert h.direction == "n"


def test_handle_at_returns_e_edge(mgr):
    # East edge midpoint: panel x=488 (within [488, 500]), y in [112, 388].
    h = mgr.handle_at((490, 250))
    assert h is not None
    assert h.direction == "e"


def test_handle_at_returns_none_for_center(mgr):
    h = mgr.handle_at((300, 250))  # well inside the panel, away from edges
    assert h is None


def test_handle_at_corner_wins_over_edge(mgr):
    # The SE corner overlaps with the south + east edges; the manager
    # should resolve to the corner.
    h = mgr.handle_at((495, 395))
    assert h is not None
    assert h.direction == "se"


# ---------------------------------------------------------------------------
# 7. on_resize_tick — directional behaviour
# ---------------------------------------------------------------------------


def test_on_resize_tick_se_increases_w_and_h(mgr):
    se = ResizeHandle(direction="se", cursor_kind="nwse-resize", bounds=(388, 288, 12, 12))
    mgr.on_resize_start(se)
    # Mouse drags out toward (600, 500) — both w and h should grow.
    new_rect = mgr.on_resize_tick(se, (600, 500))
    x, y, w, h = new_rect
    # Origin stays put.
    assert x == 100 and y == 100
    # Width = mouse_x - origin_x; height = mouse_y - origin_y.
    assert w == 500 and h == 400


def test_on_resize_tick_nw_decreases_x_y_and_grows_to_compensate(mgr):
    # Origin rect (100,100,400,300). NW handle drag to (50, 60).
    nw = ResizeHandle(direction="nw", cursor_kind="nwse-resize", bounds=(0, 0, 12, 12))
    mgr.on_resize_start(nw)
    new_rect = mgr.on_resize_tick(nw, (50, 60))
    x, y, w, h = new_rect
    assert x == 50 and y == 60
    # The east + south edges are pinned, so width = 100 + 400 - 50 = 450.
    assert w == 450
    assert h == 340


def test_on_resize_tick_n_only_moves_y_and_h(mgr):
    n = ResizeHandle(direction="n", cursor_kind="ns-resize", bounds=(12, 0, 376, 12))
    mgr.on_resize_start(n)
    new_rect = mgr.on_resize_tick(n, (250, 80))
    x, y, w, h = new_rect
    # x and w unchanged.
    assert x == 100 and w == 400
    assert y == 80
    assert h == 320  # 100 + 300 - 80


def test_on_resize_tick_e_only_moves_w(mgr):
    e = ResizeHandle(direction="e", cursor_kind="ew-resize", bounds=(388, 12, 12, 276))
    mgr.on_resize_start(e)
    new_rect = mgr.on_resize_tick(e, (600, 250))
    x, y, w, h = new_rect
    assert (x, y) == (100, 100)
    assert h == 300
    assert w == 500


# ---------------------------------------------------------------------------
# 8. Min size enforcement
# ---------------------------------------------------------------------------


def test_on_resize_tick_enforces_min_width_at_se(mgr):
    se = ResizeHandle(direction="se", cursor_kind="nwse-resize", bounds=(388, 288, 12, 12))
    mgr.on_resize_start(se)
    # Drag mouse back to (110, 110) — would be 10×10 without the clamp.
    new_rect = mgr.on_resize_tick(se, (110, 110))
    _, _, w, h = new_rect
    assert w == 200 and h == 150


def test_on_resize_tick_nw_clamp_re_anchors_east_edge(mgr):
    nw = ResizeHandle(direction="nw", cursor_kind="nwse-resize", bounds=(0, 0, 12, 12))
    mgr.on_resize_start(nw)
    # Drag NW to (490, 390) — would collapse panel to almost nothing.
    new_rect = mgr.on_resize_tick(nw, (490, 390))
    x, y, w, h = new_rect
    # Min size enforced.
    assert w == 200 and h == 150
    # East edge must remain pinned at original_x + original_w = 500;
    # so new x = 500 - 200 = 300. Same for south.
    assert x == 300
    assert y == 250  # 100 + 300 - 150


def test_clamp_to_min_size_direct():
    origin = (100, 100, 400, 300)
    rect = (200, 200, 10, 10)
    out = clamp_to_min_size(rect, "se", MinSize(width=200, height=150), origin)
    assert out == (200, 200, 200, 150)


def test_clamp_to_min_size_n_pins_south_edge():
    origin = (0, 0, 300, 300)
    # Dragging the north edge collapsed h to 5; the clamp must re-anchor
    # so south edge (origin y + h = 300) stays put.
    rect = (0, 295, 300, 5)
    out = clamp_to_min_size(rect, "n", MinSize(width=200, height=150), origin)
    x, y, w, h = out
    assert h == 150
    assert y == 150  # 0 + 300 - 150


# ---------------------------------------------------------------------------
# 9. Snap integration
# ---------------------------------------------------------------------------


def test_on_resize_tick_runs_snap_after_min_size(mgr):
    panel = DummyPanel((100, 100, 400, 300))
    snap_mgr = ResizeHandleManager(panel, MinSize(width=200, height=150), SimpleSnap(grid=100))
    se = ResizeHandle(direction="se", cursor_kind="nwse-resize", bounds=(388, 288, 12, 12))
    snap_mgr.on_resize_start(se)
    # Mouse at (640, 400) → w=540, snap rounds to nearest 100 → 500.
    new_rect = snap_mgr.on_resize_tick(se, (640, 400))
    assert new_rect[2] == 500


def test_no_snap_when_snap_manager_is_none(mgr):
    se = ResizeHandle(direction="se", cursor_kind="nwse-resize", bounds=(388, 288, 12, 12))
    mgr.on_resize_start(se)
    new_rect = mgr.on_resize_tick(se, (640, 400))
    # Width is precisely (640 - 100) = 540.
    assert new_rect[2] == 540


# ---------------------------------------------------------------------------
# 10. Cursor names
# ---------------------------------------------------------------------------


def test_cursor_for_direction(mgr):
    assert mgr.cursor_for("n") == "ns-resize"
    assert mgr.cursor_for("e") == "ew-resize"
    assert mgr.cursor_for("ne") == "nesw-resize"
    assert mgr.cursor_for("nw") == "nwse-resize"


def test_cursor_for_invalid_direction_raises(mgr):
    with pytest.raises((TypeError, ValueError)):
        mgr.cursor_for("middle")


# ---------------------------------------------------------------------------
# 11. Lifecycle
# ---------------------------------------------------------------------------


def test_is_resizing_lifecycle(mgr):
    assert not mgr.is_resizing
    se = ResizeHandle(direction="se", cursor_kind="nwse-resize", bounds=(388, 288, 12, 12))
    mgr.on_resize_start(se)
    assert mgr.is_resizing
    assert mgr.active_direction == "se"
    mgr.on_resize_end()
    assert not mgr.is_resizing
    assert mgr.active_direction is None


# ---------------------------------------------------------------------------
# 12. Render manifest + theme switching
# ---------------------------------------------------------------------------


def test_render_handles_returns_eight_entries(mgr):
    dl = RecordingDrawList()
    manifest = mgr.render_handles(dl)
    assert set(manifest.keys()) == {"nw", "ne", "sw", "se", "n", "s", "e", "w"}


def test_render_handles_corner_carries_sticker(mgr):
    dl = RecordingDrawList()
    manifest = mgr.render_handles(dl)
    for corner in ("nw", "ne", "sw", "se"):
        assert manifest[corner]["sticker"] is not None
    for edge in ("n", "s", "e", "w"):
        assert manifest[edge]["sticker"] is None


def test_render_handles_hover_flag(mgr):
    dl = RecordingDrawList()
    hover = ResizeHandle(direction="se", cursor_kind="nwse-resize", bounds=(388, 288, 12, 12))
    manifest = mgr.render_handles(dl, hovered=hover)
    assert manifest["se"]["hovered"] is True
    assert manifest["nw"]["hovered"] is False
    # Hover handle is scaled up: rect width > HANDLE_SIZE.
    assert manifest["se"]["rect"][2] > mgr.HANDLE_SIZE


def test_render_handles_invokes_drawlist(mgr):
    dl = RecordingDrawList()
    mgr.render_handles(dl)
    # All eight handles should have produced an add_rect_filled call.
    assert len(dl.rects) == 8


def test_render_handles_default_sticker_is_dot(mgr):
    # No theme registered → default fallback "dot".
    assert mgr.sticker_kind() == "dot"


def test_theme_switch_updates_sticker_kind(mgr, monkeypatch):
    """Direct unit on the manager's theme-name resolver."""
    class FakeSpec:
        name = "kawaii_planner"

    monkeypatch.setattr(
        mgr, "_resolve_theme_name", lambda: FakeSpec().name
    )
    assert mgr.sticker_kind() == "heart"

    monkeypatch.setattr(
        mgr, "_resolve_theme_name", lambda: "cottagecore_garden"
    )
    assert mgr.sticker_kind() == "star"

    monkeypatch.setattr(
        mgr, "_resolve_theme_name", lambda: "bullet_journal"
    )
    assert mgr.sticker_kind() == "dot"

    monkeypatch.setattr(
        mgr, "_resolve_theme_name", lambda: "teengirl_notebook"
    )
    assert mgr.sticker_kind() == "washi"

    monkeypatch.setattr(
        mgr, "_resolve_theme_name", lambda: "cozy_diary"
    )
    assert mgr.sticker_kind() == "leather"

    monkeypatch.setattr(
        mgr, "_resolve_theme_name", lambda: "scrapbook_summer"
    )
    assert mgr.sticker_kind() == "splat"


def test_theme_unknown_falls_back_to_dot(mgr, monkeypatch):
    monkeypatch.setattr(
        mgr, "_resolve_theme_name", lambda: "some_unregistered_theme"
    )
    assert mgr.sticker_kind() == "dot"


# ---------------------------------------------------------------------------
# 13. Construction validation
# ---------------------------------------------------------------------------


def test_manager_rejects_none_panel():
    with pytest.raises((TypeError, ValueError)):
        ResizeHandleManager(None, MinSize())


def test_manager_rejects_non_minsize():
    with pytest.raises((TypeError, ValueError)):
        ResizeHandleManager(DummyPanel((0, 0, 100, 100)), "not-a-min-size")  # type: ignore[arg-type]


def test_manager_exposes_properties(mgr):
    assert isinstance(mgr.min_size, MinSize)
    assert mgr.snap_manager is None
    assert isinstance(mgr.panel, DummyPanel)
