"""TEENGIRL_NOTEBOOK starter theme.

Lined-paper-and-washi-tape diary aesthetic. Cream paper, bubblegum-pink
accents, mint, lilac, highlighter yellow, navy ink. Source design:
``docs/theme_teengirl_notebook_2026_06_03.md`` §1.1 (light palette) +
``docs/theme_diary_family_2026_06_03.md`` §3.1 (family rollup).

``palette`` carries both the design-doc named entries (``cream``,
``bubblegum_pink``…) *and* a semantic-token alias layer (``surface``,
``primary``…). ``semantic`` is the U1 contract widget code binds to;
``metadata`` carries non-colour authoring info (tape colour, creature
roster, source-doc backlink).
"""
from __future__ import annotations

from ..nine_slice import NineSlice
from ..svg_icon import SVGIcon
from ..theme_spec import (
    Color,
    Font,
    FrameStyle,
    Gradient,
    PanelFrameSet,
    SemanticTokens,
    ShaderEffect,
    ThemeSpec,
)


# Palette — design doc §1.1 named entries + semantic-token aliases.
_PALETTE: dict[str, Color] = {
    # Named entries (lifted verbatim from the design doc).
    "cream": Color(251, 247, 236, 1.0),                # #FBF7EC
    "lilac": Color(231, 221, 241, 1.0),                # #E7DDF1
    "bubblegum_pink": Color(255, 111, 181, 1.0),       # #FF6FB5
    "highlighter_yellow": Color(255, 224, 102, 220 / 255),  # #FFE066 @220
    "mint": Color(167, 231, 199, 1.0),                 # #A7E7C7
    "ink_navy": Color(31, 47, 102, 1.0),               # #1F2F66
    "muted_body": Color(122, 118, 137, 1.0),           # #7A7689
    "success": Color(91, 193, 138, 1.0),               # #5BC18A
    "warning": Color(242, 187, 85, 1.0),               # #F2BB55
    "error": Color(232, 90, 108, 1.0),                 # #E85A6C
    # Semantic tokens (U1 forward-compat — colours alias palette roles).
    "surface": Color(251, 247, 236, 1.0),
    "surface_alt": Color(231, 221, 241, 1.0),
    "on_surface": Color(31, 47, 102, 1.0),
    "primary": Color(255, 111, 181, 1.0),
    "on_primary": Color(251, 247, 236, 1.0),
    "secondary": Color(167, 231, 199, 1.0),
    "accent": Color(255, 224, 102, 220 / 255),
}


# Fonts — Caveat header, Quicksand body, Fira Code mono.
_FONTS: dict[str, Font] = {
    "header": Font(family="Caveat", size=22, weight="600"),
    "h1": Font(family="Caveat", size=28, weight="700"),
    "body": Font(family="Quicksand", size=14, weight="500"),
    "body_small": Font(family="Quicksand", size=13, weight="regular"),
    "caption": Font(family="Quicksand", size=12, weight="italic"),
    "mono": Font(family="Fira Code", size=14, weight="regular"),
}


# Nine-slices — washi-tape (procedural, no PNG).
_NINE_SLICES: dict[str, NineSlice] = {
    # Procedural washi-tape border; renderer feeds the bubblegum-pink fill.
    "washi_tape_panel": NineSlice(source=None, insets=(8, 8, 8, 8)),
    "washi_tape_toolbar": NineSlice(source=None, insets=(0, 8, 0, 8)),
    "washi_tape_modal": NineSlice(source=None, insets=(8, 8, 8, 8)),
}


# Inline SVG icons — heart / star / sparkle starter set (each ≤ 500 bytes).
_HEART_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M12 21 L4 13 A5 5 0 0 1 12 7 A5 5 0 0 1 20 13 Z"'
    ' fill="currentColor"/></svg>'
)
_STAR_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<polygon points="12,2 15,9 22,9 16,14 18,21 12,17 6,21 8,14 2,9 9,9"'
    ' fill="currentColor"/></svg>'
)
_SPARKLE_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<polygon points="12,2 14,10 22,12 14,14 12,22 10,14 2,12 10,10"'
    ' fill="currentColor"/></svg>'
)

_ICONS: dict[str, SVGIcon] = {
    "heart": SVGIcon(svg_xml=_HEART_SVG, size=24,
                     default_fill=(255, 111, 181, 255)),
    "star": SVGIcon(svg_xml=_STAR_SVG, size=24,
                    default_fill=(255, 224, 102, 255)),
    "sparkle": SVGIcon(svg_xml=_SPARKLE_SVG, size=24,
                       default_fill=(245, 200, 75, 255)),
}


# Sanity guard — sprint constraint says each inline SVG ≤ 500 bytes.
for _name, _svg in (("heart", _HEART_SVG), ("star", _STAR_SVG),
                    ("sparkle", _SPARKLE_SVG)):
    if len(_svg.encode("utf-8")) > 500:  # pragma: no cover - constant data
        raise AssertionError(
            f"teengirl_notebook: SVG {_name!r} exceeds 500 bytes "
            f"({len(_svg.encode('utf-8'))} bytes)"
        )


# Background shader — ruled paper with lilac rules + bubblegum-pink margin.
_BACKGROUND = ShaderEffect(
    name="ruled_paper",
    params={
        "paper_color": (251, 247, 236, 255),    # cream
        "line_color": (231, 221, 241, 255),     # lilac rules
        "margin_color": (255, 111, 181, 255),   # bubblegum-pink margin
        "line_spacing": 24,
        "margin_x": 32,
    },
)


# Semantic tokens — U1 named contract widget code binds to.
_PRIMARY_GRADIENT = Gradient(
    start=Color(255, 111, 181, 1.0),    # bubblegum pink
    end=Color(231, 221, 241, 1.0),      # lilac
    angle_deg=135.0,
)
_SEMANTIC = SemanticTokens(
    primary=Color(255, 111, 181, 1.0),
    primary_gradient=_PRIMARY_GRADIENT,
    secondary=Color(167, 231, 199, 1.0),       # mint
    accent=Color(255, 224, 102, 220 / 255),    # highlighter yellow
    background=Color(251, 247, 236, 1.0),      # cream
    surface=Color(244, 239, 227, 1.0),         # panel base
    surface_hover=Color(231, 221, 241, 1.0),   # lilac hover
    border=Color(184, 176, 160, 200 / 255),    # pencil grey
    text_primary=Color(31, 47, 102, 1.0),      # ink navy
    text_secondary=Color(59, 59, 69, 1.0),     # charcoal grey
    text_disabled=Color(177, 172, 184, 1.0),
    success=Color(91, 193, 138, 1.0),
    warning=Color(242, 187, 85, 1.0),
    error=Color(232, 90, 108, 1.0),
    info=Color(127, 200, 232, 1.0),            # sky blue
    focus_ring=Color(255, 111, 181, 1.0),
    glass_bg=Color(251, 247, 236, 0.85),
    glass_blur_px=12.0,
)


# Frame styles — 1 px lilac border, rounding 10 px, padding 10x8,
# soft pink drop shadow; sidebar bumps rounding to 12 px for a softer
# inspector silhouette.
_FRAMES = PanelFrameSet(
    default=FrameStyle(
        border_size=1.0,
        border_color=Color(231, 221, 241, 1.0),    # lilac
        rounding=10.0,
        padding_x=10,
        padding_y=8,
        shadow_size=6.0,
        shadow_color=Color(255, 111, 181, 0.25),   # soft pink
        child_rounding=8.0,
        child_border_size=0.5,
        grip_size=12.0,
        grip_rounding=6.0,
        title_bar_height=24,
    ),
    sidebar=FrameStyle(
        border_size=1.0,
        border_color=Color(231, 221, 241, 1.0),
        rounding=12.0,
        padding_x=10,
        padding_y=8,
        shadow_size=6.0,
        shadow_color=Color(255, 111, 181, 0.25),
        child_rounding=10.0,
        grip_rounding=6.0,
    ),
)


# Metadata — string-only as ThemeSpec.metadata demands.
_METADATA: dict[str, str] = {
    "tape_color": "#FF6FB5",
    "tape_alt_color": "#A7E7C7",
    "seasonal_flavour": "summer",
    "creature_roster": "fox_01,butterfly_01",
    "creature_roster_count": "2",
    "variant": "light",
    "family": "diary",
    "source_doc": "docs/theme_teengirl_notebook_2026_06_03.md",
}


TEENGIRL_NOTEBOOK: ThemeSpec = ThemeSpec(
    name="teengirl_notebook",
    semantic=_SEMANTIC,
    palette=_PALETTE,
    fonts=_FONTS,
    nine_slices=_NINE_SLICES,
    icons=_ICONS,
    frames=_FRAMES,
    background_shader=_BACKGROUND,
    metadata=_METADATA,
)


__all__ = ["TEENGIRL_NOTEBOOK"]
