from __future__ import annotations


class LayerPanel:
    """
    Layer stack panel: shows layers of the selected asset.
    Supports visibility toggle, add, delete, reorder (move up/down).

    Protocol: build(parent_tag) -> None
    """

    def __init__(self):
        self._asset = None  # the currently selected asset
        self._panel_tag = "layer_panel"
        self._on_mode_change = None  # optional callback(layer, mode)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_asset(self, asset) -> None:
        """Switch which asset's layers are displayed."""
        self._asset = asset
        self._refresh()

    def set_on_layer_mode_change(self, cb) -> None:
        """Register a callback invoked when a layer's mode changes.

        Signature: cb(layer, mode: str) -> None
        """
        self._on_mode_change = cb

    def build(self, parent_tag) -> None:
        """Build the DPG widget tree inside parent_tag."""
        import dearpygui.dearpygui as dpg

        # Top header row: "Layers" label + "Add Layer" button
        with dpg.group(horizontal=True, parent=parent_tag):
            dpg.add_text("Layers")
            dpg.add_button(
                label="+ Add",
                callback=lambda: self._add_layer(),
            )

        dpg.add_separator(parent=parent_tag)

        # Container group whose children are rebuilt on _refresh()
        dpg.add_group(tag=self._panel_tag, parent=parent_tag)

        # Populate with current asset layers if one is already set
        if self._asset is not None:
            self._build_rows()

    def _refresh(self) -> None:
        """Delete and rebuild the layer list in the DPG widget."""
        import dearpygui.dearpygui as dpg

        if not dpg.does_item_exist(self._panel_tag):
            return

        dpg.delete_item(self._panel_tag, children_only=True)

        if self._asset is not None:
            self._build_rows()

    # ------------------------------------------------------------------
    # Row construction
    # ------------------------------------------------------------------

    def _build_rows(self) -> None:
        """Populate self._panel_tag with one row per layer (top-of-stack first)."""
        import dearpygui.dearpygui as dpg

        layers = self._asset.layers
        # Display reversed: index len-1 at top, index 0 at bottom
        for display_pos, layer_index in enumerate(range(len(layers) - 1, -1, -1)):
            layer = layers[layer_index]
            row_tag = f"layer_row_{layer_index}"

            # Each row is a horizontal group so all widgets sit on one line
            with dpg.group(
                horizontal=True,
                tag=row_tag,
                parent=self._panel_tag,
            ):
                # Visibility checkbox — eye toggle
                dpg.add_checkbox(
                    label="",
                    default_value=getattr(layer, "visible", True),
                    callback=self._make_visibility_callback(layer_index),
                )

                # Layer name (static label)
                dpg.add_text(layer.name)

                # Move up (toward top of stack, i.e. higher index)
                dpg.add_button(
                    label="↑",
                    callback=self._make_move_callback(layer_index, -1),
                    width=24,
                )

                # Move down (toward bottom of stack, i.e. lower index)
                dpg.add_button(
                    label="↓",
                    callback=self._make_move_callback(layer_index, 1),
                    width=24,
                )

                # Delete button
                dpg.add_button(
                    label="X",
                    callback=self._make_delete_callback(layer_index),
                    width=24,
                )

                # Mode radio buttons: [2D] [3D]
                dpg.add_radio_button(
                    items=["2D", "3D"],
                    default_value=getattr(layer, "mode", "2D"),
                    horizontal=True,
                    callback=self._make_mode_callback(layer_index),
                )

            # Right-click context menu for 3D layers (attached to the row group)
            if getattr(layer, "mode", "2D") == "3D":
                popup_tag = f"layer_row_{layer_index}_popup"
                with dpg.popup(
                    parent=row_tag,
                    tag=popup_tag,
                    mousebutton=dpg.mvMouseButton_Right,
                ):
                    dpg.add_text("Bake to 2D…")
                    dpg.add_separator()
                    dpg.add_menu_item(
                        label="Bake to 2D (256×256)",
                        callback=self._make_bake_callback(layer_index, (256, 256)),
                    )
                    dpg.add_menu_item(
                        label="Bake to 2D (512×512)",
                        callback=self._make_bake_callback(layer_index, (512, 512)),
                    )

    # ------------------------------------------------------------------
    # Callback factories — use explicit closure capture (not default args,
    # which DPG may override with positional arguments in some contexts)
    # ------------------------------------------------------------------

    def _make_visibility_callback(self, layer_index: int):
        _idx = int(layer_index)
        def _cb(sender, app_data, user_data):
            self._toggle_visible(_idx)
        return _cb

    def _make_move_callback(self, layer_index: int, direction: int):
        _idx, _dir = int(layer_index), int(direction)
        def _cb(sender, app_data, user_data):
            self._move_layer(_idx, _dir)
        return _cb

    def _make_delete_callback(self, layer_index: int):
        _idx = int(layer_index)
        def _cb(sender, app_data, user_data):
            self._delete_layer(_idx)
        return _cb

    def _make_mode_callback(self, layer_index: int):
        _idx = int(layer_index)
        def _cb(sender, app_data, user_data):
            self._set_layer_mode(_idx, app_data)
        return _cb

    def _make_bake_callback(self, layer_index: int, size: tuple):
        _idx = int(layer_index)
        _size = tuple(size)
        def _cb(sender, app_data, user_data):
            self._bake_layer(_idx, _size)
        return _cb

    # ------------------------------------------------------------------
    # Layer operations
    # ------------------------------------------------------------------

    def _add_layer(self) -> None:
        """Add a blank layer to the asset."""
        if self._asset is None:
            return

        from slappyengine.layer import Layer

        w, h = self._asset.size
        new_layer = Layer.blank(w, h, name=f"Layer {len(self._asset.layers) + 1}")
        self._asset.add_layer(new_layer)
        self._refresh()

    def _delete_layer(self, layer_index: int) -> None:
        """Remove layer at index from asset (at least one layer must remain)."""
        if self._asset is None:
            return

        layers = self._asset.layers
        if len(layers) <= 1:
            # Refuse to delete the last remaining layer
            return

        if not (0 <= layer_index < len(layers)):
            return

        layer = layers[layer_index]
        self._asset.remove_layer(layer)
        self._refresh()

    def _move_layer(self, layer_index: int, direction: int) -> None:
        """Move layer up (direction=-1, higher index) or down (direction=1, lower index).

        The UI displays layers in reverse order so "↑" visually moves a layer
        toward the top of the stack, which means increasing its list index.
        "↓" moves it toward the bottom, decreasing its list index.
        """
        if self._asset is None or layer_index is None or direction is None:
            return

        layers = self._asset.layers
        # direction=-1 means "move toward top of stack" → swap with layer at index+1
        # direction=+1 means "move toward bottom of stack" → swap with layer at index-1
        swap_index = layer_index - direction  # -(-1)=+1 for up, -(+1)=-1 for down

        if not (0 <= layer_index < len(layers)):
            return
        if not (0 <= swap_index < len(layers)):
            return

        layers[layer_index], layers[swap_index] = layers[swap_index], layers[layer_index]
        self._refresh()

    def _toggle_visible(self, layer_index: int) -> None:
        """Toggle layer.visible (if the attribute exists)."""
        if self._asset is None:
            return

        layers = self._asset.layers
        if not (0 <= layer_index < len(layers)):
            return

        layer = layers[layer_index]
        if hasattr(layer, "visible"):
            layer.visible = not layer.visible

    def _set_layer_mode(self, layer_index: int, mode: str) -> None:
        """Set the 2D/3D mode on a layer and refresh the panel."""
        if self._asset is None:
            return

        layers = self._asset.layers
        if not (0 <= layer_index < len(layers)):
            return

        layer = layers[layer_index]
        layer.mode = mode
        if mode == "3D" and not hasattr(layer, "mesh_geometry"):
            pass  # layer.py already adds these in __init__
        self._refresh()
        if self._on_mode_change:
            self._on_mode_change(layer, mode)

    def _bake_layer(self, layer_index: int, size: tuple) -> None:
        """Bake a 3D layer down to a 2D layer at the given pixel size and append it."""
        if self._asset is None:
            return

        layers = self._asset.layers
        if not (0 <= layer_index < len(layers)):
            return

        layer = layers[layer_index]
        if getattr(layer, "mode", "2D") != "3D":
            return

        try:
            baked = layer.bake_to_2d(size)
            self._asset.add_layer(baked)
            self._refresh()
        except Exception:
            pass
