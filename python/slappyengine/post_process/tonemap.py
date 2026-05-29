"""TonemapPass — Python wrapper around ``tonemap.wgsl`` with optional auto-EV.

The bare WGSL pass (``tonemap.wgsl``) is driven from
:meth:`PostProcessExecutor._make_params_buffer`. This class exists so callers
can:

* configure the manual ``exposure_ev`` knob + colour-grading parameters in one
  place, and
* optionally hand in an :class:`AutoExposurePass` whose per-frame derived EV
  overrides the manual value.

When ``auto_ev`` is ``None`` (the default) the behaviour is byte-for-byte
identical to constructing :class:`PostProcessPass` with ``shader_path="tonemap.wgsl"``
directly — that is the backward-compat contract enforced by
``test_backward_compat_no_auto_ev_unchanged``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from .auto_exposure import AutoExposurePass
from .chain import PostProcessPass


@dataclass
class TonemapPass:
    """Tone-mapping + colour-grading pass with optional auto-EV.

    Parameters
    ----------
    exposure_ev
        Manual EV stop offset. Used as-is when ``auto_ev`` is ``None``.
        Ignored (replaced) when ``auto_ev`` is supplied and
        :meth:`derive_exposure_ev` has been called for the current frame.
    mode
        ``0`` = ACES filmic (default), ``1`` = Reinhard.
    saturation, contrast
        Standard colour-grading knobs; defaults are identity (1.0).
    lift, gain, gamma
        Per-channel shadow / highlight / midtone control.
    auto_ev
        Optional :class:`AutoExposurePass`. When provided, call
        :meth:`derive_exposure_ev` once per frame with the scene-linear HDR
        image, and the next call to :meth:`make_pass` will pick up the
        derived value automatically.
    """

    exposure_ev: float = 0.0
    mode: int = 0
    saturation: float = 1.0
    contrast: float = 1.0
    lift: tuple[float, float, float] = (0.0, 0.0, 0.0)
    gain: tuple[float, float, float] = (1.0, 1.0, 1.0)
    gamma: float = 1.0
    auto_ev: Optional[AutoExposurePass] = None
    label: str = "tonemap"

    # The most recently derived EV (set by :meth:`derive_exposure_ev`).
    # ``None`` means "use the manual ``exposure_ev`` field". This is kept
    # separate from the field so backward-compat callers never see auto-EV.
    _derived_ev: Optional[float] = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------
    # Auto-EV plumbing
    # ------------------------------------------------------------------

    def derive_exposure_ev(self, image: np.ndarray) -> float:
        """Run the auto-exposure CPU path against ``image``.

        Stores the result internally so :meth:`make_pass` / :meth:`params`
        return the auto-derived EV on the next read.

        Raises
        ------
        RuntimeError
            If called without an ``auto_ev`` instance attached.
        """
        if self.auto_ev is None:
            raise RuntimeError(
                "TonemapPass.derive_exposure_ev() called without an auto_ev "
                "instance; set tonemap_pass.auto_ev = AutoExposurePass(...) first."
            )
        ev = self.auto_ev.apply_cpu(image)
        self._derived_ev = ev
        return ev

    @property
    def effective_ev(self) -> float:
        """The EV that will be sent to the shader on the next frame."""
        if self.auto_ev is not None and self._derived_ev is not None:
            return self._derived_ev
        return self.exposure_ev

    # ------------------------------------------------------------------
    # PostProcessPass interop
    # ------------------------------------------------------------------

    def params(self) -> dict[str, Any]:
        """The full param dict the executor's tonemap branch consumes."""
        return {
            "exposure_ev": self.effective_ev,
            "mode": int(self.mode),
            "saturation": float(self.saturation),
            "contrast": float(self.contrast),
            "lift_r": float(self.lift[0]),
            "lift_g": float(self.lift[1]),
            "lift_b": float(self.lift[2]),
            "gain_r": float(self.gain[0]),
            "gain_g": float(self.gain[1]),
            "gain_b": float(self.gain[2]),
            "gamma": float(self.gamma),
        }

    def make_pass(self) -> PostProcessPass:
        """Build the :class:`PostProcessPass` the executor will run."""
        return PostProcessPass(
            shader_path="tonemap.wgsl",
            params=self.params(),
            label=self.label,
            entry_point="tonemap_main",
        )
