"""
Typed base class for entity scripts.

Usage:
    class PlayerScript(Script):
        def on_start(self, entity):
            self.speed = 200.0

        def on_update(self, entity, dt):
            # move entity
            ...

    entity.attach_script(PlayerScript())
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pharos_engine.entity import Entity


class Script:
    """Base class for entity behaviour scripts.

    Override any lifecycle method you need. All methods are no-ops by default.
    """

    def on_start(self, entity: "Entity") -> None:
        """Called once when the script is first attached or the scene starts."""

    def on_update(self, entity: "Entity", dt: float) -> None:
        """Called every frame. dt is seconds since last frame."""

    def on_event(self, entity: "Entity", event: object) -> None:
        """Called when scene.events.emit() fires an event."""

    def on_destroy(self, entity: "Entity") -> None:
        """Called when the entity is removed from the scene."""

    def on_collision(self, entity: "Entity", other: "Entity") -> None:
        """Called when entity collides with another entity (if CollisionManager active)."""


class ScriptComponent(Script):
    """Script that is also a Component — can be added via entity.add_component()."""

    entity: "Entity | None" = None

    def on_attach(self, entity: "Entity") -> None:
        self.entity = entity
        self.on_start(entity)

    def on_detach(self, entity: "Entity") -> None:
        self.on_destroy(entity)
        self.entity = None

    def update(self, dt: float) -> None:
        if self.entity is not None:
            self.on_update(self.entity, dt)
