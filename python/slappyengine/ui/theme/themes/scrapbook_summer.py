"""SCRAPBOOK_SUMMER starter theme.

Bright photographic holiday-vibes diary — sky-blue, sunshine-yellow,
watermelon-pink, grass-green over paper-white. Source design:
``docs/theme_diary_family_2026_06_03.md`` §3.2 (with the user-supplied
palette refresh for the v0.4 Phase C rollout).

Background renders through the ``watercolor_wash`` shader (sky-blue +
sunshine-yellow splats at 30 % opacity over paper-white) so the page
reads as bleached scrapbook paper rather than a flat fill. Polaroid +
washi photo-corner nine-slices are procedural; renderer paints them
from the ``kraft_paper`` palette colour.
"""
from __future__ import annotations

from ..nine_slice import NineSlice
from ..svg_icon import SVGIcon
from ..theme_spec import (
    Color,
    Font,
    Gradient,
    SemanticTokens,
    ShaderEffect,
    ThemeSpec,
)


# Palette — design doc §3.2 (user-refreshed v0.4 sprint hexes) + tokens.
_PALETTE: dict[str, Color] = {
    # Named entries (sprint brief hexes).
    "sky_blue": Color(135, 206, 235, 1.0),             # #87CEEB
    "sunshine_yellow": Color(255, 217, 61, 1.0),       # #FFD93D
    "watermelon_pink": Color(255, 107, 157, 1.0),      # #FF6B9D
    "grass_green": Color(107, 203, 119, 1.0),          # #6BCB77
    "paper_white": Color(250, 250, 250, 1.0),          # #FAFAFA
    "ink_charcoal": Color(42, 42, 42, 1.0),            # #2A2A2A
    "kraft_paper": Color(198, 168, 116, 230 / 255),    # photo-corner brown
    "body": Color(59, 70, 84, 1.0),                    # slate body
    "muted_body": Color(120, 130, 145, 1.0),
    "success": Color(91, 193, 138, 1.0),
    "warning": Color(242, 187, 85, 1.0),
    "error": Color(232, 90, 108, 1.0),
    # Semantic tokens — U1 forward-compat aliases.
    "surface": Color(250, 250, 250, 1.0),
    "surface_alt": Color(244, 236, 216, 1.0),
    "on_surface": Color(42, 42, 42, 1.0),
    "primary": Color(135, 206, 235, 1.0),              # sky blue
    "on_primary": Color(42, 42, 42, 1.0),
    "secondary": Color(255, 217, 61, 1.0),             # sunshine yellow
    "accent": Color(255, 107, 157, 1.0),               # watermelon pink
}


# Fonts — Caveat header, Quicksand body, Fira Code mono.
_FONTS: dict[str, Font] = {
    "header": Font(family="Caveat", size=24, weight="600"),
    "h1": Font(family="Caveat", size=32, weight="700"),
    "body": Font(family="Quicksand", size=14, weight="500"),
    "body_small": Font(family="Quicksand", size=13, weight="regular"),
    "caption": Font(family="Quicksand", size=12, weight="italic"),
    "mono": Font(family="Fira Code", size=14, weight="regular"),
}


# Nine-slices — polaroid + washi photo-corners (procedural, no PNG).
_NINE_SLICES: dict[str, NineSlice] = {
    "polaroid_panel": NineSlice(source=None, insets=(8, 8, 24, 8)),
    "washi_corner_toolbar": NineSlice(source=None, insets=(0, 8, 0, 8)),
    "polaroid_modal": NineSlice(source=None, insets=(8, 8, 24, 8)),
}


# Inline SVG icons — sun / watermelon-slice / beach-ball (each ≤ 500 bytes).
# 8-ray sun encoded as one large polygon (star) + central disc — keeps the
# byte budget under 500 while still reading as an 8-ray sun.
_SUN_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<polygon points="12,1 14,8 21,5 18,11 23,12 18,13 21,19 14,16 12,23'
    ' 10,16 3,19 6,13 1,12 6,11 3,5 10,8" fill="currentColor"/>'
    '<circle cx="12" cy="12" r="5" fill="currentColor"/></svg>'
)
_WATERMELON_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M2 20 L22 20 A12 12 0 0 0 2 20 Z" fill="currentColor"/>'
    '<path d="M4 20 L20 20 A10 10 0 0 0 4 20 Z" fill="#6BCB77"/>'
    '<circle cx="9" cy="17" r="1" fill="#2A2A2A"/>'
    '<circle cx="15" cy="17" r="1" fill="#2A2A2A"/>'
    '<circle cx="12" cy="19" r="1" fill="#2A2A2A"/></svg>'
)
_BEACH_BALL_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="12" cy="12" r="10" fill="currentColor"/>'
    '<path d="M12 2 A10 10 0 0 1 12 22" stroke="#FFD93D"'
    ' stroke-width="3" fill="none"/>'
    '<path d="M2 12 A10 10 0 0 1 22 12" stroke="#6BCB77"'
    ' stroke-width="3" fill="none"/></svg>'
)

_ICONS: dict[str, SVGIcon] = {
    "sun": SVGIcon(svg_xml=_SUN_SVG, size=24,
                   default_fill=(255, 217, 61, 255)),
    "watermelon": SVGIcon(svg_xml=_WATERMELON_SVG, size=24,
                          default_fill=(255, 107, 157, 255)),
    "beach_ball": SVGIcon(svg_xml=_BEACH_BALL_SVG, size=24,
                          default_fill=(135, 206, 235, 255)),
}

for _name, _svg in (("sun", _SUN_SVG),
                    ("watermelon", _WATERMELON_SVG),
                    ("beach_ball", _BEACH_BALL_SVG)):
    if len(_svg.encode("utf-8")) > 500:  # pragma: no cover - constant data
        raise AssertionError(
            f"scrapbook_summer: SVG {_name!r} exceeds 500 bytes "
            f"({len(_svg.encode('utf-8'))} bytes)"
        )


# Background shader — watercolor wash (sky-blue + sunshine-yellow @ 30 %)
# over paper-white. ``color_palette`` carries the wash colours; the
# renderer-side dispatcher fills the canvas with ``base_color`` first.
_BACKGROUND = ShaderEffect(
    name="watercolor_wash",
    params={
        "base_color": (250, 250, 250, 255),            # paper white fill
        "color_palette": [
            (135, 206, 235, 255),                       # sky blue
            (255, 217, 61, 255),                        # sunshine yellow
        ],
        "wash_count": 3,
        "opacity": 0.3,
        "seed": 314159,
    },
)


# Semantic tokens — U1 named contract widget code binds to.
_PRIMARY_GRADIENT = Gradient(
    start=Color(135, 206, 235, 1.0),   # sky blue
    end=Color(255, 217, 61, 1.0),      # sunshine yellow
    angle_deg=135.0,
)

_SEMANTIC = SemanticTokens(
    primary=Color(135, 206, 235, 1.0),         # sky blue
    primary_gradient=_PRIMARY_GRADIENT,
    secondary=Color(255, 217, 61, 1.0),        # sunshine yellow
    accent=Color(255, 107, 157, 1.0),          # watermelon pink
    background=Color(250, 250, 250, 1.0),      # paper white
    surface=Color(244, 236, 216, 1.0),         # sun-bleached cream
    surface_hover=Color(248, 240, 220, 1.0),
    border=Color(198, 168, 116, 230 / 255),    # kraft paper
    text_primary=Color(42, 42, 42, 1.0),       # ink charcoal
    text_secondary=Color(59, 70, 84, 1.0),     # slate body
    text_disabled=Color(160, 165, 175, 1.0),
    success=Color(107, 203, 119, 1.0),         # grass green
    warning=Color(242, 187, 85, 1.0),
    error=Color(232, 90, 108, 1.0),
    info=Color(135, 206, 235, 1.0),
    focus_ring=Color(255, 107, 157, 1.0),
    glass_bg=Color(250, 250, 250, 0.85),
    glass_blur_px=10.0,
)


# Metadata — string-only as ThemeSpec.metadata demands.
_METADATA: dict[str, str] = {
    "tape_color": "#FF6B9D",
    "tape_alt_color": "#FFD93D",
    "seasonal_flavour": "summer",
    "creature_roster": "golden_01,butterfly_01,bee_01",
    "creature_roster_count": "3",
    "variant": "light",
    "family": "diary",
    "source_doc": "docs/theme_diary_family_2026_06_03.md",
}


SCRAPBOOK_SUMMER: ThemeSpec = ThemeSpec(
    name="scrapbook_summer",
    semantic=_SEMANTIC,
    palette=_PALETTE,
    fonts=_FONTS,
    nine_slices=_NINE_SLICES,
    icons=_ICONS,
    background_shader=_BACKGROUND,
    metadata=_METADATA,
)


__all__ = ["SCRAPBOOK_SUMMER"]
