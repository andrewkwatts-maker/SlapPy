"""``DiaryShell`` — diary-book main-window layout for the notebook editor.

The Nova3D-era editor arranged every panel as an independent, floating,
close-able window. That gave power users maximum control but flooded
first-run beginners with a wall of chrome. The **diary shell** replaces
that flat panel workspace with a *book of tabbed pages*: a right-edge
strip of coloured index tabs (like the plastic dividers glued into a
Trapper-Keeper) where each tab is a curated "page" of panels focused on
one workflow — Scene, Code, Material, Animation, FX, Settings.

Layout sketch::

    ┌─────────────────────────────────────────┬───┐
    │  [washi-tape spine: SlapPy Notebook]    │Sce│  ← index tabs
    │                                         ├───┤
    │  ┌──────┐   ┌──────────┐   ┌──────┐     │Cod│
    │  │ Out  │   │ Viewport │   │ Insp │     ├───┤
    │  │ liner│   │          │   │ ector│     │Mat│
    │  └──────┘   └──────────┘   └──────┘     ├───┤
    │                                         │Ani│
    │  ┌────────────────────────────────┐     ├───┤
    │  │       Content Browser          │     │FX │
    │  └────────────────────────────────┘     ├───┤
    │                                         │Set│
    ├─────────────────────────────────────────┴───┤
    │ [status bar]                                │
    └─────────────────────────────────────────────┘

Semantics
---------
* :class:`DiaryPage` is a *view descriptor*: it lists the panel ids that
  should be visible when this tab is selected. Nothing else about the
  page is hard-coded — a plugin can register a custom page.
* :meth:`DiaryShell.switch_page` walks the union of every registered
  page's panel-id set, hides everything, then shows the target page's
  panels. That guarantees leaving a page fully cleans it up before the
  next one paints.
* Each page also carries a ``default_layout_preset`` (``"default"``,
  ``"wide_code"``, ``"focus"``, ``"triple_pane"``, ``"compact"``) — the
  shell delegates the actual pane geometry to the existing
  :mod:`layout_presets` machinery so we don't reimplement docking.

Headless / test contract
------------------------
This module imports **no** ``dearpygui`` and no theme runtime; every
Dear PyGui call in the editor already goes through
:class:`MovablePanelWindow`, so ``DiaryShell`` just calls ``.show()`` /
``.hide()`` on the wrappers the editor already owns. That keeps the
whole class exercisable in CI without a viewport.

The class is deliberately **thin**: no rendering, no colour tweening,
no gizmo drawing. All of those are left to the parent :class:`EditorShell`
so this file stays focused on *page routing*.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pharos_engine._validation import (
    validate_bool,
    validate_non_empty_str,
    validate_str,
)

if TYPE_CHECKING:  # pragma: no cover — type-only import
    from pharos_editor.ui.editor.shell import EditorShell


# ---------------------------------------------------------------------------
# Panel-id → panel-window short-key alias table.
# ---------------------------------------------------------------------------
#
# ``EditorShell._panel_windows`` keys use short names like ``"toolbar"``
# and ``"content_browser"``, but the diary pages reference the fully
# qualified panel-ids the notebook family emits (``"notebook_toolbar"``,
# ``"notebook_content_browser"``, …). This table lets tests + plugins
# pass either flavour and always land on the right wrapper.

PANEL_ID_ALIAS: dict[str, str] = {
    "notebook_toolbar":            "toolbar",
    "notebook_outliner":           "outliner",
    "notebook_inspector":          "inspector",
    "notebook_content_browser":    "content_browser",
    "notebook_status_bar":         "status_bar",
    "notebook_code_panel":         "code_panel",
    "notebook_diary_page":         "notebook_diary_page",
    "notebook_material_editor":    "material_editor",
    "notebook_animation_panel":    "animation_panel",
    "notebook_post_process_panel": "post_process_panel",
    "notebook_telemetry_panel":    "telemetry_panel",
    "notebook_gizmos":             "notebook_gizmos",
    "theme_switcher_panel":        "theme_switcher",
}


def _resolve_panel_key(panel_id: str) -> str:
    """Map a canonical panel-id string to the ``_panel_windows`` short key.

    Falls through to *panel_id* verbatim so plugin-registered panels
    still route correctly.
    """
    return PANEL_ID_ALIAS.get(panel_id, panel_id)


# ---------------------------------------------------------------------------
# DiaryPage
# ---------------------------------------------------------------------------


@dataclass
class DiaryPage:
    """One notebook page hosting a set of panels.

    Parameters
    ----------
    id:
        Stable identifier used by :meth:`DiaryShell.switch_page` and
        persisted in the layout snapshot.
    label:
        Short human label rendered on the right-edge index tab.
        Kept ≤ 4 characters at render time (the tab is only 60 px wide)
        but stored full-length so tooltips can show the whole word.
    color:
        Tab colour as an ``(R, G, B)`` triple in the 0–255 range. The
        renderer tints the tab background with this colour; inactive
        tabs are drawn at 70 % saturation via the theme bridge.
    panels:
        Ordered list of panel-id strings visible when this page is
        active. Ids may be short (``"toolbar"``) or fully qualified
        (``"notebook_toolbar"``) — both are resolved through
        :data:`PANEL_ID_ALIAS`.
    default_layout_preset:
        Name of a preset in :mod:`layout_presets` (``"default"`` /
        ``"wide_code"`` / ``"focus"`` / ``"triple_pane"`` / ``"compact"``).
        Applied via :func:`layout_presets.apply_preset` on switch.
    """

    id: str
    label: str
    color: tuple[int, int, int]
    panels: list[str] = field(default_factory=list)
    default_layout_preset: str = "default"

    def __post_init__(self) -> None:
        validate_non_empty_str("id", "DiaryPage", self.id)
        validate_non_empty_str("label", "DiaryPage", self.label)
        validate_non_empty_str(
            "default_layout_preset", "DiaryPage", self.default_layout_preset,
        )
        if not (
            isinstance(self.color, tuple)
            and len(self.color) == 3
            and all(isinstance(c, int) and 0 <= c <= 255 for c in self.color)
        ):
            raise TypeError(
                "DiaryPage: color must be a 3-tuple of ints in 0..255; "
                f"got {self.color!r}"
            )
        if not isinstance(self.panels, list):
            raise TypeError(
                "DiaryPage: panels must be a list[str]; "
                f"got {type(self.panels).__name__}"
            )
        for i, p in enumerate(self.panels):
            if not isinstance(p, str) or not p:
                raise TypeError(
                    f"DiaryPage: panels[{i}] must be a non-empty str; got {p!r}"
                )


# ---------------------------------------------------------------------------
# Default 6 pages — Scene / Code / Material / Animation / FX / Settings
# ---------------------------------------------------------------------------


DEFAULT_PAGES: list[DiaryPage] = [
    DiaryPage(
        id="scene",
        label="Scene",
        color=(255, 168, 190),   # blush pink
        panels=[
            "notebook_toolbar",
            "notebook_outliner",
            "notebook_inspector",
            "notebook_gizmos",
            "notebook_content_browser",
            "notebook_status_bar",
        ],
        default_layout_preset="default",
    ),
    DiaryPage(
        id="code",
        label="Code",
        color=(140, 170, 220),   # soft blue
        panels=[
            "notebook_toolbar",
            "notebook_content_browser",
            "notebook_code_panel",
            "notebook_diary_page",
            "notebook_status_bar",
        ],
        default_layout_preset="wide_code",
    ),
    DiaryPage(
        id="material",
        label="Material",
        color=(180, 220, 150),   # celery green
        panels=[
            "notebook_toolbar",
            "notebook_content_browser",
            "notebook_material_editor",
            "notebook_status_bar",
        ],
        default_layout_preset="default",
    ),
    DiaryPage(
        id="animation",
        label="Animation",
        color=(250, 200, 100),   # marigold
        panels=[
            "notebook_toolbar",
            "notebook_outliner",
            "notebook_animation_panel",
            "notebook_status_bar",
        ],
        default_layout_preset="wide_code",
    ),
    DiaryPage(
        id="fx",
        label="FX",
        color=(220, 150, 240),   # lilac
        panels=[
            "notebook_toolbar",
            "notebook_post_process_panel",
            "notebook_telemetry_panel",
            "notebook_status_bar",
        ],
        default_layout_preset="focus",
    ),
    DiaryPage(
        id="settings",
        label="Settings",
        color=(200, 200, 210),   # dove grey
        panels=[
            "theme_switcher_panel",
            "notebook_status_bar",
        ],
        default_layout_preset="focus",
    ),
]


# The command id the hotkeys table emits when Ctrl+Tab / Ctrl+Shift+Tab
# is pressed. Registered on :class:`NotebookHotkeys` via
# :meth:`DiaryShell.install_hotkeys` so plugins can subscribe.
CMD_NEXT_PAGE:  str = "editor.diary_next_page"
CMD_PREV_PAGE:  str = "editor.diary_prev_page"


# ---------------------------------------------------------------------------
# DiaryShell
# ---------------------------------------------------------------------------


class DiaryShell:
    """Diary-book main window with tabbed pages.

    Replaces the flat panel workspace with a book of tabbed pages.
    Each page shows a curated set of panels; switching pages hides /
    shows the panels accordingly via
    :class:`MovablePanelWindow`.:meth:`show`/:meth:`hide` and applies
    the page's ``default_layout_preset`` through
    :func:`layout_presets.apply_preset`.

    Index tabs are drawn along the **right edge** of the primary window
    by :meth:`build` (see the module docstring sketch). Active tab
    shows a subtle notch cut to indicate the current page; inactive
    tabs are painted at reduced saturation.

    The shell is headless-safe. Every mutation lives on Python state
    so tests can drive :meth:`switch_page` without a live Dear PyGui
    context; the renderer methods early-out when DPG is missing.
    """

    #: Right-edge tab geometry — matches the spec: 40 px tall × 60 px wide.
    TAB_HEIGHT: int = 40
    TAB_WIDTH:  int = 60
    #: Number of pixels between adjacent tabs.
    TAB_GAP:    int = 4
    #: Vertical offset from the top of the workspace where the first
    #: tab starts (leaves room for the washi-tape spine header).
    TAB_TOP_MARGIN: int = 72
    #: Colour used for the "+ New page" tab. Deliberately neutral so
    #: users can tell it's a *create* affordance rather than a page.
    NEW_TAB_COLOR: tuple[int, int, int] = (245, 245, 240)

    def __init__(self, editor_shell: "EditorShell") -> None:
        if editor_shell is None:
            raise TypeError("DiaryShell: editor_shell must not be None")
        self._shell = editor_shell
        # Registered pages in insertion order; a dict preserves order
        # in every supported CPython release so we get O(1) lookup +
        # a stable iteration for the tab strip renderer.
        self._pages: dict[str, DiaryPage] = {}
        self._active_page_id: str | None = None
        # The most-recently applied layout preset name; recorded so
        # tests can verify the preset routed correctly even when the
        # underlying :func:`apply_preset` call swallows exceptions.
        self._last_preset_applied: str | None = None
        # Counters — surfaced through public accessors for tests.
        self._switch_count: int = 0
        self._page_created_count: int = 0
        self._built: bool = False
        # Track the DPG tag(s) generated by :meth:`build`. ``None``
        # until the renderer runs. Kept as a plain dict so the JSON
        # persistence layer can round-trip if a future revision opts
        # to save the last-active page.
        self._tab_tags: dict[str, str] = {}
        # Seed default pages so the shell is usable straight after
        # construction. Plugins may still add or remove pages.
        for page in DEFAULT_PAGES:
            self.add_page(page)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def editor_shell(self) -> "EditorShell":
        """Return the parent :class:`EditorShell` — read-only."""
        return self._shell

    @property
    def is_built(self) -> bool:
        """``True`` after :meth:`build` has run at least once."""
        return self._built

    @property
    def switch_count(self) -> int:
        """Number of successful :meth:`switch_page` calls."""
        return self._switch_count

    @property
    def page_created_count(self) -> int:
        """Number of user-initiated ``+ New page`` creations."""
        return self._page_created_count

    @property
    def last_preset_applied(self) -> str | None:
        """Name of the most-recent preset applied via :meth:`switch_page`."""
        return self._last_preset_applied

    def list_pages(self) -> list[DiaryPage]:
        """Return the registered pages in insertion order."""
        return list(self._pages.values())

    def get_page(self, page_id: str) -> DiaryPage | None:
        """Look up a page by id. Returns ``None`` when unknown."""
        validate_non_empty_str("page_id", "DiaryShell.get_page", page_id)
        return self._pages.get(page_id)

    def has_page(self, page_id: str) -> bool:
        """``True`` iff *page_id* is registered."""
        return isinstance(page_id, str) and page_id in self._pages

    def get_active_page(self) -> DiaryPage | None:
        """Return the currently displayed :class:`DiaryPage` (or ``None``)."""
        if self._active_page_id is None:
            return None
        return self._pages.get(self._active_page_id)

    def get_active_page_id(self) -> str | None:
        """Return the id of the active page (or ``None`` if none is active)."""
        return self._active_page_id

    def all_panel_ids(self) -> set[str]:
        """Return the union of every panel id referenced by any page.

        Used by :meth:`switch_page` to know which wrappers to hide
        before showing the target page's panels. Exposed publicly so
        plugins can pre-warm the panel registry.
        """
        panels: set[str] = set()
        for page in self._pages.values():
            for pid in page.panels:
                panels.add(pid)
        return panels

    # ------------------------------------------------------------------
    # Page registry mutations
    # ------------------------------------------------------------------

    def add_page(self, page: DiaryPage) -> None:
        """Register *page*.

        Raises
        ------
        TypeError
            If *page* isn't a :class:`DiaryPage`.
        ValueError
            If a page with the same id is already registered.
        """
        if not isinstance(page, DiaryPage):
            raise TypeError(
                "DiaryShell.add_page: page must be a DiaryPage; "
                f"got {type(page).__name__}"
            )
        if page.id in self._pages:
            raise ValueError(
                f"DiaryShell.add_page: page id {page.id!r} already registered"
            )
        self._pages[page.id] = page

    def create_custom_page(
        self,
        page_id: str,
        label: str,
        color: tuple[int, int, int] = (245, 245, 240),
        panels: list[str] | None = None,
        default_layout_preset: str = "default",
    ) -> DiaryPage:
        """Convenience wrapper used by the "+ New page" tab click handler.

        Constructs + registers a fresh :class:`DiaryPage` and bumps
        :attr:`page_created_count` so UI observers can react.
        """
        page = DiaryPage(
            id=page_id,
            label=label,
            color=color,
            panels=list(panels or ["notebook_toolbar", "notebook_status_bar"]),
            default_layout_preset=default_layout_preset,
        )
        self.add_page(page)
        self._page_created_count += 1
        return page

    def remove_page(self, page_id: str) -> None:
        """Unregister the page with the given id.

        Raises
        ------
        KeyError
            If *page_id* is not registered.
        """
        validate_non_empty_str("page_id", "DiaryShell.remove_page", page_id)
        if page_id not in self._pages:
            raise KeyError(
                f"DiaryShell.remove_page: unknown page {page_id!r}; "
                f"known: {sorted(self._pages)}"
            )
        del self._pages[page_id]
        if self._active_page_id == page_id:
            # Fall back to the first remaining page (or clear the
            # active pointer entirely when the last page is gone).
            self._active_page_id = None
            if self._pages:
                first = next(iter(self._pages))
                self.switch_page(first)

    # ------------------------------------------------------------------
    # Page switching
    # ------------------------------------------------------------------

    def switch_page(self, page_id: str) -> DiaryPage:
        """Make *page_id* the active page.

        The routine:

        1. Hides every panel wrapper referenced by any registered page
           whose id is **not** in the target page's panel list.
        2. Shows every panel referenced by the target page.
        3. Applies the target page's :attr:`default_layout_preset` via
           :func:`layout_presets.apply_preset`.
        4. Records the switch on the parent shell's status bar (best-
           effort — no-ops when the bar isn't wired).

        Returns the resolved :class:`DiaryPage`.

        Raises
        ------
        KeyError
            If *page_id* is not registered.
        """
        validate_non_empty_str("page_id", "DiaryShell.switch_page", page_id)
        page = self._pages.get(page_id)
        if page is None:
            raise KeyError(
                f"DiaryShell.switch_page: unknown page {page_id!r}; "
                f"known: {sorted(self._pages)}"
            )

        target_short = {_resolve_panel_key(pid) for pid in page.panels}

        # Compute the *union* of every page's panels once so we hide
        # panels that don't belong to the target regardless of which
        # page they came from. Panels referenced only by the target
        # page are already covered by the .show() pass below.
        every_short: set[str] = set()
        for other in self._pages.values():
            for pid in other.panels:
                every_short.add(_resolve_panel_key(pid))

        panel_windows = getattr(self._shell, "_panel_windows", {}) or {}
        # Hide first, then show — reordering avoids a momentary flash
        # where a panel is hidden by the outgoing page but the incoming
        # page wanted it visible.
        for short_key in every_short - target_short:
            wrapper = panel_windows.get(short_key)
            if wrapper is None:
                continue
            try:
                wrapper.hide()
            except Exception:
                pass
        for short_key in target_short:
            wrapper = panel_windows.get(short_key)
            if wrapper is None:
                continue
            try:
                wrapper.show()
            except Exception:
                pass

        # Apply the preset last so it can reflow whatever is now
        # visible. Route through the shell so the shell's status-bar
        # toast + persistence side-effects still fire.
        preset_name = page.default_layout_preset
        applied = False
        try:
            from pharos_editor.ui.editor.layout_presets import apply_preset

            apply_preset(self._shell, preset_name)
            applied = True
        except Exception:
            applied = False
        if applied:
            self._last_preset_applied = preset_name

        self._active_page_id = page.id
        self._switch_count += 1

        # Ambient feedback: toast the page name so the user sees the
        # book "flip" register.
        status_bar = getattr(self._shell, "_notebook_status_bar", None)
        if status_bar is not None:
            try:
                status_bar.set_message(f"Page: {page.label}", kind="info")
            except Exception:
                pass
        return page

    def cycle_page(self, direction: int = 1) -> DiaryPage | None:
        """Move to the next (``direction=+1``) / previous (``-1``) page.

        Wraps around at both ends. When no pages are registered the
        method returns ``None`` without raising.
        """
        if not isinstance(direction, int):
            raise TypeError(
                "DiaryShell.cycle_page: direction must be int; "
                f"got {type(direction).__name__}"
            )
        if direction == 0:
            raise ValueError(
                "DiaryShell.cycle_page: direction must be +1 or -1; got 0"
            )
        ids = list(self._pages.keys())
        if not ids:
            return None
        step = 1 if direction > 0 else -1
        if self._active_page_id is None:
            # No page active yet — pick the first (or last) as start.
            target = ids[0] if step > 0 else ids[-1]
        else:
            try:
                idx = ids.index(self._active_page_id)
            except ValueError:
                target = ids[0]
            else:
                target = ids[(idx + step) % len(ids)]
        return self.switch_page(target)

    def next_page(self) -> DiaryPage | None:
        """Advance to the next page (Ctrl+Tab). Wraps around."""
        return self.cycle_page(+1)

    def prev_page(self) -> DiaryPage | None:
        """Move to the previous page (Ctrl+Shift+Tab). Wraps around."""
        return self.cycle_page(-1)

    # ------------------------------------------------------------------
    # Hotkey integration
    # ------------------------------------------------------------------

    def dispatch_command(self, command: str) -> bool:
        """Route a diary-shell hotkey command.

        Returns ``True`` iff *command* was recognised and dispatched.
        Non-diary commands leave the shell unchanged so the caller
        can chain to other handlers.
        """
        validate_str(
            "command", "DiaryShell.dispatch_command", command, allow_empty=False,
        )
        if command == CMD_NEXT_PAGE:
            self.next_page()
            return True
        if command == CMD_PREV_PAGE:
            self.prev_page()
            return True
        # ``editor.diary_switch_<id>`` — jump directly to a named page.
        prefix = "editor.diary_switch_"
        if command.startswith(prefix):
            page_id = command[len(prefix):]
            if page_id in self._pages:
                self.switch_page(page_id)
                return True
        return False

    def install_hotkeys(self, hotkeys: Any) -> None:
        """Wire Ctrl+Tab / Ctrl+Shift+Tab through *hotkeys*.

        *hotkeys* is expected to be a :class:`NotebookHotkeys` (or a
        duck-typed stand-in with a ``BINDINGS`` mutable dict). We
        install into ``BINDINGS`` — the same table :meth:`handle_key_event`
        consults — so the notebook shell's dispatcher forwards
        ``editor.diary_next_page`` / ``editor.diary_prev_page`` on the
        appropriate key press.
        """
        if hotkeys is None:
            raise TypeError(
                "DiaryShell.install_hotkeys: hotkeys must not be None"
            )
        bindings = getattr(hotkeys, "BINDINGS", None)
        if not isinstance(bindings, dict):
            raise TypeError(
                "DiaryShell.install_hotkeys: hotkeys.BINDINGS must be a dict"
            )
        bindings["ctrl+tab"] = CMD_NEXT_PAGE
        bindings["ctrl+shift+tab"] = CMD_PREV_PAGE

    # ------------------------------------------------------------------
    # Tab-strip geometry (used by the renderer and tests)
    # ------------------------------------------------------------------

    def tab_bounds(self, index: int) -> tuple[int, int, int, int]:
        """Return the ``(x, y, width, height)`` rect of the *index*-th tab.

        ``x`` is a **negative** offset from the right edge of the parent
        viewport so the render layer can position the tabs by anchoring
        each rect to the workspace right side without knowing the
        viewport width itself. ``y`` is measured from the top of the
        workspace.
        """
        if not isinstance(index, int) or index < 0:
            raise ValueError(
                "DiaryShell.tab_bounds: index must be a non-negative int; "
                f"got {index!r}"
            )
        x = -self.TAB_WIDTH  # anchored to right edge
        y = self.TAB_TOP_MARGIN + index * (self.TAB_HEIGHT + self.TAB_GAP)
        return (x, y, self.TAB_WIDTH, self.TAB_HEIGHT)

    def tab_color(self, page: DiaryPage, active: bool) -> tuple[int, int, int]:
        """Return the RGB colour the tab renderer should paint for *page*.

        Inactive tabs are desaturated by pulling every channel 30 %
        toward the theme's neutral mid-grey so the active tab visually
        pops without needing a border.
        """
        if not isinstance(page, DiaryPage):
            raise TypeError(
                "DiaryShell.tab_color: page must be a DiaryPage; "
                f"got {type(page).__name__}"
            )
        active_flag = validate_bool("active", "DiaryShell.tab_color", active)
        if active_flag:
            return page.color
        # Blend the tab colour 70 % toward a neutral notebook-paper cream
        # (matches the ambient theme) to communicate "not the current tab".
        r, g, b = page.color
        neutral = (230, 224, 210)
        blend = 0.30
        return (
            int(r + (neutral[0] - r) * blend),
            int(g + (neutral[1] - g) * blend),
            int(b + (neutral[2] - b) * blend),
        )

    # ------------------------------------------------------------------
    # Build — renderer entry point
    # ------------------------------------------------------------------

    def build(self) -> None:
        """Build the tab strip on the parent editor.

        Records that the shell has been built and best-effort activates
        the first page. Any real Dear PyGui drawing is delegated to the
        editor's tab-strip renderer (out of scope for this class);
        :meth:`build` is intentionally headless-safe so tests can rely
        on the state changes without a viewport.
        """
        self._built = True
        # Pre-compute the tab tags so downstream renderers can look
        # them up deterministically.
        self._tab_tags = {
            page.id: f"diary_tab_{page.id}"
            for page in self._pages.values()
        }
        if self._active_page_id is None and self._pages:
            first = next(iter(self._pages))
            try:
                self.switch_page(first)
            except Exception:
                self._active_page_id = first

    def get_tab_tag(self, page_id: str) -> str | None:
        """Return the DPG tag minted for the *page_id* tab (or ``None``)."""
        validate_non_empty_str("page_id", "DiaryShell.get_tab_tag", page_id)
        return self._tab_tags.get(page_id)


__all__ = [
    "CMD_NEXT_PAGE",
    "CMD_PREV_PAGE",
    "DEFAULT_PAGES",
    "DiaryPage",
    "DiaryShell",
    "PANEL_ID_ALIAS",
]
