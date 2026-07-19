"""Edge-stroke shader library — hand-drawn panel borders.

Public surface:

    from slappyengine.ui.theme.edge_strokes import (
        EdgeStrokeStyle, EDGE_STROKES, get_stroke, list_strokes,
        render_stroke_border, bake_stroke_texture,
    )

Fifteen styles ship in :data:`EDGE_STROKES` — pencil, pen, marker,
brush, chalk, charcoal, crayon, ink wash, and more. Each style is a
short WGSL fragment shader plus a matching numpy fallback so headless
tests work without a GPU.

The renderer produces per-panel border strip textures (top / right /
bottom / left) that the DPG bridge stamps around the panel perimeter.
Themes may attach an :class:`EdgeStrokeStyle` to
:attr:`slappyengine.ui.theme.FrameStyle.edge_stroke` to replace the
simple ``border_color`` with a hand-drawn line.
"""
from __future__ import annotations

from .library import EDGE_STROKES, EdgeStrokeStyle, get_stroke, list_strokes
from .presets import (
    EDGE_STROKE_PRESETS,
    EdgeStrokePreset,
    list_presets,
    render_edge_stroke,
)
from .renderer import bake_stroke_texture, has_wgpu, render_stroke_border

__all__ = [
    "EDGE_STROKES",
    "EDGE_STROKE_PRESETS",
    "EdgeStrokePreset",
    "EdgeStrokeStyle",
    "bake_stroke_texture",
    "get_stroke",
    "has_wgpu",
    "list_presets",
    "list_strokes",
    "render_edge_stroke",
    "render_stroke_border",
]
