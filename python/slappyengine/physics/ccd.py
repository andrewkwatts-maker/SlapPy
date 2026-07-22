"""Continuous Collision Detection (CCD) for fast-moving hulls.

The standard broadphase samples AABBs *after* integration, which means a
small body travelling further than a thin obstacle's thickness in a single
frame can pass straight through it ("tunnelling"). The helpers in this
module operate on swept (t=0 → t=1) AABBs so the upstream world step can
identify pairs that need to be advanced to the time-of-impact before any
discrete resolution runs.

This module is intentionally standalone: it does not mutate ``HullTree`` or
``PhysicsWorld`` state. The integration glue lives elsewhere — this file
only provides the primitives.

Conventions
-----------
- AABBs are ``(x0, y0, x1, y1)`` with ``y`` down-positive (matches the
  rest of the physics module).
- ``toi`` (time of impact) is a scalar in ``[0.0, 1.0]`` denoting the
  fraction of the current step at which two swept AABBs first overlap.
  A returned ``toi`` of ``1.0`` means *no overlap inside the step*.
- ``speed_threshold`` is in pixels/second, matching ``HullTree.velocity``
  (which is "pixels per second" because ``integrate_transforms`` scales
  by ``dt``). Below this speed the discrete broadphase is already
  sufficient and we skip the CCD work.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np


# Numerical tolerance for degenerate (zero-velocity-difference) axes.
_EPS = 1.0e-9


def _to_box(aabb: Sequence[float]) -> tuple[float, float, float, float]:
    """Coerce an AABB-like into ``(x0, y0, x1, y1)`` floats.

    Accepts ``np.ndarray`` rows, tuples or lists. Normalises in case
    callers passed an inverted box (x1 < x0); this keeps the slab math
    branch-free below.
    """
    x0 = float(aabb[0])
    y0 = float(aabb[1])
    x1 = float(aabb[2])
    y1 = float(aabb[3])
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    return x0, y0, x1, y1


def _static_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    """Standard SAT overlap test for two axis-aligned boxes."""
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def swept_aabb_overlap(
    a_aabb_t0: Sequence[float],
    a_aabb_t1: Sequence[float],
    b_aabb_t0: Sequence[float],
    b_aabb_t1: Sequence[float],
) -> tuple[bool, float]:
    """Return ``(collided, toi)`` for two AABBs sweeping linearly between
    their ``t=0`` and ``t=1`` positions.

    Implementation
    --------------
    This is the moving-AABB slabs test. We reduce the problem to a single
    moving point against a static box by:

    1. Forming box ``A`` from ``a_aabb_t0`` (the t=0 footprint of ``A``).
    2. Forming the *relative* swept box of ``B`` as the Minkowski sum
       ``B_t - (-A_t0)`` — i.e. the set of positions of ``B``'s centre
       relative to ``A``'s centre that count as overlapping. In practice
       we just compare the *expanded* box for ``B`` (B inflated by A's
       half-extents) against a point at A's centre that moves with the
       relative velocity ``Δv = v_B - v_A``.

    For the standard case (no relative motion, already overlapping) we
    short-circuit to ``toi = 0.0``.

    Returns
    -------
    ``(collided, toi)`` where ``collided`` is ``True`` iff the two boxes
    overlap at *some* time in ``[0, 1]``, and ``toi`` is that earliest
    time. When ``collided`` is ``False``, ``toi`` is ``1.0``.
    """
    a0 = _to_box(a_aabb_t0)
    a1 = _to_box(a_aabb_t1)
    b0 = _to_box(b_aabb_t0)
    b1 = _to_box(b_aabb_t1)

    # Trivial accept: static-overlap at t=0.
    if _static_overlap(a0, b0):
        return True, 0.0

    # Per-axis velocities of each box's *centre* (and per-axis half-extent
    # changes are ignored — both endpoints are rigidly translated).
    a_vx = 0.5 * ((a1[0] + a1[2]) - (a0[0] + a0[2]))
    a_vy = 0.5 * ((a1[1] + a1[3]) - (a0[1] + a0[3]))
    b_vx = 0.5 * ((b1[0] + b1[2]) - (b0[0] + b0[2]))
    b_vy = 0.5 * ((b1[1] + b1[3]) - (b0[1] + b0[3]))

    # Relative velocity of B w.r.t. A.
    rvx = b_vx - a_vx
    rvy = b_vy - a_vy

    # Per-axis slab entry/exit. With ``rv == 0`` on an axis the boxes must
    # already overlap on that axis at t=0 or they can never overlap.
    t_enter = 0.0
    t_exit = 1.0

    # X axis.
    if abs(rvx) < _EPS:
        # No relative motion on X — must already be separated/overlapping.
        if a0[2] < b0[0] or b0[2] < a0[0]:
            return False, 1.0
    else:
        # Distance B's left edge needs to cover to touch A's right edge,
        # and vice-versa, divided by relative X velocity.
        if rvx > 0.0:
            # B moving right relative to A.
            t_in_x = (a0[0] - b0[2]) / rvx
            t_out_x = (a0[2] - b0[0]) / rvx
        else:
            t_in_x = (a0[2] - b0[0]) / rvx
            t_out_x = (a0[0] - b0[2]) / rvx
        if t_in_x > t_enter:
            t_enter = t_in_x
        if t_out_x < t_exit:
            t_exit = t_out_x
        if t_enter > t_exit:
            return False, 1.0

    # Y axis.
    if abs(rvy) < _EPS:
        if a0[3] < b0[1] or b0[3] < a0[1]:
            return False, 1.0
    else:
        if rvy > 0.0:
            t_in_y = (a0[1] - b0[3]) / rvy
            t_out_y = (a0[3] - b0[1]) / rvy
        else:
            t_in_y = (a0[3] - b0[1]) / rvy
            t_out_y = (a0[1] - b0[3]) / rvy
        if t_in_y > t_enter:
            t_enter = t_in_y
        if t_out_y < t_exit:
            t_exit = t_out_y
        if t_enter > t_exit:
            return False, 1.0

    # Clamp into [0, 1]. If the swept overlap is entirely after the step
    # ends (``t_enter > 1``) or entirely before (``t_exit < 0``), there's
    # no collision *this frame*.
    if t_enter > 1.0 or t_exit < 0.0:
        return False, 1.0
    toi = max(0.0, t_enter)
    return True, toi


def position_at_toi(
    hulls,
    hull_id: int,
    toi: float,
    dt: float,
) -> tuple[float, float]:
    """Where would hull ``hull_id`` be at time ``toi * dt`` within the
    current step?

    Assumes constant-velocity motion within the substep (which matches
    what the rest of the integrator does pre-contact-resolution).
    """
    px = float(hulls.position[hull_id, 0])
    py = float(hulls.position[hull_id, 1])
    vx = float(hulls.velocity[hull_id, 0])
    vy = float(hulls.velocity[hull_id, 1])
    t = float(toi) * float(dt)
    return px + vx * t, py + vy * t


def _swept_aabb_for_hull(
    hulls,
    hull_id: int,
    dt: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (t=0, t=1) AABBs for ``hull_id``, given its current AABB
    and velocity.

    The t=0 AABB is the hull's current (already-stored) AABB; the t=1
    AABB is that same box translated by ``velocity * dt``.
    """
    aabb0 = hulls.aabb[hull_id].astype(np.float64, copy=True)
    vx = float(hulls.velocity[hull_id, 0])
    vy = float(hulls.velocity[hull_id, 1])
    aabb1 = aabb0.copy()
    aabb1[0] += vx * dt
    aabb1[1] += vy * dt
    aabb1[2] += vx * dt
    aabb1[3] += vy * dt
    return aabb0, aabb1


def predict_contact_pairs(
    hulls,
    dt: float,
    speed_threshold: float = 50.0,
) -> list[tuple[int, int, float]]:
    """For each pair of live root hulls whose current velocity magnitude
    exceeds ``speed_threshold`` (px/s), compute the swept-AABB overlap
    between ``t=0`` (current position) and ``t=1`` (position +
    velocity*dt).

    A pair is included if *either* hull is moving above ``speed_threshold``
    — a fast small body striking a static thin wall is the canonical
    tunnelling case and we still want to predict it. Fixed hulls always
    count as the slow side; they're never predicted against each other.

    Returns
    -------
    A list of ``(hull_a, hull_b, toi)`` tuples for the pairs whose swept
    AABBs overlap inside the step. ``PhysicsWorld`` can use this to step
    those pairs to time-of-impact, resolve, then complete the remaining
    ``dt``.
    """
    if dt <= 0.0:
        return []

    alive = np.asarray(hulls._alive, dtype=bool)  # noqa: SLF001 - SoA access
    # Only roots: ``root_id[i] == i`` for roots.
    root_mask = (np.asarray(hulls.root_id) == np.arange(len(alive))) & alive
    fixed = np.asarray(hulls.fixed, dtype=bool)

    indices = np.nonzero(root_mask)[0]
    if indices.size < 2:
        return []

    vels = np.asarray(hulls.velocity, dtype=np.float64)
    speeds = np.sqrt(vels[:, 0] ** 2 + vels[:, 1] ** 2)

    threshold = float(speed_threshold)
    pairs: list[tuple[int, int, float]] = []

    # Pre-build the swept AABBs once so we don't redo the work per pair.
    sweeps: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for idx in indices:
        sweeps[int(idx)] = _swept_aabb_for_hull(hulls, int(idx), dt)

    n = indices.size
    for i in range(n):
        a = int(indices[i])
        for j in range(i + 1, n):
            b = int(indices[j])
            # At least one side must be moving fast enough, and we
            # require that the *moving* side actually be non-fixed.
            a_fast = (speeds[a] >= threshold) and (not fixed[a])
            b_fast = (speeds[b] >= threshold) and (not fixed[b])
            if not (a_fast or b_fast):
                continue
            a0, a1 = sweeps[a]
            b0, b1 = sweeps[b]
            collided, toi = swept_aabb_overlap(a0, a1, b0, b1)
            if collided:
                pairs.append((a, b, float(toi)))
    return pairs


__all__ = [
    "position_at_toi",
    "predict_contact_pairs",
    "swept_aabb_overlap",
]
