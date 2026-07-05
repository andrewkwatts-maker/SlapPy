"""slappyengine.text — SDF text rendering (glyph atlas + WGSL shader).

Public surface::

    from slappyengine.text import (
        SDFGlyph,
        SDFGlyphAtlas,
        SDFTextRenderer,
        TextMesh,
        SDF_TEXT_WGSL,
        sdf_from_bitmap,
        pack_glyphs_into_atlas,
    )

Design notes
------------
* PIL is a soft dependency for glyph rasterisation. When absent the
  atlas falls back to a stub monospace box per code point — enough to
  keep vertex/uv buffers consistent for CI.
* ``freetype-py`` is preferred when both a font path and the module are
  available; it produces the crispest bitmaps because it hands us the
  antialiased alpha directly.
* The SDF math is pure numpy — always available, no GPU required.
* The WGSL shader is a single fragment program that samples the atlas'
  R channel (0..1 signed distance) and uses ``smoothstep`` to derive an
  anti-aliased edge alpha.
"""
from __future__ import annotations

from .atlas import SDFGlyphAtlas
from .sdf_generator import pack_glyphs_into_atlas, sdf_from_bitmap
from .sdf_glyph import SDFGlyph
from .text_render import SDF_TEXT_WGSL, SDFTextRenderer, TextMesh

__all__ = [
    "SDFGlyph",
    "SDFGlyphAtlas",
    "SDFTextRenderer",
    "TextMesh",
    "SDF_TEXT_WGSL",
    "sdf_from_bitmap",
    "pack_glyphs_into_atlas",
]
