"""Visual node-graph canvas for DDD5's :class:`MaterialGraph` — EEE4 landing.

Nova3D shipped a fully-fledged ``MaterialGraphEditor`` (see
``engine/graphics/MaterialGraphEditor.hpp:1-359``): a drag-drop canvas
with palette on the left, node canvas in the centre, and a per-node
inspector on the right. The DDD5 sprint landed the data model
(:mod:`slappyengine.render.material_graph`); this module lands the *UI*
on top of that model so a developer sitting in the editor can wire up a
PBR material graphically instead of authoring Python by hand.

Design
------

* **Palette (left, 10 buttons).** One button per DDD5 node type. Click
  a button to arm the placement cursor; then click on the canvas to
  drop a node.
* **Canvas (centre).** DPG's native ``node_editor`` is used when
  available so users get bezier wires, minimap, and drag-select for
  free. Under the DPG stub / older DPG builds we fall back to a plain
  child window; the underlying :class:`MaterialGraph` is still edited.
* **Inspector (right).** Populates from the currently-selected node's
  ``params`` dict — float sliders / colour picker / text field per
  entry.
* **Toolbar (top).** Compile → runs ``MaterialGraph.compile()`` and
  shows the WGSL text in a modal. Save / Load → YAML round-trip over
  the underlying graph plus the canvas overlay (positions +
  ``palette_placement`` metadata). Clear → wipes the graph.

Slot-compatibility rules
------------------------

An output can wire to an input iff both slots' dtypes match, with two
exemptions:

* ``float`` may drive any of the ``vec*`` inputs (broadcast).
* ``vec4`` may drive a ``vec3`` input (drop-alpha).

Everything else (e.g. ``vec2 → sampler2D``) is refused; the canvas emits
an ``info`` message on the toolbar and does **not** touch the underlying
graph. See :meth:`MaterialGraphCanvas.is_compatible` for the full table.

Headless-safe
-------------
Every ``dearpygui`` call is guarded through :func:`_safe_dpg` so tests
build the canvas under the standard shell stub. All state (nodes,
edges, positions, selection) lives on the panel instance so tests can
inspect it directly without walking DPG.

Public surface
--------------

* :class:`MaterialGraphCanvas` — the panel itself.
* :func:`make_material_graph_canvas` — factory used by
  :class:`slappyengine.ui.editor.shell.EditorShell`.
* Module constants: :data:`NODE_PALETTE`, :data:`COMPATIBILITY_TABLE`.
"""
from __future__ import annotations

from typing import Any, Callable

import yaml

from slappyengine.render.material_graph import (
    AddNode,
    ConstColorNode,
    ConstFloatNode,
    FresnelNode,
    MaterialGraph,
    MaterialNode,
    MixNode,
    MultiplyNode,
    NormalMapNode,
    PBROutputNode,
    Texture2DNode,
    UVNode,
    _NODE_TYPES,  # type: ignore[attr-defined]  # registry re-use for YAML
)


TITLE = "Material Graph"


# ---------------------------------------------------------------------------
# Palette — mirrors DDD5's 10 concrete node types. Order is the palette
# button order in the UI; every entry names the DDD5 class + a UI label.
# ---------------------------------------------------------------------------


NODE_PALETTE: list[tuple[str, str, type[MaterialNode]]] = [
    # (palette_key,      button_label,       node_class)
    ("ConstFloat",       "Const Float",      ConstFloatNode),
    ("ConstColor",       "Const Colour",     ConstColorNode),
    ("Texture2D",        "Texture 2D",       Texture2DNode),
    ("UV",               "UV",               UVNode),
    ("Multiply",         "Multiply",         MultiplyNode),
    ("Add",              "Add",              AddNode),
    ("Mix",              "Mix",              MixNode),
    ("NormalMap",        "Normal Map",       NormalMapNode),
    ("Fresnel",          "Fresnel",          FresnelNode),
    ("PBROutput",        "PBR Output",       PBROutputNode),
]

#: Sanity check — the palette really does expose 10 entries.
assert len(NODE_PALETTE) == 10


# ---------------------------------------------------------------------------
# Slot-compatibility table
# ---------------------------------------------------------------------------


#: Exact-match dtypes always compatible with themselves. Broadcast
#: exemptions are handled by :func:`is_compatible` on top of this table.
COMPATIBILITY_TABLE: dict[tuple[str, str], bool] = {
    # Same-dtype cells — trivially wire-able.
    ("float",     "float"):     True,
    ("vec2",      "vec2"):      True,
    ("vec3",      "vec3"):      True,
    ("vec4",      "vec4"):      True,
    ("sampler2D", "sampler2D"): True,

    # Broadcasts allowed on the graph.
    ("float", "vec2"): True,
    ("float", "vec3"): True,
    ("float", "vec4"): True,

    # vec4 -> vec3 is treated as an implicit ``.xyz`` swizzle.
    ("vec4", "vec3"): True,
}


def is_compatible(src_dtype: str, dst_dtype: str) -> bool:
    """Return ``True`` when ``src_dtype`` can legally drive ``dst_dtype``.

    Consulted by :meth:`MaterialGraphCanvas.wire` before touching the
    underlying :class:`MaterialGraph`. Unknown dtypes fall through as
    incompatible so authors don't accidentally introduce a new dtype
    without updating this table.
    """
    if src_dtype == dst_dtype:
        return True
    return COMPATIBILITY_TABLE.get((src_dtype, dst_dtype), False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` or ``None`` when the extra is missing."""
    try:
        import dearpygui.dearpygui as dpg
        return dpg
    except Exception:
        return None


def _fresh_name(existing: dict[str, Any], base: str) -> str:
    """Return a unique node name based on *base* not already in *existing*.

    Falls back to ``base_1`` / ``base_2`` / ... — matches the CBB pattern
    used elsewhere in the editor.
    """
    if base not in existing:
        return base
    idx = 1
    while f"{base}_{idx}" in existing:
        idx += 1
    return f"{base}_{idx}"


# ---------------------------------------------------------------------------
# Canvas
# ---------------------------------------------------------------------------


class MaterialGraphCanvas:
    """DearPyGui panel that edits a :class:`MaterialGraph` visually.

    The panel keeps its own :class:`MaterialGraph` instance on
    :attr:`graph`. Every UI action ultimately mutates that graph so
    :meth:`compile` produces valid WGSL and :meth:`save_yaml` round-trips.

    Attributes
    ----------
    graph : MaterialGraph
        The graph being edited. Fresh on construction; mutated by every
        placement / wire / delete.
    positions : dict[str, tuple[float, float]]
        Canvas coordinates for each node's UI box. Persisted through
        YAML alongside the graph.
    selected : str | None
        Name of the currently-selected node (or ``None``).
    armed_palette : str | None
        The palette key the user has armed for the next canvas click,
        or ``None`` when placement is idle.
    last_compiled_wgsl : str | None
        The most recent output of the ``Compile`` button. Retained so
        tests + the REPL can inspect it without re-running.
    last_status : str
        Short human-readable message describing the most recent action
        (e.g. rejected wire reason). Painted onto the toolbar strip.
    """

    TITLE = TITLE

    def __init__(self, graph: MaterialGraph | None = None) -> None:
        self.graph: MaterialGraph = graph if graph is not None else MaterialGraph()
        self.positions: dict[str, tuple[float, float]] = {}
        self.selected: str | None = None
        self.armed_palette: str | None = None
        self.last_compiled_wgsl: str | None = None
        self.last_status: str = ""

        # DPG tag bookkeeping — unique per instance so multiple canvases
        # can co-exist under the same shell.
        _uid = id(self)
        self._panel_tag = f"matgraph_panel_{_uid}"
        self._palette_tag = f"matgraph_palette_{_uid}"
        self._canvas_tag = f"matgraph_canvas_{_uid}"
        self._inspector_tag = f"matgraph_inspector_{_uid}"
        self._toolbar_tag = f"matgraph_toolbar_{_uid}"
        self._status_tag = f"matgraph_status_{_uid}"
        self._wgsl_modal_tag = f"matgraph_wgsl_modal_{_uid}"
        self._wgsl_text_tag = f"matgraph_wgsl_text_{_uid}"

        # Per-node DPG tags — filled on placement.
        self._node_tags: dict[str, str] = {}
        # DPG node-attribute meta so link callbacks can decode a wire.
        self._attr_meta: dict[str, tuple[str, str, str]] = {}
        # DPG link tags → underlying edge tuple.
        self._link_tags: dict[str, tuple[str, str, str, str]] = {}

        self._built: bool = False

    # ------------------------------------------------------------------
    # Palette / placement
    # ------------------------------------------------------------------

    def arm_palette(self, palette_key: str) -> None:
        """Arm placement for *palette_key* (raises :class:`KeyError` on typo)."""
        keys = {k for k, _lbl, _cls in NODE_PALETTE}
        if palette_key not in keys:
            raise KeyError(
                f"unknown material palette entry: {palette_key!r}"
            )
        self.armed_palette = palette_key
        self.last_status = f"armed: {palette_key} — click canvas to place"

    def place_node(
        self,
        palette_key: str,
        x: float = 0.0,
        y: float = 0.0,
        *,
        name: str | None = None,
    ) -> MaterialNode:
        """Place a new node from *palette_key* onto the canvas at *(x, y)*.

        Returns the freshly-added :class:`MaterialNode`. When the name
        collides with an existing node, a numeric suffix is appended.
        The armed-palette state is cleared on success.
        """
        for key, _label, cls in NODE_PALETTE:
            if key != palette_key:
                continue
            base = name or key.lower()
            node_name = _fresh_name(self.graph.nodes, base)
            # PBROutputNode's __init__ default name is "output" but the
            # base class still takes a positional name kwarg.
            node = cls(node_name)  # type: ignore[call-arg]
            self.graph.add_node(node)
            self.positions[node_name] = (float(x), float(y))
            self._paint_node(node, x, y)
            self.armed_palette = None
            self.last_status = f"placed {palette_key} as {node_name}"
            return node
        raise KeyError(f"unknown material palette entry: {palette_key!r}")

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def wire(
        self,
        from_node: str,
        from_slot: str,
        to_node: str,
        to_slot: str,
    ) -> bool:
        """Create an edge from ``from_node.from_slot`` → ``to_node.to_slot``.

        Returns ``True`` when the edge was accepted, ``False`` when the
        dtype-compatibility check rejects it. Missing nodes / slots
        raise :class:`KeyError` — same contract as
        :meth:`MaterialGraph.connect`.
        """
        if from_node not in self.graph.nodes:
            raise KeyError(f"unknown from_node {from_node!r}")
        if to_node not in self.graph.nodes:
            raise KeyError(f"unknown to_node {to_node!r}")
        src = self.graph.nodes[from_node]
        dst = self.graph.nodes[to_node]
        if from_slot not in src.outputs:
            raise KeyError(
                f"{from_node!r} has no output slot {from_slot!r}"
            )
        if to_slot not in dst.inputs:
            raise KeyError(
                f"{to_node!r} has no input slot {to_slot!r}"
            )
        src_dtype = src.outputs[from_slot].dtype
        dst_dtype = dst.inputs[to_slot].dtype
        if not is_compatible(src_dtype, dst_dtype):
            self.last_status = (
                f"rejected wire {from_node}.{from_slot} ({src_dtype}) → "
                f"{to_node}.{to_slot} ({dst_dtype}): incompatible dtypes"
            )
            return False
        # Refuse duplicates so the canvas doesn't stack visually.
        for edge in self.graph.edges:
            if (
                edge.from_node == from_node
                and edge.from_slot == from_slot
                and edge.to_node == to_node
                and edge.to_slot == to_slot
            ):
                self.last_status = "duplicate wire — ignored"
                return False
        self.graph.connect(from_node, from_slot, to_node, to_slot)
        self._paint_link(from_node, from_slot, to_node, to_slot)
        self.last_status = (
            f"wired {from_node}.{from_slot} → {to_node}.{to_slot}"
        )
        return True

    # ------------------------------------------------------------------
    # Selection / deletion
    # ------------------------------------------------------------------

    def select_node(self, node_name: str | None) -> None:
        """Select *node_name* (or ``None`` to clear); repaints the inspector."""
        if node_name is not None and node_name not in self.graph.nodes:
            raise KeyError(f"unknown node {node_name!r}")
        self.selected = node_name
        self._paint_inspector()

    def delete_selected(self) -> str | None:
        """Delete the selected node + every connected edge.

        Returns the deleted node name (or ``None`` when nothing selected).
        Called by the Del-key handler + tests.
        """
        if self.selected is None:
            return None
        name = self.selected
        self.graph.nodes.pop(name, None)
        # Drop every incident edge — the underlying dataclass exposes
        # a plain list so we filter in place.
        self.graph.edges = [
            e for e in self.graph.edges
            if e.from_node != name and e.to_node != name
        ]
        self.positions.pop(name, None)
        self.selected = None
        self._repaint_canvas()
        self.last_status = f"deleted {name}"
        return name

    # ------------------------------------------------------------------
    # Compile
    # ------------------------------------------------------------------

    def compile(self) -> str:
        """Compile the current graph to WGSL and stash the result.

        Adds a temporary :class:`PBROutputNode` when the graph doesn't
        already contain one so a partial in-progress graph can still
        preview. The temporary node is removed after compile.
        """
        added_output: str | None = None
        if not any(isinstance(n, PBROutputNode) for n in self.graph.nodes.values()):
            temp_name = _fresh_name(self.graph.nodes, "__preview_output__")
            self.graph.add_node(PBROutputNode(temp_name))
            added_output = temp_name
        try:
            wgsl = self.graph.compile()
        finally:
            if added_output is not None:
                self.graph.nodes.pop(added_output, None)
                self.graph.edges = [
                    e for e in self.graph.edges
                    if e.from_node != added_output and e.to_node != added_output
                ]
        self.last_compiled_wgsl = wgsl
        self.last_status = f"compiled — {wgsl.count(chr(10)) + 1} WGSL lines"
        self._paint_wgsl_modal(wgsl)
        return wgsl

    # ------------------------------------------------------------------
    # YAML round-trip
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a YAML-safe dict capturing graph + canvas overlay."""
        data = self.graph.to_dict()
        data["canvas"] = {
            "positions": {k: list(v) for k, v in self.positions.items()},
        }
        return data

    def save_yaml(self, path: str) -> None:
        """Write the canvas state (graph + positions) to *path* as YAML."""
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.to_dict(), f, sort_keys=False)

    def load_yaml(self, path: str) -> None:
        """Replace the current state with a YAML payload from *path*."""
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        self._replace_from_dict(data)

    def _replace_from_dict(self, data: dict[str, Any]) -> None:
        """In-place swap of graph + positions from a canvas dict."""
        graph = MaterialGraph()
        for n in data.get("nodes", []):
            typ = _NODE_TYPES[n["type"]]
            params = n.get("params", {}) or {}
            node = typ(n["name"], **params)
            graph.add_node(node)
        for e in data.get("edges", []):
            graph.connect(
                e["from_node"], e["from_slot"],
                e["to_node"], e["to_slot"],
            )
        self.graph = graph
        # Canvas overlay — fall back to (0, 0) if the payload lacked
        # positions (e.g. loading a pure-DDD5 YAML).
        canvas = data.get("canvas") or {}
        raw_positions = canvas.get("positions") or {}
        self.positions = {
            k: (float(v[0]), float(v[1]))
            for k, v in raw_positions.items()
            if k in graph.nodes
        }
        for name in graph.nodes:
            self.positions.setdefault(name, (0.0, 0.0))
        self.selected = None
        self.armed_palette = None
        self._repaint_canvas()
        self.last_status = "loaded YAML"

    # ------------------------------------------------------------------
    # Clear
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Wipe every node + edge + position; repaint the canvas."""
        self.graph = MaterialGraph()
        self.positions.clear()
        self.selected = None
        self.armed_palette = None
        self._repaint_canvas()
        self.last_status = "cleared"

    # ------------------------------------------------------------------
    # DPG build
    # ------------------------------------------------------------------

    def build(self, parent_tag: int | str) -> None:
        """Materialise the panel under *parent_tag* (DPG protocol)."""
        self._built = True
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            with dpg.group(parent=parent_tag, tag=self._panel_tag):
                self._build_toolbar(dpg)
                try:
                    dpg.add_separator()
                except Exception:
                    pass
                # Three-column body — palette | canvas | inspector.
                with dpg.group(horizontal=True):
                    self._build_palette(dpg)
                    self._build_canvas(dpg)
                    self._build_inspector(dpg)
                # Status strip along the bottom.
                try:
                    dpg.add_text("", tag=self._status_tag)
                except Exception:
                    pass
                # WGSL modal — hidden until Compile is pressed.
                self._build_wgsl_modal(dpg)
                # Key handler — Del removes the selected node.
                self._install_key_handler(dpg)
        except Exception:
            # Stub DPG lacking context managers — fall back to bare adds
            # so the tag still lands.
            try:
                dpg.add_text(TITLE, parent=parent_tag)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # DPG paint helpers — each guarded so stub DPG doesn't blow up.
    # ------------------------------------------------------------------

    def _build_toolbar(self, dpg: Any) -> None:
        try:
            with dpg.group(horizontal=True, tag=self._toolbar_tag):
                dpg.add_button(label="Compile", callback=self._on_compile_click)
                dpg.add_button(label="Save YAML", callback=self._on_save_click)
                dpg.add_button(label="Load YAML", callback=self._on_load_click)
                dpg.add_button(label="Clear", callback=self._on_clear_click)
        except Exception:
            # Stub DPG lacking context managers — bare adds so the tags
            # still land for tests to inspect.
            for label, cb in (
                ("Compile", self._on_compile_click),
                ("Save YAML", self._on_save_click),
                ("Load YAML", self._on_load_click),
                ("Clear", self._on_clear_click),
            ):
                try:
                    dpg.add_button(label=label, callback=cb)
                except Exception:
                    pass

    def _build_palette(self, dpg: Any) -> None:
        try:
            with dpg.child_window(
                tag=self._palette_tag,
                width=140,
                height=-1,
                border=True,
            ):
                dpg.add_text("Palette")
                dpg.add_separator()
                for key, label, _cls in NODE_PALETTE:
                    dpg.add_button(
                        label=label,
                        width=-1,
                        callback=self._make_palette_callback(key),
                    )
        except Exception:
            for key, label, _cls in NODE_PALETTE:
                try:
                    dpg.add_button(
                        label=label,
                        callback=self._make_palette_callback(key),
                    )
                except Exception:
                    pass

    def _build_canvas(self, dpg: Any) -> None:
        try:
            with dpg.child_window(
                tag=self._canvas_tag,
                width=-260,
                height=-1,
                border=True,
            ):
                # Prefer DPG's native node editor when the build exposes it.
                add_node_editor = getattr(dpg, "add_node_editor", None)
                if callable(add_node_editor):
                    try:
                        add_node_editor(
                            tag=f"{self._canvas_tag}_editor",
                            callback=self._on_link,
                            delink_callback=self._on_delink,
                        )
                    except Exception:
                        pass
                else:
                    try:
                        dpg.add_text("(canvas — click a palette entry, then click here)")
                    except Exception:
                        pass
        except Exception:
            pass

    def _build_inspector(self, dpg: Any) -> None:
        try:
            with dpg.child_window(
                tag=self._inspector_tag,
                width=240,
                height=-1,
                border=True,
            ):
                dpg.add_text("Inspector")
                dpg.add_separator()
                dpg.add_text("(select a node)")
        except Exception:
            pass

    def _build_wgsl_modal(self, dpg: Any) -> None:
        try:
            with dpg.window(
                tag=self._wgsl_modal_tag,
                label="Compiled WGSL",
                modal=True,
                show=False,
                width=520,
                height=420,
            ):
                dpg.add_input_text(
                    tag=self._wgsl_text_tag,
                    multiline=True,
                    readonly=True,
                    width=-1,
                    height=-40,
                    default_value="",
                )
                dpg.add_button(
                    label="Close",
                    callback=self._on_wgsl_modal_close,
                )
        except Exception:
            pass

    def _install_key_handler(self, dpg: Any) -> None:
        try:
            with dpg.handler_registry(tag=f"{self._panel_tag}_keys"):
                dpg.add_key_press_handler(
                    key=getattr(dpg, "mvKey_Delete", 261),
                    callback=self._on_delete_key,
                )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # DPG paint — nodes / links / inspector / modal
    # ------------------------------------------------------------------

    def _paint_node(self, node: MaterialNode, x: float, y: float) -> None:
        dpg = _safe_dpg()
        if dpg is None or not self._built:
            return
        editor_tag = f"{self._canvas_tag}_editor"
        try:
            if not dpg.does_item_exist(editor_tag):
                return
        except Exception:
            return
        node_tag = f"matgraph_node_{id(self)}_{node.name}"
        self._node_tags[node.name] = node_tag
        try:
            with dpg.node(
                label=f"{type(node).__name__}: {node.name}",
                tag=node_tag,
                parent=editor_tag,
                pos=(int(x), int(y)),
            ):
                for slot_name, slot in node.inputs.items():
                    attr_tag = f"{node_tag}_in_{slot_name}"
                    self._attr_meta[attr_tag] = (node.name, slot_name, "input")
                    with dpg.node_attribute(
                        tag=attr_tag,
                        attribute_type=getattr(dpg, "mvNode_Attr_Input", 0),
                    ):
                        dpg.add_text(f"{slot_name} : {slot.dtype}")
                for slot_name, slot in node.outputs.items():
                    attr_tag = f"{node_tag}_out_{slot_name}"
                    self._attr_meta[attr_tag] = (node.name, slot_name, "output")
                    with dpg.node_attribute(
                        tag=attr_tag,
                        attribute_type=getattr(dpg, "mvNode_Attr_Output", 1),
                    ):
                        dpg.add_text(f"{slot_name} : {slot.dtype}")
        except Exception:
            pass

    def _paint_link(
        self,
        from_node: str,
        from_slot: str,
        to_node: str,
        to_slot: str,
    ) -> None:
        dpg = _safe_dpg()
        if dpg is None or not self._built:
            return
        editor_tag = f"{self._canvas_tag}_editor"
        try:
            if not dpg.does_item_exist(editor_tag):
                return
        except Exception:
            return
        from_attr = f"matgraph_node_{id(self)}_{from_node}_out_{from_slot}"
        to_attr = f"matgraph_node_{id(self)}_{to_node}_in_{to_slot}"
        link_tag = f"matgraph_link_{id(self)}_{len(self._link_tags)}"
        try:
            dpg.add_node_link(from_attr, to_attr, parent=editor_tag, tag=link_tag)
            self._link_tags[link_tag] = (from_node, from_slot, to_node, to_slot)
        except Exception:
            self._link_tags[link_tag] = (from_node, from_slot, to_node, to_slot)

    def _paint_inspector(self) -> None:
        dpg = _safe_dpg()
        if dpg is None or not self._built:
            return
        try:
            if not dpg.does_item_exist(self._inspector_tag):
                return
            dpg.delete_item(self._inspector_tag, children_only=True)
            dpg.add_text("Inspector", parent=self._inspector_tag)
            dpg.add_separator(parent=self._inspector_tag)
            if self.selected is None:
                dpg.add_text("(select a node)", parent=self._inspector_tag)
                return
            node = self.graph.nodes.get(self.selected)
            if node is None:
                dpg.add_text(
                    f"(node {self.selected!r} vanished)",
                    parent=self._inspector_tag,
                )
                return
            dpg.add_text(
                f"{type(node).__name__}: {node.name}",
                parent=self._inspector_tag,
            )
            for pname, pval in node.params.items():
                widget_tag = f"insp_{id(self)}_{node.name}_{pname}"
                if isinstance(pval, bool):
                    dpg.add_checkbox(
                        label=pname,
                        tag=widget_tag,
                        default_value=pval,
                        parent=self._inspector_tag,
                        callback=self._make_param_callback(node, pname),
                    )
                elif isinstance(pval, (int, float)):
                    dpg.add_input_float(
                        label=pname,
                        tag=widget_tag,
                        default_value=float(pval),
                        parent=self._inspector_tag,
                        callback=self._make_param_callback(node, pname),
                    )
                else:
                    dpg.add_input_text(
                        label=pname,
                        tag=widget_tag,
                        default_value=str(pval),
                        parent=self._inspector_tag,
                        callback=self._make_param_callback(node, pname),
                    )
        except Exception:
            pass

    def _paint_wgsl_modal(self, wgsl: str) -> None:
        dpg = _safe_dpg()
        if dpg is None or not self._built:
            return
        try:
            if dpg.does_item_exist(self._wgsl_text_tag):
                dpg.set_value(self._wgsl_text_tag, wgsl)
            if dpg.does_item_exist(self._wgsl_modal_tag):
                dpg.configure_item(self._wgsl_modal_tag, show=True)
        except Exception:
            pass

    def _repaint_canvas(self) -> None:
        """Full re-paint after clear / load / delete — cheapest path is to
        drop the whole editor and rebuild every node + link from the
        underlying graph.
        """
        dpg = _safe_dpg()
        self._node_tags.clear()
        self._attr_meta.clear()
        self._link_tags.clear()
        if dpg is None or not self._built:
            return
        editor_tag = f"{self._canvas_tag}_editor"
        try:
            if dpg.does_item_exist(editor_tag):
                dpg.delete_item(editor_tag, children_only=True)
        except Exception:
            pass
        # Re-paint each node in graph order.
        for name, node in self.graph.nodes.items():
            x, y = self.positions.get(name, (0.0, 0.0))
            self._paint_node(node, x, y)
        # And every edge.
        for edge in self.graph.edges:
            self._paint_link(
                edge.from_node, edge.from_slot,
                edge.to_node, edge.to_slot,
            )
        self._paint_inspector()
        self._paint_status()

    def _paint_status(self) -> None:
        dpg = _safe_dpg()
        if dpg is None or not self._built:
            return
        try:
            if dpg.does_item_exist(self._status_tag):
                dpg.set_value(self._status_tag, self.last_status)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # DPG callbacks
    # ------------------------------------------------------------------

    def _make_palette_callback(self, palette_key: str) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            # Palette click auto-places at a cascading offset when the
            # canvas isn't wired to receive click coordinates (which is
            # the common case under DPG's node editor).
            offset = 40 * len(self.graph.nodes)
            self.place_node(palette_key, x=40 + offset, y=40 + offset)
            self._paint_status()
        return _cb

    def _make_param_callback(
        self, node: MaterialNode, param_name: str,
    ) -> Callable[..., None]:
        def _cb(sender: Any = None, app_data: Any = None, *_a: Any, **_kw: Any) -> None:
            node.params[param_name] = app_data
        return _cb

    def _on_link(self, sender: Any, app_data: Any) -> None:
        """DPG link callback — decode attribute tags and delegate to wire()."""
        try:
            from_attr, to_attr = app_data
        except Exception:
            return
        from_meta = self._attr_meta.get(from_attr)
        to_meta = self._attr_meta.get(to_attr)
        if from_meta is None or to_meta is None:
            return
        from_node, from_slot, from_dir = from_meta
        to_node, to_slot, to_dir = to_meta
        if from_dir != "output" or to_dir != "input":
            return
        self.wire(from_node, from_slot, to_node, to_slot)
        self._paint_status()

    def _on_delink(self, sender: Any, app_data: Any) -> None:
        link_tag = app_data
        edge_key = self._link_tags.pop(link_tag, None)
        if edge_key is None:
            return
        f_n, f_s, t_n, t_s = edge_key
        self.graph.edges = [
            e for e in self.graph.edges
            if not (
                e.from_node == f_n
                and e.from_slot == f_s
                and e.to_node == t_n
                and e.to_slot == t_s
            )
        ]
        dpg = _safe_dpg()
        if dpg is not None:
            try:
                if dpg.does_item_exist(link_tag):
                    dpg.delete_item(link_tag)
            except Exception:
                pass
        self.last_status = f"delinked {f_n}.{f_s} → {t_n}.{t_s}"
        self._paint_status()

    def _on_compile_click(self, *_a: Any, **_kw: Any) -> None:
        try:
            self.compile()
        except Exception as ex:
            self.last_status = f"compile failed: {ex}"
        self._paint_status()

    def _on_save_click(self, *_a: Any, **_kw: Any) -> None:
        try:
            self.save_yaml("material_graph.yaml")
            self.last_status = "saved material_graph.yaml"
        except Exception as ex:
            self.last_status = f"save failed: {ex}"
        self._paint_status()

    def _on_load_click(self, *_a: Any, **_kw: Any) -> None:
        try:
            self.load_yaml("material_graph.yaml")
        except Exception as ex:
            self.last_status = f"load failed: {ex}"
        self._paint_status()

    def _on_clear_click(self, *_a: Any, **_kw: Any) -> None:
        self.clear()
        self._paint_status()

    def _on_wgsl_modal_close(self, *_a: Any, **_kw: Any) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._wgsl_modal_tag):
                dpg.configure_item(self._wgsl_modal_tag, show=False)
        except Exception:
            pass

    def _on_delete_key(self, *_a: Any, **_kw: Any) -> None:
        self.delete_selected()
        self._paint_status()


# ---------------------------------------------------------------------------
# Factory used by EditorShell (mirrors ``make_repl_panel``).
# ---------------------------------------------------------------------------


def make_material_graph_canvas(
    graph: MaterialGraph | None = None,
) -> MaterialGraphCanvas:
    """Return a fresh :class:`MaterialGraphCanvas`.

    Kept as a free function so the shell can construct the panel without
    importing the class name into its module namespace.
    """
    return MaterialGraphCanvas(graph=graph)


__all__ = [
    "MaterialGraphCanvas",
    "TITLE",
    "NODE_PALETTE",
    "COMPATIBILITY_TABLE",
    "is_compatible",
    "make_material_graph_canvas",
]
