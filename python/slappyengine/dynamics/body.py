"""Generalised :class:`Body` dataclass for the unified dynamics layer.

A :class:`Body` is a thin handle that names a contiguous slice of nodes inside
a world's node array and carries a free-form ``parameters`` dict so different
authoring tools (vehicle wizard, ragdoll builder, rope builder, ...) can
attach kind-specific metadata without bloating the type system.

The substrate solver only ever reads ``node_offset`` / ``node_count``.
Everything else is consumer-defined.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Body:
    """Generic body record.

    Parameters
    ----------
    kind:
        Authoring discriminator. Conventional values are
        ``"lattice"``, ``"rope"``, ``"ragdoll"``, ``"shell"``. The substrate
        solver does not inspect this; downstream tools (editor, serialiser,
        renderer) use it to pick the right authoring widget.
    parameters:
        Open-ended config bag. Builders write their own knobs in here.
    node_offset:
        Base index of this body's nodes inside the host world's node array.
    node_count:
        Number of contiguous nodes owned by this body.
    label:
        Human-readable identifier, useful for editor / debug overlays.
    """
    kind: str = "lattice"
    parameters: dict[str, Any] = field(default_factory=dict)
    node_offset: int = 0
    node_count: int = 0
    label: str = ""

    @property
    def node_indices(self) -> range:
        """Iterable of absolute node indices owned by this body."""
        return range(self.node_offset, self.node_offset + self.node_count)


__all__ = ["Body"]
