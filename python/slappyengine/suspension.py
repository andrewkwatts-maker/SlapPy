"""Arcade-style suspension helper for top-down vehicle games.

Like :mod:`slappyengine.drivetrain` this is a SCRIPTING-LAYER helper —
not a physics solver. It exists so games can read per-frame wheel
forces and feed body_roll / body_pitch back into their sprite without
running a full softbody suspension simulation.

For full physics, use :func:`slappyengine.softbody.vehicle.build_vehicle`
which gives you real beam-driven suspension contact.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class SuspensionComponent:
    """Tracks a 4-wheel arcade suspension state.

    The state lags behind input forces with simple low-pass smoothing.
    ``update()`` returns a dict so callers can fish out only what they
    need (body_roll, body_pitch, wheel_compression).
    """
    body_roll: float = 0.0          # radians; positive = leans right
    body_pitch: float = 0.0         # radians; positive = nose-up
    wheel_compression: list[float] = field(default_factory=lambda: [0.0] * 4)
    smoothing: float = 0.20         # 0 = no lag, 1 = no change per frame
    roll_gain: float = 0.30
    pitch_gain: float = 0.25

    def update(self, wheel_forces: Sequence[float], dt: float,
               deform: object | None = None) -> dict[str, float | list[float]]:
        """Integrate one frame of suspension state.

        Parameters
        ----------
        wheel_forces
            Iterable of 4 per-wheel vertical loads (front-left, front-right,
            rear-left, rear-right). Units are arbitrary — only relative
            differences drive roll/pitch.
        dt
            Frame delta-time (seconds). Currently unused but kept in the
            signature for forward-compatibility.
        deform
            Optional damage/deform handle — if a chassis is bent, the
            suspension biases roll slightly. Ignored when None.

        Returns
        -------
        dict with keys: ``body_roll``, ``body_pitch``, ``wheel_compression``.
        """
        f = list(wheel_forces) + [0.0] * 4
        f = f[:4]
        fl, fr, rl, rr = f
        # Roll: left-right load difference (averaging front + rear).
        roll_target = ((fr + rr) - (fl + rl)) * self.roll_gain
        # Pitch: front-rear load difference.
        pitch_target = ((rl + rr) - (fl + fr)) * self.pitch_gain

        # Optional damage bias — bent chassis sits crooked.
        if deform is not None and hasattr(deform, "tilt_bias"):
            roll_target += float(getattr(deform, "tilt_bias", 0.0))

        s = float(self.smoothing)
        self.body_roll = s * self.body_roll + (1.0 - s) * roll_target
        self.body_pitch = s * self.body_pitch + (1.0 - s) * pitch_target

        # Per-wheel compression = load magnitude lagged.
        for i in range(4):
            self.wheel_compression[i] = s * self.wheel_compression[i] \
                                         + (1.0 - s) * float(f[i])

        return {
            "body_roll": self.body_roll,
            "body_pitch": self.body_pitch,
            "wheel_compression": list(self.wheel_compression),
        }


__all__ = ["SuspensionComponent"]
