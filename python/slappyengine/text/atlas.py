"""SDF glyph atlas builder.

The atlas rasterises a set of code points from a font, converts each
bitmap into a signed distance field, and packs them into a single RGBA
texture. When ``freetype-py`` is missing the class falls back to a
PIL-only rasterisation path; the SDF math itself is CPU-only and always
available (see :mod:`slappyengine.text.sdf_generator`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

import numpy as np

from .sdf_glyph import SDFGlyph
from .sdf_generator import pack_glyphs_into_atlas, sdf_from_bitmap


# ---------------------------------------------------------------------------
# Soft imports — cached so we don't retry the failed import on every call.
# ---------------------------------------------------------------------------

_PIL_CACHE: dict[str, Any] = {"tried": False, "font_module": None, "image_module": None, "draw_module": None}
_FT_CACHE: dict[str, Any] = {"tried": False, "module": None}


def _pil():
    if not _PIL_CACHE["tried"]:
        _PIL_CACHE["tried"] = True
        try:
            from PIL import ImageFont, Image, ImageDraw  # type: ignore[import-not-found]

            _PIL_CACHE["font_module"] = ImageFont
            _PIL_CACHE["image_module"] = Image
            _PIL_CACHE["draw_module"] = ImageDraw
        except Exception:  # pragma: no cover — defensive
            pass
    return _PIL_CACHE["font_module"], _PIL_CACHE["image_module"], _PIL_CACHE["draw_module"]


def _freetype():
    if not _FT_CACHE["tried"]:
        _FT_CACHE["tried"] = True
        try:
            import freetype  # type: ignore[import-not-found]

            _FT_CACHE["module"] = freetype
        except Exception:  # pragma: no cover — defensive
            pass
    return _FT_CACHE["module"]


# ---------------------------------------------------------------------------
# Atlas
# ---------------------------------------------------------------------------

_DEFAULT_ASCII = tuple(range(32, 127))


class SDFGlyphAtlas:
    """Builds an SDF glyph atlas from a font file.

    Parameters
    ----------
    font_path:
        Path to a ``.ttf``/``.otf`` file. May be ``None`` to fall back to
        PIL's built-in default font (useful for headless CI).
    size_px:
        Nominal glyph height in pixels.
    sdf_radius:
        Halo radius in pixels; determines how much SDF space is stored
        around each glyph. The WGSL shader samples up to this radius.
    codepoints:
        Iterable of Unicode code points to include. Defaults to printable
        ASCII (32..126 inclusive).
    """

    def __init__(
        self,
        font_path: Optional[str] = None,
        size_px: int = 32,
        sdf_radius: int = 8,
        codepoints: Optional[Iterable[int]] = None,
    ) -> None:
        if size_px <= 0:
            raise ValueError("size_px must be positive")
        if sdf_radius <= 0:
            raise ValueError("sdf_radius must be positive")

        self.font_path = font_path
        self.size_px = int(size_px)
        self.sdf_radius = int(sdf_radius)
        self.codepoints = tuple(codepoints) if codepoints is not None else _DEFAULT_ASCII

        self._glyphs: dict[int, SDFGlyph] = {}
        self._atlas: Optional[np.ndarray] = None
        self._built = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self) -> np.ndarray:
        """Rasterise all glyphs, run SDF, pack into a single texture.

        Returns
        -------
        ``HxWx4`` ``uint8`` array. The R channel encodes the SDF
        (0 = far outside, 255 = far inside, 128 = boundary). G/B mirror R
        so the atlas is legible when previewed, and A is 255 everywhere
        the glyph exists (0 in padding). This layout is what
        :data:`~slappyengine.text.text_render.SDF_TEXT_WGSL` samples.
        """
        if self._built and self._atlas is not None:
            return self._atlas

        bitmaps, records = self._rasterise_all()
        if not bitmaps:
            self._atlas = np.zeros((1, 1, 4), dtype=np.uint8)
            self._built = True
            return self._atlas

        sdf_bitmaps = [sdf_from_bitmap(b, self.sdf_radius) for b in bitmaps]

        # Normalise SDF float32 -> uint8 mapping so 0.5 == boundary.
        r = self.sdf_radius
        u8_bitmaps = []
        for f in sdf_bitmaps:
            # Positive outside → below 0.5, negative inside → above 0.5.
            norm = 0.5 - (f / (2.0 * r))
            u = np.clip(norm, 0.0, 1.0) * 255.0
            u8_bitmaps.append(u.astype(np.uint8))

        packed, positions = pack_glyphs_into_atlas(u8_bitmaps, padding=1)
        h, w = packed.shape

        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[..., 0] = packed
        rgba[..., 1] = packed
        rgba[..., 2] = packed
        rgba[..., 3] = 255

        for (cp, size_px, bearing, advance_px), (x, y, gw, gh) in zip(records, positions):
            u0 = x / w
            v0 = y / h
            u1 = (x + gw) / w
            v1 = (y + gh) / h
            self._glyphs[cp] = SDFGlyph(
                codepoint=cp,
                atlas_uv=(u0, v0, u1, v1),
                size_px=(gw, gh),
                bearing=bearing,
                advance_px=advance_px,
            )

        self._atlas = rgba
        self._built = True
        return rgba

    def get_glyph(self, codepoint: int) -> Optional[SDFGlyph]:
        """Return the :class:`SDFGlyph` for ``codepoint`` or ``None``."""
        if not self._built:
            self.generate()
        return self._glyphs.get(int(codepoint))

    def text_bounds(self, text: str) -> tuple[int, int]:
        """Measure the pixel bounds ``(width, height)`` of ``text``.

        Missing glyphs contribute a fixed advance of ``size_px // 2`` so
        that the return value stays monotone in ``len(text)``.
        """
        if not self._built:
            self.generate()
        if not text:
            return (0, self.size_px)
        w_total = 0
        h_max = self.size_px
        default_advance = max(1, self.size_px // 2)
        for ch in text:
            g = self._glyphs.get(ord(ch))
            if g is None:
                w_total += default_advance
            else:
                w_total += g.advance_px
                h_max = max(h_max, g.size_px[1])
        return (w_total, h_max)

    # ------------------------------------------------------------------
    # Rasterisation
    # ------------------------------------------------------------------

    def _rasterise_all(self):
        ft = _freetype()
        if ft is not None and self.font_path:
            try:
                return self._rasterise_freetype(ft)
            except Exception:
                # Fall back to PIL silently — freetype failures during
                # face load / glyph render are common on stripped installs.
                pass
        return self._rasterise_pil()

    # ---- freetype path ---------------------------------------------------

    def _rasterise_freetype(self, ft) -> tuple[list[np.ndarray], list[tuple]]:
        face = ft.Face(self.font_path)
        face.set_pixel_sizes(0, self.size_px)
        bitmaps: list[np.ndarray] = []
        records: list[tuple] = []
        for cp in self.codepoints:
            try:
                face.load_char(chr(cp))
            except Exception:
                continue
            glyph = face.glyph
            bmp = glyph.bitmap
            w, h = bmp.width, bmp.rows
            if w == 0 or h == 0:
                # Space-like glyph: still record advance.
                records.append(
                    (
                        cp,
                        (0, 0),
                        (0, 0),
                        int(glyph.advance.x >> 6),
                    )
                )
                bitmaps.append(np.zeros((1, 1), dtype=np.uint8))
                continue
            data = np.array(bmp.buffer, dtype=np.uint8).reshape(h, w)
            bitmaps.append(data)
            records.append(
                (
                    cp,
                    (w, h),
                    (glyph.bitmap_left, glyph.bitmap_top),
                    int(glyph.advance.x >> 6),
                )
            )
        return bitmaps, records

    # ---- PIL path --------------------------------------------------------

    def _rasterise_pil(self) -> tuple[list[np.ndarray], list[tuple]]:
        ImageFont, Image, ImageDraw = _pil()
        if ImageFont is None:
            # PIL missing entirely — build a monospace stub atlas so
            # downstream code still gets an SDFGlyph per codepoint.
            return self._rasterise_stub()

        if self.font_path:
            try:
                font = ImageFont.truetype(self.font_path, self.size_px)
            except Exception:
                font = ImageFont.load_default()
        else:
            font = ImageFont.load_default()

        bitmaps: list[np.ndarray] = []
        records: list[tuple] = []
        for cp in self.codepoints:
            ch = chr(cp)
            try:
                bbox = font.getbbox(ch)
            except Exception:
                continue
            x0, y0, x1, y1 = bbox
            w = max(1, int(x1 - x0))
            h = max(1, int(y1 - y0))
            # Rasterise the glyph into a small L-mode image.
            img = Image.new("L", (w, h), 0)
            draw = ImageDraw.Draw(img)
            draw.text((-x0, -y0), ch, fill=255, font=font)
            arr = np.array(img, dtype=np.uint8)
            bitmaps.append(arr)
            try:
                advance = int(font.getlength(ch))
            except Exception:
                advance = w
            records.append(
                (
                    cp,
                    (w, h),
                    (int(x0), int(-y0)),
                    max(1, advance),
                )
            )
        return bitmaps, records

    def _rasterise_stub(self) -> tuple[list[np.ndarray], list[tuple]]:
        bitmaps: list[np.ndarray] = []
        records: list[tuple] = []
        for cp in self.codepoints:
            arr = np.zeros((self.size_px, self.size_px // 2 or 1), dtype=np.uint8)
            arr[2:-2, 2:-2] = 255
            bitmaps.append(arr)
            records.append(
                (
                    cp,
                    (arr.shape[1], arr.shape[0]),
                    (0, self.size_px),
                    max(1, self.size_px // 2),
                )
            )
        return bitmaps, records
