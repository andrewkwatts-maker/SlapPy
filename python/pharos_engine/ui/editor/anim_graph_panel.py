from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pharos_engine.animation.graph import AnimationGraph


class AnimGraphPanel:
    """
    Visual state machine editor for AnimationGraph using DPG's node editor.

    Each AnimState becomes a DPG node.
    Each AnimTransition becomes a node link.
    Clicking a node selects it and shows its properties (clips, speed, etc.)

    Protocol: build(parent_tag) -> None
    """

    def __init__(self) -> None:
        self._graph: AnimationGraph | None = None
        self._cube_array = None
        self._panel_tag = "anim_graph_panel"
        self._editor_tag = "anim_graph_editor"
        self._props_tag = "anim_graph_props"
        # state_name → dpg attribute tag (output pin), used to build links
        self._state_attr_tags: dict[str, int | str] = {}
        # state currently shown in the properties sub-panel
        self._selected_state: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_graph(self, graph, cube_array=None) -> None:
        """Set the animation graph and optional CubeArray for frame references."""
        self._graph = graph
        self._cube_array = cube_array
        self._refresh()

    def build(self, parent_tag) -> None:
        """
        Construct the full animation-graph editor widget tree under *parent_tag*.

        Must be called after ``dpg.create_context()``.
        """
        import dearpygui.dearpygui as dpg

        # ── Header ──────────────────────────────────────────────────────
        with dpg.group(horizontal=True, parent=parent_tag):
            dpg.add_text("Animation Graph")
            dpg.add_button(
                label="+ Add State",
                callback=self._add_state,
            )
            dpg.add_button(
                label="Set Initial State",
                callback=self._set_initial_state,
            )

        dpg.add_separator(parent=parent_tag)

        # ── Node editor ─────────────────────────────────────────────────
        dpg.add_node_editor(
            tag=self._editor_tag,
            parent=parent_tag,
            callback=self._link_callback,
            delink_callback=self._delink_callback,
            height=400,
        )

        # Populate nodes / links if a graph is already attached
        if self._graph is not None:
            self._build_nodes()
            self._build_links()

        dpg.add_separator(parent=parent_tag)

        # ── Properties sub-panel ────────────────────────────────────────
        dpg.add_text("State Properties", parent=parent_tag)
        dpg.add_group(tag=self._props_tag, parent=parent_tag)
        self._build_props_panel()

    # ------------------------------------------------------------------
    # Node / link construction
    # ------------------------------------------------------------------

    def _build_state_node(self, name: str, state) -> None:
        """Create a DPG node for one AnimState."""
        import dearpygui.dearpygui as dpg

        node_tag = f"anim_state_{name}"
        out_tag = f"anim_out_{name}"
        in_tag = f"anim_in_{name}"

        with dpg.node(
            label=name,
            parent=self._editor_tag,
            tag=node_tag,
        ):
            # ── Output pin (outgoing transitions) ─────────────────────
            with dpg.node_attribute(
                label="out",
                attribute_type=dpg.mvNode_Attr_Output,
                tag=out_tag,
            ):
                dpg.add_text("→")

            # ── Input pin (incoming transitions) ──────────────────────
            with dpg.node_attribute(
                label="in",
                attribute_type=dpg.mvNode_Attr_Input,
                tag=in_tag,
            ):
                dpg.add_text("←")

            # ── Static attribute: clip count and fps ───────────────────
            with dpg.node_attribute(
                label="info",
                attribute_type=dpg.mvNode_Attr_Static,
            ):
                clip_count = len(state.clip_indices) if state.clip_indices else 0
                dpg.add_text(f"clips: {clip_count}")
                dpg.add_text(f"fps:   {state.fps:.1f}")
                loop_label = "loop" if state.loop else "once"
                dpg.add_text(f"mode:  {loop_label}")

            # ── Select button ──────────────────────────────────────────
            with dpg.node_attribute(
                label="sel",
                attribute_type=dpg.mvNode_Attr_Static,
            ):
                dpg.add_button(
                    label="Select",
                    callback=self._make_select_callback(name),
                    width=80,
                )

        self._state_attr_tags[name] = out_tag

    def _build_transition_link(self, transition) -> None:
        """Add a DPG node link for one AnimTransition."""
        import dearpygui.dearpygui as dpg

        from_tag = f"anim_out_{transition.from_state}"
        to_tag = f"anim_in_{transition.to_state}"

        # Only create the link if both endpoint nodes actually exist
        if dpg.does_item_exist(from_tag) and dpg.does_item_exist(to_tag):
            dpg.add_node_link(from_tag, to_tag, parent=self._editor_tag)

    def _build_nodes(self) -> None:
        """Create all state nodes from the current graph."""
        if self._graph is None:
            return
        for name, state in self._graph._states.items():
            self._build_state_node(name, state)

    def _build_links(self) -> None:
        """Create all transition links from the current graph."""
        if self._graph is None:
            return
        for transition in self._graph._transitions:
            self._build_transition_link(transition)

    # ------------------------------------------------------------------
    # Properties sub-panel
    # ------------------------------------------------------------------

    def _build_props_panel(self) -> None:
        """Populate the properties group for the currently selected state."""
        import dearpygui.dearpygui as dpg

        if not dpg.does_item_exist(self._props_tag):
            return

        dpg.delete_item(self._props_tag, children_only=True)

        if self._graph is None or self._selected_state is None:
            dpg.add_text(
                "(no state selected)",
                parent=self._props_tag,
                tag=f"{self._props_tag}_empty",
            )
            return

        state = self._graph._states.get(self._selected_state)
        if state is None:
            dpg.add_text(
                "(state not found)",
                parent=self._props_tag,
                tag=f"{self._props_tag}_missing",
            )
            return

        # State name (read-only label)
        dpg.add_text(
            f"State: {state.name}",
            parent=self._props_tag,
            tag=f"{self._props_tag}_name",
        )

        # FPS input
        dpg.add_input_float(
            label="FPS",
            default_value=state.fps,
            min_value=0.1,
            max_value=240.0,
            callback=self._make_fps_callback(state.name),
            parent=self._props_tag,
            tag=f"{self._props_tag}_fps",
            width=120,
        )

        # Loop checkbox
        dpg.add_checkbox(
            label="Loop",
            default_value=state.loop,
            callback=self._make_loop_callback(state.name),
            parent=self._props_tag,
            tag=f"{self._props_tag}_loop",
        )

        dpg.add_separator(parent=self._props_tag)

        # Clip indices list (read-only display)
        clip_str = ", ".join(str(i) for i in state.clip_indices) if state.clip_indices else "(none)"
        dpg.add_text(
            f"Clip indices: {clip_str}",
            parent=self._props_tag,
            tag=f"{self._props_tag}_clips",
        )

        # Append clip index
        dpg.add_input_int(
            label="Clip index",
            default_value=0,
            min_value=0,
            tag=f"{self._props_tag}_clip_input",
            parent=self._props_tag,
            width=80,
        )
        dpg.add_button(
            label="Add Clip",
            callback=self._add_clip_to_selected,
            parent=self._props_tag,
            tag=f"{self._props_tag}_add_clip",
        )
        dpg.add_button(
            label="Clear Clips",
            callback=self._clear_clips_from_selected,
            parent=self._props_tag,
            tag=f"{self._props_tag}_clear_clips",
        )

        dpg.add_separator(parent=self._props_tag)

        # Outgoing transitions for this state
        outgoing = [
            t for t in self._graph._transitions
            if t.from_state == state.name
        ]
        dpg.add_text(
            f"Transitions ({len(outgoing)} outgoing):",
            parent=self._props_tag,
            tag=f"{self._props_tag}_trans_header",
        )
        for i, t in enumerate(outgoing):
            dpg.add_text(
                f"  → {t.to_state}",
                parent=self._props_tag,
                tag=f"{self._props_tag}_trans_{i}",
            )

    # ------------------------------------------------------------------
    # DPG callbacks
    # ------------------------------------------------------------------

    def _link_callback(self, sender, app_data) -> None:
        """
        Called by DPG when the user drags a link between two attribute pins.

        app_data is a tuple (output_attr_id, input_attr_id).
        Attribute tags have the form  anim_out_<name>  /  anim_in_<name>
        so we can recover state names by stripping the prefix.
        """
        import dearpygui.dearpygui as dpg
        from pharos_engine.animation.graph import AnimTransition

        if self._graph is None:
            return

        out_attr_id, in_attr_id = app_data

        # Resolve integer DPG ids back to string tags where possible
        out_alias = dpg.get_item_alias(out_attr_id) or str(out_attr_id)
        in_alias = dpg.get_item_alias(in_attr_id) or str(in_attr_id)

        prefix_out = "anim_out_"
        prefix_in = "anim_in_"

        if not (out_alias.startswith(prefix_out) and in_alias.startswith(prefix_in)):
            return

        from_name = out_alias[len(prefix_out):]
        to_name = in_alias[len(prefix_in):]

        if from_name not in self._graph._states or to_name not in self._graph._states:
            return

        # Avoid duplicate transitions
        for existing in self._graph._transitions:
            if existing.from_state == from_name and existing.to_state == to_name:
                return

        self._graph.add_transition(AnimTransition(from_state=from_name, to_state=to_name))
        # Draw the link in the editor
        dpg.add_node_link(out_attr_id, in_attr_id, parent=self._editor_tag)
        # Refresh properties if the selected state was the source
        if self._selected_state == from_name:
            self._build_props_panel()

    def _delink_callback(self, sender, app_data) -> None:
        """
        Called by DPG when the user right-clicks and removes a link.

        app_data is the link item id.  We delete the DPG link and look for
        the matching AnimTransition to remove from the graph.
        """
        import dearpygui.dearpygui as dpg

        if self._graph is None:
            return

        link_id = app_data

        # Retrieve the two endpoint attribute ids from the link configuration
        link_conf = dpg.get_item_configuration(link_id)
        out_attr_id = link_conf.get("attr_1")
        in_attr_id = link_conf.get("attr_2")

        if out_attr_id is not None and in_attr_id is not None:
            out_alias = dpg.get_item_alias(out_attr_id) or ""
            in_alias = dpg.get_item_alias(in_attr_id) or ""
            prefix_out = "anim_out_"
            prefix_in = "anim_in_"
            if out_alias.startswith(prefix_out) and in_alias.startswith(prefix_in):
                from_name = out_alias[len(prefix_out):]
                to_name = in_alias[len(prefix_in):]
                self._graph._transitions = [
                    t for t in self._graph._transitions
                    if not (t.from_state == from_name and t.to_state == to_name)
                ]

        dpg.delete_item(link_id)
        self._build_props_panel()

    # ------------------------------------------------------------------
    # Callback factories
    # ------------------------------------------------------------------

    def _make_select_callback(self, state_name: str):
        """Return a DPG callback that selects *state_name* in the props panel."""
        def _cb(sender, app_data, user_data, _name=state_name):
            self._selected_state = _name
            self._build_props_panel()
        return _cb

    def _make_fps_callback(self, state_name: str):
        """Return a DPG callback that updates the fps of *state_name*."""
        def _cb(sender, app_data, user_data, _name=state_name):
            if self._graph is None:
                return
            state = self._graph._states.get(_name)
            if state is not None:
                state.fps = float(app_data)
                # Refresh node label info
                self._refresh_node_info(_name, state)
        return _cb

    def _make_loop_callback(self, state_name: str):
        """Return a DPG callback that toggles the loop flag of *state_name*."""
        def _cb(sender, app_data, user_data, _name=state_name):
            if self._graph is None:
                return
            state = self._graph._states.get(_name)
            if state is not None:
                state.loop = bool(app_data)
        return _cb

    # ------------------------------------------------------------------
    # Clip mutations
    # ------------------------------------------------------------------

    def _add_clip_to_selected(self) -> None:
        """Append the clip index from the input widget to the selected state."""
        import dearpygui.dearpygui as dpg

        if self._graph is None or self._selected_state is None:
            return

        state = self._graph._states.get(self._selected_state)
        if state is None:
            return

        input_tag = f"{self._props_tag}_clip_input"
        if not dpg.does_item_exist(input_tag):
            return

        clip_idx = int(dpg.get_value(input_tag))
        state.clip_indices.append(clip_idx)
        self._build_props_panel()
        self._refresh_node_info(state.name, state)

    def _clear_clips_from_selected(self) -> None:
        """Remove all clip indices from the selected state."""
        if self._graph is None or self._selected_state is None:
            return
        state = self._graph._states.get(self._selected_state)
        if state is None:
            return
        state.clip_indices.clear()
        self._build_props_panel()
        self._refresh_node_info(state.name, state)

    # ------------------------------------------------------------------
    # Toolbar actions
    # ------------------------------------------------------------------

    def _add_state(self) -> None:
        """
        Add a new AnimState with a unique default name and rebuild the editor.

        Uses a simple incrementing suffix to guarantee uniqueness without
        requiring a modal dialog.
        """
        from pharos_engine.animation.graph import AnimState

        if self._graph is None:
            return

        base = "new_state"
        name = base
        counter = 1
        while name in self._graph._states:
            name = f"{base}_{counter}"
            counter += 1

        self._graph.add_state(AnimState(name=name))
        self._refresh()

    def _set_initial_state(self) -> None:
        """
        Set the initial state of the graph to whichever node is currently
        selected in the properties panel (i.e. self._selected_state).
        """
        if self._graph is None or self._selected_state is None:
            return
        if self._selected_state not in self._graph._states:
            return
        self._graph.set_initial(self._selected_state)

    # ------------------------------------------------------------------
    # Refresh helpers
    # ------------------------------------------------------------------

    def _refresh_node_info(self, name: str, state) -> None:
        """
        Update the static text widgets inside a node after a state mutation.

        This is a lightweight alternative to a full ``_refresh()`` that avoids
        destroying and recreating all nodes (which would reset their positions).
        The info attribute is identified by iterating the node's children and
        looking for text items to update.  If the node does not exist, this is
        a no-op.
        """
        import dearpygui.dearpygui as dpg

        node_tag = f"anim_state_{name}"
        if not dpg.does_item_exist(node_tag):
            return

        # Walk child attributes of the node looking for Text items
        clip_count = len(state.clip_indices) if state.clip_indices else 0
        new_texts = [
            f"clips: {clip_count}",
            f"fps:   {state.fps:.1f}",
            f"mode:  {'loop' if state.loop else 'once'}",
        ]

        # Gather all text children across all attribute children of the node
        text_items: list[int] = []
        for attr_id in dpg.get_item_children(node_tag, slot=1) or []:
            for child_id in dpg.get_item_children(attr_id, slot=1) or []:
                if dpg.get_item_type(child_id) == "mvAppItemType::mvText":
                    text_items.append(child_id)

        for i, new_text in enumerate(new_texts):
            if i < len(text_items):
                dpg.set_value(text_items[i], new_text)

    def _refresh(self) -> None:
        """Delete all nodes / links and rebuild from the current graph."""
        import dearpygui.dearpygui as dpg

        self._state_attr_tags.clear()

        if not dpg.does_item_exist(self._editor_tag):
            return

        # Delete all children of the node editor (nodes and links)
        dpg.delete_item(self._editor_tag, children_only=True)

        if self._graph is not None:
            self._build_nodes()
            self._build_links()

        # Rebuild the props panel; keep selected state if it still exists
        if self._selected_state is not None and (
            self._graph is None
            or self._selected_state not in self._graph._states
        ):
            self._selected_state = None

        self._build_props_panel()
