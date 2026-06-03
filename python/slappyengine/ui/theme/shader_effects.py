"""Procedural texture-bake helpers.

Every function in this module returns an ``(H, W, 4)`` uint8 RGBA
ndarray. They are pure-numpy so they run with no GPU dependency — the
intent is to bake light texture maps once at startup (or per resize)
and hand the result to whatever renderer the theme is targeting (DPG
texture registry, PIL canvas, wgpu texture upload, …).

Effects share one set of conventions:

* All numeric inputs validated through ``slappyengine._validation``.
* Returned arrays are ``np.uint8`` shaped ``(height, width, 4)``.
* Colour parameters are ``(r, g, b, a)`` tuples in ``[0, 255]``; we
  validate channel-by-channel.

These primitives back the "no PNG bake" design priority for the
SlapPyEngine theme system: a 100 KB total asset budget is comfortable
even when several backgrounds + highlights are baked on demand.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from slappyengine._validation import (
    validate_non_negative_int,
    validate_positive_float,
    validate_positive_int,
    validate_unit_float,
)


# ---------------------------------------------------------------------------
# Colour-validation helper (local — shape is too narrow for _validation.py)
# ---------------------------------------------------------------------------


def _validate_rgba(name: str, fn: str, value: Any) -> tuple[int, int, int, int]:
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a 4-tuple of ints; "
            f"got {type(value).__name__}"
        )
    if len(value) != 4:
        raise ValueError(
            f"{fn}: {name} must have length 4 (r, g, b, a); "
            f"got length {len(value)}"
        )
    out = []
    for i, ch in enumerate("rgba"):
        c = validate_non_negative_int(f"{name}[{i}] ({ch})", fn, value[i])
        if c > 255:
            raise ValueError(f"{fn}: {name}[{i}] must be <= 255; got {c}")
        out.append(int(c))
    return (out[0], out[1], out[2], out[3])


def _validate_size(name: str, fn: str, w: Any, h: Any) -> tuple[int, int]:
    return (
        validate_positive_int(f"{name} width", fn, w),
        validate_positive_int(f"{name} height", fn, h),
    )


# ---------------------------------------------------------------------------
# Ruled paper — horizontal lines + optional left margin rule
# ---------------------------------------------------------------------------


def ruled_paper(
    width: int,
    height: int,
    line_color: tuple[int, int, int, int] = (180, 200, 230, 255),
    line_spacing: int = 24,
    margin_color: tuple[int, int, int, int] = (240, 120, 120, 255),
    margin_x: int = 32,
    paper_color: tuple[int, int, int, int] = (252, 250, 240, 255),
) -> np.ndarray:
    """Generate a ruled-notebook background texture.

    Parameters
    ----------
    width, height:
        Output dimensions in pixels (both > 0).
    line_color:
        RGBA colour of the horizontal rules.
    line_spacing:
        Vertical pixel spacing between rules; must be ≥ 1.
    margin_color:
        RGBA colour of the optional left margin rule. Set alpha to ``0``
        to disable.
    margin_x:
        Horizontal pixel offset of the margin rule. Set ``< 0`` to omit.
    paper_color:
        Background fill colour.
    """
    fn = "ruled_paper"
    w, h = _validate_size("size", fn, width, height)
    line_rgba = _validate_rgba("line_color", fn, line_color)
    margin_rgba = _validate_rgba("margin_color", fn, margin_color)
    paper_rgba = _validate_rgba("paper_color", fn, paper_color)
    spacing = validate_positive_int("line_spacing", fn, line_spacing)
    # margin_x = -1 disables; otherwise non-negative
    if not isinstance(margin_x, int) or isinstance(margin_x, bool):
        raise TypeError(f"{fn}: margin_x must be int; got {type(margin_x).__name__}")
    out = np.empty((h, w, 4), dtype=np.uint8)
    out[:, :, :] = paper_rgba
    # Horizontal rules
    for y in range(spacing, h, spacing):
        out[y, :, :] = line_rgba
    # Margin rule
    if 0 <= margin_x < w and margin_rgba[3] > 0:
        out[:, margin_x, :] = margin_rgba
    return out


# ---------------------------------------------------------------------------
# Highlighter stroke — fat translucent horizontal band with edge wobble
# ---------------------------------------------------------------------------


def highlighter_stroke(
    width: int,
    height: int,
    color: tuple[int, int, int, int] = (255, 230, 90, 160),
    wobble: float = 0.5,
    seed: int = 1234,
) -> np.ndarray:
    """Generate a translucent highlighter-pen stroke texture.

    The stroke is a horizontal band whose edges are jittered along the
    vertical axis to mimic a pen wobble. The interior alpha falls off
    toward the top + bottom edges so the stroke blends naturally over
    paper.

    Parameters
    ----------
    width, height:
        Output dimensions.
    color:
        RGBA stroke colour. Alpha is the peak alpha; the edge falloff
        applies on top.
    wobble:
        Edge jitter strength in ``[0, 1]``. ``0`` = perfectly straight,
        ``1`` = up to ±height/4 pixels of jitter.
    seed:
        RNG seed so strokes reproduce deterministically.
    """
    fn = "highlighter_stroke"
    w, h = _validate_size("size", fn, width, height)
    rgba = _validate_rgba("color", fn, color)
    wob = validate_unit_float("wobble", fn, wobble)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise TypeError(f"{fn}: seed must be int; got {type(seed).__name__}")
    out = np.zeros((h, w, 4), dtype=np.uint8)
    rng = np.random.default_rng(seed)
    centre = h / 2.0
    band_half = h / 4.0
    jitter_amp = wob * (h / 4.0)
    # Sample a smooth jitter curve along x.
    jitter = rng.normal(0.0, 1.0, size=w)
    # Light smoothing — 5-tap box filter.
    kernel = np.ones(5) / 5.0
    jitter = np.convolve(jitter, kernel, mode="same") * jitter_amp
    yy = np.arange(h).reshape(-1, 1)
    distance = np.abs(yy - (centre + jitter.reshape(1, -1)))
    # Alpha mask — 1.0 at band centre, 0.0 at band edge.
    falloff = np.clip(1.0 - distance / max(band_half, 1.0), 0.0, 1.0)
    alpha = (falloff * rgba[3]).astype(np.uint8)
    out[:, :, 0] = rgba[0]
    out[:, :, 1] = rgba[1]
    out[:, :, 2] = rgba[2]
    out[:, :, 3] = alpha
    return out


# ---------------------------------------------------------------------------
# Paper shadow — Gaussian-falloff drop-shadow texture
# ---------------------------------------------------------------------------


def paper_shadow(
    width: int,
    height: int,
    blur_radius: int = 8,
    color: tuple[int, int, int, int] = (0, 0, 0, 128),
) -> np.ndarray:
    """Generate a soft drop-shadow texture suitable for panel underlays.

    The texture is fully opaque at the centre and falls off through a
    Gaussian envelope to fully transparent at the edges.

    Parameters
    ----------
    width, height:
        Output dimensions.
    blur_radius:
        Standard deviation of the falloff curve in pixels (≥ 1).
    color:
        Base shadow RGBA — alpha is scaled by the falloff envelope.
    """
    fn = "paper_shadow"
    w, h = _validate_size("size", fn, width, height)
    sigma = validate_positive_int("blur_radius", fn, blur_radius)
    rgba = _validate_rgba("color", fn, color)
    cy = (h - 1) / 2.0
    cx = (w - 1) / 2.0
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d2 = (xx - cx) ** 2 + (yy - cy) ** 2
    envelope = np.exp(-d2 / (2.0 * float(sigma) ** 2))
    out = np.empty((h, w, 4), dtype=np.uint8)
    out[:, :, 0] = rgba[0]
    out[:, :, 1] = rgba[1]
    out[:, :, 2] = rgba[2]
    out[:, :, 3] = (envelope * rgba[3]).clip(0, 255).astype(np.uint8)
    return out


# ---------------------------------------------------------------------------
# Noise glitter — sparse sparkle pattern
# ---------------------------------------------------------------------------


def noise_glitter(
    width: int,
    height: int,
    density: float = 0.1,
    color: tuple[int, int, int, int] = (255, 240, 200, 255),
    seed: int = 7,
) -> np.ndarray:
    """Generate a sparse glitter / star-field texture.

    *density* controls the fraction of pixels turned on. Each sparkle
    is a single pixel of *color*; the texture is otherwise fully
    transparent.

    Parameters
    ----------
    width, height:
        Output dimensions.
    density:
        Fraction of pixels lit, in ``[0, 1]``.
    color:
        RGBA colour of the sparkles.
    seed:
        RNG seed so the pattern reproduces deterministically.
    """
    fn = "noise_glitter"
    w, h = _validate_size("size", fn, width, height)
    d = validate_unit_float("density", fn, density)
    rgba = _validate_rgba("color", fn, color)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise TypeError(f"{fn}: seed must be int; got {type(seed).__name__}")
    rng = np.random.default_rng(seed)
    mask = rng.random((h, w)) < d
    out = np.zeros((h, w, 4), dtype=np.uint8)
    out[mask] = rgba
    return out


# ---------------------------------------------------------------------------
# Re-export float helper so static analysis sees the dependency.
# ---------------------------------------------------------------------------

_ = validate_positive_float


__all__ = [
    "highlighter_stroke",
    "noise_glitter",
    "paper_shadow",
    "ruled_paper",
]
