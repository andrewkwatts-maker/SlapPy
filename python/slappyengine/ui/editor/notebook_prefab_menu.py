"""``NotebookPrefabMenu`` — prefab-library spawn card grid.

An extension sibling of :class:`slappyengine.ui.editor.notebook_spawn_menu.NotebookSpawnMenu`.
Where the base spawn menu deals in *specs* (dataclasses the user fills
in through a modal), this panel deals in *prefabs*: fully-formed YAML
recipes registered in a :class:`slappyengine.prefabs.PrefabLibrary` that
spawn straight into the world.

Presentation is deliberately a close cousin of the trading-card deck in
``notebook_spawn_menu`` — small 96×96 diary-themed cards laid out in a
grid, with washi-tape headers, ink-on-paper titles, and a corner badge
showing node/joint counts. A header row hosts a category dropdown +
search box; right-click on a card opens the Spawn / Spawn N / Copy Name
/ View YAML context menu.

This module is **integration only**: it never touches
``notebook_spawn_menu.py`` (Z1-hardened, hands-off) and never touches
the ``slappyengine.prefabs`` package (Y3 landing, read-only). It
extends the presentation surface by wrapping the library from the
outside.

Design provenance
-----------------

* Task **Z2** — Prefab spawn integration (2026-07-04 sprint).
* Style reference: :mod:`slappyengine.ui.editor.notebook_spawn_menu`
  (``SpawnCard`` dataclass + ``_build_cards`` / hover / recents layout).
* Library reference: :class:`slappyengine.prefabs.library.PrefabLibrary`.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from slappyengine._validation import (
    validate_callable,
    validate_non_empty_str,
    validate_positive_int,
)
from slappyengine.prefabs import CATEGORIES, Prefab, PrefabLibrary
from slappyengine.ui.widgets.notebook_theme import (
    register_theme_listener,
    resolve_theme,
    unregister_theme_listener,
)

_LOG = logging.getLogger(__name__)

# Module-level flag toggled by the editor shell when it has a live DPG
# context. Guards native-code paths that access-violate without one
# (clipboard, modal window creation) so headless tests stay safe.
_DPG_CONTEXT_LIVE: bool = False


def mark_dpg_context_live(is_live: bool) -> None:
    """Flip the module-level ``_DPG_CONTEXT_LIVE`` guard.

    Called by :class:`slappyengine.ui.editor.shell.EditorShell` after
    ``dpg.create_context()`` / ``dpg.setup_dearpygui()`` succeed. The
    flag is a plain boolean rather than a runtime probe because the
    real DPG's ``is_dearpygui_running`` itself triggers a native crash
    when called without a context.
    """
    global _DPG_CONTEXT_LIVE
    _DPG_CONTEXT_LIVE = bool(is_live)


# ---------------------------------------------------------------------------
# Category-emoji-glyph placeholders — pure ASCII so PIL / DPG never
# stumble over unicode font gaps (mirrors the sprite-audit lesson from
# the 2026-05 sprint tick where Unicode arrows silently rendered blank).
# ---------------------------------------------------------------------------


CATEGORY_GLYPHS: dict[str, str] = {
    "props":      "[#]",   # A crate.
    "characters": "[@]",   # A humanoid.
    "vehicles":   "[V]",   # A vehicle.
    "particles":  "[*]",   # A spark.
    "structural": "[|]",   # A beam / rope.
}

#: The category filter dropdown always leads with an "All" option.
ALL_CATEGORY: str = "All"

#: The dropdown options — kept module-level so tests can enumerate them
#: without constructing the panel.
CATEGORY_OPTIONS: tuple[str, ...] = (ALL_CATEGORY,) + tuple(
    c.title() for c in CATEGORIES
)


def _category_glyph(category: str) -> str:
    """Return the fallback ASCII glyph for *category* (empty on unknown)."""
    return CATEGORY_GLYPHS.get(category, "[?]")


def _prefab_badge(prefab: Prefab) -> str:
    """Render the ``"Nn / Jj"`` corner badge from *prefab* geometry.

    The node count is inferred from the body-spec kind (best-effort —
    ``point`` / ``circle`` → 1, ``box`` → 4, ``rope`` / ``chain`` →
    ``node_count`` / ``link_count`` fields, ``ragdoll`` → bone list, etc).
    The joint count is ``len(prefab.joint_specs)`` for prefab-level
    joints plus any implicit joints introduced by the body kind (4
    edge + 2 brace for boxes; ``link_count-1`` for chains; ``node_count
    -1`` for ropes).
    """
    kind = prefab.body_spec.get("kind", "")
    node_count = 1
    joint_count = len(prefab.joint_specs)
    if kind == "box":
        node_count = 4
        joint_count += 6  # 4 edges + 2 diagonals
    elif kind == "rope":
        n = int(prefab.body_spec.get("node_count", 5))
        node_count = n
        joint_count += max(n - 1, 0)
    elif kind == "chain":
        n = int(prefab.body_spec.get("link_count", 5))
        node_count = n
        joint_count += max(n - 1, 0)
    elif kind == "ragdoll":
        bones = prefab.body_spec.get("bones") or []
        # Ragdoll build creates 1 root + one node per bone.
        node_count = max(len(bones), 1)
        joint_count += node_count - 1
    elif kind == "composite":
        raw_nodes = prefab.body_spec.get("nodes") or []
        node_count = max(len(raw_nodes), 1)
    return f"{node_count}n / {joint_count}j"


# ---------------------------------------------------------------------------
# Public constants — the layout knobs so external tests / users can read
# them without owning a menu instance.
# ---------------------------------------------------------------------------


class NotebookPrefabMenu:
    """Prefab spawn-card grid for the notebook editor.

    Parameters
    ----------
    library:
        The :class:`PrefabLibrary` to display. When ``None`` (the
        default) the constructor calls :meth:`PrefabLibrary.load_baked`
        + overlays ``~/.slappyengine/prefabs/`` so the panel has content
        out of the box.
    on_spawn:
        Optional callback ``on_spawn(prefab_name: str) -> None`` invoked
        on a card click. When absent, :meth:`spawn` falls back to a
        default handler that requires a world + cursor position to be
        bound via :meth:`set_world`.
    world:
        Optional world reference used by the default spawn handler.
    cursor_position:
        Optional cursor position for the default spawn handler.

    Raises
    ------
    TypeError
        If any argument is the wrong type.
    """

    TITLE = "Prefab Library"

    # MovablePanelWindow minimums — a compact grid needs less width than
    # the spawn-menu deck since the cards are 96×96 rather than 120×160.
    MIN_WIDTH: int = 460
    MIN_HEIGHT: int = 360

    # Layout constants.
    CARD_WIDTH: int = 96
    CARD_HEIGHT: int = 96
    CARDS_PER_ROW: int = 4

    # ------------------------------------------------------------------

    def __init__(
        self,
        library: PrefabLibrary | None = None,
        on_spawn: Callable[[str], None] | None = None,
        world: Any | None = None,
        cursor_position: tuple[float, float] = (0.0, 0.0),
    ) -> None:
        if library is not None and not isinstance(library, PrefabLibrary):
            raise TypeError(
                f"NotebookPrefabMenu: library must be a PrefabLibrary or None; "
                f"got {type(library).__name__}"
            )
        if on_spawn is not None:
            validate_callable("on_spawn", "NotebookPrefabMenu", on_spawn)

        self._library: PrefabLibrary = (
            library if library is not None else self._bootstrap_library()
        )
        self._on_spawn: Callable[[str], None] | None = on_spawn
        self._world = world
        self._cursor_position: tuple[float, float] = tuple(cursor_position)  # type: ignore[assignment]

        # Filter state — category dropdown + search box.
        self._category: str = ALL_CATEGORY
        self._search: str = ""

        # Context menu state — most-recently right-clicked card.
        self._context_prefab: str | None = None
        self._context_open: bool = False

        # View-YAML modal state — {"name": str, "yaml": str} when open.
        self._yaml_modal: dict[str, Any] | None = None

        # Build lifecycle.
        self._built: bool = False
        self._is_open: bool = False
        self._parent_tag: str | int | None = None
        self._card_tags: dict[str, str] = {}

        # Theme cache — refreshed on listener fire.
        self._theme = resolve_theme()
        self._paper = self._theme.color("paper", (250, 246, 235, 255))
        self._ink = self._theme.color("ink", (40, 40, 60, 255))
        self._accent = self._theme.color("accent", (220, 120, 160, 255))
        self._washi = self._theme.color("washi", (180, 200, 230, 255))

        # Register theme listener.
        register_theme_listener(self._on_theme_changed)

        # Call log — headless-test assertions read this.
        self.call_log: list[tuple[Any, ...]] = []

    # ==================================================================
    # Library management
    # ==================================================================

    @staticmethod
    def _bootstrap_library() -> PrefabLibrary:
        """Bake defaults + load user + baked YAMLs into a fresh library.

        Best-effort — a missing baked directory or unreadable user
        directory silently degrades to whatever the library manages to
        load. The panel still renders (as the empty-state placeholder)
        so a broken install doesn't crash the editor.
        """
        lib = PrefabLibrary()
        # Copy baked → user (idempotent) so downstream code can edit
        # without touching the wheel.
        try:
            lib.bake_defaults()
        except Exception as exc:
            _LOG.warning(
                "NotebookPrefabMenu.bootstrap: bake_defaults raised %s: %s",
                type(exc).__name__, exc,
            )
        # Prefer the user directory (overlays baked). Load baked first
        # so user copies can override name-clashes.
        try:
            lib.load_baked()
        except Exception as exc:
            _LOG.warning(
                "NotebookPrefabMenu.bootstrap: load_baked raised %s: %s",
                type(exc).__name__, exc,
            )
        try:
            user_dir = PrefabLibrary.USER_DIR
            if user_dir.is_dir():
                lib.load_from_dir(user_dir)
        except Exception as exc:
            _LOG.warning(
                "NotebookPrefabMenu.bootstrap: user-dir load raised %s: %s",
                type(exc).__name__, exc,
            )
        return lib

    @property
    def library(self) -> PrefabLibrary:
        """Return the currently displayed :class:`PrefabLibrary`."""
        return self._library

    def set_library(self, lib: PrefabLibrary) -> None:
        """Swap the displayed library — clears + rebuilds the card grid.

        Raises
        ------
        TypeError
            If *lib* is not a :class:`PrefabLibrary`.
        """
        if not isinstance(lib, PrefabLibrary):
            raise TypeError(
                f"NotebookPrefabMenu.set_library: lib must be a "
                f"PrefabLibrary; got {type(lib).__name__}"
            )
        self._library = lib
        # Reset filter state so a fresh library isn't hidden by stale
        # dropdown / search entries. (This mirrors the content browser's
        # rebuild-on-project-swap behaviour.)
        self._category = ALL_CATEGORY
        self._search = ""
        self._card_tags.clear()
        self.call_log.append(("set_library", len(lib)))
        # Rebuild the grid when we're already built.
        if self._built and self._parent_tag is not None:
            self._rebuild_grid()

    # ==================================================================
    # Callback wiring
    # ==================================================================

    def set_on_spawn(self, callback: Callable[[str], None]) -> None:
        """Subscribe to card-click spawn events.

        Signature: ``callback(prefab_name: str) -> None``.
        """
        validate_callable("callback", "NotebookPrefabMenu.set_on_spawn", callback)
        self._on_spawn = callback
        self.call_log.append(("set_on_spawn",))

    def set_world(
        self,
        world: Any,
        cursor_position: tuple[float, float] = (0.0, 0.0),
    ) -> None:
        """Bind the *world* + *cursor_position* used by the default spawn handler.

        Only relevant when no ``on_spawn`` callback is registered — with
        a callback set, the panel forwards raw prefab names and lets the
        caller decide what to do.
        """
        self._world = world
        self._cursor_position = tuple(cursor_position)  # type: ignore[assignment]

    # ==================================================================
    # Filter state
    # ==================================================================

    @property
    def category(self) -> str:
        """The current category filter (``"All"`` or a Title-case category)."""
        return self._category

    def set_category(self, category: str) -> None:
        """Set the category filter — must be one of :data:`CATEGORY_OPTIONS`."""
        validate_non_empty_str("category", "NotebookPrefabMenu.set_category", category)
        if category not in CATEGORY_OPTIONS:
            raise ValueError(
                f"NotebookPrefabMenu.set_category: category must be one of "
                f"{list(CATEGORY_OPTIONS)}; got {category!r}"
            )
        self._category = category
        self.call_log.append(("set_category", category))

    @property
    def search(self) -> str:
        """The current substring search term (lowercased match, empty = all)."""
        return self._search

    def set_search(self, text: str) -> None:
        """Set the substring search filter (case-insensitive)."""
        if not isinstance(text, str):
            raise TypeError(
                f"NotebookPrefabMenu.set_search: text must be str; "
                f"got {type(text).__name__}"
            )
        self._search = text.strip()
        self.call_log.append(("set_search", self._search))

    # ==================================================================
    # Visible prefabs — filter+search applied
    # ==================================================================

    def visible_prefabs(self) -> list[Prefab]:
        """Return prefabs after applying the category + search filters.

        Sort order is the library's own — ``list_all()`` returns names
        sorted alphabetically so downstream tests get a deterministic
        card order.
        """
        entries: list[Prefab] = self._library.list_all()
        if self._category != ALL_CATEGORY:
            wanted = self._category.lower()
            entries = [p for p in entries if p.category == wanted]
        if self._search:
            needle = self._search.lower()
            entries = [
                p for p in entries
                if needle in p.name.lower() or needle in p.category.lower()
            ]
        return entries

    def visible_count(self) -> int:
        """Return the number of prefabs currently visible."""
        return len(self.visible_prefabs())

    def is_empty(self) -> bool:
        """Return ``True`` when the library holds zero prefabs."""
        return len(self._library) == 0

    # ==================================================================
    # Card click → spawn
    # ==================================================================

    def click_card(self, prefab_name: str) -> bool:
        """Simulate a left-click on the card for *prefab_name*.

        Fires the registered ``on_spawn`` callback when present;
        otherwise falls through to the default handler which calls
        :meth:`Prefab.spawn` against the bound world.

        Returns
        -------
        bool
            ``True`` when the spawn was dispatched, ``False`` when the
            prefab id is unknown (a warning is logged so silent drops
            surface in CI).
        """
        validate_non_empty_str(
            "prefab_name", "NotebookPrefabMenu.click_card", prefab_name,
        )
        prefab = self._library.get(prefab_name)
        if prefab is None:
            _LOG.warning(
                "NotebookPrefabMenu.click_card: unknown prefab %r "
                "(known: %s)",
                prefab_name, self._library.list_names(),
            )
            return False
        self.call_log.append(("click_card", prefab_name))
        if self._on_spawn is not None:
            try:
                self._on_spawn(prefab_name)
            except Exception as exc:
                _LOG.warning(
                    "NotebookPrefabMenu.click_card: on_spawn(%r) raised "
                    "%s: %s",
                    prefab_name, type(exc).__name__, exc,
                )
                return False
            return True
        # Default handler.
        return self._default_spawn(prefab, count=1)

    def _default_spawn(self, prefab: Prefab, count: int) -> bool:
        """Fallback spawn — requires a bound world."""
        if self._world is None:
            _LOG.warning(
                "NotebookPrefabMenu._default_spawn: no world bound and "
                "no on_spawn callback registered; dropping spawn of %r",
                prefab.name,
            )
            return False
        ok = True
        for _ in range(count):
            try:
                prefab.spawn(
                    self._world,
                    self._cursor_position,
                    library=self._library,
                )
            except Exception as exc:
                _LOG.warning(
                    "NotebookPrefabMenu._default_spawn: prefab %r "
                    "spawn raised %s: %s",
                    prefab.name, type(exc).__name__, exc,
                )
                ok = False
        return ok

    # ==================================================================
    # Right-click context menu
    # ==================================================================

    def open_context_menu(self, prefab_name: str) -> bool:
        """Open the context menu for *prefab_name*.

        Returns
        -------
        bool
            ``True`` when a valid card was opened; ``False`` when the
            prefab is unknown.
        """
        validate_non_empty_str(
            "prefab_name", "NotebookPrefabMenu.open_context_menu", prefab_name,
        )
        if self._library.get(prefab_name) is None:
            _LOG.warning(
                "NotebookPrefabMenu.open_context_menu: unknown prefab %r",
                prefab_name,
            )
            return False
        self._context_prefab = prefab_name
        self._context_open = True
        self.call_log.append(("context_menu_open", prefab_name))
        return True

    def close_context_menu(self) -> None:
        """Close the right-click context menu (no-op when already closed)."""
        if self._context_open:
            self.call_log.append(("context_menu_close", self._context_prefab))
        self._context_open = False

    @property
    def context_prefab(self) -> str | None:
        """Return the prefab id the context menu is currently anchored to."""
        return self._context_prefab if self._context_open else None

    def context_spawn(self) -> bool:
        """Context-menu Spawn action — spawn once, close the menu."""
        if not self._context_open or self._context_prefab is None:
            return False
        name = self._context_prefab
        self.close_context_menu()
        return self.click_card(name)

    def context_spawn_n(self, count: int) -> bool:
        """Context-menu Spawn N action — spawn *count* copies, close the menu.

        Uses the ``on_spawn`` callback when registered (fired once per
        copy) or falls through to the default handler otherwise.
        """
        validate_positive_int(
            "count", "NotebookPrefabMenu.context_spawn_n", count,
        )
        if not self._context_open or self._context_prefab is None:
            return False
        name = self._context_prefab
        prefab = self._library.get(name)
        if prefab is None:
            self.close_context_menu()
            return False
        self.call_log.append(("context_spawn_n", name, count))
        self.close_context_menu()
        if self._on_spawn is not None:
            ok = True
            for _ in range(count):
                try:
                    self._on_spawn(name)
                except Exception as exc:
                    _LOG.warning(
                        "NotebookPrefabMenu.context_spawn_n: on_spawn(%r) "
                        "raised %s: %s",
                        name, type(exc).__name__, exc,
                    )
                    ok = False
            return ok
        return self._default_spawn(prefab, count=count)

    def context_copy_name(self) -> str | None:
        """Context-menu Copy Name — returns the copied string (or ``None``).

        Copies to the system clipboard via ``dearpygui`` when available;
        the returned string is *also* the raw prefab id so headless
        tests can assert without a clipboard.
        """
        if not self._context_open or self._context_prefab is None:
            return None
        name = self._context_prefab
        self.call_log.append(("context_copy_name", name))
        dpg = self._safe_dpg()
        if dpg is not None and self._dpg_context_alive(dpg):
            try:
                dpg.set_clipboard_text(name)
            except Exception:
                pass
        # Note: when DPG has no live context, the clipboard write is
        # skipped by design — real DPG's ``set_clipboard_text`` is a
        # native-code access violation without a viewport (Z1 lesson).
        self.close_context_menu()
        return name

    def context_view_yaml(self) -> str | None:
        """Context-menu View YAML — open a modal with the prefab's YAML.

        Returns the YAML text (for headless-test assertions) or ``None``
        when the context menu is closed / anchored to an unknown prefab.
        """
        if not self._context_open or self._context_prefab is None:
            return None
        name = self._context_prefab
        prefab = self._library.get(name)
        if prefab is None:
            self.close_context_menu()
            return None
        try:
            text = prefab.to_yaml()
        except Exception as exc:
            _LOG.warning(
                "NotebookPrefabMenu.context_view_yaml: to_yaml(%r) raised "
                "%s: %s",
                name, type(exc).__name__, exc,
            )
            text = f"# error: {exc}\n"
        self._yaml_modal = {"name": name, "yaml": text}
        self.call_log.append(("context_view_yaml", name))
        self.close_context_menu()
        # Best-effort DPG modal build.
        dpg = self._safe_dpg()
        if dpg is not None and self._dpg_context_alive(dpg):
            modal_tag = f"notebook_prefab_yaml_modal_{id(self)}"
            self._yaml_modal["modal_tag"] = modal_tag
            try:
                with dpg.window(
                    label=f"YAML: {name}",
                    modal=True,
                    tag=modal_tag,
                    width=520,
                    height=400,
                ):
                    try:
                        dpg.add_text(text, color=list(self._ink))
                    except Exception:
                        pass
                    try:
                        dpg.add_button(
                            label="Close",
                            callback=lambda *_: self.close_yaml_modal(),
                        )
                    except Exception:
                        pass
            except Exception:
                pass
        return text

    def close_yaml_modal(self) -> bool:
        """Tear down the currently open YAML modal (best-effort)."""
        if self._yaml_modal is None:
            return False
        dpg = self._safe_dpg()
        tag = self._yaml_modal.get("modal_tag")
        if (
            dpg is not None
            and isinstance(tag, str)
            and self._dpg_context_alive(dpg)
        ):
            try:
                if dpg.does_item_exist(tag):
                    dpg.delete_item(tag)
            except Exception:
                pass
        self._yaml_modal = None
        return True

    @property
    def yaml_modal(self) -> dict[str, Any] | None:
        """Return the currently open YAML modal state (or ``None``)."""
        return self._yaml_modal

    # ==================================================================
    # Build / open lifecycle
    # ==================================================================

    def build(self, parent_tag: int | str) -> bool:
        """Materialise the panel under *parent_tag*.

        Headless-safe — every DPG call is guarded so tests can drive
        the state machine without a real GUI context.
        """
        if isinstance(parent_tag, str):
            validate_non_empty_str(
                "parent_tag", "NotebookPrefabMenu.build", parent_tag,
            )
        elif not isinstance(parent_tag, int):
            raise TypeError(
                "NotebookPrefabMenu.build: parent_tag must be str or int; "
                f"got {type(parent_tag).__name__}"
            )
        self._parent_tag = parent_tag
        self._built = True
        self.call_log.append(("build", parent_tag))

        dpg = self._safe_dpg()
        if dpg is None or not self._dpg_context_alive(dpg):
            return True

        root_tag = f"notebook_prefab_menu_{id(self)}"
        try:
            with dpg.child_window(
                parent=parent_tag,
                tag=root_tag,
                border=False,
                autosize_x=True,
                height=-1,
            ):
                self._build_header(dpg)
                self._build_grid(dpg)
        except Exception:
            # Stub-DPG / context-manager-less fallback.
            self._build_header(dpg)
            self._build_grid(dpg)
        return True

    def open(self) -> None:
        """Mark the panel open (called by the shell after a toolbar click)."""
        self._is_open = True
        self.call_log.append(("open",))

    def close(self) -> None:
        """Close the panel + any lingering context menu / modal."""
        self._is_open = False
        if self._context_open:
            self.close_context_menu()
        if self._yaml_modal is not None:
            self.close_yaml_modal()
        self.call_log.append(("close",))

    def destroy(self) -> None:
        """Detach the theme listener + reset build state."""
        try:
            unregister_theme_listener(self._on_theme_changed)
        except Exception:
            pass
        self._built = False
        self._card_tags.clear()

    @property
    def is_built(self) -> bool:
        """``True`` after :meth:`build` has been invoked at least once."""
        return self._built

    @property
    def is_open(self) -> bool:
        """``True`` between :meth:`open` and :meth:`close`."""
        return self._is_open

    # ==================================================================
    # DPG rendering
    # ==================================================================

    def _build_header(self, dpg: Any) -> None:
        """Render the category dropdown + search box header row."""
        washi = list(self._washi)
        ink = list(self._ink)
        try:
            dpg.add_text(self.TITLE, color=ink)
        except Exception:
            pass
        try:
            dpg.add_text("================================", color=washi)
        except Exception:
            pass
        try:
            with dpg.group(horizontal=True):
                try:
                    dpg.add_combo(
                        items=list(CATEGORY_OPTIONS),
                        default_value=self._category,
                        width=140,
                        callback=(
                            lambda s, a, u: self._on_category_changed(a)
                        ),
                    )
                except Exception:
                    pass
                try:
                    dpg.add_input_text(
                        hint="Search prefabs",
                        default_value=self._search,
                        width=200,
                        callback=(
                            lambda s, a, u: self._on_search_changed(a)
                        ),
                    )
                except Exception:
                    pass
        except Exception:
            pass
        try:
            dpg.add_separator()
        except Exception:
            pass

    def _on_category_changed(self, value: Any) -> None:
        """DPG combo callback — safe on any value."""
        if isinstance(value, str) and value in CATEGORY_OPTIONS:
            self.set_category(value)
            self._rebuild_grid()

    def _on_search_changed(self, value: Any) -> None:
        """DPG input-text callback — safe on any value."""
        if isinstance(value, str):
            self.set_search(value)
            self._rebuild_grid()

    def _build_grid(self, dpg: Any) -> None:
        """Render the visible-prefab grid, or the empty-state placeholder."""
        grid_tag = f"notebook_prefab_grid_{id(self)}"
        entries = self.visible_prefabs()
        if not entries:
            self._build_empty_state(dpg, reason=(
                "empty" if self.is_empty() else "no_match"
            ))
            return
        try:
            with dpg.child_window(
                tag=grid_tag,
                border=False,
                autosize_x=True,
                height=-1,
            ):
                self._build_grid_rows(dpg, entries)
        except Exception:
            self._build_grid_rows(dpg, entries)

    def _build_grid_rows(self, dpg: Any, entries: list[Prefab]) -> None:
        """Lay entries out in rows of :data:`CARDS_PER_ROW`."""
        per_row = self.CARDS_PER_ROW
        for row_start in range(0, len(entries), per_row):
            row = entries[row_start: row_start + per_row]
            try:
                with dpg.group(horizontal=True):
                    for prefab in row:
                        self._build_card(dpg, prefab)
            except Exception:
                for prefab in row:
                    self._build_card(dpg, prefab)

    def _build_card(self, dpg: Any, prefab: Prefab) -> None:
        """Render one 96×96 prefab card."""
        card_tag = f"notebook_prefab_card_{prefab.name}"
        self._card_tags[prefab.name] = card_tag
        try:
            with dpg.child_window(
                tag=card_tag,
                width=self.CARD_WIDTH,
                height=self.CARD_HEIGHT,
                border=True,
            ):
                self._render_card_body(dpg, prefab)
        except Exception:
            self._render_card_body(dpg, prefab)

    def _render_card_body(self, dpg: Any, prefab: Prefab) -> None:
        """Draw the inside of a card — glyph + name + badge + click button."""
        ink = list(self._ink)
        accent = list(self._accent)
        washi = list(self._washi)

        # Category glyph in the top-left corner.
        try:
            dpg.add_text(_category_glyph(prefab.category), color=accent)
        except Exception:
            pass
        # Prefab name in the middle.
        try:
            dpg.add_text(
                prefab.name,
                color=ink,
                wrap=self.CARD_WIDTH - 8,
            )
        except Exception:
            pass
        # Node / joint badge in the bottom-right corner.
        try:
            dpg.add_text(_prefab_badge(prefab), color=washi)
        except Exception:
            pass
        # Invisible left-click button covering the card body — the way
        # DPG click-through works, we wrap the whole card in a button
        # that triggers :meth:`click_card`. Right-click is delegated to
        # a bound item-handler when the widget registry supports it.
        try:
            dpg.add_button(
                label="Spawn",
                width=self.CARD_WIDTH - 8,
                height=20,
                callback=(
                    lambda s, a, u, *_extra, name=prefab.name:
                    self.click_card(name)
                ),
            )
        except Exception:
            pass

    def _build_empty_state(self, dpg: Any, reason: str) -> None:
        """Render a paper-and-ink empty-state placeholder.

        Two variants:

        * ``"empty"`` — the library is empty. Suggests running
          :meth:`PrefabLibrary.load_baked` or creating one via YAML.
        * ``"no_match"`` — the library holds prefabs, but the current
          filter shows none. Suggests broadening the search.
        """
        ink = list(self._ink)
        accent = list(self._accent)
        try:
            with dpg.child_window(
                tag=f"notebook_prefab_empty_{id(self)}",
                border=False,
                autosize_x=True,
                height=-1,
            ):
                self._render_empty_state(dpg, reason, ink, accent)
        except Exception:
            self._render_empty_state(dpg, reason, ink, accent)

    def _render_empty_state(
        self,
        dpg: Any,
        reason: str,
        ink: list[int],
        accent: list[int],
    ) -> None:
        """Draw the placeholder body (glyph + heading + hint)."""
        try:
            dpg.add_text("[.]", color=accent)
        except Exception:
            pass
        if reason == "empty":
            heading = "No prefabs registered."
            hint = "Add *.prefab.yaml files to ~/.slappyengine/prefabs/"
        else:
            heading = "No prefabs match the current filter."
            hint = "Try widening the category or clearing the search box."
        try:
            dpg.add_text(heading, color=ink)
        except Exception:
            pass
        try:
            dpg.add_text(hint, color=ink, wrap=380)
        except Exception:
            pass

    def _rebuild_grid(self) -> None:
        """Tear down + rebuild the grid child-window (best-effort in DPG)."""
        dpg = self._safe_dpg()
        if (
            dpg is None
            or self._parent_tag is None
            or not self._dpg_context_alive(dpg)
        ):
            return
        # Delete old grid + old empty-state (if present).
        for tag in (
            f"notebook_prefab_grid_{id(self)}",
            f"notebook_prefab_empty_{id(self)}",
        ):
            try:
                if dpg.does_item_exist(tag):
                    dpg.delete_item(tag)
            except Exception:
                pass
        self._card_tags.clear()
        # And re-emit the grid under the same parent.
        try:
            self._build_grid(dpg)
        except Exception:
            pass

    # ==================================================================
    # Theme handling
    # ==================================================================

    def _on_theme_changed(self, _theme: Any) -> None:
        """Theme-listener callback — re-resolve the cached palette."""
        self._theme = resolve_theme()
        self._paper = self._theme.color("paper", self._paper)
        self._ink = self._theme.color("ink", self._ink)
        self._accent = self._theme.color("accent", self._accent)
        self._washi = self._theme.color("washi", self._washi)
        self.call_log.append(("theme_changed",))

    # ==================================================================
    # Helpers
    # ==================================================================

    @staticmethod
    def _safe_dpg() -> Any | None:
        """Return ``dearpygui.dearpygui`` or ``None`` when unavailable."""
        try:
            import dearpygui.dearpygui as dpg
            return dpg
        except Exception:
            return None

    @staticmethod
    def _dpg_context_alive(dpg: Any) -> bool:
        """Return ``True`` when DPG has a live context.

        Real DPG's clipboard + modal + probe calls all trigger native
        access violations when no context is bound (Z1 hardening
        lesson). There is no probe-safe way to ask the real module
        whether it's initialised. Instead, callers rely on this
        sentinel: stubbed DPG modules used in tests set an explicit
        ``__slappy_stub__`` marker; real DPG never has that marker so
        this method returns ``False`` and the native call is skipped.
        Shell code that owns a real viewport can flip
        :data:`slappyengine.ui.editor.notebook_prefab_menu.
        _DPG_CONTEXT_LIVE` to ``True`` before wiring the panel to
        opt into clipboard writes explicitly.
        """
        # Test stubs opt in via a marker attribute.
        if getattr(dpg, "__slappy_stub__", False):
            return True
        # Real DPG: use the module-level opt-in flag flipped by the
        # editor shell after ``create_context`` succeeds.
        return _DPG_CONTEXT_LIVE


__all__ = [
    "ALL_CATEGORY",
    "CATEGORY_GLYPHS",
    "CATEGORY_OPTIONS",
    "NotebookPrefabMenu",
    "mark_dpg_context_live",
]
