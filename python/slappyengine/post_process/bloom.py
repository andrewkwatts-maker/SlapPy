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

    # Valid string values for ``upsample_mode``.  Kept module-side to make
    # the regression tests' allow-list explicit.
    UPSAMPLE_MODES = ("tent9", "karis13")

    def __init__(
        self,
        threshold: float = 1.0,
        knee: float = 0.2,
        intensity: float = 1.0,
        upsample_mode: str = "tent9",
    ) -> None:
        """Construct a bloom extraction pass.

        Parameters
        ----------
        threshold, knee, intensity
            Standard Lottes smooth-threshold parameters (see class docstring).
        upsample_mode
            Pyramid upsample kernel selection.  ``"tent9"`` (default) uses
            the 9-tap 3×3 progressive tent (back-compat with existing
            chains).  ``"karis13"`` uses the wider 13-tap Karis upsample,
            matching the partial-Karis 13-tap downsample for higher-quality
            progressive blur.

        Raises
        ------
        TypeError
            If ``threshold`` / ``knee`` / ``intensity`` are not real numbers,
            or ``upsample_mode`` is not a ``str``.
        ValueError
            If any numeric kwarg is NaN/inf or negative, or
            ``upsample_mode`` is not one of ``UPSAMPLE_MODES``.
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
        if not isinstance(upsample_mode, str):
            raise TypeError(
                f"BloomPass: upsample_mode must be a str; "
                f"got {type(upsample_mode).__name__}"
            )
        if upsample_mode not in self.UPSAMPLE_MODES:
            raise ValueError(
                f"BloomPass: upsample_mode must be one of "
                f"{self.UPSAMPLE_MODES!r}; got {upsample_mode!r}"
            )
        self.upsample_mode = upsample_mode

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
            upsample_mode=getattr(b, "upsample_mode", "tent9"),
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


# ---------------------------------------------------------------------------
# Bloom pyramid kernels — COD 2014 / Jimenez 13-tap downsample + 9-tap tent
# upsample.  CPU reference for ``shaders/bloom_pyramid.wgsl``.
# ---------------------------------------------------------------------------


# 9-tap 3×3 tent upsample weights (corners 1, edges 2, centre 4; sum = 16).
# Identical to the COD "progressive upsample tent" used after the downsample
# pyramid is built.  Used both as the upsample kernel and as the building
# block for the 13-tap downsample (overlapping 2×2 quad averages).
_TENT_3X3 = np.array(
    [
        [1.0, 2.0, 1.0],
        [2.0, 4.0, 2.0],
        [1.0, 2.0, 1.0],
    ],
    dtype=np.float32,
) / 16.0


def _luma709(rgb: np.ndarray) -> np.ndarray:
    """BT.709 luma — matches the WGSL ``luma()`` helper."""
    return (
        rgb[..., 0] * 0.2126
        + rgb[..., 1] * 0.7152
        + rgb[..., 2] * 0.0722
    )


def _clamp_edge(rgb: np.ndarray, y: int, x: int) -> np.ndarray:
    """Clamp-to-edge fetch — mirrors ``fetch()`` in the WGSL pyramid shader."""
    h, w = rgb.shape[:2]
    yy = max(0, min(h - 1, y))
    xx = max(0, min(w - 1, x))
    return rgb[yy, xx]


def downsample_mn13(rgb: np.ndarray, karis_clamp: bool = False) -> np.ndarray:
    """COD 2014 13-tap bloom downsample (CPU reference).

    Half-resolution reduction of ``rgb`` using the 13-tap "partial-Karis"
    arrangement from Jorge Jimenez's Advanced Warfare bloom pyramid.  The
    inner quad (J,K,L,M) carries 0.5 weight and the four overlapping outer
    quads carry 0.125 each (summing to 0.5) — total spatial weight is 1.0,
    so a constant input yields a constant output (when ``karis_clamp`` is
    off).

    Parameters
    ----------
    rgb
        ``(H, W, 3)`` float array.  ``H`` and ``W`` need not be even —
        odd input is clamped at the edge.
    karis_clamp
        When ``True``, applies per-quad ``1/(1+luma(avg))`` firefly
        suppression — the same partial-Karis trick used in the COD 2014
        bloom pyramid to keep a single super-bright pixel from dominating
        the partial average.  Use this for the **first downsample level**
        only (where HDR fireflies live); subsequent levels should use the
        unclamped pure low-pass so the kernel stays linear.  Defaults to
        ``False`` for a pure low-pass that preserves constants exactly.

    Returns
    -------
    np.ndarray
        ``(H//2, W//2, 3)`` float array.

    Notes
    -----
    Compared to the legacy 2×2 box downsample this kernel concentrates the
    same total energy into a smoother low-pass — an isolated bright pixel
    is smeared into a wider Gaussian-shaped lobe instead of a hard 2×2
    block, which dramatically reduces aliasing on bright sub-pixel
    features (sparks, muzzle flashes, emissive trim).
    """
    rgb = np.asarray(rgb, dtype=np.float32)
    if rgb.ndim != 3 or rgb.shape[-1] != 3:
        raise ValueError(
            f"downsample_mn13 expects (H, W, 3) RGB, got shape {rgb.shape!r}"
        )
    h, w = rgb.shape[:2]
    dh, dw = max(1, h // 2), max(1, w // 2)
    out = np.zeros((dh, dw, 3), dtype=np.float32)

    for dy in range(dh):
        for dx in range(dw):
            cx = dx * 2
            cy = dy * 2

            # Outer 3×3 at ±2px offsets (A..I).
            A = _clamp_edge(rgb, cy - 2, cx - 2)
            B = _clamp_edge(rgb, cy - 2, cx)
            C = _clamp_edge(rgb, cy - 2, cx + 2)
            D = _clamp_edge(rgb, cy,     cx - 2)
            E = _clamp_edge(rgb, cy,     cx)
            F = _clamp_edge(rgb, cy,     cx + 2)
            G = _clamp_edge(rgb, cy + 2, cx - 2)
            H = _clamp_edge(rgb, cy + 2, cx)
            I = _clamp_edge(rgb, cy + 2, cx + 2)

            # Inner 2×2 at ±1px offsets (J,K,L,M).
            J = _clamp_edge(rgb, cy - 1, cx - 1)
            K = _clamp_edge(rgb, cy - 1, cx + 1)
            L = _clamp_edge(rgb, cy + 1, cx - 1)
            M = _clamp_edge(rgb, cy + 1, cx + 1)

            inner = (J + K + L + M) * 0.25
            q_tl = (A + B + D + E) * 0.25
            q_tr = (B + C + E + F) * 0.25
            q_bl = (D + E + G + H) * 0.25
            q_br = (E + F + H + I) * 0.25

            if karis_clamp:
                # Partial-Karis firefly suppression: each quad gets its own
                # 1/(1+luma) tone-map so a single super-bright tap can't
                # smear across the destination.  This is a non-linear
                # operation — it breaks the partition-of-unity by design.
                iw = 1.0 / (1.0 + float(_luma709(inner[None, None, :])[0, 0]))
                w_tl = 1.0 / (1.0 + float(_luma709(q_tl[None, None, :])[0, 0]))
                w_tr = 1.0 / (1.0 + float(_luma709(q_tr[None, None, :])[0, 0]))
                w_bl = 1.0 / (1.0 + float(_luma709(q_bl[None, None, :])[0, 0]))
                w_br = 1.0 / (1.0 + float(_luma709(q_br[None, None, :])[0, 0]))

                inner_contrib = inner * iw
                outer = (
                    q_tl * w_tl + q_tr * w_tr + q_bl * w_bl + q_br * w_br
                ) * 0.125
                out[dy, dx] = inner_contrib * 0.5 + outer
            else:
                # Pure linear low-pass — weights sum to exactly 1.0.
                outer = (q_tl + q_tr + q_bl + q_br) * 0.125
                out[dy, dx] = inner * 0.5 + outer

    return out


# ---------------------------------------------------------------------------
# 13-tap Karis upsample weights — Karis SIGGRAPH 2013 / COD AW 2014 companion
# to the 13-tap Mitchell-Netravali downsample.
#
# Layout (relative to the destination pixel mapped back into low-res):
#
#         . . O . . . O . .
#         . . . . . . . . .
#         O . D . C . D . O
#         . . . . . . . . .
#         . . C . X . C . .          X = centre tap     (1)
#         . . . . . . . . .          C = inner cardinal (4)  at ±1 cardinal
#         O . D . C . D . O          D = inner diagonal (4)  at ±1 diagonal
#         . . . . . . . . .          O = outer cardinal (4)  at ±2 cardinal
#         . . O . . . O . .
#
# This is a 13-tap separable-Gaussian-flavoured kernel: 1 central + 4 inner
# cardinal + 4 inner diagonal + 4 outer cardinal.  Weights are sampled from
# a Gaussian with σ = 1.0 at integer offsets and then normalised to sum to
# exactly 1.0 so a constant input yields a constant output.  Per Karis 2013
# the central tap is the highest-weighted (no ring tap exceeds it), giving
# the progressive upsample its Gaussian-shaped lobe character — wider and
# smoother than the 9-tap tent without ringing.
#
# The 4× bilinear arrangement for the outer ring is encoded by sampling the
# outer ring at ±2 cardinal offsets (the bilinear-equivalent footprint of a
# 2×2 quad at ±1.5 in higher-resolution terms, but our low-res input is
# already at 0.5× resolution so ±2 cardinal in low-res = ±1 cardinal at the
# half-res target).
_KARIS13_SIGMA = 1.0
def _gauss(r2: float, sigma: float = _KARIS13_SIGMA) -> float:
    """Gaussian at squared-radius ``r2`` with stdev ``sigma``."""
    return float(np.exp(-0.5 * r2 / (sigma * sigma)))


# Raw (unnormalised) weights for the four tap classes.
_KARIS13_RAW_CENTRE       = _gauss(0.0)                          # r = 0
_KARIS13_RAW_INNER_CARD   = _gauss(1.0)                          # r = 1
_KARIS13_RAW_INNER_DIAG   = _gauss(2.0)                          # r = sqrt(2)
_KARIS13_RAW_OUTER_CARD   = _gauss(4.0)                          # r = 2

# Normalisation factor so the 13 taps sum to exactly 1.0.
_KARIS13_NORM = (
    1.0 * _KARIS13_RAW_CENTRE
    + 4.0 * _KARIS13_RAW_INNER_CARD
    + 4.0 * _KARIS13_RAW_INNER_DIAG
    + 4.0 * _KARIS13_RAW_OUTER_CARD
)
KARIS13_W_CENTRE       = _KARIS13_RAW_CENTRE     / _KARIS13_NORM
KARIS13_W_INNER_CARD   = _KARIS13_RAW_INNER_CARD / _KARIS13_NORM
KARIS13_W_INNER_DIAG   = _KARIS13_RAW_INNER_DIAG / _KARIS13_NORM
KARIS13_W_OUTER_CARD   = _KARIS13_RAW_OUTER_CARD / _KARIS13_NORM


# Tap offsets — (dy, dx, class).  Kept in module scope so the WGSL shader and
# the CPU helper can both reference identical positions.
_KARIS13_TAPS: tuple[tuple[int, int, str], ...] = (
    ( 0,  0, "C"),  # centre
    (-1,  0, "IC"), ( 1,  0, "IC"), ( 0, -1, "IC"), ( 0,  1, "IC"),  # inner cardinal
    (-1, -1, "ID"), (-1,  1, "ID"), ( 1, -1, "ID"), ( 1,  1, "ID"),  # inner diagonal
    (-2,  0, "OC"), ( 2,  0, "OC"), ( 0, -2, "OC"), ( 0,  2, "OC"),  # outer cardinal
)
_KARIS13_CLASS_WEIGHT: dict[str, float] = {
    "C":  KARIS13_W_CENTRE,
    "IC": KARIS13_W_INNER_CARD,
    "ID": KARIS13_W_INNER_DIAG,
    "OC": KARIS13_W_OUTER_CARD,
}


def upsample_karis13(
    low: np.ndarray,
    dst_shape: tuple[int, int],
    alpha: float = 1.0,
) -> np.ndarray:
    """13-tap Karis bloom upsample (CPU reference).

    Companion to :func:`downsample_mn13`.  Doubles the resolution of ``low``
    to ``dst_shape`` using a 13-tap Gaussian-flavoured kernel — 1 central tap
    + 4 inner cardinal + 4 inner diagonal + 4 outer cardinal — with weights
    sampled from a Gaussian (σ = 1.0) and normalised to exactly 1.0.  This
    is the high-quality progressive-upsample variant from Karis SIGGRAPH
    2013 / COD AW 2014, matching the partial-Karis 13-tap downsample.

    Parameters
    ----------
    low
        ``(Hl, Wl, 3)`` float array — the low-res mip being upsampled.
    dst_shape
        ``(H, W)`` of the destination.  Typically ``(2*Hl, 2*Wl)``.
    alpha
        Optional intensity multiplier applied after the 13-tap blend.  The
        default of ``1.0`` preserves the partition-of-unity so a constant
        input yields a constant output.  Values < 1 dim the upsample;
        values > 1 brighten it.  Negative ``alpha`` is rejected — that
        would invert the bloom which is never the intent.

    Returns
    -------
    np.ndarray
        ``(H, W, 3)`` float array.

    Notes
    -----
    Compared to the 9-tap tent upsample, the 13-tap Karis kernel has a
    wider spatial support (radius 2 instead of 1) and a steeper centre
    weight, so an isolated bright low-res tap is smeared into a softer,
    rounder Gaussian-shaped lobe at the destination — fewer visible
    pyramid steps when the bloom mip chain is composited progressively.
    """
    low = np.asarray(low, dtype=np.float32)
    if low.ndim != 3 or low.shape[-1] != 3:
        raise ValueError(
            f"upsample_karis13 expects (H, W, 3) RGB, got shape {low.shape!r}"
        )
    if not np.isfinite(alpha):
        raise ValueError(f"upsample_karis13: alpha must be finite; got {alpha!r}")
    if alpha < 0.0:
        raise ValueError(f"upsample_karis13: alpha must be >= 0; got {alpha!r}")
    dh, dw = dst_shape
    out = np.zeros((dh, dw, 3), dtype=np.float32)
    a = float(alpha)

    for y in range(dh):
        for x in range(dw):
            sy = y // 2
            sx = x // 2
            acc = np.zeros(3, dtype=np.float32)
            for dy_, dx_, cls in _KARIS13_TAPS:
                w = _KARIS13_CLASS_WEIGHT[cls]
                acc += w * _clamp_edge(low, sy + dy_, sx + dx_)
            out[y, x] = acc * a

    return out


def upsample_tent9(low: np.ndarray, dst_shape: tuple[int, int]) -> np.ndarray:
    """9-tap 3×3 tent bloom upsample (CPU reference).

    Doubles the resolution of ``low`` to ``dst_shape``, sampling the low-res
    image with the COD 2014 progressive-upsample tent kernel.  The 9-tap
    weights (corners 1, edges 2, centre 4; sum = 16) sum to exactly 1.0,
    so a constant input yields a constant output.

    Parameters
    ----------
    low
        ``(Hl, Wl, 3)`` float array — the low-res mip we are upsampling.
    dst_shape
        ``(H, W)`` of the destination.  Typically ``(2*Hl, 2*Wl)``.

    Returns
    -------
    np.ndarray
        ``(H, W, 3)`` float array.

    Notes
    -----
    A single bilinear tap (the previous default) smears bright pixels into
    a box-shaped lobe; the 9-tap tent gives a smooth Gaussian-shaped lobe
    that survives subsequent additive composition without ringing.
    """
    low = np.asarray(low, dtype=np.float32)
    if low.ndim != 3 or low.shape[-1] != 3:
        raise ValueError(
            f"upsample_tent9 expects (H, W, 3) RGB, got shape {low.shape!r}"
        )
    dh, dw = dst_shape
    out = np.zeros((dh, dw, 3), dtype=np.float32)

    for y in range(dh):
        for x in range(dw):
            sy = y // 2
            sx = x // 2
            acc = np.zeros(3, dtype=np.float32)
            for ky in range(3):
                for kx in range(3):
                    weight = _TENT_3X3[ky, kx]
                    acc += weight * _clamp_edge(low, sy + ky - 1, sx + kx - 1)
            out[y, x] = acc

    return out


def downsample_box2(rgb: np.ndarray) -> np.ndarray:
    """Legacy 2×2 box downsample — kept for regression / PSNR comparisons.

    Returns a (H//2, W//2, 3) array where each output pixel is the mean of
    the corresponding 2×2 input block.  Reproduces the pre-Mitchell-Netravali
    behaviour bit-for-bit.
    """
    rgb = np.asarray(rgb, dtype=np.float32)
    h, w = rgb.shape[:2]
    dh, dw = h // 2, w // 2
    # Crop to even dims, then reshape-and-mean.
    cropped = rgb[: dh * 2, : dw * 2]
    return cropped.reshape(dh, 2, dw, 2, 3).mean(axis=(1, 3))


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
