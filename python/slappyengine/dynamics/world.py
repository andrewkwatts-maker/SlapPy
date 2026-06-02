"""Minimal XPBD-style node world that backs the dynamics primitives.

This is intentionally a thin substrate — just enough to step joints and
verify the unified type system. The full softbody package (lattices, contact,
rendering) layers on top of this and is documented separately.

Node arrays are kept as ``numpy`` matrices of shape ``(N, 2)`` so we can
vectorise distance/angular constraints. A node with ``inv_mass == 0`` is
treated as a kinematic anchor.
"""
from __future__ import annotations

import math
import warnings
from typing import Any, Protocol, runtime_checkable

import numpy as np

from ._validation import (
    validate_body,
    validate_dt,
    validate_gravity,
    validate_joint,
    validate_mass,
    validate_position,
    validate_solver_iterations,
)


def estimate_effective_damping(damping: float, iters: int) -> float:
    """Effective per-step damping ratio after N iterations of multiplicative
    per-iter damping.

    XPBD position damping is applied as a scalar multiplier ``(1 - damping)``
    on every constraint correction *inside* the inner solver loop. After
    ``iters`` passes the constraint correction has been attenuated by
    ``(1 - damping)^iters``, so the *effective* per-step damping —
    i.e. the fraction of the elastic response that has been bled out within
    a single ``World.step`` — is::

        effective = 1 - (1 - damping)^iters

    Returns a value in ``[0, 1]`` where ``1`` means the constraint
    correction has been fully cancelled inside one step (critical
    over-damping; the constraint behaves like a stiff weld with no
    oscillation). Values much above ``0.5`` mean an oscillator will
    converge to equilibrium within a single step and look like dead noise
    rather than a spring.

    The ``damping`` argument is clamped to ``[0, 1]`` and ``iters`` is
    clamped to ``max(1, iters)`` to mirror the solver's own clamping in
    :meth:`World.step`.
    """
    d = max(0.0, min(1.0, float(damping)))
    n = max(1, int(iters))
    return 1.0 - (1.0 - d) ** n


# Anything above this is "the spring degenerates within one step" territory.
OVERDAMPING_THRESHOLD: float = 0.5


# Process-wide throttle for the over-damp RuntimeWarning.
#
# Without this, every joint (and every World) re-emits the same diagnostic on
# its first step, which buries other warnings during demo smoke tests
# (hello_rope / hello_joint were responsible for 71 emissions in the v0.3
# sprint G suite). The key is the *category* of the warning — the same
# ``(kind, damping, iters)`` combination always produces the same effective
# per-step damping — so reporting it once per process is sufficient.
#
# Tests that need to observe the warning (notably
# ``test_spring_with_damping_loses_energy``) call
# :func:`_reset_warning_cache` in a fixture to clear this set.
_OVER_DAMPED_WARNED: set[tuple[str, float, int]] = set()


def _reset_warning_cache() -> None:
    """Clear the module-level over-damp warning throttle.

    Intended for test fixtures that want to re-observe the warning. The
    throttle is process-wide, so without an explicit reset only the first
    test to trigger the diagnostic would see it.
    """
    _OVER_DAMPED_WARNED.clear()


class World:
    """Container of nodes + bodies + joints with a single :meth:`step` loop.

    Coordinates are 2D — the dynamics primitives target the engine's
    planar XPBD layer; the rust ``_core.physics`` rigid-body world covers
    full 3D. Mixing both is intentional.
    """

    #: When ``True`` (default) :meth:`step` emits a :class:`RuntimeWarning`
    #: on its first invocation if any spring / distance joint's effective
    #: per-step damping (see :func:`estimate_effective_damping`) exceeds
    #: :data:`OVERDAMPING_THRESHOLD`. Set to ``False`` to silence.
    warn_overdamping: bool = True

    def __init__(self, gravity: tuple[float, float] = (0.0, -9.81)) -> None:
        gx, gy = validate_gravity("gravity", "World.__init__", gravity)
        # Geometry / mass
        self.positions: np.ndarray = np.zeros((0, 2), dtype=np.float64)
        self.prev_positions: np.ndarray = np.zeros((0, 2), dtype=np.float64)
        self.velocities: np.ndarray = np.zeros((0, 2), dtype=np.float64)
        self.inv_masses: np.ndarray = np.zeros((0,), dtype=np.float64)
        # Bodies and joints
        self.bodies: list[Any] = []
        self.joints: list[Any] = []
        # Tuning
        self.gravity = np.asarray((gx, gy), dtype=np.float64)
        # ``_solver_iterations`` is the backing field for the validated
        # property below. Set the private attr directly here so the
        # property setter doesn't run before the instance is finished
        # initialising.
        self._solver_iterations: int = 8
        # Time tracking
        self.frame: int = 0
        # Overdamping diagnostics: cache (joint_id, iters, damping) tuples we
        # have already warned about so step() doesn't spam the loop.
        self.warn_overdamping: bool = True
        self._overdamp_warned: set[tuple[int, int, float]] = set()

    # --------------------------------------------------------- solver_iterations
    @property
    def solver_iterations(self) -> int:
        """Number of XPBD passes per :meth:`step`.

        Validated at assignment so a typo like ``world.solver_iterations
        = 1e6`` fails loudly at the authoring site instead of grinding
        the solver to a halt several frames later.
        """
        return self._solver_iterations

    @solver_iterations.setter
    def solver_iterations(self, value: Any) -> None:
        self._solver_iterations = validate_solver_iterations(
            "solver_iterations", "World.solver_iterations", value
        )

    # ------------------------------------------------------------------ nodes
    def add_node(self, pos: tuple[float, float], mass: float = 1.0) -> int:
        """Append a node, returning its absolute index. ``mass == 0`` pins it.

        Raises
        ------
        TypeError
            If ``pos`` is not a 2-sequence of floats or ``mass`` is not a
            real number.
        ValueError
            If ``pos`` contains NaN/inf or ``mass`` is NaN/inf/negative.
        """
        x, y = validate_position("pos", "World.add_node", pos)
        m = validate_mass("mass", "World.add_node", mass)
        idx = self.positions.shape[0]
        p = np.asarray((x, y), dtype=np.float64).reshape(1, 2)
        self.positions = np.vstack([self.positions, p])
        self.prev_positions = np.vstack([self.prev_positions, p])
        self.velocities = np.vstack(
            [self.velocities, np.zeros((1, 2), dtype=np.float64)]
        )
        inv_m = 0.0 if m <= 0.0 else 1.0 / m
        self.inv_masses = np.append(self.inv_masses, inv_m)
        return idx

    def add_nodes(
        self, positions: np.ndarray, masses: np.ndarray | float = 1.0
    ) -> tuple[int, int]:
        """Bulk-append nodes. Returns ``(offset, count)``.

        Raises
        ------
        TypeError
            If ``positions`` is not array-coercible to ``(N, 2)`` floats
            or ``masses`` is neither a scalar nor a length-``N`` array.
        ValueError
            If any entry of ``positions`` is non-finite, ``masses`` is
            negative / NaN / inf, or ``masses`` is an array whose length
            does not match ``positions``.
        """
        if positions is None:
            raise TypeError(
                "World.add_nodes: positions must be array-like; got None"
            )
        try:
            positions = np.asarray(positions, dtype=np.float64).reshape(-1, 2)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"World.add_nodes: positions must be array-coercible to "
                f"(N, 2) floats; got {type(positions).__name__}"
            ) from exc
        if not np.isfinite(positions).all():
            raise ValueError(
                "World.add_nodes: positions must be finite "
                "(no NaN or inf entries)"
            )
        n = positions.shape[0]
        offset = self.positions.shape[0]
        if isinstance(masses, bool):
            raise TypeError(
                "World.add_nodes: masses must be a real number or array; "
                "got bool"
            )
        if np.isscalar(masses):
            m_scalar = validate_mass("masses", "World.add_nodes", masses)
            mass_arr = np.full((n,), m_scalar, dtype=np.float64)
        else:
            try:
                mass_arr = np.asarray(masses, dtype=np.float64).reshape(-1)
            except (TypeError, ValueError) as exc:
                raise TypeError(
                    f"World.add_nodes: masses must be array-coercible to "
                    f"floats; got {type(masses).__name__}"
                ) from exc
            if mass_arr.shape[0] != n:
                raise ValueError(
                    f"World.add_nodes: masses length {mass_arr.shape[0]} "
                    f"does not match positions length {n}"
                )
            if not np.isfinite(mass_arr).all():
                raise ValueError(
                    "World.add_nodes: masses must be finite "
                    "(no NaN or inf entries)"
                )
            if (mass_arr < 0.0).any():
                raise ValueError(
                    "World.add_nodes: masses must be >= 0; "
                    "got at least one negative entry"
                )
        inv_m = np.where(mass_arr <= 0.0, 0.0, 1.0 / np.where(mass_arr > 0, mass_arr, 1.0))
        self.positions = np.vstack([self.positions, positions])
        self.prev_positions = np.vstack([self.prev_positions, positions.copy()])
        self.velocities = np.vstack(
            [self.velocities, np.zeros((n, 2), dtype=np.float64)]
        )
        self.inv_masses = np.concatenate([self.inv_masses, inv_m])
        return offset, n

    # ----------------------------------------------------------------- bodies
    def register_body(self, body: Any) -> Any:
        """Register a :class:`Body` with the world.

        Raises
        ------
        TypeError
            If ``body`` is not a :class:`Body` instance.
        ValueError
            If ``body`` is already registered (same ``id``), or if its
            node slice (``node_offset``..``node_offset + node_count``)
            extends past the world's current node count.
        """
        validate_body("body", "World.register_body", body)
        for existing in self.bodies:
            if existing is body:
                raise ValueError(
                    f"World.register_body: body id={id(body)} "
                    f"(label={body.label!r}) is already registered"
                )
        n_nodes = self.positions.shape[0]
        node_offset = int(body.node_offset)
        node_count = int(body.node_count)
        if node_offset < 0:
            raise ValueError(
                f"World.register_body: body.node_offset must be >= 0; "
                f"got {node_offset}"
            )
        if node_count < 0:
            raise ValueError(
                f"World.register_body: body.node_count must be >= 0; "
                f"got {node_count}"
            )
        if node_count > 0 and node_offset + node_count > n_nodes:
            raise ValueError(
                f"World.register_body: body node slice "
                f"[{node_offset}, {node_offset + node_count}) extends "
                f"past world node count {n_nodes}; add the nodes first"
            )
        self.bodies.append(body)
        return body

    # ----------------------------------------------------------------- joints
    def add_joint(self, joint: Any) -> Any:
        """Append a :class:`JointSpec` to the world's constraint list.

        Raises
        ------
        TypeError
            If ``joint`` is not a :class:`JointSpec` instance.
        ValueError
            If ``joint.node_a`` or ``joint.node_b`` index a node that has
            not yet been added to the world (>= ``len(positions)``).
        """
        validate_joint("joint", "World.add_joint", joint)
        n_nodes = self.positions.shape[0]
        if joint.node_a >= n_nodes:
            raise ValueError(
                f"World.add_joint: joint.node_a={joint.node_a} references "
                f"a node that does not exist (world has {n_nodes} nodes); "
                f"add the node first"
            )
        if joint.node_b >= n_nodes:
            raise ValueError(
                f"World.add_joint: joint.node_b={joint.node_b} references "
                f"a node that does not exist (world has {n_nodes} nodes); "
                f"add the node first"
            )
        self.joints.append(joint)
        return joint

    # ------------------------------------------------------ overdamp warning
    def _check_overdamping(self) -> None:
        """Emit ``RuntimeWarning`` for over-damped spring / distance joints.

        Effective per-step damping is computed via
        :func:`estimate_effective_damping`; values above
        :data:`OVERDAMPING_THRESHOLD` mean the constraint correction has
        been bled down to near-equilibrium within a single ``step`` call,
        which silently turns a spring into a stiff weld.

        Throttling is two-tier: the *process-wide* :data:`_OVER_DAMPED_WARNED`
        set is keyed on ``(kind, damping, iters)`` so the same configuration
        emits at most one warning across the entire interpreter session
        (this is what stops demo smoke tests from logging 70+ identical
        diagnostics). The *per-World* ``_overdamp_warned`` set is kept for
        backward compatibility with callers that introspect it.
        """
        if not self.warn_overdamping:
            return
        iters = max(1, int(self.solver_iterations))
        for joint in self.joints:
            kind = getattr(joint, "kind", None)
            if kind not in ("spring", "distance"):
                continue
            damping = float(getattr(joint, "damping", 0.0))
            key = (id(joint), iters, damping)
            if key in self._overdamp_warned:
                continue
            effective = estimate_effective_damping(damping, iters)
            if effective > OVERDAMPING_THRESHOLD:
                self._overdamp_warned.add(key)
                global_key = (str(kind), damping, iters)
                if global_key in _OVER_DAMPED_WARNED:
                    # Same (kind, damping, iters) already reported earlier
                    # in this process — silently mark this joint resolved.
                    continue
                _OVER_DAMPED_WARNED.add(global_key)
                warnings.warn(
                    (
                        f"slappyengine.dynamics: joint id={id(joint)} "
                        f"(kind={kind!r}) is likely over-damped — "
                        f"damping={damping!r} * solver_iterations={iters} "
                        f"gives effective per-step damping "
                        f"{effective:.3f} > {OVERDAMPING_THRESHOLD:.2f}. "
                        f"XPBD position damping is applied per iteration; "
                        f"the spring will converge to equilibrium inside "
                        f"one step and look like noise rather than "
                        f"oscillation. Lower joint.damping (e.g. to "
                        f"{max(0.001, 0.3 / iters):.3f}) or reduce "
                        f"world.solver_iterations (e.g. to 1) to keep "
                        f"iters * damping <= 0.3."
                    ),
                    RuntimeWarning,
                    stacklevel=3,
                )

    # --------------------------------------------------------------- stepping
    def step(self, dt: float) -> None:
        """Integrate one frame using XPBD-style position projection.

        1. Predict positions using gravity + current velocity.
        2. Iterate the joint list ``solver_iterations`` times, calling
           :func:`slappyengine.dynamics.joint.resolve` to project each
           constraint.
        3. Recover velocity from the position delta.

        Raises
        ------
        TypeError
            If ``dt`` is not a real number (bool refused).
        ValueError
            If ``dt`` is NaN/inf, ≤ 0, or > 1.0 second.
        """
        dt = validate_dt("dt", "World.step", dt)
        self._check_overdamping()
        if self.positions.shape[0] == 0:
            self.frame += 1
            return
        from .joint import resolve as _resolve_joint

        inv_m = self.inv_masses[:, None]
        # 1. Integrate
        self.velocities += self.gravity[None, :] * dt * (inv_m > 0)
        self.prev_positions = self.positions.copy()
        self.positions = self.positions + self.velocities * dt * (inv_m > 0)

        # 2. Constraint solve
        for _ in range(max(1, self.solver_iterations)):
            for joint in self.joints:
                if not getattr(joint, "enabled", True):
                    continue
                _resolve_joint(joint, self, dt)

        # 3. Velocity recovery
        new_vel = (self.positions - self.prev_positions) / max(dt, 1e-9)
        # Preserve zeros on pinned nodes
        pinned = (self.inv_masses == 0.0)
        new_vel[pinned] = 0.0
        self.velocities = new_vel
        self.frame += 1


# Backwards-compat alias matching the plan's `SoftBodyWorld` references.
SoftBodyWorld = World


# ---------------------------------------------------------------------------
# WorldLike protocol — structural type used by ``solve_ik``,
# ``resolve_joint_specs``, ``studio.dynamics_stage`` and other callers that
# accept *either* a :class:`World` (XPBD dynamics substrate) or a
# softbody-style world (e.g. ``slappyengine.softbody.SoftBodyWorld``).
#
# The de-facto duck type historically had a sparse interface:
#
# * dynamics.World exposes ``positions`` + ``step(dt)`` + ``gravity``.
# * softbody.SoftBodyWorld exposes ``nodes.pos`` + ``gravity`` (its step lives
#   at module scope: ``slappyengine.softbody.step(world)``).
#
# Because :class:`typing.Protocol` cannot express "either A or B" naturally,
# we declare ``WorldLike`` with the minimum stable surface — ``gravity`` —
# plus the two optional accessors. Callers that need a richer surface
# (``positions``, ``nodes``, ``step``) can spell that out as a stricter
# Protocol; :func:`solve_ik` deliberately stays loose because it only
# touches the position view.
# ---------------------------------------------------------------------------


@runtime_checkable
class WorldLike(Protocol):
    """Structural type accepted by dynamics solvers, IK, and studio helpers.

    A *WorldLike* is any object that exposes a ``gravity`` vector. In
    practice the engine's two world flavours match:

    * :class:`slappyengine.dynamics.World` (this module) — the XPBD
      substrate. Has ``positions: np.ndarray``, ``step(dt)``, ``gravity``.
    * :class:`slappyengine.softbody.SoftBodyWorld` — has ``nodes.pos`` and
      ``gravity``; stepping goes through the module-level
      ``slappyengine.softbody.step(world)`` function.

    The protocol is intentionally minimal so callers can opt in to the
    parts they need:

    * :func:`solve_ik` reads positions via ``getattr(world, 'positions',
      None) or world.nodes.pos`` — no ``step`` required.
    * :func:`resolve_joint_specs` dispatches by ``isinstance(world,
      World)`` first, then falls back to a ``beams.append`` duck for the
      softbody path.
    * :func:`slappyengine.studio.dynamics_stage` only accepts
      :class:`World` because it owns the step loop.

    Marked ``@runtime_checkable`` so user code can call
    ``isinstance(obj, WorldLike)`` for defensive duck-typing. Note that
    runtime-check only verifies the attribute exists, not its
    signature/type.
    """

    gravity: Any


@runtime_checkable
class DynamicsWorldLike(WorldLike, Protocol):
    """Tighter Protocol — a :class:`World`-shaped object.

    Adds the dynamics-style ``positions`` array + ``step(dt)`` method on
    top of :class:`WorldLike`. This is the Protocol used by
    :func:`slappyengine.studio.dynamics_stage`'s default PIL renderer
    (``positions``, ``inv_masses``, ``joints``) and by callers that own
    their own step loop (``world.step(dt)``).
    """

    positions: np.ndarray
    inv_masses: np.ndarray
    joints: list[Any]

    def step(self, dt: float) -> None: ...  # pragma: no cover — Protocol stub


__all__ = [
    "DynamicsWorldLike",
    "OVERDAMPING_THRESHOLD",
    "SoftBodyWorld",
    "World",
    "WorldLike",
    "estimate_effective_damping",
]
