"""``NotebookHotkeyHelp`` — diary-themed hotkey help + rebind panel (BB7).

Presents the current hotkey binding table as a scannable two-column
diary sheet: the left column shows the key combo rendered as
``[Ctrl] + [S]`` keycap glyphs; the middle column shows the action id +
its human-readable label pulled from
:data:`pharos_engine.tool_router.REGISTRY`; the right column hosts a
``Change`` button that opens a modal capture-next-key rebind flow.

Design provenance
-----------------

* AA-batch sprint task **BB7** (2026-07-05) — user directive: "build a
  diary-themed hotkey help panel that displays the current hotkey ->
  action mapping and lets users rebind".
* Data source: :class:`pharos_engine.ui.hotkey_remap.HotkeyMap` (AA7).
* Preset dropdown loads baked YAMLs from
  :data:`pharos_engine.ui.hotkey_remap.BAKED_HOTKEY_DIR` — the same
  three files (``default.yaml``, ``vim_style.yaml``,
  ``emacs_style.yaml``) the first-launch bootstrapper copies into the
  user's ``~/.pharos_engine/ui/hotkeys/`` directory.
* Action metadata (label + category) is resolved through
  :meth:`ToolRouter.get` against
  :data:`pharos_engine.tool_router.REGISTRY` — unknown ``action_id``
  values still render as rows with an ``"(unknown action)"`` label so
  legacy user maps never disappear silently.

Panel layout
------------

::

    +----------------------------------------------------------------+
    | Hotkey Help                                                    |
    | ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ |
    | Preset: [ Default v ]   [Reset]  [Reload]                      |
    |                                                                |
    | [All] [File] [Edit] [View] [Tool] [Panel] [Theme] [Spawn]      |
    | Search: [_______________________________]                      |
    | .............................................................. |
    |  file                                                          |
    |   [Ctrl] + [S]      editor.save        (Save)         [Change] |
    |   [Ctrl] + [O]      editor.open        (Open Scene)   [Change] |
    | .............................................................. |
    |  edit                                                          |
    |   [Ctrl] + [Z]      editor.undo        (Undo)         [Change] |
    +----------------------------------------------------------------+

Headless safety
---------------

Every ``dearpygui`` call is funnelled through :func:`_safe_dpg`; when
DPG is missing the panel still populates its in-memory state so the
2 000-line test rig can exercise the filter / rebind / preset flows
without a live GUI context.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from pharos_engine._validation import (
    validate_callable,
    validate_non_empty_str,
    validate_str,
)
from pharos_engine.ui.hotkey_remap import (
    BAKED_HOTKEY_DIR,
    HotkeyBinding,
    HotkeyMap,
    default_hotkey_map,
)
from pharos_engine.ui.widgets.doodle_separator import DoodleSeparator
from pharos_engine.ui.widgets.notebook_theme import (
    register_theme_listener,
    resolve_theme,
    unregister_theme_listener,
)


_LOG = logging.getLogger(__name__)


# Module-level flag toggled by the editor shell when it has a live DPG
# context. Guards native-code paths that access-violate without one
# (window / group / context managers). Mirrors the Z2 hardening pattern
# in :mod:`pharos_engine.ui.editor.notebook_prefab_menu`.
_DPG_CONTEXT_LIVE: bool = False


def mark_dpg_context_live(is_live: bool) -> None:
    """Flip the module-level ``_DPG_CONTEXT_LIVE`` guard.

    Called by :class:`pharos_engine.ui.editor.shell.EditorShell` after
    ``dpg.create_context()`` / ``dpg.setup_dearpygui()`` succeed. The
    flag is a plain boolean rather than a runtime probe because the
    real DPG's ``is_dearpygui_running`` itself triggers a native crash
    when called without a context.
    """
    global _DPG_CONTEXT_LIVE
    _DPG_CONTEXT_LIVE = bool(is_live)


# ---------------------------------------------------------------------------
# Categories the filter buttons expose
# ---------------------------------------------------------------------------


#: The "show every row" pseudo-category — always the leftmost button.
ALL_CATEGORY: str = "All"


#: The category filter buttons — matches the task brief plus an "All"
#: umbrella. Categories are matched case-insensitively against the
#: :attr:`ToolAction.category` field on
#: :data:`pharos_engine.tool_router.REGISTRY`.
CATEGORY_OPTIONS: tuple[str, ...] = (
    ALL_CATEGORY,
    "File",
    "Edit",
    "View",
    "Tool",
    "Panel",
    "Theme",
    "Spawn",
)


#: Preset labels shown in the header dropdown. The order maps 1:1 to
#: :data:`_PRESET_YAML_STEMS` so a preset index in one list refers to
#: the same preset in the other.
PRESET_OPTIONS: tuple[str, ...] = ("Default", "Vim", "Emacs")


#: The YAML stems (no extension) each preset label loads from
#: :data:`BAKED_HOTKEY_DIR`. Unknown / missing files fall back to
#: :func:`default_hotkey_map`.
_PRESET_YAML_STEMS: tuple[str, ...] = ("default", "vim_style", "emacs_style")


# ---------------------------------------------------------------------------
# Keycap rendering
# ---------------------------------------------------------------------------


#: Pretty-printed labels for the modifier / leaf tokens the AA7
#: canonicalisation emits. Anything not in this table gets ``.upper()``
#: applied so ``ctrl+s`` -> ``[Ctrl] + [S]``.
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
    "backspace":"Bksp",
    "delete":   "Del",
    "home":     "Home",
    "end":      "End",
    "pageup":   "PgUp",
    "pagedown": "PgDn",
    "\\":       "\\",
    "/":        "/",
}


def _pretty_token(token: str) -> str:
    """Return the display label for *token* (best-effort pretty-print).

    Function keys (``f1``..``f12``) upcase; symbol keys fall through
    literally so ``\\`` and ``/`` still render as themselves.
    """
    label = _KEYCAP_LABELS.get(token)
    if label is not None:
        return label
    if len(token) <= 2 and token[0] == "f" and token[1:].isdigit():
        return token.upper()
    if len(token) == 1:
        return token.upper()
    return token.title()


def render_keycaps(combo: str) -> str:
    """Return the diary-themed ``[Ctrl] + [S]`` rendering of *combo*.

    Multi-chord bindings (``"ctrl+x ctrl+s"`` in the vim preset) are
    rendered chord-by-chord separated by ``", "`` so the row stays
    scannable in a single line.
    """
    if not isinstance(combo, str) or not combo.strip():
        return ""
    chords: list[str] = []
    for chord in combo.strip().split():
        tokens = [t for t in chord.split("+") if t]
        if not tokens:
            continue
        caps = [f"[{_pretty_token(tok)}]" for tok in tokens]
        chords.append(" + ".join(caps))
    return ", ".join(chords)


# ---------------------------------------------------------------------------
# Row model
# ---------------------------------------------------------------------------


class HotkeyHelpRow:
    """One row of the hotkey help table.

    Purely data-carrying — the panel builds one of these per binding
    and mutates the visible list based on the active category / search
    filter.
    """

    def __init__(
        self,
        binding: HotkeyBinding,
        label: str,
        category: str,
        known: bool,
    ) -> None:
        self.binding: HotkeyBinding = binding
        self.label: str = label
        self.category: str = category
        self.known: bool = known

    @property
    def combo(self) -> str:
        return self.binding.combo

    @property
    def action_id(self) -> str:
        return self.binding.action_id

    @property
    def keycaps(self) -> str:
        return render_keycaps(self.binding.combo)

    def __repr__(self) -> str:  # pragma: no cover - debug convenience
        return (
            f"HotkeyHelpRow(combo={self.binding.combo!r}, "
            f"action_id={self.binding.action_id!r}, "
            f"category={self.category!r}, known={self.known})"
        )


# ---------------------------------------------------------------------------
# Safe DPG accessor
# ---------------------------------------------------------------------------


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` if importable AND context is live.

    Real DPG's ``dpg.window`` / ``dpg.group`` / ``dpg.add_text`` all
    access-violate when the native context is missing. Test rigs supply
    a stub module (see :func:`_dpg_context_alive`) marked with
    ``__slappy_stub__`` so they still enter the DPG codepath; real DPG
    requires the editor shell to flip :func:`mark_dpg_context_live`
    first.
    """
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
# NotebookHotkeyHelp
# ---------------------------------------------------------------------------


class NotebookHotkeyHelp:
    """Diary-themed hotkey help + rebind panel (BB7).

    Parameters
    ----------
    hotkey_map:
        The initial :class:`HotkeyMap` to display. When ``None`` (the
        default) the panel loads :func:`default_hotkey_map` so the
        editor has a populated table on first launch.
    router:
        Optional :class:`~pharos_engine.tool_router.ToolRouter` used to
        resolve ``action_id`` -> ``(label, category)``. When ``None``
        the panel imports :data:`pharos_engine.tool_router.REGISTRY`
        lazily on first row-build so unit tests that never touch the
        router still get sensible output.
    on_binding_changed:
        Optional callback fired with the *new* :class:`HotkeyBinding`
        whenever :meth:`commit_rebind` succeeds. Callback exceptions
        are logged + swallowed so a broken subscriber never kills the
        panel.
    initial_category:
        Category button pre-selected on build. Defaults to
        :data:`ALL_CATEGORY`.
    """

    TITLE = "Hotkey Help"

    # MovablePanelWindow minimums — wide enough for keycap glyphs +
    # action id + Change button on a single row.
    MIN_WIDTH: int = 480
    MIN_HEIGHT: int = 320

    _ROOT_TAG = "notebook_hotkey_help_root"
    _HEADER_TAG = "notebook_hotkey_help_header"
    _SEARCH_TAG = "notebook_hotkey_help_search"
    _TABLE_TAG = "notebook_hotkey_help_table"
    _STATUS_TAG = "notebook_hotkey_help_status"

    def __init__(
        self,
        hotkey_map: HotkeyMap | None = None,
        *,
        router: Any | None = None,
        on_binding_changed: Callable[[HotkeyBinding], None] | None = None,
        initial_category: str = ALL_CATEGORY,
    ) -> None:
        if hotkey_map is not None and not isinstance(hotkey_map, HotkeyMap):
            raise TypeError(
                "NotebookHotkeyHelp: hotkey_map must be a HotkeyMap or None; "
                f"got {type(hotkey_map).__name__}"
            )
        if on_binding_changed is not None:
            validate_callable(
                "on_binding_changed",
                "NotebookHotkeyHelp",
                on_binding_changed,
            )
        validate_non_empty_str(
            "initial_category", "NotebookHotkeyHelp", initial_category,
        )
        if initial_category not in CATEGORY_OPTIONS:
            raise ValueError(
                "NotebookHotkeyHelp: initial_category must be one of "
                f"{list(CATEGORY_OPTIONS)}; got {initial_category!r}"
            )

        # ── Data sources ────────────────────────────────────────────
        self._hotkey_map: HotkeyMap = (
            hotkey_map if hotkey_map is not None else default_hotkey_map()
        )
        self._router: Any | None = router
        self._on_binding_changed: Callable[[HotkeyBinding], None] | None = (
            on_binding_changed
        )

        # ── Filter state ────────────────────────────────────────────
        self._category: str = initial_category
        self._search: str = ""

        # ── Preset dropdown state ──────────────────────────────────
        self._preset: str = PRESET_OPTIONS[0]

        # ── Rebind modal state ─────────────────────────────────────
        # When a Change button is clicked we record the combo being
        # rebound here; the next :meth:`capture_key` call commits the
        # new binding. ``None`` means "no rebind in flight".
        self._pending_rebind: str | None = None

        # ── Build lifecycle ────────────────────────────────────────
        self._built: bool = False
        self._parent_tag: str | int | None = None

        # ── Theme cache — refreshed on listener fire ───────────────
        self._theme = resolve_theme()
        self._paper = self._theme.color("paper", (250, 246, 235, 255))
        self._ink = self._theme.color("ink", (40, 40, 60, 255))
        self._accent = self._theme.color("accent", (220, 120, 160, 255))
        self._washi = self._theme.color("washi", (180, 200, 230, 255))

        register_theme_listener(self._on_theme_changed)

        # ── Call log — headless-test hook ──────────────────────────
        self.call_log: list[tuple[Any, ...]] = []

    # ==================================================================
    # Property accessors
    # ==================================================================

    @property
    def hotkey_map(self) -> HotkeyMap:
        """The active :class:`HotkeyMap` (the source of every row)."""
        return self._hotkey_map

    @property
    def router(self) -> Any | None:
        """The bound :class:`ToolRouter` (or ``None`` for the lazy import)."""
        return self._router

    @property
    def category(self) -> str:
        """The current category filter."""
        return self._category

    @property
    def search(self) -> str:
        """The current substring filter."""
        return self._search

    @property
    def preset(self) -> str:
        """The last-selected preset name (from :data:`PRESET_OPTIONS`)."""
        return self._preset

    @property
    def pending_rebind(self) -> str | None:
        """The combo awaiting a rebind key capture (``None`` when idle)."""
        return self._pending_rebind

    # ==================================================================
    # Theme listener
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
                self._rebuild_table()
            except Exception:
                pass

    # ==================================================================
    # Data mutators
    # ==================================================================

    def set_hotkey_map(self, hotkey_map: HotkeyMap) -> None:
        """Swap the source :class:`HotkeyMap` and rebuild the row list."""
        if not isinstance(hotkey_map, HotkeyMap):
            raise TypeError(
                "NotebookHotkeyHelp.set_hotkey_map: hotkey_map must be a "
                f"HotkeyMap; got {type(hotkey_map).__name__}"
            )
        self._hotkey_map = hotkey_map
        self.call_log.append(("set_hotkey_map", len(hotkey_map)))
        if self._built:
            self._rebuild_table()

    def set_router(self, router: Any) -> None:
        """Bind the :class:`ToolRouter` used to resolve action metadata."""
        if router is None:
            raise TypeError(
                "NotebookHotkeyHelp.set_router: router must not be None"
            )
        # Duck-typed — we only need has_action + get; guard so a
        # busted registry object fails fast rather than at first row.
        if not callable(getattr(router, "get", None)):
            raise TypeError(
                "NotebookHotkeyHelp.set_router: router must expose "
                "get(action_id) -> ToolAction | None"
            )
        self._router = router
        self.call_log.append(("set_router",))
        if self._built:
            self._rebuild_table()

    def on_binding_changed(
        self,
        callback: Callable[[HotkeyBinding], None],
    ) -> None:
        """Subscribe to :meth:`commit_rebind` events."""
        validate_callable(
            "callback", "NotebookHotkeyHelp.on_binding_changed", callback,
        )
        self._on_binding_changed = callback
        self.call_log.append(("on_binding_changed",))

    # ==================================================================
    # Filter state
    # ==================================================================

    def set_category(self, category: str) -> None:
        """Set the active category filter — must be in :data:`CATEGORY_OPTIONS`."""
        validate_non_empty_str(
            "category", "NotebookHotkeyHelp.set_category", category,
        )
        if category not in CATEGORY_OPTIONS:
            raise ValueError(
                "NotebookHotkeyHelp.set_category: category must be one of "
                f"{list(CATEGORY_OPTIONS)}; got {category!r}"
            )
        self._category = category
        self.call_log.append(("set_category", category))
        if self._built:
            self._rebuild_table()

    def set_search(self, text: str) -> None:
        """Set the substring filter (matches combo OR action_id)."""
        if not isinstance(text, str):
            raise TypeError(
                "NotebookHotkeyHelp.set_search: text must be str; "
                f"got {type(text).__name__}"
            )
        self._search = text.strip()
        self.call_log.append(("set_search", self._search))
        if self._built:
            self._rebuild_table()

    # ==================================================================
    # Preset dropdown
    # ==================================================================

    def set_preset(self, preset: str) -> None:
        """Load *preset* from :data:`BAKED_HOTKEY_DIR` into the panel.

        Unknown preset names fall back to :func:`default_hotkey_map`
        so a typo can never wipe the visible table.
        """
        validate_non_empty_str(
            "preset", "NotebookHotkeyHelp.set_preset", preset,
        )
        if preset not in PRESET_OPTIONS:
            raise ValueError(
                "NotebookHotkeyHelp.set_preset: preset must be one of "
                f"{list(PRESET_OPTIONS)}; got {preset!r}"
            )
        self._preset = preset
        idx = PRESET_OPTIONS.index(preset)
        stem = _PRESET_YAML_STEMS[idx]
        new_map = self._load_preset_yaml(stem)
        self.call_log.append(("set_preset", preset))
        self.set_hotkey_map(new_map)

    def _load_preset_yaml(self, stem: str) -> HotkeyMap:
        """Load ``BAKED_HOTKEY_DIR/<stem>.yaml`` — fall back to defaults."""
        try:
            path = Path(BAKED_HOTKEY_DIR) / f"{stem}.yaml"
        except Exception:
            return default_hotkey_map()
        if not path.is_file():
            _LOG.warning(
                "NotebookHotkeyHelp: preset yaml %s missing — falling back to default",
                path,
            )
            return default_hotkey_map()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            _LOG.warning(
                "NotebookHotkeyHelp: cannot read preset %s: %s", path, exc,
            )
            return default_hotkey_map()
        try:
            partial = HotkeyMap.from_yaml(text, default_source=stem)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning(
                "NotebookHotkeyHelp: cannot parse preset %s: %s", path, exc,
            )
            return default_hotkey_map()
        # Overlay the partial preset on top of defaults so presets can
        # add new combos without stripping the base map.
        if stem == "default":
            return partial if len(partial) > 0 else default_hotkey_map()
        base = default_hotkey_map()
        return base.merge(partial)

    def reset_to_default(self) -> None:
        """Reload :func:`default_hotkey_map` and reset the preset selector."""
        self._preset = PRESET_OPTIONS[0]
        self.call_log.append(("reset_to_default",))
        self.set_hotkey_map(default_hotkey_map())

    def reload(self) -> None:
        """Re-apply the currently-selected preset — used by the Reload button."""
        self.call_log.append(("reload",))
        self.set_preset(self._preset)

    # ==================================================================
    # Rebind flow
    # ==================================================================

    def start_rebind(self, combo: str) -> bool:
        """Open the rebind modal for *combo*.

        Records *combo* in :attr:`pending_rebind` — the next
        :meth:`capture_key` call replaces the binding.

        Returns ``True`` when *combo* was found in the map, ``False``
        otherwise (the caller can chain the failure to a status bar).
        """
        validate_non_empty_str(
            "combo", "NotebookHotkeyHelp.start_rebind", combo,
        )
        # Normalise via HotkeyMap so callers can pass either canonical
        # or raw combos and hit the same row.
        existing = self._hotkey_map.get(combo)
        if existing is None:
            _LOG.warning(
                "NotebookHotkeyHelp.start_rebind: unknown combo %r "
                "(known: %s)",
                combo, self._hotkey_map.combos(),
            )
            return False
        self._pending_rebind = existing.combo
        self.call_log.append(("start_rebind", existing.combo))
        return True

    def cancel_rebind(self) -> None:
        """Abort the in-flight rebind without touching the map."""
        if self._pending_rebind is None:
            return
        self.call_log.append(("cancel_rebind", self._pending_rebind))
        self._pending_rebind = None

    def capture_key(self, combo: str) -> HotkeyBinding | None:
        """Commit the pending rebind with *combo* as the new key.

        Returns the freshly-inserted :class:`HotkeyBinding` on success,
        or ``None`` when no rebind is pending / the combo is malformed.
        """
        validate_non_empty_str(
            "combo", "NotebookHotkeyHelp.capture_key", combo,
        )
        if self._pending_rebind is None:
            return None
        return self.commit_rebind(self._pending_rebind, combo)

    def commit_rebind(
        self, old_combo: str, new_combo: str,
    ) -> HotkeyBinding | None:
        """Replace the *old_combo* row's key with *new_combo*.

        The action_id / enabled / source fields are preserved via
        :func:`dataclasses.replace`. The new row's ``source`` is
        rewritten to ``"user"`` so it round-trips through
        :meth:`HotkeyMap.to_yaml` as a user override.

        Returns the new :class:`HotkeyBinding` on success, ``None``
        when the old combo is not registered or the new combo is
        malformed.
        """
        validate_non_empty_str(
            "old_combo", "NotebookHotkeyHelp.commit_rebind", old_combo,
        )
        validate_non_empty_str(
            "new_combo", "NotebookHotkeyHelp.commit_rebind", new_combo,
        )
        existing = self._hotkey_map.get(old_combo)
        if existing is None:
            _LOG.warning(
                "NotebookHotkeyHelp.commit_rebind: unknown old_combo %r",
                old_combo,
            )
            return None
        try:
            new_binding = HotkeyBinding(
                combo=new_combo,
                action_id=existing.action_id,
                enabled=existing.enabled,
                source="user",
            )
        except (ValueError, TypeError) as exc:
            _LOG.warning(
                "NotebookHotkeyHelp.commit_rebind: bad new_combo %r: %s",
                new_combo, exc,
            )
            return None
        # Drop the old row + insert the new one. When the canonical
        # form of the new combo matches the old, ``add`` overwrites in
        # place — that's fine (the source flip is preserved).
        if new_binding.combo != existing.combo:
            self._hotkey_map.remove(existing.combo)
        self._hotkey_map.add(new_binding)
        self._pending_rebind = None
        self.call_log.append(
            ("commit_rebind", existing.combo, new_binding.combo),
        )
        if self._on_binding_changed is not None:
            try:
                self._on_binding_changed(new_binding)
            except Exception as exc:  # noqa: BLE001
                _LOG.warning(
                    "NotebookHotkeyHelp.commit_rebind: subscriber raised "
                    "%s: %s", type(exc).__name__, exc,
                )
        if self._built:
            self._rebuild_table()
        return new_binding

    # ==================================================================
    # Row model
    # ==================================================================

    def _resolve_router(self) -> Any | None:
        """Return the bound router, lazily importing REGISTRY on first miss."""
        if self._router is not None:
            return self._router
        try:
            from pharos_engine.tool_router import REGISTRY  # type: ignore
        except Exception:
            return None
        self._router = REGISTRY
        return self._router

    def _resolve_action(self, action_id: str) -> tuple[str, str, bool]:
        """Return ``(label, category, known)`` for *action_id*."""
        router = self._resolve_router()
        if router is None:
            return ("(unknown action)", "misc", False)
        try:
            action = router.get(action_id)
        except Exception:
            action = None
        if action is None:
            return ("(unknown action)", "misc", False)
        label = getattr(action, "label", None) or action_id
        category = getattr(action, "category", None) or "misc"
        return (str(label), str(category), True)

    def rows(self) -> list[HotkeyHelpRow]:
        """Return every binding as a :class:`HotkeyHelpRow` (unfiltered)."""
        out: list[HotkeyHelpRow] = []
        for binding in self._hotkey_map.list_all():
            label, category, known = self._resolve_action(binding.action_id)
            out.append(HotkeyHelpRow(
                binding=binding,
                label=label,
                category=category,
                known=known,
            ))
        return out

    def visible_rows(self) -> list[HotkeyHelpRow]:
        """Return rows after the category + search filters."""
        out: list[HotkeyHelpRow] = []
        wanted = self._category
        needle = self._search.lower()
        for row in self.rows():
            if wanted != ALL_CATEGORY and row.category.lower() != wanted.lower():
                continue
            if needle:
                if (
                    needle not in row.binding.combo.lower()
                    and needle not in row.action_id.lower()
                    and needle not in row.label.lower()
                ):
                    continue
            out.append(row)
        return out

    def visible_count(self) -> int:
        return len(self.visible_rows())

    def is_empty(self) -> bool:
        return len(self._hotkey_map) == 0

    def grouped_visible_rows(self) -> list[tuple[str, list[HotkeyHelpRow]]]:
        """Return visible rows grouped by category (stable insertion order)."""
        groups: dict[str, list[HotkeyHelpRow]] = {}
        for row in self.visible_rows():
            groups.setdefault(row.category, []).append(row)
        return list(groups.items())

    # ==================================================================
    # Build + refresh
    # ==================================================================

    def build(self, parent_tag: str | int) -> None:
        """Render the panel under *parent_tag* — headless-safe."""
        self._parent_tag = parent_tag
        self._built = True
        dpg = _safe_dpg()
        if dpg is None:
            # Still touch the row model so tests can observe build state.
            _ = self.rows()
            return

        try:
            with dpg.group(tag=self._ROOT_TAG, parent=parent_tag):
                # ── Title + washi tape divider ─────────────────────
                try:
                    dpg.add_text(self.TITLE, color=list(self._ink))
                except Exception:
                    pass
                try:
                    dpg.add_text(
                        "~~~~~~~~~~~~~~~~~~~~~~~~~~~~",
                        color=list(self._washi),
                    )
                except Exception:
                    pass

                # ── Header row: preset + reset + reload ────────────
                try:
                    with dpg.group(horizontal=True, tag=self._HEADER_TAG):
                        try:
                            dpg.add_text("Preset:", color=list(self._ink))
                        except Exception:
                            pass
                        try:
                            dpg.add_combo(
                                items=list(PRESET_OPTIONS),
                                default_value=self._preset,
                                callback=self._on_preset_changed,
                                width=120,
                            )
                        except Exception:
                            pass
                        try:
                            dpg.add_button(
                                label="Reset",
                                callback=self._on_reset_clicked,
                            )
                        except Exception:
                            pass
                        try:
                            dpg.add_button(
                                label="Reload",
                                callback=self._on_reload_clicked,
                            )
                        except Exception:
                            pass
                except Exception:
                    pass

                # ── Category filter buttons ────────────────────────
                try:
                    with dpg.group(horizontal=True):
                        for cat in CATEGORY_OPTIONS:
                            try:
                                dpg.add_button(
                                    label=cat,
                                    callback=self._make_category_callback(cat),
                                )
                            except Exception:
                                pass
                except Exception:
                    pass

                # ── Search box ─────────────────────────────────────
                try:
                    dpg.add_input_text(
                        hint="Search combo or action_id...",
                        tag=self._SEARCH_TAG,
                        callback=self._on_search_changed,
                        width=-1,
                    )
                except Exception:
                    pass

                # ── Doodle separator ───────────────────────────────
                try:
                    DoodleSeparator("dotted").build(self._ROOT_TAG)
                except Exception:
                    pass

                # ── Status text ────────────────────────────────────
                try:
                    dpg.add_text(
                        self._format_status(),
                        tag=self._STATUS_TAG,
                        color=list(self._accent),
                    )
                except Exception:
                    pass

                # ── Body: grouped table ────────────────────────────
                try:
                    with dpg.group(tag=self._TABLE_TAG):
                        self._build_table_body()
                except Exception:
                    self._build_table_body()
        except Exception:
            try:
                dpg.add_text(self.TITLE, parent=parent_tag)
            except Exception:
                pass

    def _build_table_body(self) -> None:
        """Render the grouped visible rows under the table tag."""
        dpg = _safe_dpg()
        if dpg is None:
            return
        if self.is_empty():
            try:
                dpg.add_text(
                    "No hotkeys registered — set some in Settings...",
                    color=list(self._ink),
                )
            except Exception:
                pass
            return
        groups = self.grouped_visible_rows()
        if not groups:
            try:
                dpg.add_text(
                    "(no bindings match the current filter)",
                    color=list(self._ink),
                )
            except Exception:
                pass
            return
        for category, rows in groups:
            # Category heading + hand-drawn separator.
            try:
                dpg.add_text(f" {category}", color=list(self._accent))
            except Exception:
                pass
            try:
                DoodleSeparator("wavy").build(self._TABLE_TAG)
            except Exception:
                pass
            for row in rows:
                try:
                    with dpg.group(horizontal=True):
                        try:
                            dpg.add_text(
                                row.keycaps,
                                color=list(self._ink),
                            )
                        except Exception:
                            pass
                        try:
                            desc = f"{row.action_id}  ({row.label})"
                            dpg.add_text(desc, color=list(self._ink))
                        except Exception:
                            pass
                        try:
                            dpg.add_button(
                                label="Change",
                                callback=self._make_change_callback(row.combo),
                            )
                        except Exception:
                            pass
                except Exception:
                    pass

    def _rebuild_table(self) -> None:
        """Rebuild the status + table under the existing tags."""
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._STATUS_TAG):
                try:
                    dpg.set_value(self._STATUS_TAG, self._format_status())
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if dpg.does_item_exist(self._TABLE_TAG):
                for child in list(
                    dpg.get_item_children(self._TABLE_TAG, slot=1) or []
                ):
                    try:
                        dpg.delete_item(child)
                    except Exception:
                        pass
                with dpg.group(parent=self._TABLE_TAG):
                    self._build_table_body()
        except Exception:
            try:
                self._build_table_body()
            except Exception:
                pass

    def destroy(self) -> None:
        """Detach the theme listener + mark the panel torn down."""
        try:
            unregister_theme_listener(self._on_theme_changed)
        except Exception:
            pass
        self._built = False

    # ==================================================================
    # Callbacks
    # ==================================================================

    def _on_preset_changed(
        self, sender: Any, app_data: Any, user_data: Any,
    ) -> None:
        try:
            self.set_preset(str(app_data or PRESET_OPTIONS[0]))
        except Exception as exc:  # noqa: BLE001
            _LOG.warning(
                "NotebookHotkeyHelp: preset change dropped: %s", exc,
            )

    def _on_reset_clicked(self, *_a: Any, **_kw: Any) -> None:
        self.reset_to_default()

    def _on_reload_clicked(self, *_a: Any, **_kw: Any) -> None:
        self.reload()

    def _on_search_changed(
        self, sender: Any, app_data: Any, user_data: Any,
    ) -> None:
        try:
            self.set_search(str(app_data or ""))
        except Exception as exc:  # noqa: BLE001
            _LOG.warning(
                "NotebookHotkeyHelp: search change dropped: %s", exc,
            )

    def _make_category_callback(
        self, category: str,
    ) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            try:
                self.set_category(category)
            except Exception as exc:  # noqa: BLE001
                _LOG.warning(
                    "NotebookHotkeyHelp: category %r click dropped: %s",
                    category, exc,
                )
        return _cb

    def _make_change_callback(
        self, combo: str,
    ) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            try:
                self.start_rebind(combo)
            except Exception as exc:  # noqa: BLE001
                _LOG.warning(
                    "NotebookHotkeyHelp: start_rebind(%r) dropped: %s",
                    combo, exc,
                )
        return _cb

    # ==================================================================
    # Misc
    # ==================================================================

    def _format_status(self) -> str:
        total = len(self._hotkey_map)
        visible = self.visible_count()
        return (
            f"{visible} / {total} bindings | "
            f"category: {self._category} | "
            f"search: {self._search or '(none)'} | "
            f"preset: {self._preset}"
        )


__all__ = [
    "ALL_CATEGORY",
    "CATEGORY_OPTIONS",
    "HotkeyHelpRow",
    "NotebookHotkeyHelp",
    "PRESET_OPTIONS",
    "render_keycaps",
]
