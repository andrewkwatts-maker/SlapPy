"""slappyengine.ui.editor.deform_panel — Editor panel for DeformableLayerComponent.

Two panels are provided:

DeformPanel
    Full inspector for all deformation settings.  Exposes every configurable
    field of DeformableLayerComponent (and its backing MaterialConfig) as an
    appropriate DPG widget.  Conditional visibility is handled automatically:
    - Spring Decay slider only when Decay Mode == CONSTANT
    - Decay Curve editor only when Decay Mode == CURVE
    - Crack Count / Crack Length only when Crack Mode != NONE
    - Repair Rate only when Repair Mode == AUTO or AUTO_CURVE

ZoneEditorPanel
    List-based zone manager.  Shows all zones attached to the component,
    allows adding / removing zones, and edits each zone's rect, threshold,
    material, and strength_scale in place.  A "Preview Zones" button triggers
    an overlay render callback (supplied externally via set_preview_callback).

Protocol
--------
Both panels follow the same two-step protocol used by all editor panels in
this package:

    panel = DeformPanel()
    panel.build("right_sidebar")     # call once after dpg.create_context()
    panel.set_component(component)   # call whenever selection changes
"""
from __future__ import annotations

from typing import Callable


# ---------------------------------------------------------------------------
# Helpers shared by both panels
# ---------------------------------------------------------------------------

def _enum_items(enum_cls) -> list[str]:
    """Return a list of enum *value* strings for use as DPG combo items."""
    return [m.value for m in enum_cls]


def _enum_value(field) -> str:
    """Return the string value of an enum field, or the field itself if str."""
    if hasattr(field, "value"):
        return field.value
    return str(field)


# ---------------------------------------------------------------------------
# DeformPanel
# ---------------------------------------------------------------------------

class DeformPanel:
    """Inspector panel for all DeformableLayerComponent settings.

    Sections
    --------
    Material
        Material Preset dropdown (auto-fills all fields on change).
    Simulation
        Sim Mode / Decay Mode / Spring Decay / Decay Curve.
    Thresholds
        Elastic Threshold / Settle Threshold / Settling Ramp Rate.
    Cracks
        Crack Mode / Crack Count / Crack Length (crack count & length hidden
        when Crack Mode == NONE).
    Destruction
        Destroy Mode.
    Physics
        Physics Coupling.
    Repair
        Repair Mode / Repair Rate (rate hidden unless AUTO or AUTO_CURVE).
    """

    def __init__(self) -> None:
        self._comp = None
        self._panel_tag = "deform_panel"
        # Track DPG tags for conditional widgets so we can show/hide them.
        self._tags: dict[str, str | int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_component(self, component) -> None:
        """Bind a DeformableLayerComponent and refresh all widgets."""
        self._comp = component
        self._refresh()

    def build(self, parent_tag: str) -> None:
        """Create the panel container inside *parent_tag*.

        Must be called after ``dpg.create_context()`` and before the render
        loop.  Subsequent :meth:`set_component` calls repopulate the container.
        """
        import dearpygui.dearpygui as dpg

        with dpg.child_window(
            tag=self._panel_tag,
            parent=parent_tag,
            border=False,
            autosize_x=True,
            height=-1,
        ):
            dpg.add_text("Deform Settings", color=(200, 180, 120))
            dpg.add_separator()

        if self._comp is not None:
            self._refresh()

    # ------------------------------------------------------------------
    # Internal — full rebuild
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        import dearpygui.dearpygui as dpg

        if not dpg.does_item_exist(self._panel_tag):
            return

        self._tags.clear()
        dpg.delete_item(self._panel_tag, children_only=True)

        dpg.add_text("Deform Settings", color=(200, 180, 120), parent=self._panel_tag)
        dpg.add_separator(parent=self._panel_tag)

        if self._comp is None:
            dpg.add_text("(no component selected)", parent=self._panel_tag)
            return

        self._build_material_section()
        self._build_simulation_section()
        self._build_thresholds_section()
        self._build_cracks_section()
        self._build_destruction_section()
        self._build_physics_section()
        self._build_repair_section()

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_material_section(self) -> None:
        import dearpygui.dearpygui as dpg
        from slappyengine.deform_modes import MaterialPreset, list_materials

        with dpg.collapsing_header(
            label="Material",
            default_open=True,
            parent=self._panel_tag,
            tag=f"{self._panel_tag}_sec_material",
        ):
            # All known material names: built-in enums + custom registered ones
            all_names = list_materials()
            current_preset = getattr(self._comp, "material_preset", None)
            current_name = _enum_value(current_preset) if current_preset is not None else "custom"

            tag = f"{self._panel_tag}_material_preset"
            self._tags["material_preset"] = tag
            dpg.add_combo(
                label="Material Preset",
                items=all_names,
                default_value=current_name,
                callback=self._on_material_preset_change,
                parent=f"{self._panel_tag}_sec_material",
                tag=tag,
            )

    def _build_simulation_section(self) -> None:
        import dearpygui.dearpygui as dpg
        from slappyengine.deform_modes import DeformSimMode, DecayMode

        sec = f"{self._panel_tag}_sec_sim"
        with dpg.collapsing_header(
            label="Simulation",
            default_open=True,
            parent=self._panel_tag,
            tag=sec,
        ):
            # Sim Mode
            sim_items = _enum_items(DeformSimMode)
            current_sim = _enum_value(getattr(self._comp, "sim_mode", DeformSimMode.COLLISION_TRIGGERED))
            tag_sim = f"{self._panel_tag}_sim_mode"
            self._tags["sim_mode"] = tag_sim
            dpg.add_combo(
                label="Sim Mode",
                items=sim_items,
                default_value=current_sim,
                callback=self._on_sim_mode_change,
                parent=sec,
                tag=tag_sim,
            )

            dpg.add_separator(parent=sec)

            # Decay Mode
            decay_items = _enum_items(DecayMode)
            current_decay = _enum_value(getattr(self._comp, "decay_mode", DecayMode.CONSTANT))
            tag_decay = f"{self._panel_tag}_decay_mode"
            self._tags["decay_mode"] = tag_decay
            dpg.add_combo(
                label="Decay Mode",
                items=decay_items,
                default_value=current_decay,
                callback=self._on_decay_mode_change,
                parent=sec,
                tag=tag_decay,
            )

            # Spring Decay slider — only visible when decay_mode == CONSTANT
            spring_val = float(getattr(self._comp, "spring_decay", 0.94))
            tag_spring = f"{self._panel_tag}_spring_decay"
            self._tags["spring_decay"] = tag_spring
            spring_visible = (current_decay == DecayMode.CONSTANT.value)
            dpg.add_slider_float(
                label="Spring Decay",
                default_value=spring_val,
                min_value=0.0,
                max_value=1.0,
                callback=self._on_spring_decay_change,
                parent=sec,
                tag=tag_spring,
                show=spring_visible,
            )

            # Decay Curve editor — only visible when decay_mode == CURVE
            tag_curve_grp = f"{self._panel_tag}_decay_curve_grp"
            self._tags["decay_curve_grp"] = tag_curve_grp
            curve_visible = (current_decay == DecayMode.CURVE.value)
            with dpg.group(
                parent=sec,
                tag=tag_curve_grp,
                show=curve_visible,
            ):
                self._build_decay_curve_editor(tag_curve_grp)

    def _build_decay_curve_editor(self, parent: str) -> None:
        """Build the inline piecewise-curve editor for decay_curve."""
        import dearpygui.dearpygui as dpg

        # Read current curve from component; default empty
        curve: list[tuple[float, float]] = getattr(self._comp, "_decay_curve_data", None) or []
        # Try to read from a DeformController if attached
        ctrl = getattr(self._comp, "_controller", None)
        if ctrl is not None and hasattr(ctrl, "decay_curve"):
            curve = list(ctrl.decay_curve)

        dpg.add_text("Decay Curve  (time s, rate)", parent=parent, color=(180, 180, 180))

        tag_rows = f"{self._panel_tag}_curve_rows"
        self._tags["curve_rows"] = tag_rows
        dpg.add_group(tag=tag_rows, parent=parent)

        for i, (t, r) in enumerate(curve):
            self._build_curve_point_row(tag_rows, i, t, r)

        dpg.add_button(
            label="+ Add Point",
            callback=self._on_add_curve_point,
            parent=parent,
            tag=f"{self._panel_tag}_curve_add_btn",
        )

    def _build_curve_point_row(self, parent: str, index: int, t: float, r: float) -> None:
        """Add one (time, rate) row with a Remove button."""
        import dearpygui.dearpygui as dpg

        row_tag = f"{self._panel_tag}_curve_row_{index}"
        with dpg.group(horizontal=True, parent=parent, tag=row_tag):
            dpg.add_drag_float(
                label="t",
                default_value=t,
                speed=0.01,
                min_value=0.0,
                max_value=60.0,
                width=80,
                callback=self._make_curve_point_callback(index, field="time"),
                tag=f"{row_tag}_t",
            )
            dpg.add_drag_float(
                label="rate",
                default_value=r,
                speed=0.001,
                min_value=0.0,
                max_value=1.0,
                width=80,
                callback=self._make_curve_point_callback(index, field="rate"),
                tag=f"{row_tag}_r",
            )
            dpg.add_button(
                label="X",
                width=24,
                callback=self._make_remove_curve_point_callback(index),
                tag=f"{row_tag}_remove",
            )

    def _build_thresholds_section(self) -> None:
        import dearpygui.dearpygui as dpg

        sec = f"{self._panel_tag}_sec_thresh"
        with dpg.collapsing_header(
            label="Thresholds",
            default_open=True,
            parent=self._panel_tag,
            tag=sec,
        ):
            elastic_val = float(getattr(self._comp, "elastic_threshold", 80.0))
            tag_et = f"{self._panel_tag}_elastic_threshold"
            self._tags["elastic_threshold"] = tag_et
            dpg.add_input_float(
                label="Elastic Threshold",
                default_value=elastic_val,
                step=1.0,
                step_fast=10.0,
                callback=self._on_elastic_threshold_change,
                parent=sec,
                tag=tag_et,
            )

            settle_val = float(getattr(self._comp, "settle_threshold", 0.5))
            tag_st = f"{self._panel_tag}_settle_threshold"
            self._tags["settle_threshold"] = tag_st
            dpg.add_slider_float(
                label="Settle Threshold",
                default_value=settle_val,
                min_value=0.0,
                max_value=5.0,
                callback=self._on_settle_threshold_change,
                parent=sec,
                tag=tag_st,
            )

            ramp_val = float(getattr(self._comp, "settling_ramp_rate", 4.0))
            tag_ramp = f"{self._panel_tag}_settling_ramp_rate"
            self._tags["settling_ramp_rate"] = tag_ramp
            dpg.add_slider_float(
                label="Settling Ramp Rate",
                default_value=ramp_val,
                min_value=0.1,
                max_value=30.0,
                callback=self._on_settling_ramp_rate_change,
                parent=sec,
                tag=tag_ramp,
            )

    def _build_cracks_section(self) -> None:
        import dearpygui.dearpygui as dpg
        from slappyengine.deform_modes import CrackMode

        sec = f"{self._panel_tag}_sec_cracks"
        with dpg.collapsing_header(
            label="Cracks",
            default_open=True,
            parent=self._panel_tag,
            tag=sec,
        ):
            crack_items = _enum_items(CrackMode)
            # Read crack_mode from component's material config or direct attr
            current_crack = _enum_value(
                getattr(self._comp, "crack_mode", CrackMode.NONE)
            )
            # If component doesn't have crack_mode, fall back to its material config
            if current_crack == _enum_value(CrackMode.NONE) and hasattr(self._comp, "material_preset"):
                preset = getattr(self._comp, "material_preset", None)
                if preset is not None:
                    from slappyengine.deform_modes import MATERIAL_CONFIGS, MaterialPreset
                    try:
                        mat_enum = MaterialPreset(preset.value if hasattr(preset, "value") else preset)
                        cfg = MATERIAL_CONFIGS.get(mat_enum)
                        if cfg is not None:
                            current_crack = _enum_value(cfg.crack_mode)
                    except (ValueError, AttributeError):
                        pass

            tag_cm = f"{self._panel_tag}_crack_mode"
            self._tags["crack_mode"] = tag_cm
            dpg.add_combo(
                label="Crack Mode",
                items=crack_items,
                default_value=current_crack,
                callback=self._on_crack_mode_change,
                parent=sec,
                tag=tag_cm,
            )

            cracks_visible = (current_crack != CrackMode.NONE.value)

            tag_cc = f"{self._panel_tag}_crack_count"
            self._tags["crack_count"] = tag_cc
            crack_count_val = int(getattr(self._comp, "crack_count", 6))
            dpg.add_slider_int(
                label="Crack Count",
                default_value=crack_count_val,
                min_value=2,
                max_value=16,
                callback=self._on_crack_count_change,
                parent=sec,
                tag=tag_cc,
                show=cracks_visible,
            )

            tag_cl = f"{self._panel_tag}_crack_length"
            self._tags["crack_length"] = tag_cl
            crack_len_val = float(getattr(self._comp, "crack_length_px", 40.0))
            dpg.add_slider_float(
                label="Crack Length (px)",
                default_value=crack_len_val,
                min_value=5.0,
                max_value=200.0,
                callback=self._on_crack_length_change,
                parent=sec,
                tag=tag_cl,
                show=cracks_visible,
            )

    def _build_destruction_section(self) -> None:
        import dearpygui.dearpygui as dpg
        from slappyengine.deform_modes import DestroyMode

        sec = f"{self._panel_tag}_sec_destroy"
        with dpg.collapsing_header(
            label="Destruction",
            default_open=True,
            parent=self._panel_tag,
            tag=sec,
        ):
            destroy_items = _enum_items(DestroyMode)
            current_destroy = _enum_value(getattr(self._comp, "destroy_mode", DestroyMode.PERSIST))
            tag_dm = f"{self._panel_tag}_destroy_mode"
            self._tags["destroy_mode"] = tag_dm
            dpg.add_combo(
                label="Destroy Mode",
                items=destroy_items,
                default_value=current_destroy,
                callback=self._on_destroy_mode_change,
                parent=sec,
                tag=tag_dm,
            )

    def _build_physics_section(self) -> None:
        import dearpygui.dearpygui as dpg
        from slappyengine.deform_modes import PhysicsCoupling

        sec = f"{self._panel_tag}_sec_physics"
        with dpg.collapsing_header(
            label="Physics",
            default_open=False,
            parent=self._panel_tag,
            tag=sec,
        ):
            coupling_items = _enum_items(PhysicsCoupling)
            current_coupling = _enum_value(getattr(self._comp, "physics_coupling", PhysicsCoupling.ISOLATED))
            tag_pc = f"{self._panel_tag}_physics_coupling"
            self._tags["physics_coupling"] = tag_pc
            dpg.add_combo(
                label="Physics Coupling",
                items=coupling_items,
                default_value=current_coupling,
                callback=self._on_physics_coupling_change,
                parent=sec,
                tag=tag_pc,
            )

    def _build_repair_section(self) -> None:
        import dearpygui.dearpygui as dpg
        from slappyengine.deform_modes import RepairMode

        sec = f"{self._panel_tag}_sec_repair"
        with dpg.collapsing_header(
            label="Repair",
            default_open=True,
            parent=self._panel_tag,
            tag=sec,
        ):
            repair_items = _enum_items(RepairMode)
            current_repair = _enum_value(getattr(self._comp, "repair_mode", RepairMode.NONE))
            tag_rm = f"{self._panel_tag}_repair_mode"
            self._tags["repair_mode"] = tag_rm
            dpg.add_combo(
                label="Repair Mode",
                items=repair_items,
                default_value=current_repair,
                callback=self._on_repair_mode_change,
                parent=sec,
                tag=tag_rm,
            )

            # Repair Rate — only visible when repair mode is AUTO or AUTO_CURVE
            _auto_modes = {RepairMode.AUTO.value, RepairMode.AUTO_CURVE.value}
            rate_visible = current_repair in _auto_modes
            rate_val = float(getattr(self._comp, "_repair_rate", 1.0))
            tag_rr = f"{self._panel_tag}_repair_rate"
            self._tags["repair_rate"] = tag_rr
            dpg.add_slider_float(
                label="Repair Rate",
                default_value=rate_val,
                min_value=0.0,
                max_value=10.0,
                callback=self._on_repair_rate_change,
                parent=sec,
                tag=tag_rr,
                show=rate_visible,
            )

    # ------------------------------------------------------------------
    # Callback implementations
    # ------------------------------------------------------------------

    def _on_material_preset_change(self, sender, app_data, user_data) -> None:
        """Apply a material preset and rebuild the entire panel."""
        import dearpygui.dearpygui as dpg
        from slappyengine.deform_modes import get_material, MaterialPreset

        if self._comp is None:
            return

        # Resolve config — try enum first, then custom registry
        cfg = get_material(app_data)
        if cfg is None:
            return

        # Apply all config fields to the component
        _safe_setattr(self._comp, "elastic_threshold", cfg.elastic_threshold)
        _safe_setattr(self._comp, "spring_decay", cfg.spring_decay)
        _safe_setattr(self._comp, "decay_mode", cfg.decay_mode)
        _safe_setattr(self._comp, "sim_mode", cfg.sim_mode)
        _safe_setattr(self._comp, "destroy_mode", cfg.destroy_mode)
        _safe_setattr(self._comp, "crack_mode", cfg.crack_mode)
        _safe_setattr(self._comp, "crack_count", cfg.crack_count)
        _safe_setattr(self._comp, "crack_length_px", cfg.crack_length_px)
        _safe_setattr(self._comp, "repair_mode", cfg.repair_mode)
        _safe_setattr(self._comp, "_repair_rate", cfg.repair_rate)
        _safe_setattr(self._comp, "physics_coupling", cfg.physics_coupling)
        _safe_setattr(self._comp, "settle_threshold", cfg.settle_threshold)
        _safe_setattr(self._comp, "settling_ramp_rate", cfg.settling_ramp_rate)

        # Store preset reference
        try:
            self._comp.material_preset = MaterialPreset(app_data)
        except (ValueError, AttributeError):
            pass

        # Rebuild to reflect new defaults
        self._refresh()

    def _on_sim_mode_change(self, sender, app_data, user_data) -> None:
        if self._comp is None:
            return
        from slappyengine.deform_modes import DeformSimMode
        try:
            self._comp.sim_mode = DeformSimMode(app_data)
        except (ValueError, AttributeError):
            pass

    def _on_decay_mode_change(self, sender, app_data, user_data) -> None:
        """Switch decay mode and toggle spring_decay / decay_curve visibility."""
        import dearpygui.dearpygui as dpg
        from slappyengine.deform_modes import DecayMode

        if self._comp is None:
            return
        try:
            self._comp.decay_mode = DecayMode(app_data)
        except (ValueError, AttributeError):
            pass

        is_constant = (app_data == DecayMode.CONSTANT.value)
        is_curve = (app_data == DecayMode.CURVE.value)

        if dpg.does_item_exist(self._tags.get("spring_decay", "")):
            dpg.configure_item(self._tags["spring_decay"], show=is_constant)
        if dpg.does_item_exist(self._tags.get("decay_curve_grp", "")):
            dpg.configure_item(self._tags["decay_curve_grp"], show=is_curve)

    def _on_spring_decay_change(self, sender, app_data, user_data) -> None:
        if self._comp is None:
            return
        _safe_setattr(self._comp, "spring_decay", float(app_data))

    def _on_elastic_threshold_change(self, sender, app_data, user_data) -> None:
        if self._comp is None:
            return
        _safe_setattr(self._comp, "elastic_threshold", float(app_data))

    def _on_settle_threshold_change(self, sender, app_data, user_data) -> None:
        if self._comp is None:
            return
        _safe_setattr(self._comp, "settle_threshold", float(app_data))

    def _on_settling_ramp_rate_change(self, sender, app_data, user_data) -> None:
        if self._comp is None:
            return
        _safe_setattr(self._comp, "settling_ramp_rate", float(app_data))

    def _on_crack_mode_change(self, sender, app_data, user_data) -> None:
        """Switch crack mode and toggle count/length visibility."""
        import dearpygui.dearpygui as dpg
        from slappyengine.deform_modes import CrackMode

        if self._comp is None:
            return
        try:
            _safe_setattr(self._comp, "crack_mode", CrackMode(app_data))
        except ValueError:
            pass

        show_sub = (app_data != CrackMode.NONE.value)
        for key in ("crack_count", "crack_length"):
            tag = self._tags.get(key, "")
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, show=show_sub)

    def _on_crack_count_change(self, sender, app_data, user_data) -> None:
        if self._comp is None:
            return
        _safe_setattr(self._comp, "crack_count", int(app_data))

    def _on_crack_length_change(self, sender, app_data, user_data) -> None:
        if self._comp is None:
            return
        _safe_setattr(self._comp, "crack_length_px", float(app_data))

    def _on_destroy_mode_change(self, sender, app_data, user_data) -> None:
        if self._comp is None:
            return
        from slappyengine.deform_modes import DestroyMode
        try:
            self._comp.destroy_mode = DestroyMode(app_data)
        except (ValueError, AttributeError):
            pass

    def _on_physics_coupling_change(self, sender, app_data, user_data) -> None:
        if self._comp is None:
            return
        from slappyengine.deform_modes import PhysicsCoupling
        try:
            _safe_setattr(self._comp, "physics_coupling", PhysicsCoupling(app_data))
        except ValueError:
            pass

    def _on_repair_mode_change(self, sender, app_data, user_data) -> None:
        """Switch repair mode and toggle repair rate visibility."""
        import dearpygui.dearpygui as dpg
        from slappyengine.deform_modes import RepairMode

        if self._comp is None:
            return
        try:
            _safe_setattr(self._comp, "repair_mode", RepairMode(app_data))
        except ValueError:
            pass

        _auto_modes = {RepairMode.AUTO.value, RepairMode.AUTO_CURVE.value}
        show_rate = app_data in _auto_modes
        tag = self._tags.get("repair_rate", "")
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, show=show_rate)

    def _on_repair_rate_change(self, sender, app_data, user_data) -> None:
        if self._comp is None:
            return
        _safe_setattr(self._comp, "_repair_rate", float(app_data))

    # ------------------------------------------------------------------
    # Decay curve callbacks
    # ------------------------------------------------------------------

    def _get_curve_list(self) -> list[tuple[float, float]]:
        """Return the mutable decay curve from the component or controller."""
        ctrl = getattr(self._comp, "_controller", None)
        if ctrl is not None and hasattr(ctrl, "decay_curve"):
            return ctrl.decay_curve
        return getattr(self._comp, "_decay_curve_data", [])

    def _make_curve_point_callback(self, index: int, field: str) -> Callable:
        """Return a DPG callback that edits curve[index][field]."""
        def _cb(sender, app_data, user_data):
            curve = self._get_curve_list()
            if 0 <= index < len(curve):
                t, r = curve[index]
                if field == "time":
                    curve[index] = (float(app_data), r)
                else:
                    curve[index] = (t, float(app_data))
        return _cb

    def _make_remove_curve_point_callback(self, index: int) -> Callable:
        def _cb(sender, app_data, user_data):
            curve = self._get_curve_list()
            if 0 <= index < len(curve):
                del curve[index]
            self._refresh()
        return _cb

    def _on_add_curve_point(self, sender, app_data, user_data) -> None:
        """Append a new point at the end of the decay curve and refresh."""
        curve = self._get_curve_list()
        if curve:
            last_t = curve[-1][0]
            last_r = curve[-1][1]
            curve.append((last_t + 0.5, last_r))
        else:
            curve.append((0.0, 0.94))
        self._refresh()


# ---------------------------------------------------------------------------
# ZoneEditorPanel
# ---------------------------------------------------------------------------

class ZoneEditorPanel:
    """Panel for managing named deformation zones on a DeformableLayerComponent.

    Features
    --------
    - List of zones with names shown as section headers.
    - Per-zone: name field, rect (x, y, w, h) inputs, threshold slider,
      material dropdown, strength_scale slider.
    - "Add Zone" and per-zone "Remove" buttons.
    - "Preview Zones" button calls the registered preview callback with the
      component so the viewport can overlay zone boundaries.

    Protocol
    --------
        zone_panel = ZoneEditorPanel()
        zone_panel.set_preview_callback(my_preview_fn)
        zone_panel.build("right_sidebar")
        zone_panel.set_component(component)
    """

    def __init__(self) -> None:
        self._comp = None
        self._panel_tag = "zone_editor_panel"
        self._preview_callback: Callable | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_component(self, component) -> None:
        """Bind a DeformableLayerComponent and refresh zone list."""
        self._comp = component
        self._refresh()

    def set_preview_callback(self, cb: Callable) -> None:
        """Register a callback invoked when "Preview Zones" is clicked.

        Signature: ``cb(component) -> None``
        """
        self._preview_callback = cb

    def build(self, parent_tag: str) -> None:
        """Create the panel container inside *parent_tag*."""
        import dearpygui.dearpygui as dpg

        with dpg.child_window(
            tag=self._panel_tag,
            parent=parent_tag,
            border=False,
            autosize_x=True,
            height=-1,
        ):
            dpg.add_text("Zone Editor", color=(140, 200, 180))
            dpg.add_separator()

        if self._comp is not None:
            self._refresh()

    # ------------------------------------------------------------------
    # Internal — full rebuild
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        import dearpygui.dearpygui as dpg

        if not dpg.does_item_exist(self._panel_tag):
            return

        dpg.delete_item(self._panel_tag, children_only=True)
        dpg.add_text("Zone Editor", color=(140, 200, 180), parent=self._panel_tag)
        dpg.add_separator(parent=self._panel_tag)

        if self._comp is None:
            dpg.add_text("(no component selected)", parent=self._panel_tag)
            return

        # Resolve zones list — stored as a list[ZoneConfig] on the component.
        zones = list(getattr(self._comp, "zones", []) or [])

        if zones:
            for i, zone in enumerate(zones):
                self._build_zone_section(i, zone)
        else:
            dpg.add_text("(no zones defined)", parent=self._panel_tag, color=(140, 140, 140))

        dpg.add_separator(parent=self._panel_tag)

        # Toolbar buttons
        with dpg.group(horizontal=True, parent=self._panel_tag):
            dpg.add_button(
                label="Add Zone",
                callback=self._on_add_zone,
                tag=f"{self._panel_tag}_add_btn",
            )
            dpg.add_button(
                label="Preview Zones",
                callback=self._on_preview_zones,
                tag=f"{self._panel_tag}_preview_btn",
            )

    def _build_zone_section(self, index: int, zone) -> None:
        """Build the editor rows for one zone."""
        import dearpygui.dearpygui as dpg
        from slappyengine.deform_modes import list_materials

        sec_tag = f"{self._panel_tag}_zone_{index}"
        zone_name = getattr(zone, "name", f"zone_{index}")

        with dpg.collapsing_header(
            label=zone_name,
            default_open=True,
            parent=self._panel_tag,
            tag=sec_tag,
        ):
            # Name field
            dpg.add_input_text(
                label="Name",
                default_value=zone_name,
                callback=self._make_zone_field_cb(index, "name"),
                parent=sec_tag,
                tag=f"{sec_tag}_name",
            )

            # Rect inputs (stored as zone.rect = (x, y, w, h) or individual attrs)
            rect = getattr(zone, "rect", None)
            if rect is None:
                rx = int(getattr(zone, "x", 0))
                ry = int(getattr(zone, "y", 0))
                rw = int(getattr(zone, "w", 64))
                rh = int(getattr(zone, "h", 64))
            else:
                rx, ry, rw, rh = (int(v) for v in rect[:4])

            with dpg.group(horizontal=True, parent=sec_tag, tag=f"{sec_tag}_rect_row"):
                dpg.add_input_int(
                    label="X",
                    default_value=rx,
                    width=70,
                    callback=self._make_zone_rect_cb(index, 0),
                    tag=f"{sec_tag}_rx",
                )
                dpg.add_input_int(
                    label="Y",
                    default_value=ry,
                    width=70,
                    callback=self._make_zone_rect_cb(index, 1),
                    tag=f"{sec_tag}_ry",
                )
                dpg.add_input_int(
                    label="W",
                    default_value=rw,
                    width=70,
                    callback=self._make_zone_rect_cb(index, 2),
                    tag=f"{sec_tag}_rw",
                )
                dpg.add_input_int(
                    label="H",
                    default_value=rh,
                    width=70,
                    callback=self._make_zone_rect_cb(index, 3),
                    tag=f"{sec_tag}_rh",
                )

            # Integrity threshold slider.
            # ThresholdZone (new, Phase B) names the field ``threshold``;
            # legacy ZoneConfig named it ``integrity_threshold``. Support
            # both so the panel works mid-migration.
            thresh_field = "threshold" if hasattr(zone, "threshold") else "integrity_threshold"
            thresh_val = float(getattr(zone, thresh_field, 0.0))
            dpg.add_slider_float(
                label="Integrity Threshold",
                default_value=thresh_val,
                min_value=0.0,
                max_value=1.0,
                callback=self._make_zone_field_cb(index, thresh_field, float),
                parent=sec_tag,
                tag=f"{sec_tag}_threshold",
            )

            # Material dropdown
            all_mat_names = list_materials()
            zone_material = getattr(zone, "material", None)
            current_mat = _enum_value(zone_material) if zone_material is not None else ""
            dpg.add_combo(
                label="Material",
                items=["(inherit)"] + all_mat_names,
                default_value=current_mat or "(inherit)",
                callback=self._make_zone_material_cb(index),
                parent=sec_tag,
                tag=f"{sec_tag}_material",
            )

            # Strength scale slider
            strength_val = float(getattr(zone, "strength_scale", 1.0))
            dpg.add_slider_float(
                label="Strength Scale",
                default_value=strength_val,
                min_value=0.01,
                max_value=5.0,
                callback=self._make_zone_field_cb(index, "strength_scale", float),
                parent=sec_tag,
                tag=f"{sec_tag}_strength",
            )

            # Remove button
            dpg.add_button(
                label="Remove Zone",
                callback=self._make_remove_zone_cb(index),
                parent=sec_tag,
                tag=f"{sec_tag}_remove",
            )

    # ------------------------------------------------------------------
    # Zone callback factories
    # ------------------------------------------------------------------

    def _make_zone_field_cb(self, index: int, field: str, cast=str) -> Callable:
        """Return a callback that sets ``zones[index].<field> = cast(app_data)``."""
        def _cb(sender, app_data, user_data):
            zones = getattr(self._comp, "zones", None)
            if zones is None or index >= len(zones):
                return
            try:
                setattr(zones[index], field, cast(app_data))
            except (AttributeError, TypeError, ValueError):
                pass
        return _cb

    def _make_zone_rect_cb(self, index: int, coord_idx: int) -> Callable:
        """Return a callback that updates zones[index].rect[coord_idx]."""
        def _cb(sender, app_data, user_data):
            zones = getattr(self._comp, "zones", None)
            if zones is None or index >= len(zones):
                return
            zone = zones[index]
            rect = list(getattr(zone, "rect", None) or [
                getattr(zone, "x", 0),
                getattr(zone, "y", 0),
                getattr(zone, "w", 64),
                getattr(zone, "h", 64),
            ])
            while len(rect) < 4:
                rect.append(0)
            rect[coord_idx] = int(app_data)
            try:
                if hasattr(zone, "rect"):
                    zone.rect = tuple(rect)
                else:
                    attrs = ("x", "y", "w", "h")
                    setattr(zone, attrs[coord_idx], int(app_data))
            except (AttributeError, TypeError):
                pass
        return _cb

    def _make_zone_material_cb(self, index: int) -> Callable:
        def _cb(sender, app_data, user_data):
            zones = getattr(self._comp, "zones", None)
            if zones is None or index >= len(zones):
                return
            zone = zones[index]
            if app_data == "(inherit)":
                try:
                    zone.material = None
                except AttributeError:
                    pass
                return
            from slappyengine.deform_modes import MaterialPreset
            try:
                zone.material = MaterialPreset(app_data)
            except (ValueError, AttributeError):
                pass
        return _cb

    def _make_remove_zone_cb(self, index: int) -> Callable:
        def _cb(sender, app_data, user_data):
            zones = getattr(self._comp, "zones", None)
            if zones is None:
                return
            if 0 <= index < len(zones):
                del zones[index]
            self._refresh()
        return _cb

    # ------------------------------------------------------------------
    # Button callbacks
    # ------------------------------------------------------------------

    def _on_add_zone(self, sender=None, app_data=None, user_data=None) -> None:
        """Append a default zone (Phase B: slappyengine.zones.ThresholdZone) and refresh."""
        if self._comp is None:
            return
        # Phase B repackage: use the generic ThresholdZone primitive from
        # slappyengine.zones instead of the legacy ZoneConfig from
        # deform_modes. ThresholdZone preserves the rect / threshold /
        # material / strength_scale data model the panel already reads.
        from slappyengine.zones import ThresholdZone

        zones = getattr(self._comp, "zones", None)
        if zones is None:
            # Auto-create the list if the component doesn't have one yet
            try:
                self._comp.zones = []
                zones = self._comp.zones
            except AttributeError:
                return

        new_name = f"zone_{len(zones)}"
        new_zone = ThresholdZone(name=new_name, x=0, y=0, w=64, h=64)
        zones.append(new_zone)
        self._refresh()

    def _on_preview_zones(self, sender=None, app_data=None, user_data=None) -> None:
        """Call the registered preview callback, if any."""
        if self._preview_callback is not None and self._comp is not None:
            try:
                self._preview_callback(self._comp)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Shared utility
# ---------------------------------------------------------------------------

def _safe_setattr(obj, attr: str, value) -> None:
    """Set *attr* on *obj* if it exists; silently ignore AttributeError."""
    try:
        setattr(obj, attr, value)
    except (AttributeError, TypeError):
        pass
