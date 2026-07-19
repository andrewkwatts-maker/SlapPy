"""Notebook-panel edge-stroke *presets* — hand-drawn ink outlines.

This module is the **preset-level** API that themes and the panel
decorator consume. It sits on top of the low-level
:mod:`.library` / :mod:`.renderer` WGSL infrastructure but exposes a
much simpler contract:

* One dict :data:`EDGE_STROKE_PRESETS` keyed by preset name.
* One rendering entry point :func:`render_edge_stroke` that takes a
  preset name and a strip size and returns an ``(H, W, 4)`` ``uint8``
  RGBA array — *alpha 0 in the interior, stroke pixels on the border*.

The four presets ship with the default notebook theme:

* ``"pencil_scribble"`` — grey pencil hatching at ~2px thickness with a
  wavy ~0.5px per-column offset.
* ``"ink_thick"`` — solid ~2-3px black ink with slight blob variance
  (Perlin-noise-modulated width).
* ``"ink_thin"`` — ~1px charcoal-grey with occasional dried-pen gaps.
* ``"marker_bleed"`` — thick ~3-4px pastel line with an alpha-bleed
  halo of 2-4px.

All rendering is pure numpy so headless CI produces identical output.
Deterministic per-preset seeding keeps the noise repeatable across runs.

Panel-decorator convention
--------------------------
The decorator lays the returned strip on all four panel edges. It calls
:func:`render_edge_stroke` twice — once for the horizontal strips
(top / bottom) and once for the verticals (left / right, transposed).
The rasteriser therefore treats *the shorter dimension as the stroke's
thickness axis* and the longer dimension as the stroke's length axis.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from slappyengine._validation import (
    validate_non_empty_str,
    validate_positive_int,
)


# ---------------------------------------------------------------------------
# Preset dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EdgeStrokePreset:
    """One entry in :data:`EDGE_STROKE_PRESETS`.

    Presets are lightweight compared to
    :class:`~slappyengine.ui.theme.edge_strokes.EdgeStrokeStyle` — they
    carry only the parameters :func:`render_edge_stroke` needs plus the
    numpy rasteriser callable.
    """

    preset_id: str
    thickness_px: float
    description: str
    ink_rgba: tuple[int, int, int, int]
    render_fn: Callable[[int, int, tuple[int, int, int, int]], np.ndarray]
    tags: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Rasteriser helpers
# ---------------------------------------------------------------------------


def _seed_rng(preset_id: str, w: int, h: int) -> np.random.Generator:
    """Return a deterministic RNG keyed on preset + strip dims.

    Same preset + same size ⇒ same output on every run.
    """
    seed = (abs(hash(preset_id)) ^ (w * 2654435761) ^ (h * 40503)) & 0xFFFFFFFF
    return np.random.default_rng(seed)


def _orient(w: int, h: int) -> tuple[int, int]:
    """Return ``(length, thickness)`` — length is the longer axis."""
    if w >= h:
        return w, h
    return h, w


def _place_on_border(
    canvas: np.ndarray,
    stroke_rows: np.ndarray,
    thickness_axis: str,
) -> np.ndarray:
    """Copy *stroke_rows* onto both edges of the *thickness axis*.

    *stroke_rows* has shape ``(thickness, length, 4)`` when thickness
    axis is ``"y"``; ``(length, thickness, 4)`` when ``"x"``. Pixels are
    stamped on both edges; the middle stays alpha=0.
    """
    if thickness_axis == "y":
        # Horizontal strip: paint into top ``thickness`` rows.
        t = stroke_rows.shape[0]
        canvas[:t, :, :] = stroke_rows
    else:
        # Vertical strip: paint into left ``thickness`` cols.
        t = stroke_rows.shape[1]
        canvas[:, :t, :] = stroke_rows
    return canvas


# ---------------------------------------------------------------------------
# Preset render functions
# ---------------------------------------------------------------------------


def _render_pencil_scribble(
    w: int, h: int, ink: tuple[int, int, int, int]
) -> np.ndarray:
    """Grey pencil hatching, ~2px thick, wavy ~0.5px per-column offset."""
    rng = _seed_rng("pencil_scribble", w, h)
    canvas = np.zeros((h, w, 4), dtype=np.uint8)
    length, thickness = _orient(w, h)
    # Two-pixel stroke, wobbled by a sinusoid + fine noise.
    stroke_h = min(max(thickness, 1), max(2, thickness))
    wobble = (
        0.5 * np.sin(np.linspace(0.0, 6.283, length, dtype=np.float32) * 3.0)
        + 0.15 * (rng.random(length, dtype=np.float32) - 0.5) * 2.0
    )
    strip = np.zeros((stroke_h, length, 4), dtype=np.uint8)
    grey = np.array([120, 120, 120, 200], dtype=np.uint8)
    # Blend ink colour hint into grey so themes get some drift.
    grey[:3] = (0.6 * np.asarray(grey[:3]) + 0.4 * np.asarray(ink[:3])).astype(
        np.uint8
    )
    for col in range(length):
        # Wobble offset picks a sub-row bias — hatching thickness in
        # practice is 1 or 2 rows depending on where the wobble lands.
        offset = wobble[col]
        alpha_top = np.clip(0.85 - abs(offset), 0.0, 1.0)
        alpha_bot = np.clip(0.85 - abs(1.0 - offset), 0.0, 1.0)
        strip[0, col, :3] = grey[:3]
        strip[0, col, 3] = int(alpha_top * grey[3])
        if stroke_h > 1:
            strip[1, col, :3] = grey[:3]
            strip[1, col, 3] = int(alpha_bot * grey[3])
    # Overlay on both edges of the thickness axis.
    axis = "y" if w >= h else "x"
    canvas = _place_on_border(canvas, strip if axis == "y" else strip.transpose(1, 0, 2).copy(), axis)
    if axis == "y":
        canvas[-strip.shape[0]:, :, :] = strip
    else:
        canvas[:, -strip.shape[1]:, :] = strip.transpose(1, 0, 2).copy()
    return canvas


def _perlin_1d(rng: np.random.Generator, length: int, freq: float) -> np.ndarray:
    """Very cheap 1-D value-noise substitute for Perlin."""
    grid_n = max(4, int(length * freq))
    # ``endpoint=True`` so we get exactly grid_n values across [0, length].
    grid = rng.random(grid_n, dtype=np.float32)
    xs = np.linspace(0.0, grid_n - 1, length, dtype=np.float32)
    lo = np.floor(xs).astype(np.int32)
    hi = np.clip(lo + 1, 0, grid_n - 1)
    frac = xs - lo
    # Smoothstep interpolation for a Perlin-ish curve.
    frac = frac * frac * (3.0 - 2.0 * frac)
    return grid[lo] * (1.0 - frac) + grid[hi] * frac


def _render_ink_thick(
    w: int, h: int, ink: tuple[int, int, int, int]
) -> np.ndarray:
    """Solid ~2-3px black ink with Perlin-noise-modulated width blob."""
    rng = _seed_rng("ink_thick", w, h)
    canvas = np.zeros((h, w, 4), dtype=np.uint8)
    length, thickness = _orient(w, h)
    if length == 0 or thickness == 0:
        return canvas
    # Modulated width in [1.7, 3.3] pixels along the strip.
    noise = _perlin_1d(rng, length, freq=0.06)
    width = 1.7 + 1.6 * noise  # per-column width
    strip_thickness = int(min(thickness, 3))
    if strip_thickness == 0:
        strip_thickness = 1
    strip = np.zeros((max(1, strip_thickness), length, 4), dtype=np.uint8)
    ink_rgb = np.array(ink[:3], dtype=np.uint8)
    for col in range(length):
        w_here = width[col]
        # Row 0 always painted, row 1 gets less alpha near w~2, row 2 only
        # when w > 2.5.
        strip[0, col, :3] = ink_rgb
        strip[0, col, 3] = 255
        if strip_thickness > 1:
            strip[1, col, :3] = ink_rgb
            strip[1, col, 3] = int(np.clip((w_here - 1.0) * 255.0, 0.0, 255.0))
        if strip_thickness > 2:
            strip[2, col, :3] = ink_rgb
            strip[2, col, 3] = int(
                np.clip((w_here - 2.0) * 255.0, 0.0, 255.0)
            )
    axis = "y" if w >= h else "x"
    if axis == "y":
        t = strip.shape[0]
        canvas[:t, :, :] = strip
        canvas[-t:, :, :] = strip[::-1]
    else:
        t = strip.shape[0]
        vertical = strip.transpose(1, 0, 2).copy()
        canvas[:, :t, :] = vertical
        canvas[:, -t:, :] = vertical[:, ::-1]
    return canvas


def _render_ink_thin(
    w: int, h: int, ink: tuple[int, int, int, int]
) -> np.ndarray:
    """~1px charcoal-grey line with occasional dried-pen gaps."""
    rng = _seed_rng("ink_thin", w, h)
    canvas = np.zeros((h, w, 4), dtype=np.uint8)
    length, thickness = _orient(w, h)
    if length == 0 or thickness == 0:
        return canvas
    # Charcoal is desaturated grey biased toward the ink hint.
    charcoal = (
        0.7 * np.array([65, 65, 68], dtype=np.float32)
        + 0.3 * np.asarray(ink[:3], dtype=np.float32)
    ).astype(np.uint8)
    # ~7% dried-pen gap probability, streaked so gaps run 2-4 pixels.
    gap_seed = rng.random(length, dtype=np.float32)
    gaps = gap_seed < 0.07
    # Streak the gaps by OR'ing with a rolled copy — turns single-pixel
    # gaps into 2-4 pixel dry-pen runs.
    gaps = gaps | np.roll(gaps, 1) | np.roll(gaps, 2)
    strip = np.zeros((1, length, 4), dtype=np.uint8)
    strip[0, :, :3] = charcoal
    strip[0, :, 3] = np.where(gaps, 0, 235).astype(np.uint8)
    axis = "y" if w >= h else "x"
    if axis == "y":
        canvas[:1, :, :] = strip
        canvas[-1:, :, :] = strip
    else:
        vertical = strip.transpose(1, 0, 2).copy()
        canvas[:, :1, :] = vertical
        canvas[:, -1:, :] = vertical
    return canvas


def _render_marker_bleed(
    w: int, h: int, ink: tuple[int, int, int, int]
) -> np.ndarray:
    """Thick ~3-4px pastel line with 2-4px alpha-bleed halo."""
    rng = _seed_rng("marker_bleed", w, h)
    canvas = np.zeros((h, w, 4), dtype=np.uint8)
    length, thickness = _orient(w, h)
    if length == 0 or thickness == 0:
        return canvas
    # Pastel = mix ink toward white.
    pastel = (
        0.4 * np.asarray(ink[:3], dtype=np.float32)
        + 0.6 * np.array([255, 240, 245], dtype=np.float32)
    ).astype(np.uint8)
    core = min(4, max(3, thickness // 2 + 3))
    halo = min(4, max(2, thickness - core))
    total = min(thickness, core + halo)
    strip = np.zeros((total, length, 4), dtype=np.uint8)
    # Slight per-column wobble so the halo isn't perfectly straight.
    wobble = 0.15 * (rng.random(length, dtype=np.float32) - 0.5) * 2.0
    for row in range(total):
        if row < core:
            alpha = 235
        else:
            # Halo drops off from ~150 at the inner edge to ~40 at outer.
            fade = (row - core + 1) / max(1, halo)
            alpha = int(np.clip(150.0 * (1.0 - fade) + 40.0 * fade, 0.0, 255.0))
        # Apply wobble to alpha so the halo has a slightly organic edge.
        col_alpha = np.clip(alpha + wobble * 20.0, 0.0, 255.0).astype(np.uint8)
        strip[row, :, :3] = pastel
        strip[row, :, 3] = col_alpha
    axis = "y" if w >= h else "x"
    if axis == "y":
        t = strip.shape[0]
        canvas[:t, :, :] = strip
        canvas[-t:, :, :] = strip[::-1]
    else:
        t = strip.shape[0]
        vertical = strip.transpose(1, 0, 2).copy()
        canvas[:, :t, :] = vertical
        canvas[:, -t:, :] = vertical[:, ::-1]
    return canvas


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


EDGE_STROKE_PRESETS: dict[str, EdgeStrokePreset] = {
    "pencil_scribble": EdgeStrokePreset(
        preset_id="pencil_scribble",
        thickness_px=2.0,
        description="Grey pencil hatching with wavy sub-pixel column offset.",
        ink_rgba=(70, 70, 70, 255),
        render_fn=_render_pencil_scribble,
        tags=("dry", "hatching", "notebook"),
    ),
    "ink_thick": EdgeStrokePreset(
        preset_id="ink_thick",
        thickness_px=2.5,
        description="Solid black ink with Perlin-modulated width blob.",
        ink_rgba=(15, 15, 20, 255),
        render_fn=_render_ink_thick,
        tags=("wet", "solid", "notebook"),
    ),
    "ink_thin": EdgeStrokePreset(
        preset_id="ink_thin",
        thickness_px=1.0,
        description="Fine charcoal-grey line with dried-pen gap breaks.",
        ink_rgba=(50, 50, 55, 235),
        render_fn=_render_ink_thin,
        tags=("wet", "thin", "notebook"),
    ),
    "marker_bleed": EdgeStrokePreset(
        preset_id="marker_bleed",
        thickness_px=3.5,
        description="Pastel marker core with soft alpha-bleed halo.",
        ink_rgba=(240, 120, 160, 235),
        render_fn=_render_marker_bleed,
        tags=("wet", "pastel", "halo"),
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_edge_stroke(
    preset: str,
    w: int,
    h: int,
    *,
    ink_rgba: tuple[int, int, int, int] | None = None,
) -> np.ndarray:
    """Render one edge-stroke strip using *preset*.

    Parameters
    ----------
    preset:
        A key from :data:`EDGE_STROKE_PRESETS`.
    w, h:
        Strip dimensions in pixels. The shorter axis is the *thickness*;
        the longer axis is the *length*. The returned array always has
        shape ``(h, w, 4)`` uint8 RGBA with alpha ``0`` in the interior
        and stroke pixels stamped on both edges of the thickness axis.
    ink_rgba:
        Optional override for the preset's default ink colour.

    Raises
    ------
    KeyError
        If *preset* is not in :data:`EDGE_STROKE_PRESETS`.
    ValueError
        If ``w`` or ``h`` is not a positive integer.
    """
    validate_non_empty_str("preset", "render_edge_stroke", preset)
    w = validate_positive_int("w", "render_edge_stroke", int(w))
    h = validate_positive_int("h", "render_edge_stroke", int(h))
    try:
        spec = EDGE_STROKE_PRESETS[preset]
    except KeyError as exc:
        available = ", ".join(sorted(EDGE_STROKE_PRESETS)) or "(none)"
        raise KeyError(
            f"render_edge_stroke: no preset {preset!r}; available: {available}"
        ) from exc
    ink = ink_rgba if ink_rgba is not None else spec.ink_rgba
    if not isinstance(ink, (tuple, list)) or len(ink) != 4:
        raise TypeError(
            "render_edge_stroke: ink_rgba must be a 4-tuple of ints; "
            f"got {ink!r}"
        )
    ink_t = (int(ink[0]), int(ink[1]), int(ink[2]), int(ink[3]))
    return spec.render_fn(w, h, ink_t)


def list_presets() -> list[str]:
    """Return a sorted list of registered edge-stroke preset names."""
    return sorted(EDGE_STROKE_PRESETS)


__all__ = [
    "EDGE_STROKE_PRESETS",
    "EdgeStrokePreset",
    "list_presets",
    "render_edge_stroke",
]
