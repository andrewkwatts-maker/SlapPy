"""Renderer for the :mod:`page_linings` shader library.

Follows the same WGSL-first / numpy-fallback pattern used by
:mod:`~pharos_engine.ui.theme.wgsl_backgrounds`:

* When :mod:`wgpu` imports and a live GPU context is registered, the
  WGSL source is compiled + dispatched through the engine's compute
  pipeline. The dispatch harness is deferred to a follow-up commit; the
  current build hits the numpy fallback deterministically so headless
  test rigs never depend on a GPU.
* When :mod:`wgpu` is missing (or fallback is forced), a numpy analogue
  paints the same pattern the WGSL shader would produce. Each style has
  a hand-written fallback that respects its ``tile_size`` so
  :func:`render_lining` output is tileable.

BBB5 (2026-07-19) AAA-quality upgrade
--------------------------------------
The four "default" presets (``ruled_paper``, ``dot_grid``,
``graph_grid``, ``blank_cream``) accept an ``AAAShaderQualityPreset``
via the renderer's ``quality`` kwarg. The three tiers layer paper
grain, line anti-aliasing, rule jitter, warm sun-lit tint,
per-dot alpha variance, and ink bleed on top of the base pattern.
The ``LOW`` tier restores byte-for-byte parity with the pre-upgrade
fallback so existing golden textures keep passing.

Rust migration
--------------
The per-preset fallback bodies are hot enough that per the architectural
directive ("Python = wrapper, Rust = engine") they are marked as
Rust-port candidates. See ``docs/aaa_theme_shaders_2026_07_19.md``.

Every public helper returns ``(H, W, 4)`` ``uint8`` RGBA arrays.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from .library import (
    AAAShaderQualityPreset,
    DEFAULT_AAA_PRESET,
    LiningStyle,
    get_lining,
)

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


# ---------------------------------------------------------------------------
# AAA post-process helpers — small, deterministic, Rust-port candidates.
# ---------------------------------------------------------------------------


def _paper_grain(w: int, h: int, intensity: float, seed_salt: int) -> np.ndarray:
    """Return an ``(H, W)`` float32 array of Perlin-ish paper grain.

    Two octaves — 1-pixel white noise (65%) + a 4× downsampled octave
    upsampled with nearest neighbour (35%). Amplitude is scaled so that
    ``intensity=0.015`` yields ±3-4 luma variance in [0, 1] space.
    """
    if intensity <= 0.0:
        return np.zeros((h, w), dtype=np.float32)
    rng = np.random.default_rng(seed_salt ^ (w * 1009 + h))
    n1 = rng.uniform(-1.0, 1.0, size=(h, w)).astype(np.float32)
    hs = max(1, h // 4)
    ws = max(1, w // 4)
    low = rng.uniform(-1.0, 1.0, size=(hs, ws)).astype(np.float32)
    yi = np.minimum((np.arange(h) * hs) // max(h, 1), hs - 1)
    xi = np.minimum((np.arange(w) * ws) // max(w, 1), ws - 1)
    n2 = low[yi[:, None], xi[None, :]]
    return (0.65 * n1 + 0.35 * n2) * intensity


def _row_wobble(w: int, amp_px: float, seed_salt: int) -> np.ndarray:
    """Deterministic 5-tap-smoothed row wobble curve of length *w*."""
    if amp_px <= 0.0:
        return np.zeros(w, dtype=np.float32)
    rng = np.random.default_rng(seed_salt ^ (w * 7919))
    wob = rng.uniform(-amp_px, amp_px, size=w).astype(np.float32)
    k = np.ones(5, dtype=np.float32) / 5.0
    return np.convolve(wob, k, mode="same")


def _fp_ruled_paper(
    w: int,
    h: int,
    paper: np.ndarray,
    ink: np.ndarray,
    quality: AAAShaderQualityPreset | None = None,
) -> np.ndarray:
    _, Y = _make_grid(w, h)
    X, _ = _make_grid(w, h)
    red = np.array([1.0, 0.44, 0.71], dtype=np.float32)
    q = quality
    if q is None or (q.grain_intensity == 0.0 and q.line_aa_px == 0.0
                     and q.jitter_px == 0.0 and q.warm_tint == 0.0):
        # LOW tier — original pixel-perfect path (unchanged).
        line = (Y % 24.0 >= 23.0).astype(np.float32)
        margin = ((X >= 32.0) & (X < 33.0)).astype(np.float32)
        out = paper[None, None, :] * (1.0 - line[..., None]) + ink[None, None, :] * line[..., None]
        out = out * (1.0 - margin[..., None]) + red[None, None, :] * margin[..., None]
        return out
    # AAA-quality path — build the canvas in float, layer AA + grain +
    # warm tint + optional row jitter.
    canvas = np.tile(paper[None, None, :], (h, w, 1)).astype(np.float32)
    # Warm sun-lit gradient.
    if q.warm_tint > 0.0:
        grad = 1.0 - ((X / max(w - 1, 1) + Y / max(h - 1, 1)) * 0.5)
        warm_shift = grad[..., None] * q.warm_tint * np.array(
            [0.05, 0.025, -0.025], dtype=np.float32
        )
        canvas = canvas + warm_shift
    # Perlin-ish paper grain.
    if q.grain_intensity > 0.0:
        canvas = canvas + _paper_grain(w, h, q.grain_intensity, seed_salt=0xA11A)[..., None]
    # Ruled lines with optional row jitter.
    wobble = _row_wobble(w, q.jitter_px, seed_salt=0xB22B)
    aa = max(q.line_aa_px, 0.5)
    for y0 in range(23, h, 24):
        d = np.abs(Y - (float(y0) + wobble.reshape(1, -1)))
        alpha = np.clip(1.0 - d / aa, 0.0, 1.0)
        canvas = canvas * (1.0 - alpha[..., None]) + ink[None, None, :] * alpha[..., None]
    # Margin rule (crisp).
    dm = np.abs(X - 32.0)
    am = np.clip(1.0 - dm / max(aa, 0.5), 0.0, 1.0)
    canvas = canvas * (1.0 - am[..., None]) + red[None, None, :] * am[..., None]
    return canvas


def _fp_dot_grid(
    w: int,
    h: int,
    paper: np.ndarray,
    ink: np.ndarray,
    quality: AAAShaderQualityPreset | None = None,
) -> np.ndarray:
    X, Y = _make_grid(w, h)
    s = 24.0
    q = quality
    if q is None or (q.grain_intensity == 0.0 and q.line_aa_px == 0.0
                     and q.dot_alpha_variance == 0.0 and q.warm_tint == 0.0):
        # LOW tier — legacy 1.5-radius crisp dot.
        r = 1.5
        cx = (X % s) - s * 0.5
        cy = (Y % s) - s * 0.5
        d = np.sqrt(cx * cx + cy * cy)
        dot = np.clip(1.0 - (d - r) / 0.5, 0.0, 1.0) * 0.6
        return paper[None, None, :] * (1.0 - dot[..., None]) + ink[None, None, :] * dot[..., None]
    # AAA — bigger dots (2-3px), soft AA edge, per-dot alpha variance, grain.
    r = 2.4
    aa = max(q.line_aa_px, 0.6)
    canvas = np.tile(paper[None, None, :], (h, w, 1)).astype(np.float32)
    if q.warm_tint > 0.0:
        grad = 1.0 - ((X / max(w - 1, 1) + Y / max(h - 1, 1)) * 0.5)
        canvas = canvas + grad[..., None] * q.warm_tint * np.array(
            [0.05, 0.025, -0.025], dtype=np.float32
        )
    if q.grain_intensity > 0.0:
        canvas = canvas + _paper_grain(w, h, q.grain_intensity, seed_salt=0xC33C)[..., None]
    cx = (X % s) - s * 0.5
    cy = (Y % s) - s * 0.5
    d = np.sqrt(cx * cx + cy * cy)
    dot_mask = np.clip(1.0 - (d - r) / aa, 0.0, 1.0)
    # Per-dot alpha variance — hash the dot-cell index deterministically.
    if q.dot_alpha_variance > 0.0:
        col_idx = np.floor(X / s).astype(np.int32)
        row_idx = np.floor(Y / s).astype(np.int32)
        # Deterministic hash: sin-based, matches WGSL fract(sin()) idiom.
        h_ = np.mod(np.sin(col_idx * 12.9898 + row_idx * 78.233) * 43758.5453, 1.0)
        variance = (h_ * 2.0 - 1.0) * q.dot_alpha_variance
        dot_mask = np.clip(dot_mask * (1.0 + variance), 0.0, 1.0)
    dot = dot_mask * 0.7
    canvas = canvas * (1.0 - dot[..., None]) + ink[None, None, :] * dot[..., None]
    return canvas


def _fp_graph_grid(
    w: int,
    h: int,
    paper: np.ndarray,
    ink: np.ndarray,
    quality: AAAShaderQualityPreset | None = None,
) -> np.ndarray:
    X, Y = _make_grid(w, h)
    s = 10.0
    q = quality
    if q is None or (q.grain_intensity == 0.0 and q.line_aa_px == 0.0
                     and q.ink_bleed == 0.0 and q.warm_tint == 0.0):
        gx = (X % s < 1.0).astype(np.float32)
        gy = (Y % s < 1.0).astype(np.float32)
        line = np.clip(gx + gy, 0.0, 1.0) * 0.5
        return paper[None, None, :] * (1.0 - line[..., None]) + ink[None, None, :] * line[..., None]
    canvas = np.tile(paper[None, None, :], (h, w, 1)).astype(np.float32)
    if q.warm_tint > 0.0:
        grad = 1.0 - ((X / max(w - 1, 1) + Y / max(h - 1, 1)) * 0.5)
        canvas = canvas + grad[..., None] * q.warm_tint * np.array(
            [0.05, 0.025, -0.025], dtype=np.float32
        )
    if q.grain_intensity > 0.0:
        canvas = canvas + _paper_grain(w, h, q.grain_intensity, seed_salt=0xD44D)[..., None]
    aa = max(q.line_aa_px, 0.6)
    # Dual-line AA — signed distance to nearest grid line.
    dx = np.minimum(X % s, s - (X % s))
    dy = np.minimum(Y % s, s - (Y % s))
    lx = np.clip(1.0 - dx / aa, 0.0, 1.0)
    ly = np.clip(1.0 - dy / aa, 0.0, 1.0)
    line = np.clip(lx + ly, 0.0, 1.0)
    # Slight blue-ink bleed — widen the effective line footprint.
    if q.ink_bleed > 0.0:
        bleed_x = np.clip(1.0 - dx / (aa * (1.0 + 3.0 * q.ink_bleed)), 0.0, 1.0)
        bleed_y = np.clip(1.0 - dy / (aa * (1.0 + 3.0 * q.ink_bleed)), 0.0, 1.0)
        bleed = np.clip(bleed_x + bleed_y, 0.0, 1.0) * (0.25 * q.ink_bleed)
        line = np.clip(line + bleed, 0.0, 1.0)
    line = line * 0.55
    canvas = canvas * (1.0 - line[..., None]) + ink[None, None, :] * line[..., None]
    return canvas


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


def _fp_blank_cream(
    w: int,
    h: int,
    paper: np.ndarray,
    ink: np.ndarray,
    quality: AAAShaderQualityPreset | None = None,
) -> np.ndarray:
    X, Y = _make_grid(w, h)
    # Match WGSL fract(sin(x*12.9898 + y*78.233) * 43758.5453)
    n = np.mod(np.sin(X * 12.9898 + Y * 78.233) * 43758.5453, 1.0)
    noise = (n - 0.5) * 0.02
    base = paper[None, None, :] + noise[..., None]
    q = quality
    if q is None or (q.grain_intensity == 0.0 and q.warm_tint == 0.0):
        return base
    # AAA — layer Perlin-ish grain + warm sun-lit tint on top of the
    # existing high-frequency noise. blank_cream has no line contrast so
    # we boost the grain 2× to make it visibly break flatness.
    if q.grain_intensity > 0.0:
        base = base + _paper_grain(
            w, h, q.grain_intensity * 2.0, seed_salt=0xE55E,
        )[..., None]
    if q.warm_tint > 0.0:
        grad = 1.0 - ((X / max(w - 1, 1) + Y / max(h - 1, 1)) * 0.5)
        base = base + grad[..., None] * q.warm_tint * np.array(
            [0.05, 0.025, -0.025], dtype=np.float32
        )
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


# Style IDs whose fallbacks accept an ``AAAShaderQualityPreset`` via the
# ``quality`` kwarg (BBB5 upgrade). Other IDs silently ignore the arg.
AAA_QUALITY_AWARE_STYLES: frozenset[str] = frozenset(
    {"ruled_paper", "dot_grid", "graph_grid", "blank_cream"}
)


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
    quality: AAAShaderQualityPreset | None = None,
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
    quality:
        Optional :class:`~pharos_engine.ui.theme.page_linings.library.AAAShaderQualityPreset`
        controlling how much AAA-quality post-process the four "default"
        presets (``ruled_paper``, ``dot_grid``, ``graph_grid``,
        ``blank_cream``) apply. ``None`` (the default) preserves the
        pre-BBB5 flat look so existing golden textures stay stable.

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

    return _dispatch_fallback(style, w, h, paper_rgb, ink_rgb, quality=quality)


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
    quality = uniforms.pop("quality", None)
    for extra in uniforms:
        logger.debug("bake_lining_texture: ignoring unknown uniform %r", extra)
    return render_lining(
        style_id,
        size,
        paper_color=paper,
        line_color=line,
        force_fallback=force_fallback,
        quality=quality,
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
    quality: AAAShaderQualityPreset | None = None,
) -> np.ndarray:
    fn = _FALLBACKS.get(style.style_id)
    if fn is None:  # pragma: no cover - registry misalignment safeguard
        raise KeyError(
            f"render_lining: no numpy fallback registered for {style.style_id!r}"
        )
    paper = _rgb_to_float(paper_rgb)
    ink = _rgb_to_float(ink_rgb)
    # Only the AAA-aware fallbacks accept the quality kwarg; other styles
    # pass through untouched so their signature stays clean.
    if quality is not None and style.style_id in AAA_QUALITY_AWARE_STYLES:
        rgb = fn(w, h, paper, ink, quality=quality)
    else:
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
        from pharos_engine.gpu.context import GPUContext  # type: ignore[import-not-found]
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
