from __future__ import annotations

from typing import Callable, Any


# ---------------------------------------------------------------------------
# Joint kind ordering — drives the grouped sub-lists under "Joints (N)".
# Listed in this fixed order so the tree is deterministic; any kind seen on
# a real joint but not in this list is appended in first-seen order under
# its lowercase name.
# ---------------------------------------------------------------------------
_JOINT_KIND_ORDER: tuple[str, ...] = (
    "distance",
    "spring",
    "weld",
    "ball",
    "hinge",
    "motor",
    "prismatic",
)


def _joint_kind_label(kind: str) -> str:
    """Pretty-print a joint kind for the outliner header."""
    return kind.capitalize() if kind else "Other"


def _is_humanoid_body(body: Any) -> bool:
    """Return True if *body* carries the ``humanoid`` parameters tag.

    The convention is that humanoid builders set ``body.parameters["humanoid"]``
    to a truthy value (or to the rig handle itself). We deliberately keep
    the test lenient — any truthy value counts — so the editor recognises
    rigs built by either the dynamics ``make_humanoid`` adapter or
    user-supplied factories.
    """
    params = getattr(body, "parameters", None)
    if not isinstance(params, dict):
        return False
    if "humanoid" in params and params["humanoid"]:
        return True
    # Also treat ``kind == "humanoid"`` as a humanoid for the rare case
    # where authors discriminate purely via the body kind string.
    return getattr(body, "kind", None) == "humanoid"


class SceneOutliner:
    """Scene entity hierarchy panel.

    Shows all entities in the current scene with:
    - Visibility toggle (checkbox)
    - Lock toggle (small "L" button)
    - Entity name button (click to select; accent background when selected)
    - Type badge (right-aligned small text)
    - "Add Entity" button at top
    - "Delete Selected" button at top

    In addition, when a :class:`slappyengine.dynamics.World` is attached via
    :meth:`set_dynamics_world` the outliner appends a dedicated tree section
    enumerating the world's bodies and joints:

    - ``World`` (root)
      - ``Bodies (N)`` — one row per :class:`Body` showing its ``kind``
      - ``Joints (N)`` — grouped by ``kind`` sublists
        (``Distance (n)``, ``Spring (n)``, ``Hinge (n)``, …)
      - ``Humanoids (N)`` — present only when at least one body carries a
        ``"humanoid"`` tag in its ``parameters`` dict (or kind == humanoid)

    Selecting any tree row routes the body / joint reference to the same
    on-select callback used for entity rows so the PropertyInspector picks
    it up via its standard ``set_object`` path.

    Panel protocol
    --------------
    Implements ``build(parent_tag: str | int) -> None``.

    Usage::

        outliner = SceneOutliner()
        outliner.set_scene(scene)
        outliner.set_dynamics_world(world)
        outliner.set_on_select(lambda e: print("selected:", e))
        outliner.build("sidebar")
    """

    _ROW_HEIGHT = 22
    _NAME_BTN_W = -120   # fills remaining space, leaving room for badge

    def __init__(self) -> None:
        self._scene: Any | None = None
        self._dynamics_world: Any | None = None
        self._selected_entity: Any | None = None
        self._on_select: Callable[[Any], None] | None = None
        self._panel_tag: str = "scene_outliner"

        # Tracks DPG tags created for entity rows so we can rebuild cleanly
        self._row_group_tag: str = "scene_outliner_rows"
        # Container for the dynamics-world tree section, rebuilt on refresh
        self._dyn_group_tag: str = "scene_outliner_dynamics"

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

    def set_dynamics_world(self, world: Any) -> None:
        """Attach a :class:`slappyengine.dynamics.World` for tree display.

        Pass ``None`` to detach. When the outliner has already been built
        the tree is rebuilt in place so authors get immediate feedback after
        spawning a rope / ragdoll / humanoid through the ``+ Add`` menu.
        """
        self._dynamics_world = world
        if self._accent_theme is not None:
            self.refresh()

    def get_dynamics_world(self) -> Any | None:
        """Return the currently-attached dynamics world (or ``None``)."""
        return self._dynamics_world

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
                    tag="outliner_add_btn",
                    callback=self._on_add_entity,
                )
                dpg.add_button(
                    label="- Delete",
                    width=70,
                    height=22,
                    callback=self._on_delete_entity,
                )

            # Popup attached to the "+ Add" button — contains the
            # spawn_menu.SPAWN_ACTIONS entries.  Left-click on the button
            # opens the popup (mousebutton=0).
            try:
                from slappyengine.ui.editor.spawn_menu import (
                    SPAWN_ACTIONS,
                    open_spawn_modal,
                )
            except Exception:
                SPAWN_ACTIONS = []
                open_spawn_modal = None  # type: ignore[assignment]

            if SPAWN_ACTIONS and open_spawn_modal is not None:
                with dpg.popup(
                    parent="outliner_add_btn",
                    mousebutton=0,
                    tag="outliner_add_popup",
                ):
                    dpg.add_text("Spawn", color=[180, 180, 200, 255])
                    dpg.add_separator()
                    for action in SPAWN_ACTIONS:
                        # Bind action at default-arg time so the closure
                        # doesn't capture the loop variable.
                        dpg.add_menu_item(
                            label=action["label"],
                            callback=lambda s, a, u, act=action: (
                                open_spawn_modal(act, self._scene)
                            ),
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

            # Dynamics-world tree container — appended below the entity rows.
            # Built every refresh so adding a rope / ragdoll through the
            # spawn menu becomes visible without rebuilding the whole panel.
            dpg.add_separator()
            with dpg.group(tag=self._dyn_group_tag):
                self._build_dynamics_tree()

    def refresh(self) -> None:
        """Rebuild entity rows + dynamics tree from the current scene state.

        Safe to call any time after ``build()`` has been called.
        """
        import dearpygui.dearpygui as dpg

        if dpg.does_item_exist(self._row_group_tag):
            for child in dpg.get_item_children(self._row_group_tag, slot=1):
                dpg.delete_item(child)
            with dpg.group(parent=self._row_group_tag):
                self._build_rows()

        if dpg.does_item_exist(self._dyn_group_tag):
            for child in dpg.get_item_children(self._dyn_group_tag, slot=1):
                dpg.delete_item(child)
            with dpg.group(parent=self._dyn_group_tag):
                self._build_dynamics_tree()

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

    # ------------------------------------------------------------------
    # Dynamics world tree
    # ------------------------------------------------------------------

    def iter_dynamics_rows(self) -> list[dict[str, Any]]:
        """Flat dict-row enumeration of the attached dynamics world.

        Each row is::

            {"type": str, "label": str, "depth": int, "ref": Any}

        ``type`` is one of ``"world"``, ``"bodies_group"``, ``"body"``,
        ``"joints_group"``, ``"joint_kind_group"``, ``"joint"``,
        ``"humanoids_group"``, ``"humanoid"``. ``ref`` is ``None`` for
        purely structural nodes and otherwise points at the underlying
        :class:`Body` / :class:`JointSpec` so click handlers can route the
        selection straight to :class:`PropertyInspector`.

        Returns an empty list when no dynamics world is attached or the
        attached world has zero bodies *and* zero joints.
        """
        world = self._dynamics_world
        if world is None:
            return []

        bodies = list(getattr(world, "bodies", []) or [])
        joints = list(getattr(world, "joints", []) or [])
        humanoids = [b for b in bodies if _is_humanoid_body(b)]

        if not bodies and not joints:
            return []

        rows: list[dict[str, Any]] = []
        rows.append({
            "type": "world", "label": "World",
            "depth": 0, "ref": world,
        })

        # Bodies group
        rows.append({
            "type": "bodies_group",
            "label": f"Bodies ({len(bodies)})",
            "depth": 1, "ref": None,
        })
        for body in bodies:
            kind = getattr(body, "kind", "body")
            label = getattr(body, "label", "") or kind
            rows.append({
                "type": "body",
                "label": f"{label} [{kind}]",
                "depth": 2, "ref": body,
            })

        # Joints group, sub-grouped by kind
        rows.append({
            "type": "joints_group",
            "label": f"Joints ({len(joints)})",
            "depth": 1, "ref": None,
        })
        # Bucket joints by kind preserving solver order within each bucket.
        by_kind: dict[str, list[Any]] = {}
        for joint in joints:
            kind = str(getattr(joint, "kind", "other") or "other")
            by_kind.setdefault(kind, []).append(joint)
        ordered_kinds = [k for k in _JOINT_KIND_ORDER if k in by_kind]
        for kind in by_kind:
            if kind not in ordered_kinds:
                ordered_kinds.append(kind)
        for kind in ordered_kinds:
            bucket = by_kind[kind]
            rows.append({
                "type": "joint_kind_group",
                "label": f"{_joint_kind_label(kind)} ({len(bucket)})",
                "depth": 2, "ref": None,
            })
            for joint in bucket:
                a = getattr(joint, "node_a", "?")
                b = getattr(joint, "node_b", "?")
                rows.append({
                    "type": "joint",
                    "label": f"{kind} ({a}-{b})",
                    "depth": 3, "ref": joint,
                })

        # Humanoids group (only when at least one body claims the tag).
        if humanoids:
            rows.append({
                "type": "humanoids_group",
                "label": f"Humanoids ({len(humanoids)})",
                "depth": 1, "ref": None,
            })
            for body in humanoids:
                label = getattr(body, "label", "") or "humanoid"
                node_count = int(getattr(body, "node_count", 0))
                rows.append({
                    "type": "humanoid",
                    "label": f"{label} ({node_count} nodes)",
                    "depth": 2, "ref": body,
                })

        return rows

    def _build_dynamics_tree(self) -> None:
        """Render the dynamics-world tree using DPG tree_node primitives."""
        import dearpygui.dearpygui as dpg

        rows = self.iter_dynamics_rows()
        if not rows:
            return

        # First row is always the World root; everything else nests inside.
        world_row = rows[0]
        with dpg.tree_node(label=world_row["label"], default_open=True):
            i = 1
            n = len(rows)
            while i < n:
                row = rows[i]
                if row["type"] in (
                    "bodies_group", "joints_group", "humanoids_group",
                ):
                    # Collect children at depth 2+ until we hit the next
                    # depth-1 group or run out of rows.
                    section_children: list[dict[str, Any]] = []
                    j = i + 1
                    while j < n and rows[j]["depth"] >= 2:
                        section_children.append(rows[j])
                        j += 1
                    with dpg.tree_node(
                        label=row["label"], default_open=False
                    ):
                        self._render_dynamics_children(section_children)
                    i = j
                else:
                    # Defensive: shouldn't happen for well-formed rows.
                    i += 1

    def _render_dynamics_children(
        self, children: list[dict[str, Any]]
    ) -> None:
        """Render a section's child rows (joints have a kind sub-group)."""
        import dearpygui.dearpygui as dpg

        i = 0
        n = len(children)
        while i < n:
            row = children[i]
            if row["type"] == "joint_kind_group":
                # Collect the joint rows that follow this kind group.
                bucket: list[dict[str, Any]] = []
                j = i + 1
                while j < n and children[j]["type"] == "joint":
                    bucket.append(children[j])
                    j += 1
                with dpg.tree_node(label=row["label"], default_open=False):
                    for joint_row in bucket:
                        self._add_dynamics_leaf(joint_row)
                i = j
            else:
                self._add_dynamics_leaf(row)
                i += 1

    def _add_dynamics_leaf(self, row: dict[str, Any]) -> None:
        """Render a single body / joint / humanoid row as a click button."""
        import dearpygui.dearpygui as dpg

        ref = row["ref"]
        dpg.add_button(
            label=row["label"],
            width=-1,
            height=18,
            callback=lambda s, a, u=ref: self._on_select_dynamics(u),
        )

    def _on_select_dynamics(self, ref: Any) -> None:
        """Route a dynamics tree click through the standard selection hook."""
        if ref is None:
            return
        self._selected_entity = ref
        if self._on_select is not None:
            self._on_select(ref)
