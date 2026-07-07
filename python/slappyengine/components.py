"""slappyengine.components — Composable Component protocol and ready-made components.

Usage
-----
    from slappyengine.components import ComponentBase, PhysicsComponent, CollisionComponent

    entity = Entity(name="player")
    phys = entity.add_component(PhysicsComponent(velocity=(100.0, 0.0)))
    coll = entity.add_component(CollisionComponent(shape=my_aabb))

Design
------
``Component`` is a ``typing.Protocol`` — any object that satisfies the structural
interface works, no inheritance required.

``ComponentBase`` is a concrete base class with all methods as no-ops so
developers can subclass and override only what they need.
"""

from __future__ import annotations

from typing import Callable, Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from slappyengine.entity import Entity


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class Component(Protocol):
    """Structural protocol for all components.

    Any class that exposes these attributes and methods satisfies the protocol
    without needing to inherit from it.
    """

    entity: "Entity | None"

    def on_attach(self, entity: "Entity") -> None: ...
    def on_detach(self, entity: "Entity") -> None: ...
    def update(self, dt: float) -> None: ...
    def on_event(self, event: object) -> None: ...


# ---------------------------------------------------------------------------
# Concrete base class
# ---------------------------------------------------------------------------

class ComponentBase:
    """No-op base class for components.

    Subclass this and override only the methods you need.  ``entity`` is set
    automatically by ``on_attach`` / cleared by ``on_detach``.
    """

    entity: "Entity | None" = None

    def on_attach(self, entity: "Entity") -> None:
        self.entity = entity

    def on_detach(self, entity: "Entity") -> None:
        self.entity = None

    def update(self, dt: float) -> None:
        pass

    def on_event(self, event: object) -> None:
        pass


# ---------------------------------------------------------------------------
# Ready-made components
# ---------------------------------------------------------------------------

class PhysicsComponent(ComponentBase):
    """Simple 2-D kinematic physics component.

    Applies ``velocity`` to ``entity.position`` each tick.  If the entity
    already has a ``velocity`` attribute when attached, that value is adopted
    as the initial velocity (allows migration of existing dynamic entities).

    Parameters
    ----------
    velocity:
        Initial velocity as ``(vx, vy)`` in world-units per second.
    gravity_scale:
        Multiplier applied to a global gravity vector (currently unused by
        this component — reserved for engine integration).
    """

    def __init__(
        self,
        velocity: tuple[float, float] = (0.0, 0.0),
        gravity_scale: float = 1.0,
    ) -> None:
        self.velocity: tuple[float, float] = velocity
        self.gravity_scale: float = gravity_scale

    def on_attach(self, entity: "Entity") -> None:
        super().on_attach(entity)
        # Adopt pre-existing velocity attribute so existing entities migrate cleanly.
        if hasattr(entity, "velocity"):
            existing = entity.velocity
            if isinstance(existing, (tuple, list)) and len(existing) == 2:
                self.velocity = (float(existing[0]), float(existing[1]))

    def update(self, dt: float) -> None:
        if self.entity is None:
            return
        vx, vy = self.velocity
        x, y = self.entity.position
        self.entity.position = (x + vx * dt, y + vy * dt)


class CollisionComponent(ComponentBase):
    """Collision shape registration component.

    Stores a collision shape and optional layer/mask for filtering.  Does not
    implement collision *detection* itself — that is the responsibility of the
    engine's collision system, which can query this component via
    ``entity.get_component(CollisionComponent)``.

    Parameters
    ----------
    shape:
        An ``AABBShape``, ``CircleShape``, or any shape object understood by the
        active collision system.  ``None`` means no collision.
    layer:
        Bit-field layer this entity belongs to.
    mask:
        Bit-field of layers this entity can collide with.
    on_collide:
        Optional callback ``(other_entity) -> None`` invoked by the collision
        system when a collision is detected.
    """

    def __init__(
        self,
        shape=None,
        layer: int = 0,
        mask: int = 0xFFFF,
        on_collide: "Callable | None" = None,
    ) -> None:
        self.shape = shape
        self.layer: int = layer
        self.mask: int = mask
        self.on_collide: "Callable | None" = on_collide


# ---------------------------------------------------------------------------
# RigidBodyComponent
# ---------------------------------------------------------------------------

import math as _math


class RigidBodyComponent(ComponentBase):
    """2-D rigid body with force / impulse / torque integration.

    Uses semi-implicit Euler: forces accumulate during a tick, then on
    :meth:`update` they integrate into velocity and the velocity advances the
    entity position.  ``damping`` is a per-tick multiplicative factor applied
    *after* force integration (``damping=1.0`` means "no damping",
    ``damping=0.5`` halves velocity each tick).  ``max_speed`` clamps the
    linear velocity magnitude after integration.

    The component also tracks ``angular_velocity`` with the same conventions
    (mass doubles as moment of inertia for simplicity — adequate for the
    arcade-style top-down vehicles this engine targets).
    """

    def __init__(
        self,
        mass: float = 1.0,
        damping: float = 1.0,
        angular_damping: float = 1.0,
        max_speed: float | None = None,
    ) -> None:
        self.mass: float = float(mass)
        self.damping: float = float(damping)
        self.angular_damping: float = float(angular_damping)
        self.max_speed: float | None = (
            float(max_speed) if max_speed is not None else None
        )
        self.velocity: list[float] = [0.0, 0.0]
        self.angular_velocity: float = 0.0
        self._force_acc: list[float] = [0.0, 0.0]
        self._torque_acc: float = 0.0

    # --- application API ---------------------------------------------------

    def apply_force(self, fx: float, fy: float) -> None:
        """Accumulate a force that integrates on the next :meth:`update`."""
        self._force_acc[0] += float(fx)
        self._force_acc[1] += float(fy)

    def apply_impulse(self, ix: float, iy: float) -> None:
        """Instantaneously change velocity by ``impulse / mass``."""
        m = self.mass if self.mass > 0.0 else 1.0
        self.velocity[0] += float(ix) / m
        self.velocity[1] += float(iy) / m

    def apply_torque(self, t: float) -> None:
        """Accumulate a torque that integrates on the next :meth:`update`."""
        self._torque_acc += float(t)

    # --- integration -------------------------------------------------------

    def update(self, dt: float) -> None:
        m = self.mass if self.mass > 0.0 else 1.0
        # Linear integration: v += a * dt, then damp, then clamp.
        ax = self._force_acc[0] / m
        ay = self._force_acc[1] / m
        self.velocity[0] = (self.velocity[0] + ax * dt) * self.damping
        self.velocity[1] = (self.velocity[1] + ay * dt) * self.damping
        if self.max_speed is not None:
            speed = _math.hypot(self.velocity[0], self.velocity[1])
            if speed > self.max_speed and speed > 0.0:
                scale = self.max_speed / speed
                self.velocity[0] *= scale
                self.velocity[1] *= scale
        # Angular integration (mass also acts as moment of inertia).
        alpha = self._torque_acc / m
        self.angular_velocity = (
            self.angular_velocity + alpha * dt
        ) * self.angular_damping
        # Reset accumulators so forces don't carry over.
        self._force_acc[0] = 0.0
        self._force_acc[1] = 0.0
        self._torque_acc = 0.0
        # Advance entity position if attached.  Supports list/tuple positions.
        if self.entity is not None and hasattr(self.entity, "position"):
            pos = self.entity.position
            if isinstance(pos, list) and len(pos) >= 2:
                pos[0] = pos[0] + self.velocity[0] * dt
                pos[1] = pos[1] + self.velocity[1] * dt
            elif isinstance(pos, tuple) and len(pos) >= 2:
                self.entity.position = (
                    pos[0] + self.velocity[0] * dt,
                    pos[1] + self.velocity[1] * dt,
                )
            if hasattr(self.entity, "rotation") and isinstance(
                self.entity.rotation, (int, float)
            ):
                self.entity.rotation = (
                    float(self.entity.rotation) + self.angular_velocity * dt
                )


# ---------------------------------------------------------------------------
# DeformableLayerComponent
# ---------------------------------------------------------------------------


class DeformableLayerComponent(ComponentBase):
    """Queue-based impact processor for a 2-D sprite / layer.

    Each ``apply_impact`` call appends a record to ``_pending_impacts``.
    On :meth:`update`, queued impacts are applied to the layer's RGBA buffer
    (``layer._image_data``) by reducing alpha within the impact radius.

    ``mode="auto"`` selects ``"elastic"`` if ``force < elastic_threshold``
    otherwise ``"plastic"``.  Only plastic impacts persistently reduce alpha.

    ``integrity`` is the mean alpha of the layer (normalised to ``[0, 1]``),
    a cheap proxy for "how intact this sprite still is".
    """

    def __init__(
        self,
        layer,
        elastic_threshold: float = 80.0,
        **legacy_kwargs,
    ) -> None:
        self.layer = layer
        self.elastic_threshold: float = float(elastic_threshold)
        self._pending_impacts: list[dict] = []
        self._integrity: float = 1.0
        # Backwards-compat: legacy Ochema Circuit vehicle.py passes a bag of
        # per-class deform config kwargs (`spring_decay`, `strength_map`,
        # `material_preset`, `sim_mode`, `destroy_mode`). The modern component
        # collapsed these into runtime config; retain them as plain attributes
        # so downstream code that reads them post-construction still works.
        # DO NOT REMOVE without a v1.0 deprecation cycle.
        self.spring_decay: float = float(legacy_kwargs.get("spring_decay", 0.94))
        self.strength_map = legacy_kwargs.get("strength_map", None)
        self.material_preset: str = str(legacy_kwargs.get("material_preset", "metal"))
        self.sim_mode: str = str(legacy_kwargs.get("sim_mode", "collision_triggered"))
        self.destroy_mode: str = str(legacy_kwargs.get("destroy_mode", "persist"))
        # Backwards-compat: legacy Ochema Circuit tests (tests/test_gpu_deform.py
        # and 20+ downstream vehicle-physics call sites) read
        # ``comp._stress_strain_buf`` — an ``(H, W, 2)`` float32 array where
        # channel 0 is per-pixel stress and channel 1 is per-pixel strain.
        # F1 initialised the buffer lazily on the first ``update()`` call.
        # DO NOT REMOVE without a v1.0 deprecation cycle.
        self._stress_strain_buf = None

    @property
    def integrity(self) -> float:
        return self._integrity

    def apply_impact(
        self,
        pos: tuple[float, float],
        force: float,
        radius: float = 5.0,
        mode: str = "auto",
    ) -> None:
        """Queue an impact to be processed on the next :meth:`update`."""
        resolved = mode
        if mode == "auto":
            resolved = "plastic" if force >= self.elastic_threshold else "elastic"
        self._pending_impacts.append(
            {
                "pos": (float(pos[0]), float(pos[1])),
                "force": float(force),
                "radius": float(radius),
                "mode": resolved,
            }
        )

    def update(self, dt: float) -> None:
        try:
            import numpy as _np
        except ImportError:  # pragma: no cover — numpy is a core dep
            self._pending_impacts.clear()
            return
        img = getattr(self.layer, "_image_data", None)
        # Backwards-compat: lazy-init `_stress_strain_buf` on first update
        # even when no impacts are pending. Ochema Circuit's gpu-deform test
        # suite (test_gpu_deform.py) asserts the buffer becomes non-None
        # after a single update(dt) call, independent of whether any
        # impacts were queued. Shape mirrors the layer's RGBA image
        # (H, W, 2 float32 — channel 0 stress, channel 1 strain).
        # DO NOT REMOVE without a v1.0 deprecation cycle.
        if img is not None and self._stress_strain_buf is None:
            h, w = img.shape[:2]
            self._stress_strain_buf = _np.zeros((h, w, 2), dtype=_np.float32)
        # Decay any existing stress/strain toward zero per tick (elastic
        # spring-back model). Uses the `spring_decay` legacy attribute.
        if self._stress_strain_buf is not None and self.spring_decay < 1.0:
            self._stress_strain_buf *= self.spring_decay
        if not self._pending_impacts:
            return
        if img is None:
            self._pending_impacts.clear()
            return
        h, w = img.shape[:2]
        yy, xx = _np.ogrid[:h, :w]
        for impact in self._pending_impacts:
            cx, cy = impact["pos"]
            r = max(impact["radius"], 1e-3)
            dist2 = (xx - cx) ** 2 + (yy - cy) ** 2
            mask = dist2 <= r * r
            if not mask.any():
                continue
            # Falloff: full force at centre, 0 at radius.
            falloff = _np.clip(1.0 - _np.sqrt(dist2) / r, 0.0, 1.0)
            force_field = (impact["force"] * falloff * mask).astype(_np.float32)
            # Backwards-compat: mirror force into `_stress_strain_buf` so
            # downstream tests can observe stress/strain per pixel. Elastic
            # impacts write into channel 0 (stress, spring-back), plastic
            # impacts write into channel 1 (strain, permanent).
            # DO NOT REMOVE without a v1.0 deprecation cycle.
            if self._stress_strain_buf is not None:
                if impact["mode"] == "plastic":
                    self._stress_strain_buf[:, :, 1] += force_field
                else:
                    self._stress_strain_buf[:, :, 0] += force_field
            if impact["mode"] != "plastic":
                continue  # elastic impacts don't permanently damage the alpha
            reduction = force_field.astype(_np.int32)
            alpha = img[:, :, 3].astype(_np.int32)
            alpha = _np.clip(alpha - reduction, 0, 255)
            img[:, :, 3] = alpha.astype(_np.uint8)
        self._pending_impacts.clear()
        # Recompute integrity from mean alpha.
        self._integrity = float(img[:, :, 3].mean()) / 255.0


# ---------------------------------------------------------------------------
# InputDrivenComponent
# ---------------------------------------------------------------------------


class InputDrivenComponent(ComponentBase):
    """Translates input-axis values into forces / torques on a sibling rigid body.

    On each :meth:`update` the component asks ``provider.get_axes()`` for the
    current axis dict, then for every key in ``axis_to_force`` /
    ``axis_to_torque`` it multiplies the axis value by the mapped vector /
    scalar and calls ``apply_force`` / ``apply_torque`` on the entity's
    :class:`RigidBodyComponent` (if one is attached).
    """

    def __init__(
        self,
        provider,
        axis_to_force: dict[str, tuple[float, float]] | None = None,
        axis_to_torque: dict[str, float] | None = None,
    ) -> None:
        self.provider = provider
        self.axis_to_force: dict[str, tuple[float, float]] = (
            dict(axis_to_force) if axis_to_force else {}
        )
        self.axis_to_torque: dict[str, float] = (
            dict(axis_to_torque) if axis_to_torque else {}
        )

    def update(self, dt: float) -> None:
        if self.entity is None:
            return
        rb = None
        if hasattr(self.entity, "get_component"):
            rb = self.entity.get_component(RigidBodyComponent)
        if rb is None:
            return  # silent when no rigid body is attached
        try:
            axes = self.provider.get_axes() or {}
        except Exception:
            axes = {}
        for axis, (fx, fy) in self.axis_to_force.items():
            value = float(axes.get(axis, 0.0))
            if value == 0.0:
                continue
            rb.apply_force(value * fx, value * fy)
        for axis, torque in self.axis_to_torque.items():
            value = float(axes.get(axis, 0.0))
            if value == 0.0:
                continue
            rb.apply_torque(value * torque)


