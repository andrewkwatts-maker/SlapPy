"""Tests for the coloured-pencil notebook gizmo overlay.

These tests run fully headless — no DPG, no GPU. A
:class:`MockDrawList` records every drawlist primitive call so the
contract can be asserted on call counts, colours and coordinates.
"""
from __future__ import annotations

from typing import Any

import pytest

from pharos_editor.ui.editor.notebook_gizmos import (
    NotebookGizmoOverlay,
    _stable_hash,
    _wobble_samples,
)
from pharos_editor.ui.theme import Color, register_theme, apply_theme
from pharos_editor.ui.theme.theme_spec import (
    Gradient,
    SemanticTokens,
    ThemeSpec,
)


# ---------------------------------------------------------------------------
# MockDrawList — records every primitive call so tests can assert against it.
# ---------------------------------------------------------------------------


class MockDrawList:
    """Recording stand-in for a Dear PyGui viewport drawlist."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def _record(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.append((name, args, kwargs))

    def add_line(self, *args: Any, **kwargs: Any) -> None:
        self._record("add_line", args, kwargs)

    def add_circle(self, *args: Any, **kwargs: Any) -> None:
        self._record("add_circle", args, kwargs)

    def add_polyline(self, *args: Any, **kwargs: Any) -> None:
        self._record("add_polyline", args, kwargs)

    def add_text(self, *args: Any, **kwargs: Any) -> None:
        self._record("add_text", args, kwargs)

    def add_triangle(self, *args: Any, **kwargs: Any) -> None:
        self._record("add_triangle", args, kwargs)

    def add_quad(self, *args: Any, **kwargs: Any) -> None:
        self._record("add_quad", args, kwargs)

    # convenience filters
    def names(self) -> set[str]:
        return {n for (n, _a, _k) in self.calls}

    def by_name(self, name: str) -> list[tuple[tuple, dict]]:
        return [(a, k) for (n, a, k) in self.calls if n == name]

    def colors(self) -> list[tuple[int, int, int, int]]:
        return [k.get("color") for (_n, _a, k) in self.calls if "color" in k]


# ---------------------------------------------------------------------------
# Helper themes — pencil-palette theme + a "different" theme for switching.
# ---------------------------------------------------------------------------


def _make_pencil_theme(name: str, *, red=(220, 70, 80, 240),
                       blue=(50, 90, 220, 240),
                       accent=(255, 200, 80, 220)) -> ThemeSpec:
    palette: dict[str, Color] = {
        "pencil_red": Color(red[0], red[1], red[2], red[3] / 255),
        "pencil_blue": Color(blue[0], blue[1], blue[2], blue[3] / 255),
        "accent": Color(accent[0], accent[1], accent[2], accent[3] / 255),
    }
    semantic = SemanticTokens(
        primary=Color(220, 70, 80, 1.0),
        primary_gradient=Gradient(
            start=Color(220, 70, 80, 1.0), end=Color(255, 200, 80, 1.0)
        ),
        secondary=Color(50, 90, 220, 1.0),
        accent=Color(accent[0], accent[1], accent[2], 1.0),
        background=Color(250, 245, 235, 1.0),
        surface=Color(250, 245, 235, 1.0),
        surface_hover=Color(245, 240, 230, 1.0),
        border=Color(60, 50, 80, 1.0),
        text_primary=Color(60, 50, 80, 1.0),
        text_secondary=Color(120, 110, 130, 1.0),
        text_disabled=Color(180, 170, 190, 1.0),
        success=Color(70, 160, 110, 1.0),
        warning=Color(240, 190, 80, 1.0),
        error=Color(red[0], red[1], red[2], 1.0),
        info=Color(blue[0], blue[1], blue[2], 1.0),
        focus_ring=Color(255, 200, 80, 1.0),
        glass_bg=Color(255, 255, 255, 0.1),
        glass_blur_px=8.0,
    )
    return ThemeSpec(name=name, palette=palette, semantic=semantic)


@pytest.fixture()
def pencil_theme() -> ThemeSpec:
    theme = _make_pencil_theme("notebook_pencil_test")
    register_theme(theme)
    apply_theme(theme.name)
    return theme


@pytest.fixture()
def overlay(pencil_theme: ThemeSpec) -> NotebookGizmoOverlay:
    return NotebookGizmoOverlay()


# ---------------------------------------------------------------------------
# 1. Render emits expected primitives.
# ---------------------------------------------------------------------------


def test_render_translate_issues_drawlist_calls(overlay: NotebookGizmoOverlay):
    dl = MockDrawList()
    overlay.render(dl, (200.0, 150.0), "translate")
    # Translate mode draws polylines for the two shafts, triangles for
    # the arrowheads, and circles for the heart lobes.
    names = dl.names()
    assert "add_polyline" in names
    assert "add_triangle" in names
    assert "add_circle" in names
    # Sanity: there are at least two pencil-stroke polylines (one per axis).
    assert len(dl.by_name("add_polyline")) >= 2


def test_render_rotate_produces_ring_and_ticks(overlay: NotebookGizmoOverlay):
    dl = MockDrawList()
    overlay.render(dl, (300.0, 300.0), "rotate")
    # Ring is N dashed polyline segments.
    polylines = dl.by_name("add_polyline")
    assert len(polylines) >= NotebookGizmoOverlay.ROTATE_DASH_COUNT
    # Tick marks are crossed lines — 360/30 = 12 ticks × ≥2 lines each.
    lines = dl.by_name("add_line")
    assert len(lines) >= 12 * 2


def test_render_scale_has_four_corner_brackets(overlay: NotebookGizmoOverlay):
    dl = MockDrawList()
    overlay.render(dl, (400.0, 220.0), "scale")
    # Bow-tie bracket = 2 triangles per corner = 4 × 2 = 8 minimum.
    triangles = dl.by_name("add_triangle")
    assert len(triangles) >= 8


# ---------------------------------------------------------------------------
# 2. Theme colour resolution.
# ---------------------------------------------------------------------------


def test_x_arrow_color_uses_palette_pencil_red(overlay: NotebookGizmoOverlay,
                                               pencil_theme: ThemeSpec):
    dl = MockDrawList()
    overlay.render(dl, (100.0, 100.0), "translate")
    expected = pencil_theme.palette["pencil_red"].as_rgba_tuple()
    assert expected in dl.colors()


def test_y_arrow_color_uses_palette_pencil_blue(overlay: NotebookGizmoOverlay,
                                                pencil_theme: ThemeSpec):
    dl = MockDrawList()
    overlay.render(dl, (100.0, 100.0), "translate")
    expected = pencil_theme.palette["pencil_blue"].as_rgba_tuple()
    assert expected in dl.colors()


def test_pencil_red_falls_back_to_semantic_error_when_palette_missing():
    """No ``pencil_red`` palette entry → resolver should use semantic.error."""
    theme = _make_pencil_theme("notebook_no_palette_test")
    # Strip the palette so only the semantic fallback can satisfy the lookup.
    theme = ThemeSpec(
        name="notebook_no_palette_test_stripped",
        palette={},
        semantic=theme.semantic,
    )
    register_theme(theme)
    apply_theme(theme.name)
    g = NotebookGizmoOverlay()
    dl = MockDrawList()
    g.render(dl, (50.0, 50.0), "translate")
    expected_red = theme.semantic.error.as_rgba_tuple()
    expected_blue = theme.semantic.info.as_rgba_tuple()
    assert expected_red in dl.colors()
    assert expected_blue in dl.colors()


def test_theme_switch_updates_pencil_colors():
    theme_a = _make_pencil_theme("notebook_theme_a",
                                 red=(200, 60, 60, 255),
                                 blue=(40, 80, 200, 255))
    theme_b = _make_pencil_theme("notebook_theme_b",
                                 red=(255, 150, 20, 255),
                                 blue=(0, 200, 150, 255))
    register_theme(theme_a)
    register_theme(theme_b)

    g = NotebookGizmoOverlay()

    apply_theme(theme_a.name)
    dl_a = MockDrawList()
    g.render(dl_a, (100.0, 100.0), "translate")
    assert theme_a.palette["pencil_red"].as_rgba_tuple() in dl_a.colors()

    apply_theme(theme_b.name)
    dl_b = MockDrawList()
    g.render(dl_b, (100.0, 100.0), "translate")
    assert theme_b.palette["pencil_red"].as_rgba_tuple() in dl_b.colors()
    # And the old colour is no longer used.
    assert (
        theme_a.palette["pencil_red"].as_rgba_tuple() not in dl_b.colors()
    )


# ---------------------------------------------------------------------------
# 3. Hit testing.
# ---------------------------------------------------------------------------


def test_hit_test_returns_x_axis_for_mouse_over_x_tip(
    overlay: NotebookGizmoOverlay,
):
    target = (300.0, 200.0)
    overlay.render(MockDrawList(), target, "translate")
    tip_x = target[0] + overlay._arrow_len
    assert overlay.hit_test((int(tip_x), int(target[1]))) == "x_axis"


def test_hit_test_returns_y_axis_for_mouse_over_y_tip(
    overlay: NotebookGizmoOverlay,
):
    target = (300.0, 200.0)
    overlay.render(MockDrawList(), target, "translate")
    tip_y = target[1] - overlay._arrow_len
    assert overlay.hit_test((int(target[0]), int(tip_y))) == "y_axis"


def test_hit_test_returns_none_in_empty_space(
    overlay: NotebookGizmoOverlay,
):
    overlay.render(MockDrawList(), (100.0, 100.0), "translate")
    # Far away in every direction.
    assert overlay.hit_test((9999, 9999)) is None


def test_hit_test_returns_xy_center_for_mouse_over_center(
    overlay: NotebookGizmoOverlay,
):
    target = (250.0, 250.0)
    overlay.render(MockDrawList(), target, "translate")
    assert overlay.hit_test((int(target[0]), int(target[1]))) == "xy_center"


def test_hit_test_before_render_returns_none():
    g = NotebookGizmoOverlay()
    assert g.hit_test((10, 10)) is None


def test_hit_test_rotate_handle(overlay: NotebookGizmoOverlay):
    target = (400.0, 300.0)
    overlay.render(MockDrawList(), target, "rotate")
    handle = (int(target[0]), int(target[1] - overlay._rotate_r))
    assert overlay.hit_test(handle) == "rotate_handle"


def test_hit_test_scale_corners(overlay: NotebookGizmoOverlay):
    target = (150.0, 150.0)
    overlay.render(MockDrawList(), target, "scale")
    h = overlay._scale_h * 1.6
    assert overlay.hit_test(
        (int(target[0] - h), int(target[1] - h))
    ) == "scale_tl"
    assert overlay.hit_test(
        (int(target[0] + h), int(target[1] + h))
    ) == "scale_br"


# ---------------------------------------------------------------------------
# 4. Mode validation.
# ---------------------------------------------------------------------------


def test_render_rejects_unknown_mode(overlay: NotebookGizmoOverlay):
    with pytest.raises(ValueError):
        overlay.render(MockDrawList(), (0.0, 0.0), "wibble")


def test_render_rejects_bad_target(overlay: NotebookGizmoOverlay):
    with pytest.raises(TypeError):
        overlay.render(MockDrawList(), 12345, "translate")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 5. Deterministic wobble.
# ---------------------------------------------------------------------------


def test_wobble_is_deterministic_same_seed():
    a = _wobble_samples(_stable_hash((100.0, 100.0), "translate", 0),
                        12, 1.5)
    b = _wobble_samples(_stable_hash((100.0, 100.0), "translate", 0),
                        12, 1.5)
    assert a == b


def test_wobble_differs_for_different_position():
    a = _wobble_samples(_stable_hash((100.0, 100.0), "translate", 0),
                        12, 1.5)
    b = _wobble_samples(_stable_hash((200.0, 100.0), "translate", 0),
                        12, 1.5)
    assert a != b


def test_render_is_deterministic_for_same_inputs(
    overlay: NotebookGizmoOverlay,
):
    dl1 = MockDrawList()
    dl2 = MockDrawList()
    overlay.render(dl1, (123.0, 456.0), "translate")
    g2 = NotebookGizmoOverlay()
    g2.render(dl2, (123.0, 456.0), "translate")

    # Extract the polyline points from both runs and compare — these
    # carry the wobble so any non-determinism would show up here.
    pts1 = [a[0] for (a, _k) in dl1.by_name("add_polyline")]
    pts2 = [a[0] for (a, _k) in dl2.by_name("add_polyline")]
    assert pts1 == pts2


# ---------------------------------------------------------------------------
# 6. Hover / active visual states.
# ---------------------------------------------------------------------------


def test_hover_state_adds_shimmer_circle(overlay: NotebookGizmoOverlay):
    overlay.set_hover("x_axis")
    dl = MockDrawList()
    overlay.render(dl, (200.0, 200.0), "translate")
    # The shimmer is a non-filled add_circle call with fill=None.
    shimmers = [
        (a, k) for (a, k) in dl.by_name("add_circle")
        if k.get("fill") is None
    ]
    assert len(shimmers) >= 1


def test_active_drag_adds_highlighter_underline(
    overlay: NotebookGizmoOverlay,
    pencil_theme: ThemeSpec,
):
    overlay.set_active("x_axis")
    dl = MockDrawList()
    overlay.render(dl, (200.0, 200.0), "translate")
    # A thick line in highlighter colour should appear.
    thick_lines = [
        (a, k) for (a, k) in dl.by_name("add_line")
        if k.get("thickness", 0) >= 5.0
    ]
    assert len(thick_lines) >= 1
