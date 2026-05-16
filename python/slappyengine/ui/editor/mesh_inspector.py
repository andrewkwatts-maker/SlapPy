from __future__ import annotations


class MeshInspector:
    """Property panel for 3D mesh + PBR material settings.

    Displays sliders for the four key PbrMaterial float fields:
    metallic, roughness, emissive_strength, and ior.  Updates the
    material in real-time via DPG callbacks.

    Protocol: build(parent_tag) -> None
    """

    def __init__(self):
        self._layer = None
        self._panel_tag = "mesh_inspector_panel"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_layer(self, layer) -> None:
        """Switch which 3D layer is inspected."""
        self._layer = layer
        self._refresh()

    def build(self, parent_tag: str) -> None:
        """Build the DPG widget tree inside *parent_tag*."""
        import dearpygui.dearpygui as dpg

        with dpg.group(parent=parent_tag):
            dpg.add_text("3D Mesh Inspector", color=(180, 180, 220))
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

        if self._layer is None:
            dpg.add_text(
                "(no 3D layer selected)",
                parent=self._panel_tag,
                tag=f"{self._panel_tag}_empty",
            )
            return

        mat = getattr(self._layer, "mesh_material", None)
        if mat is None:
            dpg.add_text(
                "(no PBR material on layer)",
                parent=self._panel_tag,
                tag=f"{self._panel_tag}_no_mat",
            )
            return

        # ---- PBR material sliders ----------------------------------------

        dpg.add_text(
            "PBR Material",
            color=(160, 200, 160),
            parent=self._panel_tag,
        )
        dpg.add_separator(parent=self._panel_tag)

        # metallic  0..1
        dpg.add_slider_float(
            label="Metallic",
            tag=f"{self._panel_tag}_metallic",
            default_value=mat.metallic,
            min_value=0.0,
            max_value=1.0,
            callback=self._make_float_callback("metallic"),
            parent=self._panel_tag,
        )

        # roughness  0..1
        dpg.add_slider_float(
            label="Roughness",
            tag=f"{self._panel_tag}_roughness",
            default_value=mat.roughness,
            min_value=0.0,
            max_value=1.0,
            callback=self._make_float_callback("roughness"),
            parent=self._panel_tag,
        )

        # emissive_strength  0..5
        dpg.add_slider_float(
            label="Emissive Strength",
            tag=f"{self._panel_tag}_emissive_strength",
            default_value=mat.emissive_strength,
            min_value=0.0,
            max_value=5.0,
            callback=self._make_float_callback("emissive_strength"),
            parent=self._panel_tag,
        )

        # ior  1..3
        dpg.add_slider_float(
            label="IOR",
            tag=f"{self._panel_tag}_ior",
            default_value=mat.ior,
            min_value=1.0,
            max_value=3.0,
            callback=self._make_float_callback("ior"),
            parent=self._panel_tag,
        )

    # ------------------------------------------------------------------
    # Callback factory
    # ------------------------------------------------------------------

    def _make_float_callback(self, attr_name: str):
        """Return a DPG callback that writes layer.mesh_material.<attr_name>."""
        _attr = attr_name

        def _cb(sender, app_data, user_data):
            if self._layer is None:
                return
            mat = getattr(self._layer, "mesh_material", None)
            if mat is None:
                return
            try:
                setattr(mat, _attr, app_data)
            except (AttributeError, TypeError):
                pass

        return _cb
