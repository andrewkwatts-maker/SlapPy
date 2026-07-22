"""Python code-gen for visual-scripting :class:`NodeGraph` instances.

``graph_to_python`` walks the graph in topological order and emits a
self-contained Python function. Each node's ``to_python_template`` is
substituted with the bound variable names assigned by the walker:

* Each output port gets a unique local variable name
  ``v_<node_id>_<port_name>``.
* Each input port resolves to the variable of the upstream edge's source
  port, or — when nothing is wired — the input's ``default`` rendered
  as a Python literal.
* Params declared on the node show up as ``{__param_<name>__}``
  substitutions (e.g. ``logic.compare`` uses ``op`` for the comparator).

Control-flow nodes (``control.foreach`` / ``control.while`` /
``control.return``) bypass the simple template substitution and emit
hand-crafted scaffolds; for the foreach/while bodies the walker treats
*downstream* nodes as the body. Today the codegen emits a flat function
body — the editor sprint will layer richer body scoping on top.

``python_to_graph`` is a best-effort reverse: it parses simple
``v_<id>_<port> = <expr>`` assignment lines back into a sequence of nodes
plus wiring. It is good enough for the round-trip test in this sprint;
the editor sprint will replace it with an AST-driven importer.
"""
from __future__ import annotations

import ast
import re
from typing import Any

from .graph import Edge, NodeGraph
from .node import Node


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


_VAR_NAME_RE = re.compile(r"^v_([A-Za-z0-9_]+)_([A-Za-z0-9_]+)$")


def _safe_id(node_id: str) -> str:
    """Return a Python-identifier-safe form of ``node_id``."""
    return re.sub(r"[^A-Za-z0-9_]", "_", node_id)


def _var(node_id: str, port_name: str) -> str:
    return f"v_{_safe_id(node_id)}_{port_name}"


def _py_literal(value: Any) -> str:
    """Render ``value`` as a Python literal expression."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, (tuple, list)):
        return "(" + ", ".join(_py_literal(v) for v in value) + (
            ",)" if isinstance(value, tuple) and len(value) == 1 else ")"
        )
    # fallback — repr keeps tests deterministic
    return repr(value)


def _format_template(node: Node, bindings: dict[str, str]) -> str:
    """Substitute ``{port_name}`` and ``{__param_<name>__}`` markers.

    Two parameter forms are supported:

    * ``{__param_<name>__}`` — substitute the param value as a Python
      literal (string params become ``"quoted"``, ints stay bare, etc.).
    * ``{__param_<name>_raw__}`` — substitute the param value verbatim,
      with no quoting. Used by ``logic.compare`` so the ``op`` param can
      hold ``"=="`` and emit ``==`` directly into the expression.
    """
    out = node.to_python_template
    # parameter substitution — raw form first so the literal form does
    # not accidentally consume a ``__param_<name>__`` substring inside a
    # ``__param_<name>_raw__`` marker.
    for k, v in node.params.items():
        raw_marker = "{__param_" + k + "_raw__}"
        if raw_marker in out:
            out = out.replace(raw_marker, str(v))
    for k, v in node.params.items():
        marker = "{__param_" + k + "__}"
        if marker in out:
            out = out.replace(marker, _py_literal(v))
    # port substitution — preserve {literal} braces by only replacing
    # known port names. We walk in length-descending order so port names
    # that are prefixes of others (rare) don't collide.
    port_names = sorted(
        [p.name for p in node.inputs] + [p.name for p in node.outputs],
        key=len, reverse=True,
    )
    for pname in port_names:
        if pname in bindings:
            out = out.replace("{" + pname + "}", bindings[pname])
    return out


def _resolve_input(graph: NodeGraph, node: Node, port_name: str) -> str:
    """Return the Python expression bound to a single input port."""
    for e in graph.incoming_edges(node.id):
        if e.to_port == port_name:
            return _var(e.from_node_id, e.from_port)
    # fallback: use the port's declared default
    try:
        port = node.get_input(port_name)
    except KeyError:
        return "None"
    return _py_literal(port.default)


# ---------------------------------------------------------------------------
# graph_to_python
# ---------------------------------------------------------------------------


def graph_to_python(
    graph: NodeGraph,
    *,
    function_name: str = "run",
    indent: str = "    ",
) -> str:
    """Generate a Python function string from ``graph``.

    The function is callable with no arguments by default (the editor
    sprint will add input-binding support). Returns the source string;
    callers can ``exec`` it into a namespace to run.
    """
    graph.validate()  # raise if the graph is malformed
    order = graph.topological_order()

    lines: list[str] = [f"def {function_name}():"]
    if not order:
        lines.append(indent + "pass")
        return "\n".join(lines) + "\n"

    return_seen = False

    for node in order:
        # build bindings for {port_name} markers
        bindings: dict[str, str] = {}
        for p in node.inputs:
            bindings[p.name] = _resolve_input(graph, node, p.name)
        for p in node.outputs:
            bindings[p.name] = _var(node.id, p.name)

        if node.kind == "control":
            if node.node_type == "control.return":
                val_expr = bindings.get("value", "None")
                lines.append(indent + f"return {val_expr}")
                return_seen = True
                # everything after a return is unreachable; stop emitting
                break
            elif node.node_type == "control.foreach":
                iterable_expr = bindings.get("iterable", "()")
                item_var = bindings.get("item", _var(node.id, "item"))
                lines.append(indent + f"for {item_var} in {iterable_expr}:")
                lines.append(indent + indent + "pass  # body filled by editor")
                continue
            elif node.node_type == "control.while":
                cond_expr = bindings.get("cond", "False")
                lines.append(indent + f"while {cond_expr}:")
                lines.append(indent + indent + "break  # body filled by editor")
                continue

        rendered = _format_template(node, bindings)
        if rendered:
            for sub in rendered.split("\n"):
                lines.append(indent + sub)

    # ensure at least one return so the function evaluates cleanly
    if not return_seen:
        # collect last-node outputs into a dict so callers can inspect
        last = order[-1]
        if last.outputs and last.node_type != "control.return":
            out_pairs = ", ".join(
                f"{p.name!r}: {_var(last.id, p.name)}" for p in last.outputs
            )
            lines.append(indent + f"return {{{out_pairs}}}")
        else:
            lines.append(indent + "return None")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# python_to_graph
# ---------------------------------------------------------------------------


def python_to_graph(source: str, *, name: str = "imported") -> NodeGraph:
    """Best-effort parse of generated source back into a :class:`NodeGraph`.

    Looks for ``v_<id>_<port> = <expr>`` assignments where the right-hand
    side may reference other ``v_<id>_<port>`` variables; one ``Node`` is
    minted per unique ``<id>`` and one ``Edge`` per cross-reference. Node
    kinds are inferred as ``math`` (since the importer cannot recover the
    original ``node_type``); the resulting graph is therefore a
    *structurally* equivalent skeleton rather than a perfect inverse.

    The full editor sprint will replace this with an AST-driven importer
    that recognises each template family. For now the function exists so
    we can round-trip generated code through ``python_to_graph`` and
    confirm the topology matches.
    """
    if not isinstance(source, str):
        raise TypeError(
            f"python_to_graph: source must be a str; "
            f"got {type(source).__name__}"
        )

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(f"python_to_graph: failed to parse source — {exc}")

    graph = NodeGraph(name=name)

    # First pass: find every Assign whose target is ``v_<id>_<port>``.
    # Build the per-id port set.
    assignments: list[tuple[str, str, ast.AST]] = []  # (id, port, value)
    for body_node in ast.walk(tree):
        if isinstance(body_node, ast.Assign):
            if len(body_node.targets) != 1:
                continue
            tgt = body_node.targets[0]
            if not isinstance(tgt, ast.Name):
                continue
            m = _VAR_NAME_RE.match(tgt.id)
            if not m:
                continue
            node_id, port = m.group(1), m.group(2)
            assignments.append((node_id, port, body_node.value))

    # Mint nodes
    from .node import NodePort
    seen_ids: dict[str, Node] = {}
    for node_id, port, _value in assignments:
        if node_id not in seen_ids:
            n = Node(
                node_type="math.imported",
                kind="math",
                inputs=[],
                outputs=[],
                id=node_id,
                to_python_template="",
            )
            seen_ids[node_id] = n
            graph.add_node(n)
        # add output port if missing
        n = seen_ids[node_id]
        if not any(p.name == port for p in n.outputs):
            n.outputs.append(NodePort(port, "any"))

    # Second pass: find references — every Name on the RHS that matches
    # ``v_<id>_<port>`` becomes an edge from that port to a synthesised
    # input port on the assignment's id.
    input_counter: dict[str, int] = {}
    for node_id, port, value in assignments:
        n = seen_ids[node_id]
        for sub in ast.walk(value):
            if isinstance(sub, ast.Name):
                m = _VAR_NAME_RE.match(sub.id)
                if not m:
                    continue
                src_id, src_port = m.group(1), m.group(2)
                if src_id == node_id:
                    continue  # self-reference — skip
                # synthesise an input port name
                input_counter[node_id] = input_counter.get(node_id, 0) + 1
                in_port_name = f"in_{input_counter[node_id]}"
                n.inputs.append(NodePort(in_port_name, "any"))
                # only add edge if src exists
                if src_id in seen_ids:
                    graph.add_edge(src_id, src_port, node_id, in_port_name)

    return graph


__all__ = [
    "graph_to_python",
    "python_to_graph",
]
