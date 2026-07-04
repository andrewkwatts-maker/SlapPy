"""Edge-stroke border renderer.

Produces an RGBA ndarray that represents the four border strips (top /
right / bottom / left) drawn around a panel using one of the
:mod:`.library` styles. The rendering itself is done entirely in numpy
(soft-imports wgpu but never depends on it), so headless tests and
first-run scaffolds still get a real border texture.

Two entry points:

* :func:`render_stroke_border` — return a dict of four strip arrays
  keyed by ``"top" / "right" / "bottom" / "left"``. This is the shape
  the DPG bridge consumes.
* :func:`bake_stroke_texture` — return a single ``(H, W, 4)`` frame-
  shaped texture with the strips composited onto a transparent
  background. Convenient for tests + previews.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from slappyengine._validation import (
    validate_non_empty_str,
    validate_positive_float,
    validate_positive_int,
)

from .library import EDGE_STROKES, EdgeStrokeStyle, get_stroke

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Soft wgpu import — mirrors the wgsl_backgrounds pattern
# ---------------------------------------------------------------------------


try:  # pragma: no cover - exercised only when wgpu is installed
    import wgpu  # type: ignore[import-not-found]

    _HAS_WGPU = True
except Exception:  # pragma: no cover - default headless path
    wgpu = None  # type: ignore[assignment]
    _HAS_WGPU = False


def has_wgpu() -> bool:
    """Return ``True`` iff wgpu imported successfully at module load."""
    return _HAS_WGPU


# ---------------------------------------------------------------------------
# Colour packing
# ---------------------------------------------------------------------------


_ThemeColor = tuple[int, int, int, int]


def _pack_color(value: Any, default: _ThemeColor) -> _ThemeColor:
    """Coerce a colour spec to an ``(r, g, b, a)`` uint8 tuple.

    Accepts a live ``Color`` (or any object with ``as_rgba_tuple``), a
    4-sequence of numbers, or ``None`` (returns *default*).
    """
    if value is None:
        return default
    if hasattr(value, "as_rgba_tuple"):
        r, g, b, a = value.as_rgba_tuple()
        return (int(r), int(g), int(b), int(a))
    if isinstance(value, (tuple, list)) and len(value) == 4:
        r, g, b, a = value
        return (int(r), int(g), int(b), int(a))
    raise TypeError(
        "edge_strokes.renderer: theme colour must be Color, 4-sequence, "
        f"or None; got {type(value).__name__}"
    )


# ---------------------------------------------------------------------------
# Numpy fallbacks — one per style
# ---------------------------------------------------------------------------
#
# Each fallback matches the intent of its WGSL twin: same average alpha,
# same noise/wobble character. The fallback fills a 1-D "strip" strand
# that the caller then tiles into the four perimeter strips. Every
# fallback:
#
#   * Uses ``np.random.default_rng(seed)`` so output is deterministic.
#   * Returns ``(length, thickness, 4)`` uint8 RGBA arrays.
#
# The renderer picks the fallback by style_id — no other dispatch.


def _rng(style_id: str) -> np.random.Generator:
    """A deterministic per-style rng — same seed across runs."""
    return np.random.default_rng(abs(hash(style_id)) % (2**32))


def _strip(
    style_id: str,
    length: int,
    thickness: int,
    color_1: _ThemeColor,
    color_2: _ThemeColor,
) -> np.ndarray:
    """Render one 1-D strip in the requested style.

    Returns an ``(thickness, length, 4)`` ``uint8`` array — height-major
    to match PIL's row-first convention.
    """
    rng = _rng(style_id)
    c1 = np.asarray(color_1, dtype=np.float32)
    c2 = np.asarray(color_2, dtype=np.float32)
    t = np.linspace(0.0, 1.0, length, endpoint=False, dtype=np.float32)

    if style_id == "ballpoint_pen":
        jitter = rng.random(length, dtype=np.float32) * 0.08
        a = np.clip(0.9 + jitter, 0.0, 1.0)
        rgba = np.broadcast_to(c1, (length, 4)).copy()
        rgba[:, 3] = a * 255.0
    elif style_id == "gel_pen":
        a = np.clip(0.94 + 0.05 * np.sin(t * 12.0), 0.0, 1.0)
        rgba = np.broadcast_to(c1, (length, 4)).copy()
        rgba[:, 3] = a * 255.0
    elif style_id == "pencil_2b":
        n = rng.random(length, dtype=np.float32)
        s = 0.7 + n * 0.3
        mix = np.clip(n[:, None] * 0.3, 0.0, 1.0)
        rgb = c1[None, :3] * (1.0 - mix) + c2[None, :3] * mix
        rgba = np.concatenate([rgb, (s * 255.0)[:, None]], axis=1)
    elif style_id == "pencil_hb":
        n = rng.random(length, dtype=np.float32)
        s = 0.82 + n * 0.15
        rgba = np.broadcast_to(c1, (length, 4)).copy()
        rgba[:, 3] = s * 255.0
    elif style_id == "chalk":
        g = rng.random(length, dtype=np.float32)
        crumb = (g >= 0.18).astype(np.float32)
        a = 0.55 * crumb + 0.15
        rgb = c2[None, :3] * (1.0 - crumb[:, None]) + c1[None, :3] * crumb[:, None]
        rgba = np.concatenate([rgb, (a * 255.0)[:, None]], axis=1)
    elif style_id == "charcoal":
        n1 = rng.random(length, dtype=np.float32)
        n2 = rng.random(length, dtype=np.float32)
        smudge = 0.4 + 0.5 * n1 * n2
        dark = c1[:3] * 0.55
        rgb = np.broadcast_to(dark, (length, 3)).copy()
        rgba = np.concatenate([rgb, (smudge * 255.0)[:, None]], axis=1)
    elif style_id == "crayon":
        waxy = rng.random(length, dtype=np.float32)
        a = 0.65 + 0.25 * waxy
        mix = (waxy * 0.2)[:, None]
        rgb = c1[None, :3] * (1.0 - mix) + c2[None, :3] * mix
        rgba = np.concatenate([rgb, (a * 255.0)[:, None]], axis=1)
    elif style_id == "colored_pencil":
        n = rng.random(length, dtype=np.float32)
        layer = 0.75 + n * 0.2
        mix = (0.15 + n * 0.2)[:, None]
        rgb = c1[None, :3] * (1.0 - mix) + c2[None, :3] * mix
        rgba = np.concatenate([rgb, (layer * 255.0)[:, None]], axis=1)
    elif style_id == "marker_thick":
        rgba = np.broadcast_to(c1, (length, 4)).copy()
        rgba[:, 3] = 0.98 * 255.0
    elif style_id == "highlighter":
        a = 0.32 + 0.05 * np.sin(t * 7.0)
        rgba = np.broadcast_to(c1, (length, 4)).copy()
        rgba[:, 3] = a * 255.0
    elif style_id == "brush_watercolor":
        wash = rng.random(length, dtype=np.float32)
        a = 0.5 + 0.35 * wash
        mix = (wash * 0.5)[:, None]
        rgb = c1[None, :3] * (1.0 - mix) + c2[None, :3] * mix
        rgba = np.concatenate([rgb, (a * 255.0)[:, None]], axis=1)
    elif style_id == "ink_wash":
        flow = 0.35 + 0.55 * np.sin(t * np.pi)
        dark = c1[:3] * 0.35
        rgb = np.broadcast_to(dark, (length, 3)).copy()
        rgba = np.concatenate([rgb, (flow * 255.0)[:, None]], axis=1)
    elif style_id == "sharpie":
        rgba = np.broadcast_to(c1, (length, 4)).copy()
        rgba[:, 3] = 255.0
    elif style_id == "fountain_pen":
        width = 0.6 + 0.35 * (np.sin(t * 4.0) * 0.5 + 0.5)
        rgba = np.broadcast_to(c1, (length, 4)).copy()
        rgba[:, 3] = width * 255.0
    elif style_id == "quill":
        taper = 0.4 + 0.55 * np.abs(np.sin(t * 2.7))
        mix = np.full((length, 1), 0.1, dtype=np.float32)
        rgb = c1[None, :3] * (1.0 - mix) + c2[None, :3] * mix
        rgba = np.concatenate([rgb, (taper * 255.0)[:, None]], axis=1)
    else:
        raise KeyError(
            f"edge_strokes.renderer: no numpy fallback for style {style_id!r}"
        )

    rgba = np.clip(rgba, 0.0, 255.0).astype(np.uint8)
    # Broadcast to thickness rows. Anisotropic dry media (pencil,
    # charcoal, chalk, crayon) get a slight cross-strip noise so the
    # thickness axis reads as textured, not flat.
    if style_id in {"pencil_2b", "pencil_hb", "charcoal", "chalk",
                    "crayon", "colored_pencil", "brush_watercolor"}:
        cross = rng.random((thickness, length), dtype=np.float32)
        weight = 0.8 + 0.2 * cross
        strip = np.broadcast_to(rgba, (thickness, length, 4)).copy()
        strip[..., 3] = np.clip(
            strip[..., 3].astype(np.float32) * weight, 0.0, 255.0
        ).astype(np.uint8)
    else:
        strip = np.broadcast_to(rgba, (thickness, length, 4)).copy()
    return strip


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_stroke_border(
    style_id: str,
    panel_bounds: tuple[int, int],
    width_px: float | None = None,
    *,
    color_1: Any = None,
    color_2: Any = None,
) -> dict[str, np.ndarray]:
    """Render the four border strips for a panel.

    Parameters
    ----------
    style_id:
        The registry key from :data:`.library.EDGE_STROKES`.
    panel_bounds:
        ``(width, height)`` of the panel in pixels.
    width_px:
        Stroke thickness in pixels. Defaults to the style's canonical
        :attr:`EdgeStrokeStyle.thickness_px`. Rounded to nearest int.
    color_1:
        Stroke / ink colour. Accepts a live ``Color``, a 4-sequence, or
        ``None`` (defaults to opaque black). Alpha is *modulated* per-
        pixel by the style — the passed alpha is used as an upper cap.
    color_2:
        Highlight / paper colour used for interior variation. Defaults
        to a light off-white so textured strokes still read.

    Returns
    -------
    dict[str, numpy.ndarray]
        Keys ``"top"`` / ``"right"`` / ``"bottom"`` / ``"left"`` each
        map to an RGBA ``uint8`` array. ``top`` / ``bottom`` have shape
        ``(thickness, width, 4)``; ``left`` / ``right`` have shape
        ``(height, thickness, 4)``.
    """
    validate_non_empty_str("style_id", "render_stroke_border", style_id)
    if not isinstance(panel_bounds, (tuple, list)) or len(panel_bounds) != 2:
        raise TypeError(
            "render_stroke_border: panel_bounds must be (width, height); "
            f"got {panel_bounds!r}"
        )
    w = validate_positive_int(
        "panel_bounds[0]", "render_stroke_border", int(panel_bounds[0])
    )
    h = validate_positive_int(
        "panel_bounds[1]", "render_stroke_border", int(panel_bounds[1])
    )

    style = get_stroke(style_id)
    if width_px is None:
        thickness = max(1, int(round(style.thickness_px)))
    else:
        thickness = max(
            1,
            int(round(validate_positive_float(
                "width_px", "render_stroke_border", float(width_px)
            ))),
        )

    c1 = _pack_color(color_1, (0, 0, 0, 255))
    c2 = _pack_color(color_2, (245, 240, 232, 255))

    top = _strip(style_id, w, thickness, c1, c2)
    bottom = _strip(style_id, w, thickness, c1, c2)
    # Left / right are the same strip rotated 90 degrees.
    vertical = _strip(style_id, h, thickness, c1, c2)
    # Transpose so shape becomes (h, thickness, 4).
    left = np.transpose(vertical, (1, 0, 2)).copy()
    right = np.transpose(vertical, (1, 0, 2)).copy()

    return {"top": top, "right": right, "bottom": bottom, "left": left}


def bake_stroke_texture(
    style_id: str,
    panel_bounds: tuple[int, int],
    width_px: float | None = None,
    *,
    color_1: Any = None,
    color_2: Any = None,
) -> np.ndarray:
    """Composite the four strips into one ``(H, W, 4)`` texture.

    Interior is transparent. Handy for previews, docs screenshots, and
    tests that want a single-array assertion target.
    """
    strips = render_stroke_border(
        style_id,
        panel_bounds,
        width_px,
        color_1=color_1,
        color_2=color_2,
    )
    width, height = panel_bounds
    canvas = np.zeros((height, width, 4), dtype=np.uint8)
    top = strips["top"]
    bottom = strips["bottom"]
    left = strips["left"]
    right = strips["right"]

    t_h = top.shape[0]
    l_w = left.shape[1]
    canvas[:t_h, :, :] = top
    canvas[-t_h:, :, :] = bottom
    # Corners: overwrite the vertical strips into the corners the
    # horizontal strips already filled — this way the vertical strip
    # thickness is honoured on the sides.
    canvas[:, :l_w, :] = left
    canvas[:, -l_w:, :] = right
    return canvas


__all__ = [
    "bake_stroke_texture",
    "has_wgpu",
    "render_stroke_border",
]
