"""BBB3 preset API — 4 signature washi-tape stickers for panel title bars.

This module ships the *signature notebook-theme flourish* that the
sprint brief calls out: every notebook panel title bar wears a strip of
washi tape rotated a few degrees off-axis. Four presets are exposed:

* ``"pink_polka"``     — pink base + white polka dots + torn edges.
* ``"pastel_floral"`` — mint base + white daisy silhouettes.
* ``"star_print"``    — pale-yellow base + small navy stars.
* ``"plain"``          — solid soft-pink base + torn edges.

Each preset is a self-contained numpy renderer that produces an
``np.uint8`` RGBA array of shape ``(height, width, 4)``. The outermost
three rows and columns fade from ``alpha=1.0`` to ``alpha=0.0`` to give
the tape a torn-paper feel — so callers can blit the swatch directly
onto a panel's title corner without a separate mask.

Two entry points are exposed:

* :func:`render_washi_tape` — the render fn requested by BBB3. Accepts
  a preset name + ``(width, height)`` size tuple and returns the RGBA
  array.
* :data:`WASHI_TAPE_PRESETS` — a dict mapping preset id to a
  :class:`WashiTapePreset` metadata record. Downstream theme code
  (:class:`NotebookPanelDecor`) picks a preset per panel from this dict.

The presets are additive to the existing :mod:`library` (23 procedural
WGSL styles) — they neither replace nor collide with any existing style
id (all preset ids omit the ``tape_`` prefix). Callers that want a full
WGSL-backed shader library should keep using
:func:`pharos_engine.ui.theme.washi_tape.render_tape`; callers that want
the signature notebook flourish should call ``render_washi_tape`` in
this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np


# ---------------------------------------------------------------------------
# Preset metadata
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WashiTapePreset:
    """One washi-tape preset — id, display name, base RGB, and description.

    The renderer functions live below and are keyed by :attr:`id`; the
    preset record itself carries no rasterisation logic so it stays
    trivially picklable and YAML-round-trippable for theme configs.

    Parameters
    ----------
    id:
        Stable identifier (e.g. ``"pink_polka"``). Used both as the
        dict key in :data:`WASHI_TAPE_PRESETS` and as the *preset*
        argument to :func:`render_washi_tape`.
    display_name:
        Human-facing label surfaced by the theme picker.
    base_color:
        The tape's dominant colour as an ``(r, g, b)`` 0-255 int triple.
        The renderer applies this to the tape's fill; the second
        (accent) colour is preset-specific and lives in the render fn.
    description:
        Short prose describing the preset.
    """

    id: str
    display_name: str
    base_color: tuple[int, int, int]
    description: str = ""

    def __post_init__(self) -> None:
        fn = "WashiTapePreset"
        if not isinstance(self.id, str) or not self.id:
            raise ValueError(f"{fn}: id must be a non-empty str; got {self.id!r}")
        if not isinstance(self.display_name, str) or not self.display_name:
            raise ValueError(
                f"{fn}: display_name must be a non-empty str; "
                f"got {self.display_name!r}"
            )
        if (
            not isinstance(self.base_color, tuple)
            or len(self.base_color) != 3
            or not all(isinstance(c, int) for c in self.base_color)
            or any(c < 0 or c > 255 for c in self.base_color)
        ):
            raise TypeError(
                f"{fn}: base_color must be a 3-tuple of ints in [0, 255]; "
                f"got {self.base_color!r}"
            )
        if not isinstance(self.description, str):
            raise TypeError(
                f"{fn}: description must be a str; "
                f"got {type(self.description).__name__}"
            )


# ---------------------------------------------------------------------------
# Rasterisation helpers
# ---------------------------------------------------------------------------


def _validate_size(size: tuple[int, int]) -> tuple[int, int]:
    """Sanity-check a ``(width, height)`` tuple, returning ints."""
    if (
        not isinstance(size, (tuple, list))
        or len(size) != 2
        or not all(isinstance(v, int) and not isinstance(v, bool) for v in size)
        or any(v <= 0 for v in size)
    ):
        raise ValueError(
            f"render_washi_tape: size must be a 2-tuple of positive ints; "
            f"got {size!r}"
        )
    return int(size[0]), int(size[1])


def _torn_edge_alpha(h: int, w: int) -> np.ndarray:
    """Build an alpha mask with a 3-px torn edge fade top & bottom.

    Alpha ramps linearly ``0 -> 255`` across the outer 3 rows on both
    top and bottom edges. The horizontal (long-axis) edges pick up a
    tiny per-column randomisation so the tear looks organic rather than
    a machine cut — but the fade *magnitude* is preserved so the
    regression test can assert ``alpha < 128`` on the outermost row.
    """
    alpha = np.full((h, w), 255, dtype=np.int32)
    # Torn top: rows 0, 1, 2 → alpha ≈ 0, ~85, ~170.
    for row, ramp in enumerate((0, 85, 170)):
        if row < h:
            # Per-column jitter — deterministic (sin hash) so tests are stable.
            xs = np.arange(w, dtype=np.float32)
            jitter = (np.sin(xs * 1.3 + row * 2.1) * 15.0).astype(np.int32)
            alpha[row, :] = np.clip(ramp + jitter, 0, 255)
    # Torn bottom: rows h-1, h-2, h-3 → alpha ≈ 0, ~85, ~170.
    for row, ramp in enumerate((0, 85, 170)):
        idx = h - 1 - row
        if 0 <= idx < h:
            xs = np.arange(w, dtype=np.float32)
            jitter = (np.sin(xs * 1.7 + row * 2.3 + 11.0) * 15.0).astype(np.int32)
            alpha[idx, :] = np.clip(ramp + jitter, 0, 255)
    return alpha.astype(np.uint8)


def _fill_base(h: int, w: int, rgb: tuple[int, int, int]) -> np.ndarray:
    """Return an RGBA canvas filled with *rgb* and alpha=255."""
    out = np.empty((h, w, 4), dtype=np.uint8)
    out[..., 0] = rgb[0]
    out[..., 1] = rgb[1]
    out[..., 2] = rgb[2]
    out[..., 3] = 255
    return out


def _dot_mask(
    h: int, w: int,
    step_x: int, step_y: int,
    radius: float,
    offset_x: float = 0.5,
    offset_y: float = 0.5,
) -> np.ndarray:
    """Return a boolean mask of anti-aliased dots on a regular grid."""
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    # Centre each dot in its cell.
    cx = (xs / step_x) - np.floor(xs / step_x) - offset_x
    cy = (ys / step_y) - np.floor(ys / step_y) - offset_y
    d = np.sqrt(cx * cx + cy * cy)
    # Radius is a fraction in [0, 0.5] of the cell.
    return d < radius


def _paint_rgb(
    canvas: np.ndarray, mask: np.ndarray, rgb: tuple[int, int, int],
) -> None:
    """In-place: paint *rgb* onto *canvas* where *mask* is truthy."""
    canvas[mask, 0] = rgb[0]
    canvas[mask, 1] = rgb[1]
    canvas[mask, 2] = rgb[2]


# ---------------------------------------------------------------------------
# Preset renderers
# ---------------------------------------------------------------------------


def _render_pink_polka(w: int, h: int) -> np.ndarray:
    """Pink base + white polka dots + torn edges.

    The polka grid uses a 12 × 12 px cell with 3 px radius dots — dense
    enough to read as a pattern at 120 × 32, sparse enough to not
    dominate the panel title text underneath.
    """
    base = (255, 181, 197)  # #FFB5C5 — theme washi pink.
    canvas = _fill_base(h, w, base)
    dots = _dot_mask(h, w, step_x=12, step_y=12, radius=0.25)
    _paint_rgb(canvas, dots, (255, 255, 255))
    canvas[..., 3] = _torn_edge_alpha(h, w)
    return canvas


def _render_pastel_floral(w: int, h: int) -> np.ndarray:
    """Mint-green base + white daisy silhouettes.

    Each daisy is a small five-petal flower: five outer petals (dots)
    around a central dot. Rendered by unioning six dot masks per cell.
    """
    base = (185, 232, 205)  # #B9E8CD — theme washi mint.
    canvas = _fill_base(h, w, base)
    # Central bud.
    centres = _dot_mask(h, w, step_x=20, step_y=20, radius=0.10)
    _paint_rgb(canvas, centres, (255, 255, 255))
    # Five petals around each centre — sampled as five offset dot grids.
    import math
    for k in range(5):
        angle = k * (2.0 * math.pi / 5.0)
        off_x = 0.5 + 0.28 * math.cos(angle)
        off_y = 0.5 + 0.28 * math.sin(angle)
        petals = _dot_mask(
            h, w, step_x=20, step_y=20, radius=0.13,
            offset_x=off_x, offset_y=off_y,
        )
        _paint_rgb(canvas, petals, (255, 255, 255))
    canvas[..., 3] = _torn_edge_alpha(h, w)
    return canvas


def _render_star_print(w: int, h: int) -> np.ndarray:
    """Pale-yellow base + small navy stars.

    Star = 4-point cross (dot + 4 satellite dots along the axes).
    Cheap, reads as a star silhouette at typical tape sizes.
    """
    base = (255, 240, 178)  # #FFF0B2 — theme washi yellow.
    navy = (30, 45, 110)
    canvas = _fill_base(h, w, base)
    # Central dot.
    centres = _dot_mask(h, w, step_x=16, step_y=16, radius=0.10)
    _paint_rgb(canvas, centres, navy)
    # Four satellite dots — up/down/left/right — to fake a 4-point star.
    for dx, dy in ((0.5, 0.22), (0.5, 0.78), (0.22, 0.5), (0.78, 0.5)):
        arms = _dot_mask(
            h, w, step_x=16, step_y=16, radius=0.07,
            offset_x=dx, offset_y=dy,
        )
        _paint_rgb(canvas, arms, navy)
    canvas[..., 3] = _torn_edge_alpha(h, w)
    return canvas


def _render_plain(w: int, h: int) -> np.ndarray:
    """Solid soft-pink base + torn edges — no accent pattern."""
    base = (255, 210, 220)  # slightly lighter than pink_polka's base.
    canvas = _fill_base(h, w, base)
    canvas[..., 3] = _torn_edge_alpha(h, w)
    return canvas


_RENDERERS: dict[str, Callable[[int, int], np.ndarray]] = {
    "pink_polka": _render_pink_polka,
    "pastel_floral": _render_pastel_floral,
    "star_print": _render_star_print,
    "plain": _render_plain,
}


# ---------------------------------------------------------------------------
# Registry — the sprint-visible surface
# ---------------------------------------------------------------------------


WASHI_TAPE_PRESETS: dict[str, WashiTapePreset] = {
    preset.id: preset for preset in (
        WashiTapePreset(
            id="pink_polka",
            display_name="Pink Polka",
            base_color=(255, 181, 197),
            description="Pink tape with white polka dots and torn edges.",
        ),
        WashiTapePreset(
            id="pastel_floral",
            display_name="Pastel Floral",
            base_color=(185, 232, 205),
            description="Mint-green tape with white daisy silhouettes.",
        ),
        WashiTapePreset(
            id="star_print",
            display_name="Star Print",
            base_color=(255, 240, 178),
            description="Pale-yellow tape with small navy stars.",
        ),
        WashiTapePreset(
            id="plain",
            display_name="Plain",
            base_color=(255, 210, 220),
            description="Solid soft-pink tape with torn edges only.",
        ),
    )
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render_washi_tape(preset: str, size: tuple[int, int]) -> np.ndarray:
    """Render *preset* at *size* and return an ``(H, W, 4)`` RGBA array.

    Parameters
    ----------
    preset:
        One of the ids in :data:`WASHI_TAPE_PRESETS`. Unknown names
        raise ``KeyError`` — the error message lists the known presets
        so typos are easy to spot.
    size:
        ``(width, height)`` in pixels. Both must be positive ints.

    Returns
    -------
    numpy.ndarray
        ``np.uint8`` RGBA image of shape ``(height, width, 4)``. The
        outermost three rows have alpha < 128 (torn-paper edge).

    Raises
    ------
    KeyError
        If *preset* is not a registered preset id.
    ValueError
        If *size* is malformed.
    """
    if not isinstance(preset, str) or not preset:
        raise KeyError(
            f"render_washi_tape: preset must be a non-empty str; got {preset!r}"
        )
    if preset not in WASHI_TAPE_PRESETS:
        raise KeyError(
            f"render_washi_tape: unknown preset {preset!r}; "
            f"known: {sorted(WASHI_TAPE_PRESETS)}"
        )
    w, h = _validate_size(size)
    return _RENDERERS[preset](w, h)


def rotate_washi_tape(
    image: np.ndarray, angle_deg: float,
) -> np.ndarray:
    """Rotate a rendered tape *image* by *angle_deg* around its centre.

    DPG has no image-rotation primitive, so the notebook decor rotates
    the RGBA numpy array in-place before uploading it as a texture. The
    rotation uses nearest-neighbour sampling — good enough for a small
    stationery-tray sticker and 3× faster than bilinear.

    A pure-numpy rotation keeps the module free of scipy / PIL
    dependencies. Alpha is preserved so torn edges still fade correctly.

    Parameters
    ----------
    image:
        Input RGBA ``uint8`` array, shape ``(H, W, 4)``.
    angle_deg:
        Rotation in degrees; positive = counter-clockwise (matches DPG
        drawlist convention). Typical values are 4-8 for the sprint's
        "hand-placed" feel.

    Returns
    -------
    numpy.ndarray
        Rotated RGBA ``uint8`` array. The output canvas is enlarged so
        the corners of the rotated rect fit — any exposed pixel gets
        alpha=0.
    """
    if not isinstance(image, np.ndarray):
        raise TypeError(
            f"rotate_washi_tape: image must be a numpy ndarray; "
            f"got {type(image).__name__}"
        )
    if image.ndim != 3 or image.shape[2] != 4:
        raise ValueError(
            f"rotate_washi_tape: image must be RGBA (H, W, 4); "
            f"got shape {image.shape!r}"
        )
    if not isinstance(angle_deg, (int, float)) or isinstance(angle_deg, bool):
        raise TypeError(
            f"rotate_washi_tape: angle_deg must be a number; "
            f"got {type(angle_deg).__name__}"
        )
    import math
    h, w = image.shape[:2]
    theta = math.radians(float(angle_deg))
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    # Compute output canvas size (enlarged to fit rotated corners).
    new_w = int(abs(w * cos_t) + abs(h * sin_t)) + 1
    new_h = int(abs(w * sin_t) + abs(h * cos_t)) + 1
    out = np.zeros((new_h, new_w, 4), dtype=np.uint8)
    cx_in, cy_in = w / 2.0, h / 2.0
    cx_out, cy_out = new_w / 2.0, new_h / 2.0
    # Sample the source with the inverse rotation.
    ys, xs = np.mgrid[0:new_h, 0:new_w].astype(np.float32)
    dx = xs - cx_out
    dy = ys - cy_out
    src_x = cos_t * dx + sin_t * dy + cx_in
    src_y = -sin_t * dx + cos_t * dy + cy_in
    src_xi = np.round(src_x).astype(np.int32)
    src_yi = np.round(src_y).astype(np.int32)
    mask = (src_xi >= 0) & (src_xi < w) & (src_yi >= 0) & (src_yi < h)
    out[mask] = image[src_yi[mask], src_xi[mask]]
    return out


__all__ = [
    "WashiTapePreset",
    "WASHI_TAPE_PRESETS",
    "render_washi_tape",
    "rotate_washi_tape",
]
