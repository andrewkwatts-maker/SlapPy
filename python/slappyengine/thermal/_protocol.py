"""Structural Protocol for thermal heat sources.

A *heat source* is anything that injects heat into a
:class:`~slappyengine.thermal.HeatField` over a finite footprint. The
canonical implementations live in game code (engine blocks, exhausts,
braziers, exhaust pipes, …) — the engine itself ships :class:`HeatField`
and the pairwise exchange primitive, but the *source* concept stays
duck-typed so games can attach heat to any entity without inheriting
from a framework class.

The Protocol formalises the shape used by callers that drive a
``HeatField`` through fixed-step physics:

    ``temperature: float`` — current emission temperature (units match
    the field).
    ``apply(field: HeatField, dt: float) -> None`` — write into the
    field. The implementation chooses the stencil (point, gaussian, AABB).

Optional attributes:

* ``position: tuple[float, float]`` — world coords of the source. The
  Protocol does not require it because some sources (uniform ambient
  emitters, edge-bound heaters) have no point location.
* ``conductivity: float`` — passed through to
  :func:`exchange_two_regions` when the source couples to a region
  pair instead of writing into a grid.

Marked ``@runtime_checkable`` so games can ``isinstance(src,
HeatSourceProtocol)`` to filter mixed entity lists.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from . import HeatField


@runtime_checkable
class HeatSourceProtocol(Protocol):
    """Structural type for anything that emits heat into a HeatField.

    Required attributes / methods:

    * ``temperature: float`` — emission temperature.
    * ``apply(field, dt)`` — inject heat for one step.
    """

    temperature: float

    def apply(self, field: "HeatField", dt: float) -> None:  # noqa: D401
        ...  # pragma: no cover — Protocol stub


__all__ = ["HeatSourceProtocol"]
