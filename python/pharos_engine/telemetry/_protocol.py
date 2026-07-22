"""Structural Protocols for telemetry producers and consumers.

The :mod:`pharos_engine.telemetry` module exposes ``emit`` / ``subscribe``
as module-level functions for ergonomic single-process use. Games and
third-party tools often want to wire telemetry through their own objects
(per-system emitters, networked subscribers, batched profilers). The two
Protocols below formalise those object surfaces so callers can plug
their own implementations into engine code without inheriting from
anything.

* :class:`EventEmitterProtocol` — anything that publishes telemetry
  events. The shipped module-level :func:`emit` is the reference
  implementation; a per-system wrapper class can pre-bake the
  ``source=`` keyword and still satisfy this Protocol.
* :class:`EventSubscriberProtocol` — anything callable that consumes a
  :class:`TelemetryEvent`. Matches the signature accepted by
  :func:`subscribe` so callers can type-annotate their handler lists.

Both Protocols are ``@runtime_checkable``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from . import TelemetryEvent


@runtime_checkable
class EventEmitterProtocol(Protocol):
    """Structural type for anything that publishes telemetry events.

    Required method:

    * ``emit(name: str, **payload) -> None`` — publish an event with the
      given dotted name and keyword payload.
    """

    def emit(self, name: str, **payload: Any) -> None:  # noqa: D401
        ...  # pragma: no cover — Protocol stub


@runtime_checkable
class EventSubscriberProtocol(Protocol):
    """Structural type for a telemetry event handler.

    Required method:

    * ``__call__(event: TelemetryEvent) -> None`` — receive an event.

    Matches the callable signature accepted by :func:`subscribe`. Useful
    for callers that want to bundle handler state in a class instead of
    a closure.
    """

    def __call__(self, event: "TelemetryEvent") -> None:  # noqa: D401
        ...  # pragma: no cover — Protocol stub


__all__ = ["EventEmitterProtocol", "EventSubscriberProtocol"]
