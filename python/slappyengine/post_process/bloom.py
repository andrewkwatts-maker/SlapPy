"""Bloom post-process pass — Lottes 2017 smooth-threshold extraction.

The extraction stage uses the Lottes 2017 "smooth knee" curve to ramp the
contribution in gradually around the threshold, eliminating the popping
artifact that a hard luminance cutoff produces when an emissive pixel
sweeps across the threshold boundary.

Reference luma is the per-pixel ``max(R, G, B)`` (peak brightness) rather
than perceptual BT.709, because we want pure colour channels (e.g. a
saturated red flash) to bloom even when their perceptual luma is low.

Formula (see Lottes, GDC 2017, *Advanced Techniques and Optimization of
HDR Color Pipelines*):

    luma   = max(R, G, B)
    soft   = clamp(luma - threshold + knee, 0, 2*knee)**2 / (4*knee + eps)
    contrib = max(luma - threshold, soft)
    weight  = contrib / max(luma, eps)
    out     = colour * weight

When ``knee == 0`` the soft branch collapses to ``max(luma - threshold, 0)``
which reproduces the original hard-cutoff behaviour exactly (backward-compat).
"""
from __future__ import annotations

import struct
from typing import Iterable

import numpy as np

from .chain import PostProcessPass
from ._validation import validate_non_negative_float


_SHADER = "bloom_threshold.wgsl"
_ENTRY  = "main"

# Tiny epsilon used inside the Lottes formula to keep the divide safe when
# both knee and luma collapse to zero. Matches the GPU shader constant.
_EPS = 1.0e-6


def smooth_threshold(
    rgb: np.ndarray,
    threshold: float,
    knee: float,
) -> np.ndarray:
    """Apply the Lottes 2017 smooth-threshold curve to an HDR RGB image.

    Parameters
    ----------
    rgb
        ``(..., 3)`` float array of linear-HDR RGB values.
    threshold
        Cutoff luma above which pixels start bleeding into the bloom buffer.
    knee
        Width (in luma units) of the soft transition zone.  ``knee == 0``
        gives a hard cutoff.

    Returns
    -------
    np.ndarray
        Same shape as ``rgb``, containing the extracted bloom contribution.
        Pixels well below ``threshold`` are zero, pixels well above are the
        original colour, pixels inside the knee band are smoothly ramped.
    """
    rgb = np.asarray(rgb, dtype=np.float32)
    luma = rgb.max(axis=-1)

    # Hard branch: luma - threshold, clamped to >= 0
    hard = np.maximum(luma - threshold, 0.0)

    if knee <= 0.0:
        # Backward-compat hard cutoff — bypass the soft curve entirely so the
        # arithmetic is exactly the same as the legacy implementation.
        contrib = hard
    else:
        # Lottes soft branch.
        soft_in = np.clip(luma - threshold + knee, 0.0, 2.0 * knee)
        soft = (soft_in * soft_in) / (4.0 * knee + _EPS)
        contrib = np.maximum(hard, soft)

    weight = contrib / np.maximum(luma, _EPS)
    # Broadcast weight back over the colour channels.
    return rgb * weight[..., None]


class BloomPass:
    """Bloom extraction pass with Lottes 2017 smooth-knee threshold.

    Attributes
    ----------
    threshold
        Luma value above which pixels start glowing.  ``1.0`` corresponds
        to "above LDR white" for an HDR target normalised to white = 1.
    knee
        Soft-knee width.  ``0.0`` reproduces the legacy hard cutoff.
    intensity
        Scalar multiplier applied to the extracted glow before it is fed
        into the downstream blur.
    """

    label = "bloom"

    def __init__(
        self,
        threshold: float = 1.0,
        knee: float = 0.2,
        intensity: float = 1.0,
    ) -> None:
        """Construct a bloom extraction pass.

        Raises
        ------
        TypeError
            If ``threshold`` / ``knee`` / ``intensity`` are not real numbers.
        ValueError
            If any of them is NaN/inf or negative.
        """
        self.threshold = validate_non_negative_float(
            "threshold", "BloomPass", threshold,
        )
        self.knee = validate_non_negative_float(
            "knee", "BloomPass", knee,
        )
        self.intensity = validate_non_negative_float(
            "intensity", "BloomPass", intensity,
        )

    # ----------------------------------------------------------- config glue
    @classmethod
    def from_config(cls, cfg) -> "BloomPass":
        """Build a BloomPass from a global rendering config object.

        Tolerates the absence of a ``bloom`` section so legacy configs still
        work — falls back to defaults.
        """
        try:
            b = cfg.rendering.bloom
        except AttributeError:
            return cls()
        return cls(
            threshold=getattr(b, "threshold", 1.0),
            knee=getattr(b, "knee", 0.2),
            intensity=getattr(b, "intensity", 1.0),
        )

    # ----------------------------------------------------------- GPU plumbing
    def make_pass(self) -> PostProcessPass:
        """Build a PostProcessPass record for the executor.

        Layout (16 bytes, std140-compatible):
            threshold : f32   offset 0
            knee      : f32   offset 4
            intensity : f32   offset 8
            _pad      : f32   offset 12  (kept for 16-byte alignment)
        """
        raw = struct.pack(
            "<ffff",
            self.threshold,
            self.knee,
            self.intensity,
            0.0,
        )
        return PostProcessPass(
            shader_path=_SHADER,
            label=self.label,
            entry_point=_ENTRY,
            raw_params_bytes=raw,
            params={
                "threshold": self.threshold,
                "knee": self.knee,
                "intensity": self.intensity,
            },
        )

    # ----------------------------------------------------------- CPU helper
    def apply_cpu(self, rgb: np.ndarray) -> np.ndarray:
        """CPU-side reference implementation used by tests and offline tools.

        Mirrors the WGSL shader exactly so regression tests can run without
        a GPU.  Scales the extracted bloom by ``self.intensity``.
        """
        glow = smooth_threshold(rgb, self.threshold, self.knee)
        if self.intensity != 1.0:
            glow = glow * self.intensity
        return glow


def synth_hdr_strip(lumas: Iterable[float], width: int = 1) -> np.ndarray:
    """Build a single-row HDR test strip with the requested per-pixel lumas.

    Each pixel is grey (R=G=B=luma) so ``max(R,G,B) == luma`` and the
    smooth_threshold input is exactly the requested luma value.  Useful
    for the regression tests.
    """
    lumas = list(lumas)
    arr = np.zeros((1, len(lumas), 3), dtype=np.float32)
    for i, lv in enumerate(lumas):
        arr[0, i, :] = float(lv)
    if width > 1:
        arr = np.repeat(arr, width, axis=0)
    return arr
