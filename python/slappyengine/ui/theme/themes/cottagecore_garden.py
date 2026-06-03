"""COTTAGECORE_GARDEN starter theme.

Floral / herbal / embroidered cottage aesthetic — mossy-green, cream,
lavender, peach, sage on a fresh-linen background. Source design:
``docs/theme_diary_family_2026_06_03.md`` §3.5 (with the user-supplied
palette refresh for the v0.4 Phase C rollout).

Background renders through the ``parchment`` shader (cream base with a
low-density ``noise_glitter`` overlay simulating linen-weave fibre).
Embroidered-stitch / herb-sprig / pressed-flower nine-slices are
procedural; renderer paints them from the ``embroidered_moss`` colour.
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
    "mossy_green": Color(141, 167, 124, 1.0),          # #8DA77C
    "cream": Color(245, 237, 221, 1.0),                # #F5EDDD
    "lavender": Color(184, 168, 213, 1.0),             # #B8A8D5
    "peach": Color(255, 176, 122, 1.0),                # #FFB07A
    "sage": Color(156, 175, 136, 1.0),                 # #9CAF88
    "ink_sepia": Color(74, 60, 42, 1.0),               # #4A3C2A
    "embroidered_moss": Color(107, 132, 86, 220 / 255),  # border stitch
    "body": Color(90, 74, 56, 1.0),                    # earth brown
    "muted_body": Color(140, 122, 102, 1.0),
    "success": Color(122, 170, 102, 1.0),
    "warning": Color(224, 180, 90, 1.0),
    "error": Color(184, 80, 64, 1.0),
    # Semantic tokens — U1 forward-compat aliases.
    "surface": Color(245, 237, 221, 1.0),
    "surface_alt": Color(235, 229, 208, 1.0),
    "on_surface": Color(74, 60, 42, 1.0),
    "primary": Color(141, 167, 124, 1.0),              # mossy green
    "on_primary": Color(245, 237, 221, 1.0),
    "secondary": Color(184, 168, 213, 1.0),            # lavender
    "accent": Color(255, 176, 122, 1.0),               # peach
}


# Fonts — Patrick Hand header (looser script), Quicksand body, Fira Code mono.
_FONTS: dict[str, Font] = {
    "header": Font(family="Patrick Hand", size=24, weight="600"),
    "h1": Font(family="Patrick Hand", size=30, weight="700"),
    "body": Font(family="Quicksand", size=14, weight="500"),
    "body_small": Font(family="Quicksand", size=13, weight="regular"),
    "caption": Font(family="Quicksand", size=12, weight="italic"),
    "mono": Font(family="Fira Code", size=14, weight="regular"),
}


# Nine-slices — embroidered stitch / herb sprig / pressed flower (procedural).
_NINE_SLICES: dict[str, NineSlice] = {
    "embroidered_panel": NineSlice(source=None, insets=(8, 8, 8, 8)),
    "herb_sprig_toolbar": NineSlice(source=None, insets=(0, 8, 0, 8)),
    "pressed_flower_modal": NineSlice(source=None, insets=(12, 12, 12, 12)),
}


# Inline SVG icons — daisy / sprig / embroidery hoop (each ≤ 500 bytes).
_DAISY_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<ellipse cx="12" cy="4" rx="2" ry="4" fill="currentColor"/>'
    '<ellipse cx="12" cy="20" rx="2" ry="4" fill="currentColor"/>'
    '<ellipse cx="4" cy="12" rx="4" ry="2" fill="currentColor"/>'
    '<ellipse cx="20" cy="12" rx="4" ry="2" fill="currentColor"/>'
    '<circle cx="12" cy="12" r="3" fill="#FFD93D"/></svg>'
)
_SPRIG_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<line x1="12" y1="2" x2="12" y2="22" stroke="currentColor"'
    ' stroke-width="2"/>'
    '<polygon points="12,7 7,5 9,9" fill="currentColor"/>'
    '<polygon points="12,11 17,9 15,13" fill="currentColor"/>'
    '<polygon points="12,15 7,13 9,17" fill="currentColor"/></svg>'
)
_HOOP_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="12" cy="12" r="9" stroke="currentColor"'
    ' stroke-width="2" fill="none"/>'
    '<rect x="11" y="1" width="2" height="4" fill="currentColor"/>'
    '<circle cx="12" cy="12" r="3" fill="#FFB07A"/></svg>'
)

_ICONS: dict[str, SVGIcon] = {
    "daisy": SVGIcon(svg_xml=_DAISY_SVG, size=24,
                     default_fill=(245, 237, 221, 255)),
    "sprig": SVGIcon(svg_xml=_SPRIG_SVG, size=24,
                     default_fill=(141, 167, 124, 255)),
    "embroidery_hoop": SVGIcon(svg_xml=_HOOP_SVG, size=24,
                               default_fill=(107, 132, 86, 255)),
}

for _name, _svg in (("daisy", _DAISY_SVG), ("sprig", _SPRIG_SVG),
                    ("embroidery_hoop", _HOOP_SVG)):
    if len(_svg.encode("utf-8")) > 500:  # pragma: no cover - constant data
        raise AssertionError(
            f"cottagecore_garden: SVG {_name!r} exceeds 500 bytes "
            f"({len(_svg.encode('utf-8'))} bytes)"
        )


# Background shader — parchment cream base + low-density linen-weave noise.
# The renderer-side dispatcher composites a light ``noise_glitter`` overlay
# (sage flecks at ~3 % density) on top of the parchment fill to simulate
# linen fibre crosshatch.
_BACKGROUND = ShaderEffect(
    name="parchment",
    params={
        "base_color": (245, 237, 221, 255),            # fresh linen cream
        "edge_dark": 0.92,
        "noise_amount": 0.04,
        "weave_overlay": {
            "name": "noise_glitter",
            "density": 0.03,
            "color": (156, 175, 136, 90),              # sage @ ~35 % alpha
            "seed": 1707,
        },
    },
)


# Semantic tokens — U1 named contract widget code binds to.
_PRIMARY_GRADIENT = Gradient(
    start=Color(141, 167, 124, 1.0),   # mossy green
    end=Color(184, 168, 213, 1.0),     # lavender
    angle_deg=135.0,
)

_SEMANTIC = SemanticTokens(
    primary=Color(141, 167, 124, 1.0),         # mossy green
    primary_gradient=_PRIMARY_GRADIENT,
    secondary=Color(184, 168, 213, 1.0),       # lavender
    accent=Color(255, 176, 122, 1.0),          # peach
    background=Color(245, 237, 221, 1.0),      # cream / fresh linen
    surface=Color(235, 229, 208, 1.0),         # cream panel
    surface_hover=Color(240, 233, 215, 1.0),
    border=Color(107, 132, 86, 220 / 255),     # embroidered moss
    text_primary=Color(74, 60, 42, 1.0),       # ink sepia
    text_secondary=Color(90, 74, 56, 1.0),     # earth brown
    text_disabled=Color(160, 145, 125, 1.0),
    success=Color(122, 170, 102, 1.0),
    warning=Color(224, 180, 90, 1.0),
    error=Color(184, 80, 64, 1.0),
    info=Color(156, 175, 136, 1.0),            # sage
    focus_ring=Color(141, 167, 124, 1.0),
    glass_bg=Color(245, 237, 221, 0.85),
    glass_blur_px=10.0,
)


# Metadata — string-only as ThemeSpec.metadata demands.
_METADATA: dict[str, str] = {
    "tape_color": "#6B8456",
    "tape_alt_color": "#B8A8D5",
    "seasonal_flavour": "spring",
    "creature_roster": "rabbit_01,deer_01,mushroom_01,flower_01",
    "creature_roster_count": "4",
    "variant": "light",
    "family": "diary",
    "source_doc": "docs/theme_diary_family_2026_06_03.md",
}


COTTAGECORE_GARDEN: ThemeSpec = ThemeSpec(
    name="cottagecore_garden",
    semantic=_SEMANTIC,
    palette=_PALETTE,
    fonts=_FONTS,
    nine_slices=_NINE_SLICES,
    icons=_ICONS,
    background_shader=_BACKGROUND,
    metadata=_METADATA,
)


__all__ = ["COTTAGECORE_GARDEN"]
