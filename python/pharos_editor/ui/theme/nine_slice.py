"""Nine-slice texture rendering.

Nine-slice (a.k.a. 9-patch) splits a small source texture into nine
regions — four corners, four edges, one centre — so the corners stay
crisp at any target size while the edges and centre tile to fill. This
keeps theme borders, panels, and buttons authored at one fixed source
size yet legible at any DPI without baking giant PNGs.

This module ships two flavours:

* :class:`NineSlice` — reads a source image (file path or raw RGBA bytes)
  and renders into an arbitrarily-sized RGBA ndarray.
* :meth:`NineSlice.render_procedural` — generates the nine cells from a
  caller-supplied 2D pattern function, no image asset needed. This is
  the "zero-asset" path the Pharos Engine theme system prefers for
  flat / patterned UI surfaces.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from pharos_engine._validation import (
    validate_non_negative_int,
    validate_positive_int,
    validate_positive_size_2tuple,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_insets(
    name: str, fn: str, insets: Any
) -> tuple[int, int, int, int]:
    """Validate a 4-int insets tuple ``(top, right, bottom, left)``."""
    if isinstance(insets, (str, bytes)) or not hasattr(insets, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a 4-tuple of ints; "
            f"got {type(insets).__name__}"
        )
    if len(insets) != 4:
        raise ValueError(
            f"{fn}: {name} must have length 4 (top, right, bottom, left); "
            f"got length {len(insets)}"
        )
    top = validate_non_negative_int(f"{name}[0] (top)", fn, insets[0])
    right = validate_non_negative_int(f"{name}[1] (right)", fn, insets[1])
    bottom = validate_non_negative_int(f"{name}[2] (bottom)", fn, insets[2])
    left = validate_non_negative_int(f"{name}[3] (left)", fn, insets[3])
    return (top, right, bottom, left)


def _load_rgba(source: Path | bytes | np.ndarray) -> np.ndarray:
    """Load *source* into an ``(H, W, 4)`` uint8 RGBA ndarray.

    Accepts a filesystem :class:`Path`, raw image bytes, or a pre-built
    ndarray (passed through with shape validation). Image decode goes
    through PIL — the dependency is already pulled in by the editor
    extra; we raise an :class:`ImportError` with a clear hint otherwise.
    """
    if isinstance(source, np.ndarray):
        arr = source
    else:
        try:
            from PIL import Image  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - defensive
            raise ImportError(
                "NineSlice image loading requires Pillow: pip install pillow"
            ) from exc
        if isinstance(source, (bytes, bytearray)):
            import io

            img = Image.open(io.BytesIO(bytes(source)))
        elif isinstance(source, Path):
            img = Image.open(source)
        else:
            raise TypeError(
                "NineSlice: source must be Path, bytes, or ndarray; "
                f"got {type(source).__name__}"
            )
        img = img.convert("RGBA")
        arr = np.asarray(img, dtype=np.uint8)
    if arr.ndim != 3 or arr.shape[2] != 4:
        raise ValueError(
            f"NineSlice: source must be HxWx4 RGBA; got shape {arr.shape}"
        )
    if arr.dtype != np.uint8:
        arr = arr.astype(np.uint8)
    return arr


def _tile_axis(strip: np.ndarray, target_len: int, axis: int) -> np.ndarray:
    """Tile *strip* along *axis* to reach exactly *target_len* pixels.

    Wraps repeatedly then truncates — cheaper than a bicubic stretch and
    keeps the source pattern crisp at all scales.
    """
    src_len = strip.shape[axis]
    if src_len == 0:
        # Caller passed a zero-width strip — produce an empty band.
        new_shape = list(strip.shape)
        new_shape[axis] = target_len
        return np.zeros(new_shape, dtype=strip.dtype)
    reps = (target_len + src_len - 1) // src_len
    if axis == 0:
        tiled = np.tile(strip, (reps, 1, 1))
        return tiled[:target_len, :, :]
    elif axis == 1:
        tiled = np.tile(strip, (1, reps, 1))
        return tiled[:, :target_len, :]
    else:
        raise ValueError(f"_tile_axis: unsupported axis {axis}")


# ---------------------------------------------------------------------------
# NineSlice
# ---------------------------------------------------------------------------


@dataclass
class NineSlice:
    """Nine-slice texture record.

    Parameters
    ----------
    source:
        File path, raw RGBA bytes, or a pre-built ``HxWx4`` ndarray.
        ``None`` is allowed when the caller plans to use only
        :meth:`render_procedural`.
    insets:
        Corner pixel insets in ``(top, right, bottom, left)`` order.
        Each must be a non-negative int; their sums along each axis
        must fit inside the corresponding source dimension.
    """

    source: Path | bytes | np.ndarray | None = None
    insets: tuple[int, int, int, int] = (4, 4, 4, 4)
    _array: np.ndarray | None = field(default=None, repr=False, init=False)

    def __post_init__(self) -> None:
        fn = "NineSlice"
        self.insets = _validate_insets("insets", fn, self.insets)
        if self.source is not None:
            arr = _load_rgba(self.source)
            top, right, bottom, left = self.insets
            if top + bottom >= arr.shape[0]:
                raise ValueError(
                    f"{fn}: vertical insets {top}+{bottom} "
                    f">= source height {arr.shape[0]}"
                )
            if left + right >= arr.shape[1]:
                raise ValueError(
                    f"{fn}: horizontal insets {left}+{right} "
                    f">= source width {arr.shape[1]}"
                )
            self._array = arr

    # ---- Image-backed render ----------------------------------------------

    def render(self, target_size: tuple[int, int]) -> np.ndarray:
        """Render to a target-sized RGBA ndarray.

        Corners are copied verbatim, edges are tiled along their long
        axis, and the centre is tiled in both directions.

        Parameters
        ----------
        target_size:
            ``(width, height)`` in pixels. Both must be positive ints
            and at least ``insets[left]+insets[right]`` /
            ``insets[top]+insets[bottom]`` respectively.

        Raises
        ------
        ValueError
            If :class:`NineSlice` was constructed without a source.
        """
        if self._array is None:
            raise ValueError(
                "NineSlice.render: no source — use render_procedural instead"
            )
        w, h = validate_positive_size_2tuple(
            "target_size", "NineSlice.render", target_size
        )
        return self._render_from_array(self._array, (w, h))

    def _render_from_array(
        self, src: np.ndarray, target_size: tuple[int, int]
    ) -> np.ndarray:
        top, right, bottom, left = self.insets
        sh, sw = src.shape[0], src.shape[1]
        tw, th = target_size
        if tw < left + right or th < top + bottom:
            raise ValueError(
                f"NineSlice.render: target {target_size} too small for insets "
                f"(min {left + right}x{top + bottom})"
            )
        out = np.zeros((th, tw, 4), dtype=np.uint8)
        # Corner extractions
        tl = src[:top, :left, :]
        tr = src[:top, sw - right:, :]
        bl = src[sh - bottom:, :left, :]
        br = src[sh - bottom:, sw - right:, :]
        # Edge strips
        top_strip = src[:top, left:sw - right, :]
        bottom_strip = src[sh - bottom:, left:sw - right, :]
        left_strip = src[top:sh - bottom, :left, :]
        right_strip = src[top:sh - bottom, sw - right:, :]
        # Centre block
        centre = src[top:sh - bottom, left:sw - right, :]
        # Place corners
        if top and left:
            out[:top, :left, :] = tl
        if top and right:
            out[:top, tw - right:, :] = tr
        if bottom and left:
            out[th - bottom:, :left, :] = bl
        if bottom and right:
            out[th - bottom:, tw - right:, :] = br
        # Place top + bottom strips (tile along x)
        edge_w = tw - left - right
        if top and edge_w > 0:
            out[:top, left:tw - right, :] = _tile_axis(top_strip, edge_w, axis=1)
        if bottom and edge_w > 0:
            out[th - bottom:, left:tw - right, :] = _tile_axis(
                bottom_strip, edge_w, axis=1
            )
        # Place left + right strips (tile along y)
        edge_h = th - top - bottom
        if left and edge_h > 0:
            out[top:th - bottom, :left, :] = _tile_axis(
                left_strip, edge_h, axis=0
            )
        if right and edge_h > 0:
            out[top:th - bottom, tw - right:, :] = _tile_axis(
                right_strip, edge_h, axis=0
            )
        # Centre — tile in both directions
        if edge_w > 0 and edge_h > 0:
            row = _tile_axis(centre, edge_w, axis=1)
            out[top:th - bottom, left:tw - right, :] = _tile_axis(
                row, edge_h, axis=0
            )
        return out

    # ---- Procedural render ------------------------------------------------

    def render_procedural(
        self,
        size: tuple[int, int],
        color: tuple[int, int, int, int],
        pattern_fn: Callable[[int, int], np.ndarray] | None = None,
    ) -> np.ndarray:
        """Render without a source by synthesising the nine cells.

        A *pattern_fn* of signature ``fn(width, height) -> ndarray`` is
        invoked for the centre block (tiled to fill). When omitted the
        centre is a solid fill of *color*. Corners + edges are always
        drawn as a one-pixel border outline using *color*.

        Parameters
        ----------
        size:
            ``(width, height)`` in pixels.
        color:
            RGBA tuple ``[0, 255]`` per channel.
        pattern_fn:
            Optional centre-pattern generator. Must return an RGBA
            ndarray; smaller-than-centre returns are tiled.
        """
        fn = "NineSlice.render_procedural"
        w, h = validate_positive_size_2tuple("size", fn, size)
        if (not isinstance(color, (tuple, list))) or len(color) != 4:
            raise TypeError(f"{fn}: color must be a 4-tuple")
        rgba = tuple(int(c) for c in color)
        for c in rgba:
            if c < 0 or c > 255:
                raise ValueError(f"{fn}: color channels must be in [0, 255]")
        top, right, bottom, left = self.insets
        if w < left + right or h < top + bottom:
            raise ValueError(
                f"{fn}: target {size} too small for insets "
                f"(min {left + right}x{top + bottom})"
            )
        out = np.zeros((h, w, 4), dtype=np.uint8)
        # Fill solid border using *color*.
        if top:
            out[:top, :, :] = rgba
        if bottom:
            out[h - bottom:, :, :] = rgba
        if left:
            out[:, :left, :] = rgba
        if right:
            out[:, w - right:, :] = rgba
        # Centre fill
        edge_w = w - left - right
        edge_h = h - top - bottom
        if edge_w > 0 and edge_h > 0:
            if pattern_fn is None:
                out[top:h - bottom, left:w - right, :] = rgba
            else:
                tile = pattern_fn(edge_w, edge_h)
                if not isinstance(tile, np.ndarray):
                    raise TypeError(
                        f"{fn}: pattern_fn must return ndarray; "
                        f"got {type(tile).__name__}"
                    )
                if tile.ndim != 3 or tile.shape[2] != 4:
                    raise ValueError(
                        f"{fn}: pattern_fn must return HxWx4 RGBA; "
                        f"got shape {tile.shape}"
                    )
                # If the pattern is smaller than the centre, tile it.
                ph, pw = tile.shape[0], tile.shape[1]
                if ph < edge_h or pw < edge_w:
                    reps_y = (edge_h + ph - 1) // ph
                    reps_x = (edge_w + pw - 1) // pw
                    tile = np.tile(tile, (reps_y, reps_x, 1))
                out[top:h - bottom, left:w - right, :] = tile[
                    :edge_h, :edge_w, :
                ]
        return out

    # ---- YAML round-trip --------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a YAML-safe dict (omits the loaded source array)."""
        return {
            "insets": list(self.insets),
            # Source is intentionally dropped from the dict round-trip —
            # tex bytes are not YAML-friendly. Callers re-attach on load.
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NineSlice":
        """Rebuild from :meth:`to_dict` output (source-less)."""
        if not isinstance(data, dict):
            raise TypeError(
                f"NineSlice.from_dict: data must be a dict; "
                f"got {type(data).__name__}"
            )
        insets = data.get("insets", (0, 0, 0, 0))
        return cls(source=None, insets=tuple(insets))


# ---------------------------------------------------------------------------
# Re-export validator name so static analysis sees the dependency.
# ---------------------------------------------------------------------------

_ = validate_positive_int


__all__ = ["NineSlice"]
