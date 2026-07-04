"""``NotebookCommandPalette`` — VS-Code-style command finder (CC7 sprint).

A modal-style overlay opened by ``Ctrl+Shift+P`` that lets the user
fuzzy-search every action registered on a
:class:`slappyengine.tool_router.ToolRouter` and dispatch it with a
single keystroke. Presentation follows the diary aesthetic used across
the notebook editor family: floating ruled-paper window with washi-tape
corner tabs and a hand-drawn separator dividing the "recently used"
band from the full match list.

The class is deliberately headless-friendly — every DPG call is guarded
so the same state machine drives real GUI usage and pytest suites
without a live viewport. This matches the Z1/Z2 hardening pattern used
by :mod:`slappyengine.ui.editor.notebook_prefab_menu` and its cousins.

Design provenance
-----------------

* Task **CC7** — Command palette (2026-07-05 sprint).
* Router surface: :data:`slappyengine.tool_router.REGISTRY` +
  :meth:`ToolRouter.list_actions`.
* Style reference:
  :mod:`slappyengine.ui.editor.notebook_prefab_menu` for the
  ``_safe_dpg`` / ``_dpg_context_alive`` context-live gate.

Public surface
--------------

* :class:`NotebookCommandPalette` — the palette overlay + state machine.
* :data:`CATEGORY_PRIORITY` — tuple defining the tie-breaker order
  applied to fuzzy-match scores (file > edit > tool > view > panel >
  theme > spawn > everything-else).
* :data:`RECENT_BUFFER_SIZE` — module-level ring-buffer size (8).
* :data:`MAX_VISIBLE_ROWS` — module-level max-rows-in-list (15).
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

from slappyengine._validation import (
    validate_callable,
    validate_non_empty_str,
    validate_positive_int,
)
from slappyengine.tool_router import REGISTRY, ToolAction, ToolRouter
from slappyengine.ui.widgets.notebook_theme import (
    register_theme_listener,
    resolve_theme,
    unregister_theme_listener,
)

_LOG = logging.getLogger(__name__)

# Module-level DPG context sentinel — flipped by the shell after
# ``dpg.create_context()`` so palette code can safely make native
# calls (window creation, focus grabs) that would access-violate
# without a live context.
_DPG_CONTEXT_LIVE: bool = False


def mark_dpg_context_live(is_live: bool) -> None:
    """Flip the module-level ``_DPG_CONTEXT_LIVE`` guard.

    Mirrors the identical helper on ``notebook_prefab_menu`` — the
    shell calls this once after ``setup_dearpygui`` succeeds so
    modal-window creation can proceed without access-violating on the
    real DPG binding.
    """
    global _DPG_CONTEXT_LIVE
    _DPG_CONTEXT_LIVE = bool(is_live)


# ---------------------------------------------------------------------------
# Public tunables
# ---------------------------------------------------------------------------


#: Category tie-breaker order — earlier categories win a fuzzy-score tie.
#: Anything not listed here scores last and sorts by ``action_id``.
CATEGORY_PRIORITY: tuple[str, ...] = (
    "file",
    "edit",
    "tool",
    "view",
    "panel",
    "theme",
    "spawn",
)

#: Ring-buffer size for the "recently invoked" history strip shown at the
#: top of the list when the search box is empty.
RECENT_BUFFER_SIZE: int = 8

#: Cap on rows rendered in the match list (VS Code shows 15 too).
MAX_VISIBLE_ROWS: int = 15


# ---------------------------------------------------------------------------
# Fuzzy match — pure function, unit-testable without instantiating the class
# ---------------------------------------------------------------------------


def _category_rank(category: str) -> int:
    """Return the tie-breaker index for *category* (lower = higher priority)."""
    try:
        return CATEGORY_PRIORITY.index(category)
    except ValueError:
        return len(CATEGORY_PRIORITY)


def _substring_score(needle: str, haystack: str) -> int | None:
    """Return the character index of the first substring match, or ``None``.

    A lower score is better. We prefer earlier substring hits because
    that means the user's search term was a prefix (or near-prefix) of
    the action — the VS Code palette shows the same behaviour.
    """
    if not needle:
        return 0
    idx = haystack.find(needle)
    if idx < 0:
        return None
    return idx


def _acronym_score(needle: str, phrase: str) -> int | None:
    """Return an acronym-match score, or ``None`` when no match.

    Extracts the first character of every token in *phrase* (splitting
    on ``_``, ``.``, spaces, dashes) and checks whether *needle* is a
    prefix of the resulting acronym. The score is the length of the
    residual acronym (shorter matches beat longer ones — searching for
    ``"sat"`` scores ``"select_all_tool"`` as 0-residual).
    """
    if not needle:
        return None
    # Build the initials list from the phrase.
    initials: list[str] = []
    for chunk in phrase.replace(".", " ").replace("_", " ").replace("-", " ").split():
        if chunk:
            initials.append(chunk[0].lower())
    if not initials:
        return None
    acronym = "".join(initials)
    if acronym.startswith(needle):
        return len(acronym) - len(needle)
    return None


def fuzzy_score(
    needle: str,
    action: ToolAction,
) -> tuple[int, int, int, int, str] | None:
    """Return a sortable score tuple for *action* against *needle*.

    The tuple ``(bucket, sub_score, category_rank, length_bias, aid)``
    is sortable directly — ``None`` means "no match". Buckets:

    * ``0`` — substring hit on ``label`` (or ``action_id``).
    * ``1`` — acronym hit on ``action_id`` (or ``label``).

    Within a bucket, ``sub_score`` (the match-position index) orders
    first — earlier hits win. Ties are then broken by
    :data:`CATEGORY_PRIORITY`, then by shortest-label bias, then by
    lexicographic ``action_id``.
    """
    if not isinstance(action, ToolAction):
        raise TypeError(
            "fuzzy_score: action must be a ToolAction; got "
            f"{type(action).__name__}"
        )
    needle = needle.strip().lower()
    label = action.label.lower()
    aid = action.action_id.lower()
    rank = _category_rank(action.category)

    # 1) Substring match on label first (users type visible words).
    sub = _substring_score(needle, label)
    if sub is None:
        sub = _substring_score(needle, aid)
    if sub is not None:
        # Length bias — shorter labels win the tie between two hits at
        # the same index, but only after category priority.
        length_bias = max(len(label) - len(needle), 0)
        return (0, sub, rank, length_bias, aid)

    # 2) Acronym match — action_id first (dot-separated), then label.
    acr = _acronym_score(needle, aid)
    if acr is None:
        acr = _acronym_score(needle, label)
    if acr is not None:
        return (1, acr, rank, 0, aid)

    return None


# ---------------------------------------------------------------------------
# NotebookCommandPalette
# ---------------------------------------------------------------------------


class NotebookCommandPalette:
    """VS-Code-style modal command palette for the notebook editor.

    Parameters
    ----------
    router:
        The :class:`ToolRouter` whose actions the palette will search.
        Defaults to :data:`slappyengine.tool_router.REGISTRY` when
        ``None`` — matching the behaviour of every other editor panel
        that binds to the module-level singleton.
    dispatcher:
        Optional callback ``dispatcher(action_id: str) -> Any`` invoked
        when the user presses Enter on the highlighted row. When
        absent, :meth:`dispatch_selected` calls
        :meth:`ToolRouter.dispatch` with an empty ``ctx``.

    Notes
    -----
    The palette is *always constructed* at editor startup so it can be
    toggled instantly on ``Ctrl+Shift+P`` — the actual DPG widgets are
    built lazily inside :meth:`build` when the shell first mounts it.
    Between construction and first ``open()`` call the panel is idle
    and consumes no window slots.
    """

    TITLE: str = "Command Palette"

    # Overlay window minimums — the palette is tall + narrow like the
    # VS Code Ctrl+Shift+P dialog.
    WIDTH: int = 520
    HEIGHT: int = 420
    ROW_HEIGHT: int = 22

    # ------------------------------------------------------------------

    def __init__(
        self,
        router: ToolRouter | None = None,
        dispatcher: Callable[[str], Any] | None = None,
    ) -> None:
        if router is not None and not isinstance(router, ToolRouter):
            raise TypeError(
                "NotebookCommandPalette: router must be a ToolRouter or "
                f"None; got {type(router).__name__}"
            )
        if dispatcher is not None:
            validate_callable(
                "dispatcher", "NotebookCommandPalette", dispatcher,
            )

        self._router: ToolRouter = router if router is not None else REGISTRY
        self._dispatcher: Callable[[str], Any] | None = dispatcher

        # Overlay lifecycle state.
        self._is_open: bool = False
        self._built: bool = False
        self._parent_tag: str | int | None = None

        # Search + highlight state.
        self._search: str = ""
        self._highlight: int = 0
        self._matches: list[ToolAction] = []

        # Recent-actions ring buffer (bounded to RECENT_BUFFER_SIZE).
        self._recent: list[str] = []

        # Optional keyboard-shortcut lookup ``{action_id: "Ctrl+S"}``.
        # The shell wires this from ``notebook_hotkeys`` after start-up
        # — the palette renders whatever the shell hands it.
        self._shortcuts: dict[str, str] = {}

        # Theme cache — refreshed on listener fire.
        self._theme = resolve_theme()
        self._paper = self._theme.color("paper", (250, 246, 235, 255))
        self._ink = self._theme.color("ink", (40, 40, 60, 255))
        self._accent = self._theme.color("accent", (220, 120, 160, 255))
        self._washi = self._theme.color("washi", (180, 200, 230, 255))
        self._dim = self._theme.color("dim", (150, 150, 170, 255))

        # Theme listener — best-effort (theme module may be stubbed).
        try:
            register_theme_listener(self._on_theme_changed)
        except Exception:
            pass

        # Call log — test assertions read this.
        self.call_log: list[tuple[Any, ...]] = []

        # Seed initial match list so calling ``matches`` before ``open``
        # doesn't return None.
        self._recompute_matches()

    # ==================================================================
    # Router / dispatcher wiring
    # ==================================================================

    @property
    def router(self) -> ToolRouter:
        """Return the currently bound :class:`ToolRouter`."""
        return self._router

    def set_router(self, router: ToolRouter) -> None:
        """Swap the routed action source. Recomputes matches immediately."""
        if not isinstance(router, ToolRouter):
            raise TypeError(
                "NotebookCommandPalette.set_router: router must be a "
                f"ToolRouter; got {type(router).__name__}"
            )
        self._router = router
        self.call_log.append(("set_router", len(router.list_actions())))
        self._recompute_matches()

    def set_dispatcher(self, dispatcher: Callable[[str], Any]) -> None:
        """Subscribe to Enter-key invocations.

        Signature: ``dispatcher(action_id: str) -> Any``.
        """
        validate_callable(
            "dispatcher", "NotebookCommandPalette.set_dispatcher", dispatcher,
        )
        self._dispatcher = dispatcher
        self.call_log.append(("set_dispatcher",))

    def set_shortcuts(self, shortcuts: dict[str, str]) -> None:
        """Register the ``{action_id: "Ctrl+S"}`` display map for row hints."""
        if not isinstance(shortcuts, dict):
            raise TypeError(
                "NotebookCommandPalette.set_shortcuts: shortcuts must be "
                f"a dict; got {type(shortcuts).__name__}"
            )
        # Copy so callers can mutate their own dict without affecting us.
        self._shortcuts = {
            str(k): str(v) for k, v in shortcuts.items() if k and v
        }
        self.call_log.append(("set_shortcuts", len(self._shortcuts)))

    # ==================================================================
    # Open / close / toggle lifecycle
    # ==================================================================

    def open(self) -> None:
        """Show the overlay and reset highlight to the top row."""
        if self._is_open:
            return
        self._is_open = True
        self._highlight = 0
        # Recompute so a router that changed between opens is picked up.
        self._recompute_matches()
        self.call_log.append(("open",))
        self._render_overlay()

    def close(self) -> None:
        """Hide the overlay and clear the transient search buffer.

        The recent-action ring buffer is *not* cleared — the whole point
        of it is to persist across open/close cycles.
        """
        if not self._is_open:
            return
        self._is_open = False
        self._search = ""
        self._highlight = 0
        self._recompute_matches()
        self.call_log.append(("close",))
        self._teardown_overlay()

    def toggle(self) -> bool:
        """Flip visibility. Returns the new ``is_open`` state.

        Bound to ``Ctrl+Shift+P`` by the shell's hotkey wiring — this
        is the palette's single public "activate" entry point.
        """
        if self._is_open:
            self.close()
        else:
            self.open()
        return self._is_open

    @property
    def is_open(self) -> bool:
        """``True`` between :meth:`open` and :meth:`close`."""
        return self._is_open

    @property
    def is_built(self) -> bool:
        """``True`` after :meth:`build` has attached the widgets."""
        return self._built

    # ==================================================================
    # Search + highlight state machine
    # ==================================================================

    @property
    def search(self) -> str:
        """The current search-input value (lowercased match applied)."""
        return self._search

    def set_search(self, text: str) -> None:
        """Update the search box + recompute matches.

        Automatically resets the highlight to row 0 whenever the query
        changes — matches the VS Code palette UX where a fresh query
        selects the top result.
        """
        if not isinstance(text, str):
            raise TypeError(
                "NotebookCommandPalette.set_search: text must be str; "
                f"got {type(text).__name__}"
            )
        old = self._search
        self._search = text
        if old != text:
            self._highlight = 0
        self.call_log.append(("set_search", text))
        self._recompute_matches()

    @property
    def highlight(self) -> int:
        """Index of the currently highlighted row in :meth:`matches`."""
        return self._highlight

    def move_highlight(self, delta: int) -> int:
        """Shift the highlight by *delta* rows (clamped to match count).

        Positive *delta* moves down (arrow-down); negative moves up
        (arrow-up). Returns the new highlight index. A no-op on an
        empty match list — the highlight stays at 0.
        """
        if not isinstance(delta, int):
            raise TypeError(
                "NotebookCommandPalette.move_highlight: delta must be int; "
                f"got {type(delta).__name__}"
            )
        n = len(self._matches)
        if n == 0:
            self._highlight = 0
        else:
            self._highlight = max(0, min(n - 1, self._highlight + delta))
        self.call_log.append(("move_highlight", delta, self._highlight))
        return self._highlight

    def matches(self) -> list[ToolAction]:
        """Return the current filtered match list (top-N)."""
        return list(self._matches)

    # ==================================================================
    # Recent-actions ring buffer
    # ==================================================================

    @property
    def recent_action_ids(self) -> list[str]:
        """Return the last-invoked action ids, most-recent first."""
        return list(self._recent)

    def clear_recent(self) -> None:
        """Wipe the recent-actions ring buffer."""
        if not self._recent:
            return
        self._recent.clear()
        self.call_log.append(("clear_recent",))
        # Only affects the display when the search is empty.
        if not self._search:
            self._recompute_matches()

    def _push_recent(self, action_id: str) -> None:
        """Push *action_id* onto the recent buffer, dedup + bounded size."""
        # Remove any earlier occurrence so the buffer stays MRU-ordered.
        try:
            self._recent.remove(action_id)
        except ValueError:
            pass
        self._recent.insert(0, action_id)
        if len(self._recent) > RECENT_BUFFER_SIZE:
            del self._recent[RECENT_BUFFER_SIZE:]

    # ==================================================================
    # Dispatch
    # ==================================================================

    def dispatch_selected(self) -> str | None:
        """Fire the highlighted action and close the palette.

        Returns the invoked ``action_id`` (or ``None`` when the match
        list is empty). The Enter-key handler binds here.
        """
        if not self._matches:
            self.call_log.append(("dispatch_selected", None))
            return None
        idx = max(0, min(self._highlight, len(self._matches) - 1))
        action = self._matches[idx]
        action_id = action.action_id
        self._push_recent(action_id)
        self.call_log.append(("dispatch_selected", action_id))

        if self._dispatcher is not None:
            try:
                self._dispatcher(action_id)
            except Exception as exc:
                _LOG.warning(
                    "NotebookCommandPalette.dispatch_selected: dispatcher "
                    "raised %s: %s",
                    type(exc).__name__, exc,
                )
        else:
            # Fallback — dispatch straight through the router with an
            # empty ctx. Router-side python fallbacks that need a shell
            # will silently no-op, which is what we want for headless
            # tests.
            try:
                self._router.dispatch(action_id, {})
            except KeyError:
                # The action vanished between the match snapshot and the
                # Enter — swallow so the palette closes cleanly.
                pass
            except Exception as exc:
                _LOG.warning(
                    "NotebookCommandPalette.dispatch_selected: router "
                    "raised %s: %s",
                    type(exc).__name__, exc,
                )
        # Auto-close on Enter — matches VS Code behaviour.
        self.close()
        return action_id

    def dispatch_by_action_id(self, action_id: str) -> Any:
        """Explicit-id dispatch entry — used by the mouse-click row callback.

        Fails safely when *action_id* is not registered on the router.
        """
        validate_non_empty_str(
            "action_id", "NotebookCommandPalette.dispatch_by_action_id",
            action_id,
        )
        if not self._router.has_action(action_id):
            self.call_log.append(("dispatch_by_action_id", action_id, False))
            return None
        # Move highlight onto the id (best-effort) then defer to the
        # shared dispatcher path.
        for i, act in enumerate(self._matches):
            if act.action_id == action_id:
                self._highlight = i
                break
        else:
            # The clicked row isn't in the current match list (edge
            # case: recent-strip click while search is dirty). Fake a
            # single-element match snapshot so ``dispatch_selected``
            # picks the right action.
            action = self._router.get(action_id)
            if action is None:
                return None
            self._matches = [action]
            self._highlight = 0
        return self.dispatch_selected()

    # ==================================================================
    # Match computation
    # ==================================================================

    def _recompute_matches(self) -> None:
        """Recompute the visible match list based on current search state.

        Empty search → recent actions first (top of the list), followed
        by the top ``MAX_VISIBLE_ROWS - len(recent)`` alphabetically-
        sorted actions. Non-empty search → :func:`fuzzy_score` applied
        across every registered action.
        """
        actions = self._router.list_actions()
        by_id: dict[str, ToolAction] = {a.action_id: a for a in actions}

        if not self._search.strip():
            # Recent strip first — filter out any recent entries that
            # have been unregistered since they were pushed.
            head: list[ToolAction] = []
            seen: set[str] = set()
            for aid in self._recent:
                if aid in by_id and aid not in seen:
                    head.append(by_id[aid])
                    seen.add(aid)
            # Fill the remainder alphabetically, skipping duplicates.
            tail: list[ToolAction] = []
            for act in actions:
                if act.action_id in seen:
                    continue
                tail.append(act)
                if len(head) + len(tail) >= MAX_VISIBLE_ROWS:
                    break
            self._matches = (head + tail)[:MAX_VISIBLE_ROWS]
            # Clamp highlight after recomputation.
            self._clamp_highlight()
            return

        # Non-empty search — fuzzy-score every action and take top N.
        scored: list[tuple[tuple[int, int, int, int, str], ToolAction]] = []
        for action in actions:
            score = fuzzy_score(self._search, action)
            if score is None:
                continue
            scored.append((score, action))
        scored.sort(key=lambda pair: pair[0])
        self._matches = [action for _, action in scored[:MAX_VISIBLE_ROWS]]
        self._clamp_highlight()

    def _clamp_highlight(self) -> None:
        """Clamp :attr:`_highlight` to the current match-list length."""
        n = len(self._matches)
        if n == 0:
            self._highlight = 0
        elif self._highlight >= n:
            self._highlight = n - 1
        elif self._highlight < 0:
            self._highlight = 0

    # ==================================================================
    # Build / render lifecycle
    # ==================================================================

    def build(self, parent_tag: int | str) -> bool:
        """Mount the palette overlay under *parent_tag* (best-effort).

        The overlay is initially hidden — the shell mounts it once so
        the widgets exist, then calls :meth:`open` from the hotkey
        handler when the user presses ``Ctrl+Shift+P``.
        """
        if isinstance(parent_tag, str):
            validate_non_empty_str(
                "parent_tag", "NotebookCommandPalette.build", parent_tag,
            )
        elif not isinstance(parent_tag, int):
            raise TypeError(
                "NotebookCommandPalette.build: parent_tag must be str or "
                f"int; got {type(parent_tag).__name__}"
            )
        self._parent_tag = parent_tag
        self._built = True
        self.call_log.append(("build", parent_tag))
        return True

    def destroy(self) -> None:
        """Detach theme listener + tear down cached state."""
        try:
            unregister_theme_listener(self._on_theme_changed)
        except Exception:
            pass
        self._teardown_overlay()
        self._built = False

    # ------------------------------------------------------------------
    # DPG overlay rendering (all guarded — best-effort in headless mode)
    # ------------------------------------------------------------------

    def _overlay_tag(self) -> str:
        """Return the deterministic tag for this palette's DPG window."""
        return f"notebook_command_palette_{id(self)}"

    def _render_overlay(self) -> None:
        """Create the DPG modal window (no-op without a live context)."""
        dpg = self._safe_dpg()
        if dpg is None or not self._dpg_context_alive(dpg):
            return
        tag = self._overlay_tag()
        # Delete any stale window from a previous open cycle before
        # rebuilding — matches the rebuild pattern used by
        # ``notebook_prefab_menu``.
        try:
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)
        except Exception:
            pass
        ink = list(self._ink)
        washi = list(self._washi)
        try:
            with dpg.window(
                label=self.TITLE,
                modal=True,
                tag=tag,
                width=self.WIDTH,
                height=self.HEIGHT,
                no_title_bar=False,
                no_resize=True,
            ):
                # Washi-tape corner tabs — pure decoration.
                self._draw_washi_corners(dpg)
                try:
                    dpg.add_input_text(
                        hint="Type a command...",
                        default_value=self._search,
                        width=-1,
                        callback=(
                            lambda s, a, u: self._on_search_input(a)
                        ),
                    )
                except Exception:
                    pass
                try:
                    dpg.add_separator()
                except Exception:
                    pass
                self._render_rows(dpg)
        except Exception:
            # Fallback — a context-manager-less stub DPG still exercises
            # the state changes without a live viewport.
            self._render_rows(dpg)

    def _draw_washi_corners(self, dpg: Any) -> None:
        """Emit the four washi-tape corner tabs (best-effort)."""
        washi = list(self._washi)
        for corner in ("top-left", "top-right", "bottom-left", "bottom-right"):
            try:
                dpg.add_text(f"[washi:{corner}]", color=washi)
            except Exception:
                pass

    def _render_rows(self, dpg: Any) -> None:
        """Render the recent-strip / match-list rows."""
        recent_section = (
            not self._search.strip()
            and any(a.action_id in self._recent for a in self._matches)
        )
        # A hand-drawn dashed separator visually splits the recent-strip
        # from the fuzzy-search results.
        recent_ids = set(self._recent) if recent_section else set()
        drew_divider = False
        washi = list(self._washi)
        ink = list(self._ink)
        dim = list(self._dim)
        accent = list(self._accent)

        for i, action in enumerate(self._matches):
            if (
                recent_section
                and not drew_divider
                and action.action_id not in recent_ids
            ):
                # Draw the hand-drawn separator between recent + all.
                try:
                    dpg.add_text("- - - - - - - - - - - - - - - -", color=washi)
                except Exception:
                    pass
                drew_divider = True
            self._render_row(dpg, i, action, ink=ink, dim=dim, accent=accent)

    def _render_row(
        self,
        dpg: Any,
        index: int,
        action: ToolAction,
        *,
        ink: list[int],
        dim: list[int],
        accent: list[int],
    ) -> None:
        """Draw a single row — label + action_id (dim) + shortcut (right)."""
        # Highlighted row uses the accent colour; others use ink.
        color = accent if index == self._highlight else ink
        shortcut = self._shortcuts.get(action.action_id, "")
        line = f"{action.label}    [{action.action_id}]"
        if shortcut:
            line = f"{line}    {shortcut}"
        try:
            dpg.add_selectable(
                label=line,
                default_value=(index == self._highlight),
                callback=(
                    lambda s, a, u, aid=action.action_id:
                    self.dispatch_by_action_id(aid)
                ),
            )
        except Exception:
            # Older DPG builds without ``add_selectable`` — fall back
            # to a coloured text line.
            try:
                dpg.add_text(line, color=color)
            except Exception:
                pass

    def _on_search_input(self, value: Any) -> None:
        """DPG input-text callback — safe on any value."""
        if isinstance(value, str):
            self.set_search(value)
            # Rebuild the visible rows in-place. A full window rebuild
            # is the safest option under real DPG; the stubbed test rig
            # just observes ``matches()``.
            self._render_overlay()

    def _teardown_overlay(self) -> None:
        """Delete the DPG window when it exists (best-effort)."""
        dpg = self._safe_dpg()
        if dpg is None or not self._dpg_context_alive(dpg):
            return
        tag = self._overlay_tag()
        try:
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)
        except Exception:
            pass

    # ==================================================================
    # Theme handling
    # ==================================================================

    def _on_theme_changed(self, _theme: Any) -> None:
        """Theme-listener callback — re-resolve the cached palette."""
        try:
            self._theme = resolve_theme()
        except Exception:
            return
        self._paper = self._theme.color("paper", self._paper)
        self._ink = self._theme.color("ink", self._ink)
        self._accent = self._theme.color("accent", self._accent)
        self._washi = self._theme.color("washi", self._washi)
        self._dim = self._theme.color("dim", self._dim)
        self.call_log.append(("theme_changed",))

    # ==================================================================
    # DPG helpers (mirror the Z2 ``_safe_dpg`` / ``_dpg_context_alive``)
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
        """Return ``True`` when DPG has a live context (or a stub marker)."""
        if getattr(dpg, "__slappy_stub__", False):
            return True
        return _DPG_CONTEXT_LIVE


__all__ = [
    "CATEGORY_PRIORITY",
    "MAX_VISIBLE_ROWS",
    "NotebookCommandPalette",
    "RECENT_BUFFER_SIZE",
    "fuzzy_score",
    "mark_dpg_context_live",
]
