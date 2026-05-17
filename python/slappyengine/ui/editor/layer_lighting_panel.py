from __future__ import annotations

_LIGHTING_MODES = ["none", "global", "local", "cross"]


class LayerLightingPanel:
    """Per-layer lighting configuration panel.

    Displays:
    - Lighting mode radio buttons (none / global / local / cross)
    - Ambient colour picker and intensity slider
    - List of attached lights with Remove buttons
    - Add PointLight button

    Protocol: build(parent_tag) -> None
    """

    def __init__(self):
        self._layer = None
        self._panel_tag = "layer_lighting_panel"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_layer(self, layer) -> None:
        """Switch which layer's lighting context is displayed."""
        self._layer = layer
        self._refresh()

    def build(self, parent_tag: str) -> None:
        """Build the DPG widget tree inside *parent_tag*."""
        import dearpygui.dearpygui as dpg

        with dpg.group(parent=parent_tag):
            dpg.add_text("Layer Lighting", color=(220, 200, 140))
            dpg.add_separator()
            dpg.add_group(tag=self._panel_tag)

        self._refresh()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        """Delete and rebuild the panel's content for the current layer."""
        import dearpygui.dearpygui as dpg

        if not dpg.does_item_exist(self._panel_tag):
            return

        dpg.delete_item(self._panel_tag, children_only=True)

        lighting = None
        if self._layer is not None:
            lighting = getattr(self._layer, "lighting", None)

        if lighting is None:
            dpg.add_text(
                "(no lighting context)",
                parent=self._panel_tag,
                tag=f"{self._panel_tag}_empty",
            )
            return

        # ---- Lighting mode -----------------------------------------------

        dpg.add_text(
            "Lighting Mode:",
            parent=self._panel_tag,
        )

        current_mode = getattr(lighting, "mode", "local")
        # dpg.add_radio_button expects the default_value to be the item string.
        safe_mode = current_mode if current_mode in _LIGHTING_MODES else "local"

        dpg.add_radio_button(
            items=_LIGHTING_MODES,
            default_value=safe_mode,
            horizontal=True,
            callback=self._on_mode_change,
            parent=self._panel_tag,
            tag=f"{self._panel_tag}_mode_radio",
        )

        dpg.add_separator(parent=self._panel_tag)

        # ---- Ambient --------------------------------------------------------

        dpg.add_text(
            "Ambient",
            color=(200, 200, 200),
            parent=self._panel_tag,
        )

        ambient_color = getattr(lighting, "ambient_color", (0.15, 0.15, 0.20))
        # color_edit expects values in 0..255 for integers or 0.0..1.0 floats.
        # PbrMaterial and LightingContext store floats in [0, 1]; pass as-is
        # (dpg.add_color_edit accepts 0.0-1.0 when no_alpha is not set and the
        # list is length 3 with float members if we use the normalized flag).
        # We use a plain tuple converted to list; DPG 2.x treats 3-element float
        # sequences as RGB normalized colours automatically.
        dpg.add_color_edit(
            label="Ambient Color",
            tag=f"{self._panel_tag}_ambient_color",
            default_value=list(ambient_color),
            no_alpha=True,
            callback=self._on_ambient_color_change,
            parent=self._panel_tag,
        )

        ambient_intensity = getattr(lighting, "ambient_intensity", 0.15)
        dpg.add_slider_float(
            label="Ambient Intensity",
            tag=f"{self._panel_tag}_ambient_intensity",
            default_value=ambient_intensity,
            min_value=0.0,
            max_value=4.0,
            callback=self._on_ambient_intensity_change,
            parent=self._panel_tag,
        )

        dpg.add_separator(parent=self._panel_tag)

        # ---- Lights list ----------------------------------------------------

        dpg.add_text(
            "Lights:",
            color=(200, 200, 200),
            parent=self._panel_tag,
        )

        lights = getattr(lighting, "lights", [])
        if lights:
            dpg.add_group(
                tag=f"{self._panel_tag}_lights_list",
                parent=self._panel_tag,
            )
            for i, light in enumerate(list(lights)):
                self._build_light_row(i, light)
        else:
            dpg.add_text(
                "(no lights)",
                parent=self._panel_tag,
                tag=f"{self._panel_tag}_no_lights",
            )

        dpg.add_separator(parent=self._panel_tag)

        # ---- Add PointLight button ------------------------------------------

        dpg.add_button(
            label="Add PointLight",
            callback=self._on_add_point_light,
            parent=self._panel_tag,
            tag=f"{self._panel_tag}_add_btn",
        )

    # ------------------------------------------------------------------
    # Light row construction
    # ------------------------------------------------------------------

    def _build_light_row(self, index: int, light) -> None:
        """Add a single row: '[TypeName]  [Remove]'."""
        import dearpygui.dearpygui as dpg

        type_name = type(light).__name__
        row_tag = f"{self._panel_tag}_light_row_{index}"

        with dpg.group(
            horizontal=True,
            tag=row_tag,
            parent=f"{self._panel_tag}_lights_list",
        ):
            dpg.add_text(type_name)
            dpg.add_button(
                label="Remove",
                callback=self._make_remove_callback(light),
                width=70,
            )

    # ------------------------------------------------------------------
    # Callback factories
    # ------------------------------------------------------------------

    def _make_remove_callback(self, light):
        """Return a DPG callback that removes *light* and refreshes."""
        _light = light

        def _cb(sender, app_data, user_data):
            if self._layer is None:
                return
            lighting = getattr(self._layer, "lighting", None)
            if lighting is None:
                return
            try:
                lighting.remove_light(_light)
            except (ValueError, AttributeError):
                pass
            self._refresh()

        return _cb

    # ------------------------------------------------------------------
    # Callbacks — mutate LightingContext in place
    # ------------------------------------------------------------------

    def _on_mode_change(self, sender, app_data, user_data) -> None:
        if self._layer is None:
            return
        lighting = getattr(self._layer, "lighting", None)
        if lighting is None:
            return
        try:
            lighting.mode = app_data
        except AttributeError:
            pass

    def _on_ambient_color_change(self, sender, app_data, user_data) -> None:
        """app_data is a list [r, g, b] or [r, g, b, a] from DPG color_edit."""
        if self._layer is None:
            return
        lighting = getattr(self._layer, "lighting", None)
        if lighting is None:
            return
        try:
            # Normalise to a 3-tuple of floats in [0, 1]; DPG may return 0-255
            # integers when display_type is not explicitly set.
            raw = list(app_data)[:3]
            if any(v > 1.0 for v in raw):
                # Integer range — convert to float
                raw = [v / 255.0 for v in raw]
            lighting.ambient_color = tuple(raw)
        except (AttributeError, TypeError):
            pass

    def _on_ambient_intensity_change(self, sender, app_data, user_data) -> None:
        if self._layer is None:
            return
        lighting = getattr(self._layer, "lighting", None)
        if lighting is None:
            return
        try:
            lighting.ambient_intensity = float(app_data)
        except (AttributeError, TypeError):
            pass

    def _on_add_point_light(self, sender=None, app_data=None, user_data=None) -> None:
        if self._layer is None:
            return
        lighting = getattr(self._layer, "lighting", None)
        if lighting is None:
            return
        try:
            from slappyengine.lighting import PointLight
            lighting.add_light(
                PointLight(position=(0.0, 0.0), color=(1.0, 1.0, 1.0), radius=200.0)
            )
        except Exception:
            pass
        self._refresh()
