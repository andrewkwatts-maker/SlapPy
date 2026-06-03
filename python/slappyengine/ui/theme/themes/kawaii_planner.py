"""KAWAII_PLANNER starter theme.

Sticker-overload neon-pastel diary — pastel pink, mint, lavender, butter
yellow, neon-rose accents on grid paper with confetti scatter. Source
design: ``docs/theme_diary_family_2026_06_03.md`` §3.6 (with the
user-supplied palette refresh for the v0.4 Phase C rollout).

Background renders through the ``dot_grid`` shader (pastel-pink dots
every 16 px on butter-yellow paper) with a ``noise_glitter`` confetti
overlay declared in ``params["confetti"]`` for the renderer-side
dispatcher to composite. Washi-tape nine-slices are procedural.
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


# Palette — sprint brief hexes + semantic-token aliases.
_PALETTE: dict[str, Color] = {
    # Named entries (sprint brief hexes).
    "pastel_pink": Color(255, 192, 203, 1.0),          # #FFC0CB
    "mint": Color(168, 230, 207, 1.0),                 # #A8E6CF
    "lavender": Color(201, 177, 255, 1.0),             # #C9B1FF
    "butter_yellow": Color(255, 243, 176, 1.0),        # #FFF3B0
    "neon_rose": Color(255, 128, 171, 1.0),            # #FF80AB
    "ink_warm_grey": Color(92, 92, 92, 1.0),           # #5C5C5C
    "pencil_pink": Color(232, 168, 194, 200 / 255),    # border
    "body": Color(90, 79, 112, 1.0),
    "muted_body": Color(140, 130, 155, 1.0),
    "success": Color(123, 208, 160, 1.0),
    "warning": Color(255, 204, 106, 1.0),
    "error": Color(255, 122, 138, 1.0),
    # Semantic tokens — U1 forward-compat aliases.
    "surface": Color(255, 243, 176, 1.0),              # butter-yellow paper
    "surface_alt": Color(255, 192, 203, 1.0),
    "on_surface": Color(92, 92, 92, 1.0),
    "primary": Color(255, 128, 171, 1.0),              # neon rose
    "on_primary": Color(255, 255, 255, 1.0),
    "secondary": Color(168, 230, 207, 1.0),            # mint
    "accent": Color(201, 177, 255, 1.0),               # lavender
}


# Fonts — Caveat (bubblier header), Comfortaa (rounded body), Fira Code mono.
_FONTS: dict[str, Font] = {
    "header": Font(family="Caveat", size=26, weight="700"),
    "h1": Font(family="Caveat", size=34, weight="700"),
    "body": Font(family="Comfortaa", size=14, weight="500"),
    "body_small": Font(family="Comfortaa", size=13, weight="regular"),
    "caption": Font(family="Comfortaa", size=12, weight="regular"),
    "mono": Font(family="Fira Code", size=14, weight="regular"),
}


# Nine-slices — multi-colour washi / polka-dot / scalloped (procedural).
_NINE_SLICES: dict[str, NineSlice] = {
    "washi_panel": NineSlice(source=None, insets=(8, 8, 8, 8)),
    "washi_toolbar": NineSlice(source=None, insets=(0, 8, 0, 8)),
    "polka_dot_modal": NineSlice(source=None, insets=(10, 10, 10, 10)),
}


# Inline SVG icons — rainbow bow / kawaii face / star burst (each ≤ 500 bytes).
_BOW_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M12 12 L4 6 L4 18 Z" fill="currentColor"/>'
    '<path d="M12 12 L20 6 L20 18 Z" fill="#C9B1FF"/>'
    '<circle cx="12" cy="12" r="3" fill="#A8E6CF"/>'
    '<rect x="10" y="12" width="4" height="8" fill="#FFF3B0"/></svg>'
)
_KAWAII_FACE_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="12" cy="12" r="10" fill="currentColor"/>'
    '<ellipse cx="8" cy="11" rx="1.4" ry="2.2" fill="#5C5C5C"/>'
    '<ellipse cx="16" cy="11" rx="1.4" ry="2.2" fill="#5C5C5C"/>'
    '<path d="M9 15 Q12 17 15 15" stroke="#5C5C5C" stroke-width="1.5"'
    ' fill="none" stroke-linecap="round"/></svg>'
)
_STAR_BURST_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<polygon points="12,1 14,9 22,10 16,15 18,23 12,18 6,23 8,15 2,10 10,9"'
    ' fill="currentColor"/>'
    '<polygon points="12,5 13,11 18,11 14,14 15,19 12,16 9,19 10,14 6,11 11,11"'
    ' fill="#FFF3B0"/></svg>'
)

_ICONS: dict[str, SVGIcon] = {
    "rainbow_bow": SVGIcon(svg_xml=_BOW_SVG, size=24,
                           default_fill=(255, 128, 171, 255)),
    "kawaii_face": SVGIcon(svg_xml=_KAWAII_FACE_SVG, size=24,
                           default_fill=(255, 192, 203, 255)),
    "star_burst": SVGIcon(svg_xml=_STAR_BURST_SVG, size=24,
                          default_fill=(201, 177, 255, 255)),
}

for _name, _svg in (("rainbow_bow", _BOW_SVG),
                    ("kawaii_face", _KAWAII_FACE_SVG),
                    ("star_burst", _STAR_BURST_SVG)):
    if len(_svg.encode("utf-8")) > 500:  # pragma: no cover - constant data
        raise AssertionError(
            f"kawaii_planner: SVG {_name!r} exceeds 500 bytes "
            f"({len(_svg.encode('utf-8'))} bytes)"
        )


# Background shader — dot grid (pastel-pink dots, 16 px spacing) on butter
# yellow + confetti overlay declared in ``params["confetti"]`` for the
# renderer-side dispatcher to composite via ``noise_glitter``.
_BACKGROUND = ShaderEffect(
    name="dot_grid",
    params={
        "bg_color": (255, 243, 176, 255),              # butter yellow paper
        "dot_color": (255, 192, 203, 200),             # pastel pink dots
        "spacing": 16,
        "dot_radius": 2,
        "confetti": {
            "name": "noise_glitter",
            "density": 0.012,
            "color": (255, 128, 171, 200),             # neon rose @ ~78 %
            "seed": 4242,
        },
    },
)


# Semantic tokens — U1 named contract widget code binds to.
_PRIMARY_GRADIENT = Gradient(
    start=Color(255, 128, 171, 1.0),   # neon rose
    end=Color(201, 177, 255, 1.0),     # lavender
    angle_deg=135.0,
)

_SEMANTIC = SemanticTokens(
    primary=Color(255, 128, 171, 1.0),         # neon rose
    primary_gradient=_PRIMARY_GRADIENT,
    secondary=Color(168, 230, 207, 1.0),       # mint
    accent=Color(201, 177, 255, 1.0),          # lavender
    background=Color(255, 243, 176, 1.0),      # butter yellow paper
    surface=Color(255, 250, 220, 1.0),         # softer cream
    surface_hover=Color(255, 245, 200, 1.0),
    border=Color(232, 168, 194, 200 / 255),    # pencil pink
    text_primary=Color(92, 92, 92, 1.0),       # ink warm grey
    text_secondary=Color(90, 79, 112, 1.0),    # plum grey
    text_disabled=Color(180, 175, 188, 1.0),
    success=Color(123, 208, 160, 1.0),
    warning=Color(255, 204, 106, 1.0),
    error=Color(255, 122, 138, 1.0),
    info=Color(168, 230, 207, 1.0),
    focus_ring=Color(255, 128, 171, 1.0),
    glass_bg=Color(255, 252, 247, 0.9),
    glass_blur_px=8.0,
)


# Metadata — string-only as ThemeSpec.metadata demands.
_METADATA: dict[str, str] = {
    "tape_color": "#FFC0CB",
    "tape_alt_color": "#A8E6CF",
    "seasonal_flavour": "summer",
    "creature_roster": "cat_01,panda_01,porcupine_01",
    "creature_roster_count": "3",
    "sticker_density": "maximal",
    "variant": "light",
    "family": "diary",
    "source_doc": "docs/theme_diary_family_2026_06_03.md",
}


KAWAII_PLANNER: ThemeSpec = ThemeSpec(
    name="kawaii_planner",
    semantic=_SEMANTIC,
    palette=_PALETTE,
    fonts=_FONTS,
    nine_slices=_NINE_SLICES,
    icons=_ICONS,
    background_shader=_BACKGROUND,
    metadata=_METADATA,
)


__all__ = ["KAWAII_PLANNER"]
