"""BULLET_JOURNAL starter theme.

Minimalist bullet-journal aesthetic — bright white, soft-black ink, four
pastel accents, dot-grid background. Source design:
``docs/theme_diary_family_2026_06_03.md`` §3.4. Intentionally restrained:
Quicksand throughout (no script), the smallest creature roster in the
family. The background shader declares ``dot_grid`` with ``spacing=8``
so the renderer can synthesise a deterministic 1-px dot every 8 px.
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


# Palette — design doc §3.4 named entries + semantic-token aliases.
_PALETTE: dict[str, Color] = {
    # Named entries.
    "white": Color(255, 255, 255, 1.0),                # #FFFFFF
    "soft_black": Color(42, 42, 42, 1.0),              # #2A2A2A
    "pastel_pink": Color(255, 181, 197, 1.0),          # #FFB5C5
    "pastel_mint": Color(181, 230, 203, 1.0),          # #B5E6CB
    "pastel_lavender": Color(213, 194, 240, 1.0),      # #D5C2F0
    "pastel_butter": Color(250, 227, 162, 1.0),        # #FAE3A2
    "off_white": Color(248, 246, 242, 1.0),            # #F8F6F2
    "pencil_grey": Color(176, 170, 160, 200 / 255),    # #B0AAA0
    "body": Color(46, 46, 50, 1.0),
    "muted_body": Color(122, 118, 128, 1.0),
    "success": Color(111, 179, 136, 1.0),
    "warning": Color(224, 180, 90, 1.0),
    "error": Color(212, 90, 108, 1.0),
    # Semantic tokens — U1 forward-compat aliases.
    "surface": Color(255, 255, 255, 1.0),
    "surface_alt": Color(248, 246, 242, 1.0),
    "on_surface": Color(42, 42, 42, 1.0),
    "primary": Color(255, 181, 197, 1.0),
    "on_primary": Color(42, 42, 42, 1.0),
    "secondary": Color(181, 230, 203, 1.0),
    "accent": Color(213, 194, 240, 1.0),
}


# Fonts — Quicksand throughout, Cascadia Code mono. No script.
_FONTS: dict[str, Font] = {
    "header": Font(family="Quicksand", size=22, weight="600"),
    "h1": Font(family="Quicksand", size=28, weight="700"),
    "body": Font(family="Quicksand", size=14, weight="500"),
    "body_small": Font(family="Quicksand", size=13, weight="regular"),
    "caption": Font(family="Quicksand", size=12, weight="regular"),
    "mono": Font(family="Cascadia Code", size=14, weight="regular"),
}


# Nine-slices — single pencil-grey 1 px stroke everywhere.
_NINE_SLICES: dict[str, NineSlice] = {
    "pencil_stroke_panel": NineSlice(source=None, insets=(1, 1, 1, 1)),
    "pencil_stroke_toolbar": NineSlice(source=None, insets=(0, 1, 0, 1)),
    "pencil_stroke_modal": NineSlice(source=None, insets=(2, 2, 2, 2)),
}


# Inline SVG icons — bullet / dash / arrow starter set (each ≤ 500 bytes).
_BULLET_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="12" cy="12" r="4" fill="currentColor"/></svg>'
)
_DASH_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<rect x="4" y="11" width="16" height="2" fill="currentColor"/></svg>'
)
_ARROW_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<polygon points="4,11 16,11 16,7 22,12 16,17 16,13 4,13"'
    ' fill="currentColor"/></svg>'
)

_ICONS: dict[str, SVGIcon] = {
    "bullet": SVGIcon(svg_xml=_BULLET_SVG, size=24,
                      default_fill=(42, 42, 42, 255)),
    "dash": SVGIcon(svg_xml=_DASH_SVG, size=24,
                    default_fill=(42, 42, 42, 255)),
    "arrow": SVGIcon(svg_xml=_ARROW_SVG, size=24,
                     default_fill=(213, 194, 240, 255)),
}

for _name, _svg in (("bullet", _BULLET_SVG), ("dash", _DASH_SVG),
                    ("arrow", _ARROW_SVG)):
    if len(_svg.encode("utf-8")) > 500:  # pragma: no cover - constant data
        raise AssertionError(
            f"bullet_journal: SVG {_name!r} exceeds 500 bytes "
            f"({len(_svg.encode('utf-8'))} bytes)"
        )


# Background shader — dot grid (1 px dot every 8 px). The renderer-side
# dispatcher reads ``params`` and stamps the deterministic dot pattern.
_BACKGROUND = ShaderEffect(
    name="dot_grid",
    params={
        "paper_color": (255, 255, 255, 255),
        "dot_color": (42, 42, 42, 90),     # soft-black @ ~35 % alpha
        "spacing": 8,
        "dot_radius": 1,
    },
)


# Semantic tokens — U1 named contract widget code binds to.
_PRIMARY_GRADIENT = Gradient(
    start=Color(255, 181, 197, 1.0),    # pastel pink
    end=Color(181, 230, 203, 1.0),      # pastel mint
    angle_deg=135.0,
)

_SEMANTIC = SemanticTokens(
    primary=Color(255, 181, 197, 1.0),       # pastel pink
    primary_gradient=_PRIMARY_GRADIENT,
    secondary=Color(181, 230, 203, 1.0),     # pastel mint
    accent=Color(213, 194, 240, 1.0),        # pastel lavender
    background=Color(255, 255, 255, 1.0),    # white
    surface=Color(248, 246, 242, 1.0),       # off-white
    surface_hover=Color(245, 242, 235, 1.0),
    border=Color(176, 170, 160, 200 / 255),  # pencil grey
    text_primary=Color(42, 42, 42, 1.0),     # soft black
    text_secondary=Color(46, 46, 50, 1.0),
    text_disabled=Color(122, 118, 128, 1.0),
    success=Color(111, 179, 136, 1.0),
    warning=Color(224, 180, 90, 1.0),
    error=Color(212, 90, 108, 1.0),
    info=Color(213, 194, 240, 1.0),
    focus_ring=Color(255, 181, 197, 1.0),
    glass_bg=Color(255, 255, 255, 0.9),
    glass_blur_px=6.0,
)


# Frame styles — 1 px crisp soft-black border, rounding 2 px (almost
# rectangular), padding 8x6, minimal drop shadow. Restrained on every
# axis to match the minimalist bullet-journal vibe.
_FRAMES = PanelFrameSet(
    default=FrameStyle(
        border_size=1.0,
        border_color=Color(42, 42, 42, 1.0),         # soft black
        rounding=2.0,
        padding_x=8,
        padding_y=6,
        shadow_size=1.0,
        shadow_color=Color(42, 42, 42, 0.15),
        child_rounding=2.0,
        child_border_size=0.5,
        grip_size=10.0,
        grip_rounding=2.0,
        title_bar_height=22,
    ),
)


# Metadata — string-only as ThemeSpec.metadata demands.
_METADATA: dict[str, str] = {
    "tape_color": "#B0AAA0",
    "tape_alt_color": "#D5C2F0",
    "seasonal_flavour": "spring",
    "creature_roster": "hedgehog_01,porcupine_01",
    "creature_roster_count": "2",
    "variant": "light",
    "family": "diary",
    "source_doc": "docs/theme_diary_family_2026_06_03.md",
}


BULLET_JOURNAL: ThemeSpec = ThemeSpec(
    name="bullet_journal",
    semantic=_SEMANTIC,
    palette=_PALETTE,
    fonts=_FONTS,
    nine_slices=_NINE_SLICES,
    icons=_ICONS,
    frames=_FRAMES,
    background_shader=_BACKGROUND,
    metadata=_METADATA,
)


__all__ = ["BULLET_JOURNAL"]
