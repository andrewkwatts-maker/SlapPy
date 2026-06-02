"""Outline post-process pass — Sobel-magnitude smooth threshold (round-5 polish).

Audit observation that drove this round
---------------------------------------
The pre-round-5 outline shader (``shaders/outline.wgsl`` HEAD before this
commit) used a 4-cardinal-neighbour binary alpha test::

    edge = (center.a >= T) AND (any cardinal neighbour.a < T)

That formulation has two problems:

1. **Hard cutoff / popping.**  Any silhouette whose per-pixel alpha
   drifts across ``T`` between frames pops the outline on and off
   frame-by-frame.  This is the same banding-class artefact that
   round 3 (Lottes bloom) and round 4 (smoothstep vignette) replaced
   on other passes — the outline still had the binary cliff on master.

2. **Wrong bind layout.**  The shader declared a fourth binding (a
   sampler at ``@group(0) @binding(2)``) that ``PostProcessExecutor``
   never bound, so the GPU path was effectively broken.  The new shader
   uses the 3-binding convention that matches the rest of the chain.

Round 5 replaces the binary test with a proper 3x3 Sobel-magnitude
edge detector and a ``smoothstep(T - softness, T + softness, mag)``
shoulder.  The legacy 4-cardinal binary path is preserved verbatim
when ``use_sobel=False`` AND ``softness <= 0`` (backward-compat flag).

CPU reference
-------------
``OutlinePass.apply_cpu`` mirrors ``shaders/outline.wgsl`` exactly so
visual-regression tests can run headless without a GPU.

Backward compatibility
----------------------
``add_outline(...)`` on :class:`PostProcessChain` accepts the new
``softness`` and ``use_sobel`` keyword arguments.  When they are
absent (or set to their legacy defaults of ``0.0`` and ``False``),
the shader runs the original 4-neighbour binary path bit-for-bit.
"""
from __future__ import annotations

import struct
from typing import Tuple

import numpy as np

from .chain import PostProcessPass
from ._pass_base import PostProcessPassBase


_SHADER = "outline.wgsl"
_ENTRY  = "main"


# ---------------------------------------------------------------------------
# CPU reference — mirrors shaders/outline.wgsl on each branch
# ---------------------------------------------------------------------------

def _sample_a_clamped(alpha: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Sample alpha with edge-clamp addressing (matches `sample_a` in WGSL)."""
    h, w = alpha.shape
    xc = np.clip(x, 0, w - 1)
    yc = np.clip(y, 0, h - 1)
    return alpha[yc, xc]


def _smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    """WGSL smoothstep — Hermite interpolation, identical to GLSL/HLSL.

    WGSL spec: when ``edge0 == edge1`` the result is implementation-defined;
    we use the convention "step function at edge0" which matches modern
    Vulkan/Metal/D3D drivers.
    """
    if edge1 <= edge0:
        return np.where(x < edge0, 0.0, 1.0).astype(np.float32)
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0).astype(np.float32)
    return t * t * (3.0 - 2.0 * t)


def edge_factor_cardinal(
    alpha: np.ndarray,
    threshold: float,
    softness: float,
) -> np.ndarray:
    """Legacy 4-cardinal-neighbour edge factor (with optional softness).

    Parameters
    ----------
    alpha
        ``(H, W)`` float32 alpha channel.
    threshold
        Alpha threshold; pixels at or above this are considered "interior".
    softness
        ``<= 0`` selects the binary legacy path; ``> 0`` blends the
        per-neighbour gap through ``smoothstep(-softness, +softness, gap)``.

    Returns
    -------
    ``(H, W)`` float32 in ``[0, 1]``.
    """
    h, w = alpha.shape
    xs = np.arange(w, dtype=np.int64)
    ys = np.arange(h, dtype=np.int64)
    xg, yg = np.meshgrid(xs, ys, indexing="xy")

    center = alpha
    n_up    = _sample_a_clamped(alpha, xg,     yg - 1)
    n_down  = _sample_a_clamped(alpha, xg,     yg + 1)
    n_left  = _sample_a_clamped(alpha, xg - 1, yg)
    n_right = _sample_a_clamped(alpha, xg + 1, yg)

    # Per-neighbour gap relative to the threshold; positive means the
    # neighbour is *below* the threshold (which makes this an edge pixel).
    gap = np.maximum.reduce([
        threshold - n_up,
        threshold - n_down,
        threshold - n_left,
        threshold - n_right,
    ]).astype(np.float32)

    interior = (center >= threshold).astype(np.float32)
    if softness <= 0.0:
        # Original binary cliff.
        binary = (gap > 0.0).astype(np.float32)
        return (interior * binary).astype(np.float32)
    return (interior * _smoothstep(-softness, softness, gap)).astype(np.float32)


def edge_factor_sobel(
    alpha: np.ndarray,
    threshold: float,
    softness: float,
) -> np.ndarray:
    """Sobel-magnitude edge factor (round-5 default).

    A 3x3 Sobel filter on the alpha channel produces a smooth gradient
    magnitude proportional to the local edge strength.  The threshold
    then selects "what counts as an edge", and ``softness`` controls
    the width of the smoothstep shoulder used to anti-alias the cliff.

    Parameters
    ----------
    alpha
        ``(H, W)`` float32 alpha channel.
    threshold
        Sobel magnitude cutoff (typical range 0.1 .. 2.0 for unit alpha).
    softness
        Half-width of the smoothstep transition centred at ``threshold``.
        ``<= 0`` selects a binary cliff; ``> 0`` produces a soft outline.

    Returns
    -------
    ``(H, W)`` float32 in ``[0, 1]``.
    """
    h, w = alpha.shape
    xs = np.arange(w, dtype=np.int64)
    ys = np.arange(h, dtype=np.int64)
    xg, yg = np.meshgrid(xs, ys, indexing="xy")

    a00 = _sample_a_clamped(alpha, xg - 1, yg - 1)
    a10 = _sample_a_clamped(alpha, xg,     yg - 1)
    a20 = _sample_a_clamped(alpha, xg + 1, yg - 1)
    a01 = _sample_a_clamped(alpha, xg - 1, yg)
    a21 = _sample_a_clamped(alpha, xg + 1, yg)
    a02 = _sample_a_clamped(alpha, xg - 1, yg + 1)
    a12 = _sample_a_clamped(alpha, xg,     yg + 1)
    a22 = _sample_a_clamped(alpha, xg + 1, yg + 1)

    gx = (a20 + 2.0 * a21 + a22) - (a00 + 2.0 * a01 + a02)
    gy = (a02 + 2.0 * a12 + a22) - (a00 + 2.0 * a10 + a20)
    mag = np.sqrt(gx * gx + gy * gy).astype(np.float32)

    if softness <= 0.0:
        return (mag >= threshold).astype(np.float32)
    return _smoothstep(threshold - softness, threshold + softness, mag)


# ---------------------------------------------------------------------------
# OutlinePass — engine-side wrapper
# ---------------------------------------------------------------------------


class OutlinePass(PostProcessPassBase):
    """Outline edge pass with Sobel-magnitude + smoothstep falloff.

    Parameters
    ----------
    color
        ``(r, g, b, a)`` tuple in linear ``[0, 1]``.  ``a`` is used as
        the per-pixel blend weight for the edge composite, so a value
        below 1 produces a partially transparent outline.
    threshold
        Edge cutoff.  In ``use_sobel=False`` mode this is the alpha
        threshold (in ``[0, 1]``).  In ``use_sobel=True`` mode this is
        the Sobel-magnitude cutoff (typical range ``0.1`` .. ``2.0``).
    softness
        Half-width of the smoothstep transition around ``threshold``.
        Default ``0.0`` reproduces the pre-round-5 binary cliff (legacy
        backward-compat).
    use_sobel
        ``False`` (default) keeps the legacy 4-cardinal-neighbour
        binary path for backward-compat; ``True`` enables the round-5
        Sobel-magnitude detector.
    """

    label = "outline"

    # ----- PostProcessPassBase declarative schema -----
    SHADER = _SHADER
    ENTRY = _ENTRY
    CONFIG_KEY = None  # overridden ``from_config`` handles colour tuple coercion

    def __init__(
        self,
        color: Tuple[float, float, float, float] = (1.0, 0.0, 0.0, 1.0),
        threshold: float = 0.1,
        softness: float = 0.0,
        use_sobel: bool = False,
    ) -> None:
        if len(color) != 4:
            raise ValueError(f"color must be a length-4 RGBA tuple, got {color!r}")
        if threshold < 0.0:
            raise ValueError(f"threshold must be >= 0, got {threshold!r}")
        if softness < 0.0:
            raise ValueError(f"softness must be >= 0, got {softness!r}")
        self.color = tuple(float(c) for c in color)
        self.threshold = float(threshold)
        self.softness = float(softness)
        self.use_sobel = bool(use_sobel)

    @classmethod
    def from_config(cls, cfg) -> "OutlinePass":
        """Build an OutlinePass from a global rendering config object.

        Looks up ``cfg.rendering.outline`` and copies recognised fields;
        falls back to defaults when the section is absent.
        """
        try:
            o = cfg.rendering.outline
        except AttributeError:
            return cls()
        color = tuple(getattr(o, "color", (1.0, 0.0, 0.0, 1.0)))
        return cls(
            color=color,  # type: ignore[arg-type]
            threshold=getattr(o, "threshold", 0.1),
            softness=getattr(o, "softness", 0.0),
            use_sobel=getattr(o, "use_sobel", False),
        )

    # ----------------------------------------------------------- GPU plumbing
    def params_dict(self) -> dict:
        """Per-pass params dict consumed by the executor's UBO packer.

        The uniform layout (48 bytes, std140-compatible)::

            outline_r   : f32   offset  0
            outline_g   : f32   offset  4
            outline_b   : f32   offset  8
            outline_a   : f32   offset 12
            threshold   : f32   offset 16
            softness    : f32   offset 20
            use_sobel   : u32   offset 24
            _pad0       : u32   offset 28
            width       : u32   offset 32  (filled by executor)
            height      : u32   offset 36
            _pad1, _pad2: u32   offset 40, 44
        """
        return {
            "outline_r": self.color[0],
            "outline_g": self.color[1],
            "outline_b": self.color[2],
            "outline_a": self.color[3],
            "threshold": self.threshold,
            "softness":  self.softness,
            "use_sobel": int(self.use_sobel),
        }

    # NOTE: ``make_pass`` is inherited from :class:`PostProcessPassBase`.

    # ----------------------------------------------------------- CPU helper
    def apply_cpu(self, rgba: np.ndarray) -> np.ndarray:
        """CPU reference; mirrors ``shaders/outline.wgsl`` exactly.

        Parameters
        ----------
        rgba
            ``(H, W, 4)`` float32 array in linear ``[0, 1]``.

        Returns
        -------
        ``(H, W, 4)`` float32 array with the outline composited on top
        of the input.  For the legacy hard-cutoff path
        (``softness <= 0`` and ``use_sobel=False``) edge pixels are
        replaced by ``self.color`` byte-for-byte against the GPU.
        """
        rgba = np.asarray(rgba, dtype=np.float32)
        if rgba.ndim != 3 or rgba.shape[-1] != 4:
            raise ValueError(
                f"expected (H, W, 4) RGBA, got shape {rgba.shape!r}"
            )
        alpha = rgba[..., 3]
        if self.use_sobel:
            edge = edge_factor_sobel(alpha, self.threshold, self.softness)
        else:
            edge = edge_factor_cardinal(alpha, self.threshold, self.softness)

        blend = (edge * self.color[3]).astype(np.float32)[..., None]
        out_col = np.array(self.color, dtype=np.float32)
        out = rgba.copy()
        out[..., :3] = rgba[..., :3] * (1.0 - blend) + out_col[:3] * blend
        out[..., 3:4] = rgba[..., 3:4] * (1.0 - blend) + out_col[3] * blend
        return out


# ---------------------------------------------------------------------------
# Test-side helpers
# ---------------------------------------------------------------------------

def synth_disc_alpha(width: int, height: int, radius: float | None = None) -> np.ndarray:
    """Build a centred opaque disc on a transparent background.

    Returns an ``(H, W, 4)`` RGBA float32 frame whose alpha channel
    contains a soft disc (linear roll-off across one pixel) — the
    simplest test shape that exercises both the cardinal and Sobel
    edge detectors symmetrically.
    """
    if radius is None:
        radius = 0.3 * min(width, height)
    xs = np.arange(width, dtype=np.float32) - 0.5 * (width - 1)
    ys = np.arange(height, dtype=np.float32) - 0.5 * (height - 1)
    xg, yg = np.meshgrid(xs, ys, indexing="xy")
    dist = np.sqrt(xg * xg + yg * yg)
    # 1-pixel-wide linear roll-off so the edge has a controllable
    # alpha gradient — this is critical for the smoothstep tests.
    alpha = np.clip(radius - dist + 0.5, 0.0, 1.0).astype(np.float32)
    rgba = np.zeros((height, width, 4), dtype=np.float32)
    rgba[..., 0] = 1.0  # solid red interior
    rgba[..., 3] = alpha
    return rgba
