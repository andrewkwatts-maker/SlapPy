"""Minimal XPBD-style node world that backs the dynamics primitives.

This is intentionally a thin substrate — just enough to step joints and
verify the unified type system. The full softbody package (lattices, contact,
rendering) layers on top of this and is documented separately.

Node arrays are kept as ``numpy`` matrices of shape ``(N, 2)`` so we can
vectorise distance/angular constraints. A node with ``inv_mass == 0`` is
treated as a kinematic anchor.
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np


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
        # Geometry / mass
        self.positions: np.ndarray = np.zeros((0, 2), dtype=np.float64)
        self.prev_positions: np.ndarray = np.zeros((0, 2), dtype=np.float64)
        self.velocities: np.ndarray = np.zeros((0, 2), dtype=np.float64)
        self.inv_masses: np.ndarray = np.zeros((0,), dtype=np.float64)
        # Bodies and joints
        self.bodies: list[Any] = []
        self.joints: list[Any] = []
        # Tuning
        self.gravity = np.asarray(gravity, dtype=np.float64)
        self.solver_iterations: int = 8
        # Time tracking
        self.frame: int = 0
        # Overdamping diagnostics: cache (joint_id, iters, damping) tuples we
        # have already warned about so step() doesn't spam the loop.
        self.warn_overdamping: bool = True
        self._overdamp_warned: set[tuple[int, int, float]] = set()

    # ------------------------------------------------------------------ nodes
    def add_node(self, pos: tuple[float, float], mass: float = 1.0) -> int:
        """Append a node, returning its absolute index. ``mass == 0`` pins it."""
        idx = self.positions.shape[0]
        p = np.asarray(pos, dtype=np.float64).reshape(1, 2)
        self.positions = np.vstack([self.positions, p])
        self.prev_positions = np.vstack([self.prev_positions, p])
        self.velocities = np.vstack(
            [self.velocities, np.zeros((1, 2), dtype=np.float64)]
        )
        inv_m = 0.0 if mass <= 0.0 else 1.0 / mass
        self.inv_masses = np.append(self.inv_masses, inv_m)
        return idx

    def add_nodes(
        self, positions: np.ndarray, masses: np.ndarray | float = 1.0
    ) -> tuple[int, int]:
        """Bulk-append nodes. Returns ``(offset, count)``."""
        positions = np.asarray(positions, dtype=np.float64).reshape(-1, 2)
        n = positions.shape[0]
        offset = self.positions.shape[0]
        if np.isscalar(masses):
            mass_arr = np.full((n,), float(masses), dtype=np.float64)
        else:
            mass_arr = np.asarray(masses, dtype=np.float64).reshape(-1)
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
        self.bodies.append(body)
        return body

    # ----------------------------------------------------------------- joints
    def add_joint(self, joint: Any) -> Any:
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
        """
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


__all__ = [
    "World",
    "SoftBodyWorld",
    "estimate_effective_damping",
    "OVERDAMPING_THRESHOLD",
]
