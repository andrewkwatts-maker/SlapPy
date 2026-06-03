"""Notebook-themed scene outliner — "pressed flowers / bestiary" journal.

A re-skin of :class:`slappyengine.ui.editor.scene_outliner.SceneOutliner`
that renders the entity hierarchy as a field journal: each entity is a
notebook entry with a hand-drawn creature-type badge, a heart-shaped
visibility toggle, a tiny key-shaped lock toggle, and a handwritten name.

Group dividers are doodled separators (wavy / dotted) and the very first
top-level entity gets a sparkle sticker pinned to its upper-right corner
to mark it as the "primary specimen".  The selected row carries a
highlighter-stroke overlay so the user always knows which page they're on.

The module follows the Nova3D panel protocol (``build(parent_tag)``); the
heavy ``dearpygui`` import is deferred to :meth:`NotebookOutliner.build`
so headless tests / non-``[editor]`` installs can still import the file.
"""
from __future__ import annotations

from typing import Any, Callable

from slappyengine._validation import (
    validate_callable,
    validate_non_empty_str,
    validate_str,
)
from slappyengine.ui.theme.svg_icon import SVGIcon
from slappyengine.ui.widgets.notebook_theme import (
    register_theme_listener,
    resolve_theme,
    unregister_theme_listener,
)
from slappyengine.ui.widgets.sticker_corner import (
    add_sticker_corner,
    remove_sticker_corner,
)


# ---------------------------------------------------------------------------
# Entity-type → badge SVG library.
#
# Each badge is a ≤500B SVG.  The shapes are intentionally pictographic
# (fox face for body, linked rings for joints, …) so the field-journal
# metaphor reads even at thumbnail scale.  Colours are placeholders — the
# active :class:`NotebookTheme` re-tints them at draw time via the
# ``default_fill`` argument when the SVG itself ships ``fill="currentColor"``.
# ---------------------------------------------------------------------------

_BADGE_SVGS: dict[str, str] = {
    # 4-point pressed-flower star
    "entity": (
        '<svg viewBox="0 0 16 16">'
        '<polygon points="8,1 9,7 15,8 9,9 8,15 7,9 1,8 7,7" fill="#d87aa0"/>'
        '</svg>'
    ),
    # Small fox face — triangle ears + rounded jaw
    "body": (
        '<svg viewBox="0 0 16 16">'
        '<polygon points="2,3 5,2 5,6" fill="#c97a3e"/>'
        '<polygon points="14,3 11,2 11,6" fill="#c97a3e"/>'
        '<circle cx="8" cy="9" r="5" fill="#e09060"/>'
        '<circle cx="6" cy="8" r="0.8" fill="#202020"/>'
        '<circle cx="10" cy="8" r="0.8" fill="#202020"/>'
        '</svg>'
    ),
    # Two linked rings — joints
    "joint": (
        '<svg viewBox="0 0 16 16">'
        '<circle cx="5" cy="8" r="3" fill="none" stroke="#7090c0" stroke-width="1.5"/>'
        '<circle cx="11" cy="8" r="3" fill="none" stroke="#90a0d0" stroke-width="1.5"/>'
        '</svg>'
    ),
    # Sun for lights — circle + radiating lines
    "light": (
        '<svg viewBox="0 0 16 16">'
        '<circle cx="8" cy="8" r="3" fill="#f0c050"/>'
        '<line x1="8" y1="1" x2="8" y2="4" stroke="#f0c050" stroke-width="1.2"/>'
        '<line x1="8" y1="12" x2="8" y2="15" stroke="#f0c050" stroke-width="1.2"/>'
        '<line x1="1" y1="8" x2="4" y2="8" stroke="#f0c050" stroke-width="1.2"/>'
        '<line x1="12" y1="8" x2="15" y2="8" stroke="#f0c050" stroke-width="1.2"/>'
        '</svg>'
    ),
    # Daisy flower for camera (matches catalog flower_01)
    "camera": (
        '<svg viewBox="0 0 16 16">'
        '<circle cx="8" cy="3" r="2" fill="#f0d0e0"/>'
        '<circle cx="8" cy="13" r="2" fill="#f0d0e0"/>'
        '<circle cx="3" cy="8" r="2" fill="#f0d0e0"/>'
        '<circle cx="13" cy="8" r="2" fill="#f0d0e0"/>'
        '<circle cx="8" cy="8" r="2" fill="#f0b040"/>'
        '</svg>'
    ),
    # Pressed leaf for mesh — teardrop with central vein
    "mesh": (
        '<svg viewBox="0 0 16 16">'
        '<polygon points="8,1 14,8 8,15 2,8" fill="#6ea060"/>'
        '<line x1="8" y1="1" x2="8" y2="15" stroke="#3a5030" stroke-width="0.8"/>'
        '</svg>'
    ),
    # Tiny person silhouette for humanoid
    "humanoid": (
        '<svg viewBox="0 0 16 16">'
        '<circle cx="8" cy="3" r="2" fill="#d0a070"/>'
        '<rect x="6" y="5" width="4" height="6" fill="#d0a070"/>'
        '<rect x="6" y="11" width="1.5" height="4" fill="#d0a070"/>'
        '<rect x="8.5" y="11" width="1.5" height="4" fill="#d0a070"/>'
        '</svg>'
    ),
    # Paint swatch for material
    "material": (
        '<svg viewBox="0 0 16 16">'
        '<rect x="1" y="3" width="4" height="10" fill="#e07a90"/>'
        '<rect x="6" y="3" width="4" height="10" fill="#e0c850"/>'
        '<rect x="11" y="3" width="4" height="10" fill="#70a0c0"/>'
        '</svg>'
    ),
    # Curly line for rope
    "rope": (
        '<svg viewBox="0 0 16 16">'
        '<path d="M2 8 L5 4 L8 8 L11 4 L14 8" fill="none" stroke="#a07050" stroke-width="1.6"/>'
        '</svg>'
    ),
    # Puppet outline for ragdoll
    "ragdoll": (
        '<svg viewBox="0 0 16 16">'
        '<circle cx="8" cy="3" r="1.6" fill="none" stroke="#604030" stroke-width="1.2"/>'
        '<line x1="8" y1="5" x2="8" y2="10" stroke="#604030" stroke-width="1.2"/>'
        '<line x1="4" y1="7" x2="12" y2="7" stroke="#604030" stroke-width="1.2"/>'
        '<line x1="8" y1="10" x2="5" y2="14" stroke="#604030" stroke-width="1.2"/>'
        '<line x1="8" y1="10" x2="11" y2="14" stroke="#604030" stroke-width="1.2"/>'
        '</svg>'
    ),
    # Dashed rectangle for zone
    "zone": (
        '<svg viewBox="0 0 16 16">'
        '<rect x="2" y="2" width="12" height="12" fill="none" '
        'stroke="#8090a0" stroke-width="1.2" stroke-dasharray="2,2"/>'
        '</svg>'
    ),
}


# Display labels for each badge — handwritten "Latin binomial" style
# annotation alongside the icon.
_BADGE_LABELS: dict[str, str] = {
    "entity":   "entry",
    "body":     "vulpes corpus",
    "joint":    "nexus",
    "light":    "sol",
    "camera":   "oculus",
    "mesh":     "folium",
    "humanoid": "homo",
    "material": "pigmentum",
    "rope":     "filum",
    "ragdoll":  "marionetta",
    "zone":     "regio",
}


def badge_svg(kind: str) -> str:
    """Return the SVG markup for entity-type *kind* (falls back to ``entity``)."""
    return _BADGE_SVGS.get(kind, _BADGE_SVGS["entity"])


def badge_label(kind: str) -> str:
    """Return the journal-binomial label for *kind*."""
    return _BADGE_LABELS.get(kind, kind)


# ---------------------------------------------------------------------------
# Entity → type-key classifier.  Looks at .kind / class name / parameters to
# pick the badge.  Kept liberal so user-defined entity classes still get a
# sensible default badge (the generic 4-point star).
# ---------------------------------------------------------------------------

def classify_entity(entity: Any) -> str:
    """Return one of :data:`_BADGE_SVGS`'s keys for *entity*."""
    if entity is None:
        return "entity"
    # Explicit dynamics-body classification first — body.kind is the
    # most reliable signal (rope / ragdoll / humanoid / ...).
    kind = getattr(entity, "kind", None)
    if isinstance(kind, str) and kind:
        k = kind.lower()
        params = getattr(entity, "parameters", None)
        if isinstance(params, dict) and params.get("humanoid"):
            return "humanoid"
        if k in _BADGE_SVGS:
            return k
        if k in ("softbody", "rigid", "particle"):
            return "body"
        # Fall through to class-name sniff
    cls_name = type(entity).__name__.lower()
    for needle, key in (
        ("humanoid", "humanoid"),
        ("ragdoll",  "ragdoll"),
        ("rope",     "rope"),
        ("joint",    "joint"),
        ("light",    "light"),
        ("camera",   "camera"),
        ("material", "material"),
        ("mesh",     "mesh"),
        ("zone",     "zone"),
        ("body",     "body"),
    ):
        if needle in cls_name:
            return key
    return "entity"


# ---------------------------------------------------------------------------
# Public outliner class.
# ---------------------------------------------------------------------------


class NotebookOutliner:
    """Entity hierarchy panel themed as a field-journal bestiary.

    Per Nova3D's ``build(parent_tag)`` protocol.  Reads scene/world from
    the supplied ``world_getter`` callback; renders entities as journal
    entries with creature-inspired type badges.

    Parameters
    ----------
    world_getter:
        Zero-arg callable returning the active world / scene-like object.
        The object is expected to expose either ``.entities`` (a flat
        list) or ``.bodies`` (the dynamics-world surface) — both shapes
        are accepted and merged into a single flat row list.
    on_select:
        Callable invoked with the clicked entity whenever the user picks
        a row.  Mirrors :class:`SceneOutliner.set_on_select` semantics.
    """

    TITLE = "Scene"

    # Movable-window minimums — picked up by ``MovablePanelWindow``.
    MIN_WIDTH: int = 240
    MIN_HEIGHT: int = 300

    _INDENT_PX = 16
    _ROW_HEIGHT = 24
    _SEARCH_TAG = "notebook_outliner_search"
    _ROWS_GROUP = "notebook_outliner_rows"
    _EMPTY_TAG = "notebook_outliner_empty"
    _HIGHLIGHT_TAG = "notebook_outliner_highlight"

    def __init__(
        self,
        world_getter: Callable[[], Any],
        on_select: Callable[[Any], None],
    ) -> None:
        self._world_getter = validate_callable(
            "world_getter", "NotebookOutliner", world_getter,
        )
        self._on_select = validate_callable(
            "on_select", "NotebookOutliner", on_select,
        )

        self._selected_id: str | None = None
        self._search_text: str = ""
        self._built: bool = False
        self._parent_tag: str | int | None = None
        self._theme = resolve_theme()
        self._scene: Any | None = None
        self._sticker_handles: list[str] = []

        register_theme_listener(self._on_theme_changed)

    def set_scene(self, scene: Any) -> None:
        """Bind the active scene whose entities populate the outliner.

        Compat shim for the legacy `SceneOutliner.set_scene` contract that
        `Engine.run_editor()` calls during boot. Replaces the world_getter
        with one that returns `scene.world` (or the scene itself if it
        already quacks like a world).
        """
        self._scene = scene
        world = getattr(scene, "world", scene) if scene is not None else None
        self._world_getter = lambda: world
        self._selected_id = None
        if self._built:
            self.refresh()

    def set_on_select(self, callback: Callable[[Any], None]) -> None:
        """Replace the on-select callback. Compat shim for the legacy
        `SceneOutliner.set_on_select` contract.

        The original callback registered at `__init__` is replaced. If the
        engine wires this multiple times (it does once via shell.setup and
        once again later in `Engine.run_editor`), the LAST writer wins.
        """
        validated = validate_callable("callback", "set_on_select", callback)
        previous = self._on_select
        # Chain so both callbacks fire (the gizmo set_entity AND any panel
        # that subscribed earlier via the constructor).
        def _combined(entity: Any, _prev=previous, _new=validated) -> None:
            try:
                _prev(entity)
            finally:
                _new(entity)
        self._on_select = _combined

    # ------------------------------------------------------------------
    # Theme handling
    # ------------------------------------------------------------------

    def _on_theme_changed(self, _theme: Any) -> None:
        self._theme = resolve_theme()
        if self._built:
            try:
                self.refresh()
            except Exception:
                # A theme change must never crash the editor — the worst
                # case is a row painted in the old palette until the next
                # explicit refresh() call.
                pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_selected(self, entity_id: str) -> None:
        """Programmatically mark *entity_id* as the selected row."""
        validate_str("entity_id", "set_selected", entity_id, allow_empty=True)
        self._selected_id = entity_id or None
        if self._built:
            self.refresh()

    def get_selected(self) -> str | None:
        """Return the currently selected entity id (or ``None``)."""
        return self._selected_id

    def set_search(self, text: str) -> None:
        """Set the search filter text — only matching rows render."""
        validate_str("text", "set_search", text, allow_empty=True)
        self._search_text = text or ""
        if self._built:
            self.refresh()

    # ------------------------------------------------------------------
    # Build / refresh
    # ------------------------------------------------------------------

    def build(self, parent_tag: int | str) -> None:
        """Render the panel under *parent_tag* (DPG collapsing header)."""
        dpg = self._safe_dpg()
        if dpg is None:
            return
        self._parent_tag = parent_tag

        try:
            with dpg.collapsing_header(
                label=self.TITLE, default_open=True, parent=parent_tag,
            ):
                # Search box wrapped with a washi-tape underline.
                ink = list(self._theme.color("ink", (40, 40, 60, 255)))
                washi = list(self._theme.color("washi", (180, 200, 230, 255)))
                try:
                    dpg.add_input_text(
                        hint="Search the bestiary…",
                        tag=self._SEARCH_TAG,
                        callback=self._on_search_changed,
                        width=-1,
                    )
                except Exception:
                    pass
                # Washi-tape underline strip beneath the search.
                try:
                    dpg.add_text("===========================", color=washi)
                except Exception:
                    pass

                # Section dividers + per-row content live inside the
                # rows-group container so refresh() can swap them out.
                try:
                    with dpg.group(tag=self._ROWS_GROUP):
                        self._build_rows()
                except Exception:
                    # Stub-DPG without context-manager support — fall through.
                    self._build_rows()
        except Exception:
            # Final fallback: at least drop a title text so the panel is
            # visible in a minimal stub-DPG.
            try:
                dpg.add_text(self.TITLE, parent=parent_tag)
            except Exception:
                pass

        self._built = True

    def refresh(self) -> None:
        """Rebuild the rows from the current world state."""
        dpg = self._safe_dpg()
        if dpg is None:
            return
        try:
            exists = dpg.does_item_exist(self._ROWS_GROUP)
        except Exception:
            exists = False
        if exists:
            try:
                for child in dpg.get_item_children(self._ROWS_GROUP, slot=1):
                    dpg.delete_item(child)
                with dpg.group(parent=self._ROWS_GROUP):
                    self._build_rows()
                return
            except Exception:
                pass
        # Stub-DPG path — rebuild without container management.
        try:
            self._build_rows()
        except Exception:
            pass

    def destroy(self) -> None:
        """Detach theme listener + drop any sticker decorations."""
        unregister_theme_listener(self._on_theme_changed)
        for handle in list(self._sticker_handles):
            try:
                remove_sticker_corner(handle)
            except Exception:
                pass
        self._sticker_handles.clear()
        self._built = False

    # ------------------------------------------------------------------
    # Row enumeration — the data layer the tests reach into.
    # ------------------------------------------------------------------

    def iter_entities(self) -> list[Any]:
        """Return the flat entity list from the current world.

        Accepts both Nova3D scene objects (``.entities``) and dynamics
        worlds (``.bodies``).  When the world exposes both, ``.entities``
        wins and ``.bodies`` is concatenated afterwards.
        """
        try:
            world = self._world_getter()
        except Exception:
            return []
        if world is None:
            return []
        out: list[Any] = []
        for attr in ("entities", "bodies"):
            seq = getattr(world, attr, None)
            if isinstance(seq, (list, tuple)):
                out.extend(seq)
        return out

    def iter_rows(self) -> list[dict[str, Any]]:
        """Enumerate filtered rows the renderer would draw.

        Each row is a ``{"entity", "id", "name", "kind", "depth"}`` dict.
        Search filtering applies here so tests can assert visible row
        counts without touching DPG.
        """
        rows: list[dict[str, Any]] = []
        needle = self._search_text.strip().lower()
        for ent in self.iter_entities():
            name = self._entity_name(ent)
            kind = classify_entity(ent)
            if needle and needle not in name.lower() and needle not in kind.lower():
                continue
            rows.append({
                "entity": ent,
                "id":     self._entity_id(ent),
                "name":   name,
                "kind":   kind,
                "depth":  int(getattr(ent, "depth", 0) or 0),
            })
        return rows

    # ------------------------------------------------------------------
    # Row rendering
    # ------------------------------------------------------------------

    def _build_rows(self) -> None:
        dpg = self._safe_dpg()
        if dpg is None:
            return

        rows = self.iter_rows()
        if not rows:
            self._build_empty_state()
            return

        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        secondary = list(self._theme.color(
            "text_secondary",
            self._theme.color("ink", (115, 115, 122, 220)),
        ))
        accent = list(self._theme.color("accent", (220, 120, 160, 255)))
        highlight = list(self._theme.color("highlight", (255, 240, 120, 200)))

        # Group rows by kind-bucket so we can drop a doodled separator
        # between sections (entities / joints / lights / zones / other).
        # Order is fixed for determinism.
        bucket_order = (
            ("entities", {"entity", "body", "mesh", "humanoid",
                          "rope", "ragdoll", "material"}),
            ("joints",   {"joint"}),
            ("lights",   {"light", "camera"}),
            ("zones",    {"zone"}),
        )
        first_top_level_seen = False
        for section, kinds in bucket_order:
            section_rows = [r for r in rows if r["kind"] in kinds]
            if not section_rows:
                continue
            # Wavy separator between non-first sections.
            if first_top_level_seen:
                try:
                    dpg.add_text("~ ~ ~ ~ ~ ~ ~ ~", color=secondary)
                except Exception:
                    pass
            # Section header in the secondary (handwritten) colour.
            try:
                dpg.add_text(f"{section}", color=secondary)
            except Exception:
                pass

            for i, row in enumerate(section_rows):
                self._build_entity_row(
                    row,
                    is_first_overall=(not first_top_level_seen and i == 0),
                    accent=accent,
                    ink=ink,
                    highlight=highlight,
                )
            first_top_level_seen = True

    def _build_empty_state(self) -> None:
        dpg = self._safe_dpg()
        if dpg is None:
            return
        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        try:
            dpg.add_text(
                "No entries yet — drop a creature in from the spawn menu",
                color=ink,
                tag=self._EMPTY_TAG,
            )
        except Exception:
            try:
                dpg.add_text(
                    "No entries yet — drop a creature in from the spawn menu",
                )
            except Exception:
                pass
        # Small fox sticker corner — pinned to the empty-state area.
        try:
            handle = add_sticker_corner(self._EMPTY_TAG, "fox", "BR")
            self._sticker_handles.append(handle)
        except Exception:
            pass

    def _build_entity_row(
        self,
        row: dict[str, Any],
        *,
        is_first_overall: bool,
        accent: list[int],
        ink: list[int],
        highlight: list[int],
    ) -> None:
        dpg = self._safe_dpg()
        if dpg is None:
            return

        entity = row["entity"]
        eid = row["id"]
        kind = row["kind"]
        name = row["name"]
        depth = max(0, int(row["depth"]))

        safe = eid.replace(" ", "_").replace(".", "_") or "row"
        row_tag = f"notebook_row_{safe}"
        is_selected = (self._selected_id == eid)

        try:
            with dpg.group(horizontal=True, tag=row_tag):
                # Indent by depth via leading spacer text.
                if depth > 0:
                    try:
                        dpg.add_text(" " * (depth * 2))
                    except Exception:
                        pass

                # Selection highlighter overlay — a coloured prefix glyph
                # that reads as a felt-tip stroke on the page.
                if is_selected:
                    try:
                        dpg.add_text(
                            "|", color=highlight,
                            tag=f"{self._HIGHLIGHT_TAG}_{safe}",
                        )
                    except Exception:
                        pass

                # Badge — small coloured glyph standing in for the SVG.
                badge_glyph = self._badge_glyph(kind)
                try:
                    dpg.add_text(badge_glyph, color=accent)
                except Exception:
                    pass

                # Entity name (handwritten label).
                try:
                    dpg.add_button(
                        label=name,
                        callback=lambda s, a, u=entity: self._handle_select(u),
                        width=-90,
                        height=18,
                    )
                except Exception:
                    pass

                # Heart-shaped visibility toggle.
                vis_val = bool(getattr(entity, "visible", True))
                try:
                    dpg.add_checkbox(
                        label="<3",
                        default_value=vis_val,
                        callback=lambda s, a, u=entity: self._handle_toggle_visible(u, a),
                    )
                except Exception:
                    pass

                # Tiny key-shaped lock toggle.
                lock_val = bool(getattr(entity, "locked", False))
                try:
                    dpg.add_checkbox(
                        label="key",
                        default_value=lock_val,
                        callback=lambda s, a, u=entity: self._handle_toggle_lock(u, a),
                    )
                except Exception:
                    pass
        except Exception:
            # Stub-DPG fallback — flat call path.
            try:
                dpg.add_text(name, color=ink, parent=self._parent_tag)
            except Exception:
                pass

        if is_first_overall:
            try:
                handle = add_sticker_corner(row_tag, "sparkle", "TR")
                self._sticker_handles.append(handle)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_search_changed(self, sender, app_data, user_data) -> None:
        self._search_text = str(app_data or "")
        self.refresh()

    def _handle_select(self, entity: Any) -> None:
        self._selected_id = self._entity_id(entity)
        try:
            self._on_select(entity)
        except Exception:
            pass
        # Trigger a re-paint so the highlighter stroke lands on the new row.
        if self._built:
            self.refresh()

    def _handle_toggle_visible(self, entity: Any, value: Any) -> None:
        if hasattr(entity, "visible"):
            try:
                entity.visible = bool(value)
            except Exception:
                pass

    def _handle_toggle_lock(self, entity: Any, value: Any) -> None:
        if hasattr(entity, "locked"):
            try:
                entity.locked = bool(value)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _entity_id(entity: Any) -> str:
        """Return a stable id string for *entity*."""
        eid = getattr(entity, "id", None)
        if isinstance(eid, str) and eid:
            return eid
        name = getattr(entity, "name", None)
        if isinstance(name, str) and name:
            return name
        return f"{type(entity).__name__}_{id(entity)}"

    @staticmethod
    def _entity_name(entity: Any) -> str:
        name = getattr(entity, "name", None)
        if isinstance(name, str) and name:
            return name
        label = getattr(entity, "label", None)
        if isinstance(label, str) and label:
            return label
        return type(entity).__name__

    @staticmethod
    def _badge_glyph(kind: str) -> str:
        """ASCII-ish stand-in for the SVG badge — used by the DPG text path."""
        return {
            "entity":   "*",
            "body":     "fx",
            "joint":    "oo",
            "light":    "()",
            "camera":   "@",
            "mesh":     "<>",
            "humanoid": "&",
            "material": "##",
            "rope":     "~~",
            "ragdoll":  "%",
            "zone":     "[]",
        }.get(kind, "*")

    def _safe_dpg(self) -> Any | None:
        try:
            import dearpygui.dearpygui as dpg
            return dpg
        except Exception:
            return None


# ---------------------------------------------------------------------------
# SVG icon factory — kept module-level so consumers (theme registry,
# documentation generators) can ask for a real rasterisable icon without
# instantiating the outliner first.
# ---------------------------------------------------------------------------


def make_badge_icon(kind: str, size: int = 16) -> SVGIcon:
    """Return an :class:`SVGIcon` for the given entity kind.

    The icon is constructed from the embedded SVG library; ``size`` picks
    the rasterised texture edge length.
    """
    validate_non_empty_str("kind", "make_badge_icon", kind)
    svg = badge_svg(kind)
    return SVGIcon(svg_xml=svg, size=size)


__all__ = [
    "NotebookOutliner",
    "badge_label",
    "badge_svg",
    "classify_entity",
    "make_badge_icon",
]
