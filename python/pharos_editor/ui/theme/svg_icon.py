"""Tiny SVG icon rasteriser.

A purposely-minimal SVG parser sufficient for theme icons (chevrons,
checkmarks, glyph buttons, …). Supports a handful of shapes —
``<rect>``, ``<circle>``, ``<line>``, ``<polygon>``, ``<path>`` (only
``M`` / ``L`` / ``Z`` commands), each with ``fill`` and ``stroke``
attributes. That's enough to cover every icon the Pharos Engine editor
currently ships without pulling in ``cairosvg`` / ``pyrsvg`` / a Qt
runtime.

Rasterised textures are cached by ``(svg_hash, size)`` so repeat
icons share GPU memory.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from pharos_engine._validation import (
    validate_non_empty_str,
    validate_positive_int,
)


# ---------------------------------------------------------------------------
# Colour parsing
# ---------------------------------------------------------------------------


_NAMED_COLOURS: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "green": (0, 128, 0),
    "blue": (0, 0, 255),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
    "none": (0, 0, 0),
    "transparent": (0, 0, 0),
}


def _parse_colour(text: str | None, default: tuple[int, int, int, int]
                  ) -> tuple[int, int, int, int]:
    """Resolve an SVG colour string into RGBA ``[0, 255]``.

    Supports ``#rgb``, ``#rrggbb``, ``rgb(r,g,b)``, ``none``, and the
    primary named colours. Unknown strings fall back to *default*.
    """
    if text is None:
        return default
    s = text.strip().lower()
    if s in ("none", ""):
        return (0, 0, 0, 0)
    if s in _NAMED_COLOURS:
        r, g, b = _NAMED_COLOURS[s]
        return (r, g, b, 255)
    if s.startswith("#"):
        h = s[1:]
        if len(h) == 3:
            return (
                int(h[0] * 2, 16),
                int(h[1] * 2, 16),
                int(h[2] * 2, 16),
                255,
            )
        if len(h) == 6:
            return (
                int(h[0:2], 16),
                int(h[2:4], 16),
                int(h[4:6], 16),
                255,
            )
        if len(h) == 8:
            return (
                int(h[0:2], 16),
                int(h[2:4], 16),
                int(h[4:6], 16),
                int(h[6:8], 16),
            )
    m = re.match(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", s)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)), 255)
    return default


# ---------------------------------------------------------------------------
# Rasterisation primitives — pure numpy
# ---------------------------------------------------------------------------


def _strip_ns(tag: str) -> str:
    """Strip XML namespace from a tag — ``{ns}rect`` → ``rect``."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _fill_rect(
    buf: np.ndarray, x: float, y: float, w: float, h: float,
    rgba: tuple[int, int, int, int]
) -> None:
    bh, bw = buf.shape[0], buf.shape[1]
    x0 = max(0, int(round(x)))
    y0 = max(0, int(round(y)))
    x1 = min(bw, int(round(x + w)))
    y1 = min(bh, int(round(y + h)))
    if x1 > x0 and y1 > y0:
        buf[y0:y1, x0:x1, :] = rgba


def _fill_circle(
    buf: np.ndarray, cx: float, cy: float, r: float,
    rgba: tuple[int, int, int, int]
) -> None:
    bh, bw = buf.shape[0], buf.shape[1]
    yy, xx = np.ogrid[:bh, :bw]
    mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
    if rgba[3] == 0:
        return
    buf[mask] = rgba


def _stroke_line(
    buf: np.ndarray, x0: float, y0: float, x1: float, y1: float,
    rgba: tuple[int, int, int, int], width: float = 1.0
) -> None:
    """Bresenham-ish thick line."""
    if rgba[3] == 0:
        return
    bh, bw = buf.shape[0], buf.shape[1]
    steps = int(max(abs(x1 - x0), abs(y1 - y0)) * 2 + 1)
    if steps <= 0:
        return
    ts = np.linspace(0.0, 1.0, steps)
    xs = x0 + (x1 - x0) * ts
    ys = y0 + (y1 - y0) * ts
    half = max(0.5, width / 2.0)
    r = int(np.ceil(half))
    for cx, cy in zip(xs, ys):
        ix0 = max(0, int(round(cx)) - r)
        iy0 = max(0, int(round(cy)) - r)
        ix1 = min(bw, int(round(cx)) + r + 1)
        iy1 = min(bh, int(round(cy)) + r + 1)
        if ix1 > ix0 and iy1 > iy0:
            buf[iy0:iy1, ix0:ix1, :] = rgba


def _fill_polygon(
    buf: np.ndarray, pts: list[tuple[float, float]],
    rgba: tuple[int, int, int, int]
) -> None:
    """Even-odd polygon fill — naive scanline."""
    if not pts or rgba[3] == 0:
        return
    bh, bw = buf.shape[0], buf.shape[1]
    ys_min = max(0, int(np.floor(min(p[1] for p in pts))))
    ys_max = min(bh - 1, int(np.ceil(max(p[1] for p in pts))))
    for y in range(ys_min, ys_max + 1):
        xs: list[float] = []
        n = len(pts)
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            if (y0 <= y < y1) or (y1 <= y < y0):
                t = (y - y0) / (y1 - y0) if y1 != y0 else 0.0
                xs.append(x0 + t * (x1 - x0))
        xs.sort()
        for i in range(0, len(xs) - 1, 2):
            xa = max(0, int(round(xs[i])))
            xb = min(bw, int(round(xs[i + 1])))
            if xb > xa:
                buf[y, xa:xb, :] = rgba


# ---------------------------------------------------------------------------
# Path parsing — supports M / L / Z (uppercase + lowercase)
# ---------------------------------------------------------------------------


def _parse_path(d: str) -> list[list[tuple[float, float]]]:
    """Parse an SVG ``d`` attribute into a list of subpath point lists."""
    tokens = re.findall(r"[MmLlZzHhVv]|-?\d+(?:\.\d+)?", d)
    subpaths: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    cx, cy = 0.0, 0.0
    i = 0
    cmd = ""
    while i < len(tokens):
        t = tokens[i]
        if t in "MmLlZzHhVv":
            cmd = t
            i += 1
            if cmd in ("Z", "z"):
                if current:
                    subpaths.append(current)
                    current = []
            continue
        # Numeric token → consume args based on cmd.
        if cmd in ("M", "L"):
            x = float(tokens[i]); y = float(tokens[i + 1])
            cx, cy = x, y
            if cmd == "M" and current:
                subpaths.append(current); current = []
            current.append((cx, cy))
            i += 2
            if cmd == "M":
                cmd = "L"
        elif cmd in ("m", "l"):
            dx = float(tokens[i]); dy = float(tokens[i + 1])
            cx, cy = cx + dx, cy + dy
            if cmd == "m" and current:
                subpaths.append(current); current = []
            current.append((cx, cy))
            i += 2
            if cmd == "m":
                cmd = "l"
        elif cmd == "H":
            cx = float(tokens[i]); current.append((cx, cy)); i += 1
        elif cmd == "h":
            cx += float(tokens[i]); current.append((cx, cy)); i += 1
        elif cmd == "V":
            cy = float(tokens[i]); current.append((cx, cy)); i += 1
        elif cmd == "v":
            cy += float(tokens[i]); current.append((cx, cy)); i += 1
        else:
            i += 1
    if current:
        subpaths.append(current)
    return subpaths


# ---------------------------------------------------------------------------
# Texture cache
# ---------------------------------------------------------------------------

_TEX_CACHE: dict[tuple[str, int], np.ndarray] = {}


def _cache_key(svg_xml: str, size: int) -> tuple[str, int]:
    h = hashlib.sha1(svg_xml.encode("utf-8", errors="replace")).hexdigest()
    return (h, size)


def clear_cache() -> None:
    """Clear the rasterised-texture cache. Public for tests."""
    _TEX_CACHE.clear()


# ---------------------------------------------------------------------------
# SVGIcon
# ---------------------------------------------------------------------------


@dataclass
class SVGIcon:
    """A parsed + rasterised SVG icon.

    Parameters
    ----------
    svg_xml:
        Source XML string.
    size:
        Square texture edge length in pixels.
    default_fill:
        RGBA fallback when a shape has no explicit ``fill``.
    """

    svg_xml: str
    size: int = 16
    default_fill: tuple[int, int, int, int] = (255, 255, 255, 255)
    _texture: np.ndarray | None = field(default=None, repr=False, init=False)
    _dpg_texture_id: int | None = field(default=None, repr=False, init=False)

    def __post_init__(self) -> None:
        fn = "SVGIcon"
        self.svg_xml = validate_non_empty_str("svg_xml", fn, self.svg_xml)
        self.size = validate_positive_int("size", fn, self.size)
        if not isinstance(self.default_fill, (tuple, list)) or len(
            self.default_fill
        ) != 4:
            raise TypeError(f"{fn}: default_fill must be a 4-tuple of ints")
        self.default_fill = tuple(int(c) for c in self.default_fill)  # type: ignore[assignment]

    # ---- Rasterisation ----------------------------------------------------

    def rasterize(self) -> np.ndarray:
        """Rasterise *and cache* the SVG into an ``(N, N, 4)`` uint8 array.

        Repeated calls return the cached array. The cache is keyed on
        ``(svg_hash, size)`` so two ``SVGIcon`` instances with the same
        markup share storage.
        """
        if self._texture is not None:
            return self._texture
        key = _cache_key(self.svg_xml, self.size)
        cached = _TEX_CACHE.get(key)
        if cached is not None:
            self._texture = cached
            return cached
        buf = np.zeros((self.size, self.size, 4), dtype=np.uint8)
        root = ET.fromstring(self.svg_xml)
        # Determine viewbox so we can map element coords → pixel coords.
        viewbox = root.attrib.get("viewBox")
        if viewbox:
            parts = [float(x) for x in viewbox.replace(",", " ").split()]
            if len(parts) == 4:
                _, _, vbw, vbh = parts
            else:
                vbw, vbh = float(self.size), float(self.size)
        else:
            vbw = float(root.attrib.get("width", self.size))
            vbh = float(root.attrib.get("height", self.size))
        sx = self.size / max(vbw, 1e-6)
        sy = self.size / max(vbh, 1e-6)

        def _attr_float(el: ET.Element, name: str, default: float = 0.0) -> float:
            v = el.attrib.get(name)
            if v is None:
                return default
            try:
                return float(v)
            except ValueError:
                return default

        def _draw(el: ET.Element) -> None:
            tag = _strip_ns(el.tag)
            fill = _parse_colour(el.attrib.get("fill"), self.default_fill)
            stroke = _parse_colour(el.attrib.get("stroke"), (0, 0, 0, 0))
            stroke_w = _attr_float(el, "stroke-width", 1.0)
            if tag == "rect":
                x = _attr_float(el, "x") * sx
                y = _attr_float(el, "y") * sy
                w = _attr_float(el, "width") * sx
                h = _attr_float(el, "height") * sy
                _fill_rect(buf, x, y, w, h, fill)
                if stroke[3] > 0:
                    _stroke_line(buf, x, y, x + w, y, stroke, stroke_w)
                    _stroke_line(buf, x + w, y, x + w, y + h, stroke, stroke_w)
                    _stroke_line(buf, x + w, y + h, x, y + h, stroke, stroke_w)
                    _stroke_line(buf, x, y + h, x, y, stroke, stroke_w)
            elif tag == "circle":
                cx = _attr_float(el, "cx") * sx
                cy = _attr_float(el, "cy") * sy
                r = _attr_float(el, "r") * min(sx, sy)
                _fill_circle(buf, cx, cy, r, fill)
            elif tag == "line":
                x0 = _attr_float(el, "x1") * sx
                y0 = _attr_float(el, "y1") * sy
                x1 = _attr_float(el, "x2") * sx
                y1 = _attr_float(el, "y2") * sy
                _stroke_line(buf, x0, y0, x1, y1, stroke if stroke[3] else fill, stroke_w)
            elif tag == "polygon":
                points = el.attrib.get("points", "")
                nums = [float(x) for x in re.split(r"[\s,]+", points.strip()) if x]
                pts = [
                    (nums[i] * sx, nums[i + 1] * sy)
                    for i in range(0, len(nums) - 1, 2)
                ]
                _fill_polygon(buf, pts, fill)
            elif tag == "path":
                d = el.attrib.get("d", "")
                if d:
                    for sub in _parse_path(d):
                        scaled = [(p[0] * sx, p[1] * sy) for p in sub]
                        if fill[3] > 0:
                            _fill_polygon(buf, scaled, fill)
                        if stroke[3] > 0 and len(scaled) >= 2:
                            for i in range(len(scaled) - 1):
                                _stroke_line(
                                    buf, scaled[i][0], scaled[i][1],
                                    scaled[i + 1][0], scaled[i + 1][1],
                                    stroke, stroke_w,
                                )
            elif tag in ("g", "svg"):
                pass
            # children
            for child in list(el):
                _draw(child)

        _draw(root)
        self._texture = buf
        _TEX_CACHE[key] = buf
        return buf

    # ---- DPG bridge -------------------------------------------------------

    def to_dpg_texture(self, registry: Any) -> int:
        """Register the rasterised icon with a DPG texture registry.

        *registry* is the value returned by ``dpg.add_texture_registry``.
        The DPG texture id is cached on the icon so repeated calls return
        the same id without re-uploading. When :mod:`dearpygui` is not
        installed the method raises :class:`ImportError` with the usual
        ``pip install Pharos Engine[editor]`` hint.
        """
        if self._dpg_texture_id is not None:
            return self._dpg_texture_id
        try:
            import dearpygui.dearpygui as dpg  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - defensive
            raise ImportError(
                "SVGIcon.to_dpg_texture requires dearpygui: "
                "pip install Pharos Engine[editor]"
            ) from exc
        arr = self.rasterize().astype(np.float32) / 255.0
        flat = arr.reshape(-1).tolist()
        tex_id = dpg.add_static_texture(
            self.size, self.size, flat, parent=registry
        )
        self._dpg_texture_id = int(tex_id)
        return self._dpg_texture_id

    # ---- YAML round-trip --------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "svg_xml": self.svg_xml,
            "size": int(self.size),
            "default_fill": list(self.default_fill),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SVGIcon":
        if not isinstance(data, dict):
            raise TypeError(
                f"SVGIcon.from_dict: data must be a dict; "
                f"got {type(data).__name__}"
            )
        return cls(
            svg_xml=data.get("svg_xml", ""),
            size=int(data.get("size", 16)),
            default_fill=tuple(data.get("default_fill", (255, 255, 255, 255))),
        )


__all__ = ["SVGIcon", "clear_cache"]
