"""Arcade-style drivetrain helper for top-down vehicle games.

This is a SCRIPTING-LAYER helper, not a physics solver. The actual chassis
physics lives in :mod:`slappyengine.softbody.vehicle` (XPBD softbody +
beams). This module exists so games like Ochema Circuit, which read
input + compute a single per-frame "traction" multiplier to apply to
their velocity, don't have to roll their own.

Public surface:

* :class:`DriveType` — RWD / FWD / AWD selector
* :class:`DiffType`  — open / LSD / locked differential
* :class:`DrivetrainComponent` — per-frame update returning an
  ``overall_traction`` scalar in ``[0.1, 1.0]``

If you want full softbody physics (chassis beams, plasticity, suspension
contact), use :func:`slappyengine.softbody.vehicle.build_vehicle` and
:func:`apply_drivetrain_torque` instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DriveType(Enum):
    """Which wheels receive engine torque."""
    RWD = "rwd"
    FWD = "fwd"
    AWD = "awd"


class DiffType(Enum):
    """Differential behaviour at the axle."""
    FREE = "free"               # open differential
    LIMITED_SLIP = "lsd"        # LSD with bias
    LOCKED = "locked"           # spool / locker


@dataclass
class DrivetrainComponent:
    """Arcade drivetrain — single scalar 'traction' per frame.

    Parameters
    ----------
    drive_type
        Which axle drives. RWD oversteers at high speed; FWD understeers
        under power; AWD is neutral.
    front_diff, rear_diff
        Differential type per axle. LSD/locked give a small traction
        bonus during corners; ``FREE`` is the baseline.
    """
    drive_type: DriveType = DriveType.RWD
    front_diff: DiffType = DiffType.FREE
    rear_diff: DiffType = DiffType.FREE
    overall_traction: float = 1.0
    speed: float = 0.0

    # ------- diff bonus (LSD/locked claw back some of the steer penalty) -------
    _DIFF_BONUS = {
        DiffType.FREE: 0.00,
        DiffType.LIMITED_SLIP: 0.05,
        DiffType.LOCKED: 0.08,
    }

    def _drivetype_bias(self, speed: float, steer: float) -> float:
        """Drive-layout-specific traction offset.

        RWD loses grip in corners at high speed (oversteer). FWD pulls
        through corners (understeer = stable). AWD plants the car.
        """
        s = abs(float(steer))
        if self.drive_type is DriveType.AWD:
            return 0.05
        if self.drive_type is DriveType.FWD:
            return 0.02
        # RWD
        return -0.05 * s if speed > 80.0 else 0.0

    def update(self, dt: float, speed: float, accel: float,
               brake: float, steer: float, thrust: float = 0.0) -> float:
        """Recompute :attr:`overall_traction` for this frame and return it.

        Inputs are clamped — out-of-range values produce stable behaviour
        instead of NaN. Returns the new traction so callers can chain.
        """
        self.speed = float(speed)
        s = abs(float(steer))
        b = max(0.0, min(1.0, float(brake)))

        # Base: cornering and braking both bleed traction.
        base = 1.0 - 0.30 * s - 0.50 * b

        # Diff bonuses per axle (LSD / locked help under load).
        front_bonus = self._DIFF_BONUS.get(self.front_diff, 0.0)
        rear_bonus = self._DIFF_BONUS.get(self.rear_diff, 0.0)
        diff_bias = 0.5 * (front_bonus + rear_bonus)

        # Drivetrain layout adjustment.
        layout_bias = self._drivetype_bias(self.speed, steer)

        self.overall_traction = max(0.10, min(1.0, base + diff_bias + layout_bias))
        return self.overall_traction


__all__ = ["DriveType", "DiffType", "DrivetrainComponent"]
