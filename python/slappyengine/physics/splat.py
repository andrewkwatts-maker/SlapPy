"""Splat deformation calculator — squash/stretch polygon fragments on impact.

When a fluid-ish polygon particle (mud, water, slime) hits a surface, it
should deform: compress along the impact direction and widen perpendicular
to it. Rigid particles (rock, ice) keep their shape. This module is the
standalone calculator that maps an impact context to the right
``(scale_x, scale_y, rotation)`` tuple for
:meth:`slappyengine.physics.fragment.FragmentShape.bake_mask_xy`.

Design note: this module deliberately has no side effects and no
dependencies on the live simulation. It's a pure function of impact
state — easy to test, easy to compose, easy to swap in the upcoming
Material refactor without touching either side.

The two knobs are:

* ``squash_strength`` — fractional compression along the impact axis.
  ``0.5`` means the polygon is half as tall (in the impact axis) at
  full fluidity + full speed.
* ``stretch_strength`` — fractional widening perpendicular to impact.
  ``0.4`` means the polygon is 1.4× wider (in the perpendicular axis)
  at full fluidity + full speed.

Both are gated by ``fluidity_gate``: a particle with current fluidity
below the gate just thuds and keeps its shape.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


# Speed window over which the splat ramps from 0 to full effect. Below
# ``_SPEED_FLOOR`` an impact is treated as a soft landing and contributes
# nothing; above ``_SPEED_FLOOR + _SPEED_WINDOW`` the speed factor saturates.
_SPEED_FLOOR = 50.0
_SPEED_WINDOW = 200.0


@dataclass(frozen=True)
class SplatConfig:
    """Material's splat behaviour. Squash compresses the polygon along
    the impact direction; stretch widens it perpendicular. Fluidity
    gate gates the effect — only particles still kinetic enough
    splat (rigid materials like rock keep their shape)."""

    squash_strength: float = 0.0   # 0 = no squash; 1 = polygon flattened to a line
    stretch_strength: float = 0.0  # 0 = no stretch; 1 = double-wide perpendicular
    fluidity_gate: float = 0.3     # require current_fluidity > gate to splat

    # Optional: fracture support (placeholder — not implemented here)
    can_fracture: bool = False
    fracture_threshold_ke: float = 5e5


def _clamp(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def compute_splat(
    impact_vel: tuple[float, float],
    current_fluidity: float,
    base_scale: float,
    base_rotation: float,
    cfg: SplatConfig,
) -> tuple[float, float, float]:
    """Return ``(scale_x, scale_y, rotation)`` for
    :meth:`FragmentShape.bake_mask_xy`.

    Parameters
    ----------
    impact_vel:
        ``(vx, vy)`` velocity just before landing.
    current_fluidity:
        How kinetic/wet the particle is, in ``[0, 1]``.
    base_scale:
        The particle's ``bake_radius`` — the un-deformed footprint size.
    base_rotation:
        The particle's stored ``shape_rotation`` — the polygon's own
        spin around its splat axis.
    cfg:
        Material splat parameters.

    Returns
    -------
    A tuple ready to splice straight into ``bake_mask_xy``.

    Notes
    -----
    If ``current_fluidity < cfg.fluidity_gate`` or
    ``cfg.squash_strength == 0`` (and ``cfg.stretch_strength == 0``),
    returns ``(base_scale, base_scale, base_rotation)`` unchanged.

    Otherwise computes ``impact_dir = normalize(impact_vel)``, rotates
    the polygon so its "down" axis (the axis ``bake_mask_xy`` squashes
    when ``scale_y < scale_x``) aligns with ``impact_dir``, then scales
    by ``(1 - squash_strength * eff)`` along impact and
    ``(1 + stretch_strength * eff)`` perpendicular, where

        eff = current_fluidity * clamp((|v| - 50) / 200, 0, 1)
    """
    # Gate 1: material is rigid or splat disabled.
    if cfg.squash_strength == 0.0 and cfg.stretch_strength == 0.0:
        return base_scale, base_scale, base_rotation

    # Gate 2: particle is not fluid enough.
    if current_fluidity <= cfg.fluidity_gate:
        return base_scale, base_scale, base_rotation

    vx, vy = impact_vel
    speed = math.hypot(vx, vy)
    if speed <= 0.0:
        return base_scale, base_scale, base_rotation

    # Speed factor: ramp 0 → 1 over [_SPEED_FLOOR, _SPEED_FLOOR + _SPEED_WINDOW].
    speed_factor = _clamp((speed - _SPEED_FLOOR) / _SPEED_WINDOW, 0.0, 1.0)
    effective_fluidity = _clamp(current_fluidity, 0.0, 1.0) * speed_factor

    if effective_fluidity <= 0.0:
        # Below the speed floor: no measurable splat even if the
        # material *would* splat at higher speeds.
        return base_scale, base_scale, base_rotation

    # Impact direction (unit).
    dx = vx / speed
    dy = vy / speed

    # ``bake_mask_xy`` rotates the polygon in unit space first, then
    # applies the non-uniform scale in world frame. So scale_y < scale_x
    # always squashes along the world-y axis. To align that squash axis
    # with the impact direction, choose rotation such that the rotated
    # unit "down" vector (0, 1) maps to (dx, dy). Rotation matrix gives
    #   (0, 1) → (-sin(r), cos(r))
    # so cos(r) = dy and -sin(r) = dx, i.e. r = atan2(-dx, dy).
    rotation = math.atan2(-dx, dy) + base_rotation

    squash = 1.0 - cfg.squash_strength * effective_fluidity
    stretch = 1.0 + cfg.stretch_strength * effective_fluidity

    # Don't let squash collapse below a fingernail of width — bake_mask_xy
    # clamps to 0.1 anyway, but doing it here keeps the returned numbers
    # well-formed for downstream consumers.
    squash = max(0.05, squash)

    scale_x = base_scale * stretch
    scale_y = base_scale * squash

    return scale_x, scale_y, rotation


# ── Predefined splat configurations ────────────────────────────────────

SPLAT_NONE = SplatConfig(squash_strength=0.0, stretch_strength=0.0)
SPLAT_MUD = SplatConfig(squash_strength=0.5, stretch_strength=0.4, fluidity_gate=0.1)
SPLAT_WATER = SplatConfig(squash_strength=0.7, stretch_strength=0.5, fluidity_gate=0.0)
