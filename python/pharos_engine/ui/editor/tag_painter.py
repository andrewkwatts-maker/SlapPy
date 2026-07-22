from __future__ import annotations


class TagPainter:
    """
    Tag painter tool — assigns per-pixel tag bits to an asset's data layer.

    Supports three modes:
    1. Color-range flood fill: match all pixels in color range -> assign tag
    2. Brush paint: assign tag to pixels near mouse position (UV coords)
    3. Mask import: load a grayscale PNG; white pixels -> assign tag

    The tag is OR'd into the pixel's existing tag field (bitmask OR, not replace).

    Protocol: build(parent_tag) -> None
    """

    _PAINT_MODES = ["Color Range", "Brush", "Mask Import"]

    def __init__(self):
        self._asset = None
        self._tag_registry = None
        self._selected_tag: str | None = None
        self._paint_mode: str = "Color Range"
        self._brush_radius: float = 0.05  # fraction of asset size
        # Color range for flood fill
        self._cr_r = [0, 255]
        self._cr_g = [0, 255]
        self._cr_b = [0, 255]
        # Mask import
        self._mask_path: str = ""
        # DPG tag for the refreshable body group
        self._panel_tag = "tag_painter_body"
        # DPG tags for dynamically shown/hidden mode panels
        self._cr_group_tag = "tag_painter_cr_group"
        self._brush_group_tag = "tag_painter_brush_group"
        self._mask_group_tag = "tag_painter_mask_group"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_asset(self, asset, tag_registry) -> None:
        """Switch the active asset and tag registry, then refresh the UI."""
        self._asset = asset
        self._tag_registry = tag_registry
        self._refresh()

    def build(self, parent_tag) -> None:
        """Build the DPG widget tree inside parent_tag."""
        import dearpygui.dearpygui as dpg

        # Header
        with dpg.group(horizontal=True, parent=parent_tag):
            dpg.add_text("Tag Painter")

        dpg.add_separator(parent=parent_tag)

        # Refreshable body group
        dpg.add_group(tag=self._panel_tag, parent=parent_tag)

        if self._asset is not None and self._tag_registry is not None:
            self._build_body()

    # ------------------------------------------------------------------
    # Body construction
    # ------------------------------------------------------------------

    def _build_body(self) -> None:
        """Populate self._panel_tag with all painter controls."""
        import dearpygui.dearpygui as dpg

        parent = self._panel_tag

        # ---- Tag selector ----
        tag_names = list(self._tag_registry.all_tags().keys())
        default_tag = self._selected_tag if self._selected_tag in tag_names else (
            tag_names[0] if tag_names else ""
        )
        self._selected_tag = default_tag or None

        dpg.add_combo(
            label="Tag",
            items=tag_names,
            default_value=default_tag,
            callback=self._on_tag_changed,
            parent=parent,
        )

        # ---- Paint mode selector ----
        dpg.add_combo(
            label="Mode",
            items=self._PAINT_MODES,
            default_value=self._paint_mode,
            callback=self._on_mode_changed,
            parent=parent,
        )

        dpg.add_separator(parent=parent)

        # ---- Color Range controls ----
        with dpg.group(tag=self._cr_group_tag, parent=parent,
                       show=(self._paint_mode == "Color Range")):
            dpg.add_text("Color Range", parent=self._cr_group_tag)

            # R channel
            with dpg.group(horizontal=True, parent=self._cr_group_tag):
                dpg.add_text("R:", parent=self._cr_group_tag)
                dpg.add_drag_int(
                    label="min##r",
                    tag="tp_cr_r_min",
                    default_value=self._cr_r[0],
                    min_value=0,
                    max_value=255,
                    parent=self._cr_group_tag,
                    callback=lambda s, a: self._cr_r.__setitem__(0, a),
                )
                dpg.add_drag_int(
                    label="max##r",
                    tag="tp_cr_r_max",
                    default_value=self._cr_r[1],
                    min_value=0,
                    max_value=255,
                    parent=self._cr_group_tag,
                    callback=lambda s, a: self._cr_r.__setitem__(1, a),
                )

            # G channel
            with dpg.group(horizontal=True, parent=self._cr_group_tag):
                dpg.add_text("G:", parent=self._cr_group_tag)
                dpg.add_drag_int(
                    label="min##g",
                    tag="tp_cr_g_min",
                    default_value=self._cr_g[0],
                    min_value=0,
                    max_value=255,
                    parent=self._cr_group_tag,
                    callback=lambda s, a: self._cr_g.__setitem__(0, a),
                )
                dpg.add_drag_int(
                    label="max##g",
                    tag="tp_cr_g_max",
                    default_value=self._cr_g[1],
                    min_value=0,
                    max_value=255,
                    parent=self._cr_group_tag,
                    callback=lambda s, a: self._cr_g.__setitem__(1, a),
                )

            # B channel
            with dpg.group(horizontal=True, parent=self._cr_group_tag):
                dpg.add_text("B:", parent=self._cr_group_tag)
                dpg.add_drag_int(
                    label="min##b",
                    tag="tp_cr_b_min",
                    default_value=self._cr_b[0],
                    min_value=0,
                    max_value=255,
                    parent=self._cr_group_tag,
                    callback=lambda s, a: self._cr_b.__setitem__(0, a),
                )
                dpg.add_drag_int(
                    label="max##b",
                    tag="tp_cr_b_max",
                    default_value=self._cr_b[1],
                    min_value=0,
                    max_value=255,
                    parent=self._cr_group_tag,
                    callback=lambda s, a: self._cr_b.__setitem__(1, a),
                )

        # ---- Brush controls ----
        with dpg.group(tag=self._brush_group_tag, parent=parent,
                       show=(self._paint_mode == "Brush")):
            dpg.add_text("Brush", parent=self._brush_group_tag)
            dpg.add_slider_float(
                label="Radius##brush",
                tag="tp_brush_radius",
                default_value=self._brush_radius,
                min_value=0.01,
                max_value=0.5,
                parent=self._brush_group_tag,
                callback=lambda s, a: setattr(self, "_brush_radius", a),
            )

        # ---- Mask Import controls ----
        with dpg.group(tag=self._mask_group_tag, parent=parent,
                       show=(self._paint_mode == "Mask Import")):
            dpg.add_text("Mask Import", parent=self._mask_group_tag)
            dpg.add_input_text(
                label="Path##mask",
                tag="tp_mask_path",
                default_value=self._mask_path,
                parent=self._mask_group_tag,
                callback=lambda s, a: setattr(self, "_mask_path", a),
            )
            dpg.add_button(
                label="Load Mask",
                parent=self._mask_group_tag,
                callback=self._load_mask,
            )

        dpg.add_separator(parent=parent)

        # ---- Action buttons ----
        with dpg.group(horizontal=True, parent=parent):
            dpg.add_button(
                label="Apply Tags",
                callback=self._apply_tags,
            )
            dpg.add_button(
                label="Clear Tags for Selection",
                callback=self._clear_tags,
            )

    # ------------------------------------------------------------------
    # DPG callbacks
    # ------------------------------------------------------------------

    def _on_tag_changed(self, sender, app_data, user_data=None) -> None:
        self._selected_tag = app_data if app_data else None

    def _on_mode_changed(self, sender, app_data, user_data=None) -> None:
        import dearpygui.dearpygui as dpg

        self._paint_mode = app_data

        # Show/hide the relevant mode group without a full rebuild
        for tag, mode in (
            (self._cr_group_tag, "Color Range"),
            (self._brush_group_tag, "Brush"),
            (self._mask_group_tag, "Mask Import"),
        ):
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, show=(app_data == mode))

    # ------------------------------------------------------------------
    # Tag application
    # ------------------------------------------------------------------

    def _apply_tags(self, sender=None, app_data=None, user_data=None) -> None:
        """Apply the selected tag to matching pixels."""
        if self._asset is None or self._selected_tag is None:
            return
        if self._tag_registry is None:
            return
        if self._selected_tag not in self._tag_registry:
            return
        tag_bit = self._tag_registry[self._selected_tag]  # bitmask, e.g. 0b0001

        if self._paint_mode == "Color Range":
            self._apply_color_range(tag_bit)
        elif self._paint_mode == "Brush":
            self._apply_brush(tag_bit)
        elif self._paint_mode == "Mask Import":
            self._apply_mask(tag_bit)

    def _apply_color_range(self, tag_bit: int) -> None:
        """OR tag_bit into pixels matching the color range across all layers."""
        import numpy as np

        r_lo, r_hi = self._cr_r
        g_lo, g_hi = self._cr_g
        b_lo, b_hi = self._cr_b

        for layer in self._asset.layers:
            if layer._image_data is None:
                continue
            img = layer._image_data  # (H, W, 4) uint8
            mask = (
                (img[:, :, 0] >= r_lo) & (img[:, :, 0] <= r_hi) &
                (img[:, :, 1] >= g_lo) & (img[:, :, 1] <= g_hi) &
                (img[:, :, 2] >= b_lo) & (img[:, :, 2] <= b_hi)
            )
            self._or_tag_into_layer(layer, mask, tag_bit)

    def _apply_brush(self, tag_bit: int) -> None:
        """OR tag_bit into pixels within brush_radius of the last mouse UV position.

        UV coordinates are not tracked here; this method operates on _image_data
        using a stored (u, v) centre set by the viewport (default 0.5, 0.5 when
        no position has been provided).  Integration with the viewport's mouse
        position is expected to call set_brush_uv() before Apply Tags.
        """
        import numpy as np

        u = getattr(self, "_brush_u", 0.5)
        v = getattr(self, "_brush_v", 0.5)

        for layer in self._asset.layers:
            if layer._image_data is None:
                continue
            h, w = layer._image_data.shape[:2]
            # Pixel coordinates of brush centre
            cx = u * w
            cy = v * h
            # Radius in pixels (use the smaller dimension as reference)
            r_px = self._brush_radius * min(w, h)
            ys, xs = np.ogrid[:h, :w]
            mask = (xs - cx) ** 2 + (ys - cy) ** 2 <= r_px ** 2
            self._or_tag_into_layer(layer, mask, tag_bit)

    def _apply_mask(self, tag_bit: int) -> None:
        """OR tag_bit into pixels where the loaded grayscale mask is white (>= 128)."""
        import numpy as np
        from PIL import Image

        path = getattr(self, "_loaded_mask_path", None)
        mask_arr = getattr(self, "_loaded_mask_arr", None)
        if mask_arr is None:
            return

        for layer in self._asset.layers:
            if layer._image_data is None:
                continue
            h, w = layer._image_data.shape[:2]
            # Resize mask to layer dimensions if needed
            if mask_arr.shape[:2] != (h, w):
                mask_img = Image.fromarray(mask_arr).resize((w, h), Image.NEAREST)
                resized = np.asarray(mask_img)
            else:
                resized = mask_arr
            mask = resized >= 128
            self._or_tag_into_layer(layer, mask, tag_bit)

    def _or_tag_into_layer(self, layer, mask, tag_bit: int) -> None:
        """OR tag_bit into layer._data_array where mask is True.

        The tag channel index within _data_array is not yet known without
        StructRegistry introspection; this stores the result in a separate
        per-layer tag overlay (layer._tag_overlay) as a uint32 array until
        full StructRegistry integration is available.
        """
        import numpy as np

        if layer._image_data is None:
            return
        h, w = layer._image_data.shape[:2]

        # Initialise the tag overlay on first use
        if not hasattr(layer, "_tag_overlay") or layer._tag_overlay is None:
            layer._tag_overlay = np.zeros((h, w), dtype=np.uint32)

        # Grow overlay if layer size changed
        if layer._tag_overlay.shape != (h, w):
            layer._tag_overlay = np.zeros((h, w), dtype=np.uint32)

        layer._tag_overlay[mask] |= np.uint32(tag_bit)

    # ------------------------------------------------------------------
    # Tag clearing
    # ------------------------------------------------------------------

    def _clear_tags(self, sender=None, app_data=None, user_data=None) -> None:
        """Clear the selected tag bit from all pixels on all layers."""
        if self._asset is None or self._selected_tag is None:
            return
        if self._tag_registry is None:
            return
        if self._selected_tag not in self._tag_registry:
            return
        tag_bit = self._tag_registry[self._selected_tag]
        clear_mask = ~(tag_bit)  # bitwise NOT of the tag bitmask

        import numpy as np

        for layer in self._asset.layers:
            overlay = getattr(layer, "_tag_overlay", None)
            if overlay is None:
                continue
            layer._tag_overlay = (overlay.astype(np.uint32) & np.uint32(clear_mask))

    # ------------------------------------------------------------------
    # Brush UV setter (called by viewport integration)
    # ------------------------------------------------------------------

    def set_brush_uv(self, u: float, v: float) -> None:
        """Set the brush centre in UV space (0.0–1.0).  Called by the viewport."""
        self._brush_u = max(0.0, min(1.0, u))
        self._brush_v = max(0.0, min(1.0, v))

    # ------------------------------------------------------------------
    # Mask loading
    # ------------------------------------------------------------------

    def _load_mask(self, sender=None, app_data=None, user_data=None) -> None:
        """Load the grayscale PNG from self._mask_path into self._loaded_mask_arr."""
        import dearpygui.dearpygui as dpg
        import numpy as np
        from PIL import Image
        from pathlib import Path

        # Sync path widget value in case the callback hasn't fired yet
        if dpg.does_item_exist("tp_mask_path"):
            self._mask_path = dpg.get_value("tp_mask_path")

        path = Path(self._mask_path)
        if not path.is_file():
            return

        try:
            img = Image.open(path).convert("L")  # grayscale
            self._loaded_mask_arr = np.asarray(img, dtype=np.uint8)
            self._loaded_mask_path = str(path)
        except Exception:
            self._loaded_mask_arr = None
            self._loaded_mask_path = None

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        """Delete and rebuild the DPG widget body."""
        import dearpygui.dearpygui as dpg

        if not dpg.does_item_exist(self._panel_tag):
            return

        dpg.delete_item(self._panel_tag, children_only=True)

        if self._asset is not None and self._tag_registry is not None:
            self._build_body()
