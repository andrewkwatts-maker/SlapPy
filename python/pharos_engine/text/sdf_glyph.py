"""SDF glyph metadata dataclass.

Each glyph rasterised into the :class:`~pharos_engine.text.atlas.SDFGlyphAtlas`
carries these five fields; they are enough to lay out and draw a UTF-8 string
using the WGSL shader in :mod:`pharos_engine.text.text_render`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SDFGlyph:
    """Immutable per-glyph record inside an SDF atlas.

    Attributes
    ----------
    codepoint:
        Unicode code point of the glyph (e.g. ``ord('A') == 65``).
    atlas_uv:
        ``(u0, v0, u1, v1)`` UV rectangle of the glyph inside the atlas
        texture. All four components are in ``[0, 1]`` and ``u1 > u0``,
        ``v1 > v0``.
    size_px:
        ``(width_px, height_px)`` glyph pixel size on the atlas (the
        rendered box, including the SDF halo).
    bearing:
        ``(left_bearing_px, top_bearing_px)`` — 2D offset from the pen
        position to the top-left corner of the glyph box.
    advance_px:
        Horizontal pen advance after drawing this glyph.
    """

    codepoint: int
    atlas_uv: tuple[float, float, float, float]
    size_px: tuple[int, int]
    bearing: tuple[int, int]
    advance_px: int
