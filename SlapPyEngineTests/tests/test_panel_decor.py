"""Tests for :mod:`pharos_engine.ui.editor.panel_decor`.

Exercises every :class:`DividerStyle` (each style should register at
least one drawlist op via the recording stub), the washi-tape corner
renderer (colour lookup + rotation + drop shadow + torn edge), the
theme-driven default resolution, and the nested-panel adjacency helper
that decides *where* a divider goes.

The tests are pure-Python — Dear PyGui is never imported. Every
drawlist op is captured by a tiny recording stub so we can assert on
op counts, colours, and geometry without a live viewport.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pytest

from pharos_engine.ui.editor.panel_decor import (
    DividerSpec,
    DividerStyle,
    PanelDecor,
    WashiCornerSpec,
    WashiCornerStyle,
    collect_divider_edges,
    corner_specs_for_floating,
    dashed_segments,
    dotted_centers,
    flower_petals,
    heart_polygon,
    sine_wave_points,
    star_polygon,
    washi_pigment,
    washi_rect_corners,
)
from pharos_engine.ui.theme.theme_spec import (
    Color,
    Gradient,
    PanelDecorConfig,
    SemanticTokens,
    ThemeSpec,
)


# ---------------------------------------------------------------------------
# Recording stub for the drawlist
# ---------------------------------------------------------------------------


class _RecordingDrawList:
    """Capture every drawlist call in a plain list of dicts."""

    def __init__(self) -> None:
        self.ops: list[dict[str, Any]] = []

    def draw_polyline(self, **kwargs: Any) -> None:
        self.ops.append({"op": "polyline", **kwargs})

    def draw_line(self, **kwargs: Any) -> None:
        self.ops.append({"op": "line", **kwargs})

    def draw_circle(self, **kwargs: Any) -> None:
        self.ops.append({"op": "circle", **kwargs})

    def draw_polygon(self, **kwargs: Any) -> None:
        self.ops.append({"op": "polygon", **kwargs})

    def ops_of(self, kind: str) -> list[dict[str, Any]]:
        return [op for op in self.ops if op["op"] == kind]


# ---------------------------------------------------------------------------
# Minimal ThemeSpec fixtures — enough for the decor renderer to resolve
# an accent colour and default divider / corner style.
# ---------------------------------------------------------------------------


def _make_theme(divider_style: str, corner_style: str) -> ThemeSpec:
    accent = Color(200, 100, 150, 1.0)
    grad = Gradient(start=accent, end=accent, angle_deg=135.0)
    semantic = SemanticTokens(
        primary=accent,
        primary_gradient=grad,
        secondary=accent,
        accent=accent,
        background=Color(255, 255, 255, 1.0),
        surface=Color(240, 240, 240, 1.0),
        surface_hover=Color(220, 220, 220, 1.0),
        border=Color(150, 150, 150, 1.0),
        text_primary=Color(20, 20, 20, 1.0),
        text_secondary=Color(80, 80, 80, 1.0),
        text_disabled=Color(180, 180, 180, 1.0),
        success=Color(80, 200, 120, 1.0),
        warning=Color(240, 200, 80, 1.0),
        error=Color(240, 80, 80, 1.0),
        info=Color(80, 160, 240, 1.0),
        focus_ring=accent,
        glass_bg=Color(255, 255, 255, 0.6),
        glass_blur_px=8.0,
    )
    return ThemeSpec(
        name=f"test_{divider_style}_{corner_style}",
        semantic=semantic,
        decor=PanelDecorConfig(
            divider_style=divider_style,
            corner_style=corner_style,
        ),
    )


@pytest.fixture
def kawaii_theme() -> ThemeSpec:
    return _make_theme("heart_chain", "tape_pink")


@pytest.fixture
def bullet_theme() -> ThemeSpec:
    return _make_theme("dashed", "tape_yellow")


# ---------------------------------------------------------------------------
# Enum coercion
# ---------------------------------------------------------------------------


class TestEnums:
    def test_divider_style_from_str_roundtrip(self):
        assert DividerStyle.from_str("wavy") is DividerStyle.WAVY
        assert DividerStyle.from_str("heart_chain") is DividerStyle.HEART_CHAIN

    def test_divider_style_from_str_rejects_unknown(self):
        with pytest.raises(ValueError):
            DividerStyle.from_str("triangle_chain")

    def test_washi_style_from_str_roundtrip(self):
        assert (WashiCornerStyle.from_str("tape_pink")
                is WashiCornerStyle.TAPE_PINK)

    def test_washi_style_from_str_rejects_unknown(self):
        with pytest.raises(ValueError):
            WashiCornerStyle.from_str("tape_neon_green")


# ---------------------------------------------------------------------------
# Divider math helpers
# ---------------------------------------------------------------------------


class TestDividerMath:
    def test_sine_wave_points_endpoints(self):
        pts = sine_wave_points((0, 0), (160, 0))
        assert pts[0] == pytest.approx((0.0, 0.0), abs=1e-6)
        assert pts[-1] == pytest.approx((160.0, 0.0), abs=1e-6)

    def test_sine_wave_point_count_scales_with_length(self):
        short = sine_wave_points((0, 0), (32, 0))
        long = sine_wave_points((0, 0), (320, 0))
        # 320 / 32 = 10x length, so we expect ~10x samples (within +/-2).
        assert len(long) > len(short) * 8

    def test_sine_wave_amplitude_bounded(self):
        pts = sine_wave_points((0, 0), (160, 0))
        # Excursion must sit inside ±amplitude (=4 px).
        assert max(abs(y) for _, y in pts) <= 4.0 + 1e-6

    def test_dotted_centers_spacing(self):
        centers = dotted_centers((0, 0), (32, 0))
        # 32 / 8 = 4 gaps → 5 dots (0, 8, 16, 24, 32).
        assert len(centers) == 5
        assert centers[0] == (0.0, 0.0)
        assert centers[-1] == (32.0, 0.0)

    def test_dashed_segments_alternate(self):
        segs = dashed_segments((0, 0), (24, 0))
        # 24 px / (8 + 4) = 2 strides → 2 dashes.
        assert len(segs) == 2
        (a1, b1), (a2, b2) = segs
        # First dash: 0..8, second dash: 12..20.
        assert a1 == (0.0, 0.0)
        assert b1 == (8.0, 0.0)
        assert a2 == (12.0, 0.0)
        assert b2 == (20.0, 0.0)

    def test_star_polygon_has_eight_vertices(self):
        pts = star_polygon((0.0, 0.0), radius=4.0)
        assert len(pts) == 8

    def test_heart_polygon_sample_count(self):
        pts = heart_polygon((0.0, 0.0), radius=3.0)
        assert len(pts) == 24

    def test_flower_petals_count(self):
        pts = flower_petals((0.0, 0.0), radius=4.0)
        assert len(pts) == 5


# ---------------------------------------------------------------------------
# Divider rendering — each style emits at least one drawlist op
# ---------------------------------------------------------------------------


class TestRenderDivider:
    def _renderer(self, theme: ThemeSpec) -> PanelDecor:
        return PanelDecor(theme_getter=lambda: theme)

    @pytest.mark.parametrize("style", list(DividerStyle))
    def test_every_style_emits_ops(self, style, kawaii_theme):
        dl = _RecordingDrawList()
        decor = self._renderer(kawaii_theme)
        spec = DividerSpec(orientation="horizontal", style=style)
        result = decor.render_divider(dl, (0, 100), (160, 100), spec)
        assert result["draw_calls"] >= 1
        assert len(dl.ops) == result["draw_calls"]

    def test_wavy_uses_polyline(self, kawaii_theme):
        dl = _RecordingDrawList()
        decor = self._renderer(kawaii_theme)
        spec = DividerSpec(
            orientation="horizontal", style=DividerStyle.WAVY,
        )
        decor.render_divider(dl, (0, 100), (160, 100), spec)
        assert len(dl.ops_of("polyline")) == 1
        pts = dl.ops_of("polyline")[0]["points"]
        # 160 px / 16 px period * 16 samples/period + 1 = 161 samples.
        assert len(pts) == 161

    def test_dotted_uses_circles(self, kawaii_theme):
        dl = _RecordingDrawList()
        decor = self._renderer(kawaii_theme)
        spec = DividerSpec(
            orientation="horizontal", style=DividerStyle.DOTTED,
        )
        decor.render_divider(dl, (0, 100), (32, 100), spec)
        # 5 dots at 0, 8, 16, 24, 32.
        assert len(dl.ops_of("circle")) == 5

    def test_dashed_uses_lines(self, kawaii_theme):
        dl = _RecordingDrawList()
        decor = self._renderer(kawaii_theme)
        spec = DividerSpec(
            orientation="horizontal", style=DividerStyle.DASHED,
        )
        decor.render_divider(dl, (0, 100), (24, 100), spec)
        assert len(dl.ops_of("line")) == 2

    def test_star_chain_uses_polygons(self, kawaii_theme):
        dl = _RecordingDrawList()
        decor = self._renderer(kawaii_theme)
        spec = DividerSpec(
            orientation="horizontal", style=DividerStyle.STAR_CHAIN,
        )
        decor.render_divider(dl, (0, 100), (48, 100), spec)
        # 48 / 16 = 3 chain slots (offset half-spacing).
        assert len(dl.ops_of("polygon")) >= 2

    def test_pencil_line_taper_uses_multiple_polylines(self, kawaii_theme):
        dl = _RecordingDrawList()
        decor = self._renderer(kawaii_theme)
        spec = DividerSpec(
            orientation="horizontal", style=DividerStyle.PENCIL_LINE,
        )
        decor.render_divider(dl, (0, 100), (64, 100), spec)
        # Main run + 2 tapered caps = 3 polylines.
        assert len(dl.ops_of("polyline")) == 3

    def test_divider_uses_theme_accent(self, kawaii_theme):
        dl = _RecordingDrawList()
        decor = self._renderer(kawaii_theme)
        spec = DividerSpec(
            orientation="horizontal", style=DividerStyle.WAVY,
        )
        decor.render_divider(dl, (0, 100), (64, 100), spec)
        # kawaii_theme accent = (200, 100, 150, 255).
        color = dl.ops_of("polyline")[0]["color"]
        assert list(color) == [200, 100, 150, 255]

    def test_divider_explicit_color_override(self, kawaii_theme):
        dl = _RecordingDrawList()
        decor = self._renderer(kawaii_theme)
        spec = DividerSpec(
            orientation="horizontal",
            style=DividerStyle.WAVY,
            color=(10, 20, 30, 200),
        )
        decor.render_divider(dl, (0, 100), (64, 100), spec)
        assert dl.ops_of("polyline")[0]["color"] == [10, 20, 30, 200]

    def test_render_divider_rejects_wrong_spec_type(self, kawaii_theme):
        dl = _RecordingDrawList()
        decor = self._renderer(kawaii_theme)
        with pytest.raises(TypeError):
            decor.render_divider(dl, (0, 0), (1, 0), "not a spec")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Corner rendering
# ---------------------------------------------------------------------------


class TestRenderCorner:
    def _renderer(self, theme: ThemeSpec) -> PanelDecor:
        return PanelDecor(theme_getter=lambda: theme)

    def test_corner_emits_shadow_body_and_torn_edges(self, kawaii_theme):
        dl = _RecordingDrawList()
        decor = self._renderer(kawaii_theme)
        spec = WashiCornerSpec(
            corner="TL", style=WashiCornerStyle.TAPE_PINK,
        )
        result = decor.render_corner(dl, (10, 10, 400, 300), spec)
        polys = dl.ops_of("polygon")
        lines = dl.ops_of("line")
        # 2 polygons: shadow + body.
        assert len(polys) == 2
        # 6 torn-edge dashes (3 per long side).
        assert len(lines) == 6
        assert result["draw_calls"] == len(polys) + len(lines)

    def test_corner_body_uses_pigment(self, kawaii_theme):
        dl = _RecordingDrawList()
        decor = self._renderer(kawaii_theme)
        spec = WashiCornerSpec(
            corner="TR", style=WashiCornerStyle.TAPE_BLUE,
        )
        decor.render_corner(dl, (0, 0, 300, 300), spec)
        # Body is the *second* polygon (shadow drawn first).
        body = dl.ops_of("polygon")[1]
        assert body["fill"] == list(washi_pigment(WashiCornerStyle.TAPE_BLUE))

    def test_corner_shadow_is_semi_translucent_black(self, kawaii_theme):
        dl = _RecordingDrawList()
        decor = self._renderer(kawaii_theme)
        spec = WashiCornerSpec(
            corner="BL", style=WashiCornerStyle.TAPE_MINT,
        )
        decor.render_corner(dl, (0, 0, 100, 100), spec)
        shadow = dl.ops_of("polygon")[0]
        # RGB=0, alpha < body.
        assert shadow["fill"][0] == 0
        assert shadow["fill"][1] == 0
        assert shadow["fill"][2] == 0
        assert 0 < shadow["fill"][3] < 220

    def test_corner_rotation_applied_to_rect(self):
        # Compare unrotated vs rotated rect geometry directly.
        r0 = washi_rect_corners((0.0, 0.0), "TL", 32, 0.0)
        r1 = washi_rect_corners((0.0, 0.0), "TL", 32, 15.0)
        # Anchor point (index 0-ish) stays roughly on the anchor; the
        # far corner moves.
        far0 = r0[1]
        far1 = r1[1]
        assert far0 != pytest.approx(far1, abs=1e-6)

    def test_render_corner_rejects_wrong_bounds_type(self, kawaii_theme):
        dl = _RecordingDrawList()
        decor = self._renderer(kawaii_theme)
        spec = WashiCornerSpec(
            corner="TL", style=WashiCornerStyle.TAPE_PINK,
        )
        with pytest.raises(TypeError):
            decor.render_corner(dl, "not bounds", spec)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Theme default resolution
# ---------------------------------------------------------------------------


class TestThemeDefaults:
    def test_default_divider_uses_theme_style(self, kawaii_theme):
        decor = PanelDecor(theme_getter=lambda: kawaii_theme)
        spec = decor.default_divider_for_theme()
        assert spec.style is DividerStyle.HEART_CHAIN

    def test_default_corner_uses_theme_style(self, kawaii_theme):
        decor = PanelDecor(theme_getter=lambda: kawaii_theme)
        spec = decor.default_corner_for_theme(corner="TR")
        assert spec.style is WashiCornerStyle.TAPE_PINK
        assert spec.corner == "TR"

    def test_theme_switch_swaps_default_style(
        self, kawaii_theme, bullet_theme,
    ):
        active = {"theme": kawaii_theme}
        decor = PanelDecor(theme_getter=lambda: active["theme"])
        d1 = decor.default_divider_for_theme()
        c1 = decor.default_corner_for_theme(corner="TL")
        active["theme"] = bullet_theme
        d2 = decor.default_divider_for_theme()
        c2 = decor.default_corner_for_theme(corner="TL")
        assert d1.style is DividerStyle.HEART_CHAIN
        assert d2.style is DividerStyle.DASHED
        assert c1.style is WashiCornerStyle.TAPE_PINK
        assert c2.style is WashiCornerStyle.TAPE_YELLOW

    def test_per_kind_override(self):
        theme = _make_theme("wavy", "tape_pink")
        theme.decor.per_kind["toolbar"] = ("dotted", "tape_blue")
        decor = PanelDecor(theme_getter=lambda: theme)
        d = decor.default_divider_for_theme(kind="toolbar")
        c = decor.default_corner_for_theme(kind="toolbar", corner="TL")
        assert d.style is DividerStyle.DOTTED
        assert c.style is WashiCornerStyle.TAPE_BLUE
        # Sidebar (no override) falls back to the theme default.
        assert (decor.default_divider_for_theme(kind="sidebar").style
                is DividerStyle.WAVY)

    def test_defaults_survive_no_theme(self):
        def _raise() -> Any:
            raise LookupError("no active theme")

        decor = PanelDecor(theme_getter=_raise)
        spec = decor.default_divider_for_theme()
        assert isinstance(spec, DividerSpec)
        assert spec.style is DividerStyle.WAVY


# ---------------------------------------------------------------------------
# Floating vs docked window corners
# ---------------------------------------------------------------------------


class TestFloatingCorners:
    def test_floating_panel_gets_four_corners(self):
        specs = corner_specs_for_floating(
            is_floating=True, style=WashiCornerStyle.TAPE_PINK,
        )
        assert len(specs) == 4
        assert sorted(s.corner for s in specs) == ["BL", "BR", "TL", "TR"]

    def test_floating_panel_can_get_two_corners(self):
        specs = corner_specs_for_floating(
            is_floating=True, style=WashiCornerStyle.TAPE_BLUE,
            corners=("TL", "TR"),
        )
        assert len(specs) == 2
        assert {s.corner for s in specs} == {"TL", "TR"}

    def test_docked_panel_gets_zero_corners(self):
        specs = corner_specs_for_floating(
            is_floating=False, style=WashiCornerStyle.TAPE_PINK,
        )
        assert specs == []

    def test_floating_corners_have_distinct_rotations(self):
        specs = corner_specs_for_floating(
            is_floating=True, style=WashiCornerStyle.TAPE_PINK,
        )
        rotations = [s.rotation_deg for s in specs]
        # 4 distinct phases so no two corners look identical.
        assert len(set(rotations)) == 4

    def test_floating_corners_accept_string_style(self):
        specs = corner_specs_for_floating(
            is_floating=True, style="tape_mint",
        )
        assert all(s.style is WashiCornerStyle.TAPE_MINT for s in specs)


# ---------------------------------------------------------------------------
# Nested-panel adjacency
# ---------------------------------------------------------------------------


class TestAdjacencyDetection:
    def test_side_by_side_panels_share_vertical_edge(self):
        # Panel A occupies (0, 0, 100, 200); B occupies (100, 0, 100, 200).
        edges = collect_divider_edges([(0, 0, 100, 200), (100, 0, 100, 200)])
        assert len(edges) == 1
        e = edges[0]
        assert e.orientation == "vertical"
        assert e.p1 == (100, 0)
        assert e.p2 == (100, 200)

    def test_stacked_panels_share_horizontal_edge(self):
        edges = collect_divider_edges([(0, 0, 200, 100), (0, 100, 200, 100)])
        assert len(edges) == 1
        e = edges[0]
        assert e.orientation == "horizontal"
        assert e.p1 == (0, 100)
        assert e.p2 == (200, 100)

    def test_disjoint_panels_yield_no_edges(self):
        edges = collect_divider_edges([(0, 0, 50, 50), (100, 100, 50, 50)])
        assert edges == []

    def test_partial_overlap_span_only(self):
        # A occupies (0, 0, 100, 100); B occupies (100, 40, 100, 200).
        # Shared vertical edge spans y in [40, 100].
        edges = collect_divider_edges([(0, 0, 100, 100), (100, 40, 100, 200)])
        assert len(edges) == 1
        e = edges[0]
        assert e.orientation == "vertical"
        assert e.p1 == (100, 40)
        assert e.p2 == (100, 100)

    def test_three_panel_layout_yields_two_edges(self):
        # Three side-by-side panels — 2 vertical dividers between them.
        panels = [
            (0, 0, 100, 200),
            (100, 0, 100, 200),
            (200, 0, 100, 200),
        ]
        edges = collect_divider_edges(panels)
        assert len(edges) == 2
        assert all(e.orientation == "vertical" for e in edges)

    def test_grid_of_four_yields_four_edges(self):
        # 2x2 grid — 2 vertical + 2 horizontal edges.
        panels = [
            (0, 0, 100, 100),
            (100, 0, 100, 100),
            (0, 100, 100, 100),
            (100, 100, 100, 100),
        ]
        edges = collect_divider_edges(panels)
        assert len(edges) == 4
        orients = sorted(e.orientation for e in edges)
        assert orients == ["horizontal", "horizontal", "vertical", "vertical"]


# ---------------------------------------------------------------------------
# Integration with the 6 shipping diary themes
# ---------------------------------------------------------------------------


class TestShippingThemes:
    """Sanity check — each diary theme carries a valid PanelDecorConfig."""

    @pytest.mark.parametrize("module_name,attr_name,expected_divider,expected_corner", [
        ("pharos_engine.ui.theme.themes.kawaii_planner",
         "KAWAII_PLANNER", "heart_chain", "tape_pink"),
        ("pharos_engine.ui.theme.themes.bullet_journal",
         "BULLET_JOURNAL", "dashed", "tape_yellow"),
        ("pharos_engine.ui.theme.themes.cottagecore_garden",
         "COTTAGECORE_GARDEN", "flower_chain", "tape_mint"),
        ("pharos_engine.ui.theme.themes.cozy_diary",
         "COZY_DIARY", "pencil_line", "tape_lavender"),
        ("pharos_engine.ui.theme.themes.scrapbook_summer",
         "SCRAPBOOK_SUMMER", "star_chain", "tape_blue"),
        ("pharos_engine.ui.theme.themes.teengirl_notebook",
         "TEENGIRL_NOTEBOOK", "wavy", "tape_pink"),
    ])
    def test_theme_has_expected_decor(
        self, module_name, attr_name, expected_divider, expected_corner,
    ):
        import importlib
        module = importlib.import_module(module_name)
        theme = getattr(module, attr_name)
        assert theme.decor.divider_style == expected_divider
        assert theme.decor.corner_style == expected_corner
