"""Node / NodePort / NodeRegistry primitives for the visual scripting graph.

The visual-scripting backbone borrows the shape of ``pharos_engine.material``'s
``NodeDef`` / ``NodeMaterial`` but generalises beyond rendering: a node here
may be ``math`` / ``logic`` / ``control`` / ``io`` / ``compute`` / ``render``
/ ``audio`` / ``event``. Each node carries typed input/output ``NodePort``
records and a ``to_python_template`` string that the codegen module fills in
with the actual variable names bound by the graph walker.

The runtime is deliberately small — this module owns *only* the dataclasses
and the type-string allow-lists. The graph itself (cycles, topological order,
YAML round-trip) lives in :mod:`pharos_engine.visual_scripting.graph`. The
builtin palette of 20 starter nodes lives in
:mod:`pharos_engine.visual_scripting.palette`.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Iterable

from pharos_engine._validation import (
    validate_non_empty_str,
    validate_str,
)


# ---------------------------------------------------------------------------
# Type-string allow-lists. Treated as ``Literal``-style values at the doc/API
# level but kept here as frozensets so adding a new kind is a one-line edit
# (instead of an ``importlib`` round-trip on a ``Literal`` alias).
# ---------------------------------------------------------------------------

NODE_KINDS: frozenset[str] = frozenset({
    "compute",
    "io",
    "control",
    "math",
    "logic",
    "render",
    "audio",
    "event",
})

PORT_KINDS: frozenset[str] = frozenset({
    "float",
    "int",
    "bool",
    "str",
    "vec2",
    "vec3",
    "vec4",
    "sampler2d",
    "any",
})

# Cross-port-kind compatibility map. The validator uses this to allow
# ``int`` -> ``float`` (widening) and ``any`` -> anything, while still
# catching the obvious "wired a vec3 into a bool" foot-guns.
# Each entry: ``from_kind -> {to_kind, ...}`` — i.e. the set of target
# port kinds a source of this kind can drive. Widening is explicit
# (``int -> float`` and ``int -> bool`` both allowed); narrowing
# (``float -> int``) is not, because that would silently drop precision.
_COMPATIBLE_PORTS: dict[str, frozenset[str]] = {
    "any":   frozenset(PORT_KINDS),
    "float": frozenset({"float", "any"}),
    "int":   frozenset({"int", "float", "any"}),
    "bool":  frozenset({"bool", "any"}),
    "str":   frozenset({"str", "any"}),
    "vec2":  frozenset({"vec2", "any"}),
    "vec3":  frozenset({"vec3", "any"}),
    "vec4":  frozenset({"vec4", "any"}),
    "sampler2d": frozenset({"sampler2d", "any"}),
}


def ports_compatible(from_kind: str, to_kind: str) -> bool:
    """Return ``True`` iff a ``from_kind`` output can drive a ``to_kind`` input.

    Symmetric on ``any``; otherwise matches the table in
    ``_COMPATIBLE_PORTS``. Both arguments are validated against
    ``PORT_KINDS`` so a typo at the call site fails loudly rather than
    silently returning ``False``.
    """
    if from_kind not in PORT_KINDS:
        raise ValueError(
            f"ports_compatible: from_kind {from_kind!r} not in PORT_KINDS"
        )
    if to_kind not in PORT_KINDS:
        raise ValueError(
            f"ports_compatible: to_kind {to_kind!r} not in PORT_KINDS"
        )
    return to_kind in _COMPATIBLE_PORTS.get(from_kind, frozenset())


# Convenience aliases — the public surface lists them so callers can write
# ``NodeKind = "math"`` without having to know about the frozenset.
NodeKind = str  # one of NODE_KINDS at runtime
PortKind = str  # one of PORT_KINDS at runtime


# ---------------------------------------------------------------------------
# NodePort
# ---------------------------------------------------------------------------


@dataclass
class NodePort:
    """A single typed port on a :class:`Node`.

    Inputs and outputs share the same record; the direction is implied by
    which list the port lives in on the parent node.
    """

    name: str
    port_kind: str
    default: Any = None

    def __post_init__(self) -> None:
        self.name = validate_non_empty_str("name", "NodePort", self.name)
        self.port_kind = validate_non_empty_str(
            "port_kind", "NodePort", self.port_kind
        )
        if self.port_kind not in PORT_KINDS:
            raise ValueError(
                f"NodePort: port_kind must be one of "
                f"{sorted(PORT_KINDS)}; got {self.port_kind!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "port_kind": self.port_kind,
            "default": self.default,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NodePort":
        if not isinstance(data, dict):
            raise TypeError(
                f"NodePort.from_dict: expected dict; got {type(data).__name__}"
            )
        return cls(
            name=data["name"],
            port_kind=data["port_kind"],
            default=data.get("default"),
        )


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------


@dataclass
class Node:
    """A single node in a visual-scripting graph.

    Notes
    -----
    * ``node_type`` is the registry key (e.g. ``"math.add"``); ``name`` is
      an instance-level display label that defaults to ``node_type``.
    * ``id`` is the addressable identifier used by :class:`Edge`; it is
      auto-assigned when missing so callers can build a graph with
      ``Node(node_type="math.add", ...)`` without thinking about ids.
    * ``to_python_template`` is the codegen template; the codegen module
      fills ``{port_name}`` placeholders with bound variable names.
    """

    node_type: str
    kind: str
    inputs: list[NodePort] = field(default_factory=list)
    outputs: list[NodePort] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    position: tuple[int, int] = (0, 0)
    name: str = ""
    id: str = ""
    to_python_template: str = ""

    def __post_init__(self) -> None:
        self.node_type = validate_non_empty_str(
            "node_type", "Node", self.node_type
        )
        self.kind = validate_non_empty_str("kind", "Node", self.kind)
        if self.kind not in NODE_KINDS:
            raise ValueError(
                f"Node: kind must be one of {sorted(NODE_KINDS)}; "
                f"got {self.kind!r}"
            )
        if not self.name:
            self.name = self.node_type
        else:
            self.name = validate_non_empty_str("name", "Node", self.name)
        if not self.id:
            self.id = _gen_id()
        else:
            self.id = validate_non_empty_str("id", "Node", self.id)
        if not isinstance(self.inputs, list):
            raise TypeError(
                f"Node: inputs must be a list; got {type(self.inputs).__name__}"
            )
        if not isinstance(self.outputs, list):
            raise TypeError(
                f"Node: outputs must be a list; got "
                f"{type(self.outputs).__name__}"
            )
        for i, p in enumerate(self.inputs):
            if not isinstance(p, NodePort):
                raise TypeError(
                    f"Node: inputs[{i}] must be a NodePort; "
                    f"got {type(p).__name__}"
                )
        for i, p in enumerate(self.outputs):
            if not isinstance(p, NodePort):
                raise TypeError(
                    f"Node: outputs[{i}] must be a NodePort; "
                    f"got {type(p).__name__}"
                )
        if not isinstance(self.params, dict):
            raise TypeError(
                f"Node: params must be a dict; "
                f"got {type(self.params).__name__}"
            )
        # validate the template if present; empty is allowed (e.g. flow
        # nodes that the codegen handles with a custom case).
        if self.to_python_template:
            validate_str(
                "to_python_template", "Node", self.to_python_template
            )

    # ------------------------------------------------------------------
    # ergonomic helpers
    # ------------------------------------------------------------------

    def input_names(self) -> list[str]:
        return [p.name for p in self.inputs]

    def output_names(self) -> list[str]:
        return [p.name for p in self.outputs]

    def get_input(self, name: str) -> NodePort:
        for p in self.inputs:
            if p.name == name:
                return p
        raise KeyError(
            f"Node {self.node_type!r}: no input port {name!r} "
            f"(have {self.input_names()})"
        )

    def get_output(self, name: str) -> NodePort:
        for p in self.outputs:
            if p.name == name:
                return p
        raise KeyError(
            f"Node {self.node_type!r}: no output port {name!r} "
            f"(have {self.output_names()})"
        )

    # ------------------------------------------------------------------
    # serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "node_type": self.node_type,
            "kind": self.kind,
            "name": self.name,
            "inputs": [p.to_dict() for p in self.inputs],
            "outputs": [p.to_dict() for p in self.outputs],
            "params": dict(self.params),
            "position": [int(self.position[0]), int(self.position[1])],
            "to_python_template": self.to_python_template,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Node":
        if not isinstance(data, dict):
            raise TypeError(
                f"Node.from_dict: expected dict; got {type(data).__name__}"
            )
        pos = data.get("position", (0, 0))
        if isinstance(pos, list):
            pos = tuple(pos)
        return cls(
            node_type=data["node_type"],
            kind=data["kind"],
            inputs=[NodePort.from_dict(p) for p in data.get("inputs", [])],
            outputs=[NodePort.from_dict(p) for p in data.get("outputs", [])],
            params=dict(data.get("params", {})),
            position=pos,
            name=data.get("name", ""),
            id=data.get("id", ""),
            to_python_template=data.get("to_python_template", ""),
        )

    def clone(self, *, new_id: bool = True) -> "Node":
        """Return a deep copy. When ``new_id`` is True (default) a fresh id is
        minted so the clone can sit alongside the original in the same graph.
        """
        c = Node(
            node_type=self.node_type,
            kind=self.kind,
            inputs=[NodePort(p.name, p.port_kind, copy.deepcopy(p.default))
                    for p in self.inputs],
            outputs=[NodePort(p.name, p.port_kind, copy.deepcopy(p.default))
                     for p in self.outputs],
            params=copy.deepcopy(self.params),
            position=tuple(self.position),
            name=self.name,
            id="" if new_id else self.id,
            to_python_template=self.to_python_template,
        )
        return c


# ---------------------------------------------------------------------------
# NodeRegistry
# ---------------------------------------------------------------------------


class NodeRegistry:
    """Registry of available node definitions keyed by ``node_type``.

    The registry stores *prototype* :class:`Node` records; callers should
    invoke :meth:`spawn` (which returns a fresh :class:`Node` with a unique
    id) instead of registering pre-spawned nodes.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}

    def register(self, node: Node) -> Node:
        validate_non_empty_str("node.node_type", "NodeRegistry.register",
                               node.node_type)
        if node.node_type in self._nodes:
            raise ValueError(
                f"NodeRegistry.register: node_type {node.node_type!r} "
                f"already registered"
            )
        self._nodes[node.node_type] = node
        return node

    def unregister(self, node_type: str) -> None:
        self._nodes.pop(node_type, None)

    def get(self, node_type: str) -> Node:
        if node_type not in self._nodes:
            raise KeyError(
                f"NodeRegistry.get: unknown node_type {node_type!r} "
                f"(have {sorted(self._nodes)})"
            )
        return self._nodes[node_type]

    def has(self, node_type: str) -> bool:
        return node_type in self._nodes

    def spawn(self, node_type: str, *, position: tuple[int, int] = (0, 0),
              params: dict[str, Any] | None = None) -> Node:
        """Mint a new :class:`Node` from the registered prototype."""
        proto = self.get(node_type)
        n = proto.clone(new_id=True)
        n.position = (int(position[0]), int(position[1]))
        if params:
            n.params.update(params)
        return n

    def list_types(self, *, kind: str | None = None) -> list[str]:
        if kind is None:
            return sorted(self._nodes)
        if kind not in NODE_KINDS:
            raise ValueError(
                f"NodeRegistry.list_types: kind must be one of "
                f"{sorted(NODE_KINDS)}; got {kind!r}"
            )
        return sorted(t for t, n in self._nodes.items() if n.kind == kind)

    def values(self) -> Iterable[Node]:
        return self._nodes.values()

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, node_type: str) -> bool:
        return node_type in self._nodes


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------


def _gen_id() -> str:
    import uuid
    return "n_" + uuid.uuid4().hex[:8]


__all__ = [
    "Node",
    "NodeKind",
    "NodePort",
    "PortKind",
    "NodeRegistry",
    "NODE_KINDS",
    "PORT_KINDS",
    "ports_compatible",
]
