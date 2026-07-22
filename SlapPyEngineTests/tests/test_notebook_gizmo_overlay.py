"""Headless tests for :class:`NotebookGizmoOverlay`.

Every test runs without Dear PyGui — a :class:`MockDrawList` records the
drawlist primitive calls the overlay would issue, and the delta callback
just captures its arguments into a list. This mirrors the pattern already
established by :mod:`test_editor_notebook_gizmos` for the visual reskin
overlay so both files stay easy to read side-by-side.
"""
from __future__ import annotations

import math
from typing import Any

import pytest

from pharos_editor.ui.editor.notebook_gizmo_overlay import (
    TOOL_MOVE,
    TOOL_ROTATE,
    TOOL_SCALE,
    VALID_TOOLS,
    NotebookGizmoOverlay,
    _hand_drawn_line,
    _jitter_samples,
    _stable_hash,
)
from pharos_editor.ui.theme import Color, apply_theme, register_theme
from pharos_editor.ui.theme.theme_spec import (
    Gradient,
    SemanticTokens,
    ThemeSpec,
)


# ---------------------------------------------------------------------------
# MockDrawList — same pattern as test_editor_notebook_gizmos.
# ---------------------------------------------------------------------------


class MockDrawList:
    """Recording stand-in for a Dear PyGui viewport drawlist."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def _record(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.append((name, args, kwargs))

    def add_line(self, *args: Any, **kwargs: Any) -> None:
        self._record("add_line", args, kwargs)

    def add_polyline(self, *args: Any, **kwargs: Any) -> None:
        self._record("add_polyline", args, kwargs)

    def add_circle(self, *args: Any, **kwargs: Any) -> None:
        self._record("add_circle", args, kwargs)

    def add_quad(self, *args: Any, **kwargs: Any) -> None:
        self._record("add_quad", args, kwargs)

    def add_triangle(self, *args: Any, **kwargs: Any) -> None:
        self._record("add_triangle", args, kwargs)

    def add_text(self, *args: Any, **kwargs: Any) -> None:
        self._record("add_text", args, kwargs)

    def names(self) -> set[str]:
        return {n for (n, _a, _k) in self.calls}

    def by_name(self, name: str) -> list[tuple[tuple, dict]]:
        return [(a, k) for (n, a, k) in self.calls if n == name]

    def colors(self) -> list[tuple[int, int, int, int]]:
        return [k.get("color") for (_n, _a, k) in self.calls if "color" in k]


# ---------------------------------------------------------------------------
# Theme fixtures.
# ---------------------------------------------------------------------------


def _make_gizmo_theme(
    name: str,
    *,
    accent: tuple[int, int, int, int] = (255, 180, 70, 235),
    primary: tuple[int, int, int, int] = (100, 140, 220, 235),
) -> ThemeSpec:
    palette: dict[str, Color] = {}
    semantic = SemanticTokens(
        primary=Color(primary[0], primary[1], primary[2], primary[3] / 255),
        primary_gradient=Gradient(
            start=Color(primary[0], primary[1], primary[2], 1.0),
            end=Color(accent[0], accent[1], accent[2], 1.0),
        ),
        secondary=Color(80, 100, 180, 1.0),
        accent=Color(accent[0], accent[1], accent[2], accent[3] / 255),
        background=Color(250, 245, 235, 1.0),
        surface=Color(250, 245, 235, 1.0),
        surface_hover=Color(240, 235, 225, 1.0),
        border=Color(60, 50, 80, 1.0),
        text_primary=Color(60, 50, 80, 1.0),
        text_secondary=Color(120, 110, 140, 200 / 255),
        text_disabled=Color(180, 170, 190, 1.0),
        success=Color(70, 160, 110, 1.0),
        warning=Color(240, 190, 80, 1.0),
        error=Color(200, 60, 60, 1.0),
        info=Color(60, 150, 220, 1.0),
        focus_ring=Color(255, 200, 80, 1.0),
        glass_bg=Color(255, 255, 255, 0.1),
        glass_blur_px=8.0,
    )
    return ThemeSpec(name=name, palette=palette, semantic=semantic)


@pytest.fixture()
def gizmo_theme() -> ThemeSpec:
    theme = _make_gizmo_theme("notebook_gizmo_overlay_test")
    register_theme(theme)
    apply_theme(theme.name)
    return theme


@pytest.fixture()
def overlay(gizmo_theme: ThemeSpec) -> NotebookGizmoOverlay:
    o = NotebookGizmoOverlay()
    o.set_selection_bbox((100.0, 100.0, 80.0, 60.0))
    return o


# ---------------------------------------------------------------------------
# 1. Tool constants.
# ---------------------------------------------------------------------------


def test_tool_constants_are_distinct() -> None:
    assert TOOL_MOVE != TOOL_ROTATE
    assert TOOL_ROTATE != TOOL_SCALE
    assert TOOL_MOVE != TOOL_SCALE
    assert set(VALID_TOOLS) == {TOOL_MOVE, TOOL_ROTATE, TOOL_SCALE}


def test_default_tool_is_move(overlay: NotebookGizmoOverlay) -> None:
    assert overlay.tool == TOOL_MOVE


# ---------------------------------------------------------------------------
# 2. Tool swap — handle counts differ per tool.
# ---------------------------------------------------------------------------


def test_set_tool_swaps_handle_set_move_to_scale(
    overlay: NotebookGizmoOverlay,
) -> None:
    overlay.set_tool(TOOL_MOVE)
    move_count = overlay.handle_count()
    overlay.set_tool(TOOL_SCALE)
    scale_count = overlay.handle_count()
    assert move_count != scale_count
    # Scale is the biggest set (8 handles).
    assert scale_count == 8
    # Move is 3 (x, y, xy).
    assert move_count == 3


def test_set_tool_rotate_has_one_handle(overlay: NotebookGizmoOverlay) -> None:
    overlay.set_tool(TOOL_ROTATE)
    assert overlay.handle_count() == 1


def test_set_tool_rejects_unknown(overlay: NotebookGizmoOverlay) -> None:
    with pytest.raises(ValueError):
        overlay.set_tool("bogus")


# ---------------------------------------------------------------------------
# 3. Selection bbox — auto-hide + centre math.
# ---------------------------------------------------------------------------


def test_selection_bbox_none_hides_gizmo(gizmo_theme: ThemeSpec) -> None:
    g = NotebookGizmoOverlay()
    assert not g.is_visible()
    g.set_selection_bbox((10.0, 20.0, 30.0, 40.0))
    assert g.is_visible()
    g.set_selection_bbox(None)
    assert not g.is_visible()


def test_render_no_ops_when_not_visible(gizmo_theme: ThemeSpec) -> None:
    g = NotebookGizmoOverlay()
    dl = MockDrawList()
    g.render(dl)
    assert dl.calls == []


def test_center_computed_from_bbox(gizmo_theme: ThemeSpec) -> None:
    g = NotebookGizmoOverlay()
    g.set_selection_bbox((100.0, 200.0, 40.0, 60.0))
    cx, cy = g.center()  # type: ignore[misc]
    assert cx == 120.0
    assert cy == 230.0


def test_set_selection_bbox_rejects_bad_shape(overlay: NotebookGizmoOverlay) -> None:
    with pytest.raises(TypeError):
        overlay.set_selection_bbox((1.0, 2.0))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 4. Render — emits primitives per tool.
# ---------------------------------------------------------------------------


def test_render_move_draws_two_arrows(overlay: NotebookGizmoOverlay) -> None:
    overlay.set_tool(TOOL_MOVE)
    dl = MockDrawList()
    overlay.render(dl)
    # Two hand-drawn shafts → two polylines. Arrowheads are lines.
    assert len(dl.by_name("add_polyline")) >= 2
    assert len(dl.by_name("add_line")) >= 4  # 2 lines per arrowhead × 2 arrows


def test_render_rotate_draws_arc_and_ticks(overlay: NotebookGizmoOverlay) -> None:
    overlay.set_tool(TOOL_ROTATE)
    dl = MockDrawList()
    overlay.render(dl)
    # 1 arc polyline + 8 tick lines + 1 handle circle.
    assert len(dl.by_name("add_polyline")) >= 1
    assert len(dl.by_name("add_line")) >= NotebookGizmoOverlay.ROTATE_TICK_COUNT
    assert len(dl.by_name("add_circle")) >= 1


def test_render_scale_draws_eight_handle_boxes(
    overlay: NotebookGizmoOverlay,
) -> None:
    overlay.set_tool(TOOL_SCALE)
    dl = MockDrawList()
    overlay.render(dl)
    # 8 handles × 4 polylines per box + 4 guide-rect polylines = 36.
    polylines = dl.by_name("add_polyline")
    assert len(polylines) >= 8 * 4 + 4


# ---------------------------------------------------------------------------
# 5. Drag callback — shape per tool.
# ---------------------------------------------------------------------------


def test_move_drag_yields_dx_dy_proportional(
    overlay: NotebookGizmoOverlay,
) -> None:
    captured: list[tuple[str, tuple]] = []
    overlay.set_on_transform(lambda kind, delta: captured.append((kind, delta)))
    overlay.set_tool(TOOL_MOVE)
    overlay.on_drag_start("move_xy", (140.0, 130.0))
    delta = overlay.on_drag((160.0, 145.0))
    assert delta == (20.0, 15.0)
    assert captured[-1] == (TOOL_MOVE, (20.0, 15.0))


def test_move_drag_scales_with_mouse(overlay: NotebookGizmoOverlay) -> None:
    overlay.set_tool(TOOL_MOVE)
    overlay.on_drag_start("move_xy", (100.0, 100.0))
    d1 = overlay.on_drag((110.0, 110.0))
    d2 = overlay.on_drag((120.0, 120.0))
    assert d1 == (10.0, 10.0)
    assert d2 == (20.0, 20.0)
    # Second delta is exactly 2× the first.
    assert d2[0] == pytest.approx(2 * d1[0])
    assert d2[1] == pytest.approx(2 * d1[1])


def test_rotate_drag_yields_radians(overlay: NotebookGizmoOverlay) -> None:
    overlay.set_tool(TOOL_ROTATE)
    # Selection centre is (140, 130) for the fixture bbox.
    cx, cy = overlay.center()  # type: ignore[misc]
    # Anchor mouse at (cx + 100, cy) — angle 0.
    overlay.on_drag_start("rotate_handle", (cx + 100.0, cy))
    # Drag to (cx, cy + 100) — angle +pi/2 (screen y grows downward, atan2
    # returns pi/2 for a positive y delta).
    delta = overlay.on_drag((cx, cy + 100.0))
    assert delta is not None
    assert len(delta) == 1
    assert delta[0] == pytest.approx(math.pi / 2, abs=1e-6)


def test_rotate_drag_delta_proportional_to_angle(
    overlay: NotebookGizmoOverlay,
) -> None:
    overlay.set_tool(TOOL_ROTATE)
    cx, cy = overlay.center()  # type: ignore[misc]
    overlay.on_drag_start("rotate_handle", (cx + 50.0, cy))
    d_quarter = overlay.on_drag((cx, cy + 50.0))  # +pi/2
    d_eighth = overlay.on_drag((cx + 50.0, cy + 50.0))  # +pi/4
    assert d_quarter[0] == pytest.approx(math.pi / 2, abs=1e-6)
    assert d_eighth[0] == pytest.approx(math.pi / 4, abs=1e-6)


def test_scale_drag_yields_ratio(overlay: NotebookGizmoOverlay) -> None:
    overlay.set_tool(TOOL_SCALE)
    cx, cy = overlay.center()  # type: ignore[misc]
    # Anchor 40 px from centre.
    overlay.on_drag_start("scale_br", (cx + 40.0, cy))
    # Drag to 80 px — ratio should be 2.0.
    delta = overlay.on_drag((cx + 80.0, cy))
    assert delta is not None
    assert len(delta) == 2
    assert delta[0] == pytest.approx(2.0)
    assert delta[1] == pytest.approx(2.0)


def test_scale_drag_ratio_less_than_one(overlay: NotebookGizmoOverlay) -> None:
    overlay.set_tool(TOOL_SCALE)
    cx, cy = overlay.center()  # type: ignore[misc]
    overlay.on_drag_start("scale_br", (cx + 100.0, cy))
    delta = overlay.on_drag((cx + 50.0, cy))
    assert delta[0] == pytest.approx(0.5)
    assert delta[1] == pytest.approx(0.5)


def test_drag_end_clears_state(overlay: NotebookGizmoOverlay) -> None:
    overlay.set_tool(TOOL_MOVE)
    overlay.on_drag_start("move_xy", (140.0, 130.0))
    assert overlay.is_dragging()
    overlay.on_drag_end()
    assert not overlay.is_dragging()
    # Subsequent drag returns None because no anchor is set.
    assert overlay.on_drag((200.0, 200.0)) is None


def test_drag_without_start_is_noop(overlay: NotebookGizmoOverlay) -> None:
    overlay.set_tool(TOOL_MOVE)
    captured: list[Any] = []
    overlay.set_on_transform(lambda k, d: captured.append((k, d)))
    assert overlay.on_drag((10.0, 20.0)) is None
    assert captured == []


def test_set_tool_mid_drag_resets_anchor(overlay: NotebookGizmoOverlay) -> None:
    overlay.set_tool(TOOL_MOVE)
    overlay.on_drag_start("move_xy", (100.0, 100.0))
    assert overlay.is_dragging()
    overlay.set_tool(TOOL_ROTATE)
    assert not overlay.is_dragging()


# ---------------------------------------------------------------------------
# 6. Callback wiring.
# ---------------------------------------------------------------------------


def test_set_on_transform_callback_fires(overlay: NotebookGizmoOverlay) -> None:
    seen: list[tuple[str, tuple]] = []
    overlay.set_on_transform(lambda k, d: seen.append((k, d)))
    overlay.set_tool(TOOL_MOVE)
    overlay.on_drag_start("move_xy", (140.0, 130.0))
    overlay.on_drag((150.0, 140.0))
    assert seen == [(TOOL_MOVE, (10.0, 10.0))]


def test_callback_exception_does_not_propagate(
    overlay: NotebookGizmoOverlay,
) -> None:
    def bad(kind: str, delta: tuple) -> None:
        raise RuntimeError("boom")

    overlay.set_on_transform(bad)
    overlay.set_tool(TOOL_MOVE)
    overlay.on_drag_start("move_xy", (140.0, 130.0))
    # Should not raise — errors are swallowed.
    result = overlay.on_drag((160.0, 140.0))
    assert result == (20.0, 10.0)


def test_clear_callback_silences_drag(overlay: NotebookGizmoOverlay) -> None:
    seen: list[Any] = []
    overlay.set_on_transform(lambda k, d: seen.append((k, d)))
    overlay.set_on_transform(None)
    overlay.set_tool(TOOL_MOVE)
    overlay.on_drag_start("move_xy", (100.0, 100.0))
    overlay.on_drag((110.0, 110.0))
    assert seen == []


# ---------------------------------------------------------------------------
# 7. Theme resolution — X = accent, Y = primary.
# ---------------------------------------------------------------------------


def test_move_x_uses_accent(overlay: NotebookGizmoOverlay,
                            gizmo_theme: ThemeSpec) -> None:
    overlay.set_tool(TOOL_MOVE)
    dl = MockDrawList()
    overlay.render(dl)
    accent = gizmo_theme.semantic.accent.as_rgba_tuple()
    assert accent in dl.colors()


def test_move_y_uses_primary(overlay: NotebookGizmoOverlay,
                             gizmo_theme: ThemeSpec) -> None:
    overlay.set_tool(TOOL_MOVE)
    dl = MockDrawList()
    overlay.render(dl)
    primary = gizmo_theme.semantic.primary.as_rgba_tuple()
    assert primary in dl.colors()


def test_theme_swap_updates_axis_colors() -> None:
    theme_a = _make_gizmo_theme(
        "notebook_gizmo_theme_a",
        accent=(255, 100, 50, 255),
        primary=(30, 70, 200, 255),
    )
    theme_b = _make_gizmo_theme(
        "notebook_gizmo_theme_b",
        accent=(50, 200, 150, 255),
        primary=(200, 50, 255, 255),
    )
    register_theme(theme_a)
    register_theme(theme_b)
    g = NotebookGizmoOverlay()
    g.set_selection_bbox((0.0, 0.0, 100.0, 100.0))
    g.set_tool(TOOL_MOVE)

    apply_theme(theme_a.name)
    dl_a = MockDrawList()
    g.render(dl_a)
    assert theme_a.semantic.accent.as_rgba_tuple() in dl_a.colors()

    apply_theme(theme_b.name)
    dl_b = MockDrawList()
    g.render(dl_b)
    assert theme_b.semantic.accent.as_rgba_tuple() in dl_b.colors()
    # And the old accent is no longer used in the new drawlist.
    assert theme_a.semantic.accent.as_rgba_tuple() not in dl_b.colors()


# ---------------------------------------------------------------------------
# 8. Hit testing.
# ---------------------------------------------------------------------------


def test_hit_test_none_when_hidden(gizmo_theme: ThemeSpec) -> None:
    g = NotebookGizmoOverlay()
    assert g.hit_test((10.0, 10.0)) is None


def test_hit_test_returns_move_handle(overlay: NotebookGizmoOverlay) -> None:
    overlay.set_tool(TOOL_MOVE)
    cx, cy = overlay.center()  # type: ignore[misc]
    hit = overlay.hit_test(
        (cx + NotebookGizmoOverlay.MOVE_ARROW_LEN, cy)
    )
    assert hit == "move_x"


def test_hit_test_returns_scale_corner(overlay: NotebookGizmoOverlay) -> None:
    overlay.set_tool(TOOL_SCALE)
    x, y, w, h = 100.0, 100.0, 80.0, 60.0
    assert overlay.hit_test((x, y)) == "scale_tl"
    assert overlay.hit_test((x + w, y + h)) == "scale_br"


# ---------------------------------------------------------------------------
# 9. Hand-drawn jitter helper — magnitude bound.
# ---------------------------------------------------------------------------


def test_hand_drawn_line_returns_wobbled_points() -> None:
    dl = MockDrawList()
    pts = _hand_drawn_line(
        dl, (0.0, 0.0), (60.0, 0.0), (0, 0, 0, 255),
        seed=42, jitter_px=1.4,
    )
    assert len(pts) >= 5
    # Every sample's perpendicular offset (y here — line is horizontal) is
    # inside ±jitter_px.
    for _x, y in pts:
        assert abs(y) <= 1.4 + 1e-6


def test_hand_drawn_line_deterministic() -> None:
    dl1 = MockDrawList()
    dl2 = MockDrawList()
    p1 = _hand_drawn_line(dl1, (0.0, 0.0), (100.0, 0.0),
                          (0, 0, 0, 255), seed=99, jitter_px=1.4)
    p2 = _hand_drawn_line(dl2, (0.0, 0.0), (100.0, 0.0),
                          (0, 0, 0, 255), seed=99, jitter_px=1.4)
    assert p1 == p2


def test_hand_drawn_line_zero_jitter_is_straight() -> None:
    dl = MockDrawList()
    pts = _hand_drawn_line(
        dl, (10.0, 20.0), (60.0, 20.0), (0, 0, 0, 255),
        seed=1, jitter_px=0.0, samples=5,
    )
    for _x, y in pts:
        assert y == 20.0


def test_jitter_samples_bounded() -> None:
    samples = _jitter_samples(seed=123, count=32, amplitude=1.4)
    assert len(samples) == 32
    assert max(abs(v) for v in samples) <= 1.4 + 1e-6


def test_stable_hash_is_deterministic() -> None:
    assert _stable_hash("a", 1) == _stable_hash("a", 1)
    assert _stable_hash("a", 1) != _stable_hash("a", 2)


# ---------------------------------------------------------------------------
# 10. DPG bounding-box math — sanity check that handle placement follows
#     the bbox anchor exactly, regardless of tool.
# ---------------------------------------------------------------------------


def test_handle_positions_track_bbox_translation(
    overlay: NotebookGizmoOverlay,
) -> None:
    """Translating the bbox by (dx, dy) translates every handle by the same amount."""
    overlay.set_tool(TOOL_SCALE)
    x, y, w, h = overlay.bbox  # type: ignore[misc]
    before = overlay.handle_positions()
    dx, dy = 25.0, -13.0
    overlay.set_selection_bbox((x + dx, y + dy, w, h))
    after = overlay.handle_positions()
    for key, (bx, by) in before.items():
        ax, ay = after[key]
        assert ax == pytest.approx(bx + dx)
        assert ay == pytest.approx(by + dy)


def test_scale_corner_handles_at_bbox_corners(
    overlay: NotebookGizmoOverlay,
) -> None:
    """DPG bbox math: corner handles land exactly on the bbox corners."""
    overlay.set_tool(TOOL_SCALE)
    positions = overlay.handle_positions()
    x, y, w, h = overlay.bbox  # type: ignore[misc]
    assert positions["scale_tl"] == (x, y)
    assert positions["scale_tr"] == (x + w, y)
    assert positions["scale_br"] == (x + w, y + h)
    assert positions["scale_bl"] == (x, y + h)


def test_scale_edge_handles_at_edge_midpoints(
    overlay: NotebookGizmoOverlay,
) -> None:
    overlay.set_tool(TOOL_SCALE)
    positions = overlay.handle_positions()
    x, y, w, h = overlay.bbox  # type: ignore[misc]
    assert positions["scale_top"] == (x + w * 0.5, y)
    assert positions["scale_right"] == (x + w, y + h * 0.5)
    assert positions["scale_bottom"] == (x + w * 0.5, y + h)
    assert positions["scale_left"] == (x, y + h * 0.5)
