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

from pharos_engine._strata_validation import (
    validate_entity_arg,
    validate_finite_float,
    validate_layer_list,
    validate_non_empty_str,
    validate_non_negative_int,
    validate_rgba_tuple,
    validate_unit_float,
)


@dataclass
class StrataLayer:
    name: str
    index: int
    tint: tuple[float, float, float, float]   # RGBA multiplier for entities on this layer
    parallax: float = 1.0                      # scroll speed multiplier vs camera

    def __post_init__(self) -> None:
        """Validate at construction — invalid layers would silently render
        as garbage (NaN tint, negative index) and the failure would surface
        deep inside the renderer where the traceback is lost.

        Raises
        ------
        TypeError
            If ``name`` is not a ``str``, ``index`` is not a plain int,
            ``tint`` is not a 4-element sequence of real numbers, or
            ``parallax`` is not a real number.
        ValueError
            If ``name`` is empty, ``index < 0``, ``tint`` has wrong length
            or contains NaN/inf, or ``parallax`` is NaN/inf.
        """
        self.name = validate_non_empty_str("name", "StrataLayer", self.name)
        self.index = validate_non_negative_int("index", "StrataLayer", self.index)
        self.tint = validate_rgba_tuple("tint", "StrataLayer", self.tint)
        self.parallax = validate_finite_float(
            "parallax", "StrataLayer", self.parallax,
        )


class StrataWorld:
    """
    Manages multiple parallel world layers.
    Attached to Scene as scene.strata.
    """
    def __init__(self, layers: list[StrataLayer], inactive_dim: float = 0.35):
        """Construct a strata world.

        Raises
        ------
        TypeError
            If ``layers`` is not a list of :class:`StrataLayer`, or
            ``inactive_dim`` is not a real number.
        ValueError
            If ``layers`` is empty, or ``inactive_dim`` is not in ``[0, 1]``.
        """
        self.layers = validate_layer_list("layers", "StrataWorld", layers)
        self.active_index: int = 0
        # alpha multiplier for entities on inactive layers
        self.inactive_dim = validate_unit_float(
            "inactive_dim", "StrataWorld", inactive_dim,
        )
        self._phase_transitions: dict[int, float] = {}  # entity_id → transition alpha (0→1)

    @property
    def active_layer(self) -> StrataLayer:
        return self.layers[self.active_index]

    def set_active(self, index: int) -> None:
        """Set the active strata layer (wraps modulo ``len(self.layers)``).

        Raises
        ------
        TypeError
            If ``index`` is not a plain int (``bool`` refused — ``True``
            would silently mean "layer 1").
        ValueError
            If ``index < 0`` (we refuse rather than wrap negatives because
            Python's ``%`` on negatives gives non-obvious results).
        """
        index = validate_non_negative_int("index", "StrataWorld.set_active", index)
        self.active_index = index % len(self.layers)

    def get_layer(self, index: int) -> StrataLayer | None:
        """Return the layer at ``index`` or ``None`` if out-of-range.

        Negative ``index`` values return ``None`` (preserving the original
        defensive behaviour) — only the type is checked at the boundary.

        Raises
        ------
        TypeError
            If ``index`` is not a plain int.
        """
        if isinstance(index, bool) or not isinstance(index, int):
            raise TypeError(
                f"StrataWorld.get_layer: index must be an int; "
                f"got {type(index).__name__}"
            )
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
        validate_entity_arg("entity", "StrataWorld.entity_visibility_alpha", entity)
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
        validate_entity_arg("entity", "StrataWorld.entity_tint", entity)
        el = getattr(entity, "strata_layer", 0)
        if isinstance(el, int) and not isinstance(el, bool) and 0 <= el < len(self.layers):
            return self.layers[el].tint
        return (1.0, 1.0, 1.0, 1.0)

    def begin_phase(self, entity, transition_time: float = 0.15) -> None:
        """Mark entity as mid-phase transition (rendered at partial alpha in both layers).

        Raises
        ------
        TypeError
            If ``entity`` is ``None``, or ``transition_time`` is not a real
            number.
        ValueError
            If ``transition_time`` is NaN/inf.
        """
        validate_entity_arg("entity", "StrataWorld.begin_phase", entity)
        validate_finite_float(
            "transition_time", "StrataWorld.begin_phase", transition_time,
        )
        self._phase_transitions[id(entity)] = 0.5

    def end_phase(self, entity) -> None:
        """End a phase transition for ``entity``.

        Raises
        ------
        TypeError
            If ``entity`` is ``None``.
        """
        validate_entity_arg("entity", "StrataWorld.end_phase", entity)
        self._phase_transitions.pop(id(entity), None)

    def tick(self, dt: float) -> None:
        """Animate phase transitions.

        Raises
        ------
        TypeError
            If ``dt`` is not a real number (bool refused).
        ValueError
            If ``dt`` is NaN/inf.
        """
        dt = validate_finite_float("dt", "StrataWorld.tick", dt)
        to_remove = []
        for eid, alpha in self._phase_transitions.items():
            new_alpha = alpha + dt * 4.0  # complete in ~0.25s
            if new_alpha >= 1.0:
                to_remove.append(eid)
            else:
                self._phase_transitions[eid] = new_alpha
        for eid in to_remove:
            del self._phase_transitions[eid]
