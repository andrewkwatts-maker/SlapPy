"""``MovablePanelWindow`` — wrap an editor panel in a movable DPG window.

The first generation of the notebook editor laid every panel out as
a fixed ``child_window`` slot inside the ``editor_root`` primary
window. That gave us a deterministic boot-time layout but stripped the
user's ability to move, resize, or float panels. This module restores
that affordance.

A :class:`MovablePanelWindow` wraps any object that implements the
panel protocol::

    def build(self, parent_tag: int | str) -> None: ...

and gives it:

* its own dpg.window(...) with no_close=False (when requested) /
  no_move=False / no_resize=False so the OS chrome handles drag +
  resize;
* a theme-driven titlebar — the wrapper resolves the active
  :class:`~pharos_engine.ui.theme.theme_spec.ThemeSpec` and binds a
  per-window DPG theme handle derived from
  ``theme.frames.for_panel(kind)``;
* tracked position + size so the shell can persist the layout;
* honour for any ``MIN_WIDTH`` / ``MIN_HEIGHT`` class attribute on the
  wrapped panel — those override the constructor ``min_size`` when
  larger.

The wrapper is headless-safe: every Dear PyGui call is guarded so the
panel can be exercised in CI without a real GUI context, and tests
can introspect every public method directly.
"""
from __future__ import annotations

from typing import Any

from pharos_engine._validation import (
    validate_non_empty_str,
    validate_positive_int,
)

# Keep a module-level counter so unique tags survive even when the
# caller doesn't pass an explicit ``window_tag``. The shell builds
# every panel at construction time so a simple counter is enough.
_TAG_COUNTER: int = 0


def _next_tag() -> int:
    global _TAG_COUNTER
    _TAG_COUNTER += 1
    return _TAG_COUNTER


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` if importable, else ``None``.

    Identical to the helper used by every notebook panel — kept local
    so the import surface stays minimal.
    """
    try:
        import dearpygui.dearpygui as dpg  # type: ignore[import-not-found]

        return dpg
    except Exception:
        return None


def _panel_min_size(panel: Any) -> tuple[int | None, int | None]:
    """Return ``(MIN_WIDTH, MIN_HEIGHT)`` if declared on *panel*, else ``(None, None)``."""
    w = getattr(panel, "MIN_WIDTH", None)
    h = getattr(panel, "MIN_HEIGHT", None)
    if not isinstance(w, int):
        w = None
    if not isinstance(h, int):
        h = None
    return (w, h)


def _resolve_title(panel: Any, fallback: str | None) -> str:
    """Derive a window title from *panel* or *fallback*.

    Looks for ``panel.TITLE`` (a class attribute used by every notebook
    panel) before falling back to *fallback* or the class name.
    """
    for attr in ("TITLE", "title", "PANEL_TITLE"):
        value = getattr(panel, attr, None)
        if isinstance(value, str) and value:
            return value
    if isinstance(fallback, str) and fallback:
        return fallback
    return type(panel).__name__


class MovablePanelWindow:
    """Wrap a panel in a movable + resizable DPG window.

    Parameters
    ----------
    panel:
        Any object with a ``build(parent_tag)`` method.
    title:
        Optional title-bar label. Defaults to ``panel.TITLE`` when
        the panel exposes one, else the panel class name.
    default_pos:
        Initial top-left ``(x, y)`` in pixels.
    default_size:
        Initial ``(width, height)`` in pixels.
    min_size:
        Minimum ``(width, height)`` in pixels — clamped against any
        ``MIN_WIDTH`` / ``MIN_HEIGHT`` class attribute on the panel
        (the larger value wins so the panel never shrinks below what
        its own widgets need).
    closable:
        When ``True`` the window shows a close button. When ``False``
        the close handler simply hides the window (handy for the
        toolbar / status bar which shouldn't be dismissable).
    kind:
        Theme-frame kind passed to ``theme.frames.for_panel(kind)``.
        One of ``toolbar``, ``sidebar``, ``viewport``, ``modal``,
        ``code_pane``, ``status_bar``. Unknown kinds fall through to
        ``theme.frames.default``.
    no_move, no_resize, no_title_bar, modal:
        Per-window overrides for the corresponding ``dpg.window``
        flags. Defaults reflect the typical sidebar layout (movable,
        resizable, titled, non-modal).
    window_tag:
        Optional explicit DPG tag; otherwise a fresh one is minted.
    """

    def __init__(
        self,
        panel: Any,
        title: str | None = None,
        default_pos: tuple[int, int] = (0, 0),
        default_size: tuple[int, int] = (320, 480),
        min_size: tuple[int, int] = (200, 150),
        closable: bool = False,
        kind: str = "sidebar",
        no_move: bool = False,
        no_resize: bool = False,
        no_title_bar: bool = False,
        modal: bool = False,
        window_tag: str | None = None,
    ) -> None:
        if panel is None:
            raise TypeError("MovablePanelWindow: panel must not be None")
        if not callable(getattr(panel, "build", None)):
            raise TypeError(
                "MovablePanelWindow: panel must implement build(parent_tag); "
                f"got {type(panel).__name__}"
            )

        # ── Position ----------------------------------------------------
        px, py = default_pos
        if not (isinstance(px, int) and isinstance(py, int)):
            raise TypeError(
                "MovablePanelWindow: default_pos must be (int, int); "
                f"got {default_pos!r}"
            )

        # ── Size --------------------------------------------------------
        dw, dh = default_size
        validate_positive_int("default_size.width", "MovablePanelWindow", dw)
        validate_positive_int("default_size.height", "MovablePanelWindow", dh)

        # ── Minimum size — clamp against the panel's MIN_WIDTH/MIN_HEIGHT
        mw, mh = min_size
        validate_positive_int("min_size.width", "MovablePanelWindow", mw)
        validate_positive_int("min_size.height", "MovablePanelWindow", mh)
        pmw, pmh = _panel_min_size(panel)
        if pmw is not None and pmw > mw:
            mw = pmw
        if pmh is not None and pmh > mh:
            mh = pmh

        # Clamp default size to be at least the minimum.
        if dw < mw:
            dw = mw
        if dh < mh:
            dh = mh

        # ── Kind --------------------------------------------------------
        self._kind = validate_non_empty_str("kind", "MovablePanelWindow", kind)

        # ── Stash -------------------------------------------------------
        self._panel = panel
        self._title = _resolve_title(panel, title)
        self._pos: tuple[int, int] = (int(px), int(py))
        self._size: tuple[int, int] = (int(dw), int(dh))
        self._min_size: tuple[int, int] = (int(mw), int(mh))
        self._closable = bool(closable)
        self._no_move = bool(no_move)
        self._no_resize = bool(no_resize)
        self._no_title_bar = bool(no_title_bar)
        self._modal = bool(modal)
        self._visible = True
        self._built = False
        self._theme_handle: Any = None
        # Name of the dock zone the window is currently snapped to, or
        # ``None`` when the window is floating. Set by
        # :class:`DockZoneManager` on successful drag-end docking and
        # reset to ``None`` when the user drags the window away again.
        # Stored as ``str`` (the lowercase zone name, e.g. ``"left"``)
        # rather than the enum so callers can persist it cheaply.
        self.docked_to: str | None = None

        # ── Extended washi-tape corner stickers ───────────────────────
        # Populated by :class:`ExtendedPanelDecorator.attach` — a list of
        # :class:`ExtendedCornerSpec` describing tape strips that extend
        # PAST the panel edge. The wrapper itself doesn't render them
        # (they live on a viewport-level drawlist so they can spill
        # outside the window rect); we keep the slot here so the theme
        # switcher + layout persistence can inspect / re-attach without
        # bouncing through the decorator's private bookkeeping.
        self.extended_corners: list = []

        # Window tag — string for compatibility with DPG's tag system.
        self._window_tag: str = (
            window_tag if isinstance(window_tag, str) and window_tag
            else f"movable_panel_{type(panel).__name__}_{_next_tag()}"
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_window_tag(self) -> str:
        """Return the unique DPG tag of the wrapped window."""
        return self._window_tag

    @property
    def panel(self) -> Any:
        """The wrapped panel object."""
        return self._panel

    @property
    def kind(self) -> str:
        """Theme-frame kind (passed to ``theme.frames.for_panel``)."""
        return self._kind

    @property
    def title(self) -> str:
        """Current window title."""
        return self._title

    @property
    def min_size(self) -> tuple[int, int]:
        """Effective minimum ``(width, height)`` for the window."""
        return self._min_size

    @property
    def closable(self) -> bool:
        """``True`` iff the window shows a close button."""
        return self._closable

    @property
    def no_move(self) -> bool:
        return self._no_move

    @property
    def no_resize(self) -> bool:
        return self._no_resize

    @property
    def no_title_bar(self) -> bool:
        return self._no_title_bar

    @property
    def modal(self) -> bool:
        return self._modal

    @property
    def is_built(self) -> bool:
        """``True`` after :meth:`build` has been invoked at least once."""
        return self._built

    # ------------------------------------------------------------------
    # Position / size accessors
    # ------------------------------------------------------------------

    def get_position(self) -> tuple[int, int]:
        """Return the tracked ``(x, y)`` top-left position."""
        return self._pos

    def set_position(self, x: int, y: int) -> None:
        """Move the window to ``(x, y)``.

        Updates the tracked position immediately. When DPG is up and
        the window already exists, the call also propagates to the
        live window via ``configure_item``.
        """
        if not isinstance(x, int) or not isinstance(y, int):
            raise TypeError(
                f"MovablePanelWindow.set_position: x, y must be ints; "
                f"got ({type(x).__name__}, {type(y).__name__})"
            )
        self._pos = (x, y)
        dpg = _safe_dpg()
        if dpg is None or not self._built:
            return
        try:
            if dpg.does_item_exist(self._window_tag):
                dpg.configure_item(self._window_tag, pos=[x, y])
        except Exception:
            pass

    def set_bounds(self, x: int, y: int, w: int, h: int) -> None:
        """Move + resize the window in one call.

        Convenience wrapper used by :class:`DockZoneManager` when a drag
        ends inside a dock zone. Delegates to :meth:`set_position` then
        :meth:`set_size` so the size-clamping and live DPG propagation
        already implemented on those methods both run.
        """
        self.set_position(x, y)
        self.set_size(w, h)

    def get_size(self) -> tuple[int, int]:
        """Return the tracked ``(width, height)`` of the window."""
        return self._size

    def set_size(self, w: int, h: int) -> None:
        """Resize the window to ``(w, h)``, clamped to :attr:`min_size`."""
        if not isinstance(w, int) or not isinstance(h, int):
            raise TypeError(
                f"MovablePanelWindow.set_size: w, h must be ints; "
                f"got ({type(w).__name__}, {type(h).__name__})"
            )
        if w <= 0 or h <= 0:
            raise ValueError(
                f"MovablePanelWindow.set_size: w, h must be > 0; "
                f"got ({w}, {h})"
            )
        mw, mh = self._min_size
        w = max(w, mw)
        h = max(h, mh)
        self._size = (w, h)
        dpg = _safe_dpg()
        if dpg is None or not self._built:
            return
        try:
            if dpg.does_item_exist(self._window_tag):
                dpg.configure_item(self._window_tag, width=w, height=h)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Visibility
    # ------------------------------------------------------------------

    def show(self) -> None:
        """Mark the window visible (and reflect to DPG when built)."""
        self._visible = True
        dpg = _safe_dpg()
        if dpg is None or not self._built:
            return
        try:
            if dpg.does_item_exist(self._window_tag):
                dpg.configure_item(self._window_tag, show=True)
        except Exception:
            pass

    def hide(self) -> None:
        """Mark the window hidden (and reflect to DPG when built)."""
        self._visible = False
        dpg = _safe_dpg()
        if dpg is None or not self._built:
            return
        try:
            if dpg.does_item_exist(self._window_tag):
                dpg.configure_item(self._window_tag, show=False)
        except Exception:
            pass

    def is_visible(self) -> bool:
        """Return the tracked visibility flag."""
        return self._visible

    # ------------------------------------------------------------------
    # Theme integration
    # ------------------------------------------------------------------

    def get_frame_style(self):
        """Resolve the :class:`FrameStyle` for this panel kind.

        Returns ``None`` when no theme has been applied yet (e.g.
        called in headless tests before the registry is primed).
        """
        try:
            from pharos_engine.ui.theme import get_active_theme

            theme = get_active_theme()
        except Exception:
            return None
        try:
            return theme.frames.for_panel(self._kind)
        except Exception:
            return None

    def _bind_theme(self, dpg: Any) -> None:
        """Build + bind a per-kind DPG theme handle to the window."""
        try:
            from pharos_engine.ui.theme import get_active_theme
            from pharos_engine.ui.theme.dpg_bridge import build_panel_theme

            theme = get_active_theme()
        except Exception:
            return
        try:
            handle = build_panel_theme(theme, self._kind)
        except Exception:
            handle = None
        if handle is None:
            return
        self._theme_handle = handle
        try:
            dpg.bind_item_theme(self._window_tag, handle)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, parent_tag: int | str | None = None) -> None:
        """Construct the dpg.window and call ``panel.build`` inside it.

        Headless-safe: when DPG is missing the call still flips
        ``self._built`` so position / size mutations are stored, and
        the wrapped panel's ``build`` is still invoked (the notebook
        panels are themselves headless-safe).

        Parameters
        ----------
        parent_tag:
            Optional parent container tag. Top-level movable windows
            ignore the parent (DPG windows are roots), but the
            parameter is accepted so the wrapper matches the panel
            protocol contract.
        """
        self._built = True

        dpg = _safe_dpg()
        if dpg is None:
            # Still drive the panel build so tests that walk
            # build()-side state can observe it.
            try:
                self._panel.build(self._window_tag)
            except Exception:
                pass
            return

        # The window kwargs map to dpg.window's flags. ``no_close`` is
        # the *inverse* of our ``closable`` knob — DPG hides the close
        # widget when ``no_close=True``.
        kwargs: dict[str, Any] = {
            "tag": self._window_tag,
            "label": self._title,
            "width": self._size[0],
            "height": self._size[1],
            "pos": list(self._pos),
            "no_close": not self._closable,
            "no_move": self._no_move,
            "no_resize": self._no_resize,
            "no_title_bar": self._no_title_bar,
            "show": self._visible,
            "modal": self._modal,
            "min_size": list(self._min_size),
        }

        try:
            with dpg.window(**kwargs):
                try:
                    self._panel.build(self._window_tag)
                except Exception:
                    pass
        except Exception:
            # Stub-DPG without context-manager support — fall back to
            # the flat form and still drive the panel build.
            try:
                dpg.window(**kwargs)
            except Exception:
                pass
            try:
                self._panel.build(self._window_tag)
            except Exception:
                pass

        # Apply the theme last so the per-window override sits on top
        # of any colour pushed by the panel build.
        self._bind_theme(dpg)


__all__ = ["MovablePanelWindow"]
