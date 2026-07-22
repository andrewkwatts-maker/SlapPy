"""Joint/constraint system for the hierarchical-hull physics module.

Adapter pattern: game code constructs constraints and calls
``solver.solve(world, dt)`` each frame between (or after) ``world.step``
invocations.  The solver does *not* touch :mod:`world` internals other
than the public position / velocity / angle / omega arrays exposed on
:class:`HullTree`, plus the ``mass``/``inertia`` of each body.

Implemented as a position-based projected Gauss-Seidel sweep with a
small Baumgarte bias for clean convergence at 4 iterations.  Three
joint types are supplied:

* :class:`PinConstraint` -- frictionless rotational pin (chassis/wheel).
* :class:`DistanceConstraint` -- stiff or soft rod between two anchor
  points (axle, beam, rope-when-tight).
* :class:`WeldConstraint` -- locks both position and orientation.

Use :class:`ConstraintSolver` to assemble + solve a set of constraints.
A constraint whose accumulated impulse magnitude exceeds its
``break_force`` (or, for :class:`DistanceConstraint`, whose strain
exceeds ``break_strain``) is removed from the active set and appended
to ``solver.broken`` so game code can react.

The solver respects ``config.physics.constraints.enabled`` in
``config/physics.yml`` -- if disabled at load time the solver becomes
a no-op while still accepting ``add``/``remove`` calls.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Union

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pharos_engine.physics.body import PhysicsBody
    from pharos_engine.physics.world import PhysicsWorld


# Baumgarte position-correction coefficient.  Small values stabilise the
# solver without injecting noticeable energy.  Tuned to give clean
# convergence with iterations=4.
_BAUMGARTE_BETA = 0.2

# Treat ``mass`` or ``inertia`` <= this as effectively infinite (fixed body).
_FIXED_THRESHOLD = 1e-12


# --------------------------------------------------------------------------- #
# Constraint dataclasses                                                      #
# --------------------------------------------------------------------------- #


@dataclass
class PinConstraint:
    """Two bodies share a single world-space anchor point.

    Equivalent to a frictionless 2D rotational pin (chassis-to-wheel,
    chain-link, hinge pivot).  Implemented via positional projection +
    impulse application on the bodies' rigid state.
    """

    body_a: "PhysicsBody"
    body_b: "PhysicsBody"
    local_anchor_a: tuple[float, float]
    local_anchor_b: tuple[float, float]
    break_force: float = float("inf")
    # Last impulse magnitude applied this solve() call (diagnostic).
    last_impulse: float = field(default=0.0, init=False, repr=False)


@dataclass
class DistanceConstraint:
    """Two bodies stay at fixed world-distance through two attachment points.

    Equivalent to a stiff rod (axle, beam, rope-when-tight).
    ``stiffness`` is a 0..1 fraction of the full correction applied per
    iteration; 1.0 is a perfectly rigid rod.
    """

    body_a: "PhysicsBody"
    body_b: "PhysicsBody"
    local_anchor_a: tuple[float, float]
    local_anchor_b: tuple[float, float]
    distance: float
    stiffness: float = 1.0
    break_strain: float = 0.5
    last_impulse: float = field(default=0.0, init=False, repr=False)


@dataclass
class WeldConstraint:
    """Two bodies share both position AND orientation (frame-locked).

    Useful for rigid attachments where rotational play is unwanted -- e.g.
    bolting a turret onto a chassis.
    """

    body_a: "PhysicsBody"
    body_b: "PhysicsBody"
    local_anchor_a: tuple[float, float]
    local_anchor_b: tuple[float, float]
    target_relative_angle: float = 0.0
    break_force: float = float("inf")
    last_impulse: float = field(default=0.0, init=False, repr=False)


Constraint = Union[PinConstraint, DistanceConstraint, WeldConstraint]


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _body_state(body: "PhysicsBody") -> dict:
    """Pull mutable rigid state from a PhysicsBody as a small dict.

    The solver mutates this dict, then ``_write_back`` flushes the new
    state to the underlying HullTree arrays.  Going via a dict keeps the
    math readable and lets us run the solve in a self-contained loop
    without poking many ``np.ndarray`` indices in the inner loop.
    """
    world = body.world
    hid = body.root_hull_id
    fixed = bool(body.fixed) or float(world.hulls.mass[hid]) <= _FIXED_THRESHOLD
    return {
        "hid": hid,
        "fixed": fixed,
        "px": float(world.hulls.position[hid, 0]),
        "py": float(world.hulls.position[hid, 1]),
        "vx": float(world.hulls.velocity[hid, 0]),
        "vy": float(world.hulls.velocity[hid, 1]),
        "angle": float(world.hulls.angle[hid]),
        "omega": float(world.hulls.omega[hid]),
        "mass": float(world.hulls.mass[hid]),
        "inertia": float(world.hulls.inertia[hid]),
    }


def _write_back(body: "PhysicsBody", st: dict) -> None:
    world = body.world
    hid = st["hid"]
    if st["fixed"]:
        # Fixed bodies never move under constraints; still set angle for
        # safety in case caller toggled fixed mid-solve.
        return
    world.hulls.position[hid, 0] = st["px"]
    world.hulls.position[hid, 1] = st["py"]
    world.hulls.velocity[hid, 0] = st["vx"]
    world.hulls.velocity[hid, 1] = st["vy"]
    world.hulls.angle[hid] = st["angle"]
    world.hulls.omega[hid] = st["omega"]


def _inv_mass(st: dict) -> float:
    if st["fixed"]:
        return 0.0
    m = st["mass"]
    return 0.0 if m <= _FIXED_THRESHOLD else 1.0 / m


def _inv_inertia(st: dict) -> float:
    if st["fixed"]:
        return 0.0
    i = st["inertia"]
    return 0.0 if i <= _FIXED_THRESHOLD else 1.0 / i


def _world_anchor(st: dict, local: tuple[float, float]) -> tuple[float, float]:
    """Rotate ``local`` by ``angle`` and translate by body position."""
    c = math.cos(st["angle"])
    s = math.sin(st["angle"])
    lx, ly = float(local[0]), float(local[1])
    wx = st["px"] + c * lx - s * ly
    wy = st["py"] + s * lx + c * ly
    return wx, wy


# --------------------------------------------------------------------------- #
# Config                                                                      #
# --------------------------------------------------------------------------- #


@dataclass
class ConstraintsConfig:
    """Constraints block of ``config/physics.yml``."""

    enabled: bool = True
    iterations: int = 4


def _load_constraints_config() -> ConstraintsConfig:
    """Read the ``constraints:`` block from ``config/physics.yml``.

    Walks up from this file to find the repo's ``config/physics.yml``;
    if no YAML is present we just return defaults so unit tests that
    construct a bare world still work.
    """
    here = Path(__file__).resolve()
    cfg_path: Path | None = None
    for parent in here.parents:
        cand = parent / "config" / "physics.yml"
        if cand.exists():
            cfg_path = cand
            break
    if cfg_path is None:
        return ConstraintsConfig()
    try:
        import yaml  # local import: tests outside the engine should not need PyYAML
    except ImportError:
        return ConstraintsConfig()
    try:
        with open(cfg_path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except OSError:
        return ConstraintsConfig()
    block = raw.get("constraints", {}) if isinstance(raw, dict) else {}
    if not isinstance(block, dict):
        block = {}
    return ConstraintsConfig(
        enabled=bool(block.get("enabled", True)),
        iterations=int(block.get("iterations", 4)),
    )


# --------------------------------------------------------------------------- #
# Solver                                                                      #
# --------------------------------------------------------------------------- #


class ConstraintSolver:
    """Position-based projected Gauss-Seidel constraint solver.

    Usage::

        solver = ConstraintSolver(iterations=4)
        solver.add(PinConstraint(chassis, wheel_l, (-15, 12), (0, 0)))
        solver.add(PinConstraint(chassis, wheel_r, (+15, 12), (0, 0)))
        for f in range(N):
            world.step(dt)
            solver.solve(world, dt)

    ``add`` returns a stable integer id; pass it (or the constraint
    object itself) to :meth:`remove` to detach a joint at runtime.
    Constraints whose accumulated impulse exceeds ``break_force`` (or
    whose strain exceeds ``break_strain`` for a distance constraint)
    are moved to ``self.broken``.
    """

    def __init__(self, iterations: int | None = None, *, enabled: bool | None = None) -> None:
        cfg = _load_constraints_config()
        self.iterations: int = cfg.iterations if iterations is None else int(iterations)
        self.enabled: bool = cfg.enabled if enabled is None else bool(enabled)
        self.constraints: list[Constraint] = []
        self.broken: list[Constraint] = []
        self._ids: dict[int, Constraint] = {}
        self._next_id: int = 1

    # -- add / remove --------------------------------------------------------

    def add(self, constraint: Constraint) -> int:
        """Register ``constraint`` and return a stable id."""
        cid = self._next_id
        self._next_id += 1
        self._ids[cid] = constraint
        self.constraints.append(constraint)
        return cid

    def remove(self, constraint_or_id: Any) -> None:
        """Remove a constraint by id or by object identity."""
        target: Constraint | None = None
        if isinstance(constraint_or_id, int):
            target = self._ids.pop(constraint_or_id, None)
        else:
            target = constraint_or_id
            # Drop any id mapping pointing at this object.
            stale = [k for k, v in self._ids.items() if v is target]
            for k in stale:
                del self._ids[k]
        if target is None:
            return
        try:
            self.constraints.remove(target)
        except ValueError:
            pass

    # -- main entry point ----------------------------------------------------

    def solve(self, world: "PhysicsWorld", dt: float) -> None:
        """Project all registered constraints onto the rigid state.

        No-op when ``self.enabled is False`` or ``iterations <= 0`` so
        callers can flip the constraint system off without unwiring it.
        """
        if not self.enabled:
            return
        if self.iterations <= 0:
            return
        if not self.constraints:
            return

        # Snapshot every body that participates so we can iterate in dicts
        # without re-reading the HullTree arrays each pass.  Identity-keyed
        # via id() so we share state between constraints that touch the
        # same body.
        state_by_body: dict[int, dict] = {}
        for c in self.constraints:
            for body in (c.body_a, c.body_b):
                key = id(body)
                if key not in state_by_body:
                    state_by_body[key] = _body_state(body)

        inv_dt = 1.0 / dt if dt > 0.0 else 0.0
        newly_broken: list[Constraint] = []

        for _iter in range(self.iterations):
            for c in self.constraints:
                if c in newly_broken:
                    continue
                sa = state_by_body[id(c.body_a)]
                sb = state_by_body[id(c.body_b)]
                if isinstance(c, PinConstraint):
                    impulse_mag = _solve_pin(c, sa, sb, inv_dt)
                elif isinstance(c, DistanceConstraint):
                    impulse_mag = _solve_distance(c, sa, sb, inv_dt)
                elif isinstance(c, WeldConstraint):
                    impulse_mag = _solve_weld(c, sa, sb, inv_dt)
                else:  # pragma: no cover - exhaustive over Constraint union
                    continue
                c.last_impulse = impulse_mag
                if _should_break(c, sa, sb, impulse_mag):
                    newly_broken.append(c)

        # Flush rigid state back to the HullTree.
        for c in self.constraints:
            for body in (c.body_a, c.body_b):
                st = state_by_body.get(id(body))
                if st is not None:
                    _write_back(body, st)
                    # Mark dirty once -- repeated writes are cheap regardless.
                    body.world.hulls.mark_dirty()

        # Mass-array dirty bookkeeping (in case any consumer caches it).
        if newly_broken:
            for c in newly_broken:
                try:
                    self.constraints.remove(c)
                except ValueError:
                    pass
                self.broken.append(c)


# --------------------------------------------------------------------------- #
# Per-constraint solve routines                                               #
# --------------------------------------------------------------------------- #


def _solve_pin(c: PinConstraint, sa: dict, sb: dict, inv_dt: float) -> float:
    """One Gauss-Seidel pass for a positional pin.

    Computes the world-space anchor mismatch ``Cn = pa - pb`` and applies a
    2x2 effective-mass correction.  Returns the magnitude of the applied
    impulse so callers can check ``break_force``.
    """
    pax, pay = _world_anchor(sa, c.local_anchor_a)
    pbx, pby = _world_anchor(sb, c.local_anchor_b)
    cx = pax - pbx
    cy = pay - pby
    if cx * cx + cy * cy < 1e-20:
        return 0.0

    # Lever arms from each body's centre to its world-space anchor.
    rax = pax - sa["px"]
    ray = pay - sa["py"]
    rbx = pbx - sb["px"]
    rby = pby - sb["py"]

    inv_ma = _inv_mass(sa)
    inv_mb = _inv_mass(sb)
    inv_ia = _inv_inertia(sa)
    inv_ib = _inv_inertia(sb)
    total_inv_m = inv_ma + inv_mb
    if total_inv_m <= 0.0 and inv_ia <= 0.0 and inv_ib <= 0.0:
        return 0.0

    # Effective-mass matrix K = (1/ma + 1/mb)*I + r_a x r_a' contribution
    # for a 2D rigid body.  For r = (rx, ry) the cross-product expansion is:
    #     K_xx = inv_m + inv_I_a * ray^2 + inv_I_b * rby^2
    #     K_yy = inv_m + inv_I_a * rax^2 + inv_I_b * rbx^2
    #     K_xy = -inv_I_a*rax*ray - inv_I_b*rbx*rby
    k11 = total_inv_m + inv_ia * ray * ray + inv_ib * rby * rby
    k22 = total_inv_m + inv_ia * rax * rax + inv_ib * rbx * rbx
    k12 = -inv_ia * rax * ray - inv_ib * rbx * rby

    det = k11 * k22 - k12 * k12
    if abs(det) < 1e-20:
        return 0.0
    inv_det = 1.0 / det
    # lambda = -K^{-1} * Baumgarte * C  (Baumgarte bleeds correction in).
    bx = _BAUMGARTE_BETA * cx
    by = _BAUMGARTE_BETA * cy
    lam_x = -(k22 * bx - k12 * by) * inv_det
    lam_y = -(-k12 * bx + k11 * by) * inv_det

    # Apply linear & angular position/velocity correction.  We treat the
    # lambda as a position correction lambda_p (which doubles as a velocity
    # impulse over dt -- the rigid bus needs both so the next world.step
    # doesn't immediately re-violate the constraint).
    _apply_anchor_correction(sa, sb, rax, ray, rbx, rby, lam_x, lam_y, inv_dt)
    return math.hypot(lam_x, lam_y) * (inv_dt if inv_dt > 0.0 else 1.0)


def _solve_distance(c: DistanceConstraint, sa: dict, sb: dict, inv_dt: float) -> float:
    pax, pay = _world_anchor(sa, c.local_anchor_a)
    pbx, pby = _world_anchor(sb, c.local_anchor_b)
    dx = pax - pbx
    dy = pay - pby
    dist = math.hypot(dx, dy)
    if dist < 1e-9:
        return 0.0
    nx = dx / dist
    ny = dy / dist
    err = dist - c.distance

    rax = pax - sa["px"]
    ray = pay - sa["py"]
    rbx = pbx - sb["px"]
    rby = pby - sb["py"]

    inv_ma = _inv_mass(sa)
    inv_mb = _inv_mass(sb)
    inv_ia = _inv_inertia(sa)
    inv_ib = _inv_inertia(sb)
    # Cross products of lever arms with the line normal.
    cra = rax * ny - ray * nx
    crb = rbx * ny - rby * nx
    effective_mass = inv_ma + inv_mb + inv_ia * cra * cra + inv_ib * crb * crb
    if effective_mass <= 0.0:
        return 0.0

    stiffness = max(0.0, min(1.0, c.stiffness))
    lam = -stiffness * _BAUMGARTE_BETA * err / effective_mass
    lx = lam * nx
    ly = lam * ny
    _apply_anchor_correction(sa, sb, rax, ray, rbx, rby, lx, ly, inv_dt)
    return abs(lam) * (inv_dt if inv_dt > 0.0 else 1.0)


def _solve_weld(c: WeldConstraint, sa: dict, sb: dict, inv_dt: float) -> float:
    # Positional half: same as the pin.
    pin_mag = _solve_pin(
        PinConstraint(c.body_a, c.body_b, c.local_anchor_a, c.local_anchor_b),
        sa,
        sb,
        inv_dt,
    )
    # Angular half: enforce angle_a - angle_b == target.
    inv_ia = _inv_inertia(sa)
    inv_ib = _inv_inertia(sb)
    inv_sum = inv_ia + inv_ib
    if inv_sum <= 0.0:
        return pin_mag
    err = (sa["angle"] - sb["angle"]) - c.target_relative_angle
    # Wrap into (-pi, pi] to take the short way round.
    while err > math.pi:
        err -= 2.0 * math.pi
    while err < -math.pi:
        err += 2.0 * math.pi
    lam_ang = -_BAUMGARTE_BETA * err / inv_sum
    sa["angle"] += inv_ia * lam_ang
    sb["angle"] -= inv_ib * lam_ang
    # Velocity correction for spin (rough velocity-impulse proxy).
    if inv_dt > 0.0:
        sa["omega"] += inv_ia * lam_ang * inv_dt
        sb["omega"] -= inv_ib * lam_ang * inv_dt
    return pin_mag + abs(lam_ang) * (inv_dt if inv_dt > 0.0 else 1.0)


def _apply_anchor_correction(
    sa: dict,
    sb: dict,
    rax: float,
    ray: float,
    rbx: float,
    rby: float,
    lx: float,
    ly: float,
    inv_dt: float,
) -> None:
    """Apply ``lambda = (lx, ly)`` to both bodies symmetrically.

    Position is corrected by ``+inv_m * lambda``; angle by ``+inv_I * (r x
    lambda)``.  Velocity / omega get the same correction multiplied by
    ``inv_dt`` so the rigid integrator next step does not immediately
    re-violate the constraint.
    """
    inv_ma = _inv_mass(sa)
    inv_mb = _inv_mass(sb)
    inv_ia = _inv_inertia(sa)
    inv_ib = _inv_inertia(sb)

    # Body A receives +lambda.
    sa["px"] += inv_ma * lx
    sa["py"] += inv_ma * ly
    sa["angle"] += inv_ia * (rax * ly - ray * lx)
    if inv_dt > 0.0:
        sa["vx"] += inv_ma * lx * inv_dt
        sa["vy"] += inv_ma * ly * inv_dt
        sa["omega"] += inv_ia * (rax * ly - ray * lx) * inv_dt
    # Body B receives -lambda.
    sb["px"] -= inv_mb * lx
    sb["py"] -= inv_mb * ly
    sb["angle"] -= inv_ib * (rbx * ly - rby * lx)
    if inv_dt > 0.0:
        sb["vx"] -= inv_mb * lx * inv_dt
        sb["vy"] -= inv_mb * ly * inv_dt
        sb["omega"] -= inv_ib * (rbx * ly - rby * lx) * inv_dt


def _should_break(c: Constraint, sa: dict, sb: dict, impulse_mag: float) -> bool:
    """Decide whether ``c`` exceeded its breaking threshold."""
    if isinstance(c, DistanceConstraint):
        pax, pay = _world_anchor(sa, c.local_anchor_a)
        pbx, pby = _world_anchor(sb, c.local_anchor_b)
        dist = math.hypot(pax - pbx, pay - pby)
        rest = max(c.distance, 1e-9)
        strain = abs(dist - rest) / rest
        if strain > c.break_strain:
            return True
        if impulse_mag > getattr(c, "break_force", float("inf")):
            return True
        return False
    # Pin / Weld: compare last impulse to break_force.
    return impulse_mag > getattr(c, "break_force", float("inf"))


__all__ = [
    "ConstraintSolver",
    "ConstraintsConfig",
    "DistanceConstraint",
    "PinConstraint",
    "WeldConstraint",
]
