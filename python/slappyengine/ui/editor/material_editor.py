"""Legacy Nova3D reference. The shipping editor uses notebook_material_editor — see docs/ui_pattern_audit_2026_06_03.md.

Survivors:
  * ``notebook_material_editor`` imports ``MaterialPropertyAdapter`` / kind constants from here.
  * ``__init__.py`` still re-exports ``MaterialEditor`` via the lazy map.

Do NOT extend — funnel new work into ``notebook_material_editor.py``.
"""
from __future__ import annotations

import dataclasses
from typing import Any


# Kinds the editor knows how to render.  Selected automatically by
# :meth:`MaterialEditor.set_target` based on the object's shape (an
# explicit ``kind`` kwarg is also accepted for callers that already
# know the kind).
KIND_MATERIAL_MAP = "material_map"   # slappyengine.material.MaterialMap
KIND_SOFTBODY     = "softbody"       # softbody.Material dataclass
KIND_FLUID        = "fluid"          # fluid.FluidMaterial dataclass


def _detect_kind(target: Any) -> str:
    """Return the ``kind`` string for *target* based on its shape.

    Detection rules (most-specific first):

    1. Object exposes ``_materials: list`` → ``"material_map"``
       (MaterialMap interface).
    2. Type module starts with ``slappyengine.fluid`` → ``"fluid"``.
    3. Type module starts with ``slappyengine.softbody`` → ``"softbody"``.
    4. Any other dataclass → fall back to ``"softbody"`` so it still
       gets rendered through the dataclass-reflection path.
    5. Anything else → ``"material_map"`` (the legacy default; the
       editor will render its empty-hint when there are no materials).
    """
    if hasattr(target, "_materials"):
        return KIND_MATERIAL_MAP
    mod = getattr(type(target), "__module__", "") or ""
    if mod.startswith("slappyengine.fluid"):
        return KIND_FLUID
    if mod.startswith("slappyengine.softbody"):
        return KIND_SOFTBODY
    if dataclasses.is_dataclass(target) and not isinstance(target, type):
        return KIND_SOFTBODY
    return KIND_MATERIAL_MAP


class MaterialEditor:
    """
    Visual editor for MaterialMap — shows color ranges and behavior tags.

    Supports three target kinds via auto-detection (or an explicit
    ``kind`` kwarg on :meth:`set_target`):

    ``"material_map"``
        Legacy :class:`slappyengine.material.map.MaterialMap` mode.  One
        collapsing header per :class:`MaterialDef` with R/G/B sliders,
        alpha meaning, behaviour list, delete button, plus an
        ``Add Material`` button at the bottom.

    ``"softbody"``
        :class:`softbody.Material` dataclass mode.  Reflects every
        primitive field of the dataclass directly (sliders for ints/
        floats, color edits for RGBA tuples, etc.).  No add/delete —
        one material per panel.

    ``"fluid"``
        :class:`fluid.FluidMaterial` dataclass mode.  Same dataclass-
        reflection path as ``"softbody"`` but tagged separately so a
        future polish pass can specialise the layout (e.g. wider
        viscosity slider).

    Protocol: build(parent_tag) -> None
    """

    _ALPHA_MEANINGS = ["opacity", "health", "strength", "density", "pressure"]

    def __init__(self) -> None:
        self._material_map = None       # MaterialMap instance (legacy field)
        self._target: Any = None         # current target object (any kind)
        self._kind: str = KIND_MATERIAL_MAP
        self._panel_tag = "material_editor"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_material_map(self, mat_map) -> None:
        """Attach a MaterialMap and rebuild the panel.

        Kept for backwards compatibility; equivalent to
        ``set_target(mat_map, kind="material_map")``.
        """
        from slappyengine.material.map import MaterialMap  # noqa: F401

        self._material_map = mat_map
        self._target = mat_map
        self._kind = KIND_MATERIAL_MAP
        self._refresh()

    def set_target(self, target: Any, kind: str | None = None) -> None:
        """Attach an arbitrary target and rebuild the panel.

        Parameters
        ----------
        target:
            One of:

            - A :class:`slappyengine.material.map.MaterialMap`,
            - A :class:`softbody.Material` dataclass instance, or
            - A :class:`fluid.FluidMaterial` dataclass instance.
        kind:
            Explicit kind override.  When ``None`` the kind is
            auto-detected by :func:`_detect_kind`.  Must be one of
            :data:`KIND_MATERIAL_MAP`, :data:`KIND_SOFTBODY`,
            :data:`KIND_FLUID`.
        """
        self._target = target
        self._kind = kind if kind is not None else _detect_kind(target)
        if self._kind == KIND_MATERIAL_MAP:
            self._material_map = target
        else:
            self._material_map = None
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
        # The Add Material button only applies to MaterialMap kind.  It
        # is rendered regardless but is a no-op for dataclass kinds.
        dpg.add_button(
            label="Add Material",
            callback=self._add_material,
            parent=parent_tag,
            tag=f"{self._panel_tag}_add_btn",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_entries(self) -> None:
        """Populate self._panel_tag with widgets for the current target.

        Dispatches on :attr:`_kind`:

        - ``"material_map"`` — one collapsing header per
          :class:`MaterialDef` (legacy path).
        - ``"softbody"`` / ``"fluid"`` — reflect every dataclass field
          on the target as a primitive widget.
        """
        import dearpygui.dearpygui as dpg

        if self._kind == KIND_MATERIAL_MAP:
            if self._material_map is None:
                dpg.add_text(
                    "No MaterialMap loaded.",
                    parent=self._panel_tag,
                    tag=f"{self._panel_tag}_empty_hint",
                )
                return
            for index, mat in enumerate(self._material_map._materials):
                self._build_entry(index, mat)
            return

        # Dataclass kinds (softbody / fluid) — reflect every primitive
        # field using the same widget vocabulary as the MaterialMap
        # path.  Reuses PropertyInspector._render_field so we don't
        # duplicate widget code.
        target = self._target
        if target is None or not dataclasses.is_dataclass(target):
            dpg.add_text(
                f"No {self._kind} target loaded.",
                parent=self._panel_tag,
                tag=f"{self._panel_tag}_empty_hint",
            )
            return

        from slappyengine.ui.editor.property_inspector import PropertyInspector

        inspector = PropertyInspector()
        inspector._panel_tag = f"{self._panel_tag}_reflect"
        # Build a child window then reflect the target into it.
        dpg.add_child_window(
            tag=inspector._panel_tag,
            parent=self._panel_tag,
            border=False,
            autosize_x=True,
            height=-1,
        )
        inspector._obj = target
        # Re-add the inspector's static header items so _refresh works.
        # If DPG is a stub, these calls are no-ops.
        try:
            dpg.add_text(
                f"{self._kind.title()} Material",
                parent=inspector._panel_tag,
                tag=f"{inspector._panel_tag}_header",
            )
            dpg.add_separator(
                parent=inspector._panel_tag,
                tag=f"{inspector._panel_tag}_sep",
            )
        except Exception:
            pass
        inspector._refresh()
        # Stash a reference so callers can introspect what was built.
        self._reflect_inspector = inspector

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
        # Only meaningful for the MaterialMap kind; dataclass kinds
        # represent one material so there's nothing to add.
        if self._kind != KIND_MATERIAL_MAP:
            return
        from slappyengine.material.map import ColorRange, MaterialDef

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
