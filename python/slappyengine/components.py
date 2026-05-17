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
