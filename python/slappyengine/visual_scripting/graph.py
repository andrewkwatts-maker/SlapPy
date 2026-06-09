"""NodeGraph + Edge for the visual scripting backbone.

The graph owns the topology (nodes + edges + their YAML round-trip), the
validator (cycles / dangling refs / port-kind mismatches), and the
topological sort used by the codegen walker.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from slappyengine._validation import validate_non_empty_str

from .node import Node, NodePort, ports_compatible


class GraphValidationError(ValueError):
    """Raised by :meth:`NodeGraph.validate` when one or more invariants fail.

    ``errors`` carries the per-issue error strings so the editor UI can show
    a list rather than truncating to the first message.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        if not self.errors:
            super().__init__("GraphValidationError (no errors recorded)")
        else:
            super().__init__(
                "; ".join(self.errors) if len(self.errors) <= 5
                else f"{len(self.errors)} validation error(s): "
                     + "; ".join(self.errors[:5]) + " ..."
            )


@dataclass
class Edge:
    """A directed connection between two ports on two nodes."""

    from_node_id: str
    from_port: str
    to_node_id: str
    to_port: str

    def __post_init__(self) -> None:
        self.from_node_id = validate_non_empty_str(
            "from_node_id", "Edge", self.from_node_id
        )
        self.from_port = validate_non_empty_str(
            "from_port", "Edge", self.from_port
        )
        self.to_node_id = validate_non_empty_str(
            "to_node_id", "Edge", self.to_node_id
        )
        self.to_port = validate_non_empty_str(
            "to_port", "Edge", self.to_port
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "from_node_id": self.from_node_id,
            "from_port": self.from_port,
            "to_node_id": self.to_node_id,
            "to_port": self.to_port,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Edge":
        if not isinstance(data, dict):
            raise TypeError(
                f"Edge.from_dict: expected dict; got {type(data).__name__}"
            )
        return cls(
            from_node_id=data["from_node_id"],
            from_port=data["from_port"],
            to_node_id=data["to_node_id"],
            to_port=data["to_port"],
        )


@dataclass
class NodeGraph:
    """An ordered collection of :class:`Node` records with directed edges.

    The graph is the *whole* serialisable artefact: the codegen module reads
    it, the editor UI mutates it, and the YAML round-trip persists it. The
    runtime evaluation lives in the codegen module rather than here so we
    can swap to a different backend (e.g. a Rust-backed walker) without
    touching the data model.
    """

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    name: str = "untitled"

    def __post_init__(self) -> None:
        self.name = validate_non_empty_str("name", "NodeGraph", self.name)
        if not isinstance(self.nodes, list):
            raise TypeError(
                f"NodeGraph: nodes must be a list; "
                f"got {type(self.nodes).__name__}"
            )
        if not isinstance(self.edges, list):
            raise TypeError(
                f"NodeGraph: edges must be a list; "
                f"got {type(self.edges).__name__}"
            )

    # ------------------------------------------------------------------
    # mutation helpers
    # ------------------------------------------------------------------

    def add_node(self, node: Node) -> Node:
        if not isinstance(node, Node):
            raise TypeError(
                f"NodeGraph.add_node: expected Node; "
                f"got {type(node).__name__}"
            )
        if any(n.id == node.id for n in self.nodes):
            raise ValueError(
                f"NodeGraph.add_node: duplicate node id {node.id!r}"
            )
        self.nodes.append(node)
        return node

    def add_edge(self, from_node: Node | str, from_port: str,
                 to_node: Node | str, to_port: str) -> Edge:
        from_id = from_node.id if isinstance(from_node, Node) else from_node
        to_id = to_node.id if isinstance(to_node, Node) else to_node
        edge = Edge(
            from_node_id=from_id,
            from_port=from_port,
            to_node_id=to_id,
            to_port=to_port,
        )
        self.edges.append(edge)
        return edge

    def get_node(self, node_id: str) -> Node:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(f"NodeGraph.get_node: no node with id {node_id!r}")

    def remove_node(self, node_id: str) -> None:
        self.nodes = [n for n in self.nodes if n.id != node_id]
        self.edges = [
            e for e in self.edges
            if e.from_node_id != node_id and e.to_node_id != node_id
        ]

    # ------------------------------------------------------------------
    # validation
    # ------------------------------------------------------------------

    def validate(self, *, raise_on_error: bool = True) -> list[str]:
        """Return a list of error strings (empty on success).

        Checks (in order):

        * Duplicate node ids.
        * Each edge's ``from_node_id`` / ``to_node_id`` resolves.
        * Each edge's ``from_port`` exists on the source node's outputs and
          ``to_port`` exists on the target node's inputs.
        * Port-kind compatibility between source output and target input
          (see :func:`ports_compatible`).
        * No cycles in the directed edge graph.

        Raises
        ------
        GraphValidationError
            When ``raise_on_error`` is True (default) and at least one
            invariant fails.
        """
        errors: list[str] = []

        # 1. duplicate ids
        seen_ids: set[str] = set()
        for n in self.nodes:
            if n.id in seen_ids:
                errors.append(f"duplicate node id {n.id!r}")
            seen_ids.add(n.id)

        id_to_node = {n.id: n for n in self.nodes}

        # 2-4. per-edge structural checks
        for i, e in enumerate(self.edges):
            src = id_to_node.get(e.from_node_id)
            dst = id_to_node.get(e.to_node_id)
            if src is None:
                errors.append(
                    f"edge[{i}]: from_node_id {e.from_node_id!r} not in graph"
                )
            if dst is None:
                errors.append(
                    f"edge[{i}]: to_node_id {e.to_node_id!r} not in graph"
                )
            if src is None or dst is None:
                continue

            try:
                src_port = src.get_output(e.from_port)
            except KeyError:
                errors.append(
                    f"edge[{i}]: from_port {e.from_port!r} not on "
                    f"node {src.node_type!r} outputs {src.output_names()}"
                )
                src_port = None

            try:
                dst_port = dst.get_input(e.to_port)
            except KeyError:
                errors.append(
                    f"edge[{i}]: to_port {e.to_port!r} not on "
                    f"node {dst.node_type!r} inputs {dst.input_names()}"
                )
                dst_port = None

            if src_port is not None and dst_port is not None:
                if not ports_compatible(src_port.port_kind, dst_port.port_kind):
                    errors.append(
                        f"edge[{i}]: port-kind mismatch "
                        f"{src.node_type}.{e.from_port} ({src_port.port_kind}) "
                        f"-> {dst.node_type}.{e.to_port} "
                        f"({dst_port.port_kind})"
                    )

        # 5. cycle detection — DFS three-colour
        if not errors:  # only run if structure is intact
            if self._has_cycle():
                errors.append("graph contains at least one cycle")
        else:
            # still run a best-effort cycle check
            try:
                if self._has_cycle():
                    errors.append("graph contains at least one cycle")
            except Exception:  # pragma: no cover — defensive
                pass

        if errors and raise_on_error:
            raise GraphValidationError(errors)
        return errors

    def _adjacency(self) -> dict[str, list[str]]:
        adj: dict[str, list[str]] = {n.id: [] for n in self.nodes}
        for e in self.edges:
            if e.from_node_id in adj:
                adj[e.from_node_id].append(e.to_node_id)
        return adj

    def _has_cycle(self) -> bool:
        adj = self._adjacency()
        WHITE, GREY, BLACK = 0, 1, 2
        color: dict[str, int] = {nid: WHITE for nid in adj}

        def visit(nid: str) -> bool:
            color[nid] = GREY
            for nxt in adj.get(nid, []):
                c = color.get(nxt, WHITE)
                if c == GREY:
                    return True
                if c == WHITE and visit(nxt):
                    return True
            color[nid] = BLACK
            return False

        for nid in adj:
            if color[nid] == WHITE:
                if visit(nid):
                    return True
        return False

    # ------------------------------------------------------------------
    # topological ordering
    # ------------------------------------------------------------------

    def topological_order(self) -> list[Node]:
        """Return nodes in dependency order (sources first, sinks last).

        Uses Kahn's algorithm; deterministic when ``self.nodes`` ordering is
        stable (ties broken by insertion order). Raises
        :class:`GraphValidationError` if the graph has a cycle.
        """
        adj = self._adjacency()
        indeg: dict[str, int] = {n.id: 0 for n in self.nodes}
        for src, neigh in adj.items():
            for dst in neigh:
                if dst in indeg:
                    indeg[dst] += 1

        # preserve insertion order for ties — iterate self.nodes
        ready: list[str] = [n.id for n in self.nodes if indeg[n.id] == 0]
        order: list[str] = []
        id_to_node = {n.id: n for n in self.nodes}

        while ready:
            nid = ready.pop(0)
            order.append(nid)
            for nxt in adj.get(nid, []):
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    ready.append(nxt)

        if len(order) != len(self.nodes):
            raise GraphValidationError(
                ["topological_order: graph contains a cycle"]
            )

        return [id_to_node[nid] for nid in order]

    # ------------------------------------------------------------------
    # YAML round-trip
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NodeGraph":
        if not isinstance(data, dict):
            raise TypeError(
                f"NodeGraph.from_dict: expected dict; "
                f"got {type(data).__name__}"
            )
        g = cls(name=data.get("name", "untitled"))
        for nd in data.get("nodes", []):
            g.nodes.append(Node.from_dict(nd))
        for ed in data.get("edges", []):
            g.edges.append(Edge.from_dict(ed))
        return g

    def to_yaml(self) -> str:
        import yaml
        return yaml.safe_dump(self.to_dict(), sort_keys=False)

    @classmethod
    def from_yaml(cls, source: str) -> "NodeGraph":
        import yaml
        data = yaml.safe_load(source)
        if data is None:
            return cls()
        return cls.from_dict(data)

    # ------------------------------------------------------------------
    # convenience
    # ------------------------------------------------------------------

    def incoming_edges(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.to_node_id == node_id]

    def outgoing_edges(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.from_node_id == node_id]

    def __len__(self) -> int:
        return len(self.nodes)

    def __iter__(self) -> Iterable[Node]:
        return iter(self.nodes)


__all__ = [
    "Edge",
    "NodeGraph",
    "GraphValidationError",
]
