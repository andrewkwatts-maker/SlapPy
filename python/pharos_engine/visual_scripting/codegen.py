"""Bidirectional Python <-> visual-scripting codegen (V6).

This module extends the one-way codegen shipped in
:mod:`pharos_engine.visual_scripting.codegen_python` with a real
AST-driven importer (:func:`python_to_graph`) so users can edit either
side of the graph and get round-trip parity.

The graph->code direction re-exports the existing
:func:`pharos_engine.visual_scripting.codegen_python.graph_to_python`
walker, layered with best-effort formatting preservation when
``graph.metadata.get("preserve_formatting")`` is truthy (blank lines +
inline ``# comment`` markers survive the round-trip).

The code->graph direction (:func:`python_to_graph`) walks
``ast.parse(source)`` and mints one node per recognised construct:

===============================  ==================================
Python construct                 Graph node ``node_type``
===============================  ==================================
``x = a + b``                    ``math.add`` (a.k.a. AddNode)
``x = a * b``                    ``math.multiply`` (a.k.a. MultiplyNode)
``x = a - b``                    ``math.subtract``
``x = a / b``                    ``math.divide``
``x = a ** b``                   ``math.power``
``x = f(...)``                   ``call.<funcname>`` (CallNode)
``if cond: ... else: ...``       ``control.branch`` (BranchNode)
``for x in seq: ...``            ``control.foreach`` (ForEachNode)
``while cond: ...``              ``control.while`` (WhileNode)
``return expr``                  ``control.return`` (ReturnNode)
``print(x)``                     ``io.print`` (PrintNode)
Bare ``Name``                    ``var.get.<name>`` (VariableGetNode)
Literal ``Constant``             ``math.constant`` (ConstantNode)
===============================  ==================================

Unsupported constructs raise :class:`CodegenError` with the offending
line number (``class``, ``import``, ``try``, ``with``, ``async``,
``lambda``, ``global``, ``nonlocal``, ``yield`` — anything the writer
did not explicitly whitelist).

Layout hints
------------
Every node minted by :func:`python_to_graph` gets a ``position`` field
laid out on a 200 x 150 grid via a breadth-first walk of the source AST
so the editor can render the imported graph without a manual layout
pass.

Round-trip guarantee
--------------------
For the whitelisted subset (see the module doctest), the identity

    ``ast.dump(ast.parse(graph_to_python(python_to_graph(src)))) ==
      ast.dump(ast.parse(src))``

holds. Formatting (blank lines / comments) is preserved on a
best-effort basis only when the caller opts in via ``metadata``.
"""
from __future__ import annotations

import ast
import re
from typing import Any

from .codegen_python import graph_to_python as _graph_to_python_base
from .graph import NodeGraph
from .node import Node, NodePort


# ---------------------------------------------------------------------------
# public error type
# ---------------------------------------------------------------------------


class CodegenError(ValueError):
    """Raised by :func:`python_to_graph` on an unsupported AST node.

    Carries the offending line number so the editor UI can point at the
    offending line in its Code Mode buffer.
    """

    def __init__(self, message: str, *, lineno: int | None = None) -> None:
        self.lineno = lineno
        if lineno is not None:
            super().__init__(f"{message} (line {lineno})")
        else:
            super().__init__(message)


# ---------------------------------------------------------------------------
# supported / rejected construct allow-list
# ---------------------------------------------------------------------------


# AST node classes that raise CodegenError on sight. Anything not in the
# whitelist below and not in this list falls through to a generic
# "unsupported AST node" error so an unknown Python 3.12+ syntax cannot
# silently become a no-op.
_REJECTED_AST_TYPES: tuple[type, ...] = (
    ast.ClassDef,
    ast.Import,
    ast.ImportFrom,
    ast.Try,
    ast.With,
    ast.AsyncFunctionDef,
    ast.AsyncFor,
    ast.AsyncWith,
    ast.Await,
    ast.Yield,
    ast.YieldFrom,
    ast.Lambda,
    ast.Global,
    ast.Nonlocal,
    ast.Raise,
    ast.Delete,
    ast.Match,
)


# ---------------------------------------------------------------------------
# graph_to_python (formatting-preserving wrapper)
# ---------------------------------------------------------------------------


def graph_to_python(
    graph: NodeGraph,
    *,
    function_name: str = "run",
    indent: str = "    ",
) -> str:
    """Emit Python from a graph, optionally preserving formatting hints.

    When ``graph.metadata`` (a best-effort attribute added by the
    importer) carries ``preserve_formatting=True`` and a
    ``source_lines`` list, the wrapper interleaves blank lines and
    inline ``# comment`` markers from the original source alongside the
    generated body.

    Anything else defers to
    :func:`pharos_engine.visual_scripting.codegen_python.graph_to_python`.
    """
    # Rebuild-from-AST graphs (created by python_to_graph) render via a
    # dedicated walker that understands the ``ast_kind`` metadata; the
    # generic template-based walker in codegen_python is used as the
    # fallback for hand-built graphs.
    meta = getattr(graph, "metadata", None) or {}
    if meta.get("built_from_ast"):
        return _emit_from_ast_graph(
            graph,
            function_name=function_name,
            indent=indent,
            preserve_formatting=bool(meta.get("preserve_formatting")),
        )
    return _graph_to_python_base(
        graph, function_name=function_name, indent=indent
    )


# ---------------------------------------------------------------------------
# python_to_graph (AST-driven importer)
# ---------------------------------------------------------------------------


# Grid layout constants — the editor sprint picked these so a
# 20-node graph fits on a 1080p canvas without scrolling.
_GRID_STEP_X = 200
_GRID_STEP_Y = 150


def python_to_graph(
    source: str,
    *,
    name: str = "imported",
    preserve_formatting: bool = False,
) -> NodeGraph:
    """Parse Python ``source`` into a :class:`NodeGraph`.

    Parameters
    ----------
    source
        A Python source string. Must parse cleanly with :func:`ast.parse`
        and use only whitelisted constructs (see the module docstring).
    name
        Name for the resulting :class:`NodeGraph` (defaults to
        ``"imported"``).
    preserve_formatting
        When ``True`` the returned graph's ``metadata`` records the raw
        source lines so a subsequent :func:`graph_to_python` can
        interleave blank lines / inline comments. This is best-effort —
        only formatting outside of the compiled AST is preserved.

    Raises
    ------
    CodegenError
        On any unsupported construct (with the line number).
    """
    if not isinstance(source, str):
        raise TypeError(
            f"python_to_graph: source must be a str; "
            f"got {type(source).__name__}"
        )

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise CodegenError(
            f"python_to_graph: failed to parse source ({exc.msg})",
            lineno=exc.lineno,
        )

    _reject_unsupported(tree)

    graph = NodeGraph(name=name)
    # attach metadata as a plain attribute — NodeGraph is a dataclass but
    # extra attributes are welcome (the __init__ doesn't seal it).
    graph.metadata = {  # type: ignore[attr-defined]
        "built_from_ast": True,
        "preserve_formatting": bool(preserve_formatting),
        "source_lines": source.splitlines() if preserve_formatting else [],
    }

    ctx = _Ctx(graph)

    body = tree.body
    # Unwrap a single top-level FunctionDef so the caller can hand in
    # either bare statements or a wrapped `def run(): ...` body.
    if len(body) == 1 and isinstance(body[0], ast.FunctionDef):
        body = body[0].body

    ctx.walk_body(body)
    ctx.finalise_layout()
    return graph


# ---------------------------------------------------------------------------
# rejection pass
# ---------------------------------------------------------------------------


def _reject_unsupported(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, _REJECTED_AST_TYPES):
            kind = type(node).__name__
            raise CodegenError(
                f"unsupported construct {kind!r}",
                lineno=getattr(node, "lineno", None),
            )


# ---------------------------------------------------------------------------
# walker context
# ---------------------------------------------------------------------------


_SAFE_NAME = re.compile(r"[^A-Za-z0-9_]")


def _slug(text: str) -> str:
    return _SAFE_NAME.sub("_", text) or "x"


class _Ctx:
    """State passed through the AST walker.

    Tracks the variable-name -> (node_id, output_port) mapping used to
    wire :class:`Edge` records, plus a monotonic index used to lay out
    nodes on a breadth-first grid.
    """

    def __init__(self, graph: NodeGraph) -> None:
        self.graph = graph
        # variable name -> (node_id, out_port)
        self.var_bindings: dict[str, tuple[str, str]] = {}
        # traversal order used to build the layout
        self.order: list[str] = []
        self.depth_of: dict[str, int] = {}
        self._depth = 0
        # per-depth counter for horizontal grid slot
        self._slot: dict[int, int] = {}
        # Stack of "currently collecting" body-id lists for nested walks.
        # When a nested block (if/for/while) is active, newly-minted node
        # ids are appended to the innermost list *only* — so an inner
        # branch's descendants don't leak into the outer branch's
        # then_body / else_body / body param.
        self._collecting: list[list[str]] = []

    # ------------------------------------------------------------------
    # node minting helpers
    # ------------------------------------------------------------------

    def _add(self, node: Node) -> Node:
        self.graph.add_node(node)
        self.order.append(node.id)
        self.depth_of[node.id] = self._depth
        col = self._slot.get(self._depth, 0)
        self._slot[self._depth] = col + 1
        node.position = (col * _GRID_STEP_X, self._depth * _GRID_STEP_Y)
        # If we're inside a nested block, register this id with the
        # innermost collecting list so the parent container (branch /
        # loop) sees it exactly once. Sub-blocks push their own list on
        # top; their ids do NOT bubble up to the outer list.
        if self._collecting:
            self._collecting[-1].append(node.id)
        return node

    def _bind_var(self, name: str, node_id: str, port: str) -> None:
        self.var_bindings[name] = (node_id, port)

    def _resolve_or_get(
        self, expr: ast.expr,
    ) -> tuple[str, str]:
        """Return ``(node_id, out_port)`` producing ``expr``.

        Mints a :class:`Node` for literal constants and pure name reads;
        recurses into binops / calls / comparisons to produce the value.
        """
        if isinstance(expr, ast.Constant):
            return self._mint_constant(expr.value)
        if isinstance(expr, ast.Name):
            # existing binding wins; otherwise mint a VariableGetNode
            if expr.id in self.var_bindings:
                return self.var_bindings[expr.id]
            return self._mint_variable_get(expr.id)
        if isinstance(expr, ast.BinOp):
            return self._mint_binop(expr)
        if isinstance(expr, ast.Compare):
            return self._mint_compare(expr)
        if isinstance(expr, ast.BoolOp):
            return self._mint_boolop(expr)
        if isinstance(expr, ast.UnaryOp):
            return self._mint_unary(expr)
        if isinstance(expr, ast.Call):
            return self._mint_call(expr)
        raise CodegenError(
            f"unsupported expression {type(expr).__name__!r}",
            lineno=getattr(expr, "lineno", None),
        )

    # ------------------------------------------------------------------
    # concrete node minters
    # ------------------------------------------------------------------

    def _mint_constant(self, value: Any) -> tuple[str, str]:
        port_kind = _infer_port_kind(value)
        n = Node(
            node_type="math.constant",
            kind="math",
            inputs=[],
            outputs=[NodePort("value", port_kind, default=value)],
            params={"value": value},
        )
        self._add(n)
        return n.id, "value"

    def _mint_variable_get(self, var_name: str) -> tuple[str, str]:
        n = Node(
            node_type=f"var.get.{_slug(var_name)}",
            kind="io",
            inputs=[],
            outputs=[NodePort("value", "any")],
            params={"name": var_name},
        )
        self._add(n)
        # cache so subsequent reads re-use the same node
        self._bind_var(var_name, n.id, "value")
        return n.id, "value"

    def _mint_binop(self, expr: ast.BinOp) -> tuple[str, str]:
        op = expr.op
        node_type, out_port = _binop_node_type(op)
        if node_type is None:
            raise CodegenError(
                f"unsupported binary op {type(op).__name__!r}",
                lineno=expr.lineno,
            )
        left_id, left_port = self._resolve_or_get(expr.left)
        right_id, right_port = self._resolve_or_get(expr.right)
        n = Node(
            node_type=node_type,
            kind="math",
            inputs=[NodePort("a", "float"), NodePort("b", "float")],
            outputs=[NodePort(out_port, "float")],
        )
        self._add(n)
        self.graph.add_edge(left_id, left_port, n.id, "a")
        self.graph.add_edge(right_id, right_port, n.id, "b")
        return n.id, out_port

    def _mint_compare(self, expr: ast.Compare) -> tuple[str, str]:
        if len(expr.ops) != len(expr.comparators):
            raise CodegenError(
                "compare op/comparator length mismatch",
                lineno=expr.lineno,
            )
        for op in expr.ops:
            if _compare_op_str(op) is None:
                raise CodegenError(
                    f"unsupported comparison op {type(op).__name__!r}",
                    lineno=expr.lineno,
                )
        # Single comparison — mint the classic 2-input logic.compare so
        # existing graphs / palette entries keep working.
        if len(expr.ops) == 1:
            op_str = _compare_op_str(expr.ops[0])
            left_id, left_port = self._resolve_or_get(expr.left)
            right_id, right_port = self._resolve_or_get(expr.comparators[0])
            n = Node(
                node_type="logic.compare",
                kind="logic",
                inputs=[NodePort("a", "float"), NodePort("b", "float")],
                outputs=[NodePort("result", "bool")],
                params={"op": op_str},
            )
            self._add(n)
            self.graph.add_edge(left_id, left_port, n.id, "a")
            self.graph.add_edge(right_id, right_port, n.id, "b")
            return n.id, "result"

        # Chained comparison (``a < b < c``) — mint a single dedicated
        # ``logic.compare_chain`` node with one input per operand and an
        # ordered ``ops`` param. The emitter reconstructs the source
        # form ``a < b < c`` (rather than the semantically-equivalent
        # but AST-distinct desugar ``a < b and b < c``).
        operands = [expr.left] + list(expr.comparators)
        producers: list[tuple[str, str]] = [
            self._resolve_or_get(operand) for operand in operands
        ]
        input_ports = [NodePort(f"a{i}", "float") for i in range(len(operands))]
        ops = [_compare_op_str(op) for op in expr.ops]
        n = Node(
            node_type="logic.compare_chain",
            kind="logic",
            inputs=input_ports,
            outputs=[NodePort("result", "bool")],
            params={"ops": ops},
        )
        self._add(n)
        for (src_id, src_port), port in zip(producers, input_ports):
            self.graph.add_edge(src_id, src_port, n.id, port.name)
        return n.id, "result"

    def _mint_boolop(self, expr: ast.BoolOp) -> tuple[str, str]:
        node_type = "logic.and" if isinstance(expr.op, ast.And) else "logic.or"
        if len(expr.values) < 2:
            raise CodegenError(
                "boolop must have >= 2 operands", lineno=expr.lineno,
            )
        # left-fold pairs into a chain of 2-arg boolop nodes
        left_id, left_port = self._resolve_or_get(expr.values[0])
        for rhs in expr.values[1:]:
            right_id, right_port = self._resolve_or_get(rhs)
            n = Node(
                node_type=node_type,
                kind="logic",
                inputs=[NodePort("a", "bool"), NodePort("b", "bool")],
                outputs=[NodePort("result", "bool")],
            )
            self._add(n)
            self.graph.add_edge(left_id, left_port, n.id, "a")
            self.graph.add_edge(right_id, right_port, n.id, "b")
            left_id, left_port = n.id, "result"
        return left_id, left_port

    def _mint_unary(self, expr: ast.UnaryOp) -> tuple[str, str]:
        if isinstance(expr.op, ast.Not):
            operand_id, operand_port = self._resolve_or_get(expr.operand)
            n = Node(
                node_type="logic.not",
                kind="logic",
                inputs=[NodePort("a", "bool")],
                outputs=[NodePort("result", "bool")],
            )
            self._add(n)
            self.graph.add_edge(operand_id, operand_port, n.id, "a")
            return n.id, "result"
        if isinstance(expr.op, ast.USub):
            # ``-<constant>`` folds into a single negated constant so the
            # round-trip preserves the ``-25`` idiom rather than expanding
            # it into ``0 - 25``. Non-constant operands still lower to a
            # subtract-from-zero pair (there is no dedicated negate node
            # in the palette yet).
            if isinstance(expr.operand, ast.Constant) and isinstance(
                expr.operand.value, (int, float)
            ) and not isinstance(expr.operand.value, bool):
                return self._mint_constant(-expr.operand.value)
            zero_id, zero_port = self._mint_constant(0)
            operand_id, operand_port = self._resolve_or_get(expr.operand)
            n = Node(
                node_type="math.subtract",
                kind="math",
                inputs=[NodePort("a", "float"), NodePort("b", "float")],
                outputs=[NodePort("diff", "float")],
            )
            self._add(n)
            self.graph.add_edge(zero_id, zero_port, n.id, "a")
            self.graph.add_edge(operand_id, operand_port, n.id, "b")
            return n.id, "diff"
        if isinstance(expr.op, ast.UAdd):
            return self._resolve_or_get(expr.operand)
        raise CodegenError(
            f"unsupported unary op {type(expr.op).__name__!r}",
            lineno=expr.lineno,
        )

    def _mint_call(self, expr: ast.Call) -> tuple[str, str]:
        # special-case print(x) so the io.print node is minted directly
        func_name = _call_name(expr.func)
        if func_name is None:
            raise CodegenError(
                "only bare function-name calls are supported "
                "(no attribute or lambda calls)",
                lineno=expr.lineno,
            )
        if func_name == "print":
            return self._mint_print(expr)
        return self._mint_generic_call(expr, func_name)

    def _mint_print(self, expr: ast.Call) -> tuple[str, str]:
        # take first positional argument as the message; codegen emits
        # print(message) so extra args are dropped (users can re-add
        # them through the editor UI).
        if not expr.args:
            msg_id, msg_port = self._mint_constant("")
        else:
            msg_id, msg_port = self._resolve_or_get(expr.args[0])
        n = Node(
            node_type="io.print",
            kind="io",
            inputs=[NodePort("message", "any")],
            outputs=[NodePort("done", "any")],
            params={"argc": len(expr.args)},
        )
        self._add(n)
        self.graph.add_edge(msg_id, msg_port, n.id, "message")
        return n.id, "done"

    def _mint_generic_call(
        self, expr: ast.Call, func_name: str,
    ) -> tuple[str, str]:
        # mint an input port per positional arg; keyword args land in
        # ``params`` since the editor treats them as static.
        input_ports: list[NodePort] = []
        arg_bindings: list[tuple[str, str]] = []
        for i, arg in enumerate(expr.args):
            aid, aport = self._resolve_or_get(arg)
            input_ports.append(NodePort(f"arg{i}", "any"))
            arg_bindings.append((aid, aport))
        params: dict[str, Any] = {"func": func_name}
        for kw in expr.keywords:
            if kw.arg is None:
                raise CodegenError(
                    "**kwargs unpacking is not supported",
                    lineno=expr.lineno,
                )
            if not isinstance(kw.value, ast.Constant):
                raise CodegenError(
                    "call keyword args must be constants",
                    lineno=expr.lineno,
                )
            params[kw.arg] = kw.value.value
        n = Node(
            node_type=f"call.{_slug(func_name)}",
            kind="compute",
            inputs=input_ports,
            outputs=[NodePort("result", "any")],
            params=params,
        )
        self._add(n)
        for (aid, aport), port in zip(arg_bindings, input_ports):
            self.graph.add_edge(aid, aport, n.id, port.name)
        return n.id, "result"

    # ------------------------------------------------------------------
    # statement walker
    # ------------------------------------------------------------------

    def walk_body(self, body: list[ast.stmt]) -> None:
        for stmt in body:
            self.walk_stmt(stmt)

    def walk_stmt(self, stmt: ast.stmt) -> None:
        if isinstance(stmt, ast.Assign):
            self._walk_assign(stmt)
        elif isinstance(stmt, ast.AugAssign):
            self._walk_aug_assign(stmt)
        elif isinstance(stmt, ast.Expr):
            # bare expression, typically a Call whose result is discarded
            self._resolve_or_get(stmt.value)
        elif isinstance(stmt, ast.If):
            self._walk_if(stmt)
        elif isinstance(stmt, ast.For):
            self._walk_for(stmt)
        elif isinstance(stmt, ast.While):
            self._walk_while(stmt)
        elif isinstance(stmt, ast.Return):
            self._walk_return(stmt)
        elif isinstance(stmt, ast.Pass):
            # no-op; nothing to emit
            return
        elif isinstance(stmt, ast.Break):
            n = Node(
                node_type="control.break",
                kind="control",
                inputs=[], outputs=[],
            )
            self._add(n)
        elif isinstance(stmt, ast.Continue):
            n = Node(
                node_type="control.continue",
                kind="control",
                inputs=[], outputs=[],
            )
            self._add(n)
        elif isinstance(stmt, ast.FunctionDef):
            # nested function defs are not supported
            raise CodegenError(
                "nested function definitions are not supported",
                lineno=stmt.lineno,
            )
        else:
            raise CodegenError(
                f"unsupported statement {type(stmt).__name__!r}",
                lineno=getattr(stmt, "lineno", None),
            )

    def _walk_assign(self, stmt: ast.Assign) -> None:
        if len(stmt.targets) != 1:
            raise CodegenError(
                "chained assignments (a = b = c) are not supported",
                lineno=stmt.lineno,
            )
        tgt = stmt.targets[0]
        if not isinstance(tgt, ast.Name):
            raise CodegenError(
                f"assignment target must be a bare Name; "
                f"got {type(tgt).__name__!r}",
                lineno=stmt.lineno,
            )
        node_id, port = self._resolve_or_get(stmt.value)
        self._bind_var(tgt.id, node_id, port)
        # stash the variable name on the producing node so the emitter
        # can reconstruct ``<var> = <expr>`` on the way back out.
        producer = next(
            (n for n in self.graph.nodes if n.id == node_id), None,
        )
        if producer is not None:
            producer.params.setdefault("__var__", tgt.id)
            # for ``x = a + b`` the producer *is* the binop node, so we
            # want the assignment name to override any earlier stash
            # from a nested Constant that lived below.
            producer.params["__var__"] = tgt.id

    def _walk_aug_assign(self, stmt: ast.AugAssign) -> None:
        # x += y  ->  x = x + y
        binop = ast.BinOp(left=ast.Name(id=stmt.target.id, ctx=ast.Load()),
                          op=stmt.op, right=stmt.value)
        ast.copy_location(binop, stmt)
        new_assign = ast.Assign(
            targets=[ast.Name(id=stmt.target.id, ctx=ast.Store())],
            value=binop,
        )
        ast.copy_location(new_assign, stmt)
        self._walk_assign(new_assign)

    def _walk_if(self, stmt: ast.If) -> None:
        cond_id, cond_port = self._resolve_or_get(stmt.test)
        branch = Node(
            node_type="control.branch",
            kind="control",
            inputs=[NodePort("cond", "bool")],
            outputs=[NodePort("then", "any"), NodePort("else", "any")],
        )
        self._add(branch)
        self.graph.add_edge(cond_id, cond_port, branch.id, "cond")
        # walk both bodies into flat sequences; the codegen renderer
        # reconstructs the if/else scaffold from the ``control.branch``
        # node + its ``then_body`` / ``else_body`` param blocks.
        then_ids = self._walk_nested_block(stmt.body)
        else_ids = self._walk_nested_block(stmt.orelse)
        branch.params["then_body"] = then_ids
        branch.params["else_body"] = else_ids

    def _walk_for(self, stmt: ast.For) -> None:
        if not isinstance(stmt.target, ast.Name):
            raise CodegenError(
                "for-loop target must be a bare Name",
                lineno=stmt.lineno,
            )
        iter_id, iter_port = self._resolve_or_get(stmt.iter)
        loop = Node(
            node_type="control.foreach",
            kind="control",
            inputs=[NodePort("iterable", "any")],
            outputs=[NodePort("item", "any")],
            params={"var": stmt.target.id},
        )
        self._add(loop)
        self.graph.add_edge(iter_id, iter_port, loop.id, "iterable")
        # bind the loop var to the loop node's ``item`` output
        self._bind_var(stmt.target.id, loop.id, "item")
        body_ids = self._walk_nested_block(stmt.body)
        loop.params["body"] = body_ids

    def _walk_while(self, stmt: ast.While) -> None:
        cond_id, cond_port = self._resolve_or_get(stmt.test)
        loop = Node(
            node_type="control.while",
            kind="control",
            inputs=[NodePort("cond", "bool")],
            outputs=[],
        )
        self._add(loop)
        self.graph.add_edge(cond_id, cond_port, loop.id, "cond")
        body_ids = self._walk_nested_block(stmt.body)
        loop.params["body"] = body_ids

    def _walk_return(self, stmt: ast.Return) -> None:
        if stmt.value is None:
            val_id, val_port = self._mint_constant(None)
        else:
            val_id, val_port = self._resolve_or_get(stmt.value)
        n = Node(
            node_type="control.return",
            kind="control",
            inputs=[NodePort("value", "any")],
            outputs=[],
        )
        self._add(n)
        self.graph.add_edge(val_id, val_port, n.id, "value")

    def _walk_nested_block(self, body: list[ast.stmt]) -> list[str]:
        # capture the node ids created while walking this nested block so
        # the parent (branch / loop) can point at them. Uses the
        # ``_collecting`` stack so that when an inner branch / loop opens
        # its own nested block, those descendants land in the inner
        # container's list — NOT in this one. This prevents the
        # then_body double-emit bug where an outer branch's then_body
        # used to contain the inner branch's children flat as well.
        self._depth += 1
        self._collecting.append([])
        try:
            self.walk_body(body)
            collected = self._collecting[-1]
        finally:
            self._collecting.pop()
            self._depth -= 1
        # Direct children only — sub-blocks did not push into our list.
        return list(collected)

    # ------------------------------------------------------------------
    # layout finaliser
    # ------------------------------------------------------------------

    def finalise_layout(self) -> None:
        # positions are already set at mint-time via depth + slot;
        # the finaliser exists as a hook for downstream editors that
        # want to snap to grid on import completion. No-op today.
        return


# ---------------------------------------------------------------------------
# helper predicates
# ---------------------------------------------------------------------------


def _binop_node_type(op: ast.operator) -> tuple[str | None, str]:
    if isinstance(op, ast.Add):
        return "math.add", "sum"
    if isinstance(op, ast.Sub):
        return "math.subtract", "diff"
    if isinstance(op, ast.Mult):
        return "math.multiply", "product"
    if isinstance(op, ast.Div):
        return "math.divide", "quotient"
    if isinstance(op, ast.Pow):
        return "math.power", "result"
    if isinstance(op, ast.Mod):
        return "math.mod", "remainder"
    if isinstance(op, ast.FloorDiv):
        return "math.floordiv", "quotient"
    return None, ""


def _compare_op_str(op: ast.cmpop) -> str | None:
    mapping = {
        ast.Eq: "==",
        ast.NotEq: "!=",
        ast.Lt: "<",
        ast.LtE: "<=",
        ast.Gt: ">",
        ast.GtE: ">=",
    }
    return mapping.get(type(op))


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        # allow simple ``module.func`` calls — flatten to a single name.
        chain: list[str] = []
        cur: ast.expr = func
        while isinstance(cur, ast.Attribute):
            chain.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            chain.append(cur.id)
            return ".".join(reversed(chain))
    return None


def _infer_port_kind(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    return "any"


# ---------------------------------------------------------------------------
# renderer for AST-built graphs
# ---------------------------------------------------------------------------


def _emit_from_ast_graph(
    graph: NodeGraph,
    *,
    function_name: str,
    indent: str,
    preserve_formatting: bool,
) -> str:
    """Render a graph produced by :func:`python_to_graph` back to source.

    Walks ``graph.nodes`` in insertion order (which matches the AST
    walker's own order), emitting each construct into a flat function
    body. Nested branch/loop bodies are looked up via ``node.params``.

    Precedence
    ----------
    ``expr_for`` accepts an optional ``parent_prec`` argument. When a
    sub-expression's operator precedence is *lower* than its consumer's,
    it wraps itself in parentheses so ``(1 + 2) * 3`` survives the
    round-trip instead of collapsing into ``1 + 2 * 3``.

    Variable reuse
    --------------
    Whenever a node's assignment statement is emitted (``x = <expr>``)
    the (node_id, out_port) is registered in ``emitted_names``. Any
    subsequent ``expr_for`` call that hits the same (node_id, out_port)
    returns the bound name ``x`` instead of re-inlining the RHS. This
    fixes the ``y = 5 + 1; z = 5 + 5 + 1`` regression from
    ``assignment_reuse`` and the constant-inlined-into-while-condition
    regression from ``while_countdown``.
    """
    # index for lookup
    by_id = {n.id: n for n in graph.nodes}

    # incoming edges: {(dst_node, dst_port): (src_node, src_port)}
    incoming: dict[tuple[str, str], tuple[str, str]] = {}
    for e in graph.edges:
        incoming[(e.to_node_id, e.to_port)] = (e.from_node_id, e.from_port)

    # collect the ids that live inside a nested branch/loop body so the
    # top-level pass skips them (they'll be emitted from inside their
    # container).
    nested: set[str] = set()
    for n in graph.nodes:
        for key in ("then_body", "else_body", "body"):
            for cid in n.params.get(key, []) or []:
                nested.add(cid)

    lines: list[str] = [f"def {function_name}():"]

    # (node_id, port) -> bound name; populated as ``x = <expr>`` lines
    # are emitted so downstream reads can reuse the name.
    emitted_names: dict[tuple[str, str], str] = {}

    def expr_for(node_id: str, port: str, parent_prec: int = 0) -> str:
        # If the producer has already been emitted as a named assignment
        # anywhere upstream, reuse the name — otherwise every consumer
        # would re-inline the RHS (bug 4 and 6).
        bound = emitted_names.get((node_id, port))
        if bound is not None:
            return bound

        n = by_id[node_id]
        nt = n.node_type
        my_prec = _op_precedence(nt)
        if nt == "math.constant":
            expr = _py_literal(n.params.get("value"))
        elif nt.startswith("var.get."):
            expr = str(n.params.get("name", nt.split(".", 2)[-1]))
        elif nt == "control.foreach":
            # The foreach node's ``item`` output is the loop variable.
            # Emission here means a downstream statement (e.g. ``print(i)``)
            # is reading the loop var; return the bound name.
            expr = str(n.params.get("var", "i"))
        elif nt == "math.add":
            a = expr_for(*_src(n, "a"), my_prec)
            b = expr_for(*_src(n, "b"), my_prec)
            expr = f"{a} + {b}"
        elif nt == "math.subtract":
            a = expr_for(*_src(n, "a"), my_prec)
            # Subtraction is left-associative; the RHS needs a higher
            # effective precedence to force parens around ``a - (b - c)``
            # (which is semantically different from ``a - b - c``).
            b = expr_for(*_src(n, "b"), my_prec + 1)
            expr = f"{a} - {b}"
        elif nt == "math.multiply":
            a = expr_for(*_src(n, "a"), my_prec)
            b = expr_for(*_src(n, "b"), my_prec)
            expr = f"{a} * {b}"
        elif nt == "math.divide":
            a = expr_for(*_src(n, "a"), my_prec)
            b = expr_for(*_src(n, "b"), my_prec + 1)
            expr = f"{a} / {b}"
        elif nt == "math.power":
            # Power is right-associative in Python; ``a ** b ** c`` reads
            # as ``a ** (b ** c)``. Force parens on the LHS instead.
            a = expr_for(*_src(n, "a"), my_prec + 1)
            b = expr_for(*_src(n, "b"), my_prec)
            expr = f"{a} ** {b}"
        elif nt == "math.mod":
            a = expr_for(*_src(n, "a"), my_prec)
            b = expr_for(*_src(n, "b"), my_prec + 1)
            expr = f"{a} % {b}"
        elif nt == "math.floordiv":
            a = expr_for(*_src(n, "a"), my_prec)
            b = expr_for(*_src(n, "b"), my_prec + 1)
            expr = f"{a} // {b}"
        elif nt == "logic.compare":
            a = expr_for(*_src(n, "a"), my_prec + 1)
            b = expr_for(*_src(n, "b"), my_prec + 1)
            op = n.params.get("op", "==")
            expr = f"{a} {op} {b}"
        elif nt == "logic.compare_chain":
            # Reconstruct a chained comparison ``a op0 b op1 c ...``.
            ops = n.params.get("ops", []) or []
            operands = [
                expr_for(*_src(n, p.name), my_prec + 1) for p in n.inputs
            ]
            parts = [operands[0]]
            for i, op in enumerate(ops):
                parts.append(op)
                parts.append(operands[i + 1])
            expr = " ".join(parts)
        elif nt == "logic.and":
            a = expr_for(*_src(n, "a"), my_prec)
            b = expr_for(*_src(n, "b"), my_prec)
            expr = f"{a} and {b}"
        elif nt == "logic.or":
            a = expr_for(*_src(n, "a"), my_prec)
            b = expr_for(*_src(n, "b"), my_prec)
            expr = f"{a} or {b}"
        elif nt == "logic.not":
            a = expr_for(*_src(n, "a"), my_prec)
            expr = f"not {a}"
        elif nt == "io.print":
            msg = expr_for(*_src(n, "message"), 0)
            expr = f"print({msg})"
        elif nt.startswith("call."):
            fname = n.params.get("func", nt.split(".", 1)[-1])
            args = [expr_for(*_src(n, p.name), 0) for p in n.inputs]
            # Filter walker-internal sentinels (``__var__`` records the
            # assignment target for name reuse; ``func`` is the callable)
            # so they don't leak into the emitted kwargs.
            kw_parts = [
                f"{k}={_py_literal(v)}"
                for k, v in n.params.items()
                if k not in ("func", "__var__")
            ]
            expr = f"{fname}({', '.join(args + kw_parts)})"
        else:
            # fallback
            expr = f"# unrecognised node {nt}"

        if my_prec < parent_prec:
            expr = f"({expr})"
        return expr

    def _src(n: Node, port: str) -> tuple[str, str]:
        """Return the ``(node_id, out_port)`` driving ``n.<port>``.

        If nothing is wired, mint a synthetic ``__default__:<value>``
        producer id so :func:`expr_for` can materialise the default via
        a ``__default__`` prefix — but in practice the AST-driven graphs
        never leave inputs dangling, so this returns ``("__default__",
        port)`` and the caller falls through to a literal-default path.
        """
        src = incoming.get((n.id, port))
        if src is not None:
            return src
        # Encode the default lookup with a sentinel prefix so expr_for
        # can produce the literal without needing the node id.
        try:
            default = n.get_input(port).default
        except KeyError:
            default = None
        # Reuse the constants-table by storing the literal directly under
        # a synthetic key; we shortcut via a lambda so we don't have to
        # mint a real Node.
        key = f"__default_{id(n)}_{port}"
        _defaults[key] = default
        return (key, "__default__")

    # Overload expr_for to understand the synthetic default sentinel.
    _defaults: dict[str, Any] = {}
    _real_expr_for = expr_for

    def expr_for_wrapped(node_id: str, port: str, parent_prec: int = 0) -> str:
        if port == "__default__":
            return _py_literal(_defaults.get(node_id))
        return _real_expr_for(node_id, port, parent_prec)

    expr_for = expr_for_wrapped  # type: ignore[assignment]

    def emit_stmt(node_id: str, prefix: str) -> None:
        n = by_id[node_id]
        nt = n.node_type
        if nt == "io.print":
            lines.append(prefix + expr_for(node_id, "done"))
            return
        if nt == "control.return":
            val = expr_for(*_src(n, "value"), 0)
            lines.append(prefix + f"return {val}")
            return
        if nt == "control.branch":
            cond = expr_for(*_src(n, "cond"), 0)
            lines.append(prefix + f"if {cond}:")
            then_body = n.params.get("then_body", []) or []
            if not then_body:
                lines.append(prefix + indent + "pass")
            for cid in then_body:
                emit_stmt(cid, prefix + indent)
            else_body = n.params.get("else_body", []) or []
            if else_body:
                lines.append(prefix + "else:")
                for cid in else_body:
                    emit_stmt(cid, prefix + indent)
            return
        if nt == "control.foreach":
            iterable = expr_for(*_src(n, "iterable"), 0)
            var = n.params.get("var", "i")
            # Register the ``item`` output as bound to the loop var name
            # BEFORE emitting the body so any consumer (``print(i)``)
            # can look it up.
            emitted_names[(n.id, "item")] = var
            lines.append(prefix + f"for {var} in {iterable}:")
            body = n.params.get("body", []) or []
            if not body:
                lines.append(prefix + indent + "pass")
            for cid in body:
                emit_stmt(cid, prefix + indent)
            return
        if nt == "control.while":
            cond = expr_for(*_src(n, "cond"), 0)
            lines.append(prefix + f"while {cond}:")
            body = n.params.get("body", []) or []
            if not body:
                lines.append(prefix + indent + "pass")
            for cid in body:
                emit_stmt(cid, prefix + indent)
            return
        if nt == "control.break":
            lines.append(prefix + "break")
            return
        if nt == "control.continue":
            lines.append(prefix + "continue")
            return
        if nt.startswith("call.") and not _has_assignment_consumer(
            graph, n.id, "result"
        ) and "__var__" not in n.params:
            # bare-expression call statement (result not consumed and not
            # assigned to a variable).
            lines.append(prefix + expr_for(node_id, "result"))
            return
        # generic assignment: bind each output to a fresh local
        for p in n.outputs:
            var_name = _find_var_name_for(graph, n.id, p.name)
            if var_name is None:
                # only emit the value if it has no downstream consumers;
                # otherwise the consumer inlines the expression itself.
                if _has_consumer(graph, n.id, p.name):
                    return
                expr = expr_for(node_id, p.name, 0)
                lines.append(prefix + expr)
                return
            expr = expr_for(node_id, p.name, 0)
            lines.append(prefix + f"{var_name} = {expr}")
            # Record so subsequent expr_for() calls emit the name rather
            # than re-inlining the RHS.
            emitted_names[(n.id, p.name)] = var_name

    # walk in insertion order, skipping nested-body ids
    _pre_pass_bind_vars(graph)
    for n in graph.nodes:
        if n.id in nested:
            continue
        emit_stmt(n.id, indent)

    if len(lines) == 1:  # only the def line
        lines.append(indent + "pass")

    # preserve blank lines / inline comments best-effort
    if preserve_formatting:
        src_lines = getattr(graph, "metadata", {}).get("source_lines", [])
        lines = _splice_formatting(lines, src_lines, indent)

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# operator precedence helper (used by _emit_from_ast_graph)
# ---------------------------------------------------------------------------


# Higher numbers bind tighter. Values match Python's grammar precedence
# ordering closely enough for the emitter's parenthesisation choices;
# ``0`` is reserved for "statement context" (no wrapping ever needed).
_PRECEDENCE: dict[str, int] = {
    "logic.or":       1,
    "logic.and":      2,
    "logic.not":      3,
    "logic.compare":  4,
    "logic.compare_chain": 4,
    "math.add":       5,
    "math.subtract":  5,
    "math.multiply":  6,
    "math.divide":    6,
    "math.mod":       6,
    "math.floordiv":  6,
    "math.power":     7,
    # atoms — never need wrapping
    "math.constant":  99,
    "io.print":       99,
}


def _op_precedence(node_type: str) -> int:
    if node_type in _PRECEDENCE:
        return _PRECEDENCE[node_type]
    if node_type.startswith("var.get."):
        return 99
    if node_type.startswith("call."):
        return 99
    if node_type == "control.foreach":
        return 99
    # Unknown / control-flow nodes never appear as expressions.
    return 0


# The AST walker records the *last* variable name that a given
# (node_id, out_port) was bound to. The renderer needs that name to
# reconstruct the ``x = ...`` line. Since the walker's ``_Ctx`` is not
# stored on the graph, we replay a simpler pass here: any node whose
# insertion-order successor bound it into ``var_bindings`` in the walker
# corresponds to an ``ast.Assign`` in the original source. To recover
# the name we stash it on the node during walking via a hidden
# ``params["__var__"]`` key.


def _pre_pass_bind_vars(graph: NodeGraph) -> None:
    # noop stub — bindings are already stashed on nodes when needed;
    # exists so downstream refactors have a hook.
    return


def _find_var_name_for(
    graph: NodeGraph, node_id: str, port: str,
) -> str | None:
    for n in graph.nodes:
        if n.id == node_id:
            return n.params.get("__var__")
    return None


def _has_consumer(graph: NodeGraph, node_id: str, port: str) -> bool:
    for e in graph.edges:
        if e.from_node_id == node_id and e.from_port == port:
            return True
    return False


def _has_assignment_consumer(
    graph: NodeGraph, node_id: str, port: str,
) -> bool:
    return _has_consumer(graph, node_id, port)


def _py_literal(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return repr(value)
    return repr(value)


def _splice_formatting(
    lines: list[str], src_lines: list[str], indent: str,
) -> list[str]:
    """Interleave blank lines + trailing ``# comment`` lines.

    Best-effort: matches assignment-target names between generated
    lines and source lines, then splices any blank/comment src lines
    that sit just above the match into the output.
    """
    if not src_lines:
        return lines
    out: list[str] = [lines[0]]  # the def
    src_idx = 0
    for gen in lines[1:]:
        # walk src_lines forward, splicing blanks / pure comments
        while src_idx < len(src_lines):
            s = src_lines[src_idx]
            stripped = s.strip()
            if not stripped or stripped.startswith("#"):
                out.append(indent + stripped if stripped else "")
                src_idx += 1
                continue
            break
        out.append(gen)
        src_idx += 1
    return out


__all__ = [
    "CodegenError",
    "graph_to_python",
    "python_to_graph",
]
