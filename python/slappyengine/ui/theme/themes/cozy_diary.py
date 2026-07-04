"""COZY_DIARY starter theme.

Warm autumn leather-journal aesthetic — dusty rose, caramel, sage,
cream, sepia ink. Source design:
``docs/theme_diary_family_2026_06_03.md`` §3.3.

Background renders through the existing ``ruled_paper`` shader recipe
parameterised with cream / sepia hues so the page reads as parchment
rather than a school notebook. Leather-edge nine-slice is procedural;
the renderer paints it from the ``leather_edge`` palette colour.
"""
from __future__ import annotations

from ..nine_slice import NineSlice
from ..svg_icon import SVGIcon
from ..theme_spec import (
    Color,
    Font,
    FrameStyle,
    Gradient,
    PanelDecorConfig,
    PanelFrameSet,
    SemanticTokens,
    ShaderEffect,
    ThemeSpec,
)


# Palette — design doc §3.3 names + semantic-token aliases.
_PALETTE: dict[str, Color] = {
    # Named palette entries.
    "cream": Color(245, 237, 221, 1.0),                # #F5EDDD
    "dusty_rose": Color(216, 162, 168, 1.0),           # #D8A2A8
    "caramel": Color(176, 122, 92, 1.0),               # #B07A5C
    "sage": Color(141, 167, 124, 1.0),                 # #8DA77C
    "ink": Color(46, 41, 38, 1.0),                     # #2E2926
    "leather_edge": Color(124, 85, 50, 230 / 255),     # #7C5532
    "body": Color(92, 70, 48, 1.0),                    # coffee brown
    "muted_body": Color(140, 122, 102, 1.0),
    "success": Color(122, 170, 102, 1.0),
    "warning": Color(212, 160, 74, 1.0),
    "error": Color(184, 80, 64, 1.0),
    # Semantic tokens — U1 forward-compat aliases.
    "surface": Color(245, 237, 221, 1.0),
    "surface_alt": Color(239, 224, 190, 1.0),
    "on_surface": Color(46, 41, 38, 1.0),
    "primary": Color(216, 162, 168, 1.0),
    "on_primary": Color(46, 41, 38, 1.0),
    "secondary": Color(141, 167, 124, 1.0),
    "accent": Color(176, 122, 92, 1.0),
}


# Fonts — Patrick Hand header, Quicksand body, JetBrains Mono code.
_FONTS: dict[str, Font] = {
    "header": Font(family="Patrick Hand", size=22, weight="600"),
    "h1": Font(family="Patrick Hand", size=28, weight="700"),
    "body": Font(family="Quicksand", size=14, weight="500"),
    "body_small": Font(family="Quicksand", size=13, weight="regular"),
    "caption": Font(family="Quicksand", size=12, weight="italic"),
    "mono": Font(family="JetBrains Mono", size=14, weight="regular"),
}


# Nine-slices — leather edge + stitched strap; procedural.
_NINE_SLICES: dict[str, NineSlice] = {
    "leather_edge_panel": NineSlice(source=None, insets=(8, 8, 8, 8)),
    "leather_strap_toolbar": NineSlice(source=None, insets=(0, 8, 0, 8)),
    "embossed_leather_modal": NineSlice(source=None, insets=(10, 10, 10, 10)),
}


# Inline SVG icons — leaf / acorn / bookmark starter set (each ≤ 500 bytes).
_LEAF_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M4 20 C4 10 10 4 20 4 C20 14 14 20 4 20 Z"'
    ' fill="currentColor"/>'
    '<line x1="4" y1="20" x2="20" y2="4" stroke="#2E2926"'
    ' stroke-width="1"/></svg>'
)
_ACORN_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M6 10 L18 10 L17 18 L12 22 L7 18 Z" fill="currentColor"/>'
    '<rect x="5" y="6" width="14" height="5" fill="#7C5532"/></svg>'
)
_BOOKMARK_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<polygon points="6,3 18,3 18,21 12,17 6,21" fill="currentColor"/></svg>'
)

_ICONS: dict[str, SVGIcon] = {
    "leaf": SVGIcon(svg_xml=_LEAF_SVG, size=24,
                    default_fill=(141, 167, 124, 255)),
    "acorn": SVGIcon(svg_xml=_ACORN_SVG, size=24,
                     default_fill=(176, 122, 92, 255)),
    "bookmark": SVGIcon(svg_xml=_BOOKMARK_SVG, size=24,
                        default_fill=(216, 162, 168, 255)),
}

for _name, _svg in (("leaf", _LEAF_SVG), ("acorn", _ACORN_SVG),
                    ("bookmark", _BOOKMARK_SVG)):
    if len(_svg.encode("utf-8")) > 500:  # pragma: no cover - constant data
        raise AssertionError(
            f"cozy_diary: SVG {_name!r} exceeds 500 bytes "
            f"({len(_svg.encode('utf-8'))} bytes)"
        )


# Background shader — parchment via ruled_paper with sepia tones.
_BACKGROUND = ShaderEffect(
    name="ruled_paper",
    params={
        "paper_color": (245, 237, 221, 255),    # parchment cream
        "line_color": (124, 85, 50, 100),       # brown ink, parchment fibre
        "margin_color": (176, 122, 92, 180),    # caramel margin (subtle)
        "line_spacing": 28,
        "margin_x": 28,
    },
)


# Semantic tokens — U1 named contract widget code binds to.
_PRIMARY_GRADIENT = Gradient(
    start=Color(216, 162, 168, 1.0),  # dusty rose
    end=Color(176, 122, 92, 1.0),     # caramel
    angle_deg=135.0,
)

_SEMANTIC = SemanticTokens(
    primary=Color(216, 162, 168, 1.0),       # dusty rose
    primary_gradient=_PRIMARY_GRADIENT,
    secondary=Color(141, 167, 124, 1.0),     # sage
    accent=Color(176, 122, 92, 1.0),         # caramel
    background=Color(245, 237, 221, 1.0),    # cream
    surface=Color(239, 224, 190, 1.0),       # warm cream panel
    surface_hover=Color(245, 230, 200, 1.0),
    border=Color(124, 85, 50, 230 / 255),    # leather edge
    text_primary=Color(46, 41, 38, 1.0),     # sepia ink
    text_secondary=Color(92, 70, 48, 1.0),   # coffee brown
    text_disabled=Color(160, 142, 122, 1.0),
    success=Color(122, 170, 102, 1.0),
    warning=Color(212, 160, 74, 1.0),
    error=Color(184, 80, 64, 1.0),
    info=Color(155, 178, 140, 1.0),
    focus_ring=Color(216, 162, 168, 1.0),
    glass_bg=Color(245, 237, 221, 0.85),
    glass_blur_px=10.0,
)


# Frame styles — 2 px caramel leather border, rounding 6 px (compact
# bookbinding feel), padding 12x10, larger sage drop shadow.
_FRAMES = PanelFrameSet(
    default=FrameStyle(
        border_size=2.0,
        border_color=Color(176, 122, 92, 1.0),       # caramel
        rounding=6.0,
        padding_x=12,
        padding_y=10,
        shadow_size=8.0,
        shadow_color=Color(141, 167, 124, 0.35),     # sage shadow
        child_rounding=4.0,
        child_border_size=1.0,
        grip_size=12.0,
        grip_rounding=3.0,
        title_bar_height=26,
    ),
    modal=FrameStyle(
        border_size=2.5,
        border_color=Color(124, 85, 50, 1.0),         # leather_edge
        rounding=6.0,
        padding_x=14,
        padding_y=12,
        shadow_size=10.0,
        shadow_color=Color(141, 167, 124, 0.4),
        child_rounding=4.0,
        child_border_size=1.0,
    ),
)


# Metadata — string-only as ThemeSpec.metadata demands.
_METADATA: dict[str, str] = {
    "tape_color": "#7C5532",
    "tape_alt_color": "#8DA77C",
    "seasonal_flavour": "autumn",
    "creature_roster": "red_panda_01,fox_01,leaf_01",
    "creature_roster_count": "3",
    "variant": "light",
    "family": "diary",
    "source_doc": "docs/theme_diary_family_2026_06_03.md",
}


# Decor — warm pencil rule + lavender washi tape.
_DECOR = PanelDecorConfig(
    divider_style="pencil_line",
    corner_style="tape_lavender",
    divider_thickness_px=2,
    corner_size_px=32,
)


COZY_DIARY: ThemeSpec = ThemeSpec(
    name="cozy_diary",
    semantic=_SEMANTIC,
    palette=_PALETTE,
    fonts=_FONTS,
    nine_slices=_NINE_SLICES,
    icons=_ICONS,
    frames=_FRAMES,
    decor=_DECOR,
    background_shader=_BACKGROUND,
    metadata=_METADATA,
)


__all__ = ["COZY_DIARY"]
