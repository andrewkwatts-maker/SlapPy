"""Structural Protocol for zone types.

A *zone* is anything that can answer ``contains_point(px, py)`` and that
optionally fires ``on_enter`` / ``on_exit`` callbacks when entities move
in or out. The shipped :class:`~slappyengine.zones.RectZone` and
:class:`~slappyengine.zones.ThresholdZone` are the reference
implementations, but any third-party zone class — radial, polygonal,
heightmap-clipped — satisfies the contract by exposing the same shape.

Marked ``@runtime_checkable`` so callers and tests can use
``isinstance(zone, ZoneProtocol)`` for defensive duck-typing.

The Protocol intentionally only mandates ``contains_point`` (the *one*
method the manager actually calls). ``on_enter`` / ``on_exit`` /
``name`` are declared as optional attributes so non-rect implementations
do not need to carry rect-specific state.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ZoneProtocol(Protocol):
    """Structural type for anything :class:`ZoneManager` can register.

    A conforming zone exposes:

    * ``name`` — stable identifier (used as the registry key).
    * ``contains_point(px, py) -> bool`` — point-in-zone query.

    Optional attributes (read by the manager when present):

    * ``on_enter(entity_id)`` — fired the first frame an entity is inside.
    * ``on_exit(entity_id)`` — fired the first frame an entity leaves.
    """

    name: str

    def contains_point(self, px: float, py: float) -> bool:  # noqa: D401
        ...  # pragma: no cover — Protocol stub


__all__ = ["ZoneProtocol"]
