from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playslap.material.node_material import NodeMaterial, NodeDef


# --------------------------------------------------------------------------
# Port layout declared here so _build_node() can resolve it without imports.
# Mirrors graph_schema.KNOWN_PORT_TYPES — kept local to avoid a hard dep at
# module-load time (the editor extra may be installed without _core).
# --------------------------------------------------------------------------
_PORT_SCHEMA: dict[str, dict[str, list[str]]] = {
    "UV":           {"inputs": [],                  "outputs": ["uv"]},
    "GravityWarp":  {"inputs": ["uv"],              "outputs": ["out_uv"]},
    "SampleTexture":{"inputs": ["uv"],              "outputs": ["color"]},
    "FinalColor":   {"inputs": ["color"],           "outputs": []},
    "Add":          {"inputs": ["a", "b"],          "outputs": ["out"]},
    "Multiply":     {"inputs": ["a", "b"],          "outputs": ["out"]},
    "Lerp":         {"inputs": ["a", "b", "t"],     "outputs": ["out"]},
    "Clamp":        {"inputs": ["val"],             "outputs": ["out"]},
    "Remap":        {"inputs": ["val"],             "outputs": ["out"]},
    "PixelColor":   {"inputs": [],                  "outputs": ["color"]},
    "PixelChannel": {"inputs": [],                  "outputs": ["val"]},
    "Discard":      {"inputs": [],                  "outputs": []},
}

# Params that should be edited as float sliders vs text input.
_FLOAT_PARAMS: frozenset[str] = frozenset({"min", "max", "strength", "radius"})

# Nodes that can be inserted via the "Add Node" menu, grouped by category.
_ADD_MENU: dict[str, list[str]] = {
    "Source":   ["UV", "PixelColor", "PixelChannel"],
    "Sample":   ["SampleTexture"],
    "Math":     ["Add", "Multiply", "Lerp", "Clamp", "Remap"],
    "Warp":     ["GravityWarp"],
    "Output":   ["FinalColor", "Discard"],
}

# Default params for nodes that require them when inserted from the menu.
_DEFAULT_PARAMS: dict[str, dict] = {
    "Clamp":        {"min": 0.0, "max": 1.0},
    "GravityWarp":  {"strength": 2.0, "radius": 0.3},
    "PixelChannel": {"channel": "r"},
}


class NodeGraphPanel:
    """
    Visual node graph editor using DPG's built-in node editor widget.

    Edits :class:`~playslap.material.node_material.NodeMaterial` graphs —
    each :class:`~playslap.material.node_material.NodeDef` becomes a DPG
    node box with typed input/output port attributes.

    Protocol: ``build(parent_tag) -> None``

    All ``dearpygui`` imports are deferred to runtime so the rest of the engine
    remains importable without the ``[editor]`` extra installed.
    """

    def __init__(self) -> None:
        self._material: NodeMaterial | None = None

        # DPG tag for the outer group (holds toolbar + editor canvas).
        self._panel_tag: str = "node_graph_panel"
        # DPG tag for the node editor canvas itself.
        self._editor_tag: str = "node_graph_editor"

        # node_def.id  →  DPG node tag  (str, built as f"ng_node_{node_id}")
        self._node_tags: dict[str, str] = {}

        # Flat map: DPG attribute tag  →  (node_id, port_name, "input"|"output")
        # Used by the link/delink callbacks to decode which ports are being wired.
        self._attr_meta: dict[str, tuple[str, str, str]] = {}

        # DPG link tag  →  edge dict so we can remove it from the material on delink.
        self._link_tags: dict[str, dict] = {}

        # Counter for generating unique integer-based tags within a session.
        self._tag_counter: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_material(self, material: NodeMaterial) -> None:
        """Switch which :class:`NodeMaterial` is displayed and edited."""
        self._material = material
        self._refresh()

    def build(self, parent_tag) -> None:
        """
        Build the DPG widget tree inside *parent_tag*.

        Creates a toolbar row (Add Node menu, Compile button, Clear button)
        followed by the node editor canvas.  If a material is already loaded
        it is rendered immediately.
        """
        import dearpygui.dearpygui as dpg

        with dpg.group(tag=self._panel_tag, parent=parent_tag):
            # ---- Toolbar -------------------------------------------------
            with dpg.group(horizontal=True):
                # "Add Node" popup menu
                dpg.add_button(
                    label="+ Add Node",
                    callback=self._open_add_menu,
                )
                dpg.add_button(
                    label="Compile",
                    callback=self._compile_callback,
                )
                dpg.add_button(
                    label="Clear",
                    callback=self._clear_callback,
                )

            # Hidden popup that contains the per-category add-node entries.
            # It is positioned and shown by _open_add_menu().
            with dpg.window(
                tag="ng_add_menu_popup",
                popup=True,
                no_title_bar=True,
                autosize=True,
                no_saved_settings=True,
                show=False,
            ):
                for category, node_types in _ADD_MENU.items():
                    dpg.add_text(category, color=(160, 160, 255))
                    for ntype in node_types:
                        dpg.add_menu_item(
                            label=ntype,
                            callback=self._make_add_node_callback(ntype),
                        )
                    dpg.add_separator()

            dpg.add_separator()

            # ---- Node editor canvas -------------------------------------
            dpg.add_node_editor(
                tag=self._editor_tag,
                callback=self._link_callback,
                delink_callback=self._delink_callback,
                minimap=True,
                minimap_location=dpg.mvNodeMiniMap_Location_BottomRight,
            )

        # Populate canvas if a material was pre-loaded before build().
        if self._material is not None:
            self._populate_canvas()

    # ------------------------------------------------------------------
    # Canvas population helpers
    # ------------------------------------------------------------------

    def _populate_canvas(self) -> None:
        """Render all nodes and edges of the current material onto the canvas."""
        import dearpygui.dearpygui as dpg

        if self._material is None:
            return
        if not dpg.does_item_exist(self._editor_tag):
            return

        self._node_tags.clear()
        self._attr_meta.clear()
        self._link_tags.clear()

        for node_def in self._material._nodes:
            self._build_node(node_def)

        for edge in self._material._edges:
            self._build_link(edge)

    def _build_node(self, node_def: NodeDef) -> None:
        """Add a single DPG node box for *node_def* to the editor canvas."""
        import dearpygui.dearpygui as dpg

        node_id = node_def.id
        node_tag = f"ng_node_{node_id}"
        self._node_tags[node_id] = node_tag

        schema = _PORT_SCHEMA.get(node_def.node_type, {"inputs": [], "outputs": []})

        with dpg.node(
            label=node_def.node_type,
            tag=node_tag,
            parent=self._editor_tag,
        ):
            # ---- Input ports -----------------------------------------
            for port_name in schema["inputs"]:
                attr_tag = f"ng_attr_{node_id}_{port_name}_in"
                self._attr_meta[attr_tag] = (node_id, port_name, "input")
                with dpg.node_attribute(
                    tag=attr_tag,
                    attribute_type=dpg.mvNode_Attr_Input,
                    label=port_name,
                ):
                    dpg.add_text(port_name)

            # ---- Param controls (Static attributes) ------------------
            for param_name, param_val in node_def.params.items():
                attr_tag = f"ng_attr_{node_id}_{param_name}_static"
                widget_tag = f"ng_widget_{node_id}_{param_name}"
                with dpg.node_attribute(
                    tag=attr_tag,
                    attribute_type=dpg.mvNode_Attr_Static,
                    label=param_name,
                ):
                    if param_name in _FLOAT_PARAMS and isinstance(param_val, (int, float)):
                        dpg.add_input_float(
                            tag=widget_tag,
                            label=param_name,
                            default_value=float(param_val),
                            width=120,
                            step=0.0,
                            callback=self._make_param_callback(node_def, param_name),
                        )
                    else:
                        dpg.add_input_text(
                            tag=widget_tag,
                            label=param_name,
                            default_value=str(param_val),
                            width=120,
                            callback=self._make_param_callback(node_def, param_name),
                        )

            # ---- Output ports ----------------------------------------
            for port_name in schema["outputs"]:
                attr_tag = f"ng_attr_{node_id}_{port_name}_out"
                self._attr_meta[attr_tag] = (node_id, port_name, "output")
                with dpg.node_attribute(
                    tag=attr_tag,
                    attribute_type=dpg.mvNode_Attr_Output,
                    label=port_name,
                ):
                    dpg.add_text(port_name)

    def _build_link(self, edge: dict) -> None:
        """Draw a wire for an existing *edge* dict from the material's edge list."""
        import dearpygui.dearpygui as dpg

        from_node_id = edge["from_node"]
        from_port    = edge["from_port"]
        to_node_id   = edge["to_node"]
        to_port      = edge["to_port"]

        from_attr = f"ng_attr_{from_node_id}_{from_port}_out"
        to_attr   = f"ng_attr_{to_node_id}_{to_port}_in"

        if not dpg.does_item_exist(from_attr) or not dpg.does_item_exist(to_attr):
            return

        link_tag = f"ng_link_{self._next_tag()}"
        dpg.add_node_link(from_attr, to_attr, parent=self._editor_tag, tag=link_tag)
        self._link_tags[link_tag] = edge

    # ------------------------------------------------------------------
    # DPG callbacks
    # ------------------------------------------------------------------

    def _link_callback(self, sender, app_data) -> None:
        """Called by DPG when the user drags a wire between two attributes.

        *app_data* is a tuple ``(from_attr_tag, to_attr_tag)``.
        """
        import dearpygui.dearpygui as dpg

        if self._material is None:
            return

        from_attr_tag, to_attr_tag = app_data

        from_meta = self._attr_meta.get(from_attr_tag)
        to_meta   = self._attr_meta.get(to_attr_tag)

        if from_meta is None or to_meta is None:
            return

        from_node_id, from_port, from_dir = from_meta
        to_node_id,   to_port,   to_dir   = to_meta

        # Enforce directionality: output → input.
        if from_dir != "output" or to_dir != "input":
            return

        # Guard: refuse to wire a node to itself.
        if from_node_id == to_node_id:
            return

        # Deduplicate: skip if this exact edge already exists.
        edge = {
            "from_node": from_node_id,
            "from_port": from_port,
            "to_node":   to_node_id,
            "to_port":   to_port,
        }
        if edge in self._material._edges:
            return

        self._material._edges.append(edge)

        link_tag = f"ng_link_{self._next_tag()}"
        dpg.add_node_link(from_attr_tag, to_attr_tag, parent=sender, tag=link_tag)
        self._link_tags[link_tag] = edge

    def _delink_callback(self, sender, app_data) -> None:
        """Called by DPG when the user deletes a wire.

        *app_data* is the DPG tag of the link item to remove.
        """
        import dearpygui.dearpygui as dpg

        link_tag = app_data
        edge = self._link_tags.pop(link_tag, None)

        if edge is not None and self._material is not None:
            try:
                self._material._edges.remove(edge)
            except ValueError:
                pass

        if dpg.does_item_exist(link_tag):
            dpg.delete_item(link_tag)

    def _compile_callback(self) -> None:
        """Trigger WGSL compilation for the current material."""
        if self._material is None:
            return
        try:
            self._material.compile()
        except RuntimeError:
            # _core not available (no Rust extension) — silently skip in editor.
            pass

    def _clear_callback(self) -> None:
        """Remove all nodes and edges from the material and repaint the canvas."""
        if self._material is None:
            return
        self._material._nodes.clear()
        self._material._edges.clear()
        self._refresh()

    def _open_add_menu(self) -> None:
        """Show the 'Add Node' popup window."""
        import dearpygui.dearpygui as dpg

        if dpg.does_item_exist("ng_add_menu_popup"):
            dpg.configure_item("ng_add_menu_popup", show=True)

    # ------------------------------------------------------------------
    # Callback factories
    # ------------------------------------------------------------------

    def _make_add_node_callback(self, node_type: str):
        """Return a callback that appends a new node of *node_type* to the material."""
        def _cb(sender, app_data, user_data, _ntype=node_type):
            self._add_node(_ntype)
        return _cb

    def _make_param_callback(self, node_def: NodeDef, param_name: str):
        """Return a callback that writes the widget value back to *node_def.params*."""
        def _cb(sender, app_data, user_data, _nd=node_def, _pn=param_name):
            _nd.params[_pn] = app_data
        return _cb

    # ------------------------------------------------------------------
    # Node insertion
    # ------------------------------------------------------------------

    def _add_node(self, node_type: str) -> None:
        """Append a new NodeDef of *node_type* to the material and paint it."""
        import dearpygui.dearpygui as dpg

        if self._material is None:
            return
        if not dpg.does_item_exist(self._editor_tag):
            return

        from playslap.material.node_material import NodeDef

        params = dict(_DEFAULT_PARAMS.get(node_type, {}))
        node_def = NodeDef(node_type=node_type, params=params)
        self._material._nodes.append(node_def)
        self._build_node(node_def)

        # Hide the popup after selection.
        if dpg.does_item_exist("ng_add_menu_popup"):
            dpg.configure_item("ng_add_menu_popup", show=False)

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        """Wipe the canvas and rebuild from the current material state."""
        import dearpygui.dearpygui as dpg

        if not dpg.does_item_exist(self._editor_tag):
            return

        # Remove all child items of the node editor (nodes + links).
        dpg.delete_item(self._editor_tag, children_only=True)

        self._node_tags.clear()
        self._attr_meta.clear()
        self._link_tags.clear()

        if self._material is not None:
            self._populate_canvas()

    # ------------------------------------------------------------------
    # Internal utilities
    # ------------------------------------------------------------------

    def _next_tag(self) -> int:
        """Return a session-unique integer suffix for generated DPG tags."""
        self._tag_counter += 1
        return self._tag_counter
