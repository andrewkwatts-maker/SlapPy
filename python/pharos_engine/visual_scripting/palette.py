"""Starter palette of 20 visual-scripting node definitions.

Grouped into five categories — Math (10), Logic (5), Flow (3), IO (2).
Each definition is a prototype :class:`Node` carrying a
``to_python_template`` string that the codegen module fills with bound
variable names (``{port_name}`` substitution).

Templates can be:

* a single expression that assigns to the node's output ports
  (most math / logic nodes),
* a multi-line statement with ``{__indent__}`` markers handled by the
  codegen module (control-flow nodes),
* an empty string when the codegen module has a custom case
  (``Return`` is the only such today).

The catalogue lives here rather than scattered across modules so callers
can iterate the full palette in one place (``BUILTIN_NODES``). The same
prototypes register into a process-wide :data:`BUILTIN_REGISTRY` so
``get_node`` and ``list_nodes`` work without the caller threading their
own :class:`NodeRegistry` through every call.
"""
from __future__ import annotations

from .node import Node, NodePort, NodeRegistry


# ---------------------------------------------------------------------------
# Math (10)
# ---------------------------------------------------------------------------

CONSTANT = Node(
    node_type="math.constant",
    kind="math",
    inputs=[],
    outputs=[NodePort("value", "float", default=0.0)],
    params={"value": 0.0},
    to_python_template="{value} = {__param_value__}",
)

ADD = Node(
    node_type="math.add",
    kind="math",
    inputs=[NodePort("a", "float", default=0.0),
            NodePort("b", "float", default=0.0)],
    outputs=[NodePort("sum", "float")],
    to_python_template="{sum} = {a} + {b}",
)

SUBTRACT = Node(
    node_type="math.subtract",
    kind="math",
    inputs=[NodePort("a", "float", default=0.0),
            NodePort("b", "float", default=0.0)],
    outputs=[NodePort("diff", "float")],
    to_python_template="{diff} = {a} - {b}",
)

MULTIPLY = Node(
    node_type="math.multiply",
    kind="math",
    inputs=[NodePort("a", "float", default=1.0),
            NodePort("b", "float", default=1.0)],
    outputs=[NodePort("product", "float")],
    to_python_template="{product} = {a} * {b}",
)

DIVIDE = Node(
    node_type="math.divide",
    kind="math",
    inputs=[NodePort("a", "float", default=1.0),
            NodePort("b", "float", default=1.0)],
    outputs=[NodePort("quotient", "float")],
    to_python_template="{quotient} = {a} / {b} if {b} != 0 else 0.0",
)

POWER = Node(
    node_type="math.power",
    kind="math",
    inputs=[NodePort("base", "float", default=1.0),
            NodePort("exp", "float", default=2.0)],
    outputs=[NodePort("result", "float")],
    to_python_template="{result} = {base} ** {exp}",
)

SIN = Node(
    node_type="math.sin",
    kind="math",
    inputs=[NodePort("x", "float", default=0.0)],
    outputs=[NodePort("y", "float")],
    to_python_template="{y} = __import__('math').sin({x})",
)

COS = Node(
    node_type="math.cos",
    kind="math",
    inputs=[NodePort("x", "float", default=0.0)],
    outputs=[NodePort("y", "float")],
    to_python_template="{y} = __import__('math').cos({x})",
)

LERP = Node(
    node_type="math.lerp",
    kind="math",
    inputs=[NodePort("a", "float", default=0.0),
            NodePort("b", "float", default=1.0),
            NodePort("t", "float", default=0.5)],
    outputs=[NodePort("value", "float")],
    to_python_template="{value} = {a} + ({b} - {a}) * {t}",
)

CLAMP = Node(
    node_type="math.clamp",
    kind="math",
    inputs=[NodePort("x", "float", default=0.0),
            NodePort("lo", "float", default=0.0),
            NodePort("hi", "float", default=1.0)],
    outputs=[NodePort("value", "float")],
    to_python_template="{value} = max({lo}, min({hi}, {x}))",
)


# ---------------------------------------------------------------------------
# Logic (5)
# ---------------------------------------------------------------------------

IF_NODE = Node(
    node_type="logic.if",
    kind="logic",
    inputs=[NodePort("cond", "bool", default=False),
            NodePort("when_true", "any", default=None),
            NodePort("when_false", "any", default=None)],
    outputs=[NodePort("result", "any")],
    to_python_template="{result} = ({when_true}) if ({cond}) else ({when_false})",
)

AND_NODE = Node(
    node_type="logic.and",
    kind="logic",
    inputs=[NodePort("a", "bool", default=False),
            NodePort("b", "bool", default=False)],
    outputs=[NodePort("result", "bool")],
    to_python_template="{result} = bool({a}) and bool({b})",
)

OR_NODE = Node(
    node_type="logic.or",
    kind="logic",
    inputs=[NodePort("a", "bool", default=False),
            NodePort("b", "bool", default=False)],
    outputs=[NodePort("result", "bool")],
    to_python_template="{result} = bool({a}) or bool({b})",
)

NOT_NODE = Node(
    node_type="logic.not",
    kind="logic",
    inputs=[NodePort("a", "bool", default=False)],
    outputs=[NodePort("result", "bool")],
    to_python_template="{result} = not bool({a})",
)

COMPARE = Node(
    node_type="logic.compare",
    kind="logic",
    inputs=[NodePort("a", "float", default=0.0),
            NodePort("b", "float", default=0.0)],
    outputs=[NodePort("result", "bool")],
    params={"op": "=="},
    to_python_template="{result} = ({a} {__param_op_raw__} {b})",
)


# ---------------------------------------------------------------------------
# Flow (3)
# ---------------------------------------------------------------------------

# ForEach / While / Return are control-flow nodes; the codegen module has a
# dedicated case for ``control.*`` kinds that emits the proper loop/return
# scaffold rather than substituting the template literally.
FOR_EACH = Node(
    node_type="control.foreach",
    kind="control",
    inputs=[NodePort("iterable", "any", default=())],
    outputs=[NodePort("item", "any")],
    to_python_template="for {item} in {iterable}:",
)

WHILE_NODE = Node(
    node_type="control.while",
    kind="control",
    inputs=[NodePort("cond", "bool", default=False)],
    outputs=[],
    to_python_template="while {cond}:",
)

RETURN = Node(
    node_type="control.return",
    kind="control",
    inputs=[NodePort("value", "any", default=None)],
    outputs=[],
    to_python_template="return {value}",
)


# ---------------------------------------------------------------------------
# IO (2)
# ---------------------------------------------------------------------------

PRINT = Node(
    node_type="io.print",
    kind="io",
    inputs=[NodePort("message", "any", default="")],
    outputs=[],
    to_python_template="print({message})",
)

LOG_TO_STATUS_BAR = Node(
    node_type="io.log_status",
    kind="io",
    inputs=[NodePort("message", "str", default="")],
    outputs=[],
    to_python_template=(
        "__import__('pharos_engine').event_bus.EventBus.global_emit("
        "'StatusBar.Log', {message}) "
        "if hasattr(__import__('pharos_engine').event_bus.EventBus, "
        "'global_emit') else print('[status]', {message})"
    ),
)


# ---------------------------------------------------------------------------
# Master list + registry
# ---------------------------------------------------------------------------

BUILTIN_NODES: tuple[Node, ...] = (
    # Math
    CONSTANT, ADD, SUBTRACT, MULTIPLY, DIVIDE, POWER, SIN, COS, LERP, CLAMP,
    # Logic
    IF_NODE, AND_NODE, OR_NODE, NOT_NODE, COMPARE,
    # Flow
    FOR_EACH, WHILE_NODE, RETURN,
    # IO
    PRINT, LOG_TO_STATUS_BAR,
)

assert len(BUILTIN_NODES) == 20, (
    f"BUILTIN_NODES must hold exactly 20 entries; got {len(BUILTIN_NODES)}"
)

BUILTIN_REGISTRY = NodeRegistry()
for _node in BUILTIN_NODES:
    BUILTIN_REGISTRY.register(_node)


def get_node(node_type: str) -> Node:
    """Return the prototype :class:`Node` for ``node_type``.

    Raises
    ------
    KeyError
        If ``node_type`` is not in the builtin registry.
    """
    return BUILTIN_REGISTRY.get(node_type)


def list_nodes(*, kind: str | None = None) -> list[Node]:
    """Return the builtin prototypes, optionally filtered by ``kind``.

    Examples
    --------
    >>> list_nodes(kind="math")  # doctest: +SKIP
    [<Node math.constant>, <Node math.add>, ...]
    """
    if kind is None:
        return list(BUILTIN_NODES)
    return [n for n in BUILTIN_NODES if n.kind == kind]


__all__ = [
    "BUILTIN_NODES",
    "BUILTIN_REGISTRY",
    "get_node",
    "list_nodes",
    # individual prototypes (so editor code can `from palette import ADD`)
    "CONSTANT", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "POWER",
    "SIN", "COS", "LERP", "CLAMP",
    "IF_NODE", "AND_NODE", "OR_NODE", "NOT_NODE", "COMPARE",
    "FOR_EACH", "WHILE_NODE", "RETURN",
    "PRINT", "LOG_TO_STATUS_BAR",
]
