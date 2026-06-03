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
    validate_finite_float,
    validate_non_negative_int,
    validate_positive_float,
    validate_positive_int,
    validate_unit_float,
)

from .theme_spec import Color


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


def _coerce_color(
    name: str, fn: str, value: Any
) -> tuple[int, int, int, int]:
    """Accept either a :class:`Color` instance or a 4-tuple of ints."""
    if isinstance(value, Color):
        return value.as_rgba_tuple()
    return _validate_rgba(name, fn, value)


def _optional_color(
    name: str, fn: str, value: Any
) -> tuple[int, int, int, int] | None:
    if value is None:
        return None
    return _coerce_color(name, fn, value)


def _gaussian_blur_rgba(arr: np.ndarray, radius: int) -> np.ndarray:
    """Separable Gaussian blur for an ``(H, W, 4)`` uint8 RGBA array.

    Pure numpy — implements the blur as two 1-D convolutions with a
    Gaussian kernel of standard deviation ``radius``. Edges are handled
    by reflective padding so corners stay smooth rather than smearing
    to zero.
    """
    if radius < 1:
        return arr.copy()
    sigma = float(radius)
    # Kernel half-width = 3 sigma rounded up; covers ~99.7% of energy.
    half = max(1, int(np.ceil(3.0 * sigma)))
    x = np.arange(-half, half + 1, dtype=np.float32)
    k = np.exp(-(x * x) / (2.0 * sigma * sigma))
    k /= k.sum()
    src = arr.astype(np.float32)
    # Horizontal pass — pad along axis=1, convolve per row per channel.
    padded = np.pad(src, ((0, 0), (half, half), (0, 0)), mode="reflect")
    h, w, c = src.shape
    tmp = np.zeros_like(src)
    for i, weight in enumerate(k):
        tmp += weight * padded[:, i : i + w, :]
    # Vertical pass.
    padded = np.pad(tmp, ((half, half), (0, 0), (0, 0)), mode="reflect")
    out = np.zeros_like(src)
    for i, weight in enumerate(k):
        out += weight * padded[i : i + h, :, :]
    return np.clip(out, 0.0, 255.0).astype(np.uint8)


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
# Glassmorphism — backdrop blur + translucent overlay
# ---------------------------------------------------------------------------


def glass_blur(
    source: np.ndarray,
    blur_radius: int = 10,
    opacity: float = 0.1,
    tint: Color | tuple[int, int, int, int] | None = None,
) -> np.ndarray:
    """Apply a frosted-glass blur + translucent overlay to *source*.

    Mirrors EyesOfAzrael's `--glass-bg` / `--glass-blur` CSS contract:
    the underlying viewport region is blurred with a separable Gaussian
    of standard deviation *blur_radius*, then an opaque white (or *tint*)
    overlay at *opacity* is alpha-composited on top.

    Parameters
    ----------
    source:
        ``(H, W, 4)`` uint8 RGBA ndarray — the viewport region behind
        the glass panel.
    blur_radius:
        Gaussian standard deviation in pixels (≥ 1). Larger = more frosted.
    opacity:
        Overlay opacity in ``[0, 1]``. EyesOfAzrael's default is ``0.1``.
    tint:
        Optional overlay colour. ``None`` → pure white (the CSS default
        ``rgba(255, 255, 255, 0.1)``). Accepts a :class:`Color` instance
        or a raw RGBA 4-tuple.
    """
    fn = "glass_blur"
    if not isinstance(source, np.ndarray):
        raise TypeError(
            f"{fn}: source must be a numpy.ndarray; "
            f"got {type(source).__name__}"
        )
    if source.ndim != 3 or source.shape[2] != 4:
        raise ValueError(
            f"{fn}: source must be shape (H, W, 4); got {source.shape}"
        )
    if source.dtype != np.uint8:
        raise TypeError(
            f"{fn}: source must be uint8; got dtype={source.dtype}"
        )
    radius = validate_positive_int("blur_radius", fn, blur_radius)
    op = validate_unit_float("opacity", fn, opacity)
    overlay = _optional_color("tint", fn, tint)
    if overlay is None:
        overlay = (255, 255, 255, 255)
    blurred = _gaussian_blur_rgba(source, radius)
    # Alpha-composite overlay (r, g, b) at the requested opacity over the
    # blurred backdrop. The result keeps the source's alpha channel.
    over_rgb = np.array(overlay[:3], dtype=np.float32)
    backdrop_rgb = blurred[:, :, :3].astype(np.float32)
    mixed = backdrop_rgb * (1.0 - op) + over_rgb * op
    out = np.empty_like(blurred)
    out[:, :, :3] = np.clip(mixed, 0.0, 255.0).astype(np.uint8)
    out[:, :, 3] = blurred[:, :, 3]
    return out


# ---------------------------------------------------------------------------
# Frosted panel — standalone glass texture
# ---------------------------------------------------------------------------


def frosted_panel(
    width: int,
    height: int,
    blur_radius: int = 10,
    opacity: float = 0.1,
    border_color: Color | tuple[int, int, int, int] | None = None,
) -> np.ndarray:
    """Generate a standalone frosted-glass panel texture (no backdrop).

    Synthesises the frosted look from blurred noise: low-frequency
    chroma variation under a translucent white overlay. Optionally
    strokes a 1-pixel border in *border_color*.
    """
    fn = "frosted_panel"
    w, h = _validate_size("size", fn, width, height)
    radius = validate_positive_int("blur_radius", fn, blur_radius)
    op = validate_unit_float("opacity", fn, opacity)
    border = _optional_color("border_color", fn, border_color)
    # Seed a deterministic noise field — same panel size → identical art.
    rng = np.random.default_rng(0xF305 ^ (w * 1009 + h))
    noise = rng.integers(120, 200, size=(h, w, 4), dtype=np.uint16)
    noise[:, :, 3] = 255
    noise_u8 = noise.astype(np.uint8)
    blurred = _gaussian_blur_rgba(noise_u8, radius)
    # White overlay at the requested opacity.
    over_rgb = np.array((255.0, 255.0, 255.0), dtype=np.float32)
    mixed = blurred[:, :, :3].astype(np.float32) * (1.0 - op) + over_rgb * op
    out = np.empty_like(blurred)
    out[:, :, :3] = np.clip(mixed, 0.0, 255.0).astype(np.uint8)
    # Half-transparent overall — frosted panels sit over viewport content.
    out[:, :, 3] = np.uint8(int(round(160 + 80 * op)))
    if border is not None:
        out[0, :, :] = border
        out[h - 1, :, :] = border
        out[:, 0, :] = border
        out[:, w - 1, :] = border
    return out


# ---------------------------------------------------------------------------
# Dot grid — bullet-journal background
# ---------------------------------------------------------------------------


def dot_grid(
    width: int,
    height: int,
    dot_color: Color | tuple[int, int, int, int],
    dot_radius: int = 1,
    spacing: int = 8,
    bg_color: Color | tuple[int, int, int, int] | None = None,
) -> np.ndarray:
    """Bullet-journal style dot pattern.

    Dots are placed on a regular ``spacing`` × ``spacing`` lattice
    starting at ``(spacing/2, spacing/2)`` so a ``W = 80, spacing = 8``
    texture carries exactly ``W/spacing = 10`` dots per row.

    Parameters
    ----------
    width, height:
        Output dimensions in pixels.
    dot_color:
        RGBA colour of each dot.
    dot_radius:
        Half-extent of each dot in pixels (≥ 1). A radius of 1 paints a
        single pixel; larger radii paint a filled square (cheap and
        crisp at journaling scales).
    spacing:
        Distance between dot centres along both axes (≥ 1).
    bg_color:
        Optional background fill. ``None`` → fully transparent.
    """
    fn = "dot_grid"
    w, h = _validate_size("size", fn, width, height)
    dot_rgba = _coerce_color("dot_color", fn, dot_color)
    r = validate_positive_int("dot_radius", fn, dot_radius)
    s = validate_positive_int("spacing", fn, spacing)
    bg = _optional_color("bg_color", fn, bg_color)
    out = np.zeros((h, w, 4), dtype=np.uint8)
    if bg is not None:
        out[:, :, :] = bg
    # Place dot centres at (s/2, s/2), (s/2, 3s/2), … so the (w/s)*(h/s)
    # count contract holds for any width / height divisible by spacing.
    half = s // 2
    ys = np.arange(half, h, s)
    xs = np.arange(half, w, s)
    for cy in ys:
        for cx in xs:
            y0 = max(0, cy - (r - 1))
            y1 = min(h, cy + r)
            x0 = max(0, cx - (r - 1))
            x1 = min(w, cx + r)
            out[y0:y1, x0:x1, :] = dot_rgba
    return out


# ---------------------------------------------------------------------------
# Parchment — cozy-diary background with dark edges
# ---------------------------------------------------------------------------


def parchment(
    width: int,
    height: int,
    base_color: Color | tuple[int, int, int, int],
    edge_dark: float = 0.85,
    noise_amount: float = 0.05,
) -> np.ndarray:
    """Cozy-diary parchment background.

    Fills the canvas with *base_color*, applies a radial darkening
    vignette that multiplies the edge pixels by *edge_dark*, then adds a
    light per-pixel noise modulation of strength *noise_amount* so the
    surface reads as paper rather than flat fill.

    Parameters
    ----------
    width, height:
        Output dimensions.
    base_color:
        RGBA base parchment colour.
    edge_dark:
        Multiplier applied to the four corners, in ``[0, 1]``. ``1.0``
        leaves the edges unchanged; lower values darken them.
    noise_amount:
        Per-pixel noise strength as a fraction of the base intensity,
        in ``[0, 1]``. Typical diary look is ``~0.03 – 0.08``.
    """
    fn = "parchment"
    w, h = _validate_size("size", fn, width, height)
    base = _coerce_color("base_color", fn, base_color)
    dark = validate_unit_float("edge_dark", fn, edge_dark)
    amt = validate_unit_float("noise_amount", fn, noise_amount)
    # Radial vignette: dist² → [0, 1] → multiplier in [edge_dark, 1.0].
    cy = (h - 1) / 2.0
    cx = (w - 1) / 2.0
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d2 = ((xx - cx) / max(cx, 1.0)) ** 2 + ((yy - cy) / max(cy, 1.0)) ** 2
    d2 = np.clip(d2, 0.0, 1.0)
    mult = 1.0 - (1.0 - dark) * d2  # 1 at centre, edge_dark in corners
    rgb = np.array(base[:3], dtype=np.float32).reshape(1, 1, 3)
    img = rgb * mult[:, :, None]
    rng = np.random.default_rng(0xCAFE ^ (w * 7919 + h))
    noise = rng.uniform(-amt, amt, size=(h, w, 1)).astype(np.float32)
    img = img * (1.0 + noise)
    out = np.empty((h, w, 4), dtype=np.uint8)
    out[:, :, :3] = np.clip(img, 0.0, 255.0).astype(np.uint8)
    out[:, :, 3] = base[3]
    return out


# ---------------------------------------------------------------------------
# Watercolor wash — scrapbook-summer soft splats
# ---------------------------------------------------------------------------


def watercolor_wash(
    width: int,
    height: int,
    color_palette: list[Color] | list[tuple[int, int, int, int]],
    wash_count: int = 3,
    opacity: float = 0.3,
    seed: int = 314159,
) -> np.ndarray:
    """Scrapbook-summer style soft watercolor washes.

    Builds *wash_count* soft-edged elliptical splats sampled from
    *color_palette*, each at *opacity*, and blends them additively over
    a transparent canvas.

    Parameters
    ----------
    width, height:
        Output dimensions.
    color_palette:
        List of palette colours (Color or RGBA tuple). Must be non-empty.
    wash_count:
        Number of splats to draw (≥ 1).
    opacity:
        Per-wash peak opacity in ``[0, 1]``.
    seed:
        RNG seed so identical inputs reproduce identical art.
    """
    fn = "watercolor_wash"
    w, h = _validate_size("size", fn, width, height)
    n = validate_positive_int("wash_count", fn, wash_count)
    op = validate_unit_float("opacity", fn, opacity)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise TypeError(f"{fn}: seed must be int; got {type(seed).__name__}")
    if not hasattr(color_palette, "__len__") or len(color_palette) == 0:
        raise ValueError(
            f"{fn}: color_palette must be a non-empty sequence"
        )
    palette: list[tuple[int, int, int, int]] = []
    for i, c in enumerate(color_palette):
        palette.append(_coerce_color(f"color_palette[{i}]", fn, c))
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    accum = np.zeros((h, w, 3), dtype=np.float32)
    coverage = np.zeros((h, w), dtype=np.float32)
    for i in range(n):
        cx = float(rng.uniform(0, w))
        cy = float(rng.uniform(0, h))
        # Splat radii vary in [min(w,h)*0.15, min(w,h)*0.45].
        rx = float(rng.uniform(min(w, h) * 0.15, min(w, h) * 0.45))
        ry = float(rng.uniform(min(w, h) * 0.15, min(w, h) * 0.45))
        d2 = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
        # Soft Gaussian-ish falloff; ≈1 at centre, 0 outside ellipse.
        env = np.clip(np.exp(-d2 * 2.0), 0.0, 1.0)
        col = palette[i % len(palette)]
        rgb = np.array(col[:3], dtype=np.float32)
        accum += rgb[None, None, :] * (env * op)[:, :, None]
        coverage = coverage + env * op
    out = np.empty((h, w, 4), dtype=np.uint8)
    out[:, :, :3] = np.clip(accum, 0.0, 255.0).astype(np.uint8)
    out[:, :, 3] = np.clip(coverage * 255.0, 0.0, 255.0).astype(np.uint8)
    return out


# ---------------------------------------------------------------------------
# Re-export float helpers so static analysis sees the dependency.
# ---------------------------------------------------------------------------

_ = validate_positive_float
_ = validate_finite_float


__all__ = [
    "dot_grid",
    "frosted_panel",
    "glass_blur",
    "highlighter_stroke",
    "noise_glitter",
    "paper_shadow",
    "parchment",
    "ruled_paper",
    "watercolor_wash",
]
