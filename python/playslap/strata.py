"""
Strata layer system for Bullet Strata's parallel-dimension mechanic.

The arena has N overlapping world layers (e.g. Physical, Cyber Void, Ruined Realm).
Each entity has a strata_layer: int attribute.
The renderer dims entities not on the camera's active layer.

Usage:
    strata = StrataWorld([
        StrataLayer("Physical World",  0, (1.0, 1.0, 1.0, 1.0), parallax=1.0),
        StrataLayer("Cyber Void",      1, (0.4, 0.6, 1.0, 0.9), parallax=1.1),
        StrataLayer("Ruined Realm",    2, (1.0, 0.35, 0.2, 0.9), parallax=0.9),
    ])
    scene.strata = strata
    strata.set_active(0)
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class StrataLayer:
    name: str
    index: int
    tint: tuple[float, float, float, float]   # RGBA multiplier for entities on this layer
    parallax: float = 1.0                      # scroll speed multiplier vs camera


class StrataWorld:
    """
    Manages multiple parallel world layers.
    Attached to Scene as scene.strata.
    """
    def __init__(self, layers: list[StrataLayer], inactive_dim: float = 0.35):
        self.layers = layers
        self.active_index: int = 0
        self.inactive_dim = inactive_dim  # alpha multiplier for entities on inactive layers
        self._phase_transitions: dict[int, float] = {}  # entity_id → transition alpha (0→1)

    @property
    def active_layer(self) -> StrataLayer:
        return self.layers[self.active_index]

    def set_active(self, index: int) -> None:
        self.active_index = index % len(self.layers)

    def get_layer(self, index: int) -> StrataLayer | None:
        if 0 <= index < len(self.layers):
            return self.layers[index]
        return None

    def entity_visibility_alpha(self, entity) -> float:
        """
        Returns the alpha multiplier to apply when rendering this entity.
        Entities on the active layer → 1.0
        Entities on inactive layers → inactive_dim (e.g. 0.35)
        Entities mid-phase → lerp
        """
        el = getattr(entity, "strata_layer", 0)
        if el == self.active_index:
            return 1.0
        # Check if mid-transition
        eid = id(entity)
        if eid in self._phase_transitions:
            return self._phase_transitions[eid]
        return self.inactive_dim

    def entity_tint(self, entity) -> tuple[float, float, float, float]:
        """RGBA tint for the entity's current strata layer."""
        el = getattr(entity, "strata_layer", 0)
        if 0 <= el < len(self.layers):
            return self.layers[el].tint
        return (1.0, 1.0, 1.0, 1.0)

    def begin_phase(self, entity, transition_time: float = 0.15) -> None:
        """Mark entity as mid-phase transition (rendered at partial alpha in both layers)."""
        self._phase_transitions[id(entity)] = 0.5

    def end_phase(self, entity) -> None:
        self._phase_transitions.pop(id(entity), None)

    def tick(self, dt: float) -> None:
        """Animate phase transitions."""
        to_remove = []
        for eid, alpha in self._phase_transitions.items():
            new_alpha = alpha + dt * 4.0  # complete in ~0.25s
            if new_alpha >= 1.0:
                to_remove.append(eid)
            else:
                self._phase_transitions[eid] = new_alpha
        for eid in to_remove:
            del self._phase_transitions[eid]
