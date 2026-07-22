"""Structural Protocol for material graph nodes.

A *node* is any object that can be added to a :class:`NodeMaterial`
graph. The shipped factory helpers (``UVNode()``, ``AddNode()``,
``LerpNode()`` …) return plain :class:`NodeDef` instances, but the graph
compiler does not actually care about the dataclass — it only reads
``node_type`` (string) and ``params`` (dict). Any custom node from a
third-party material extension that exposes the same two attributes can
be folded into the same graph.

This Protocol formalises that contract so:

* The schema validator can ``isinstance(n, NodeProtocol)`` instead of
  asserting on :class:`NodeDef`.
* Extensions implementing alternative node container classes (named
  tuples, frozen dataclasses, Pydantic models) work without inheritance.

Marked ``@runtime_checkable`` so the existing schema check can flip from
``isinstance(_, NodeDef)`` to ``isinstance(_, NodeProtocol)`` at any
time without breaking callers.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable


@runtime_checkable
class NodeProtocol(Protocol):
    """Structural type for any node addable to a :class:`NodeMaterial`.

    Required attributes:

    * ``node_type: str`` — type tag used by the schema + compiler.
    * ``params: Mapping[str, Any]`` — per-instance parameters (read by
      the schema + compiler; mutated only by authoring helpers).

    The optional ``id`` attribute (used by :class:`NodeDef` for stable
    graph addressing) is not required — the compiler synthesises one
    when missing.
    """

    node_type: str
    params: Mapping[str, Any]


__all__ = ["NodeProtocol"]
