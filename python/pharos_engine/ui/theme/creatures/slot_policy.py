"""Slot region + slot policy primitives for the creature scheduler.

A :class:`SlotRegion` is a Dear PyGui screen-space rect that anchors a
creature into a UI panel. The :class:`SlotPolicy` wraps that rect with
the cooldown range that gates idle animations and the maximum number
of concurrent trigger animations the slot allows.

Both records are pure data and YAML-round-trippable; the scheduler
holds references to them but never mutates them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pharos_engine._validation import (
    validate_bool,
    validate_non_negative_int,
    validate_optional_str,
    validate_positive_float,
    validate_positive_int,
)


# ---------------------------------------------------------------------------
# SlotRegion
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlotRegion:
    """A screen-space rect (DPG coordinate space) that hosts a creature.

    Parameters
    ----------
    x, y:
        Top-left corner in pixels (≥ 0).
    w, h:
        Width and height in pixels (> 0).
    parent_panel:
        Optional name of the DPG panel that owns the slot. Purely
        informational; the scheduler does not need it but tooling /
        diagnostics do.
    """

    x: int = 0
    y: int = 0
    w: int = 1
    h: int = 1
    parent_panel: str | None = None

    def __post_init__(self) -> None:
        fn = "SlotRegion"
        x = validate_non_negative_int("x", fn, self.x)
        y = validate_non_negative_int("y", fn, self.y)
        w = validate_positive_int("w", fn, self.w)
        h = validate_positive_int("h", fn, self.h)
        parent = validate_optional_str("parent_panel", fn, self.parent_panel)
        if parent is not None and parent == "":
            raise ValueError(f"{fn}: parent_panel must be non-empty if provided")
        object.__setattr__(self, "x", int(x))
        object.__setattr__(self, "y", int(y))
        object.__setattr__(self, "w", int(w))
        object.__setattr__(self, "h", int(h))
        object.__setattr__(self, "parent_panel", parent)

    def to_dict(self) -> dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
            "parent_panel": self.parent_panel,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SlotRegion":
        if not isinstance(data, dict):
            raise TypeError(
                "SlotRegion.from_dict: data must be a dict; "
                f"got {type(data).__name__}"
            )
        return cls(
            x=int(data.get("x", 0)),
            y=int(data.get("y", 0)),
            w=int(data.get("w", 1)),
            h=int(data.get("h", 1)),
            parent_panel=data.get("parent_panel"),
        )


# ---------------------------------------------------------------------------
# SlotPolicy
# ---------------------------------------------------------------------------


@dataclass
class SlotPolicy:
    """Where a creature lives and how often it may animate.

    Parameters
    ----------
    region:
        :class:`SlotRegion` the creature occupies.
    idle_cooldown_s:
        ``(min_seconds, max_seconds)`` between idle animations.
        ``max >= min > 0``.
    max_concurrent:
        Maximum trigger animations the slot may host simultaneously.
        Additional trigger requests are dropped per the §3 contract in
        the design doc (NOT queued, to avoid backlog drift).
    reduced_motion_idle_ok:
        When the scheduler is in reduced-motion mode this flag decides
        whether idle ``blink`` animations may still fire here.
        Non-blink idle animations are suppressed regardless.
    """

    region: SlotRegion
    idle_cooldown_s: tuple[float, float] = (3.0, 7.0)
    max_concurrent: int = 1
    reduced_motion_idle_ok: bool = True

    def __post_init__(self) -> None:
        fn = "SlotPolicy"
        if not isinstance(self.region, SlotRegion):
            raise TypeError(
                f"{fn}: region must be a SlotRegion; "
                f"got {type(self.region).__name__}"
            )
        if (
            isinstance(self.idle_cooldown_s, (str, bytes))
            or not hasattr(self.idle_cooldown_s, "__len__")
        ):
            raise TypeError(
                f"{fn}: idle_cooldown_s must be a (min, max) tuple; "
                f"got {type(self.idle_cooldown_s).__name__}"
            )
        if len(self.idle_cooldown_s) != 2:
            raise ValueError(
                f"{fn}: idle_cooldown_s must have length 2 (min, max); "
                f"got length {len(self.idle_cooldown_s)}"
            )
        lo = validate_positive_float(
            "idle_cooldown_s[0]", fn, self.idle_cooldown_s[0]
        )
        hi = validate_positive_float(
            "idle_cooldown_s[1]", fn, self.idle_cooldown_s[1]
        )
        if hi < lo:
            raise ValueError(
                f"{fn}: idle_cooldown_s max ({hi}) must be >= min ({lo})"
            )
        self.idle_cooldown_s = (lo, hi)
        self.max_concurrent = validate_positive_int(
            "max_concurrent", fn, self.max_concurrent
        )
        self.reduced_motion_idle_ok = validate_bool(
            "reduced_motion_idle_ok", fn, self.reduced_motion_idle_ok
        )


__all__ = ["SlotPolicy", "SlotRegion"]
