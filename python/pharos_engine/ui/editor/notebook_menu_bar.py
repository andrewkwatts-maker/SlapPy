"""``NotebookMenuBar`` — categorised auto-generated menu bar (EE3).

Reads the :data:`pharos_engine.tool_router.REGISTRY` and generates a diary-
themed top-level menu with one submenu per canonical category
(:data:`MENU_ORDER`). Each menu item displays the action label plus the
resolved keyboard shortcut on the right-hand side; clicking dispatches
the action via the bound router. Keyboard shortcuts are resolved through
an optional :class:`~pharos_engine.ui.hotkey_remap.HotkeyMap` so users see
their *actual* rebound shortcut, not the baked default.

Design provenance
-----------------

* EE-batch sprint task **EE3** (2026-07-05) — user directive: "build a
  consolidated ``NotebookMenuBar`` panel that reads the ToolRouter
  registry and generates a categorised menu structure".
* Data sources:
  - :class:`pharos_engine.tool_router.ToolRouter` — action list + labels.
  - :class:`pharos_engine.ui.hotkey_remap.HotkeyMap` — combo -> action_id.
* Diary theme: emoji glyph per category title, hand-drawn separator
  between category groups (see :class:`DoodleSeparator`), accent-colour
  hover state via the shared theme registry.

Menu layout
-----------

::

    +------------------------------------------------------------------+
    | ✎ File   ✂ Edit   ◇ View   ✧ Tool   ▤ Panel   ✿ Theme  ✱ Spawn  |
    +------------------------------------------------------------------+
                    |
                    v (submenu — click ✎ File)
    +------------------------------------+
    |  New Scene              Ctrl+N     |
    |  Open Scene             Ctrl+O     |
    |  ...................................|
    |  Save                   Ctrl+S     |
    |  Save Project                      |
    |  Save Layout As...                 |
    +------------------------------------+

Type-ahead search
-----------------

While a submenu is open, letters typed on the keyboard filter items via
:meth:`NotebookMenuBar.push_type_ahead_char`. Backspace / escape reset
the filter. The panel exposes :meth:`visible_items` so headless tests
can assert against the filtered list without needing a live DPG event
loop.

Headless safety
---------------

All DPG calls funnel through :func:`_safe_dpg`; when no context is live
the panel still populates its in-memory row tree so unit tests can
exercise the full API (build / refresh / dispatch / filter) without a
GUI.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from pharos_engine._validation import (
    validate_non_empty_str,
    validate_str,
)
from pharos_engine.ui.widgets.doodle_separator import DoodleSeparator
from pharos_engine.ui.widgets.notebook_theme import (
    register_theme_listener,
    resolve_theme,
    unregister_theme_listener,
)


_LOG = logging.getLogger(__name__)


# Module-level flag toggled by the editor shell after ``dpg.create_context``
# succeeds. Mirrors the Z2 hardening pattern already used by BB7 hotkey
# help so real DPG never enters ``dpg.menu_bar`` without a live context.
_DPG_CONTEXT_LIVE: bool = False


def mark_dpg_context_live(is_live: bool) -> None:
    """Flip the module-level ``_DPG_CONTEXT_LIVE`` guard.

    :class:`pharos_engine.ui.editor.shell.EditorShell` calls this after
    ``dpg.setup_dearpygui()`` succeeds. Headless tests reach the DPG
    codepath by installing a stub module with ``__slappy_stub__ = True``.
    """
    global _DPG_CONTEXT_LIVE
    _DPG_CONTEXT_LIVE = bool(is_live)


# ---------------------------------------------------------------------------
# Canonical category order + glyphs
# ---------------------------------------------------------------------------


#: The canonical top-level menu order — matches the EE3 task brief.
#: Categories outside this tuple still surface via
#: :meth:`NotebookMenuBar.extra_categories` so the shell can decide how to
#: present them (typically appended after "Help" as an ``Other`` submenu).
MENU_ORDER: tuple[str, ...] = (
    "file",
    "edit",
    "view",
    "tool",
    "panel",
    "theme",
    "spawn",
    "help",
)


#: Diary-themed emoji glyph shown in front of each submenu title. Anything
#: not in this table falls back to the raw category name.
CATEGORY_GLYPHS: dict[str, str] = {
    "file":  "✎",   # ✎ pencil
    "edit":  "✂",   # ✂ scissors
    "view":  "◇",   # ◇ diamond
    "tool":  "✧",   # ✧ four-point star
    "panel": "▤",   # ▤ square with horizontal fill
    "theme": "✿",   # ✿ flower
    "spawn": "✱",   # ✱ heavy asterisk
    "help":  "?",
}


#: Human-friendly title case for each category. Kept separate from the
#: glyphs so themes can render the two in different fonts.
CATEGORY_TITLES: dict[str, str] = {
    "file":  "File",
    "edit":  "Edit",
    "view":  "View",
    "tool":  "Tool",
    "panel": "Panel",
    "theme": "Theme",
    "spawn": "Spawn",
    "help":  "Help",
}


# The "help" category is a UX bucket — the router doesn't populate it yet
# because :meth:`ToolRouter.list_by_category` only surfaces action rows.
# The menu bar promotes the ``editor.help`` action (registered under
# ``view``) into the ``help`` menu so users still find "Welcome" where
# they'd expect it. The alias table below lets us grow this in the future
# without breaking backward compatibility with the tool router.
_CATEGORY_ALIASES: dict[str, tuple[str, ...]] = {
    "help": ("editor.help",),
}


# ---------------------------------------------------------------------------
# Combo pretty-printing (mirrors BB7)
# ---------------------------------------------------------------------------


_KEYCAP_LABELS: dict[str, str] = {
    "ctrl":     "Ctrl",
    "shift":    "Shift",
    "alt":      "Alt",
    "meta":     "Meta",
    "escape":   "Esc",
    "enter":    "Enter",
    "tab":      "Tab",
    "space":    "Space",
    "up":       "Up",
    "down":     "Down",
    "left":     "Left",
    "right":    "Right",
    "backspace": "Bksp",
    "delete":   "Del",
    "home":     "Home",
    "end":      "End",
    "pageup":   "PgUp",
    "pagedown": "PgDn",
    "\\":       "\\",
    "/":        "/",
}


def _pretty_token(token: str) -> str:
    """Return the display label for *token* (best-effort pretty-print)."""
    label = _KEYCAP_LABELS.get(token)
    if label is not None:
        return label
    if len(token) <= 3 and token.startswith("f") and token[1:].isdigit():
        return token.upper()
    if len(token) == 1:
        return token.upper()
    return token.title()


def format_shortcut(combo: str | None) -> str:
    """Format a canonical *combo* as ``Ctrl+Shift+S`` for menu display.

    Returns the empty string when *combo* is ``None`` / empty so callers
    can drop the shortcut column without a special case.
    """
    if not combo:
        return ""
    if not isinstance(combo, str):
        return ""
    chords: list[str] = []
    for chord in combo.strip().split():
        tokens = [t for t in chord.split("+") if t]
        if not tokens:
            continue
        chords.append("+".join(_pretty_token(t) for t in tokens))
    return " ".join(chords)


# ---------------------------------------------------------------------------
# Row model
# ---------------------------------------------------------------------------


class MenuItem:
    """One clickable row inside a :class:`NotebookMenuBar` submenu.

    Purely data-carrying — the panel builds one of these per action and
    hangs them off the parent :class:`MenuGroup`.
    """

    def __init__(
        self,
        action_id: str,
        label: str,
        category: str,
        shortcut: str = "",
        enabled: bool = True,
    ) -> None:
        self.action_id: str = action_id
        self.label: str = label
        self.category: str = category
        self.shortcut: str = shortcut
        self.enabled: bool = enabled

    @property
    def display(self) -> str:
        """Return the "label ................ Ctrl+S" full display string."""
        if self.shortcut:
            return f"{self.label}   {self.shortcut}"
        return self.label

    def matches(self, needle: str) -> bool:
        """Return ``True`` when *needle* (lowercased) matches this row."""
        if not needle:
            return True
        n = needle.lower()
        return (
            n in self.label.lower()
            or n in self.action_id.lower()
            or n in self.shortcut.lower()
        )

    def __repr__(self) -> str:  # pragma: no cover - debug convenience
        return (
            f"MenuItem(action_id={self.action_id!r}, "
            f"category={self.category!r}, shortcut={self.shortcut!r}, "
            f"enabled={self.enabled})"
        )


class MenuGroup:
    """One top-level submenu — a category + its rows."""

    def __init__(self, category: str, glyph: str, title: str) -> None:
        self.category: str = category
        self.glyph: str = glyph
        self.title: str = title
        self.items: list[MenuItem] = []

    @property
    def display_title(self) -> str:
        """Return ``"✎ File"`` style title used in the menu bar."""
        if self.glyph and self.glyph != "?":
            return f"{self.glyph} {self.title}"
        # For the help glyph fall-through, prefix with the '?' too so it
        # still reads visually distinct from a bare "Help".
        return f"{self.glyph} {self.title}" if self.glyph else self.title

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)


# ---------------------------------------------------------------------------
# Safe DPG accessor (mirrors BB7)
# ---------------------------------------------------------------------------


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` if importable AND context is live."""
    try:
        import dearpygui.dearpygui as dpg  # type: ignore[import-not-found]
    except Exception:
        return None
    if not _dpg_context_alive(dpg):
        return None
    return dpg


def _dpg_context_alive(dpg: Any) -> bool:
    """Return ``True`` when DPG has a live context (or is a test stub)."""
    if getattr(dpg, "__slappy_stub__", False):
        return True
    return _DPG_CONTEXT_LIVE


# ---------------------------------------------------------------------------
# NotebookMenuBar
# ---------------------------------------------------------------------------


class NotebookMenuBar:
    """Categorised auto-generated menu bar (EE3).

    Parameters
    ----------
    router:
        Optional :class:`~pharos_engine.tool_router.ToolRouter`. Set via
        constructor or :meth:`set_router`. When ``None`` the panel
        renders an empty menu structure until the router is bound.
    hotkey_map:
        Optional :class:`~pharos_engine.ui.hotkey_remap.HotkeyMap`. When
        set, each row's shortcut column shows the combo bound to the
        action; when ``None`` the shortcut column is blank.
    dispatch_ctx:
        Optional dict passed to :meth:`ToolRouter.dispatch` on each
        click. Defaults to ``{}``. The shell typically injects the
        ``shell`` key so Python fallbacks can find it.
    on_dispatch:
        Optional callback fired with ``(action_id, result)`` after every
        successful dispatch — used by the editor to update the status
        bar / message log. Subscriber exceptions are logged + swallowed.
    """

    TITLE = "Menu Bar"

    _ROOT_TAG = "notebook_menu_bar_root"

    def __init__(
        self,
        router: Any | None = None,
        *,
        hotkey_map: Any | None = None,
        dispatch_ctx: dict[str, Any] | None = None,
        on_dispatch: Callable[[str, Any], None] | None = None,
    ) -> None:
        # ── Call log — must exist before any set_* helper fires ────
        self.call_log: list[tuple[Any, ...]] = []

        # ── Data sources ────────────────────────────────────────────
        self._router: Any | None = None
        self._hotkey_map: Any | None = None

        if dispatch_ctx is not None and not isinstance(dispatch_ctx, dict):
            raise TypeError(
                "NotebookMenuBar: dispatch_ctx must be a dict or None; got "
                f"{type(dispatch_ctx).__name__}"
            )
        self._dispatch_ctx: dict[str, Any] = (
            dict(dispatch_ctx) if dispatch_ctx else {}
        )

        if on_dispatch is not None and not callable(on_dispatch):
            raise TypeError(
                "NotebookMenuBar: on_dispatch must be callable or None; got "
                f"{type(on_dispatch).__name__}"
            )
        self._on_dispatch: Callable[[str, Any], None] | None = on_dispatch

        # ── Type-ahead state (per active menu) ─────────────────────
        # Keyed by category so opening a new submenu resets its filter
        # while other menus keep their in-flight text.
        self._type_ahead: dict[str, str] = {}
        self._active_menu: str | None = None

        # ── Registry snapshot for stale detection ──────────────────
        # We cache the list of action_ids observed at :meth:`build`
        # time so :meth:`refresh` can quickly test whether a rebuild
        # is needed after third-party mutations.
        self._last_snapshot: tuple[str, ...] = ()

        # ── Build lifecycle ────────────────────────────────────────
        self._built: bool = False
        self._parent_tag: str | int | None = None

        # ── Theme cache ────────────────────────────────────────────
        self._theme = resolve_theme()
        self._paper = self._theme.color("paper", (250, 246, 235, 255))
        self._ink = self._theme.color("ink", (40, 40, 60, 255))
        self._accent = self._theme.color("accent", (220, 120, 160, 255))
        self._washi = self._theme.color("washi", (180, 200, 230, 255))
        register_theme_listener(self._on_theme_changed)

        # ── Deferred data-source wiring (needs call_log initialised) ─
        if router is not None:
            self.set_router(router)
        if hotkey_map is not None:
            self.set_hotkey_map(hotkey_map)

    # ==================================================================
    # Accessors
    # ==================================================================

    @property
    def router(self) -> Any | None:
        return self._router

    @property
    def hotkey_map(self) -> Any | None:
        return self._hotkey_map

    @property
    def dispatch_ctx(self) -> dict[str, Any]:
        return self._dispatch_ctx

    @property
    def active_menu(self) -> str | None:
        return self._active_menu

    # ==================================================================
    # Data mutators
    # ==================================================================

    def set_router(self, router: Any) -> None:
        """Bind the :class:`ToolRouter` this panel draws its actions from."""
        if router is None:
            raise TypeError(
                "NotebookMenuBar.set_router: router must not be None"
            )
        # Duck-typed contract — we need list_actions() + dispatch().
        if not callable(getattr(router, "list_actions", None)):
            raise TypeError(
                "NotebookMenuBar.set_router: router must expose "
                "list_actions() -> Iterable[ToolAction]"
            )
        if not callable(getattr(router, "dispatch", None)):
            raise TypeError(
                "NotebookMenuBar.set_router: router must expose "
                "dispatch(action_id, ctx) callable"
            )
        self._router = router
        self.call_log.append(("set_router",))
        if self._built:
            self._rebuild()

    def set_hotkey_map(self, hotkey_map: Any) -> None:
        """Bind the :class:`HotkeyMap` used to resolve shortcut labels.

        Passing ``None`` clears the binding so the shortcut column blanks
        out (useful for tests / "keyboard-off" kiosk modes).
        """
        if hotkey_map is None:
            self._hotkey_map = None
        else:
            # Duck-typed: we need list_all() OR __iter__() so we can walk
            # every binding to build the reverse action_id -> combo map.
            has_iter = (
                callable(getattr(hotkey_map, "list_all", None))
                or callable(getattr(hotkey_map, "__iter__", None))
            )
            if not has_iter:
                raise TypeError(
                    "NotebookMenuBar.set_hotkey_map: hotkey_map must be "
                    "iterable or expose list_all()"
                )
            self._hotkey_map = hotkey_map
        self.call_log.append(("set_hotkey_map",))
        if self._built:
            self._rebuild()

    def set_dispatch_ctx(self, ctx: dict[str, Any]) -> None:
        """Replace the ``dispatch_ctx`` sent with every click."""
        if not isinstance(ctx, dict):
            raise TypeError(
                "NotebookMenuBar.set_dispatch_ctx: ctx must be dict; got "
                f"{type(ctx).__name__}"
            )
        self._dispatch_ctx = dict(ctx)
        self.call_log.append(("set_dispatch_ctx",))

    def on_dispatch(
        self, callback: Callable[[str, Any], None],
    ) -> None:
        """Subscribe to post-dispatch notifications."""
        if not callable(callback):
            raise TypeError(
                "NotebookMenuBar.on_dispatch: callback must be callable; got "
                f"{type(callback).__name__}"
            )
        self._on_dispatch = callback
        self.call_log.append(("on_dispatch",))

    # ==================================================================
    # Shortcut resolution
    # ==================================================================

    def _iter_hotkey_bindings(self):
        """Yield every :class:`HotkeyBinding` in ``self._hotkey_map``."""
        hm = self._hotkey_map
        if hm is None:
            return
        list_all = getattr(hm, "list_all", None)
        if callable(list_all):
            try:
                for b in list_all():
                    yield b
                return
            except Exception:
                pass
        try:
            for b in hm:
                yield b
        except Exception:
            return

    def _build_shortcut_lookup(self) -> dict[str, str]:
        """Build ``action_id -> formatted_shortcut`` from the hotkey map.

        When multiple combos target the same action, the *first*
        encountered wins (insertion order). Disabled bindings
        (``enabled=False``) are skipped so users don't see a shortcut
        they can't actually press.
        """
        lookup: dict[str, str] = {}
        for binding in self._iter_hotkey_bindings():
            combo = getattr(binding, "combo", None)
            action_id = getattr(binding, "action_id", None)
            enabled = getattr(binding, "enabled", True)
            if not combo or not action_id or not enabled:
                continue
            if action_id in lookup:
                continue
            lookup[action_id] = format_shortcut(combo)
        return lookup

    # ==================================================================
    # Group / row assembly
    # ==================================================================

    def _list_router_actions(self) -> list[Any]:
        """Return every registered :class:`ToolAction` (empty when unset)."""
        router = self._router
        if router is None:
            return []
        try:
            return list(router.list_actions())
        except Exception as exc:  # noqa: BLE001
            _LOG.warning(
                "NotebookMenuBar._list_router_actions: router raised %s: %s",
                type(exc).__name__, exc,
            )
            return []

    def _snapshot_action_ids(self) -> tuple[str, ...]:
        """Return the *sorted* tuple of every registered action_id."""
        return tuple(sorted(
            getattr(a, "action_id", "") for a in self._list_router_actions()
        ))

    def groups(self) -> list[MenuGroup]:
        """Return one :class:`MenuGroup` per canonical category (in order).

        Categories with zero actions still return an empty group so the
        menu structure is stable across router mutations — the DPG build
        collapses empty groups so users don't see dead submenus.
        """
        by_category: dict[str, list[MenuItem]] = {c: [] for c in MENU_ORDER}
        shortcut_lookup = self._build_shortcut_lookup()
        actions = self._list_router_actions()
        for action in actions:
            action_id = getattr(action, "action_id", None)
            label = getattr(action, "label", None) or action_id or ""
            category = getattr(action, "category", None) or "misc"
            if not action_id:
                continue
            item = MenuItem(
                action_id=str(action_id),
                label=str(label),
                category=str(category),
                shortcut=shortcut_lookup.get(action_id, ""),
                enabled=bool(getattr(action, "enabled", True)),
            )
            if category in by_category:
                by_category[category].append(item)
        # Category aliases — promote hand-picked actions into the "help"
        # bucket (see :data:`_CATEGORY_ALIASES`). The alias never removes
        # the action from its original category — an entry can appear in
        # both View and Help so users find it either way.
        by_action = {getattr(a, "action_id", ""): a for a in actions}
        for target_cat, alias_ids in _CATEGORY_ALIASES.items():
            for alias_id in alias_ids:
                action = by_action.get(alias_id)
                if action is None:
                    continue
                by_category.setdefault(target_cat, []).append(MenuItem(
                    action_id=alias_id,
                    label=str(getattr(action, "label", alias_id)),
                    category=target_cat,
                    shortcut=shortcut_lookup.get(alias_id, ""),
                    enabled=bool(getattr(action, "enabled", True)),
                ))
        out: list[MenuGroup] = []
        for cat in MENU_ORDER:
            items = by_category.get(cat, [])
            # Stable sort by label so the menu is scannable regardless
            # of registration order.
            items.sort(key=lambda i: (i.label.lower(), i.action_id))
            group = MenuGroup(
                category=cat,
                glyph=CATEGORY_GLYPHS.get(cat, ""),
                title=CATEGORY_TITLES.get(cat, cat.title()),
            )
            group.items = items
            out.append(group)
        return out

    def extra_categories(self) -> list[str]:
        """Return every action category *not* in :data:`MENU_ORDER`.

        The shell can render these as an ``Other`` submenu; this panel
        keeps its top-level surface deliberately narrow so power users
        aren't overwhelmed on first launch.
        """
        seen: set[str] = set()
        for action in self._list_router_actions():
            cat = getattr(action, "category", None) or "misc"
            if cat not in MENU_ORDER:
                seen.add(str(cat))
        return sorted(seen)

    def all_items(self) -> list[MenuItem]:
        """Return every :class:`MenuItem` across every canonical group."""
        out: list[MenuItem] = []
        for group in self.groups():
            out.extend(group.items)
        return out

    def items_for(self, category: str) -> list[MenuItem]:
        """Return the visible items for *category* — applies type-ahead."""
        validate_non_empty_str(
            "category", "NotebookMenuBar.items_for", category,
        )
        for group in self.groups():
            if group.category == category:
                needle = self._type_ahead.get(category, "")
                if not needle:
                    return list(group.items)
                return [i for i in group.items if i.matches(needle)]
        return []

    def visible_items(self) -> list[MenuItem]:
        """Return the visible items for the currently-open submenu.

        Returns an empty list when no submenu is open — the caller can
        then fall through to :meth:`all_items` to show every row.
        """
        if self._active_menu is None:
            return self.all_items()
        return self.items_for(self._active_menu)

    def is_empty(self) -> bool:
        """Return ``True`` when the router registry has no known actions."""
        return len(self._list_router_actions()) == 0

    # ==================================================================
    # Type-ahead
    # ==================================================================

    def open_menu(self, category: str) -> None:
        """Mark *category* as the active submenu.

        Called by the DPG hover / click handler; also usable directly
        from headless tests. Setting a new active menu resets the
        type-ahead filter for that category.
        """
        validate_non_empty_str(
            "category", "NotebookMenuBar.open_menu", category,
        )
        self._active_menu = category
        self._type_ahead[category] = ""
        self.call_log.append(("open_menu", category))

    def close_menu(self) -> None:
        """Clear the active-menu marker (and its type-ahead buffer)."""
        if self._active_menu is not None:
            self._type_ahead.pop(self._active_menu, None)
        self._active_menu = None
        self.call_log.append(("close_menu",))

    def push_type_ahead_char(self, char: str) -> str:
        """Append *char* to the active submenu's type-ahead buffer.

        Returns the new filter string. Characters longer than one code
        point are treated as raw literals so power users can paste
        prefixes; empty strings are no-ops.
        """
        if not isinstance(char, str):
            raise TypeError(
                "NotebookMenuBar.push_type_ahead_char: char must be str"
            )
        if not char:
            return self._type_ahead.get(self._active_menu or "", "")
        if self._active_menu is None:
            # No open submenu — quietly drop.
            return ""
        current = self._type_ahead.get(self._active_menu, "")
        current = current + char
        self._type_ahead[self._active_menu] = current
        self.call_log.append(("type_ahead", self._active_menu, current))
        return current

    def pop_type_ahead_char(self) -> str:
        """Delete the last character from the active type-ahead buffer."""
        if self._active_menu is None:
            return ""
        current = self._type_ahead.get(self._active_menu, "")
        if not current:
            return ""
        current = current[:-1]
        self._type_ahead[self._active_menu] = current
        self.call_log.append(("type_ahead_pop", self._active_menu, current))
        return current

    def clear_type_ahead(self) -> None:
        """Reset the active submenu's type-ahead buffer."""
        if self._active_menu is None:
            return
        self._type_ahead[self._active_menu] = ""
        self.call_log.append(("type_ahead_clear", self._active_menu))

    def get_type_ahead(self, category: str) -> str:
        """Return the type-ahead buffer for *category* (or empty string)."""
        return self._type_ahead.get(category, "")

    # ==================================================================
    # Dispatch
    # ==================================================================

    def dispatch(self, action_id: str) -> Any:
        """Dispatch *action_id* via the bound router.

        Returns the router's return value on success, ``None`` on any
        failure (no router bound, unknown action, dispatch raised).
        The registered :attr:`on_dispatch` callback fires with the
        ``(action_id, result)`` tuple even when the result is ``None``
        so status bars can still surface the click.
        """
        validate_non_empty_str(
            "action_id", "NotebookMenuBar.dispatch", action_id,
        )
        router = self._router
        if router is None:
            self.call_log.append(("dispatch_no_router", action_id))
            return None
        result: Any = None
        try:
            result = router.dispatch(action_id, dict(self._dispatch_ctx))
        except KeyError:
            _LOG.warning(
                "NotebookMenuBar.dispatch: unknown action_id %r",
                action_id,
            )
            result = None
        except Exception as exc:  # noqa: BLE001
            _LOG.warning(
                "NotebookMenuBar.dispatch: %r raised %s: %s",
                action_id, type(exc).__name__, exc,
            )
            result = None
        self.call_log.append(("dispatch", action_id, result))
        if self._on_dispatch is not None:
            try:
                self._on_dispatch(action_id, result)
            except Exception as exc:  # noqa: BLE001
                _LOG.warning(
                    "NotebookMenuBar.dispatch: on_dispatch subscriber "
                    "raised %s: %s", type(exc).__name__, exc,
                )
        return result

    # ==================================================================
    # Build + refresh
    # ==================================================================

    def build(self, parent_tag: str | int) -> None:
        """Render the menu bar under *parent_tag* — headless-safe."""
        self._parent_tag = parent_tag
        self._built = True
        # Cache the snapshot so subsequent :meth:`refresh` calls can
        # decide whether to rebuild.
        self._last_snapshot = self._snapshot_action_ids()

        dpg = _safe_dpg()
        if dpg is None:
            # Still touch the group model so tests can observe build state.
            _ = self.groups()
            self.call_log.append(("build", parent_tag))
            return
        self.call_log.append(("build", parent_tag))

        # DPG's menu_bar attaches inside a window; when the shell already
        # wraps us in a window the ``dpg.menu_bar`` context works. Fall
        # back to a plain group when the enclosing widget doesn't accept
        # a menu bar so the panel still renders *something*.
        menu_bar_cm: Any = None
        try:
            menu_bar_cm = dpg.menu_bar(parent=parent_tag, tag=self._ROOT_TAG)
        except Exception:
            try:
                menu_bar_cm = dpg.group(
                    parent=parent_tag,
                    horizontal=True,
                    tag=self._ROOT_TAG,
                )
            except Exception:
                menu_bar_cm = None

        if menu_bar_cm is None:
            return

        try:
            with menu_bar_cm:
                for i, group in enumerate(self.groups()):
                    if not group.items:
                        continue
                    self._build_group(dpg, group)
                    # Hand-drawn separator between groups. Some DPG
                    # backends will silently ignore this inside a
                    # menu_bar; that's fine — the row separators still
                    # give visual structure.
                    if i < len(MENU_ORDER) - 1:
                        try:
                            DoodleSeparator("dotted").build(self._ROOT_TAG)
                        except Exception:
                            pass
        except Exception:
            # Full-menu failure is a soft-fail — the shell still renders.
            _LOG.warning(
                "NotebookMenuBar.build: menu_bar assembly failed",
                exc_info=True,
            )

    def _build_group(self, dpg: Any, group: MenuGroup) -> None:
        """Render one :class:`MenuGroup` as a DPG submenu."""
        menu_tag = f"notebook_menu_bar__{group.category}"
        try:
            menu_cm = dpg.menu(
                label=group.display_title,
                tag=menu_tag,
            )
        except Exception:
            return
        try:
            with menu_cm:
                for item in group.items:
                    try:
                        dpg.add_menu_item(
                            label=item.display,
                            enabled=item.enabled,
                            callback=self._make_click_callback(item.action_id),
                        )
                    except Exception:
                        # Some DPG versions ignore the enabled kwarg —
                        # retry without it before giving up.
                        try:
                            dpg.add_menu_item(
                                label=item.display,
                                callback=self._make_click_callback(
                                    item.action_id
                                ),
                            )
                        except Exception:
                            pass
        except Exception:
            pass

    def refresh(self) -> bool:
        """Rebuild the menu bar iff the router registry changed.

        Returns ``True`` when a rebuild ran, ``False`` when the cached
        snapshot still matches the router's current action list. Callers
        can chain the return value into a "menu was stale" toast if
        desired.
        """
        current = self._snapshot_action_ids()
        if current == self._last_snapshot:
            self.call_log.append(("refresh_noop",))
            return False
        self._last_snapshot = current
        self.call_log.append(("refresh_rebuild",))
        self._rebuild()
        return True

    def force_refresh(self) -> None:
        """Rebuild the menu regardless of whether the snapshot changed."""
        self._last_snapshot = self._snapshot_action_ids()
        self.call_log.append(("force_refresh",))
        self._rebuild()

    def _rebuild(self) -> None:
        """Tear down + rebuild the DPG tree under ``self._parent_tag``."""
        if not self._built:
            return
        dpg = _safe_dpg()
        if dpg is None:
            return
        # Best-effort teardown — some DPG builds throw on delete_item for
        # a menu_bar tag; ignore.
        try:
            if dpg.does_item_exist(self._ROOT_TAG):
                dpg.delete_item(self._ROOT_TAG)
        except Exception:
            pass
        parent = self._parent_tag
        if parent is None:
            return
        self._built = False
        self.build(parent)

    def destroy(self) -> None:
        """Detach the theme listener and mark the panel torn down."""
        try:
            unregister_theme_listener(self._on_theme_changed)
        except Exception:
            pass
        self._built = False

    # ==================================================================
    # Callbacks
    # ==================================================================

    def _on_theme_changed(self, _theme: Any) -> None:
        self._theme = resolve_theme()
        self._paper = self._theme.color("paper", (250, 246, 235, 255))
        self._ink = self._theme.color("ink", (40, 40, 60, 255))
        self._accent = self._theme.color("accent", (220, 120, 160, 255))
        self._washi = self._theme.color("washi", (180, 200, 230, 255))
        self.call_log.append(("theme_changed",))
        if self._built:
            try:
                self._rebuild()
            except Exception:
                pass

    def _make_click_callback(
        self, action_id: str,
    ) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            try:
                self.dispatch(action_id)
            except Exception as exc:  # noqa: BLE001
                _LOG.warning(
                    "NotebookMenuBar: click on %r dropped: %s",
                    action_id, exc,
                )
        return _cb


__all__ = [
    "CATEGORY_GLYPHS",
    "CATEGORY_TITLES",
    "MENU_ORDER",
    "MenuGroup",
    "MenuItem",
    "NotebookMenuBar",
    "format_shortcut",
    "mark_dpg_context_live",
]
