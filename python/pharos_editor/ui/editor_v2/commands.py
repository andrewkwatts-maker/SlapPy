"""Concrete Command implementations for v2 undo/redo.

Each command owns the diff it needs to reverse itself — no lookup at
undo time so the operation stays deterministic across scene edits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SpawnEntityCommand:
    """Add an entity to the scene; undo removes it."""

    scene: Any
    entity: Any
    label: str = "Spawn Entity"

    def do(self) -> None:
        self.scene.add_entity(self.entity)

    def undo(self) -> None:
        try:
            self.scene.remove_entity(self.entity)
        except Exception:
            # Some Scene builds want the id, others want the entity.
            try:
                self.scene._entities.pop(self.entity.id, None)
            except Exception:
                pass


@dataclass
class DeleteEntityCommand:
    """Remove entities from the scene; undo restores each in original order."""

    scene: Any
    entities: list[Any]
    label: str = "Delete Entity"

    def do(self) -> None:
        for e in self.entities:
            try:
                self.scene.remove_entity(e)
            except Exception:
                try:
                    self.scene._entities.pop(e.id, None)
                except Exception:
                    pass

    def undo(self) -> None:
        for e in self.entities:
            try:
                self.scene.add_entity(e)
            except Exception:
                pass


@dataclass
class DuplicateEntityCommand:
    """Copy entities and add the copies; undo removes the copies."""

    scene: Any
    originals: list[Any]
    copies: list[Any] = field(default_factory=list)
    label: str = "Duplicate Entity"

    def do(self) -> None:
        # Materialise copies lazily so redo re-uses the same ones.
        if not self.copies:
            for src in self.originals:
                self.copies.append(self._clone(src))
        for c in self.copies:
            self.scene.add_entity(c)

    def undo(self) -> None:
        for c in self.copies:
            try:
                self.scene.remove_entity(c)
            except Exception:
                try:
                    self.scene._entities.pop(c.id, None)
                except Exception:
                    pass

    def _clone(self, src: Any) -> Any:
        try:
            from pharos_engine.entity import Entity

            copy = Entity(
                name=f"{getattr(src, 'name', 'Entity')} (copy)",
                position=getattr(src, "position", (0.0, 0.0)),
            )
            copy.rotation = float(getattr(src, "rotation", 0.0))
            copy.scale = float(getattr(src, "scale", 1.0))
            copy.tags = set(getattr(src, "tags", set()))
            return copy
        except Exception:
            return src
