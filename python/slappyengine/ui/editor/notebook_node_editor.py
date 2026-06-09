"""``NotebookNodeEditor`` — diary-themed visual node graph editor.

Designed to plug into ``NotebookDiaryPage``'s "Nodes" mode (P3) and
operate on the ``slappyengine.visual_scripting.NodeGraph`` data model
(P4).  Both P3 and P4 land in sibling sprints; this module is wired to
soft-import the data model and falls back to an internal stub when the
real module is not yet on disk so the editor remains importable in
every state of the sprint stack.

Visual contract
---------------

Each node renders as a *notebook-themed sticker card*:

* a **washi-tape header strip** carrying the node name in handwritten
  font (theme-tinted ``washi`` colour),
* a column of **input ports** on the left edge (small dots, colour
  coded by ``port_kind``),
* a column of **output ports** on the right edge (same shape, mirrored),
* a small **kind glyph** centred on the card (``+`` for math, ``*``
  for logic, ``>`` for flow/control, etc.).

Connections are doodled as **cubic-bezier curves** from an output port
to an input port, drawn in the active theme's ``semantic.accent``
colour.  The wire under the cursor renders at a fatter stroke so the
user always knows what they're about to delete.

The widget owns a ``dpg.drawlist`` that fills the available area.
Pan / zoom is implemented in software so the contract stays
draw-list-only (i.e. no nested DPG node-editor widget — we want full
control over the sticker geometry).

Headless safety
---------------

Every ``dpg.*`` call is wrapped in ``try / except`` so the editor still
registers its tags + call-log entries when ``dearpygui`` is missing or
stubbed.  All edit operations route through the data-model layer and
never depend on a built DPG tree, so tests can drive the entire surface
without a GUI context.

Per Nova3D's ``build(parent_tag)`` protocol.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from slappyengine._validation import validate_non_empty_str


# ---------------------------------------------------------------------------
# Soft-import of the visual_scripting data model.
#
# When the package is on disk we delegate to its ``NodeGraph`` / ``Node``
# / ``NodePort`` / ``Edge`` / ``PortKind`` / ``BUILTIN_NODES`` /
# ``graph_to_python`` so the editor never duplicates schema.  When the
# package isn't on disk yet we install a small in-module stub with the
# same shape; the public stub is exported from this module under the
# same names so callers can construct one regardless of the sibling
# sprint's state.
# ---------------------------------------------------------------------------


_HAS_VS = False
try:
    from slappyengine.visual_scripting import (  # type: ignore[import-not-found]
        BUILTIN_NODES as _VS_BUILTIN_NODES,
        Edge as _VS_Edge,
        Node as _VS_Node,
        NodeGraph as _VS_NodeGraph,
        NodePort as _VS_NodePort,
        PORT_KINDS as _VS_PORT_KINDS,
        PortKind as _VS_PortKind,
        graph_to_python as _vs_graph_to_python,
        ports_compatible as _vs_ports_compatible,
    )
    _HAS_VS = True
except Exception:
    _VS_BUILTIN_NODES = None
    _VS_Edge = None
    _VS_Node = None
    _VS_NodeGraph = None
    _VS_NodePort = None
    _VS_PORT_KINDS = None
    _VS_PortKind = None
    _vs_graph_to_python = None
    _vs_ports_compatible = None


# ---- Stub data model (used only when visual_scripting isn't on disk) ------


_STUB_PORT_KINDS = frozenset({
    "float", "int", "bool", "str", "vec2", "vec3", "vec4", "any",
})


@dataclass
class _StubNodePort:
    """Mimic ``slappyengine.visual_scripting.NodePort``."""

    name: str
    port_kind: str = "any"
    default: Any = None


@dataclass
class _StubNode:
    """Mimic ``slappyengine.visual_scripting.Node``."""

    node_type: str
    kind: str = "math"
    inputs: list[_StubNodePort] = field(default_factory=list)
    outputs: list[_StubNodePort] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    position: tuple[int, int] = (0, 0)
    name: str = ""
    id: str = ""
    to_python_template: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = "n_" + uuid.uuid4().hex[:8]
        if not self.name:
            self.name = self.node_type

    def clone(self, *, new_id: bool = True) -> "_StubNode":
        import copy as _copy
        return _StubNode(
            node_type=self.node_type,
            kind=self.kind,
            inputs=[_StubNodePort(p.name, p.port_kind, _copy.deepcopy(p.default))
                    for p in self.inputs],
            outputs=[_StubNodePort(p.name, p.port_kind, _copy.deepcopy(p.default))
                     for p in self.outputs],
            params=_copy.deepcopy(self.params),
            position=tuple(self.position),
            name=self.name,
            id="" if new_id else self.id,
            to_python_template=self.to_python_template,
        )


@dataclass
class _StubEdge:
    """Mimic ``slappyengine.visual_scripting.Edge``."""

    from_node_id: str
    from_port: str
    to_node_id: str
    to_port: str


@dataclass
class _StubNodeGraph:
    """Mimic ``slappyengine.visual_scripting.NodeGraph``."""

    nodes: list[_StubNode] = field(default_factory=list)
    edges: list[_StubEdge] = field(default_factory=list)
    name: str = "untitled"

    def add_node(self, node: _StubNode) -> _StubNode:
        self.nodes.append(node)
        return node

    def add_edge(
        self,
        from_node: Any,
        from_port: str,
        to_node: Any,
        to_port: str,
    ) -> _StubEdge:
        from_id = from_node.id if hasattr(from_node, "id") else from_node
        to_id = to_node.id if hasattr(to_node, "id") else to_node
        edge = _StubEdge(
            from_node_id=from_id,
            from_port=from_port,
            to_node_id=to_id,
            to_port=to_port,
        )
        self.edges.append(edge)
        return edge

    def get_node(self, node_id: str) -> _StubNode:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(node_id)

    def remove_node(self, node_id: str) -> None:
        self.nodes = [n for n in self.nodes if n.id != node_id]
        self.edges = [
            e for e in self.edges
            if e.from_node_id != node_id and e.to_node_id != node_id
        ]


def _stub_ports_compatible(from_kind: str, to_kind: str) -> bool:
    """Minimal fallback compatibility table for the stub branch."""
    if from_kind == "any" or to_kind == "any":
        return True
    if from_kind == to_kind:
        return True
    # int widens to float (matches the real visual_scripting rule).
    if from_kind == "int" and to_kind == "float":
        return True
    return False


# A tiny built-in palette so the stub branch still has something for the
# Add Node popup to display.  Reuses the real package's naming so a swap
# is purely additive.
_STUB_BUILTIN_NODES: tuple[_StubNode, ...] = (
    _StubNode(
        node_type="math.constant", kind="math",
        outputs=[_StubNodePort("value", "float", 0.0)],
        params={"value": 0.0},
        to_python_template="{value} = {__param_value__}",
    ),
    _StubNode(
        node_type="math.add", kind="math",
        inputs=[_StubNodePort("a", "float", 0.0),
                _StubNodePort("b", "float", 0.0)],
        outputs=[_StubNodePort("sum", "float")],
        to_python_template="{sum} = {a} + {b}",
    ),
    _StubNode(
        node_type="logic.and", kind="logic",
        inputs=[_StubNodePort("a", "bool", False),
                _StubNodePort("b", "bool", False)],
        outputs=[_StubNodePort("result", "bool")],
        to_python_template="{result} = bool({a}) and bool({b})",
    ),
    _StubNode(
        node_type="control.return", kind="control",
        inputs=[_StubNodePort("value", "any", None)],
        outputs=[],
        to_python_template="return {value}",
    ),
    _StubNode(
        node_type="io.print", kind="io",
        inputs=[_StubNodePort("message", "any", "")],
        outputs=[],
        to_python_template="print({message})",
    ),
)


def _stub_graph_to_python(graph: Any) -> str:
    """Stub ``visual_scripting.graph_to_python`` — placeholder source."""
    lines: list[str] = [
        "# Generated by NotebookNodeEditor (stub backend)",
        "",
        "def run():",
    ]
    nodes = list(getattr(graph, "nodes", []))
    for node in nodes:
        nid = getattr(node, "id", "?")
        ntype = getattr(node, "node_type", "?")
        lines.append(f"    # node {nid}: {ntype}")
    if not nodes:
        lines.append(f"    \"\"\"Empty graph with 0 nodes\"\"\"")
        lines.append("    pass")
    else:
        lines.append("    pass")
    lines.append("")
    return "\n".join(lines)


# ---- Public names — prefer real module when available --------------------


if _HAS_VS:
    NodeGraph = _VS_NodeGraph  # type: ignore[assignment]
    Node = _VS_Node  # type: ignore[assignment]
    NodePort = _VS_NodePort  # type: ignore[assignment]
    Edge = _VS_Edge  # type: ignore[assignment]
    PortKind = _VS_PortKind  # type: ignore[assignment]
    BUILTIN_NODES = _VS_BUILTIN_NODES
    _PORT_KIND_SET = _VS_PORT_KINDS
    _graph_to_python_fn = _vs_graph_to_python
    _ports_compatible_fn = _vs_ports_compatible
else:
    NodeGraph = _StubNodeGraph  # type: ignore[assignment]
    Node = _StubNode  # type: ignore[assignment]
    NodePort = _StubNodePort  # type: ignore[assignment]
    Edge = _StubEdge  # type: ignore[assignment]
    PortKind = str  # type: ignore[assignment]
    BUILTIN_NODES = _STUB_BUILTIN_NODES
    _PORT_KIND_SET = _STUB_PORT_KINDS
    _graph_to_python_fn = _stub_graph_to_python
    _ports_compatible_fn = _stub_ports_compatible


# ---------------------------------------------------------------------------
# Visual constants
# ---------------------------------------------------------------------------


# Per-port-kind RGBA dot colour.  These are theme-independent so they
# read unambiguously regardless of the active palette (the theme accent
# is reserved for wires).  The keys match the real ``PORT_KINDS`` set.
_PORT_KIND_COLOR: dict[str, tuple[int, int, int, int]] = {
    "float":  (120, 200, 255, 255),   # cool blue
    "int":    (140, 220, 200, 255),   # teal
    "bool":   (240, 220, 120, 255),   # warm yellow
    "str":    (200, 140, 220, 255),   # purple
    "vec2":   (250, 180, 120, 255),   # peach
    "vec3":   (250, 130, 130, 255),   # salmon
    "vec4":   (200, 100, 180, 255),   # magenta
    "any":    (180, 180, 180, 255),   # neutral grey
}

# Per-kind sticker glyph used in the centre of each node card.  The keys
# match the real ``NODE_KINDS`` set; "flow" maps to the control-flow
# bucket so the description in the spec reads naturally.
_KIND_GLYPH: dict[str, str] = {
    "math":    "+",
    "logic":   "*",
    "control": ">",
    "flow":    ">",
    "io":      "@",
    "compute": "#",
    "render":  "%",
    "audio":   "~",
    "event":   "!",
}


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` or ``None`` when the extra is missing."""
    try:
        import dearpygui.dearpygui as dpg

        return dpg
    except Exception:
        return None


def _dpg_item_exists(dpg: Any, tag: str) -> bool:
    """Wrap ``does_item_exist`` in a try/except — guards against the
    DPG access-violation when no context is active.
    """
    try:
        return bool(dpg.does_item_exist(tag))
    except Exception:
        return False


def _theme_accent() -> tuple[int, int, int, int]:
    """Return the active notebook theme's accent colour (with fallback)."""
    try:
        from slappyengine.ui.widgets.notebook_theme import resolve_theme

        theme = resolve_theme()
        return theme.color("accent", (220, 120, 160, 255))
    except Exception:
        return (220, 120, 160, 255)


# ---------------------------------------------------------------------------
# NotebookNodeEditor
# ---------------------------------------------------------------------------


class NotebookNodeEditor:
    """Visual node graph editor — drag/drop sticker nodes.

    Each node renders as a notebook-themed sticker card:

    * washi tape header with the node name,
    * input ports on the left (small dots, colour-coded by ``port_kind``),
    * output ports on the right,
    * a small icon/glyph indicating the node's kind (math = ``+``,
      logic = ``*``, control = ``>``, etc.).

    Connections are doodled curved lines from output port to input port,
    drawn in the active theme's ``semantic.accent`` colour.

    Per Nova3D's ``build(parent_tag)`` protocol.

    Parameters
    ----------
    graph:
        Existing :class:`NodeGraph` to edit.  If ``None`` an empty graph
        is constructed and stashed on the editor.
    on_change:
        Optional callback fired on every successful mutation
        (add / remove / connect / disconnect / move).  Receives the
        current graph object.
    """

    TITLE = "Nodes"
    NODE_W = 160
    NODE_H = 80
    PORT_RADIUS = 6
    HEADER_H = 16
    PORT_SPACING = 14

    def __init__(
        self,
        graph: Any = None,
        on_change: Callable[[Any], None] | None = None,
    ) -> None:
        self._graph: Any = graph if graph is not None else NodeGraph()
        self._on_change = on_change

        # Pan / zoom state for the canvas.
        self._pan: tuple[float, float] = (0.0, 0.0)
        self._zoom: float = 1.0

        # Wire-drag preview state.
        self._drag_from: tuple[str, str] | None = None  # (node_id, port_name)
        self._drag_pos: tuple[float, float] = (0.0, 0.0)

        # Currently hovered / selected edge.
        self._hovered_edge: Any = None
        self._selected_edge: Any = None

        # DPG tags — stable across rebuilds so refresh() can target them.
        oid = id(self)
        self._panel_tag = f"notebook_node_editor_{oid}"
        self._toolbar_tag = f"{self._panel_tag}_toolbar"
        self._canvas_tag = f"{self._panel_tag}_canvas"
        self._palette_popup_tag = f"{self._panel_tag}_palette"
        self._codegen_pane_tag = f"{self._panel_tag}_codegen"

        # Build lifecycle.
        self._built: bool = False
        self._parent_tag: str | int | None = None
        self._palette_spawn: tuple[int, int] = (40, 40)

        # Optional sibling code-pane reference; populated by the diary
        # page so the "Generate Python" button has somewhere to spit
        # the output.  When ``None`` the codegen result is cached on
        # ``self._last_codegen`` instead.
        self._code_panel: Any | None = None
        self._last_codegen: str = ""

        # Call log for headless test assertions.
        self.call_log: list[tuple[Any, ...]] = []

    # ------------------------------------------------------------------
    # Public API — graph + lifecycle
    # ------------------------------------------------------------------

    def get_graph(self) -> Any:
        """Return the currently edited :class:`NodeGraph` instance."""
        return self._graph

    def set_graph(self, graph: Any) -> None:
        """Replace the edited graph and refresh the canvas."""
        if graph is None:
            raise TypeError(
                "NotebookNodeEditor.set_graph: graph must not be None",
            )
        self._graph = graph
        self.call_log.append(("set_graph", id(graph)))
        self.refresh()

    def bind_code_panel(self, panel: Any) -> None:
        """Bind a code-pane sibling.

        The Diary page passes the parallel ``NotebookCodePanel`` so the
        toolbar's "Generate Python" button can populate it.  Safe to call
        before or after :meth:`build`.
        """
        self._code_panel = panel
        self.call_log.append(("bind_code_panel", id(panel) if panel else None))

    @property
    def builtin_nodes(self) -> list[Any]:
        """Return the builtin-node palette list (prototypes)."""
        return list(BUILTIN_NODES) if BUILTIN_NODES else []

    # ------------------------------------------------------------------
    # Edit operations — every mutation routes through these so on_change
    # fires consistently regardless of the input path (drag, palette,
    # programmatic test).
    # ------------------------------------------------------------------

    def add_node(self, node_type: str, position: tuple[int, int]) -> str:
        """Add a new node of *node_type* at *position*.

        Returns the new node's id.  When *node_type* doesn't match any
        builtin prototype a minimal placeholder node is created so the
        editor remains tolerant of WIP catalogues.
        """
        node_type = validate_non_empty_str(
            "node_type", "NotebookNodeEditor.add_node", node_type,
        )
        if (
            not isinstance(position, tuple) or len(position) != 2
            or not all(isinstance(c, (int, float)) for c in position)
        ):
            raise TypeError(
                "NotebookNodeEditor.add_node: position must be (int, int); "
                f"got {position!r}",
            )

        node = self._spawn_node(
            node_type=node_type,
            position=(int(position[0]), int(position[1])),
        )
        try:
            self._graph.add_node(node)
        except Exception:
            # Stub graphs / minor schema mismatch — append directly.
            try:
                self._graph.nodes.append(node)
            except Exception:
                pass
        self.call_log.append(("add_node", node.id, node_type))
        self._fire_change()
        self.refresh()
        return node.id

    def remove_node(self, node_id: str) -> None:
        """Delete *node_id* and every edge that touches it."""
        node_id = validate_non_empty_str(
            "node_id", "NotebookNodeEditor.remove_node", node_id,
        )
        target = self._find_node(node_id)
        if target is None:
            return
        # Prefer the graph's own remove_node if it has one (handles edge
        # sweep + nodes in one shot).
        if hasattr(self._graph, "remove_node"):
            try:
                self._graph.remove_node(node_id)
            except Exception:
                self._manual_remove(node_id)
        else:
            self._manual_remove(node_id)
        self.call_log.append(("remove_node", node_id))
        self._fire_change()
        self.refresh()

    def _manual_remove(self, node_id: str) -> None:
        """Manual edge + node sweep for graphs without ``remove_node``."""
        self._graph.nodes = [n for n in self._graph.nodes if n.id != node_id]
        self._graph.edges = [
            e for e in self._graph.edges
            if self._edge_from_id(e) != node_id
            and self._edge_to_id(e) != node_id
        ]

    def connect(
        self,
        from_node: str,
        from_port: str,
        to_node: str,
        to_port: str,
    ) -> bool:
        """Create an edge from ``from_node.from_port`` to ``to_node.to_port``.

        Returns ``True`` on success, ``False`` when the port kinds don't
        match, when either endpoint is missing, when the edge would be
        a duplicate, or when the user tried to wire a node to itself.
        """
        from_node = validate_non_empty_str(
            "from_node", "NotebookNodeEditor.connect", from_node,
        )
        from_port = validate_non_empty_str(
            "from_port", "NotebookNodeEditor.connect", from_port,
        )
        to_node = validate_non_empty_str(
            "to_node", "NotebookNodeEditor.connect", to_node,
        )
        to_port = validate_non_empty_str(
            "to_port", "NotebookNodeEditor.connect", to_port,
        )

        if from_node == to_node:
            return False

        src = self._find_node(from_node)
        dst = self._find_node(to_node)
        if src is None or dst is None:
            return False

        src_port = self._find_port(src, from_port, "outputs")
        dst_port = self._find_port(dst, to_port, "inputs")
        if src_port is None or dst_port is None:
            return False

        # Type check — delegate to the data model's compatibility rule.
        src_kind = self._port_kind(src_port)
        dst_kind = self._port_kind(dst_port)
        try:
            compatible = bool(_ports_compatible_fn(src_kind, dst_kind))
        except Exception:
            # On any schema validation error, fall back to permissive
            # equal-or-any compatibility so the editor never wedges.
            compatible = _stub_ports_compatible(src_kind, dst_kind)
        if not compatible:
            self.call_log.append(
                ("connect_rejected_type", from_node, from_port, to_node, to_port),
            )
            return False

        # Duplicate guard.
        for e in self._graph.edges:
            if (
                self._edge_from_id(e) == from_node
                and self._edge_from_port(e) == from_port
                and self._edge_to_id(e) == to_node
                and self._edge_to_port(e) == to_port
            ):
                return False

        try:
            edge = self._graph.add_edge(src, from_port, dst, to_port)
        except Exception:
            # Stub graph without add_edge — synthesise the Edge directly.
            try:
                edge = Edge(
                    from_node_id=from_node,
                    from_port=from_port,
                    to_node_id=to_node,
                    to_port=to_port,
                )
            except Exception:
                edge = _StubEdge(
                    from_node_id=from_node,
                    from_port=from_port,
                    to_node_id=to_node,
                    to_port=to_port,
                )
            self._graph.edges.append(edge)

        self.call_log.append(("connect", from_node, from_port, to_node, to_port))
        self._fire_change()
        self.refresh()
        return True

    def disconnect(self, edge: Any) -> None:
        """Remove *edge* from the graph (no-op when absent)."""
        if edge is None:
            return
        fid = self._edge_from_id(edge)
        fp = self._edge_from_port(edge)
        tid = self._edge_to_id(edge)
        tp = self._edge_to_port(edge)
        before = len(self._graph.edges)
        self._graph.edges = [
            e for e in self._graph.edges
            if not (
                self._edge_from_id(e) == fid
                and self._edge_from_port(e) == fp
                and self._edge_to_id(e) == tid
                and self._edge_to_port(e) == tp
            )
        ]
        if len(self._graph.edges) != before:
            self.call_log.append(("disconnect",))
            self._fire_change()
            self.refresh()

    def move_node(self, node_id: str, new_pos: tuple[int, int]) -> None:
        """Move *node_id* to *new_pos*."""
        node_id = validate_non_empty_str(
            "node_id", "NotebookNodeEditor.move_node", node_id,
        )
        if (
            not isinstance(new_pos, tuple) or len(new_pos) != 2
            or not all(isinstance(c, (int, float)) for c in new_pos)
        ):
            raise TypeError(
                "NotebookNodeEditor.move_node: new_pos must be (int, int); "
                f"got {new_pos!r}",
            )

        node = self._find_node(node_id)
        if node is None:
            return
        node.position = (int(new_pos[0]), int(new_pos[1]))
        self.call_log.append(("move_node", node_id, node.position))
        self._fire_change()
        self.refresh()

    # ------------------------------------------------------------------
    # Palette modal
    # ------------------------------------------------------------------

    def open_palette(self, position: tuple[int, int]) -> None:
        """Open the "Add Node" palette modal at *position*.

        Headless-safe — when no DPG context is active the call only
        records the request in ``call_log`` and stashes the spawn
        coordinates so a subsequent palette selection knows where to
        drop the new node.
        """
        self._palette_spawn = (int(position[0]), int(position[1]))
        self.call_log.append(("open_palette", self._palette_spawn))

        dpg = _safe_dpg()
        if dpg is None or not self._built:
            return
        if not _dpg_item_exists(dpg, self._palette_popup_tag):
            return
        try:
            dpg.configure_item(
                self._palette_popup_tag,
                show=True,
                pos=list(self._palette_spawn),
            )
        except Exception:
            pass

    def palette_entries(self) -> dict[str, list[str]]:
        """Return builtin nodes grouped by ``kind`` for the palette UI."""
        groups: dict[str, list[str]] = {}
        for proto in self.builtin_nodes:
            kind = str(getattr(proto, "kind", "other"))
            ntype = str(getattr(proto, "node_type", ""))
            if not ntype:
                continue
            groups.setdefault(kind, []).append(ntype)
        return groups

    # ------------------------------------------------------------------
    # Codegen
    # ------------------------------------------------------------------

    def generate_python(self) -> str:
        """Run the codegen backend and return the generated source.

        Routes through ``slappyengine.visual_scripting.graph_to_python``
        when available; otherwise falls back to the in-module stub so
        the diary page always has something to display.
        """
        try:
            code = _graph_to_python_fn(self._graph)
        except Exception:
            code = _stub_graph_to_python(self._graph)
        if not isinstance(code, str) or not code:
            code = _stub_graph_to_python(self._graph)
        self._last_codegen = code
        self.call_log.append(("generate_python", len(code)))
        # If the host wired a code panel, dump straight into its buffer.
        if self._code_panel is not None:
            try:
                self._code_panel._code_text = code  # type: ignore[attr-defined]
                if hasattr(self._code_panel, "_sync_inputs_to_dpg"):
                    self._code_panel._sync_inputs_to_dpg()
            except Exception:
                pass
        return code

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, parent_tag: int | str) -> None:
        """Materialise the editor under *parent_tag* (DPG protocol)."""
        self._parent_tag = parent_tag
        self._built = True
        self.call_log.append(("build", parent_tag))

        dpg = _safe_dpg()
        if dpg is None:
            return

        try:
            with dpg.group(parent=parent_tag, tag=self._panel_tag):
                self._build_toolbar(dpg)
                self._build_canvas(dpg)
                self._build_palette_popup(dpg)
        except Exception:
            # Stub DPG / no context-manager support — flat fallback path.
            try:
                dpg.add_text(self.TITLE, parent=parent_tag, tag=self._panel_tag)
            except Exception:
                pass
            self._build_toolbar(dpg)
            self._build_canvas(dpg)
            self._build_palette_popup(dpg)

        self.refresh()

    def _build_toolbar(self, dpg: Any) -> None:
        """Top-row toolbar: Add Node / Generate Python / Clear."""
        try:
            with dpg.group(
                horizontal=True, parent=self._panel_tag, tag=self._toolbar_tag,
            ):
                self._render_toolbar_buttons(dpg)
        except Exception:
            try:
                dpg.add_text(
                    "Toolbar", parent=self._panel_tag, tag=self._toolbar_tag,
                )
            except Exception:
                pass
            self._render_toolbar_buttons(dpg)

    def _render_toolbar_buttons(self, dpg: Any) -> None:
        try:
            dpg.add_button(
                label="+ Add Node",
                parent=self._toolbar_tag,
                tag=f"{self._toolbar_tag}_add",
                callback=lambda *_: self.open_palette((40, 40)),
            )
        except Exception:
            pass
        try:
            dpg.add_button(
                label="Generate Python",
                parent=self._toolbar_tag,
                tag=f"{self._toolbar_tag}_codegen",
                callback=lambda *_: self.generate_python(),
            )
        except Exception:
            pass
        try:
            dpg.add_button(
                label="Clear",
                parent=self._toolbar_tag,
                tag=f"{self._toolbar_tag}_clear",
                callback=lambda *_: self._clear_graph(),
            )
        except Exception:
            pass

    def _build_canvas(self, dpg: Any) -> None:
        """The drawlist canvas that hosts every sticker + wire."""
        try:
            dpg.add_drawlist(
                width=1024,
                height=640,
                parent=self._panel_tag,
                tag=self._canvas_tag,
            )
        except Exception:
            try:
                dpg.add_text(
                    "Canvas", parent=self._panel_tag, tag=self._canvas_tag,
                )
            except Exception:
                pass

    def _build_palette_popup(self, dpg: Any) -> None:
        """Hidden palette modal (Add Node) — entries grouped by ``kind``."""
        try:
            with dpg.window(
                tag=self._palette_popup_tag,
                popup=True,
                no_title_bar=True,
                autosize=True,
                no_saved_settings=True,
                show=False,
            ):
                self._render_palette_entries(dpg)
        except Exception:
            try:
                dpg.add_text("Palette", tag=self._palette_popup_tag)
            except Exception:
                pass
            self._render_palette_entries(dpg)

    def _render_palette_entries(self, dpg: Any) -> None:
        """Populate the palette popup with one menu item per builtin node."""
        groups = self.palette_entries()
        for kind, types in groups.items():
            try:
                dpg.add_text(
                    kind.capitalize(),
                    parent=self._palette_popup_tag,
                    color=(160, 160, 255, 255),
                )
            except Exception:
                pass
            for ntype in types:
                try:
                    dpg.add_menu_item(
                        label=ntype,
                        parent=self._palette_popup_tag,
                        callback=self._make_palette_pick_callback(ntype),
                    )
                except Exception:
                    pass
            try:
                dpg.add_separator(parent=self._palette_popup_tag)
            except Exception:
                pass

    def _make_palette_pick_callback(
        self, node_type: str,
    ) -> Callable[..., None]:
        """Return a DPG callback that places *node_type* at the palette spawn."""
        def _cb(*_a: Any, **_kw: Any) -> None:
            spawn = self._palette_spawn
            self.add_node(node_type, spawn)
            dpg = _safe_dpg()
            if dpg is None:
                return
            if not _dpg_item_exists(dpg, self._palette_popup_tag):
                return
            try:
                dpg.configure_item(self._palette_popup_tag, show=False)
            except Exception:
                pass

        return _cb

    # ------------------------------------------------------------------
    # Refresh — wipe the drawlist and repaint every node + wire.
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Repaint the canvas from the current graph state."""
        self.call_log.append(("refresh",))
        dpg = _safe_dpg()
        if dpg is None or not self._built:
            return
        if not _dpg_item_exists(dpg, self._canvas_tag):
            return
        # Wipe the existing drawlist children.
        try:
            dpg.delete_item(self._canvas_tag, children_only=True)
        except Exception:
            pass
        # Repaint nodes then wires (wires render on top).
        for node in self._graph.nodes:
            self._draw_node(dpg, node)
        for edge in self._graph.edges:
            self._draw_wire(dpg, edge)

    # ------------------------------------------------------------------
    # Draw helpers
    # ------------------------------------------------------------------

    def _draw_node(self, dpg: Any, node: Any) -> None:
        """Paint a single sticker card for *node*."""
        nx, ny = getattr(node, "position", (0, 0))
        x = int(nx * self._zoom + self._pan[0])
        y = int(ny * self._zoom + self._pan[1])
        w = int(self.NODE_W * self._zoom)
        h = int(self.NODE_H * self._zoom)

        # Card body — soft paper rectangle.
        try:
            dpg.draw_rectangle(
                pmin=(x, y),
                pmax=(x + w, y + h),
                color=(60, 60, 80, 255),
                fill=(245, 240, 220, 255),
                rounding=6,
                parent=self._canvas_tag,
            )
        except Exception:
            pass

        # Washi-tape header strip.
        try:
            dpg.draw_rectangle(
                pmin=(x, y),
                pmax=(x + w, y + int(self.HEADER_H * self._zoom)),
                color=(0, 0, 0, 0),
                fill=(180, 200, 230, 230),
                parent=self._canvas_tag,
            )
        except Exception:
            pass

        # Node-type label.
        try:
            dpg.draw_text(
                pos=(x + 6, y + 2),
                text=str(getattr(node, "name", getattr(node, "node_type", "?"))),
                color=(40, 40, 60, 255),
                size=12,
                parent=self._canvas_tag,
            )
        except Exception:
            pass

        # Centre kind glyph.
        try:
            kind = str(getattr(node, "kind", "other"))
            glyph = _KIND_GLYPH.get(kind, "?")
            dpg.draw_text(
                pos=(x + w // 2 - 4, y + h // 2 - 6),
                text=glyph,
                color=(80, 80, 100, 255),
                size=18,
                parent=self._canvas_tag,
            )
        except Exception:
            pass

        # Input port dots (left edge).
        inputs = list(getattr(node, "inputs", []) or [])
        for i, port in enumerate(inputs):
            py = y + int(self.HEADER_H * self._zoom) + 8 + i * self.PORT_SPACING
            color = _PORT_KIND_COLOR.get(
                self._port_kind(port), _PORT_KIND_COLOR["any"],
            )
            try:
                dpg.draw_circle(
                    center=(x, py),
                    radius=self.PORT_RADIUS,
                    color=(40, 40, 60, 255),
                    fill=color,
                    parent=self._canvas_tag,
                )
                dpg.draw_text(
                    pos=(x + 9, py - 6),
                    text=str(getattr(port, "name", "?")),
                    color=(60, 60, 80, 255),
                    size=10,
                    parent=self._canvas_tag,
                )
            except Exception:
                pass

        # Output port dots (right edge).
        outputs = list(getattr(node, "outputs", []) or [])
        for i, port in enumerate(outputs):
            py = y + int(self.HEADER_H * self._zoom) + 8 + i * self.PORT_SPACING
            color = _PORT_KIND_COLOR.get(
                self._port_kind(port), _PORT_KIND_COLOR["any"],
            )
            try:
                dpg.draw_circle(
                    center=(x + w, py),
                    radius=self.PORT_RADIUS,
                    color=(40, 40, 60, 255),
                    fill=color,
                    parent=self._canvas_tag,
                )
                dpg.draw_text(
                    pos=(x + w - 28, py - 6),
                    text=str(getattr(port, "name", "?")),
                    color=(60, 60, 80, 255),
                    size=10,
                    parent=self._canvas_tag,
                )
            except Exception:
                pass

    def _draw_wire(self, dpg: Any, edge: Any) -> None:
        """Paint a cubic-bezier wire for *edge*."""
        src = self._find_node(self._edge_from_id(edge))
        dst = self._find_node(self._edge_to_id(edge))
        if src is None or dst is None:
            return

        sx, sy = self._port_world_pos(src, self._edge_from_port(edge), "outputs")
        ex, ey = self._port_world_pos(dst, self._edge_to_port(edge), "inputs")

        # Cubic bezier control points — horizontal handles for a soft S-curve.
        cx = (ex - sx) * 0.5
        p1 = (sx, sy)
        p2 = (sx + cx, sy)
        p3 = (ex - cx, ey)
        p4 = (ex, ey)

        color = _theme_accent()
        thickness = 4 if edge is self._hovered_edge else 2

        try:
            dpg.draw_bezier_cubic(
                p1=p1, p2=p2, p3=p3, p4=p4,
                color=color, thickness=thickness,
                parent=self._canvas_tag,
            )
        except Exception:
            # No bezier helper — fall back to a polyline approximation so the
            # contract still surfaces.
            try:
                pts = self._sample_bezier(p1, p2, p3, p4, 12)
                dpg.draw_polyline(
                    points=pts, color=color, thickness=thickness,
                    parent=self._canvas_tag,
                )
            except Exception:
                pass

    @staticmethod
    def _sample_bezier(
        p1: tuple[float, float],
        p2: tuple[float, float],
        p3: tuple[float, float],
        p4: tuple[float, float],
        steps: int,
    ) -> list[tuple[float, float]]:
        """Return *steps* points along the cubic bezier (inclusive endpoints)."""
        pts: list[tuple[float, float]] = []
        for i in range(steps + 1):
            t = i / steps
            u = 1.0 - t
            x = (
                u * u * u * p1[0]
                + 3 * u * u * t * p2[0]
                + 3 * u * t * t * p3[0]
                + t * t * t * p4[0]
            )
            y = (
                u * u * u * p1[1]
                + 3 * u * u * t * p2[1]
                + 3 * u * t * t * p3[1]
                + t * t * t * p4[1]
            )
            pts.append((x, y))
        return pts

    def _port_world_pos(
        self, node: Any, port_name: str, side: str,
    ) -> tuple[float, float]:
        """Return the canvas-space (x, y) of *port_name* on *node*."""
        nx, ny = getattr(node, "position", (0, 0))
        x = nx * self._zoom + self._pan[0]
        y = ny * self._zoom + self._pan[1]
        w = self.NODE_W * self._zoom
        header = self.HEADER_H * self._zoom

        ports = list(
            getattr(node, "outputs" if side == "outputs" else "inputs", [])
            or []
        )
        for i, port in enumerate(ports):
            if getattr(port, "name", None) == port_name:
                py = y + header + 8 + i * self.PORT_SPACING
                return (x + w, py) if side == "outputs" else (x, py)
        # Fallback to corner of the card.
        return (x + w, y) if side == "outputs" else (x, y)

    # ------------------------------------------------------------------
    # Edge accessors — work across the real Edge schema
    # (from_node_id) and the legacy/stub (from_node) shape.
    # ------------------------------------------------------------------

    @staticmethod
    def _edge_from_id(edge: Any) -> str:
        return str(
            getattr(edge, "from_node_id",
                    getattr(edge, "from_node", "")) or ""
        )

    @staticmethod
    def _edge_to_id(edge: Any) -> str:
        return str(
            getattr(edge, "to_node_id",
                    getattr(edge, "to_node", "")) or ""
        )

    @staticmethod
    def _edge_from_port(edge: Any) -> str:
        return str(getattr(edge, "from_port", "") or "")

    @staticmethod
    def _edge_to_port(edge: Any) -> str:
        return str(getattr(edge, "to_port", "") or "")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_node(self, node_id: str) -> Any | None:
        if hasattr(self._graph, "get_node"):
            try:
                return self._graph.get_node(node_id)
            except Exception:
                pass
        for n in getattr(self._graph, "nodes", []):
            if getattr(n, "id", None) == node_id:
                return n
        return None

    @staticmethod
    def _find_port(node: Any, port_name: str, side: str) -> Any | None:
        ports = list(
            getattr(node, "outputs" if side == "outputs" else "inputs", [])
            or []
        )
        for p in ports:
            if getattr(p, "name", None) == port_name:
                return p
        return None

    @staticmethod
    def _port_kind(port: Any) -> str:
        """Return the port-kind token regardless of attribute name."""
        return str(
            getattr(port, "port_kind",
                    getattr(port, "kind", "any")) or "any"
        )

    def _lookup_template(self, node_type: str) -> Any | None:
        for proto in self.builtin_nodes:
            if str(getattr(proto, "node_type", "")) == node_type:
                return proto
        return None

    def _spawn_node(
        self,
        node_type: str,
        position: tuple[int, int],
    ) -> Any:
        """Mint a new graph node from the builtin palette (or placeholder)."""
        proto = self._lookup_template(node_type)
        if proto is not None and hasattr(proto, "clone"):
            try:
                node = proto.clone(new_id=True)
                node.position = position
                return node
            except Exception:
                pass

        # No prototype — synthesise a placeholder.  Try the real Node first
        # (its constructor enforces ``kind in NODE_KINDS``); fall back to
        # the stub on any mismatch.
        if _HAS_VS and Node is not _StubNode:
            try:
                return Node(  # type: ignore[call-arg]
                    node_type=node_type,
                    kind="math",
                    inputs=[],
                    outputs=[],
                    position=position,
                )
            except Exception:
                pass
        return _StubNode(
            node_type=node_type,
            kind="math",
            inputs=[],
            outputs=[],
            position=position,
        )

    def _clear_graph(self) -> None:
        """Wipe every node + edge.  Used by the toolbar Clear button."""
        self._graph.nodes = []
        self._graph.edges = []
        self.call_log.append(("clear_graph",))
        self._fire_change()
        self.refresh()

    def _fire_change(self) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change(self._graph)
        except Exception:
            # Don't let a misbehaving listener break the editor.
            pass


__all__ = [
    "NotebookNodeEditor",
    "NodeGraph",
    "Node",
    "NodePort",
    "Edge",
    "PortKind",
    "BUILTIN_NODES",
]
