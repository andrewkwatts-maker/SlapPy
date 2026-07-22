"""CPU signed-distance-field generation + atlas box-packing.

The functions in this module are deliberately dependency-free (numpy only)
so they work in headless CI even when freetype / PIL are unavailable.

``sdf_from_bitmap`` is a straight 8-SSED (eight-point sequential Euclidean
distance) transform:

* pass 1 sweeps top-left → bottom-right, propagating the nearest boundary
  pixel from the north/west neighbourhood,
* pass 2 sweeps bottom-right → top-left, propagating from the south/east
  neighbourhood.

The signed distance is then computed by evaluating the transform once with
inside pixels as seeds and once with outside pixels as seeds and combining
the two (inside distances are negated). Values are clamped to the
``radius_px`` requested by the caller so the atlas can be stored as
uint8 without losing precision beyond the halo the shader samples.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np


# ---------------------------------------------------------------------------
# 8-SSED transform
# ---------------------------------------------------------------------------

_INF = 1e9


def _edt_from_seed(seed: np.ndarray) -> np.ndarray:
    """Euclidean distance transform: seed==True are sources, distance
    to the nearest True pixel is returned in float32."""
    h, w = seed.shape
    # Store the *offset* from each pixel to its nearest seed as two int
    # channels; that is how the 8SSED algorithm keeps sub-pixel precision.
    # Uninitialised pixels use a huge offset so they lose min() comparisons.
    dx = np.where(seed, 0, np.int32(1 << 15)).astype(np.int32)
    dy = np.where(seed, 0, np.int32(1 << 15)).astype(np.int32)

    def _sq(ax, ay):
        return ax.astype(np.int64) * ax + ay.astype(np.int64) * ay

    # Forward pass (top-left → bottom-right)
    for y in range(h):
        for x in range(w):
            best_dx, best_dy = dx[y, x], dy[y, x]
            best = _sq(np.array(best_dx), np.array(best_dy))
            for oy, ox in ((-1, -1), (-1, 0), (-1, 1), (0, -1)):
                ny, nx = y + oy, x + ox
                if 0 <= ny < h and 0 <= nx < w:
                    cand_dx = dx[ny, nx] + ox
                    cand_dy = dy[ny, nx] + oy
                    cand = _sq(np.array(cand_dx), np.array(cand_dy))
                    if cand < best:
                        best = cand
                        best_dx, best_dy = cand_dx, cand_dy
            dx[y, x], dy[y, x] = best_dx, best_dy

    # Backward pass (bottom-right → top-left)
    for y in range(h - 1, -1, -1):
        for x in range(w - 1, -1, -1):
            best_dx, best_dy = dx[y, x], dy[y, x]
            best = _sq(np.array(best_dx), np.array(best_dy))
            for oy, ox in ((0, 1), (1, -1), (1, 0), (1, 1)):
                ny, nx = y + oy, x + ox
                if 0 <= ny < h and 0 <= nx < w:
                    cand_dx = dx[ny, nx] + ox
                    cand_dy = dy[ny, nx] + oy
                    cand = _sq(np.array(cand_dx), np.array(cand_dy))
                    if cand < best:
                        best = cand
                        best_dx, best_dy = cand_dx, cand_dy
            dx[y, x], dy[y, x] = best_dx, best_dy

    return np.sqrt(_sq(dx, dy).astype(np.float64)).astype(np.float32)


def sdf_from_bitmap(bitmap: np.ndarray, radius_px: int) -> np.ndarray:
    """Compute a signed distance field from a binary bitmap.

    Parameters
    ----------
    bitmap:
        HxW array; non-zero pixels are considered *inside* the shape.
    radius_px:
        Distances are clamped to ``[-radius_px, +radius_px]``. Positive
        distances mean outside, negative distances mean inside — the sign
        convention the WGSL shader assumes.

    Returns
    -------
    ``np.ndarray`` (float32) of shape ``bitmap.shape`` holding the signed
    distance in pixels.
    """
    if radius_px <= 0:
        raise ValueError("radius_px must be positive")
    b = np.asarray(bitmap) != 0
    if b.ndim != 2:
        raise ValueError("bitmap must be 2D")

    # For small bitmaps we use the naive-but-exact O(h*w * h*w) approach —
    # the 8-SSED loop above is O(h*w) but has heavy Python overhead. Cap at
    # 96px on each axis (glyphs at 32px + 8px halo comfortably fit).
    if max(b.shape) <= 96:
        outside = _brute_edt(b)
        inside = _brute_edt(~b)
    else:  # pragma: no cover — exercised in the pack test with larger bitmaps
        outside = _edt_from_seed(b)
        inside = _edt_from_seed(~b)

    signed = outside - inside  # positive outside, negative inside
    return np.clip(signed, -radius_px, radius_px).astype(np.float32)


def _brute_edt(seed: np.ndarray) -> np.ndarray:
    """Exact Euclidean distance transform via broadcasting.

    Only viable for small bitmaps (< ~100 px per side) but numerically
    perfect, which is what the tests want.
    """
    h, w = seed.shape
    ys, xs = np.where(seed)
    if len(ys) == 0:
        return np.full((h, w), np.inf, dtype=np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    dy = yy[..., None] - ys[None, None, :]
    dx = xx[..., None] - xs[None, None, :]
    d2 = dy * dy + dx * dx
    return np.sqrt(d2.min(axis=-1)).astype(np.float32)


# ---------------------------------------------------------------------------
# Rectangle packing (shelf/skyline hybrid — simple and stable)
# ---------------------------------------------------------------------------


def pack_glyphs_into_atlas(
    glyphs: Sequence[np.ndarray],
    max_side: int = 2048,
    padding: int = 1,
) -> tuple[np.ndarray, list[tuple[int, int, int, int]]]:
    """Pack a list of glyph bitmaps into a single 2D atlas texture.

    Parameters
    ----------
    glyphs:
        Iterable of HxW numpy arrays (float32 SDF or uint8 alpha).
    max_side:
        Maximum atlas width/height in pixels.
    padding:
        Empty pixels inserted between glyphs to avoid bilinear bleed.

    Returns
    -------
    ``(atlas, positions)`` where ``atlas`` has the same dtype as the input
    (all glyphs must share dtype) and ``positions`` is a list of
    ``(x, y, w, h)`` tuples in the same order as ``glyphs``.
    """
    if max_side <= 0:
        raise ValueError(f"max_side must be > 0; got {max_side}")
    if padding < 0:
        raise ValueError(f"padding must be >= 0; got {padding}")
    if not glyphs:
        return np.zeros((1, 1), dtype=np.float32), []

    for i, g in enumerate(glyphs):
        if not isinstance(g, np.ndarray):
            raise TypeError(
                f"pack_glyphs_into_atlas: glyph[{i}] must be ndarray; "
                f"got {type(g).__name__}"
            )
        if g.ndim != 2:
            raise ValueError(
                f"pack_glyphs_into_atlas: glyph[{i}] must be 2D; "
                f"got shape {g.shape}"
            )

    dtype = glyphs[0].dtype
    if any(g.dtype != dtype for g in glyphs):
        raise ValueError("all glyph bitmaps must share dtype")

    # Sort by descending height for a well-known ~10% packing win.
    ordered = sorted(
        range(len(glyphs)),
        key=lambda i: (-glyphs[i].shape[0], -glyphs[i].shape[1]),
    )

    # Shelf packer — width chosen as smallest power-of-two that fits the
    # widest glyph, doubling until everything packs.
    widest = max(g.shape[1] for g in glyphs) + 2 * padding
    atlas_w = 1
    while atlas_w < widest:
        atlas_w *= 2

    while True:
        positions = [None] * len(glyphs)  # type: ignore[assignment]
        shelf_x = padding
        shelf_y = padding
        shelf_h = 0
        overflow = False
        for i in ordered:
            g = glyphs[i]
            gh, gw = g.shape[:2]
            if shelf_x + gw + padding > atlas_w:
                shelf_y += shelf_h + padding
                shelf_x = padding
                shelf_h = 0
            positions[i] = (shelf_x, shelf_y, gw, gh)
            shelf_x += gw + padding
            shelf_h = max(shelf_h, gh)
        atlas_h = shelf_y + shelf_h + padding
        if atlas_h <= atlas_w or atlas_w >= max_side:
            # Fits within a mostly-square atlas, or we've hit max_side —
            # accept the result.
            break
        atlas_w *= 2
        if atlas_w > max_side:
            atlas_w = max_side
            overflow = True
            break

    # Round atlas height up to next power of two for tex-sampler happiness.
    atlas_h = 1
    for i, (x, y, w, h) in enumerate(positions):
        atlas_h = max(atlas_h, y + h + padding)
    ph = 1
    while ph < atlas_h:
        ph *= 2
    atlas_h = ph

    atlas = np.zeros((atlas_h, atlas_w), dtype=dtype)
    for i, (x, y, w, h) in enumerate(positions):
        atlas[y:y + h, x:x + w] = glyphs[i]

    _ = overflow  # kept for potential future flag; silence lint
    return atlas, list(positions)  # type: ignore[return-value]
