"""Animation curve primitive — keyframe-driven scalar over normalised time.

A :class:`Keyframe` carries a normalised time ``t`` in ``[0, 1]`` and a
plain ``float`` value. An :class:`AnimationCurve` bundles a list of
keyframes with a wall-clock ``duration_s`` so the scheduler can both
sample interpolated values and decide when a curve has retired.

The curve is deliberately tiny — the creature subsystem needs hundreds
of curves on a hot path, so keyframes are sorted once at construction
time and :meth:`AnimationCurve.sample` runs in O(log n) via
``bisect_right``.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Any

from slappyengine._validation import (
    validate_finite_float,
    validate_positive_float,
    validate_unit_float,
)


# ---------------------------------------------------------------------------
# Keyframe
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Keyframe:
    """A single ``(t, value)`` keyframe.

    Parameters
    ----------
    t:
        Normalised time in ``[0.0, 1.0]``.
    value:
        Output value at *t*.
    """

    t: float
    value: float

    def __post_init__(self) -> None:
        fn = "Keyframe"
        object.__setattr__(self, "t", validate_unit_float("t", fn, self.t))
        object.__setattr__(
            self, "value", validate_finite_float("value", fn, self.value)
        )


# ---------------------------------------------------------------------------
# AnimationCurve
# ---------------------------------------------------------------------------


@dataclass
class AnimationCurve:
    """A keyframe-driven scalar curve over a fixed wall-clock duration.

    Sample with :meth:`sample` passing the elapsed time in seconds (the
    scheduler does this every tick). :meth:`is_done` returns ``True`` once
    the curve has played out, so the scheduler can retire it.

    Linear interpolation between keyframes. The curve clamps below the
    first keyframe (returning its value) and above the last one (same).

    Parameters
    ----------
    keyframes:
        Non-empty list of :class:`Keyframe`. Re-sorted by ``t`` on
        construction so callers can author in any order.
    duration_s:
        Total wall-clock duration in seconds (> 0).
    loop:
        If ``True``, :meth:`is_done` always returns ``False`` and
        :meth:`sample` wraps elapsed time modulo *duration_s*.
    """

    keyframes: list[Keyframe]
    duration_s: float
    loop: bool = False
    _ts: list[float] = field(init=False, repr=False)
    _vs: list[float] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        fn = "AnimationCurve"
        if not isinstance(self.keyframes, list):
            raise TypeError(
                f"{fn}: keyframes must be a list; "
                f"got {type(self.keyframes).__name__}"
            )
        if not self.keyframes:
            raise ValueError(f"{fn}: keyframes must be non-empty")
        for i, kf in enumerate(self.keyframes):
            if not isinstance(kf, Keyframe):
                raise TypeError(
                    f"{fn}: keyframes[{i}] must be a Keyframe; "
                    f"got {type(kf).__name__}"
                )
        self.duration_s = validate_positive_float(
            "duration_s", fn, self.duration_s
        )
        if not isinstance(self.loop, bool):
            raise TypeError(
                f"{fn}: loop must be a bool; got {type(self.loop).__name__}"
            )
        # Sort by t for O(log n) sample.
        sorted_kfs = sorted(self.keyframes, key=lambda k: k.t)
        self.keyframes = sorted_kfs
        self._ts = [kf.t for kf in sorted_kfs]
        self._vs = [kf.value for kf in sorted_kfs]

    # ---- API --------------------------------------------------------------

    def sample(self, t: float) -> float:
        """Return the interpolated value at elapsed time *t* (seconds).

        Below ``0`` clamps to the first keyframe value; above
        ``duration_s`` clamps to the last (unless ``loop=True``, in which
        case the elapsed time wraps).
        """
        elapsed = validate_finite_float("t", "AnimationCurve.sample", t)
        if self.loop:
            elapsed = elapsed % self.duration_s
        norm = elapsed / self.duration_s
        if norm <= self._ts[0]:
            return self._vs[0]
        if norm >= self._ts[-1]:
            return self._vs[-1]
        # bisect_right finds the first ts strictly greater than norm; the
        # interval is [idx-1, idx].
        idx = bisect_right(self._ts, norm)
        t0 = self._ts[idx - 1]
        t1 = self._ts[idx]
        v0 = self._vs[idx - 1]
        v1 = self._vs[idx]
        span = t1 - t0
        if span <= 0.0:
            return v1
        alpha = (norm - t0) / span
        return v0 + (v1 - v0) * alpha

    def is_done(self, t: float) -> bool:
        """``True`` once *t* (seconds) has reached or exceeded duration.

        Looping curves never finish — they always return ``False``.
        """
        elapsed = validate_finite_float("t", "AnimationCurve.is_done", t)
        if self.loop:
            return False
        return elapsed >= self.duration_s

    # ---- Round-trip -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain-Python dict (YAML/JSON safe)."""
        return {
            "keyframes": [{"t": kf.t, "value": kf.value} for kf in self.keyframes],
            "duration_s": self.duration_s,
            "loop": self.loop,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnimationCurve":
        """Rebuild from :meth:`to_dict` output."""
        if not isinstance(data, dict):
            raise TypeError(
                "AnimationCurve.from_dict: data must be a dict; "
                f"got {type(data).__name__}"
            )
        kfs_raw = data.get("keyframes") or []
        kfs = [Keyframe(t=float(k["t"]), value=float(k["value"])) for k in kfs_raw]
        return cls(
            keyframes=kfs,
            duration_s=float(data.get("duration_s", 1.0)),
            loop=bool(data.get("loop", False)),
        )


__all__ = ["AnimationCurve", "Keyframe"]
