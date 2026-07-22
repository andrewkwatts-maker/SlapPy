"""``NotebookStatusBar`` — marginalia note row pinned to the page bottom.

A bottom-of-window status strip themed as a notebook's marginalia row:
a thin washi-tape divider above and below, hand-written status text in
the middle, transient stickers for save/error feedback, and a small
theme-indicator sticker on the right that opens the theme switcher.

Layout (single ~24 px row)::

    --[washi tape divider above]------------------------------------
    [tool] Move tool   1 selected   world: (12.4, 8.0)   60 fps  heart saved   sticker teengirl_notebook
    --[washi tape divider below]------------------------------------

Headless safety
---------------
Every ``dearpygui`` call is wrapped in ``try/except`` so the bar can be
constructed, mutated and ticked on a CI box that has no DPG installed.
This mirrors the contract carried by every other notebook-themed editor
panel (toolbar, gizmos, inspector, outliner).

Design provenance
-----------------

* ``docs/theme_teengirl_notebook_2026_06_03.md`` §3.2 (washi tape +
  marginalia palette tokens).
* ``docs/ui_pattern_audit_2026_06_03.md`` §5.4 (Nova3D status bar →
  notebook reskin: tool + cursor + fps + save + theme).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pharos_engine._validation import (
    validate_bool,
    validate_callable,
    validate_finite_float,
    validate_non_negative_float,
    validate_non_empty_str,
    validate_str,
)


# ---------------------------------------------------------------------------
# Message kinds — sticker + semantic colour role per kind.
# ---------------------------------------------------------------------------


_VALID_KINDS: tuple[str, ...] = ("info", "success", "warning", "error")

# Sticker glyph per message kind. The renderer reads these to choose
# which procedural sticker to paint next to the message text.
_KIND_STICKER: dict[str, str] = {
    "info":    "pencil",
    "success": "heart",
    "warning": "star",
    "error":   "baby_porcupine",
}

# Semantic token role per kind. The status-bar message colour is looked
# up against the active ThemeSpec's :class:`SemanticTokens` so the bar
# tracks runtime theme switches automatically.
_KIND_SEMANTIC: dict[str, str] = {
    "info":    "text_secondary",
    "success": "success",
    "warning": "warning",
    "error":   "error",
}


# Default fallback colours when no theme is registered (handwritten-ink
# navy for body, friendly green/red/amber for semantic kinds).
_FALLBACK_INK: tuple[int, int, int, int] = (31, 47, 102, 255)
_FALLBACK_SUCCESS: tuple[int, int, int, int] = (91, 193, 138, 255)
_FALLBACK_WARNING: tuple[int, int, int, int] = (242, 187, 85, 255)
_FALLBACK_ERROR: tuple[int, int, int, int] = (232, 90, 108, 255)
_FALLBACK_WASHI: tuple[int, int, int, int] = (255, 111, 181, 255)

_FALLBACK_BY_KIND: dict[str, tuple[int, int, int, int]] = {
    "info":    _FALLBACK_INK,
    "success": _FALLBACK_SUCCESS,
    "warning": _FALLBACK_WARNING,
    "error":   _FALLBACK_ERROR,
}


# ---------------------------------------------------------------------------
# Sticker for the active theme indicator at the right margin.
# ---------------------------------------------------------------------------


# Sticker glyph per registered diary theme. Themes outside the map fall
# back to ``"sparkle"`` so the indicator always shows *something*.
_THEME_STICKER_HINT: dict[str, str] = {
    "teengirl_notebook":  "sparkle",
    "cozy_diary":         "leaf",
    "bullet_journal":     "star",
    "scrapbook_summer":   "sun",
    "cottagecore_garden": "flower",
    "kawaii_planner":     "heart",
}


# ---------------------------------------------------------------------------
# Transient message record
# ---------------------------------------------------------------------------


@dataclass
class _TransientMessage:
    """One in-flight status message with a 3 s fade timer.

    ``elapsed`` is the seconds since :meth:`NotebookStatusBar.set_message`
    was called. ``ttl_s`` is the configured display window (default 3.0).
    The bar fades the alpha linearly across the last 25 % of the window.
    """

    text: str
    kind: str
    elapsed: float = 0.0
    ttl_s: float = 3.0

    @property
    def expired(self) -> bool:
        return self.elapsed >= self.ttl_s

    @property
    def alpha(self) -> float:
        """Linear fade alpha in ``[0, 1]`` across the last 25 % of TTL."""
        if self.ttl_s <= 0.0:
            return 0.0
        fade_start = 0.75 * self.ttl_s
        if self.elapsed <= fade_start:
            return 1.0
        if self.elapsed >= self.ttl_s:
            return 0.0
        # Linear fade between fade_start and ttl_s.
        return max(0.0, 1.0 - (self.elapsed - fade_start) /
                   (self.ttl_s - fade_start))


# ---------------------------------------------------------------------------
# NotebookStatusBar
# ---------------------------------------------------------------------------


class NotebookStatusBar:
    """Status bar themed as a marginalia note row at page bottom.

    Shows: active tool / selection count / coordinates of cursor in
    world space / FPS / save-state / active theme. Transient messages
    (``set_message``) overlay a sticker + tinted text for 3 s then fade.

    Parameters
    ----------
    on_theme_indicator_click:
        Optional callback invoked when the user clicks the rightmost
        theme indicator. Wired by :class:`EditorShell` to open the
        :class:`ThemeSwitcherPanel`.
    transient_ttl_s:
        Time in seconds a transient message stays visible. Default 3.0
        matches the brief.
    """

    # Visual constants — tuned for a 24-px-tall status bar.
    _BAR_H: int = 24
    _DIVIDER_H: int = 2
    _THEME_STICKER_SIZE: int = 16

    # Movable-window minimums — picked up by ``MovablePanelWindow``.
    # The status bar is fixed-height (24 px) and full-width.
    MIN_WIDTH: int = 400
    MIN_HEIGHT: int = 24

    def __init__(
        self,
        on_theme_indicator_click: Callable[[], None] | None = None,
        transient_ttl_s: float = 3.0,
    ) -> None:
        if on_theme_indicator_click is not None:
            validate_callable(
                "on_theme_indicator_click",
                "NotebookStatusBar",
                on_theme_indicator_click,
            )
        self._on_theme_click = on_theme_indicator_click
        self._transient_ttl_s = validate_non_negative_float(
            "transient_ttl_s", "NotebookStatusBar", transient_ttl_s,
        )

        # State surfaced by every setter — the renderer rebuilds the
        # composite label string from these on every ``tick``.
        self._active_tool: str = "select"
        self._selection_count: int = 0
        self._world_cursor: tuple[float, float] = (0.0, 0.0)
        self._fps: float = 0.0
        self._saved: bool = True
        self._theme_name: str = "teengirl_notebook"
        # Project segment — populated by ``EditorShell.load_project``.
        # ``None`` means "no project loaded" → renders as ``"project: -"``.
        self._project_name: str | None = None

        # Transient message stack — only the newest is rendered; older
        # entries linger only long enough for tests to inspect the queue.
        self._transient: _TransientMessage | None = None

        # DPG tags for the row + composite label. Kept on the instance so
        # tests can introspect names without driving DPG.
        self._row_tag: str = "notebook_status_bar_row"
        self._label_tag: str = "notebook_status_bar_label"
        self._theme_indicator_tag: str = "notebook_status_bar_theme_indicator"
        self._upper_divider_tag: str = "notebook_status_bar_divider_upper"
        self._lower_divider_tag: str = "notebook_status_bar_divider_lower"

        # Whether ``build`` has run — used by ``set_*`` setters to gate
        # the DPG-write codepath.
        self._built: bool = False

    # ------------------------------------------------------------------
    # Theme + colour helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _lookup_themespec() -> Any | None:
        """Return the active :class:`ThemeSpec` or ``None`` (lazy import)."""
        try:
            from pharos_engine.ui import theme as theme_pkg

            return theme_pkg.get_active_theme()
        except Exception:
            return None

    def _resolve_semantic(
        self, role: str, fallback: tuple[int, int, int, int]
    ) -> tuple[int, int, int, int]:
        """Read ``semantic.<role>`` from the active ThemeSpec, else *fallback*."""
        spec = self._lookup_themespec()
        if spec is None:
            return fallback
        try:
            tok = getattr(spec.semantic, role, None)
            if tok is not None:
                return tok.as_rgba_tuple()
        except Exception:
            pass
        return fallback

    def _resolve_washi(self) -> tuple[int, int, int, int]:
        """Active washi-tape colour (used for the upper/lower dividers)."""
        spec = self._lookup_themespec()
        if spec is not None:
            try:
                washi = spec.palette.get("washi_tape") or spec.palette.get("washi")
                if washi is not None:
                    return washi.as_rgba_tuple()
            except Exception:
                pass
            try:
                return spec.semantic.accent.as_rgba_tuple()
            except Exception:
                pass
        return _FALLBACK_WASHI

    def _resolve_message_color(
        self, kind: str
    ) -> tuple[int, int, int, int]:
        """Colour for a transient message of *kind* — semantic-token driven."""
        role = _KIND_SEMANTIC[kind]
        return self._resolve_semantic(role, _FALLBACK_BY_KIND[kind])

    # ------------------------------------------------------------------
    # Public state setters — match the brief signatures exactly.
    # ------------------------------------------------------------------

    def set_active_tool(self, tool_id: str) -> None:
        """Update the active tool segment of the bar."""
        self._active_tool = validate_non_empty_str(
            "tool_id", "NotebookStatusBar.set_active_tool", tool_id,
        )
        self._refresh_label()

    def set_selection_count(self, count: int) -> None:
        """Update the selection-count segment of the bar."""
        if not isinstance(count, int) or isinstance(count, bool):
            raise TypeError(
                "NotebookStatusBar.set_selection_count: count must be int; "
                f"got {type(count).__name__}"
            )
        if count < 0:
            raise ValueError(
                f"NotebookStatusBar.set_selection_count: count must be >= 0; "
                f"got {count}"
            )
        self._selection_count = count
        self._refresh_label()

    def set_world_cursor(self, x: float, y: float) -> None:
        """Update the world-cursor segment of the bar."""
        x = validate_finite_float("x", "NotebookStatusBar.set_world_cursor", x)
        y = validate_finite_float("y", "NotebookStatusBar.set_world_cursor", y)
        self._world_cursor = (x, y)
        self._refresh_label()

    def set_fps(self, fps: float) -> None:
        """Update the FPS segment of the bar."""
        fps = validate_non_negative_float(
            "fps", "NotebookStatusBar.set_fps", fps,
        )
        self._fps = fps
        self._refresh_label()

    def set_save_state(self, saved: bool) -> None:
        """Update the save-state segment (``True`` -> heart 'saved', ``False`` -> 'unsaved')."""
        self._saved = validate_bool(
            "saved", "NotebookStatusBar.set_save_state", saved,
        )
        self._refresh_label()

    def set_active_theme_name(self, theme_name: str) -> None:
        """Update the rightmost theme-indicator label + sticker hint."""
        self._theme_name = validate_non_empty_str(
            "theme_name",
            "NotebookStatusBar.set_active_theme_name",
            theme_name,
        )
        self._refresh_label()

    def set_project_name(self, project_name: str | None) -> None:
        """Update the project segment of the bar.

        Pass ``None`` to indicate "no project loaded" — the bar renders
        a dash placeholder in that state.
        """
        if project_name is None:
            self._project_name = None
        else:
            self._project_name = validate_non_empty_str(
                "project_name",
                "NotebookStatusBar.set_project_name",
                project_name,
            )
        self._refresh_label()

    def set_message(self, text: str, kind: str = "info") -> None:
        """Push a transient sticker + text overlay for ``transient_ttl_s`` seconds.

        ``kind`` selects both the sticker glyph (e.g. ``"heart"`` for
        success, ``"baby_porcupine"`` for error) and the semantic colour
        role pulled from the active :class:`ThemeSpec`.
        """
        text = validate_str(
            "text", "NotebookStatusBar.set_message", text, allow_empty=True,
        )
        validate_non_empty_str(
            "kind", "NotebookStatusBar.set_message", kind,
        )
        if kind not in _VALID_KINDS:
            raise ValueError(
                f"NotebookStatusBar.set_message: kind must be one of "
                f"{sorted(_VALID_KINDS)}; got {kind!r}"
            )
        self._transient = _TransientMessage(
            text=text, kind=kind, elapsed=0.0, ttl_s=self._transient_ttl_s,
        )
        self._refresh_label()

    def tick(self, dt: float) -> None:
        """Advance the transient-message timer.

        ``dt`` is wall-clock seconds since the previous tick. Once the
        active transient expires it is dropped and the bar reverts to
        the resident state line.
        """
        dt = validate_non_negative_float(
            "dt", "NotebookStatusBar.tick", dt,
        )
        if self._transient is None:
            return
        self._transient.elapsed += dt
        if self._transient.expired:
            self._transient = None
        self._refresh_label()

    # ------------------------------------------------------------------
    # Read-only accessors used by tests + the renderer.
    # ------------------------------------------------------------------

    @property
    def active_tool(self) -> str:
        return self._active_tool

    @property
    def selection_count(self) -> int:
        return self._selection_count

    @property
    def world_cursor(self) -> tuple[float, float]:
        return self._world_cursor

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def saved(self) -> bool:
        return self._saved

    @property
    def theme_name(self) -> str:
        return self._theme_name

    @property
    def project_name(self) -> str | None:
        return self._project_name

    @property
    def transient(self) -> _TransientMessage | None:
        return self._transient

    @property
    def transient_ttl_s(self) -> float:
        return self._transient_ttl_s

    @property
    def row_tag(self) -> str:
        return self._row_tag

    @property
    def label_tag(self) -> str:
        return self._label_tag

    @property
    def theme_indicator_tag(self) -> str:
        return self._theme_indicator_tag

    @property
    def upper_divider_tag(self) -> str:
        return self._upper_divider_tag

    @property
    def lower_divider_tag(self) -> str:
        return self._lower_divider_tag

    @property
    def theme_sticker_hint(self) -> str:
        """Sticker glyph id for the current active theme."""
        return _THEME_STICKER_HINT.get(self._theme_name, "sparkle")

    @property
    def message_color(self) -> tuple[int, int, int, int]:
        """Resolved colour for the currently-rendered status text."""
        if self._transient is not None:
            return self._resolve_message_color(self._transient.kind)
        return self._resolve_semantic("text_primary", _FALLBACK_INK)

    @property
    def divider_color(self) -> tuple[int, int, int, int]:
        """Washi-tape colour the upper + lower dividers paint with."""
        return self._resolve_washi()

    def compose_label(self) -> str:
        """Return the composite single-line label the renderer paints.

        Format:
            ``"[tool: <id>] <N> selected   world: (x, y)   <fps> fps   <save>   <theme>"``

        When a transient is active the resident line is *replaced* with
        the transient text so the user's attention isn't split between
        two strings.
        """
        if self._transient is not None:
            return self._transient.text
        x, y = self._world_cursor
        # Per the brief, dirty mode renders a "✿ unsaved" marker beside
        # the project segment; saved renders the heart sticker.
        save_marker = "saved" if self._saved else "✿ unsaved"
        # Coordinates rounded to 0.1 — the docs called out 1-decimal
        # precision so the bar doesn't shimmer on every mouse-move.
        project_segment = (
            f"project: {self._project_name}"
            if self._project_name is not None
            else "project: -"
        )
        return (
            f"tool: {self._active_tool}   "
            f"{self._selection_count} selected   "
            f"world: ({x:.1f}, {y:.1f})   "
            f"{self._fps:.0f} fps   "
            f"{save_marker}   "
            f"{project_segment}   "
            f"theme: {self._theme_name}"
        )

    # ------------------------------------------------------------------
    # Theme indicator click
    # ------------------------------------------------------------------

    def on_theme_indicator_click(self) -> bool:
        """Fire the ``on_theme_indicator_click`` callback.

        Returns ``True`` iff a callback was registered and ran without
        raising. Headless tests use this entry point because DPG is not
        available in CI.
        """
        if self._on_theme_click is None:
            return False
        try:
            self._on_theme_click()
        except Exception:
            return False
        return True

    # ------------------------------------------------------------------
    # Build / refresh
    # ------------------------------------------------------------------

    def build(self, parent_tag: int | str) -> None:
        """Materialise the status bar inside *parent_tag*.

        Contract: the caller must have invoked ``dpg.create_context()``
        first — this matches every other notebook-themed panel in the
        package (toolbar, gizmos, inspector, outliner). Tests that need
        to exercise the DPG codepath should ``monkeypatch`` a stub DPG
        into ``sys.modules`` before calling ``build``; the headless test
        suite simply skips ``build`` and inspects ``set_*`` outputs
        directly.

        Headless-safe in one direction only: when ``dearpygui`` cannot
        be imported at all (no ``[editor]`` extra installed), the build
        is a no-op apart from flipping ``self._built``.
        """
        try:
            import dearpygui.dearpygui as dpg  # type: ignore[import-not-found]
        except Exception:
            dpg = None  # type: ignore[assignment]

        self._built = True
        if dpg is None:
            return

        # Upper washi-tape divider, status row, lower washi-tape divider.
        try:
            # Upper divider — a 2-px washi strip via separator + colour push.
            dpg.add_separator(
                parent=parent_tag, tag=self._upper_divider_tag,
            )
            # Status row — a single horizontal group so the text + theme
            # indicator sit on one line.
            with dpg.group(
                parent=parent_tag,
                horizontal=True,
                tag=self._row_tag,
            ):
                dpg.add_text(
                    self.compose_label(),
                    tag=self._label_tag,
                    color=self.message_color,
                )
                # Right-margin sticker (16x16) for the theme indicator.
                dpg.add_button(
                    label=self.theme_sticker_hint,
                    tag=self._theme_indicator_tag,
                    width=self._THEME_STICKER_SIZE,
                    height=self._THEME_STICKER_SIZE,
                    callback=lambda *_: self.on_theme_indicator_click(),
                )
            dpg.add_separator(
                parent=parent_tag, tag=self._lower_divider_tag,
            )
        except Exception:
            # Stub DPG / context-manager unsupported — flat fallback.
            try:
                dpg.add_text(
                    self.compose_label(),
                    tag=self._label_tag,
                    parent=parent_tag,
                )
            except Exception:
                pass

    def _refresh_label(self) -> None:
        """Push the freshly-composed label string + colour into DPG.

        Skipped entirely when :meth:`build` has not yet run or when
        ``dearpygui`` is missing. Once ``build`` has run the caller is
        responsible for having created a DPG context first; tests stub
        ``dearpygui.dearpygui`` via ``monkeypatch`` to exercise this path.
        """
        if not self._built:
            return
        try:
            import dearpygui.dearpygui as dpg  # type: ignore[import-not-found]
        except Exception:
            return
        try:
            if dpg.does_item_exist(self._label_tag):
                dpg.set_value(self._label_tag, self.compose_label())
                dpg.configure_item(
                    self._label_tag, color=self.message_color,
                )
            if dpg.does_item_exist(self._theme_indicator_tag):
                dpg.configure_item(
                    self._theme_indicator_tag,
                    label=self.theme_sticker_hint,
                )
        except Exception:
            pass


__all__ = ["NotebookStatusBar"]
