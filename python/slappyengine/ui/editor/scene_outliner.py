from __future__ import annotations

from typing import Callable, Any


class SceneOutliner:
    """Scene entity hierarchy panel.

    Shows all entities in the current scene with:
    - Visibility toggle (checkbox)
    - Lock toggle (small "L" button)
    - Entity name button (click to select; accent background when selected)
    - Type badge (right-aligned small text)
    - "Add Entity" button at top
    - "Delete Selected" button at top

    Panel protocol
    --------------
    Implements ``build(parent_tag: str | int) -> None``.

    Usage::

        outliner = SceneOutliner()
        outliner.set_scene(scene)
        outliner.set_on_select(lambda e: print("selected:", e))
        outliner.build("sidebar")
    """

    _ROW_HEIGHT = 22
    _NAME_BTN_W = -120   # fills remaining space, leaving room for badge

    def __init__(self) -> None:
        self._scene: Any | None = None
        self._selected_entity: Any | None = None
        self._on_select: Callable[[Any], None] | None = None
        self._panel_tag: str = "scene_outliner"

        # Tracks DPG tags created for entity rows so we can rebuild cleanly
        self._row_group_tag: str = "scene_outliner_rows"

        # Per-item themes for selected vs normal name buttons
        self._accent_theme: int | None = None
        self._default_theme: int | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_scene(self, scene: Any) -> None:
        """Attach a scene object and refresh the outliner if already built."""
        self._scene = scene
        if self._accent_theme is not None:
            # build() has already been called — live refresh
            self.refresh()

    def get_selected(self) -> Any | None:
        """Return the currently selected entity, or ``None``."""
        return self._selected_entity

    def set_on_select(self, cb: Callable[[Any], None]) -> None:
        """Register a callback invoked whenever the selection changes."""
        self._on_select = cb

    def build(self, parent_tag: str | int) -> None:
        """Draw the outliner panel inside *parent_tag*."""
        import dearpygui.dearpygui as dpg
        from slappyengine.ui.editor.theme import get_accent_button_theme, get_default_button_theme

        self._accent_theme  = get_accent_button_theme()
        self._default_theme = get_default_button_theme()

        with dpg.collapsing_header(
            label="Scene Outliner",
            default_open=True,
            parent=parent_tag,
        ):
            # Action bar: Add / Delete
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="+ Add",
                    width=70,
                    height=22,
                    callback=self._on_add_entity,
                )
                dpg.add_button(
                    label="- Delete",
                    width=70,
                    height=22,
                    callback=self._on_delete_entity,
                )

            dpg.add_separator()

            # Column header row
            with dpg.group(horizontal=True):
                dpg.add_text("V ", color=[115, 115, 122, 200])   # vis
                dpg.add_text("L ", color=[115, 115, 122, 200])   # lock
                dpg.add_text("Name", color=[115, 115, 122, 200])

            dpg.add_separator()

            # Entity rows container — replaced wholesale on refresh()
            with dpg.group(tag=self._row_group_tag):
                self._build_rows()

    def refresh(self) -> None:
        """Rebuild entity rows from the current scene state.

        Safe to call any time after ``build()`` has been called.
        """
        import dearpygui.dearpygui as dpg

        if not dpg.does_item_exist(self._row_group_tag):
            return

        # Delete existing children of the rows group then repopulate
        for child in dpg.get_item_children(self._row_group_tag, slot=1):
            dpg.delete_item(child)

        with dpg.group(parent=self._row_group_tag):
            self._build_rows()

    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    def _build_rows(self) -> None:
        """One row per entity: [vis] [lock] [name...] [type badge]."""
        import dearpygui.dearpygui as dpg

        entities = self._entities()
        if not entities:
            dpg.add_text("  (no entities)", color=[115, 115, 122, 200])
            return

        for i, entity in enumerate(entities):
            self._build_entity_row(entity, i)

    def _build_entity_row(self, entity: Any, index: int) -> None:
        """Render a single entity row."""
        import dearpygui.dearpygui as dpg

        name     = getattr(entity, "name", f"Entity_{index}")
        type_tag = type(entity).__name__

        # Sanitise name for use as a DPG tag fragment
        safe = name.replace(" ", "_").replace(".", "_")
        row_tag   = f"outliner_row_{index}_{safe}"
        vis_tag   = f"outliner_vis_{index}_{safe}"
        lock_tag  = f"outliner_lock_{index}_{safe}"
        name_tag  = f"outliner_name_{index}_{safe}"

        with dpg.group(horizontal=True, tag=row_tag):
            # --- Visibility checkbox ----------------------------------------
            has_visible = hasattr(entity, "visible")
            visible_val = bool(getattr(entity, "visible", True))
            if has_visible:
                dpg.add_checkbox(
                    tag=vis_tag,
                    default_value=visible_val,
                    callback=lambda s, a, u=entity: self._on_toggle_visible(u, a),
                )
            else:
                dpg.add_text("  ")   # placeholder spacing

            # --- Lock button ------------------------------------------------
            has_locked = hasattr(entity, "locked")
            locked_val = bool(getattr(entity, "locked", False))
            lock_label = "L" if not locked_val else "L"
            lock_color = [77, 191, 102, 255] if not locked_val else [230, 89, 89, 255]
            dpg.add_button(
                label=lock_label,
                tag=lock_tag,
                width=18,
                height=18,
                callback=lambda s, a, u=(entity, lock_tag): self._on_toggle_lock(*u),
            )

            # --- Name button (selection) ------------------------------------
            is_selected = entity is self._selected_entity
            dpg.add_button(
                label=name,
                tag=name_tag,
                width=self._NAME_BTN_W,
                height=18,
                callback=lambda s, a, u=(entity, index): self._on_select_entity(*u),
            )
            if is_selected and self._accent_theme is not None:
                dpg.bind_item_theme(name_tag, self._accent_theme)
            elif self._default_theme is not None:
                dpg.bind_item_theme(name_tag, self._default_theme)

            # --- Type badge -------------------------------------------------
            dpg.add_text(f"[{type_tag}]", color=[115, 115, 122, 220])

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_select_entity(self, entity: Any, index: int) -> None:
        """Handle name-button click: update selection and highlights."""
        import dearpygui.dearpygui as dpg

        prev = self._selected_entity
        self._selected_entity = entity

        # Refresh highlights for the previous and new selection
        entities = self._entities()
        for i, e in enumerate(entities):
            name     = getattr(e, "name", f"Entity_{i}")
            safe     = name.replace(" ", "_").replace(".", "_")
            name_tag = f"outliner_name_{i}_{safe}"
            if not dpg.does_item_exist(name_tag):
                continue
            if e is entity and self._accent_theme is not None:
                dpg.bind_item_theme(name_tag, self._accent_theme)
            elif self._default_theme is not None:
                dpg.bind_item_theme(name_tag, self._default_theme)

        if self._on_select is not None:
            self._on_select(entity)

    def _on_toggle_visible(self, entity: Any, value: bool) -> None:
        """Toggle entity visibility."""
        if hasattr(entity, "visible"):
            entity.visible = value

    def _on_toggle_lock(self, entity: Any, lock_tag: str) -> None:
        """Toggle entity lock state."""
        import dearpygui.dearpygui as dpg

        if hasattr(entity, "locked"):
            entity.locked = not entity.locked
        if dpg.does_item_exist(lock_tag):
            locked = bool(getattr(entity, "locked", False))
            # Tint the lock button red when locked, green when unlocked
            pass  # colour handled at build-time; full restyle needs a rebuild

    def _on_add_entity(self) -> None:
        """Placeholder — subclass or connect to engine to implement."""
        pass

    def _on_delete_entity(self) -> None:
        """Delete the currently selected entity from the scene."""
        if self._selected_entity is None:
            return
        if self._scene is not None and hasattr(self._scene, "entities"):
            try:
                self._scene.entities.remove(self._selected_entity)
            except ValueError:
                pass
        self._selected_entity = None
        self.refresh()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _entities(self) -> list[Any]:
        """Return the flat entity list from the current scene."""
        if self._scene is None:
            return []
        return list(getattr(self._scene, "entities", []))
