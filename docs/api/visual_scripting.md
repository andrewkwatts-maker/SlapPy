<!-- handauthored: do not regenerate -->
# slappyengine.visual_scripting — API Reference

> Hand-written reference for the visual-scripting **backbone** —
> the headless graph data model, validator, YAML round-trip, Python
> code generator and 20-node starter palette. The editor UI that
> surfaces this data model lands in a follow-up sprint; the surface
> documented here stays framework-agnostic. For the material-graph
> sibling system (used for shader authoring) see
> [`material.md`](material.md).

## Overview

`slappyengine.visual_scripting` owns the data model behind the editor's
node-graph authoring surface. The runtime is intentionally minimal:

* a typed :class:`Node` / :class:`NodePort` data model with eight
  ``NodeKind`` flavours (`compute`, `io`, `control`, `math`, `logic`,
  `render`, `audio`, `event`) and eight ``PortKind`` flavours (`float`,
  `int`, `bool`, `str`, `vec2`, `vec3`, `vec4`, `any`),
* a :class:`NodeGraph` that owns the ``nodes`` / ``edges`` topology, a
  validator that rejects cycles / dangling refs / port-kind mismatches,
  a :meth:`NodeGraph.topological_order` walker, and a YAML round-trip,
* a Python code generator that compiles a graph into a runnable function
  string (and a best-effort inverse importer for round-trip tests),
* a :data:`BUILTIN_NODES` palette of 20 starter prototypes registered
  into a process-wide :data:`BUILTIN_REGISTRY` so the editor's spawn
  menu can iterate them without setting up a registry of its own.

Pipeline shape: build a :class:`NodeGraph`, spawn prototype nodes via
``get_node(node_type).clone()``, wire them up with
:meth:`NodeGraph.add_edge`, call :meth:`NodeGraph.validate` to check
invariants, then either :meth:`NodeGraph.to_yaml` for persistence or
:func:`graph_to_python` to compile to a Python function.

Lazy-import contract: the subpackage is plain Python with no
``wgpu`` / Rust / heavy dependencies, so a bare
``from slappyengine import visual_scripting`` is cheap. The top-level
``slappyengine.__getattr__`` exposes the module via the
``_subpackages`` set; there is no ``_LAZY_MAP`` per-symbol entry
because the per-class surface stays inside the subpackage.

## Public surface

```python
from slappyengine.visual_scripting import (
    # primitives
    Node, NodeKind, NodePort, PortKind, NodeRegistry,
    NODE_KINDS, PORT_KINDS, ports_compatible,
    # graph
    Edge, NodeGraph, GraphValidationError,
    # codegen
    graph_to_python, python_to_graph,
    # palette
    BUILTIN_NODES, BUILTIN_REGISTRY, get_node, list_nodes,
)
```

The eight builtin prototype names (e.g. ``ADD``, ``LERP``,
``IF_NODE``) are also exported from :mod:`slappyengine.visual_scripting.palette`
for callers that want to reference them by Python identifier instead
of the ``node_type`` string.

## Classes

### `NodePort`

_dataclass — defined in `slappyengine.visual_scripting.node`_

A single typed port on a :class:`Node`. Inputs and outputs share the
same record; direction is implied by which list the port lives in on
the parent node.

```python
NodePort(name: str, port_kind: PortKind, default: Any = None) -> None
```

Raises ``ValueError`` if ``port_kind`` is not in :data:`PORT_KINDS`.
``default`` is rendered by the codegen module as a Python literal when
the port is unwired.

### `Node`

_dataclass — defined in `slappyengine.visual_scripting.node`_

```python
Node(
    node_type: str,
    kind: NodeKind,
    inputs: list[NodePort] = [],
    outputs: list[NodePort] = [],
    params: dict[str, Any] = {},
    position: tuple[int, int] = (0, 0),
    name: str = "",
    id: str = "",
    to_python_template: str = "",
) -> None
```

`node_type` is the registry key (e.g. `"math.add"`); `name` is an
instance-level display label that defaults to `node_type`. `id` is
auto-assigned (`n_<8-hex>`) when blank so callers can build a graph
without thinking about ids. `to_python_template` is the codegen
template (see *Code generation* below).

#### Methods

- `input_names(self) -> list[str]`, `output_names(self) -> list[str]`
- `get_input(self, name) -> NodePort`, `get_output(self, name) -> NodePort`
- `clone(self, *, new_id: bool = True) -> Node` — deep copy, optionally
  with a fresh id.
- `to_dict()` / `from_dict(data)` — JSON-style serialisation used by
  :meth:`NodeGraph.to_yaml`.

### `NodeRegistry`

_class — defined in `slappyengine.visual_scripting.node`_

Registry of available node *prototypes* keyed by ``node_type``. The
registry stores prototype `Node` records; callers should invoke
:meth:`NodeRegistry.spawn` (which mints a unique id) rather than
adding pre-spawned nodes to the graph.

#### Methods

- `register(self, node: Node) -> Node` — raises `ValueError` if the
  `node_type` is already registered.
- `unregister(self, node_type: str) -> None`
- `get(self, node_type: str) -> Node` — raises `KeyError` on miss.
- `has(self, node_type: str) -> bool`
- `spawn(self, node_type, *, position=(0, 0), params=None) -> Node` —
  clone + assign position + apply param overrides.
- `list_types(self, *, kind: NodeKind | None = None) -> list[str]`

### `Edge`

_dataclass — defined in `slappyengine.visual_scripting.graph`_

```python
Edge(from_node_id: str, from_port: str, to_node_id: str, to_port: str)
```

A directed connection between two ports on two nodes. All four fields
are validated to be non-empty strings; structural checks (the nodes
exist, the ports exist on them, the port kinds line up) live in
:meth:`NodeGraph.validate`.

### `NodeGraph`

_dataclass — defined in `slappyengine.visual_scripting.graph`_

Ordered collection of :class:`Node` records plus a list of
:class:`Edge` records. The graph is the *whole* serialisable artefact;
runtime evaluation is delegated to :func:`graph_to_python` so the
walker can be swapped (CPU vs Rust-backed vs editor live-preview)
without touching the data model.

```python
NodeGraph(nodes: list[Node] = [], edges: list[Edge] = [], name: str = "untitled")
```

#### Methods

- `add_node(self, node: Node) -> Node` — duplicate ids raise `ValueError`.
- `add_edge(self, from_node, from_port, to_node, to_port) -> Edge` —
  `from_node` / `to_node` may be a `Node` instance or its id string.
- `get_node(self, node_id) -> Node` / `remove_node(self, node_id) -> None`
- `incoming_edges(self, node_id) -> list[Edge]` /
  `outgoing_edges(self, node_id) -> list[Edge]`
- `validate(self, *, raise_on_error: bool = True) -> list[str]` —
  runs duplicate-id / dangling-ref / port-existence / port-kind /
  cycle checks; raises `GraphValidationError` carrying every error
  string by default.
- `topological_order(self) -> list[Node]` — Kahn's algorithm; raises
  `GraphValidationError` on cycles. Ties are broken by insertion order.
- `to_yaml(self) -> str` / `from_yaml(cls, source: str) -> NodeGraph`
- `to_dict(self) -> dict` / `from_dict(cls, data) -> NodeGraph`

### `GraphValidationError`

_exception (subclass of `ValueError`) — defined in
`slappyengine.visual_scripting.graph`_

Raised by :meth:`NodeGraph.validate` and
:meth:`NodeGraph.topological_order`. Carries an ``errors: list[str]``
attribute so the editor UI can show every issue rather than truncating
to the first message.

## Functions

### `ports_compatible(from_kind: PortKind, to_kind: PortKind) -> bool`

_defined in `slappyengine.visual_scripting.node`_

Return `True` iff a `from_kind` output can drive a `to_kind` input.
Widening rules:

- `any` is symmetrically compatible with every kind.
- `int` can drive `int` / `float`.
- All other kinds match only themselves (and `any`).

Both arguments are validated against `PORT_KINDS`; a typo at the call
site raises `ValueError` rather than silently returning `False`.

### `graph_to_python(graph: NodeGraph, *, function_name: str = "run", indent: str = "    ") -> str`

_defined in `slappyengine.visual_scripting.codegen_python`_

Walk `graph` in topological order and emit a Python function. Each
node's `to_python_template` is substituted with bound variable names:

- Each output port is bound to `v_<node_id>_<port_name>`.
- Each input port resolves to the upstream edge's source variable, or
  to the port's `default` rendered as a Python literal when unwired.
- `{__param_<name>__}` markers substitute the param as a literal
  (string params come out quoted); `{__param_<name>_raw__}` markers
  substitute the param verbatim (used by `logic.compare` for the
  comparator op).

Control-flow nodes (`control.foreach` / `control.while` /
`control.return`) bypass template substitution and emit
hand-crafted scaffolds. The function always ends with a `return`
(either an explicit `control.return` or a dict of the final node's
output bindings) so the caller can `exec` it and inspect the result.

### `python_to_graph(source: str, *, name: str = "imported") -> NodeGraph`

_defined in `slappyengine.visual_scripting.codegen_python`_

Best-effort inverse: parses `v_<id>_<port> = <expr>` assignments from
`source` and rebuilds the topology — one synthesised `Node` per unique
`<id>`, one `Edge` per cross-reference between assignment RHS values.
Useful for round-trip tests of generated code; the editor sprint will
replace this with an AST-driven importer that recognises every
template family.

Raises `ValueError` if `source` is not parseable Python.

### `get_node(node_type: str) -> Node`

_defined in `slappyengine.visual_scripting.palette`_

Return the prototype `Node` for `node_type` from the builtin registry.
Raises `KeyError` on miss.

### `list_nodes(*, kind: NodeKind | None = None) -> list[Node]`

_defined in `slappyengine.visual_scripting.palette`_

Return the builtin prototypes, optionally filtered by `kind`.

## Constants

### `NODE_KINDS`

_frozenset[str] — defined in `slappyengine.visual_scripting.node`_

Allow-list of node-kind tags: `compute`, `io`, `control`, `math`,
`logic`, `render`, `audio`, `event`.

### `PORT_KINDS`

_frozenset[str] — defined in `slappyengine.visual_scripting.node`_

Allow-list of port-kind tags: `float`, `int`, `bool`, `str`, `vec2`,
`vec3`, `vec4`, `any`.

### `BUILTIN_NODES`

_tuple[Node, ...] — defined in `slappyengine.visual_scripting.palette`_

The 20 starter prototypes. Composition:

- **Math (10):** `math.constant`, `math.add`, `math.subtract`,
  `math.multiply`, `math.divide`, `math.power`, `math.sin`,
  `math.cos`, `math.lerp`, `math.clamp`.
- **Logic (5):** `logic.if`, `logic.and`, `logic.or`, `logic.not`,
  `logic.compare`.
- **Flow (3):** `control.foreach`, `control.while`, `control.return`.
- **IO (2):** `io.print`, `io.log_status`.

### `BUILTIN_REGISTRY`

_NodeRegistry — defined in `slappyengine.visual_scripting.palette`_

A process-wide `NodeRegistry` pre-populated with `BUILTIN_NODES`. The
editor's spawn menu walks this registry; `get_node` /
`list_nodes` are thin facades over it.

## Code generation

```text
graph_to_python(graph)
  ├─ graph.validate()                    # raise on any structural issue
  ├─ graph.topological_order()           # Kahn's algorithm
  └─ for each node in dependency order:
        emit  v_<id>_<port> = <template-filled rhs>
        (control.* nodes emit for: / while: / return scaffolds instead)
  └─ ensure trailing return so the function evaluates cleanly
```

The generated function is callable with no arguments by default and
returns a dict `{port_name: value, ...}` of the *last* node's outputs
unless a `control.return` short-circuits it earlier.

## Inner modules

- `node` — `Node`, `NodePort`, `NodeRegistry`, `NODE_KINDS`,
  `PORT_KINDS`, `ports_compatible`.
- `graph` — `Edge`, `NodeGraph`, `GraphValidationError`.
- `codegen_python` — `graph_to_python`, `python_to_graph`.
- `palette` — `BUILTIN_NODES`, `BUILTIN_REGISTRY`, `get_node`,
  `list_nodes`, and the 20 individual prototype constants
  (`CONSTANT`, `ADD`, …, `LOG_TO_STATUS_BAR`).

## Conventions

- **Headless.** No DearPyGui / wgpu / Rust dependencies. The editor
  sprint layers the panel on top of this surface; live-preview and
  drag-to-connect interactions consume the same `validate()` and
  `graph_to_python` entry points.
- **Lazy import.** The subpackage is registered in the top-level
  `_subpackages` set, so `slappyengine.visual_scripting` resolves on
  first access and is cached. There is no per-symbol `_LAZY_MAP` entry
  — every public name lives inside the subpackage.
- **Validation.** Inputs reuse the shared `slappyengine._validation`
  helpers (`validate_non_empty_str`, `validate_str`); domain checks
  (cycle detection, port-kind table) stay inside this subpackage.
- **Auto-id minting.** `Node.id` defaults to `n_<8-hex>` so callers can
  build a graph with positional kwargs and never hand-author an id.
  Round-trip through `to_yaml` / `from_yaml` preserves ids.

## See also

- [`material.md`](material.md) — the sibling node-graph subsystem used
  for shader authoring; this subpackage borrowed the `NodeDef` /
  `NodeMaterial` shape but generalised beyond rendering.
- [`ui_editor.md`](ui_editor.md) — the editor shell that will surface
  the panel in a follow-up sprint.
- [`compute.md`](compute.md) — compute-shader counterpart for the
  hot-path numeric kernels.
