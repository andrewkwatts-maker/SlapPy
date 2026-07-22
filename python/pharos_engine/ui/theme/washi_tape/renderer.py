"""Rasterise washi-tape swatches from :class:`WashiTapeStyle` sources.

The renderer has two backends:

* A **wgpu backend** that compiles and runs the shader's WGSL source
  against a small offscreen render target. Enabled when ``wgpu`` is
  importable; otherwise skipped without complaint.
* A **numpy fallback** that reproduces each style using pure numpy
  primitives. It is always available and drives every headless test.

Public API
----------

* :func:`render_tape` — bake a swatch for a style id + explicit colour
  pair. Returns an ``np.uint8`` RGBA ``(H, W, 4)`` array.
* :func:`bake_tape_texture` — same, but accepts kwargs
  (``theme_color_1``, ``theme_color_2``, ``time``) so callers that
  don't want positional colour tuples can stay declarative.

Both entry points funnel through :func:`_numpy_fallback` per style so
the two backends agree on visible output up to floating-point rounding.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import numpy as np

from .library import WashiTapeStyle, get_tape


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Soft wgpu import
# ---------------------------------------------------------------------------


try:  # pragma: no cover - only exercised with wgpu installed
    import wgpu  # type: ignore[import-not-found]

    _HAS_WGPU = True
except Exception:  # pragma: no cover - headless default
    wgpu = None  # type: ignore[assignment]
    _HAS_WGPU = False


def has_wgpu() -> bool:
    """Return ``True`` iff wgpu imported successfully."""
    return _HAS_WGPU


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------


ColorRGB = tuple[int, int, int]


def _normalise_color(
    color: ColorRGB | tuple[float, float, float] | None,
    default: ColorRGB,
) -> np.ndarray:
    """Normalise an ``(r, g, b)`` triple to ``float32`` in ``[0, 1]``.

    Accepts ints in ``[0, 255]`` or floats in ``[0, 1]``. ``None`` maps
    to *default*. Raises ``TypeError`` for anything else.
    """
    if color is None:
        color = default
    if (
        not isinstance(color, (tuple, list))
        or len(color) != 3
        or not all(isinstance(c, (int, float)) for c in color)
    ):
        raise TypeError(
            f"_normalise_color: colour must be a 3-tuple of numbers; "
            f"got {color!r}"
        )
    arr = np.asarray(color, dtype=np.float32)
    # If any channel exceeds 1.0 treat the whole tuple as 0-255.
    if float(arr.max()) > 1.0:
        arr = arr / 255.0
    return np.clip(arr, 0.0, 1.0)


def _validate_size(size: tuple[int, int]) -> tuple[int, int]:
    if (
        not isinstance(size, (tuple, list))
        or len(size) != 2
        or not all(isinstance(v, int) and v > 0 for v in size)
    ):
        raise ValueError(
            f"render_tape: size must be a 2-tuple of positive ints; got {size!r}"
        )
    return int(size[0]), int(size[1])


# ---------------------------------------------------------------------------
# UV grid
# ---------------------------------------------------------------------------


def _uv_grid(w: int, h: int) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(u, v)`` arrays of shape ``(h, w)`` in ``[0, 1]``.

    Matches the WGSL convention ``uv = frag_pos.xy / u_size`` with
    ``u`` running along the x axis and ``v`` along the y axis.
    """
    u = (np.arange(w, dtype=np.float32) + 0.5) / float(w)
    v = (np.arange(h, dtype=np.float32) + 0.5) / float(h)
    uu, vv = np.meshgrid(u, v)
    return uu, vv


def _edge_mask(vv: np.ndarray, top: float = 0.05, bot_hi: float = 0.95) -> np.ndarray:
    """Match the shared torn-edge alpha ramp from the shader preamble."""
    top_ramp = np.clip(vv / max(top, 1e-6), 0.0, 1.0)
    bot_ramp = np.clip((1.0 - vv) / max(1.0 - bot_hi, 1e-6), 0.0, 1.0)
    return top_ramp * bot_ramp


def _hash01(a: np.ndarray) -> np.ndarray:
    """Deterministic hash in ``[0, 1)`` matching the shader's ``fract(sin(x))`` idiom."""
    return np.abs(np.sin(a) * 43758.0) % 1.0


# ---------------------------------------------------------------------------
# Style fallbacks
# ---------------------------------------------------------------------------


def _fb_pink_solid(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    noise = _hash01(uu * 43.0) * 0.05
    rgb = np.clip(c1[None, None, :] - noise[..., None], 0.0, 1.0)
    alpha = 0.85 * _edge_mask(vv, 0.06, 0.94)
    return rgb, alpha


def _fb_pink_dots(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    du = (uu * 8.0) % 1.0
    dv = (vv * 3.0) % 1.0
    d = np.sqrt((du - 0.5) ** 2 + (dv - 0.5) ** 2)
    mask = 1.0 - np.clip((d - 0.15) / 0.10, 0.0, 1.0)
    rgb = c1[None, None, :] * (1.0 - mask[..., None]) + c2[None, None, :] * mask[..., None]
    alpha = 0.85 * _edge_mask(vv)
    return rgb, alpha


def _fb_blue_stripes(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    s = ((uu * 6.0) % 1.0 >= 0.5).astype(np.float32) * 0.7
    rgb = c1[None, None, :] * (1.0 - s[..., None]) + c2[None, None, :] * s[..., None]
    alpha = 0.9 * _edge_mask(vv)
    return rgb, alpha


def _fb_yellow_gingham(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    a = ((uu * 8.0) % 1.0 >= 0.5).astype(np.float32)
    b = ((vv * 3.0) % 1.0 >= 0.5).astype(np.float32)
    g = (a + b) * 0.5
    rgb = c1[None, None, :] * (1.0 - g[..., None]) + c2[None, None, :] * g[..., None]
    alpha = 0.9 * _edge_mask(vv)
    return rgb, alpha


def _fb_mint_polka(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    big_u = (uu * 4.0) % 1.0
    big_v = (vv * 1.5) % 1.0
    sm_u = (uu * 8.0 + 0.25) % 1.0
    sm_v = (vv * 3.0 + 0.5) % 1.0
    d1 = np.sqrt((big_u - 0.5) ** 2 + (big_v - 0.5) ** 2)
    d2 = np.sqrt((sm_u - 0.5) ** 2 + (sm_v - 0.5) ** 2)
    m1 = 1.0 - np.clip((d1 - 0.18) / 0.12, 0.0, 1.0)
    m2 = (1.0 - np.clip((d2 - 0.10) / 0.08, 0.0, 1.0)) * 0.6
    m = np.maximum(m1, m2)
    rgb = c1[None, None, :] * (1.0 - m[..., None]) + c2[None, None, :] * m[..., None]
    alpha = 0.85 * _edge_mask(vv)
    return rgb, alpha


def _fb_lavender_floral(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    cx = (uu * 5.0) % 1.0 - 0.5
    cy = (vv * 2.0) % 1.0 - 0.5
    r = np.sqrt(cx * cx + cy * cy)
    ang = np.arctan2(cy, cx)
    petal = 0.28 + 0.14 * np.cos(ang * 5.0)
    m = 1.0 - np.clip((r - (petal - 0.03)) / 0.06, 0.0, 1.0)
    rgb = c1[None, None, :] * (1.0 - m[..., None]) + c2[None, None, :] * m[..., None]
    alpha = 0.85 * _edge_mask(vv)
    return rgb, alpha


def _fb_watercolor_wash(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    n = _hash01(uu * 12.7 + vv * 78.2)
    blot = 0.5 + 0.5 * np.sin(uu * 7.0 + n * 2.0)
    rgb = c1[None, None, :] * (1.0 - blot[..., None]) + c2[None, None, :] * blot[..., None]
    alpha = 0.78 * _edge_mask(vv, 0.08, 0.92)
    return rgb, alpha


def _fb_gold_foil(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    shimmer = 0.5 + 0.5 * np.sin(uu * 40.0 + vv * 8.0)
    hi = np.power(shimmer, 4.0) * 0.75
    rgb = c1[None, None, :] * (1.0 - hi[..., None]) + c2[None, None, :] * hi[..., None]
    alpha = 0.9 * _edge_mask(vv)
    return rgb, alpha


def _fb_ripped_edge(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    tear_top = 0.05 + 0.04 * np.sin(uu * 60.0) * _hash01(uu * 17.0)
    tear_bot = 0.95 - 0.04 * np.sin(uu * 55.0 + 1.0) * _hash01(uu * 23.0)
    m = ((vv >= tear_top) & (vv <= tear_bot)).astype(np.float32)
    rgb = c1[None, None, :] * 0.85 + c2[None, None, :] * 0.15
    rgb = np.broadcast_to(rgb, (h, w, 3)).copy()
    alpha = 0.9 * m
    return rgb, alpha


def _fb_lace_border(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    band = (vv >= 0.75).astype(np.float32) + (vv <= 0.25).astype(np.float32)
    scallop = 0.5 + 0.5 * np.cos(uu * 24.0)
    mask = band * (scallop >= 0.4).astype(np.float32)
    rgb = c1[None, None, :] * (1.0 - mask[..., None]) + c2[None, None, :] * mask[..., None]
    alpha = 0.85 * _edge_mask(vv)
    return rgb, alpha


def _fb_star_confetti(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    gx = (uu * 6.0) % 1.0 - 0.5
    gy = (vv * 2.0) % 1.0 - 0.5
    r = np.sqrt(gx * gx + gy * gy)
    ang = np.abs(np.arctan2(gy, gx))
    star = 0.24 + 0.08 * np.cos(ang * 5.0)
    m = 1.0 - np.clip((r - (star - 0.02)) / 0.04, 0.0, 1.0)
    rgb = c1[None, None, :] * (1.0 - m[..., None]) + c2[None, None, :] * m[..., None]
    alpha = 0.85 * _edge_mask(vv)
    return rgb, alpha


def _fb_kraft_paper(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    f = _hash01(uu * 91.0 + vv * 27.0)
    g = f * 0.15
    rgb = c1[None, None, :] * (0.85 + g[..., None])
    rgb = np.clip(rgb, 0.0, 1.0)
    alpha = 0.92 * _edge_mask(vv)
    return rgb, alpha


def _fb_rainbow_gradient(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    h_ = uu
    r = 0.5 + 0.5 * np.cos(6.28 * (h_ + 0.0))
    g = 0.5 + 0.5 * np.cos(6.28 * (h_ + 0.33))
    b = 0.5 + 0.5 * np.cos(6.28 * (h_ + 0.67))
    rainbow = np.stack([r, g, b], axis=-1)
    rgb = c1[None, None, :] * 0.3 + rainbow * 0.7
    alpha = 0.85 * _edge_mask(vv)
    return rgb, alpha


def _fb_sparkle_animated(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    cell_u = np.floor(uu * 16.0)
    cell_v = np.floor(vv * 4.0)
    seed = _hash01(cell_u * 12.0 + cell_v * 78.0)
    tw = 0.5 + 0.5 * np.sin(t * 4.0 + seed * 6.28)
    sp = (seed >= 0.85).astype(np.float32) * tw
    rgb = c1[None, None, :] * (1.0 - sp[..., None]) + c2[None, None, :] * sp[..., None]
    alpha = 0.9 * _edge_mask(vv)
    return rgb, alpha


def _fb_music_notes(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    staff_val = 1.0 - np.abs(((vv * 5.0) % 1.0) - 0.5) * 2.0
    staff = (staff_val >= 0.98).astype(np.float32) * 0.4
    gx = (uu * 6.0) % 1.0 - 0.5
    gy = (vv * 1.0) - 0.5
    dnorm = np.sqrt(gx * gx + (gy * 1.6) ** 2)
    head = 1.0 - np.clip((dnorm - 0.10) / 0.04, 0.0, 1.0)
    m = np.maximum(staff, head)
    rgb = c1[None, None, :] * (1.0 - m[..., None]) + c2[None, None, :] * m[..., None]
    alpha = 0.85 * _edge_mask(vv)
    return rgb, alpha


# ---------------------------------------------------------------------------
# Animated V7 fallbacks — each mirrors the corresponding WGSL body and
# advances by ``t`` so ``time_offset`` sweeps produce distinct frames.
# ---------------------------------------------------------------------------


def _fb_heart_pulse(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    s = 1.0 + 0.1 * np.sin(t * 2.0 * np.pi * 2.0)
    gx = ((uu * 5.0) % 1.0 - 0.5) / s
    gy = -((vv * 2.0) % 1.0 - 0.5) / s
    a = gx * gx + gy * gy - 0.09
    heart = a * a * a - gx * gx * gy * gy * gy
    m = 1.0 - np.clip((heart + 0.002) / 0.006, 0.0, 1.0)
    rgb = c1[None, None, :] * (1.0 - m[..., None]) + c2[None, None, :] * m[..., None]
    alpha = 0.9 * _edge_mask(vv)
    return rgb, alpha


def _fb_sparkle_shimmer(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    shift_u = t * 0.15
    shift_v = t * 0.05
    cell_u = np.floor((uu + shift_u) * 14.0)
    cell_v = np.floor((vv + shift_v) * 4.0)
    seed = _hash01(cell_u * 12.9 + cell_v * 78.2)
    phase = (t * 3.0 + seed) % 1.0
    envelope = np.clip((phase - 0.3) / 0.7, 0.0, 1.0)
    envelope = envelope * envelope * (3.0 - 2.0 * envelope)
    sp = envelope * (seed >= 0.7).astype(np.float32)
    rgb = c1[None, None, :] * (1.0 - sp[..., None]) + c2[None, None, :] * sp[..., None]
    alpha = 0.9 * _edge_mask(vv)
    return rgb, alpha


def _fb_rainbow_flow(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    h_ = uu + t * (60.0 / 360.0)
    r = 0.5 + 0.5 * np.cos(6.28 * (h_ + 0.0))
    g = 0.5 + 0.5 * np.cos(6.28 * (h_ + 0.33))
    b = 0.5 + 0.5 * np.cos(6.28 * (h_ + 0.67))
    rainbow = np.stack([r, g, b], axis=-1)
    rgb = c1[None, None, :] * 0.3 + rainbow * 0.7
    alpha = 0.85 * _edge_mask(vv)
    return rgb, alpha


def _fb_marching_dots(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    shift = t * 20.0 / float(w)
    du = ((uu + shift) * 8.0) % 1.0
    dv = (vv * 3.0) % 1.0
    d = np.sqrt((du - 0.5) ** 2 + (dv - 0.5) ** 2)
    m = 1.0 - np.clip((d - 0.15) / 0.10, 0.0, 1.0)
    rgb = c1[None, None, :] * (1.0 - m[..., None]) + c2[None, None, :] * m[..., None]
    alpha = 0.9 * _edge_mask(vv)
    return rgb, alpha


def _fb_wave_shift(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    wave = 0.05 * np.sin(uu * 12.0 + t * 2.0)
    shift = t * 15.0 / float(h)
    vy = (vv - shift + wave) % 1.0
    band = (vy >= 0.5).astype(np.float32)
    m = band * 0.55
    rgb = c1[None, None, :] * (1.0 - m[..., None]) + c2[None, None, :] * m[..., None]
    alpha = 0.9 * _edge_mask(vv)
    return rgb, alpha


def _fb_dashed_scroll(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    shift = t * 30.0 / float(w)
    dash = (((uu + shift) * 10.0) % 1.0 >= 0.5).astype(np.float32)
    band = ((vv >= 0.35) & (vv <= 0.65)).astype(np.float32)
    m = dash * band
    rgb = c1[None, None, :] * (1.0 - m[..., None]) + c2[None, None, :] * m[..., None]
    alpha = 0.9 * _edge_mask(vv)
    return rgb, alpha


def _fb_stars_twinkle(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    cell_u = np.floor(uu * 6.0)
    cell_v = np.floor(vv * 2.0)
    seed = _hash01(cell_u * 12.0 + cell_v * 78.0)
    phase = seed * 2.0 * np.pi
    tw = 0.5 + 0.5 * np.sin(t * 3.0 + phase)
    gx = (uu * 6.0) % 1.0 - 0.5
    gy = (vv * 2.0) % 1.0 - 0.5
    r = np.sqrt(gx * gx + gy * gy)
    ang = np.abs(np.arctan2(gy, gx))
    star = 0.24 + 0.08 * np.cos(ang * 5.0)
    m = (1.0 - np.clip((r - (star - 0.02)) / 0.04, 0.0, 1.0)) * tw
    rgb = c1[None, None, :] * (1.0 - m[..., None]) + c2[None, None, :] * m[..., None]
    alpha = 0.9 * _edge_mask(vv)
    return rgb, alpha


def _fb_music_notes_flow(w, h, c1, c2, t):
    uu, vv = _uv_grid(w, h)
    staff_val = 1.0 - np.abs(((vv * 5.0) % 1.0) - 0.5) * 2.0
    staff = (staff_val >= 0.98).astype(np.float32) * 0.4
    shift = t * 25.0 / float(w)
    gx = ((uu + shift) * 6.0) % 1.0 - 0.5
    gy = (vv * 1.0) - 0.5
    dnorm = np.sqrt(gx * gx + (gy * 1.6) ** 2)
    head = 1.0 - np.clip((dnorm - 0.10) / 0.04, 0.0, 1.0)
    m = np.maximum(staff, head)
    rgb = c1[None, None, :] * (1.0 - m[..., None]) + c2[None, None, :] * m[..., None]
    alpha = 0.85 * _edge_mask(vv)
    return rgb, alpha


_FALLBACKS: dict[str, Callable[..., tuple[np.ndarray, np.ndarray]]] = {
    "tape_pink_solid": _fb_pink_solid,
    "tape_pink_dots": _fb_pink_dots,
    "tape_blue_stripes": _fb_blue_stripes,
    "tape_yellow_gingham": _fb_yellow_gingham,
    "tape_mint_polka": _fb_mint_polka,
    "tape_lavender_floral": _fb_lavender_floral,
    "tape_watercolor_wash": _fb_watercolor_wash,
    "tape_gold_foil": _fb_gold_foil,
    "tape_ripped_edge": _fb_ripped_edge,
    "tape_lace_border": _fb_lace_border,
    "tape_star_confetti": _fb_star_confetti,
    "tape_kraft_paper": _fb_kraft_paper,
    "tape_rainbow_gradient": _fb_rainbow_gradient,
    "tape_sparkle_animated": _fb_sparkle_animated,
    "tape_music_notes": _fb_music_notes,
    # V7 animated variants
    "tape_heart_pulse": _fb_heart_pulse,
    "tape_sparkle_shimmer": _fb_sparkle_shimmer,
    "tape_rainbow_flow": _fb_rainbow_flow,
    "tape_marching_dots": _fb_marching_dots,
    "tape_wave_shift": _fb_wave_shift,
    "tape_dashed_scroll": _fb_dashed_scroll,
    "tape_stars_twinkle": _fb_stars_twinkle,
    "tape_music_notes_flow": _fb_music_notes_flow,
}


# ---------------------------------------------------------------------------
# Rasterisation entry points
# ---------------------------------------------------------------------------


def _default_c1(style_id: str) -> ColorRGB:
    palette = {
        "tape_pink_solid": (255, 181, 197),
        "tape_pink_dots": (255, 181, 197),
        "tape_blue_stripes": (181, 214, 255),
        "tape_yellow_gingham": (255, 240, 178),
        "tape_mint_polka": (185, 232, 205),
        "tape_lavender_floral": (214, 199, 255),
        "tape_watercolor_wash": (200, 220, 240),
        "tape_gold_foil": (200, 165, 90),
        "tape_ripped_edge": (240, 220, 200),
        "tape_lace_border": (250, 240, 230),
        "tape_star_confetti": (255, 200, 220),
        "tape_kraft_paper": (170, 130, 90),
        "tape_rainbow_gradient": (255, 255, 255),
        "tape_sparkle_animated": (220, 200, 250),
        "tape_music_notes": (255, 240, 240),
    }
    return palette.get(style_id, (220, 200, 220))


def _default_c2(style_id: str) -> ColorRGB:
    return (255, 255, 255)


def render_tape(
    style_id: str,
    size: tuple[int, int],
    theme_color_1: ColorRGB | None = None,
    theme_color_2: ColorRGB | None = None,
    time: float = 0.0,
    use_gpu: bool = False,
) -> np.ndarray:
    """Bake a tape swatch for *style_id* at *size*.

    Parameters
    ----------
    style_id:
        Name of a style registered in :data:`WASHI_TAPES`.
    size:
        ``(width, height)`` in pixels; both must be positive ints.
    theme_color_1, theme_color_2:
        Primary and secondary colours as either 0-255 ints or 0-1 floats
        (3-tuples). When ``None`` the style's built-in defaults are used.
    time:
        Wall-clock seconds forwarded to animated styles.
    use_gpu:
        Reserved for a future wgpu path. Currently ignored — the numpy
        fallback always drives output, but the flag is accepted so
        callers don't have to change signatures once GPU baking lands.

    Returns
    -------
    np.ndarray
        ``uint8`` RGBA image of shape ``(h, w, 4)``.

    Raises
    ------
    KeyError
        If *style_id* is unknown.
    ValueError
        If *size* is malformed.
    """
    style: WashiTapeStyle = get_tape(style_id)  # raises KeyError
    w, h = _validate_size(size)
    c1 = _normalise_color(theme_color_1, _default_c1(style_id))
    c2 = _normalise_color(theme_color_2, _default_c2(style_id))
    fallback = _FALLBACKS.get(style_id)
    if fallback is None:  # pragma: no cover - guarded by the KeyError above
        raise KeyError(
            f"render_tape: no numpy fallback registered for {style_id!r}"
        )
    rgb, alpha = fallback(w, h, c1, c2, float(time))
    rgb = np.clip(rgb, 0.0, 1.0)
    alpha = np.clip(alpha, 0.0, 1.0)
    out = np.empty((h, w, 4), dtype=np.uint8)
    out[..., 0] = (rgb[..., 0] * 255.0 + 0.5).astype(np.uint8)
    out[..., 1] = (rgb[..., 1] * 255.0 + 0.5).astype(np.uint8)
    out[..., 2] = (rgb[..., 2] * 255.0 + 0.5).astype(np.uint8)
    out[..., 3] = (alpha * 255.0 + 0.5).astype(np.uint8)
    _ = style  # keep style alive for future GPU path
    return out


def bake_tape_texture(
    style_id: str,
    size: tuple[int, int] | None = None,
    **uniforms: Any,
) -> np.ndarray:
    """Public tape bake entry point accepting keyword uniforms.

    Wraps :func:`render_tape` but accepts a kwargs bag so
    higher-level theme code can stay declarative::

        img = bake_tape_texture(
            "tape_pink_dots",
            size=(64, 24),
            theme_color_1=(255, 180, 200),
            theme_color_2=(255, 255, 255),
        )

    Recognised keys: ``theme_color_1``, ``theme_color_2``, ``time``,
    ``use_gpu``. Unknown keys raise ``TypeError`` (typo-safety > silent
    drop).
    """
    style: WashiTapeStyle = get_tape(style_id)
    if size is None:
        size = style.default_size
    unknown = set(uniforms) - {
        "theme_color_1", "theme_color_2", "time", "use_gpu",
    }
    if unknown:
        raise TypeError(
            f"bake_tape_texture: unknown uniform(s) {sorted(unknown)!r}; "
            "accepted: theme_color_1, theme_color_2, time, use_gpu"
        )
    return render_tape(
        style_id=style_id,
        size=size,
        theme_color_1=uniforms.get("theme_color_1"),
        theme_color_2=uniforms.get("theme_color_2"),
        time=float(uniforms.get("time", 0.0)),
        use_gpu=bool(uniforms.get("use_gpu", False)),
    )


__all__ = [
    "has_wgpu",
    "render_tape",
    "bake_tape_texture",
]
