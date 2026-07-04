"""Renderer for the :mod:`page_linings` shader library.

Follows the same WGSL-first / numpy-fallback pattern used by
:mod:`~slappyengine.ui.theme.wgsl_backgrounds`:

* When :mod:`wgpu` imports and a live GPU context is registered, the
  WGSL source is compiled + dispatched through the engine's compute
  pipeline. The dispatch harness is deferred to a follow-up commit; the
  current build hits the numpy fallback deterministically so headless
  test rigs never depend on a GPU.
* When :mod:`wgpu` is missing (or fallback is forced), a numpy analogue
  paints the same pattern the WGSL shader would produce. Each style has
  a hand-written fallback that respects its ``tile_size`` so
  :func:`render_lining` output is tileable.

Every public helper returns ``(H, W, 4)`` ``uint8`` RGBA arrays.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from .library import LiningStyle, get_lining

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Soft wgpu import (matches wgsl_backgrounds.py)
# ---------------------------------------------------------------------------


try:  # pragma: no cover - only exercised when wgpu is installed
    import wgpu  # type: ignore[import-not-found]

    _HAS_WGPU = True
except Exception:  # pragma: no cover - default headless path
    wgpu = None  # type: ignore[assignment]
    _HAS_WGPU = False


def has_wgpu() -> bool:
    """Return ``True`` iff wgpu imported successfully at module load."""
    return _HAS_WGPU


# ---------------------------------------------------------------------------
# Colour validation
# ---------------------------------------------------------------------------


def _validate_size(size: Any) -> tuple[int, int]:
    if not isinstance(size, (tuple, list)) or len(size) != 2:
        raise TypeError(
            f"render_lining: size must be a (width, height) 2-sequence; "
            f"got {size!r}"
        )
    w = int(size[0])
    h = int(size[1])
    if w <= 0 or h <= 0:
        raise ValueError(
            f"render_lining: size must be positive; got ({w}, {h})"
        )
    return w, h


def _validate_rgb(name: str, value: Any) -> tuple[int, int, int]:
    if value is None:
        raise TypeError(f"render_lining: {name} must not be None here")
    if not hasattr(value, "__len__") or len(value) < 3:
        raise TypeError(
            f"render_lining: {name} must be a 3-sequence (r, g, b); got {value!r}"
        )
    out: list[int] = []
    for i, ch in enumerate("rgb"):
        c = int(value[i])
        if c < 0 or c > 255:
            raise ValueError(
                f"render_lining: {name}[{i}] ({ch}) must be in [0, 255]; got {c}"
            )
        out.append(c)
    return (out[0], out[1], out[2])


def _rgb_to_float(rgb: tuple[int, int, int]) -> np.ndarray:
    return np.array([rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0], dtype=np.float32)


# ---------------------------------------------------------------------------
# Per-style numpy fallbacks
# ---------------------------------------------------------------------------
#
# Each takes (width, height, paper_rgb_float, ink_rgb_float) and returns a
# float32 ndarray of shape (H, W, 3) in [0, 1]. The caller composites in
# alpha and casts to uint8.
# ---------------------------------------------------------------------------


def _make_grid(width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    x = np.arange(width, dtype=np.float32)
    y = np.arange(height, dtype=np.float32)
    return np.meshgrid(x, y)  # returns (X, Y)


def _fp_ruled_paper(w: int, h: int, paper: np.ndarray, ink: np.ndarray) -> np.ndarray:
    _, Y = _make_grid(w, h)
    X, _ = _make_grid(w, h)
    line = (Y % 24.0 >= 23.0).astype(np.float32)
    margin = ((X >= 32.0) & (X < 33.0)).astype(np.float32)
    red = np.array([1.0, 0.44, 0.71], dtype=np.float32)
    out = paper[None, None, :] * (1.0 - line[..., None]) + ink[None, None, :] * line[..., None]
    out = out * (1.0 - margin[..., None]) + red[None, None, :] * margin[..., None]
    return out


def _fp_dot_grid(w: int, h: int, paper: np.ndarray, ink: np.ndarray) -> np.ndarray:
    X, Y = _make_grid(w, h)
    s = 24.0
    r = 1.5
    cx = (X % s) - s * 0.5
    cy = (Y % s) - s * 0.5
    d = np.sqrt(cx * cx + cy * cy)
    dot = np.clip(1.0 - (d - r) / 0.5, 0.0, 1.0) * 0.6
    return paper[None, None, :] * (1.0 - dot[..., None]) + ink[None, None, :] * dot[..., None]


def _fp_graph_grid(w: int, h: int, paper: np.ndarray, ink: np.ndarray) -> np.ndarray:
    X, Y = _make_grid(w, h)
    s = 10.0
    gx = (X % s < 1.0).astype(np.float32)
    gy = (Y % s < 1.0).astype(np.float32)
    line = np.clip(gx + gy, 0.0, 1.0) * 0.5
    return paper[None, None, :] * (1.0 - line[..., None]) + ink[None, None, :] * line[..., None]


def _fp_isometric_grid(w: int, h: int, paper: np.ndarray, ink: np.ndarray) -> np.ndarray:
    X, Y = _make_grid(w, h)
    s = 24.0
    hh = s * 0.8660254
    a = (Y % s) < 1.0
    b = ((Y + X * 1.7320508) % (2.0 * hh)) < 1.0
    c = ((Y - X * 1.7320508 + 4096.0) % (2.0 * hh)) < 1.0
    line = np.clip(a.astype(np.float32) + b.astype(np.float32) + c.astype(np.float32), 0.0, 1.0) * 0.4
    return paper[None, None, :] * (1.0 - line[..., None]) + ink[None, None, :] * line[..., None]


def _fp_hex_grid(w: int, h: int, paper: np.ndarray, ink: np.ndarray) -> np.ndarray:
    X, Y = _make_grid(w, h)
    edge = np.abs(np.sin(X * 0.1815) * np.sin(Y * 0.1047))
    line = np.clip((edge - 0.95) / 0.05, 0.0, 1.0) * 0.35
    return paper[None, None, :] * (1.0 - line[..., None]) + ink[None, None, :] * line[..., None]


def _fp_music_staff(w: int, h: int, paper: np.ndarray, ink: np.ndarray) -> np.ndarray:
    _, Y = _make_grid(w, h)
    s = 48.0
    yy = Y % s
    line = np.zeros_like(yy, dtype=np.float32)
    for base in (0.0, 8.0, 16.0, 24.0, 32.0):
        line = np.maximum(line, ((yy >= base) & (yy < base + 1.0)).astype(np.float32))
    line *= 0.9
    return paper[None, None, :] * (1.0 - line[..., None]) + ink[None, None, :] * line[..., None]


def _fp_blank_cream(w: int, h: int, paper: np.ndarray, ink: np.ndarray) -> np.ndarray:
    X, Y = _make_grid(w, h)
    # Match WGSL fract(sin(x*12.9898 + y*78.233) * 43758.5453)
    n = np.mod(np.sin(X * 12.9898 + Y * 78.233) * 43758.5453, 1.0)
    noise = (n - 0.5) * 0.02
    base = paper[None, None, :] + noise[..., None]
    return base


def _fp_parchment_aged(w: int, h: int, paper: np.ndarray, ink: np.ndarray) -> np.ndarray:
    X, Y = _make_grid(w, h)
    s = 128.0
    x = X % s
    y = Y % s
    cx = x - s * 0.5
    cy = y - s * 0.5
    d = np.sqrt(cx * cx + cy * cy) / (s * 0.5)
    stain = np.clip((d - 0.6) / 0.45, 0.0, 1.0) * 0.25
    n = np.mod(np.sin(X * 3.1 + Y * 5.7) * 91.31, 1.0) * 0.04
    mixed = paper[None, None, :] * (1.0 - stain[..., None]) + ink[None, None, :] * stain[..., None]
    return mixed + (n - 0.02)[..., None]


def _fp_kraft_paper(w: int, h: int, paper: np.ndarray, ink: np.ndarray) -> np.ndarray:
    X, Y = _make_grid(w, h)
    s = 32.0
    x = X % s
    y = Y % s
    f = np.mod(np.sin(np.floor(x * 0.5) * 3.7 + np.floor(y) * 7.1) * 12.9, 1.0)
    stripe = (f >= 0.88).astype(np.float32) * 0.5
    return paper[None, None, :] * (1.0 - stripe[..., None]) + ink[None, None, :] * stripe[..., None]


def _fp_watercolor_paper(w: int, h: int, paper: np.ndarray, ink: np.ndarray) -> np.ndarray:
    X, Y = _make_grid(w, h)
    s = 4.0
    x = X % s
    y = Y % s
    bump = np.mod(np.sin(np.floor(x) * 12.9 + np.floor(y) * 78.2) * 43758.5, 1.0)
    rough = np.clip((bump - 0.4) / 0.5, 0.0, 1.0) * 0.25
    return paper[None, None, :] * (1.0 - rough[..., None]) + ink[None, None, :] * rough[..., None]


def _fp_graph_engineering(w: int, h: int, paper: np.ndarray, ink: np.ndarray) -> np.ndarray:
    X, Y = _make_grid(w, h)
    sm = 5.0
    bg = 25.0
    mx = (X % sm < 1.0).astype(np.float32)
    my = (Y % sm < 1.0).astype(np.float32)
    minor = np.clip(mx + my, 0.0, 1.0)
    bx = (X % bg < 1.0).astype(np.float32)
    by = (Y % bg < 1.0).astype(np.float32)
    major = np.clip(bx + by, 0.0, 1.0)
    line = np.maximum(minor * 0.25, major * 0.65)
    return paper[None, None, :] * (1.0 - line[..., None]) + ink[None, None, :] * line[..., None]


def _fp_polka_dot_soft(w: int, h: int, paper: np.ndarray, ink: np.ndarray) -> np.ndarray:
    X, Y = _make_grid(w, h)
    s = 32.0
    r = 4.0
    cx = (X % s) - s * 0.5
    cy = (Y % s) - s * 0.5
    d = np.sqrt(cx * cx + cy * cy)
    dot = np.clip(1.0 - (d - r) / 1.5, 0.0, 1.0) * 0.7
    return paper[None, None, :] * (1.0 - dot[..., None]) + ink[None, None, :] * dot[..., None]


def _fp_star_scatter(w: int, h: int, paper: np.ndarray, ink: np.ndarray) -> np.ndarray:
    X, Y = _make_grid(w, h)
    s = 32.0
    x = X % s
    y = Y % s
    cx = x - s * 0.5
    cy = y - s * 0.5
    d = np.sqrt(cx * cx + cy * cy)
    sparkle = np.mod(
        np.sin(np.floor(X / s) * 12.9 + np.floor(Y / s) * 78.2) * 43758.5, 1.0
    )
    dot = np.clip(1.0 - (d - 1.0) / 1.0, 0.0, 1.0) * (sparkle >= 0.65).astype(np.float32)
    return paper[None, None, :] * (1.0 - dot[..., None]) + ink[None, None, :] * dot[..., None]


def _fp_linen_woven(w: int, h: int, paper: np.ndarray, ink: np.ndarray) -> np.ndarray:
    X, Y = _make_grid(w, h)
    vx = np.abs(np.sin(X * 0.7854))
    vy = np.abs(np.sin(Y * 0.7854))
    weave = (vx + vy) * 0.5 * 0.35
    return paper[None, None, :] * (1.0 - weave[..., None]) + ink[None, None, :] * weave[..., None]


def _fp_notebook_college(w: int, h: int, paper: np.ndarray, ink: np.ndarray) -> np.ndarray:
    X, Y = _make_grid(w, h)
    line = ((Y % 16.0) >= 15.0).astype(np.float32) * 0.85
    margin = ((X >= 48.0) & (X < 49.0)).astype(np.float32) * 0.9
    red = np.array([0.90, 0.45, 0.55], dtype=np.float32)
    out = paper[None, None, :] * (1.0 - line[..., None]) + ink[None, None, :] * line[..., None]
    out = out * (1.0 - margin[..., None]) + red[None, None, :] * margin[..., None]
    return out


_FALLBACKS = {
    "ruled_paper": _fp_ruled_paper,
    "dot_grid": _fp_dot_grid,
    "graph_grid": _fp_graph_grid,
    "isometric_grid": _fp_isometric_grid,
    "hex_grid": _fp_hex_grid,
    "music_staff": _fp_music_staff,
    "blank_cream": _fp_blank_cream,
    "parchment_aged": _fp_parchment_aged,
    "kraft_paper": _fp_kraft_paper,
    "watercolor_paper": _fp_watercolor_paper,
    "graph_engineering": _fp_graph_engineering,
    "polka_dot_soft": _fp_polka_dot_soft,
    "star_scatter": _fp_star_scatter,
    "linen_woven": _fp_linen_woven,
    "notebook_college": _fp_notebook_college,
}


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def render_lining(
    style_id: str,
    size: tuple[int, int],
    paper_color: tuple[int, int, int] | None = None,
    line_color: tuple[int, int, int] | None = None,
    *,
    force_fallback: bool = False,
) -> np.ndarray:
    """Bake a page-lining style to an RGBA texture.

    When :mod:`wgpu` is installed and a live GPU context is registered
    the WGSL source is dispatched through the engine's compute pipeline.
    Otherwise the numpy fallback paints the same pattern deterministically.

    Parameters
    ----------
    style_id:
        A registered lining id (see :func:`list_linings`).
    size:
        ``(width, height)`` of the output texture in pixels; both > 0.
    paper_color:
        Optional ``(r, g, b)`` override for the paper anchor. Defaults
        to the style's :attr:`LiningStyle.default_paper`.
    line_color:
        Optional ``(r, g, b)`` override for the line/ink anchor. Defaults
        to the style's :attr:`LiningStyle.default_ink`.
    force_fallback:
        When ``True`` skip the GPU dispatch attempt and go straight to
        the numpy fallback. Used by tests + the numpy CI matrix.

    Returns
    -------
    numpy.ndarray
        ``(height, width, 4)`` ``uint8`` RGBA array; alpha is 255.
    """
    style = get_lining(style_id)
    w, h = _validate_size(size)
    paper_rgb = _validate_rgb("paper_color", paper_color) if paper_color is not None else style.default_paper
    ink_rgb = _validate_rgb("line_color", line_color) if line_color is not None else style.default_ink

    if not force_fallback and _HAS_WGPU:
        gpu = _try_gpu(style, w, h, paper_rgb, ink_rgb)
        if gpu is not None:
            return gpu

    return _dispatch_fallback(style, w, h, paper_rgb, ink_rgb)


def bake_lining_texture(
    style_id: str,
    size: tuple[int, int],
    **uniforms: Any,
) -> np.ndarray:
    """Convenience wrapper — bakes and applies named uniform overrides.

    Recognised uniforms:

    * ``paper_color`` — 3-sequence override for the paper anchor.
    * ``line_color`` — 3-sequence override for the ink anchor.
    * ``force_fallback`` — ``bool`` toggle for the numpy path.

    Unknown uniform keys are ignored (with a debug log) so callers can
    pass a shared uniform bag across multiple style bakes without
    branching per style.
    """
    paper = uniforms.pop("paper_color", None)
    line = uniforms.pop("line_color", None)
    force_fallback = bool(uniforms.pop("force_fallback", False))
    for extra in uniforms:
        logger.debug("bake_lining_texture: ignoring unknown uniform %r", extra)
    return render_lining(
        style_id,
        size,
        paper_color=paper,
        line_color=line,
        force_fallback=force_fallback,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _dispatch_fallback(
    style: LiningStyle,
    w: int,
    h: int,
    paper_rgb: tuple[int, int, int],
    ink_rgb: tuple[int, int, int],
) -> np.ndarray:
    fn = _FALLBACKS.get(style.style_id)
    if fn is None:  # pragma: no cover - registry misalignment safeguard
        raise KeyError(
            f"render_lining: no numpy fallback registered for {style.style_id!r}"
        )
    paper = _rgb_to_float(paper_rgb)
    ink = _rgb_to_float(ink_rgb)
    rgb = fn(w, h, paper, ink)
    rgb = np.clip(rgb, 0.0, 1.0)
    out = np.empty((h, w, 4), dtype=np.uint8)
    out[..., :3] = (rgb * 255.0 + 0.5).astype(np.uint8)
    out[..., 3] = 255
    return out


def _try_gpu(  # pragma: no cover - requires live GPU context
    style: LiningStyle,
    w: int,
    h: int,
    paper_rgb: tuple[int, int, int],
    ink_rgb: tuple[int, int, int],
) -> np.ndarray | None:
    """Attempt a WGSL dispatch through the engine's compute pipeline.

    The current build returns ``None`` when no live context is registered
    so the caller falls back to numpy — matching the ``wgsl_backgrounds``
    module's philosophy of a deferred GPU integration commit.
    """
    try:
        from slappyengine.gpu.context import GPUContext  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        ctx = GPUContext.current()  # type: ignore[attr-defined]
    except Exception:
        return None
    if ctx is None:
        return None
    # Full dispatch is deferred; return None so the fallback path runs.
    return None


__all__ = [
    "bake_lining_texture",
    "has_wgpu",
    "render_lining",
]
