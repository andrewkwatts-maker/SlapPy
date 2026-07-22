"""Post-processing passes for the PhysicsRenderer.

This module is intentionally self-contained: it operates on plain ``numpy``
``(H, W, 4)`` uint8 RGBA frames so it can be composed downstream of any
renderer without coupling to the renderer's internals.

Passes provided:

* :class:`BloomPass`     - single-pass separable Gaussian bloom on bright
  pixels (luma > threshold).  Uses :func:`scipy.ndimage.gaussian_filter`
  when SciPy is available, otherwise falls back to a pure-NumPy separable
  Gaussian implementation.
* :class:`TonemapPass`   - Narkowicz ACES-fitted tonemap curve.
* :class:`PostProcessChain` - composable chain of passes.

Approximation notes (reported in the module docstring for clarity):

* The bloom is a *single* Gaussian convolution rather than a multi-mip
  downsample/upsample chain.  This is cheaper and adequate for the small
  2D framebuffers the PhysicsRenderer produces.
* The ACES curve is the Narkowicz "ACES Filmic" fit, not the full
  RRT+ODT pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np

try:  # SciPy is optional; we fall back to a NumPy implementation.
    from scipy.ndimage import gaussian_filter as _scipy_gaussian_filter

    _HAVE_SCIPY = True
except Exception:  # pragma: no cover - exercised only when SciPy missing
    _scipy_gaussian_filter = None
    _HAVE_SCIPY = False


__all__ = [
    "BloomPass",
    "TonemapPass",
    "PostProcessChain",
    "default_post_process_chain",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _luma(rgb: np.ndarray) -> np.ndarray:
    """Rec.601 luma from an (H, W, 3) float array."""
    return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]


def _gaussian_kernel_1d(sigma: float) -> np.ndarray:
    """Build a 1-D Gaussian kernel for a given sigma."""
    sigma = max(float(sigma), 1e-6)
    # Truncate at 3 sigma like scipy's default.
    radius = max(1, int(np.ceil(3.0 * sigma)))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    k = np.exp(-(x * x) / (2.0 * sigma * sigma))
    k /= k.sum()
    return k


def _separable_gaussian(image: np.ndarray, sigma: float) -> np.ndarray:
    """Pure-NumPy separable Gaussian blur for an (H, W) or (H, W, C) float array.

    Used as a fallback when SciPy is not installed.
    """
    if sigma <= 0.0:
        return image.copy()

    k = _gaussian_kernel_1d(sigma)
    radius = (k.size - 1) // 2

    def _blur_axis(arr: np.ndarray, axis: int) -> np.ndarray:
        # Reflect-pad to match scipy's default 'reflect' mode behaviour.
        pad = [(0, 0)] * arr.ndim
        pad[axis] = (radius, radius)
        padded = np.pad(arr, pad, mode="reflect")
        # Build sliding window view along the chosen axis.
        out = np.zeros_like(arr, dtype=np.float64)
        for i, w in enumerate(k):
            sl = [slice(None)] * arr.ndim
            sl[axis] = slice(i, i + arr.shape[axis])
            out += w * padded[tuple(sl)]
        return out

    blurred = _blur_axis(image.astype(np.float64), axis=0)
    blurred = _blur_axis(blurred, axis=1)
    return blurred


def _gaussian_blur(image: np.ndarray, sigma: float) -> np.ndarray:
    """Blur an (H, W) or (H, W, C) array, using SciPy when available."""
    if sigma <= 0.0:
        return image.astype(np.float64, copy=True)
    if _HAVE_SCIPY:
        if image.ndim == 2:
            return _scipy_gaussian_filter(image.astype(np.float64), sigma=sigma)
        # Blur each channel independently; do not blur across channels.
        sigmas = (sigma, sigma) + (0.0,) * (image.ndim - 2)
        return _scipy_gaussian_filter(image.astype(np.float64), sigma=sigmas)
    return _separable_gaussian(image, sigma)


# ---------------------------------------------------------------------------
# Passes
# ---------------------------------------------------------------------------


@dataclass
class BloomPass:
    """Single-pass Gaussian bloom on bright (luma > threshold) pixels.

    The threshold operates on Rec.601 luma in the same 0..255 scale as the
    input frame.  The blurred bright-pixel contribution is added back into
    the original frame and clamped to ``[0, 255]``.
    """

    threshold: float = 200.0
    intensity: float = 0.8
    radius_px: float = 6.0

    def apply(self, frame: np.ndarray) -> np.ndarray:
        if frame.ndim != 3 or frame.shape[-1] != 4:
            raise ValueError("BloomPass expects an (H, W, 4) RGBA frame")

        rgb = frame[..., :3].astype(np.float64)
        alpha = frame[..., 3:4]

        luma = _luma(rgb)
        mask = (luma > float(self.threshold)).astype(np.float64)

        # Extract bright pixels only.
        bright = rgb * mask[..., None]

        # Blur the bright-only image.
        blurred = _gaussian_blur(bright, sigma=float(self.radius_px))

        # Composite: original + intensity * blurred bright.
        out = rgb + float(self.intensity) * blurred
        np.clip(out, 0.0, 255.0, out=out)

        result = np.empty_like(frame)
        result[..., :3] = out.astype(np.uint8)
        result[..., 3:4] = alpha
        return result


@dataclass
class TonemapPass:
    """Narkowicz ACES-fitted tonemap.

    Operates in normalised float space ``[0, 1]`` after applying the
    ``exposure`` multiplier.  Alpha is passed through untouched.
    """

    exposure: float = 1.0

    def apply(self, frame: np.ndarray) -> np.ndarray:
        if frame.ndim != 3 or frame.shape[-1] != 4:
            raise ValueError("TonemapPass expects an (H, W, 4) RGBA frame")

        rgb = frame[..., :3].astype(np.float64) / 255.0
        alpha = frame[..., 3:4]

        x = rgb * float(self.exposure)
        # Narkowicz ACES fit.
        aces = (x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14)
        np.clip(aces, 0.0, 1.0, out=aces)

        result = np.empty_like(frame)
        result[..., :3] = (aces * 255.0).astype(np.uint8)
        result[..., 3:4] = alpha
        return result


class PostProcessChain:
    """Composable chain of post-processing passes."""

    def __init__(self, passes: Optional[List[object]] = None) -> None:
        self.passes: List[object] = list(passes) if passes else []

    def add(self, pass_: object) -> "PostProcessChain":
        self.passes.append(pass_)
        return self

    def apply(self, frame: np.ndarray) -> np.ndarray:
        for p in self.passes:
            frame = p.apply(frame)
        return frame


def default_post_process_chain() -> PostProcessChain:
    """Factory returning a sensible default chain (bloom -> tonemap)."""
    return PostProcessChain([BloomPass(), TonemapPass()])
