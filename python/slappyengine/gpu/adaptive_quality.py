"""AdaptiveQualityController — monitors frame time, manages quality tiers.

Game code registers callbacks for each quality dimension (particle count,
fog resolution, etc.). The controller calls them when the tier changes.
"""
from __future__ import annotations
from typing import Callable
import time


class QualityTier:
    """Immutable description of one quality level."""
    __slots__ = ("label", "params")
    def __init__(self, label: str, **params):
        self.label = label
        self.params = params

    def __repr__(self):
        return f"QualityTier({self.label!r}, {self.params!r})"


class AdaptiveQualityController:
    """Frame-time-based adaptive quality system.

    Parameters
    ----------
    tiers:
        Ordered list of QualityTier from highest quality (index 0) to lowest.
        The controller starts at tier 0 and reduces when frame time is too high.
    target_fps:
        Target frame rate. Default 60.
    miss_threshold:
        Number of consecutive frames exceeding the frame budget before reducing
        a tier. Default 3.
    recovery_threshold:
        Number of consecutive frames under budget before restoring a tier.
        Default 5.
    on_tier_change:
        Optional callback fired with the new QualityTier whenever the tier
        changes. Game code uses this to adjust particle counts, step counts, etc.
    """

    def __init__(
        self,
        tiers: list[QualityTier],
        target_fps: float = 60.0,
        miss_threshold: int = 3,
        recovery_threshold: int = 5,
        on_tier_change: Callable[[QualityTier], None] | None = None,
    ) -> None:
        if not tiers:
            raise ValueError("tiers must be non-empty")
        self._tiers = list(tiers)
        self._target_ms: float = 1000.0 / max(1.0, target_fps)
        self._miss_threshold = miss_threshold
        self._recovery_threshold = recovery_threshold
        self._on_tier_change = on_tier_change

        self._tier_idx: int = 0           # current tier (0 = highest quality)
        self._miss_count: int = 0         # consecutive frames over budget
        self._recovery_count: int = 0     # consecutive frames under budget
        self._last_frame_ms: float = 0.0
        self._frame_count: int = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def current_tier(self) -> QualityTier:
        return self._tiers[self._tier_idx]

    @property
    def tier_index(self) -> int:
        return self._tier_idx

    @property
    def last_frame_ms(self) -> float:
        return self._last_frame_ms

    @property
    def frame_count(self) -> int:
        return self._frame_count

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def record_frame(self, frame_ms: float) -> None:
        """Feed actual frame time in milliseconds. Call once per frame.

        Automatically promotes or demotes quality tier based on consecutive
        budget misses / recoveries.
        """
        self._last_frame_ms = float(frame_ms)
        self._frame_count += 1

        over_budget = frame_ms > self._target_ms

        if over_budget:
            self._miss_count += 1
            self._recovery_count = 0
            if self._miss_count >= self._miss_threshold:
                self._reduce()
                self._miss_count = 0
        else:
            self._recovery_count += 1
            self._miss_count = 0
            if self._recovery_count >= self._recovery_threshold:
                self._restore()
                self._recovery_count = 0

    # ------------------------------------------------------------------
    # Tier management
    # ------------------------------------------------------------------

    def _reduce(self) -> None:
        """Move to the next lower quality tier if possible."""
        if self._tier_idx < len(self._tiers) - 1:
            self._tier_idx += 1
            self._notify()

    def _restore(self) -> None:
        """Move to the next higher quality tier if possible."""
        if self._tier_idx > 0:
            self._tier_idx -= 1
            self._notify()

    def _notify(self) -> None:
        if self._on_tier_change is not None:
            try:
                self._on_tier_change(self.current_tier)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Force / reset
    # ------------------------------------------------------------------

    def set_tier(self, index: int) -> None:
        """Force a specific tier by index (0 = highest quality)."""
        idx = max(0, min(index, len(self._tiers) - 1))
        if idx != self._tier_idx:
            self._tier_idx = idx
            self._notify()

    def reset(self) -> None:
        """Return to highest quality tier and clear counters."""
        self._tier_idx = 0
        self._miss_count = 0
        self._recovery_count = 0

    # ------------------------------------------------------------------
    # Debug summary
    # ------------------------------------------------------------------

    def debug_str(self) -> str:
        """One-line status for HUD overlay or console."""
        return (
            f"Quality: {self.current_tier.label}  "
            f"({self._last_frame_ms:.1f}ms / {self._target_ms:.1f}ms target)  "
            f"miss={self._miss_count}  recovery={self._recovery_count}"
        )
