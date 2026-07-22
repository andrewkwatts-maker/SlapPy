"""Vignette post-process pass — smooth radial falloff (round-4 polish).

Round-4 lighting/post-process work replaces the legacy hard-quadratic
edge darkening (``1 - pow(dist*strength, 2)``) with a band-limited
``smoothstep`` falloff controlled by an explicit ``inner_radius`` and
``feather`` width.  The legacy curve produced visible banding on
8-bit storage targets because the ``pow(..., 2)`` shoulder transitions
through ~10 quantisation levels in roughly two pixels of screen radius.

A ``smoothstep(a, b, dist)`` shoulder spreads the same brightness
delta across the configurable ``feather`` band, eliminating the
banding artefact.  Setting ``feather <= 0`` reproduces the legacy
curve byte-for-byte — this is the backward-compat path used by
existing scenes that do not opt in.

CPU reference
-------------
``apply_cpu`` mirrors ``shaders/vignette.wgsl`` exactly so visual
regression tests can run headless without a GPU.
"""
from __future__ import annotations

import struct
from typing import Tuple

import numpy as np

from .chain import PostProcessPass
from ._validation import (
    validate_non_negative_float,
    validate_unit_interval,
)


_SHADER = "vignette.wgsl"
_ENTRY  = "main"


# ---------------------------------------------------------------------------
# CPU reference — mirrors the WGSL shader bit-for-bit on each branch
# ---------------------------------------------------------------------------

def _legacy_factor(uv: np.ndarray, strength: float) -> np.ndarray:
    """Old hard-quadratic shoulder; kept verbatim for backward-compat tests."""
    offset = uv - 0.5
    dist = np.linalg.norm(offset, axis=-1) / np.linalg.norm([0.5, 0.5])
    return np.clip(1.0 - np.power(dist * strength, 2.0), 0.0, 1.0)


def _smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    """WGSL smoothstep — Hermite interpolation, identical to GLSL/HLSL."""
    if edge1 <= edge0:
        # Degenerate band — step function at edge0.  Matches GPU smoothstep
        # behaviour where edge0 == edge1 returns 0 below and 1 at-or-above.
        return np.where(x < edge0, 0.0, 1.0).astype(np.float32)
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _smooth_factor(
    uv: np.ndarray,
    strength: float,
    inner_radius: float,
    feather: float,
) -> np.ndarray:
    """Round-4 smoothstep shoulder; uses half-axis normalisation so the
    vignette stays circular irrespective of aspect ratio."""
    offset = uv - 0.5
    dist = np.linalg.norm(offset, axis=-1) / 0.5
    ramp = _smoothstep(inner_radius, inner_radius + feather, dist)
    return np.clip(1.0 - strength * ramp, 0.0, 1.0)


def vignette_factor(
    width: int,
    height: int,
    strength: float,
    inner_radius: float = 0.0,
    feather: float = 0.0,
) -> np.ndarray:
    """Return the per-pixel brightness scalar for a vignette pass.

    Parameters
    ----------
    width, height
        Output buffer resolution in pixels.
    strength
        Maximum darkening factor.  At ``ramp = 1`` the pixel is multiplied
        by ``1 - strength``.  ``strength = 0`` is identity, ``strength = 1``
        fully blacks the corner.
    inner_radius
        Normalised radius (0 = centre, 1 = nearest screen edge) at which
        the falloff begins.  Used only when ``feather > 0``.
    feather
        Width (in normalised radius units) of the smoothstep transition.
        ``feather <= 0`` selects the legacy ``1 - pow(d*s, 2)`` curve and
        the ``inner_radius`` argument is ignored (backward-compat path).

    Returns
    -------
    np.ndarray
        Shape ``(height, width)``, float32 in [0, 1].  Multiply the
        scene RGB by this to get the vignette result.
    """
    # Build the UV grid in the same order as the shader (texel centres).
    xs = (np.arange(width, dtype=np.float32)) / float(width)
    ys = (np.arange(height, dtype=np.float32)) / float(height)
    uv = np.stack(np.meshgrid(xs, ys, indexing="xy"), axis=-1)

    if feather <= 0.0:
        return _legacy_factor(uv, strength).astype(np.float32)
    return _smooth_factor(uv, strength, inner_radius, feather).astype(np.float32)


# ---------------------------------------------------------------------------
# VignettePass — engine-side wrapper
# ---------------------------------------------------------------------------


class VignettePass:
    """Vignette extraction pass with smoothstep radial falloff.

    Attributes
    ----------
    strength
        Peak darkening at the corner / outside the feather band.
    inner_radius
        Normalised radius at which the falloff begins.  ``0`` means the
        whole frame is rolled off; ``0.5`` keeps the middle 50 % crisp.
        Only meaningful when ``feather > 0``.
    feather
        Width of the smoothstep transition in normalised radius units.
        ``feather == 0`` selects the legacy ``pow(d*s, 2)`` shoulder
        (backward-compat).
    """

    label = "vignette"

    def __init__(
        self,
        strength: float = 1.0,
        inner_radius: float = 0.0,
        feather: float = 0.0,
    ) -> None:
        """Construct a vignette darkening pass.

        Raises
        ------
        TypeError
            If ``strength`` / ``inner_radius`` / ``feather`` are not
            real numbers.
        ValueError
            If ``strength`` is negative or NaN/inf, ``inner_radius`` is
            outside ``[0, 1]`` or NaN/inf, or ``feather`` is negative
            or NaN/inf.
        """
        self.strength = validate_non_negative_float(
            "strength", "VignettePass", strength,
        )
        self.inner_radius = validate_unit_interval(
            "inner_radius", "VignettePass", inner_radius,
        )
        self.feather = validate_non_negative_float(
            "feather", "VignettePass", feather,
        )

    @classmethod
    def from_config(cls, cfg) -> "VignettePass":
        """Build a VignettePass from a global rendering config object.

        Looks up ``cfg.rendering.vignette`` with fallback to the
        legacy ``cfg.rendering.night_vision.vignette_strength`` value
        used by the night-vision shader's vignette component.
        """
        try:
            v = cfg.rendering.vignette
        except AttributeError:
            try:
                strength = float(cfg.rendering.night_vision.vignette_strength)
            except AttributeError:
                return cls()
            return cls(strength=strength)
        return cls(
            strength=getattr(v, "strength", 1.0),
            inner_radius=getattr(v, "inner_radius", 0.0),
            feather=getattr(v, "feather", 0.0),
        )

    # ----------------------------------------------------------- GPU plumbing
    def make_pass(self) -> PostProcessPass:
        """Build a PostProcessPass record for the executor.

        Layout (32 bytes, std140-compatible):
            strength     : f32   offset  0
            width        : u32   offset  4   (executor splices the real value)
            height       : u32   offset  8
            inner_radius : f32   offset 12
            feather      : f32   offset 16
            _pad0..2     : u32×3 offset 20
        """
        # Width/height are filled by the executor; we send placeholders here.
        return PostProcessPass(
            shader_path=_SHADER,
            label=self.label,
            entry_point=_ENTRY,
            params={
                "strength":     self.strength,
                "inner_radius": self.inner_radius,
                "feather":      self.feather,
            },
        )

    # ----------------------------------------------------------- CPU helper
    def apply_cpu(self, rgb: np.ndarray) -> np.ndarray:
        """CPU-side reference implementation used by tests and offline tools.

        Mirrors the WGSL shader exactly.  Accepts ``(H, W, 3)`` or
        ``(H, W, 4)`` arrays of any dtype castable to float32; returns
        the same shape as the input.
        """
        rgb = np.asarray(rgb, dtype=np.float32)
        if rgb.ndim != 3 or rgb.shape[-1] not in (3, 4):
            raise ValueError(
                f"expected (H, W, 3) or (H, W, 4); got shape {rgb.shape!r}"
            )
        h, w = rgb.shape[:2]
        factor = vignette_factor(
            w, h, self.strength, self.inner_radius, self.feather,
        )
        out = rgb.copy()
        out[..., :3] = rgb[..., :3] * factor[..., None]
        return out

    # ----------------------------------------------------------- diagnostics
    def feather_radius_px(self, width: int, height: int) -> Tuple[float, float]:
        """Return the (inner, outer) pixel radii of the feather band.

        Useful for diagnostics and visual regression assertions that
        need to know how wide the transition zone is on a given target.
        """
        if self.feather <= 0.0:
            return (0.0, 0.0)
        # Normalised radius units use 0.5 of the smaller axis, but the
        # smoothstep is computed against ``length(offset)/0.5`` so the
        # absolute pixel radius is ``r * 0.5 * min(w, h)``.
        half_min = 0.5 * float(min(width, height))
        inner_px = self.inner_radius * half_min
        outer_px = (self.inner_radius + self.feather) * half_min
        return (inner_px, outer_px)


def synth_grey_frame(width: int, height: int, luma: float = 1.0) -> np.ndarray:
    """Build a uniformly-lit grey RGB frame for vignette regression tests.

    A flat input lets the test isolate the vignette factor — every pixel
    is multiplied by the same input value so the output is exactly the
    vignette curve scaled to the requested luma.
    """
    arr = np.full((height, width, 3), float(luma), dtype=np.float32)
    return arr
