"""Soft-import shim for a 3D physics broadphase + integrator — LL7.

Nova3D parity Sprint 18 (LL-batch): games and demos that want *some*
3D dynamics should not hard-depend on the untracked WIP
``slappyengine.physics`` tree. This module gives them a stable
Python-level surface with two implementations:

* ``backend="physics"`` — delegates to :mod:`slappyengine.physics`
  when that module is importable. Bodies keep their kinematic
  attributes on the shim side, and the real physics tree is used for
  the heavy lifting (contacts, constraints, per-pixel cells, …).
* ``backend="fallback"`` — a minimal built-in 3D world that does
  semi-implicit Euler integration, sweep-and-prune broadphase along
  the X axis, sphere-sphere collision response, and a naive ray-AABB
  test. This is a *prototyping* solver, not a real engine — it exists
  so downstream code can be written, tested and demoed even when the
  WIP tree is stripped from a build.

The soft-import contract mirrors what :mod:`slappyengine.render.bvh_3d`
does for JJ5's Frustum: try the richer thing; fall back on a
duck-typed local implementation; never raise at import time.

Public surface
--------------

* :func:`resolve_physics3_backend` — string tag for the currently
  chosen backend (``"physics"`` / ``"fallback"`` / ``"none"``).
* :class:`Body3D` — thin dataclass with position, orientation,
  linear/angular velocity, mass, and a shape descriptor. Deliberately
  small so it can be serialised trivially.
* :class:`World3D` — the wrapper class. ``World3D(backend="auto")``
  picks the best available backend at construction time.
* :class:`PhysicsBackendError` — raised only when both backends are
  unavailable (i.e. the numpy dependency itself is missing).

The 2D dynamics surface (``slappyengine.dynamics.World`` and
``slappyengine.dynamics.Body``) shaped this API: game code that
already talks to the 2D substrate should be able to swap in a
``World3D`` with only tuple-length changes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

try:
    import numpy as np
    _HAS_NUMPY = True
except Exception:  # pragma: no cover - numpy is a hard dep of the engine
    np = None  # type: ignore[assignment]
    _HAS_NUMPY = False


# ---------------------------------------------------------------------------
# Backend soft-imports
# ---------------------------------------------------------------------------

try:  # pragma: no cover - the WIP tree may or may not be importable
    from slappyengine import physics as _physics_pkg  # noqa: F401
    _HAS_PHYSICS = True
except Exception:  # pragma: no cover - stripped or broken WIP tree
    _physics_pkg = None  # type: ignore[assignment]
    _HAS_PHYSICS = False

try:
    from slappyengine.render.bvh_3d import AABB3D as _AABB3D  # noqa: F401
    _HAS_AABB3D = True
except Exception:  # pragma: no cover - stripped render tree
    _AABB3D = None  # type: ignore[assignment]
    _HAS_AABB3D = False


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PhysicsBackendError(RuntimeError):
    """Raised when neither the WIP physics tree nor the fallback works.

    In practice this only fires if numpy is unavailable — the fallback
    solver depends on numpy for its per-step arithmetic. If you're
    seeing this in a shipped build, the environment is broken.
    """


# ---------------------------------------------------------------------------
# resolve_physics3_backend
# ---------------------------------------------------------------------------


def resolve_physics3_backend() -> str:
    """Return the tag of the *preferred* 3D physics backend.

    Priorities:

    * ``"physics"`` — :mod:`slappyengine.physics` imported cleanly.
    * ``"fallback"`` — numpy is importable so the built-in shim can run.
    * ``"none"``    — neither is available. Callers should treat this
      as a build-error indicator; :class:`World3D` will still let you
      call it in the ``"fallback"`` slot but ``step()`` will raise
      :class:`PhysicsBackendError` immediately.

    The check is cheap enough to call every frame, but it is stable
    for the process lifetime, so caching the result at import time is
    the usual pattern.
    """
    if _HAS_PHYSICS:
        return "physics"
    if _HAS_NUMPY:
        return "fallback"
    return "none"


# ---------------------------------------------------------------------------
# Raycast / Sweep result dataclasses (NN4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RaycastHit:
    """Single ray/AABB intersection result returned by :meth:`World3D.raycast`.

    Attributes
    ----------
    body_id
        Handle of the hit body (matches :attr:`World3D.bodies` key).
    distance
        Parametric distance ``t`` along the ray such that the hit point is
        ``origin + t * direction``. Always ``>= 0``.
    point
        World-space hit position.
    normal
        Surface normal at the hit point — for AABB intersections this is
        the axis-aligned normal of the slab face the ray entered through.
    """

    body_id: int
    distance: float
    point: tuple[float, float, float]
    normal: tuple[float, float, float]


@dataclass(frozen=True)
class SweepHit:
    """Single AABB-sweep result returned by :meth:`World3D.sweep_aabb`.

    Attributes
    ----------
    body_id
        Handle of the static body the sweep hit.
    time_of_impact
        Parameter ``t`` in ``[0, 1]`` — ``0`` means the swept box already
        overlaps the target at start, ``1`` means the hit is at the far
        end of the sweep.
    contact_normal
        Axis-aligned normal of the target's slab face that was contacted.
    """

    body_id: int
    time_of_impact: float
    contact_normal: tuple[float, float, float]


# ---------------------------------------------------------------------------
# Body3D
# ---------------------------------------------------------------------------

_VALID_SHAPES = frozenset({"sphere", "box", "capsule", "mesh"})


@dataclass
class Body3D:
    """Minimal 3D rigid-body descriptor.

    The fields intentionally mirror the smallest useful subset of the
    2D ``dynamics.Body`` surface plus what a 3D solver needs (a
    quaternion instead of a scalar angle, angular velocity as a
    3-vector). Concrete solvers may store extra data internally but
    should never require callers to provide anything more than this.

    Attributes
    ----------
    position
        World-space centroid ``(x, y, z)``.
    orientation
        Unit quaternion ``(w, x, y, z)``. Defaults to identity.
    linear_velocity
        World-space linear velocity ``(vx, vy, vz)``.
    angular_velocity
        Body-space angular velocity ``(wx, wy, wz)``.
    mass
        Mass in kg. ``0.0`` marks a static body — the fallback solver
        will skip gravity and integration for zero-mass bodies.
    shape_kind
        One of ``"sphere"``, ``"box"``, ``"capsule"``, ``"mesh"``.
    shape_params
        Free-form ``dict`` interpreted by the collision path. For
        the fallback solver the recognised keys are:

        * sphere: ``radius`` (default ``0.5``)
        * box: ``half_extents`` (default ``(0.5, 0.5, 0.5)``)
        * capsule: ``radius``, ``half_height``
        * mesh: ``aabb_min``, ``aabb_max`` (fallback uses AABB only)
    """

    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    orientation: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)
    linear_velocity: tuple[float, float, float] = (0.0, 0.0, 0.0)
    angular_velocity: tuple[float, float, float] = (0.0, 0.0, 0.0)
    mass: float = 1.0
    shape_kind: str = "sphere"
    shape_params: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Normalise tuple lengths — friendly to callers that pass lists.
        self.position = _coerce3(self.position, "position")
        self.orientation = _coerce4(self.orientation, "orientation")
        self.linear_velocity = _coerce3(self.linear_velocity, "linear_velocity")
        self.angular_velocity = _coerce3(self.angular_velocity, "angular_velocity")
        self.mass = float(self.mass)
        if self.mass < 0.0:
            raise ValueError(
                f"Body3D.mass must be non-negative; got {self.mass}"
            )
        if self.shape_kind not in _VALID_SHAPES:
            raise ValueError(
                f"Body3D.shape_kind must be one of {sorted(_VALID_SHAPES)};"
                f" got {self.shape_kind!r}"
            )
        if not isinstance(self.shape_params, dict):
            raise TypeError(
                f"Body3D.shape_params must be a dict; got"
                f" {type(self.shape_params).__name__}"
            )

    # ------------------------------------------------------------------
    def radius(self) -> float:
        """Best-effort bounding radius used by the fallback broadphase."""
        if self.shape_kind == "sphere":
            return float(self.shape_params.get("radius", 0.5))
        if self.shape_kind == "box":
            he = self.shape_params.get("half_extents", (0.5, 0.5, 0.5))
            he = _coerce3(he, "half_extents")
            return math.sqrt(he[0] * he[0] + he[1] * he[1] + he[2] * he[2])
        if self.shape_kind == "capsule":
            r = float(self.shape_params.get("radius", 0.5))
            h = float(self.shape_params.get("half_height", 0.5))
            return r + h
        # mesh — use aabb corners if provided, else a unit ball.
        if "aabb_min" in self.shape_params and "aabb_max" in self.shape_params:
            mn = _coerce3(self.shape_params["aabb_min"], "aabb_min")
            mx = _coerce3(self.shape_params["aabb_max"], "aabb_max")
            dx = (mx[0] - mn[0]) * 0.5
            dy = (mx[1] - mn[1]) * 0.5
            dz = (mx[2] - mn[2]) * 0.5
            return math.sqrt(dx * dx + dy * dy + dz * dz)
        return 0.5

    def aabb(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """Loose axis-aligned bounding box in world space.

        Rotation is currently ignored (loose bound); the fallback
        broadphase overestimates for boxes and capsules by using the
        bounding sphere, which is fine for a prototype broadphase.
        """
        r = self.radius()
        p = self.position
        return (
            (p[0] - r, p[1] - r, p[2] - r),
            (p[0] + r, p[1] + r, p[2] + r),
        )

    def aabb3d(self) -> Any:
        """Return the KK1 :class:`AABB3D` if available, else a tuple pair."""
        mn, mx = self.aabb()
        if _HAS_AABB3D:
            return _AABB3D(min=mn, max=mx)
        return (mn, mx)


# ---------------------------------------------------------------------------
# World3D
# ---------------------------------------------------------------------------


class World3D:
    """Backend-agnostic 3D physics world.

    ``backend="auto"`` picks the best available implementation at
    construction time. Pass ``backend="fallback"`` to force the
    built-in shim even when the WIP tree is present — useful for
    deterministic tests. Pass ``backend="physics"`` to *require* the
    WIP tree and raise :class:`PhysicsBackendError` if it is missing.

    The public API is intentionally small:

    * :meth:`add_body` / :meth:`remove_body` — lifetime management.
    * :meth:`step` — advance simulation by ``dt`` seconds.
    * :meth:`query_aabb` / :meth:`query_ray` — spatial queries.

    Attributes are exposed so tests and tools can inspect state:

    * ``bodies`` — ``dict[int, Body3D]`` keyed by handle.
    * ``gravity`` — 3-vector.
    * ``backend`` — the tag returned by :func:`resolve_physics3_backend`
      at construction time.
    """

    def __init__(
        self,
        gravity: tuple[float, float, float] = (0.0, -9.81, 0.0),
        backend: str = "auto",
    ) -> None:
        self.gravity: tuple[float, float, float] = _coerce3(gravity, "gravity")
        self.bodies: dict[int, Body3D] = {}
        self._next_id: int = 0
        self.backend: str = self._pick_backend(backend)
        # If the real physics tree is chosen, we hold an optional real
        # PhysicsWorld — created lazily on first use in case the caller
        # is only using the shim for API surface.
        self._real_world: Any = None

    # ------------------------------------------------------------------
    @staticmethod
    def _pick_backend(requested: str) -> str:
        if requested == "auto":
            return resolve_physics3_backend()
        if requested == "physics":
            if not _HAS_PHYSICS:
                raise PhysicsBackendError(
                    "backend='physics' requested but slappyengine.physics"
                    " is not importable"
                )
            return "physics"
        if requested == "fallback":
            if not _HAS_NUMPY:
                raise PhysicsBackendError(
                    "backend='fallback' requested but numpy is not"
                    " importable"
                )
            return "fallback"
        raise ValueError(
            f"World3D.backend must be 'auto', 'physics' or 'fallback';"
            f" got {requested!r}"
        )

    # ------------------------------------------------------------------
    def add_body(self, body: Body3D) -> int:
        """Insert *body* and return its stable integer handle."""
        if not isinstance(body, Body3D):
            raise TypeError(
                f"World3D.add_body: expected Body3D; got"
                f" {type(body).__name__}"
            )
        handle = self._next_id
        self._next_id += 1
        self.bodies[handle] = body
        return handle

    def remove_body(self, handle: int) -> None:
        """Remove the body with the given handle.

        Raises :class:`KeyError` if the handle is unknown, matching
        the 2D dynamics surface.
        """
        if handle not in self.bodies:
            raise KeyError(f"World3D.remove_body: unknown handle {handle}")
        del self.bodies[handle]

    def get_body(self, handle: int) -> Body3D:
        """Return the body for *handle*."""
        return self.bodies[handle]

    def __len__(self) -> int:
        return len(self.bodies)

    def __contains__(self, handle: object) -> bool:
        return handle in self.bodies

    # ------------------------------------------------------------------
    def step(self, dt: float) -> None:
        """Advance the simulation by ``dt`` seconds.

        Delegates to :meth:`_step_physics` when the real backend is
        online, else to :meth:`_step_fallback`. Raises
        :class:`PhysicsBackendError` if the backend tag is ``"none"``.
        """
        if dt < 0.0:
            raise ValueError(f"World3D.step: dt must be non-negative; got {dt}")
        if self.backend == "physics":
            self._step_physics(dt)
        elif self.backend == "fallback":
            self._step_fallback(dt)
        else:
            raise PhysicsBackendError(
                "World3D.step: no backend available (numpy and physics"
                " both missing)"
            )

    # ------------------------------------------------------------------
    def query_aabb(
        self,
        aabb: Any,
    ) -> list[int]:
        """Return the handles of bodies whose bounding box overlaps *aabb*.

        *aabb* may be an :class:`AABB3D` (KK1), or any ``(min, max)``
        pair of 3-tuples. Uses the fallback SAP even when the WIP
        backend is online — good enough for editor-side picking.

        Raises
        ------
        TypeError
            If *aabb* is ``None``.
        """
        if aabb is None:
            raise TypeError("World3D.query_aabb: aabb must not be None")
        mn, mx = _aabb_bounds(aabb)
        hits: list[int] = []
        for h, body in self.bodies.items():
            bmn, bmx = body.aabb()
            if (
                bmn[0] <= mx[0] and bmx[0] >= mn[0] and
                bmn[1] <= mx[1] and bmx[1] >= mn[1] and
                bmn[2] <= mx[2] and bmx[2] >= mn[2]
            ):
                hits.append(h)
        return hits

    def query_ray(
        self,
        origin: tuple[float, float, float],
        direction: tuple[float, float, float],
    ) -> list[tuple[int, float]]:
        """Return sorted ``(handle, t_hit)`` tuples for ray intersections.

        Uses the slab test against each body's AABB (fallback) — good
        enough for editor picking and simple gameplay traces. ``t`` is
        the parameter along the ray such that the hit point equals
        ``origin + t * direction``. Only forward-facing hits (``t >= 0``)
        are returned.
        """
        o = _coerce3(origin, "origin")
        d = _coerce3(direction, "direction")
        # Guard against degenerate direction — return empty list rather
        # than diving through a divide-by-zero.
        d_len_sq = d[0] * d[0] + d[1] * d[1] + d[2] * d[2]
        if d_len_sq <= 0.0:
            return []
        out: list[tuple[int, float]] = []
        for h, body in self.bodies.items():
            mn, mx = body.aabb()
            t = _ray_aabb(o, d, mn, mx)
            if t is not None and t >= 0.0:
                out.append((h, t))
        out.sort(key=lambda pair: pair[1])
        return out

    # ------------------------------------------------------------------
    # NN4 — first-hit raycast + AABB sweep
    # ------------------------------------------------------------------
    def raycast(
        self,
        origin: tuple[float, float, float],
        direction: tuple[float, float, float],
        max_distance: float = float("inf"),
    ) -> "RaycastHit | None":
        """Return the first :class:`RaycastHit` along the ray, or ``None``.

        The ray is defined as ``P(t) = origin + t * direction`` for
        ``t >= 0``. Each body's AABB is slab-tested; the closest
        forward-facing hit within ``max_distance`` is returned.

        Parameters
        ----------
        origin
            Ray origin ``(x, y, z)``.
        direction
            Ray direction ``(dx, dy, dz)``. Need not be normalised —
            ``distance`` on the returned hit is in units of ``|direction|``.
        max_distance
            Upper bound on the returned hit distance. Defaults to +infinity.
            Must be ``>= 0``.

        Raises
        ------
        TypeError
            If *origin* or *direction* is ``None`` or not a 3-sequence.
        ValueError
            If *max_distance* is negative or *direction* has zero length.
        """
        if origin is None:
            raise TypeError("World3D.raycast: origin must not be None")
        if direction is None:
            raise TypeError("World3D.raycast: direction must not be None")
        o = _coerce3(origin, "origin")
        d = _coerce3(direction, "direction")
        if max_distance < 0.0:
            raise ValueError(
                f"World3D.raycast: max_distance must be >= 0; got {max_distance}"
            )
        d_len_sq = d[0] * d[0] + d[1] * d[1] + d[2] * d[2]
        if d_len_sq <= 0.0:
            raise ValueError("World3D.raycast: direction must be non-zero")
        if not self.bodies:
            return None

        best_t: float = math.inf
        best_handle: int | None = None
        best_axis: int = 0
        best_sign: float = 1.0  # sign of direction component on hit axis
        for h, body in self.bodies.items():
            mn, mx = body.aabb()
            hit = _ray_aabb_full(o, d, mn, mx)
            if hit is None:
                continue
            t, axis, entered_from_min = hit
            if t < 0.0 or t > max_distance:
                continue
            if t < best_t:
                best_t = t
                best_handle = h
                best_axis = axis
                # Normal points from the box outward on the entered face.
                best_sign = 1.0 if entered_from_min else -1.0
        if best_handle is None:
            return None
        point = (
            o[0] + best_t * d[0],
            o[1] + best_t * d[1],
            o[2] + best_t * d[2],
        )
        normal = [0.0, 0.0, 0.0]
        normal[best_axis] = -best_sign
        # If the ray started inside the AABB, best_t == 0 and axis == 0 with
        # entered_from_min=True — the returned normal is still a legal
        # axis-aligned unit vector.
        return RaycastHit(
            body_id=best_handle,
            distance=float(best_t),
            point=(float(point[0]), float(point[1]), float(point[2])),
            normal=(float(normal[0]), float(normal[1]), float(normal[2])),
        )

    def sweep_aabb(
        self,
        aabb_min: tuple[float, float, float],
        aabb_max: tuple[float, float, float],
        direction: tuple[float, float, float],
        distance: float,
    ) -> list["SweepHit"]:
        """Sweep an AABB along *direction* by *distance* and return hits.

        Uses the classic Minkowski trick: expand each static body's AABB by
        the moving box's half-extents, then do a ray-vs-expanded-AABB slab
        test using the moving box's centroid as the ray origin. The TOI is
        normalised to ``[0, 1]`` — ``0`` = already overlapping, ``1`` = at
        the far end of the sweep.

        Parameters
        ----------
        aabb_min, aabb_max
            Corners of the moving AABB in world space at ``t=0``.
        direction
            Sweep direction; the box moves ``distance * direction`` over
            the sweep. Need not be normalised.
        distance
            Non-negative scalar. ``0`` is legal (returns bodies already
            overlapping the moving AABB with TOI 0).

        Returns
        -------
        list[SweepHit]
            One entry per hit body, sorted by ascending
            ``time_of_impact``. Empty when the sweep clears every body.

        Raises
        ------
        TypeError
            If any of *aabb_min*, *aabb_max*, or *direction* is ``None`` or
            not a 3-sequence.
        ValueError
            If *distance* is negative or *aabb_min* > *aabb_max* on any
            axis.
        """
        if aabb_min is None:
            raise TypeError("World3D.sweep_aabb: aabb_min must not be None")
        if aabb_max is None:
            raise TypeError("World3D.sweep_aabb: aabb_max must not be None")
        if direction is None:
            raise TypeError("World3D.sweep_aabb: direction must not be None")
        mn = _coerce3(aabb_min, "aabb_min")
        mx = _coerce3(aabb_max, "aabb_max")
        d = _coerce3(direction, "direction")
        if distance < 0.0:
            raise ValueError(
                f"World3D.sweep_aabb: distance must be >= 0; got {distance}"
            )
        for axis in range(3):
            if mn[axis] > mx[axis]:
                raise ValueError(
                    f"World3D.sweep_aabb: aabb_min[{axis}]={mn[axis]} >"
                    f" aabb_max[{axis}]={mx[axis]}"
                )
        # Moving box centroid + half-extents.
        cx = (mn[0] + mx[0]) * 0.5
        cy = (mn[1] + mx[1]) * 0.5
        cz = (mn[2] + mx[2]) * 0.5
        hx = (mx[0] - mn[0]) * 0.5
        hy = (mx[1] - mn[1]) * 0.5
        hz = (mx[2] - mn[2]) * 0.5
        # Sweep displacement.
        dx = d[0] * distance
        dy = d[1] * distance
        dz = d[2] * distance
        out: list[SweepHit] = []
        for handle, body in self.bodies.items():
            bmn, bmx = body.aabb()
            # Expand static AABB by moving-box half-extents (Minkowski sum).
            emn = (bmn[0] - hx, bmn[1] - hy, bmn[2] - hz)
            emx = (bmx[0] + hx, bmx[1] + hy, bmx[2] + hz)
            hit = _sweep_ray_aabb(
                (cx, cy, cz), (dx, dy, dz), emn, emx
            )
            if hit is None:
                continue
            toi, axis, entered_from_min = hit
            if toi < 0.0 or toi > 1.0:
                continue
            normal = [0.0, 0.0, 0.0]
            # Outward normal on the contacted face: -axis if the sweep
            # entered through the min face (moving toward +axis), +axis
            # otherwise. This points from the static body outward toward
            # the moving box at the moment of contact.
            normal[axis] = -1.0 if entered_from_min else 1.0
            out.append(
                SweepHit(
                    body_id=handle,
                    time_of_impact=float(toi),
                    contact_normal=(
                        float(normal[0]),
                        float(normal[1]),
                        float(normal[2]),
                    ),
                )
            )
        out.sort(key=lambda s: s.time_of_impact)
        return out

    # ------------------------------------------------------------------
    # SAP broadphase — used by the fallback integrator and exposed for
    # testing.
    # ------------------------------------------------------------------
    def broadphase_pairs(self) -> list[tuple[int, int]]:
        """Return candidate collision pairs from a sweep-and-prune along X.

        Deterministic across runs: the returned pairs are sorted by
        ``(min_handle, max_handle)`` so tests can compare against a
        fixed expected set. This is the same SAP the fallback step
        uses; exposed so callers who want a different narrowphase
        can reuse it.
        """
        if not self.bodies:
            return []
        # Build (min_x, max_x, handle) tuples, sort by min_x.
        entries: list[tuple[float, float, int]] = []
        for h, body in self.bodies.items():
            mn, mx = body.aabb()
            entries.append((mn[0], mx[0], h))
        entries.sort(key=lambda e: e[0])
        pairs: list[tuple[int, int]] = []
        active: list[tuple[float, int]] = []  # (max_x, handle)
        for lo, hi, h in entries:
            # Retire actives whose max_x is behind the current lo.
            active = [(ax, ah) for (ax, ah) in active if ax >= lo]
            # Everything still active overlaps on the X sweep — needs a
            # Y/Z check for a proper AABB overlap.
            for _, ah in active:
                other = self.bodies[ah]
                omn, omx = other.aabb()
                bmn, bmx = self.bodies[h].aabb()
                if (
                    omn[1] <= bmx[1] and omx[1] >= bmn[1] and
                    omn[2] <= bmx[2] and omx[2] >= bmn[2]
                ):
                    a, b = (ah, h) if ah < h else (h, ah)
                    pairs.append((a, b))
            active.append((hi, h))
        pairs.sort()
        return pairs

    # ------------------------------------------------------------------
    # Fallback backend implementation
    # ------------------------------------------------------------------
    def _step_fallback(self, dt: float) -> None:
        """Semi-implicit Euler + sphere-sphere response for a single tick.

        The solver in three passes:

        1. Integrate: ``v += gravity * dt`` for dynamic bodies, then
           ``p += v * dt``.
        2. Broadphase: SAP along X yielding candidate pairs.
        3. Narrowphase (sphere-sphere only): resolve overlaps by
           pushing each body along the contact normal proportional to
           its inverse mass, and reflect the relative velocity with a
           restitution of 0.5.

        Non-sphere shapes still get integrated correctly — they just
        skip narrowphase in the fallback. That is intentional; a real
        3D solver is out of scope for this shim.
        """
        if not _HAS_NUMPY:
            raise PhysicsBackendError("fallback backend requires numpy")
        gx, gy, gz = self.gravity
        for body in self.bodies.values():
            if body.mass <= 0.0:
                continue  # static
            vx, vy, vz = body.linear_velocity
            vx += gx * dt
            vy += gy * dt
            vz += gz * dt
            body.linear_velocity = (vx, vy, vz)
            px, py, pz = body.position
            body.position = (px + vx * dt, py + vy * dt, pz + vz * dt)
        # Sphere-sphere narrowphase over SAP pairs.
        for a, b in self.broadphase_pairs():
            ba = self.bodies[a]
            bb = self.bodies[b]
            if ba.shape_kind != "sphere" or bb.shape_kind != "sphere":
                continue
            ra = float(ba.shape_params.get("radius", 0.5))
            rb = float(bb.shape_params.get("radius", 0.5))
            dx = bb.position[0] - ba.position[0]
            dy = bb.position[1] - ba.position[1]
            dz = bb.position[2] - ba.position[2]
            dist_sq = dx * dx + dy * dy + dz * dz
            r_sum = ra + rb
            if dist_sq >= r_sum * r_sum or dist_sq <= 1e-12:
                continue
            dist = math.sqrt(dist_sq)
            nx, ny, nz = dx / dist, dy / dist, dz / dist
            penetration = r_sum - dist
            inv_ma = 0.0 if ba.mass <= 0.0 else 1.0 / ba.mass
            inv_mb = 0.0 if bb.mass <= 0.0 else 1.0 / bb.mass
            inv_sum = inv_ma + inv_mb
            if inv_sum <= 0.0:
                continue
            push_a = penetration * (inv_ma / inv_sum)
            push_b = penetration * (inv_mb / inv_sum)
            ba.position = (
                ba.position[0] - nx * push_a,
                ba.position[1] - ny * push_a,
                ba.position[2] - nz * push_a,
            )
            bb.position = (
                bb.position[0] + nx * push_b,
                bb.position[1] + ny * push_b,
                bb.position[2] + nz * push_b,
            )
            # Reflect the relative velocity along the normal (impulse).
            rvx = bb.linear_velocity[0] - ba.linear_velocity[0]
            rvy = bb.linear_velocity[1] - ba.linear_velocity[1]
            rvz = bb.linear_velocity[2] - ba.linear_velocity[2]
            rel = rvx * nx + rvy * ny + rvz * nz
            if rel >= 0.0:
                continue  # already separating
            restitution = 0.5
            j = -(1.0 + restitution) * rel / inv_sum
            jx, jy, jz = j * nx, j * ny, j * nz
            ba.linear_velocity = (
                ba.linear_velocity[0] - jx * inv_ma,
                ba.linear_velocity[1] - jy * inv_ma,
                ba.linear_velocity[2] - jz * inv_ma,
            )
            bb.linear_velocity = (
                bb.linear_velocity[0] + jx * inv_mb,
                bb.linear_velocity[1] + jy * inv_mb,
                bb.linear_velocity[2] + jz * inv_mb,
            )

    # ------------------------------------------------------------------
    # Real-backend implementation
    # ------------------------------------------------------------------
    def _step_physics(self, dt: float) -> None:
        """Delegate to the WIP ``slappyengine.physics`` tree.

        The WIP tree targets a 2D per-pixel simulator today (see its
        ``PhysicsWorld``), so we can't hand raw Body3Ds through — the
        adapter is a *placeholder* that runs the fallback integrator
        for now, but keeps the delegation seam so a future sprint can
        drop in a real 3D step without changing the caller-visible
        API. This matches how :mod:`slappyengine.render.bvh_3d` used a
        duck-typed fallback for JJ5 integration until the Frustum
        landed.
        """
        # Placeholder: run the fallback so callers who pick the real
        # backend still get *something* moving. When the WIP tree
        # gains a 3D rigid-body path this branch becomes:
        #     self._real_world.step(dt)
        # and body state is mirrored back into `self.bodies` for
        # editor / tool visibility.
        self._step_fallback(dt)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce3(v: Any, name: str) -> tuple[float, float, float]:
    """Coerce *v* to a 3-tuple of floats or raise ``TypeError``."""
    try:
        a, b, c = v
    except Exception as exc:
        raise TypeError(
            f"{name} must be a 3-sequence; got {v!r}"
        ) from exc
    return (float(a), float(b), float(c))


def _coerce4(v: Any, name: str) -> tuple[float, float, float, float]:
    """Coerce *v* to a 4-tuple of floats or raise ``TypeError``."""
    try:
        a, b, c, d = v
    except Exception as exc:
        raise TypeError(
            f"{name} must be a 4-sequence; got {v!r}"
        ) from exc
    return (float(a), float(b), float(c), float(d))


def _aabb_bounds(
    aabb: Any,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Return ``(min, max)`` for either an :class:`AABB3D` or a tuple pair."""
    if _HAS_AABB3D and isinstance(aabb, _AABB3D):
        return aabb.min, aabb.max
    try:
        mn, mx = aabb
    except Exception as exc:
        raise TypeError(
            f"query_aabb: expected AABB3D or (min, max) pair; got {aabb!r}"
        ) from exc
    return _coerce3(mn, "aabb.min"), _coerce3(mx, "aabb.max")


def _ray_aabb(
    origin: tuple[float, float, float],
    direction: tuple[float, float, float],
    mn: tuple[float, float, float],
    mx: tuple[float, float, float],
) -> float | None:
    """Slab-test ray-AABB. Returns entry ``t`` or ``None`` if no hit.

    Uses the standard Kay-Kajiya slabs formulation with ±inf guards
    for axis-aligned rays. When the ray origin is inside the AABB
    the returned ``t`` is ``0.0``.
    """
    tmin = -math.inf
    tmax = math.inf
    for axis in range(3):
        o = origin[axis]
        d = direction[axis]
        lo = mn[axis]
        hi = mx[axis]
        if abs(d) < 1e-12:
            if o < lo or o > hi:
                return None
            continue
        inv_d = 1.0 / d
        t0 = (lo - o) * inv_d
        t1 = (hi - o) * inv_d
        if t0 > t1:
            t0, t1 = t1, t0
        if t0 > tmin:
            tmin = t0
        if t1 < tmax:
            tmax = t1
        if tmin > tmax:
            return None
    if tmax < 0.0:
        return None
    return max(tmin, 0.0)


def _ray_aabb_full(
    origin: tuple[float, float, float],
    direction: tuple[float, float, float],
    mn: tuple[float, float, float],
    mx: tuple[float, float, float],
) -> tuple[float, int, bool] | None:
    """Slab-test variant returning ``(t, axis, entered_from_min)``.

    ``axis`` is the axis of the slab whose entry plane the ray crossed
    last (the one determining the hit); ``entered_from_min`` is ``True``
    when the entry plane was the ``mn[axis]`` face — i.e. the ray was
    moving toward +axis at hit time.
    """
    tmin = -math.inf
    tmax = math.inf
    hit_axis = 0
    hit_from_min = True
    for axis in range(3):
        o = origin[axis]
        d = direction[axis]
        lo = mn[axis]
        hi = mx[axis]
        if abs(d) < 1e-12:
            if o < lo or o > hi:
                return None
            continue
        inv_d = 1.0 / d
        t0 = (lo - o) * inv_d
        t1 = (hi - o) * inv_d
        # Track which face is the entry face on this axis.
        entered_from_min_this = d > 0.0
        if t0 > t1:
            t0, t1 = t1, t0
            entered_from_min_this = not entered_from_min_this
        if t0 > tmin:
            tmin = t0
            hit_axis = axis
            hit_from_min = entered_from_min_this
        if t1 < tmax:
            tmax = t1
        if tmin > tmax:
            return None
    if tmax < 0.0:
        return None
    if tmin < 0.0:
        # Origin is inside the box — treat as an immediate hit at t=0.
        return 0.0, hit_axis, hit_from_min
    return tmin, hit_axis, hit_from_min


def _sweep_ray_aabb(
    origin: tuple[float, float, float],
    displacement: tuple[float, float, float],
    mn: tuple[float, float, float],
    mx: tuple[float, float, float],
) -> tuple[float, int, bool] | None:
    """AABB-sweep helper: ray *origin* → *origin + displacement*.

    Returns ``(toi, axis, entered_from_min)`` with ``toi`` in ``[0, 1]``
    when the swept ray hits *(mn, mx)*, or ``None`` when it misses.

    Handles the zero-displacement case by returning ``(0.0, ...)`` when
    the origin already lies inside the (Minkowski-expanded) AABB.
    """
    # Zero-displacement fast path: overlap iff origin ∈ [mn, mx].
    disp_len_sq = (
        displacement[0] * displacement[0]
        + displacement[1] * displacement[1]
        + displacement[2] * displacement[2]
    )
    if disp_len_sq <= 0.0:
        inside = all(mn[a] <= origin[a] <= mx[a] for a in range(3))
        if inside:
            return 0.0, 0, True
        return None
    hit = _ray_aabb_full(origin, displacement, mn, mx)
    if hit is None:
        return None
    toi, axis, entered_from_min = hit
    if toi > 1.0:
        return None
    return toi, axis, entered_from_min


__all__ = [
    "AABB3D",
    "Body3D",
    "PhysicsBackendError",
    "RaycastHit",
    "SweepHit",
    "World3D",
    "resolve_physics3_backend",
]


# Re-export AABB3D if available so callers don't have to reach into
# ``slappyengine.render.bvh_3d`` themselves. When missing, expose the
# name as ``None`` so ``isinstance(x, physics3_bridge.AABB3D)`` is a
# checkable-but-safe pattern.
AABB3D = _AABB3D
