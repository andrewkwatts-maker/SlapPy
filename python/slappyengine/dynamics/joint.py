"""Generic constraint type for the unified dynamics layer.

All seven joint flavours (``distance``, ``spring``, ``weld``, ``ball``,
``hinge``, ``motor``, ``prismatic``) share the :class:`JointSpec` dataclass
and resolve through the same :func:`resolve` dispatch table. Each kind is
expressed as a small composition of XPBD-style position projections plus
(for the motor) a tangential impulse — no new low-level kernels.

Schema for ``params`` by ``kind``:

- ``distance``: ``{}``
- ``spring``:   ``{}`` (same as distance but author defaults differ)
- ``weld``:     ``{"rest_offset": (dx, dy)}`` optional; stiff distance + drift fix
- ``ball``:     ``{}`` (zero rest length)
- ``hinge``:    ``{"anchor": int, "min_angle": float, "max_angle": float}``
- ``motor``:    ``{"hub": int, "axis": (ax, ay), "target_omega": float,
                  "max_torque": float}``
- ``prismatic``:``{"axis": (ax, ay), "min": float, "max": float}``

Each builder in :mod:`slappyengine.dynamics.spring` etc. is the *only* code
allowed to write into ``params`` for that ``kind``. The solver reads via
``params.get(key, default)`` so a typo silently disables the feature rather
than crashing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:  # pragma: no cover
    from .world import World


# Documented schema per kind — used by tests and builders to validate keys.
KIND_PARAM_KEYS: dict[str, set[str]] = {
    "distance":  set(),
    "spring":    set(),
    "weld":      {"rest_offset"},
    "ball":      set(),
    "hinge":     {"anchor", "min_angle", "max_angle"},
    "motor":     {"hub", "axis", "target_omega", "max_torque"},
    "prismatic": {"axis", "min", "max"},
}


@dataclass
class JointSpec:
    """Generic two-node constraint.

    Parameters
    ----------
    kind:
        One of the strings in :data:`KIND_PARAM_KEYS`.
    node_a, node_b:
        Absolute node indices inside the host :class:`~.world.World`.
    rest_length:
        Target separation for distance-family constraints.
    stiffness:
        XPBD compliance is computed as ``1 / (stiffness * dt^2)`` so larger
        values produce a harder constraint.
    damping:
        Position-level damping coefficient in ``[0, 1]``.
    params:
        Kind-specific extras (see module docstring).
    break_force:
        Joint deactivates once the latest correction magnitude exceeds this.
    enabled:
        Lets builders disable a joint without removing it from the list.
    """
    kind: str
    node_a: int
    node_b: int
    rest_length: float = 0.0
    stiffness: float = 1.0e9
    damping: float = 0.02
    params: dict[str, Any] = field(default_factory=dict)
    break_force: float = math.inf
    enabled: bool = True


# ---------------------------------------------------------------------------
# Low-level XPBD distance projection — the only solver primitive we need.
# ---------------------------------------------------------------------------

def _project_distance(
    world: "World",
    a: int,
    b: int,
    rest_length: float,
    stiffness: float,
    damping: float,
    dt: float,
) -> float:
    """Project a distance constraint and return the correction magnitude.

    Implements the canonical XPBD position update::

        C       = |x_a - x_b| - L
        ∇C_a    =  n
        ∇C_b    = -n
        α̂       = 1 / (k · dt²)
        Δλ      = -(C + α̂ λ) / (w_a + w_b + α̂)
        Δx_a    =  w_a · Δλ · n
        Δx_b    = -w_b · Δλ · n
    """
    pa = world.positions[a]
    pb = world.positions[b]
    delta = pa - pb
    d = float(np.linalg.norm(delta))
    if d < 1e-12:
        return 0.0
    n = delta / d
    C = d - rest_length
    wa = float(world.inv_masses[a])
    wb = float(world.inv_masses[b])
    w_sum = wa + wb
    if w_sum <= 0.0:
        return 0.0
    compliance = 1.0 / max(stiffness * dt * dt, 1e-12)
    dlambda = -C / (w_sum + compliance)
    # Apply position-level damping by scaling the correction.
    dlambda *= (1.0 - max(0.0, min(1.0, damping)))
    corr_a = wa * dlambda * n
    corr_b = -wb * dlambda * n
    world.positions[a] = pa + corr_a
    world.positions[b] = pb + corr_b
    return abs(dlambda)


def _project_angle(
    world: "World",
    anchor: int,
    a: int,
    b: int,
    min_angle: float,
    max_angle: float,
    stiffness: float,
) -> float:
    """Iterative hinge/angle limit — extension built atop numpy.

    Computes the signed angle between vectors ``anchor->a`` and ``anchor->b``;
    when it exceeds the declared ``[min_angle, max_angle]`` band the two free
    ends are nudged tangentially to bring the angle back into range. This is
    the "new primitive" the plan permitted us to add in pure numpy when the
    solver lacked it.
    """
    p0 = world.positions[anchor]
    pa = world.positions[a]
    pb = world.positions[b]
    va = pa - p0
    vb = pb - p0
    la = float(np.linalg.norm(va))
    lb = float(np.linalg.norm(vb))
    if la < 1e-9 or lb < 1e-9:
        return 0.0
    ang = math.atan2(
        va[0] * vb[1] - va[1] * vb[0],
        va[0] * vb[0] + va[1] * vb[1],
    )
    if ang < min_angle:
        delta_ang = min_angle - ang
    elif ang > max_angle:
        delta_ang = max_angle - ang
    else:
        return 0.0
    half = 0.5 * delta_ang * max(0.0, min(1.0, stiffness))
    # Rotate va by -half and vb by +half so the angle moves toward the band.
    cos_n, sin_n = math.cos(-half), math.sin(-half)
    cos_p, sin_p = math.cos(half), math.sin(half)
    new_va = np.array([cos_n * va[0] - sin_n * va[1], sin_n * va[0] + cos_n * va[1]])
    new_vb = np.array([cos_p * vb[0] - sin_p * vb[1], sin_p * vb[0] + cos_p * vb[1]])
    wa = float(world.inv_masses[a])
    wb = float(world.inv_masses[b])
    if wa > 0.0:
        world.positions[a] = p0 + new_va
    if wb > 0.0:
        world.positions[b] = p0 + new_vb
    return abs(delta_ang)


# ---------------------------------------------------------------------------
# Per-kind resolvers
# ---------------------------------------------------------------------------

def _resolve_distance(joint: JointSpec, world: "World", dt: float) -> float:
    return _project_distance(
        world, joint.node_a, joint.node_b,
        joint.rest_length, joint.stiffness, joint.damping, dt,
    )


def _resolve_spring(joint: JointSpec, world: "World", dt: float) -> float:
    # Same projection as distance — the difference is encoded in the default
    # stiffness / damping the make_spring builder writes.
    return _project_distance(
        world, joint.node_a, joint.node_b,
        joint.rest_length, joint.stiffness, joint.damping, dt,
    )


def _resolve_weld(joint: JointSpec, world: "World", dt: float) -> float:
    # Weld = stiff distance constraint at the configured rest_length (default 0).
    return _project_distance(
        world, joint.node_a, joint.node_b,
        joint.rest_length, joint.stiffness, joint.damping, dt,
    )


def _resolve_ball(joint: JointSpec, world: "World", dt: float) -> float:
    # Ball joint = zero rest length distance constraint, no angular limit.
    return _project_distance(
        world, joint.node_a, joint.node_b,
        0.0, joint.stiffness, joint.damping, dt,
    )


def _resolve_hinge(joint: JointSpec, world: "World", dt: float) -> float:
    # Hinge holds node_b at rest_length from node_a (the pivot) AND clamps
    # the angle to anchor->node_a vs anchor->node_b within [min, max].
    corr = _project_distance(
        world, joint.node_a, joint.node_b,
        joint.rest_length, joint.stiffness, joint.damping, dt,
    )
    anchor = joint.params.get("anchor")
    if anchor is None:
        return corr
    min_a = float(joint.params.get("min_angle", -math.pi))
    max_a = float(joint.params.get("max_angle", math.pi))
    corr += _project_angle(
        world, int(anchor), joint.node_a, joint.node_b,
        min_a, max_a, 1.0,
    )
    return corr


def _resolve_motor(joint: JointSpec, world: "World", dt: float) -> float:
    # Motor: spin the rim (node_a, node_b) around hub.
    # 1) keep rim attached to the hub at rest_length (two distance constraints)
    # 2) drive each rim node tangentially toward a target angular velocity
    hub = int(joint.params.get("hub", joint.node_a))
    if hub == joint.node_a:
        # Mis-keyed — bail to a pure distance constraint to avoid silent NaNs.
        return _project_distance(
            world, joint.node_a, joint.node_b,
            joint.rest_length, joint.stiffness, joint.damping, dt,
        )
    target_omega = float(joint.params.get("target_omega", 0.0))
    max_torque = float(joint.params.get("max_torque", 0.0))
    corr = 0.0
    # Hold rim-to-hub distances.
    if joint.rest_length > 0.0:
        corr += _project_distance(
            world, hub, joint.node_a, joint.rest_length,
            joint.stiffness, joint.damping, dt,
        )
        corr += _project_distance(
            world, hub, joint.node_b, joint.rest_length,
            joint.stiffness, joint.damping, dt,
        )
    # Tangential velocity push: v_target = ω × r.
    p_hub = world.positions[hub]
    for rim in (joint.node_a, joint.node_b):
        w = float(world.inv_masses[rim])
        if w <= 0.0:
            continue
        r = world.positions[rim] - p_hub
        # Tangent in 2D for positive ω: (-ry, rx).
        tangent = np.array([-r[1], r[0]])
        # Drive velocity toward tangent * target_omega magnitude.
        target_v = tangent * target_omega
        cur_v = world.velocities[rim]
        dv = target_v - cur_v
        # Project dv onto tangent so we add spin, not radial drift.
        t_norm = float(np.linalg.norm(tangent))
        if t_norm < 1e-9:
            continue
        t_hat = tangent / t_norm
        dv_along = float(np.dot(dv, t_hat))
        impulse_per_mass = dv_along
        # Cap by max_torque (interpreted as |Δv| per substep).
        if max_torque > 0.0:
            cap = max_torque * dt
            if abs(impulse_per_mass) > cap:
                impulse_per_mass = math.copysign(cap, impulse_per_mass)
        push = t_hat * impulse_per_mass
        world.velocities[rim] = cur_v + push
        # Reflect in positions so the XPBD velocity-recovery step sees it.
        world.positions[rim] = world.positions[rim] + push * dt
        corr += abs(impulse_per_mass)
    return corr


def _resolve_prismatic(joint: JointSpec, world: "World", dt: float) -> float:
    # Prismatic: relative displacement constrained to axis with [min, max] slot.
    axis = joint.params.get("axis", (1.0, 0.0))
    axis_v = np.asarray(axis, dtype=np.float64)
    n = float(np.linalg.norm(axis_v))
    if n < 1e-9:
        return 0.0
    axis_v = axis_v / n
    # Perpendicular component of (b - a) should be zero.
    pa = world.positions[joint.node_a]
    pb = world.positions[joint.node_b]
    rel = pb - pa
    along = float(np.dot(rel, axis_v))
    perp = rel - along * axis_v
    wa = float(world.inv_masses[joint.node_a])
    wb = float(world.inv_masses[joint.node_b])
    w_sum = wa + wb
    if w_sum <= 0.0:
        return 0.0
    # Cancel perpendicular drift (stiff).
    world.positions[joint.node_a] = pa + (wa / w_sum) * perp
    world.positions[joint.node_b] = pb - (wb / w_sum) * perp
    # Clamp along-axis distance to [min, max].
    lo = float(joint.params.get("min", -math.inf))
    hi = float(joint.params.get("max", math.inf))
    if along < lo:
        excess = lo - along
        world.positions[joint.node_a] = pa + (wa / w_sum) * perp - (wa / w_sum) * excess * axis_v
        world.positions[joint.node_b] = pb - (wb / w_sum) * perp + (wb / w_sum) * excess * axis_v
        return float(np.linalg.norm(perp)) + abs(excess)
    if along > hi:
        excess = along - hi
        world.positions[joint.node_a] = pa + (wa / w_sum) * perp + (wa / w_sum) * excess * axis_v
        world.positions[joint.node_b] = pb - (wb / w_sum) * perp - (wb / w_sum) * excess * axis_v
        return float(np.linalg.norm(perp)) + abs(excess)
    return float(np.linalg.norm(perp))


_DISPATCH = {
    "distance":  _resolve_distance,
    "spring":    _resolve_spring,
    "weld":      _resolve_weld,
    "ball":      _resolve_ball,
    "hinge":     _resolve_hinge,
    "motor":     _resolve_motor,
    "prismatic": _resolve_prismatic,
}


def resolve(joint: JointSpec, world: "World", dt: float) -> float:
    """Dispatch a joint to its XPBD projection. Returns correction magnitude."""
    fn = _DISPATCH.get(joint.kind)
    if fn is None:
        raise ValueError(f"Unknown JointSpec.kind: {joint.kind!r}")
    corr = fn(joint, world, dt)
    if corr > joint.break_force:
        joint.enabled = False
    return corr


__all__ = ["JointSpec", "KIND_PARAM_KEYS", "resolve"]
