from __future__ import annotations


class MaterialEditor:
    """
    Visual editor for MaterialMap — shows color ranges and behavior tags.

    Each material entry shows:
    - Name (text input)
    - Color range sliders (R min/max, G min/max, B min/max)
    - Alpha meaning dropdown (opacity, health, strength, custom)
    - Behaviors list (comma-separated text input)
    - Delete button

    Plus an "Add Material" button at the bottom.

    Protocol: build(parent_tag) -> None
    """

    _ALPHA_MEANINGS = ["opacity", "health", "strength", "density", "pressure"]

    def __init__(self) -> None:
        self._material_map = None  # MaterialMap instance
        self._panel_tag = "material_editor"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_material_map(self, mat_map) -> None:
        """Attach a MaterialMap and rebuild the panel."""
        from playslap.material.map import MaterialMap  # noqa: F401 (type check)

        self._material_map = mat_map
        self._refresh()

    def build(self, parent_tag) -> None:
        """
        Construct the full material editor widget tree under *parent_tag*.

        Must be called after ``dpg.create_context()``.
        """
        import dearpygui.dearpygui as dpg

        dpg.add_text("Materials", parent=parent_tag)
        dpg.add_separator(parent=parent_tag)

        # Root group that we can wipe and rebuild on refresh.
        dpg.add_group(tag=self._panel_tag, parent=parent_tag)

        self._build_entries()

        dpg.add_separator(parent=parent_tag)
        dpg.add_button(
            label="Add Material",
            callback=self._add_material,
            parent=parent_tag,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_entries(self) -> None:
        """Populate self._panel_tag with one collapsing header per material."""
        import dearpygui.dearpygui as dpg

        if self._material_map is None:
            dpg.add_text(
                "No MaterialMap loaded.",
                parent=self._panel_tag,
                tag=f"{self._panel_tag}_empty_hint",
            )
            return

        for index, mat in enumerate(self._material_map._materials):
            self._build_entry(index, mat)

    def _build_entry(self, index: int, mat) -> None:
        """Build one collapsing header for a single MaterialDef."""
        import dearpygui.dearpygui as dpg

        header_tag = f"{self._panel_tag}_header_{index}"

        with dpg.collapsing_header(
            label=mat.name,
            parent=self._panel_tag,
            tag=header_tag,
        ):
            # ---- Name ------------------------------------------------
            dpg.add_input_text(
                label="Name",
                default_value=mat.name,
                callback=lambda s, app_data, idx=index: self._on_name_change(idx, app_data),
                parent=header_tag,
            )

            dpg.add_separator(parent=header_tag)

            # ---- Color range: R --------------------------------------
            dpg.add_text("R range", parent=header_tag)
            dpg.add_drag_int(
                label="R min",
                min_value=0,
                max_value=255,
                default_value=mat.color_range.r[0],
                callback=lambda s, app_data, idx=index: self._on_color_change(idx, "r", 0, app_data),
                parent=header_tag,
            )
            dpg.add_drag_int(
                label="R max",
                min_value=0,
                max_value=255,
                default_value=mat.color_range.r[1],
                callback=lambda s, app_data, idx=index: self._on_color_change(idx, "r", 1, app_data),
                parent=header_tag,
            )

            # ---- Color range: G --------------------------------------
            dpg.add_text("G range", parent=header_tag)
            dpg.add_drag_int(
                label="G min",
                min_value=0,
                max_value=255,
                default_value=mat.color_range.g[0],
                callback=lambda s, app_data, idx=index: self._on_color_change(idx, "g", 0, app_data),
                parent=header_tag,
            )
            dpg.add_drag_int(
                label="G max",
                min_value=0,
                max_value=255,
                default_value=mat.color_range.g[1],
                callback=lambda s, app_data, idx=index: self._on_color_change(idx, "g", 1, app_data),
                parent=header_tag,
            )

            # ---- Color range: B --------------------------------------
            dpg.add_text("B range", parent=header_tag)
            dpg.add_drag_int(
                label="B min",
                min_value=0,
                max_value=255,
                default_value=mat.color_range.b[0],
                callback=lambda s, app_data, idx=index: self._on_color_change(idx, "b", 0, app_data),
                parent=header_tag,
            )
            dpg.add_drag_int(
                label="B max",
                min_value=0,
                max_value=255,
                default_value=mat.color_range.b[1],
                callback=lambda s, app_data, idx=index: self._on_color_change(idx, "b", 1, app_data),
                parent=header_tag,
            )

            dpg.add_separator(parent=header_tag)

            # ---- Alpha meaning ----------------------------------------
            alpha = mat.alpha_meaning if mat.alpha_meaning in self._ALPHA_MEANINGS else self._ALPHA_MEANINGS[0]
            dpg.add_combo(
                label="Alpha meaning",
                items=self._ALPHA_MEANINGS,
                default_value=alpha,
                callback=lambda s, app_data, idx=index: self._on_alpha_change(idx, app_data),
                parent=header_tag,
            )

            dpg.add_separator(parent=header_tag)

            # ---- Behaviors -------------------------------------------
            behaviors_str = ", ".join(mat.behaviors)
            dpg.add_input_text(
                label="Behaviors",
                default_value=behaviors_str,
                hint="comma-separated, e.g. solid, flammable",
                callback=lambda s, app_data, idx=index: self._on_behaviors_change(idx, app_data),
                parent=header_tag,
            )

            dpg.add_separator(parent=header_tag)

            # ---- Delete button ----------------------------------------
            dpg.add_button(
                label="Delete",
                callback=lambda s, app_data, idx=index: self._delete_material(idx),
                parent=header_tag,
            )

    # ------------------------------------------------------------------
    # Callbacks — mutate the MaterialMap in place
    # ------------------------------------------------------------------

    def _on_name_change(self, index: int, value: str) -> None:
        if self._material_map is None:
            return
        self._material_map._materials[index].name = value

    def _on_color_change(self, index: int, channel: str, bound: int, value: int) -> None:
        """Update one bound (0=min, 1=max) of one channel (r/g/b)."""
        if self._material_map is None:
            return
        cr = self._material_map._materials[index].color_range
        current = list(getattr(cr, channel))
        current[bound] = value
        setattr(cr, channel, tuple(current))

    def _on_alpha_change(self, index: int, value: str) -> None:
        if self._material_map is None:
            return
        self._material_map._materials[index].alpha_meaning = value

    def _on_behaviors_change(self, index: int, value: str) -> None:
        if self._material_map is None:
            return
        behaviors = [b.strip() for b in value.split(",") if b.strip()]
        self._material_map._materials[index].behaviors = behaviors

    # ------------------------------------------------------------------
    # Structural mutations — require a full panel rebuild
    # ------------------------------------------------------------------

    def _add_material(self) -> None:
        from playslap.material.map import ColorRange, MaterialDef

        if self._material_map is None:
            return
        new_mat = MaterialDef(
            name="new_material",
            color_range=ColorRange(),
            alpha_meaning="opacity",
            behaviors=[],
        )
        self._material_map._materials.append(new_mat)
        self._refresh()

    def _delete_material(self, index: int) -> None:
        if self._material_map is None:
            return
        del self._material_map._materials[index]
        self._refresh()

    def _refresh(self) -> None:
        """Wipe the entry group and rebuild all material rows."""
        import dearpygui.dearpygui as dpg

        # Guard: panel may not have been built yet (set_material_map called early).
        try:
            dpg.does_item_exist(self._panel_tag)
        except Exception:
            return

        if not dpg.does_item_exist(self._panel_tag):
            return

        dpg.delete_item(self._panel_tag, children_only=True)
        self._build_entries()
