"""Automatic exposure (auto-EV) pass — Lottes 2017 / Karis 2013 style.

The class :class:`AutoExposurePass` derives an EV (exposure stops) such that
the scene's geometric-mean luminance lands on a configurable mid-grey
(0.18 by default — the photographic 18 % grey).

The derivation runs in two phases:

1. Compute the *log-average luminance* of the input frame::

       log_avg = (1 / N) * sum_i log(max(L_i, eps))
       L_avg   = exp(log_avg)

   Using the geometric mean keeps the result stable when the frame contains a
   small number of very bright pixels (specular highlights, suns, etc.). This
   is the standard log-luminance reduction used in Reinhard 2002, Lottes 2017
   and Karis 2013.

2. Derive the EV that maps ``L_avg`` to ``target_grey``::

       derived_ev = log2(target_grey / L_avg)

3. Smooth the result across frames so the camera adapts rather than snapping::

       ev = ev * (1 - smoothing) + derived_ev * smoothing

   With ``smoothing = 0.05`` the time-constant is ~20 frames (1 - 0.05^k <= 1e-3
   at k ~ 60, but the EV settles within ~30 frames to within 0.05 stop tolerance,
   matching the standard photographic adaptation curve).

The CPU reference path (:meth:`AutoExposurePass.apply_cpu`) performs exactly
the same math the GPU shader (``auto_exposure.wgsl``) does, so unit tests can
exercise the pipeline without any GPU at all.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

# Reference luminance coefficients (BT.709 / Rec. 709 / sRGB primaries).
_LUMA_COEFFS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

# Floor on luminance before taking log, mirrors the shader's `max(L, 1e-7)`.
# Pixels below this are treated as 1e-7 nits to avoid log(0).
_LUM_FLOOR = 1e-7


class AutoExposurePass:
    """Auto-exposure pre-pass with per-frame smoothing.

    Parameters
    ----------
    target_grey
        Linear-luminance value that the geometric mean of the scene should be
        mapped to (default 0.18 — photographic mid-grey).
    smoothing
        Per-frame blend factor in ``[0, 1]``. ``0`` freezes the EV at its
        current value; ``1`` snaps instantly. Default ``0.05`` gives the
        ~20-frame adaptation envelope the Lottes 2017 paper recommends.
    min_ev, max_ev
        Hard clamp applied to the smoothed EV. The defaults
        ``[-5, +5]`` give ±5 photographic stops of latitude around manual.
    """

    def __init__(
        self,
        target_grey: float = 0.18,
        smoothing: float = 0.05,
        min_ev: float = -5.0,
        max_ev: float = 5.0,
    ) -> None:
        if not 0.0 < target_grey <= 1.0:
            raise ValueError(
                f"target_grey must be in (0, 1]; got {target_grey!r}"
            )
        if not 0.0 <= smoothing <= 1.0:
            raise ValueError(
                f"smoothing must be in [0, 1]; got {smoothing!r}"
            )
        if min_ev >= max_ev:
            raise ValueError(
                f"min_ev ({min_ev}) must be < max_ev ({max_ev})"
            )

        self.target_grey: float = float(target_grey)
        self.smoothing: float = float(smoothing)
        self.min_ev: float = float(min_ev)
        self.max_ev: float = float(max_ev)

        # Per-frame state: the smoothed EV from the previous frame.
        # ``None`` means "uninitialised — accept whatever the next frame says
        # verbatim"; after the first :meth:`apply_cpu` it becomes a float.
        self._smoothed_ev: Optional[float] = None

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset the smoothing state.

        After calling, the next :meth:`apply_cpu` produces an EV computed
        purely from its input frame, with no influence from prior frames.
        """
        self._smoothed_ev = None

    @property
    def current_ev(self) -> float:
        """The most recently smoothed EV (0.0 if no frame has been processed)."""
        return 0.0 if self._smoothed_ev is None else self._smoothed_ev

    # ------------------------------------------------------------------
    # CPU reference path
    # ------------------------------------------------------------------

    def _log_average_luminance(self, image: np.ndarray) -> float:
        """Geometric mean of scene luminance, computed via log-average.

        Formula::

            log_avg = (1 / N) * sum_i log(max(L_i, 1e-7))
            L_avg   = exp(log_avg)

        ``image`` may be ``(H, W, 3)``, ``(H, W, 4)`` (alpha ignored) or
        ``(H, W)`` (treated as already-luminance).
        """
        if image.ndim == 2:
            lum = np.asarray(image, dtype=np.float32)
        elif image.ndim == 3 and image.shape[2] in (3, 4):
            rgb = np.asarray(image[..., :3], dtype=np.float32)
            lum = rgb @ _LUMA_COEFFS
        else:
            raise ValueError(
                "image must be (H,W), (H,W,3) or (H,W,4); "
                f"got shape {image.shape!r}"
            )
        lum = np.maximum(lum, _LUM_FLOOR)
        log_avg = float(np.mean(np.log(lum)))
        return math.exp(log_avg)

    def _derive_ev(self, l_avg: float) -> float:
        """Map the geometric-mean luminance to an EV stop offset."""
        # log2(target / l_avg) — the EV that scales l_avg up/down to target.
        l_avg = max(l_avg, _LUM_FLOOR)
        return math.log2(self.target_grey / l_avg)

    def apply_cpu(self, image: np.ndarray) -> float:
        """Compute the smoothed, clamped EV for a single frame.

        Parameters
        ----------
        image
            Scene-linear HDR image as a NumPy array. Accepts ``(H, W)``
            (already-luminance), ``(H, W, 3)`` RGB, or ``(H, W, 4)`` RGBA.

        Returns
        -------
        float
            The EV (exposure stops) to feed into the tonemap params for this
            frame, after smoothing against prior frames and clamping to
            ``[min_ev, max_ev]``.
        """
        l_avg = self._log_average_luminance(image)
        derived_ev = self._derive_ev(l_avg)

        if self._smoothed_ev is None:
            smoothed = derived_ev
        else:
            smoothed = (
                self._smoothed_ev * (1.0 - self.smoothing)
                + derived_ev * self.smoothing
            )

        # Clamp last so the smoothing curve itself is monotonic.
        clamped = max(self.min_ev, min(self.max_ev, smoothed))
        self._smoothed_ev = clamped
        return clamped
