"""Per-panel resize handles with theme-styled corner grip stickers.

This module gives every notebook-themed :class:`MovablePanelWindow` a
self-contained resize subsystem:

* **Eight handles per panel** — the four edges (n / s / e / w) plus the
  four corners (ne / nw / se / sw). Each handle is a pure rectangle in
  panel-local coordinates and a small theme sticker the renderer paints
  on top.
* **Per-panel minimum sizes** — :class:`MinSize` carries each panel's
  authored floor; the resize tick clamps against that floor so a user
  cannot make the toolbar 4 px tall or the welcome screen 200 px wide.
  DPG's native ``min_size`` is global, so we layer our own enforcement.
* **Theme-styled corner grips** — kawaii hearts, cottagecore stars,
  bullet-journal dots, teengirl washi-tape strips, cozy-diary leather
  corners, scrapbook watercolour splats. The grip kind is keyed off the
  active :class:`~pharos_engine.ui.theme.ThemeSpec.name`; if no theme is
  registered we fall back to a flat dot so the API still draws something.
* **Edge handles** — 4 px line in ``semantic.border`` colour. On hover
  every handle scales to 1.15× and gets a 1-frame shimmer (a brighter
  fill drawn under the sticker).
* **OS cursor changes** — :meth:`ResizeHandleManager.cursor_for` returns
  the canonical CSS cursor name (``ns-resize``, ``nesw-resize``, etc.);
  the editor shell forwards that to DPG's ``set_cursor_*`` shim or to a
  no-op when running headless.
* **Snap integration** — when a :class:`SnapManager` is supplied the
  resize tick also asks the snap manager whether the candidate panel
  rect should snap to a viewport edge or sibling panel; the snapped
  rect is the one returned.

The class is intentionally framework-free in its hot paths
(:meth:`compute_handles`, :meth:`handle_at`, :meth:`on_resize_tick`):
they're pure math + tuple arithmetic so the test suite can exercise
every branch without DPG present. Only :meth:`render_handles` touches a
draw list, and that takes the list as a parameter so callers can pass a
DPG drawlist, a PIL image, or a recording stub.

Public surface
--------------

.. code-block:: python

    from pharos_engine.ui.editor.resize_handles import (
        ResizeHandle, MinSize, ResizeHandleManager,
    )

    mgr = ResizeHandleManager(panel_window, MinSize(200, 150))
    handle = mgr.handle_at((mouse_x, mouse_y))
    if handle is not None:
        mgr.on_resize_start(handle)
        new_rect = mgr.on_resize_tick(handle, (mouse_x, mouse_y))
        mgr.on_resize_end()
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pharos_engine._validation import (
    validate_non_empty_str,
    validate_non_negative_int,
    validate_positive_int,
)


# ---------------------------------------------------------------------------
# Cursor-name table
# ---------------------------------------------------------------------------

#: Canonical CSS cursor name per handle direction. ``handle_at`` /
#: ``cursor_for`` look up this table; the editor shell forwards the name
#: to whatever cursor-setting shim it has.
_CURSOR_BY_DIRECTION: dict[str, str] = {
    "n":  "ns-resize",
    "s":  "ns-resize",
    "e":  "ew-resize",
    "w":  "ew-resize",
    "ne": "nesw-resize",
    "sw": "nesw-resize",
    "nw": "nwse-resize",
    "se": "nwse-resize",
}

#: Direction set, ordered: corners first, edges second. Tests pin both
#: the order and the count (eight handles, four corners + four edges).
_DIRECTIONS: tuple[str, ...] = (
    "nw", "ne", "sw", "se",   # corners
    "n",  "s",  "e",  "w",    # edges
)

#: Subset of corners and edges used by the renderer / compute helpers.
_CORNERS: tuple[str, ...] = ("nw", "ne", "sw", "se")
_EDGES: tuple[str, ...] = ("n", "s", "e", "w")


# ---------------------------------------------------------------------------
# Theme-keyed corner sticker glyphs
# ---------------------------------------------------------------------------

#: Mapping of theme name → corner sticker glyph kind. The renderer reads
#: this so it can draw the right sticker without re-importing the theme.
_STICKER_BY_THEME: dict[str, str] = {
    "kawaii_planner":      "heart",
    "cottagecore_garden":  "star",
    "bullet_journal":      "dot",
    "teengirl_notebook":   "washi",
    "cozy_diary":          "leather",
    "scrapbook_summer":    "splat",
}

#: Fallback sticker when no theme is registered or the theme name is
#: unknown. A simple dot is theme-neutral.
_DEFAULT_STICKER: str = "dot"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ResizeHandle:
    """One resize handle on a panel.

    Parameters
    ----------
    direction:
        One of ``"n"``, ``"s"``, ``"e"``, ``"w"``, ``"ne"``, ``"nw"``,
        ``"se"``, ``"sw"`` — the eight cardinal/intercardinal sides.
    cursor_kind:
        Canonical CSS cursor identifier (``"ns-resize"`` /
        ``"ew-resize"`` / ``"nesw-resize"`` / ``"nwse-resize"``). The
        editor shell forwards this to the OS / DPG cursor shim.
    bounds:
        ``(x, y, w, h)`` rectangle in **panel-local** coordinates
        (origin at the panel's top-left). The renderer adds the panel's
        own origin to translate into viewport space.
    """

    direction: str
    cursor_kind: str
    bounds: tuple[int, int, int, int]

    def __post_init__(self) -> None:
        fn = "ResizeHandle"
        direction = validate_non_empty_str("direction", fn, self.direction)
        if direction not in _CURSOR_BY_DIRECTION:
            raise ValueError(
                f"{fn}: direction must be one of "
                f"{sorted(_CURSOR_BY_DIRECTION)}; got {direction!r}"
            )
        self.direction = direction
        cursor_kind = validate_non_empty_str("cursor_kind", fn, self.cursor_kind)
        self.cursor_kind = cursor_kind
        if (
            not isinstance(self.bounds, tuple)
            or len(self.bounds) != 4
        ):
            raise TypeError(
                f"{fn}: bounds must be a 4-tuple; got {self.bounds!r}"
            )
        x, y, w, h = self.bounds
        for nm, v in (("bounds.x", x), ("bounds.y", y)):
            if not isinstance(v, int):
                raise TypeError(
                    f"{fn}: {nm} must be int; got {type(v).__name__}"
                )
        for nm, v in (("bounds.w", w), ("bounds.h", h)):
            if not isinstance(v, int):
                raise TypeError(
                    f"{fn}: {nm} must be int; got {type(v).__name__}"
                )
            if v < 0:
                raise ValueError(f"{fn}: {nm} must be >= 0; got {v}")
        self.bounds = (int(x), int(y), int(w), int(h))

    def contains(self, x: int, y: int) -> bool:
        """Return ``True`` if ``(x, y)`` is inside :attr:`bounds`.

        ``x`` / ``y`` are in **panel-local** coordinates (same frame as
        :attr:`bounds`). Inclusive of the lower edge, exclusive of the
        upper edge — the usual half-open rectangle convention.
        """
        bx, by, bw, bh = self.bounds
        return bx <= x < bx + bw and by <= y < by + bh


@dataclass
class MinSize:
    """Per-panel minimum width / height in DPG pixels.

    Default of 200×150 matches the brief's "global fallback" and is the
    floor every panel collapses to when its authored minimum is missing.
    """

    width: int = 200
    height: int = 150

    def __post_init__(self) -> None:
        fn = "MinSize"
        self.width = validate_positive_int("width", fn, self.width)
        self.height = validate_positive_int("height", fn, self.height)


# ---------------------------------------------------------------------------
# Per-panel minimum-size table
# ---------------------------------------------------------------------------

#: Per-panel-class ``MinSize`` table. Keyed by class name (string) so we
#: don't have to import each panel class at module load time — that
#: keeps the resize module cheap to import in headless contexts and lets
#: panels register themselves lazily. :func:`min_size_for_panel` walks
#: the panel's MRO so subclasses inherit their parent's minimum.
PANEL_MIN_SIZES: dict[str, MinSize] = {
    "NotebookToolbar":         MinSize(width=800, height=40),
    "NotebookOutliner":        MinSize(width=240, height=300),
    "NotebookInspector":       MinSize(width=280, height=400),
    "NotebookContentBrowser":  MinSize(width=320, height=180),
    "NotebookCodePanel":       MinSize(width=480, height=320),
    "NotebookSpawnMenu":       MinSize(width=600, height=400),
    "NotebookMaterialEditor":  MinSize(width=280, height=400),
    "ThemeSwitcherPanel":      MinSize(width=280, height=360),
    "NotebookStatusBar":       MinSize(width=400, height=24),
    "NotebookWelcome":         MinSize(width=600, height=500),
    "NotebookProjectPicker":   MinSize(width=480, height=420),
}


def min_size_for_panel(panel: Any) -> MinSize:
    """Return the registered :class:`MinSize` for *panel* (or the default).

    Looks at the panel's class hierarchy so a subclass inherits the
    minimum size of the closest registered ancestor. Falls back to the
    global ``MinSize()`` floor (200×150) when nothing matches.
    """
    cls = panel if isinstance(panel, type) else type(panel)
    # Prefer an explicit attribute when the panel has authored its own.
    direct = getattr(panel, "MIN_SIZE", None)
    if isinstance(direct, MinSize):
        return direct
    for ancestor in cls.__mro__:
        ms = PANEL_MIN_SIZES.get(ancestor.__name__)
        if ms is not None:
            return ms
    return MinSize()


# ---------------------------------------------------------------------------
# Protocols (duck-typed so we don't import MovablePanelWindow / SnapManager)
# ---------------------------------------------------------------------------


class _PanelWindowProto(Protocol):
    """Duck-typed view of a :class:`MovablePanelWindow`.

    The resize manager only needs the panel's current rect. Concrete
    panels may expose this as a tuple property; tests in this module
    stub a tiny object literal that satisfies the protocol.
    """

    @property
    def rect(self) -> tuple[int, int, int, int]: ...


class _SnapManagerProto(Protocol):
    """Duck-typed view of a snap adapter for the **resize** path.

    The shipped :class:`~pharos_engine.ui.editor.snap_manager.SnapManager`
    is built for the drag path and exposes :meth:`on_drag_tick`, not
    :meth:`snap_rect`. The resize manager intentionally consumes a
    minimal :meth:`snap_rect` shim so the editor can wrap the real
    snap manager with a per-resize adapter without coupling the two
    subsystems' APIs. When no adapter is supplied (or it doesn't expose
    :meth:`snap_rect`) the resize path falls through unchanged.
    """

    def snap_rect(
        self,
        rect: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int]: ...


# ---------------------------------------------------------------------------
# Geometry helpers — pure math, no DPG
# ---------------------------------------------------------------------------


def compute_handle_rects(
    panel_rect: tuple[int, int, int, int],
    handle_size: int,
) -> dict[str, tuple[int, int, int, int]]:
    """Return per-direction handle rectangles in panel-local coordinates.

    The eight handles are laid out so corners take the full
    ``handle_size`` square at each corner and edges fill the run between
    corners. ``panel_rect`` is supplied in viewport coordinates but the
    returned rects are translated to **panel-local** space (the panel's
    own origin subtracted) so the renderer + hit test agree on a single
    frame.
    """
    if not isinstance(panel_rect, tuple) or len(panel_rect) != 4:
        raise TypeError(
            "compute_handle_rects: panel_rect must be a 4-tuple; "
            f"got {panel_rect!r}"
        )
    _, _, pw, ph = panel_rect
    if pw < 0 or ph < 0:
        raise ValueError(
            "compute_handle_rects: panel_rect dimensions must be "
            f"non-negative; got w={pw}, h={ph}"
        )
    hs = validate_positive_int(
        "handle_size", "compute_handle_rects", handle_size,
    )
    # Corners get a square at each corner.
    nw = (0, 0, hs, hs)
    ne = (max(0, pw - hs), 0, hs, hs)
    sw = (0, max(0, ph - hs), hs, hs)
    se = (max(0, pw - hs), max(0, ph - hs), hs, hs)

    # Edges run between corners.
    # The width / height of each edge is whatever remains after the
    # two corner squares — clamped to 0 so a tiny panel doesn't go
    # negative.
    edge_w = max(0, pw - 2 * hs)
    edge_h = max(0, ph - 2 * hs)
    n = (hs, 0, edge_w, hs)
    s = (hs, max(0, ph - hs), edge_w, hs)
    w = (0, hs, hs, edge_h)
    e = (max(0, pw - hs), hs, hs, edge_h)
    return {
        "nw": nw, "ne": ne, "sw": sw, "se": se,
        "n": n, "s": s, "e": e, "w": w,
    }


def clamp_to_min_size(
    rect: tuple[int, int, int, int],
    direction: str,
    min_size: MinSize,
    origin_rect: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    """Clamp *rect* so its ``w / h`` never drop below *min_size*.

    The clamp is direction-aware: when the user is dragging the north
    edge we keep the south edge pinned, so shrinking below ``min_h``
    pushes the new ``y`` back down. Same logic for the west edge.

    *origin_rect* is the panel's rect at the moment the drag started —
    we need it to know which edge is fixed when the user dragged from a
    side that touches multiple edges.
    """
    x, y, w, h = rect
    ox, oy, ow, oh = origin_rect
    south_pinned = "n" in direction
    east_pinned = "w" in direction  # west edge dragged → east pinned

    if w < min_size.width:
        w = min_size.width
        if east_pinned:
            # Re-anchor against the right edge of the original rect so
            # the south-east stays where it was.
            x = ox + ow - min_size.width
    if h < min_size.height:
        h = min_size.height
        if south_pinned:
            y = oy + oh - min_size.height
    return (x, y, w, h)


# ---------------------------------------------------------------------------
# ResizeHandleManager
# ---------------------------------------------------------------------------


class ResizeHandleManager:
    """Renders + handles resize for a :class:`MovablePanelWindow`.

    DPG's native window resize is enabled (no_resize=False), but we
    layer custom resize behavior to:

    1. Enforce per-panel min sizes (DPG's native min is global).
    2. Render theme-styled corner grip stickers.
    3. Show a hover sticker on the active handle.
    4. Snap-aware: while resizing, also check snap targets.
    """

    #: Edge / corner pixel-thickness. Twelve pixels matches the brief —
    #: large enough to grab on a high-DPI display, small enough that the
    #: handles don't eat the panel content area.
    HANDLE_SIZE: int = 12

    #: How much the handle scales on hover (1.15× per the brief).
    HOVER_SCALE: float = 1.15

    def __init__(
        self,
        panel_window: Any,
        min_size: MinSize,
        snap_manager: Any | None = None,
    ) -> None:
        if panel_window is None:
            raise TypeError(
                "ResizeHandleManager: panel_window must not be None"
            )
        if not isinstance(min_size, MinSize):
            raise TypeError(
                "ResizeHandleManager: min_size must be a MinSize; "
                f"got {type(min_size).__name__}"
            )
        self._panel = panel_window
        self._min_size = min_size
        self._snap = snap_manager

        # Cached origin rect captured at the start of a drag. ``None``
        # outside of an active resize.
        self._origin_rect: tuple[int, int, int, int] | None = None
        self._active_direction: str | None = None

        # Cached theme name → sticker glyph lookup. Re-resolved on every
        # render call (so a theme switch surfaces without a manual
        # refresh) but cached between calls inside one frame.
        self._cached_sticker_kind: str = _DEFAULT_STICKER

    # ------------------------------------------------------------------
    # Properties — useful for tests + the editor shell
    # ------------------------------------------------------------------

    @property
    def panel(self) -> Any:
        return self._panel

    @property
    def min_size(self) -> MinSize:
        return self._min_size

    @property
    def is_resizing(self) -> bool:
        """``True`` between :meth:`on_resize_start` and :meth:`on_resize_end`."""
        return self._origin_rect is not None

    @property
    def active_direction(self) -> str | None:
        """Direction of the in-flight resize, or ``None`` when idle."""
        return self._active_direction

    @property
    def snap_manager(self) -> Any | None:
        return self._snap

    # ------------------------------------------------------------------
    # Handle geometry
    # ------------------------------------------------------------------

    def compute_handles(
        self,
        panel_rect: tuple[int, int, int, int],
    ) -> list[ResizeHandle]:
        """Return the eight :class:`ResizeHandle` instances for *panel_rect*.

        The list is ordered corners-then-edges (``nw, ne, sw, se, n, s,
        e, w``) so tests can pin the order with a single equality.
        """
        rects = compute_handle_rects(panel_rect, self.HANDLE_SIZE)
        out: list[ResizeHandle] = []
        for direction in _DIRECTIONS:
            out.append(
                ResizeHandle(
                    direction=direction,
                    cursor_kind=_CURSOR_BY_DIRECTION[direction],
                    bounds=rects[direction],
                )
            )
        return out

    def handle_at(
        self,
        mouse_pos: tuple[int, int],
        panel_rect: tuple[int, int, int, int] | None = None,
    ) -> ResizeHandle | None:
        """Return the handle under *mouse_pos*, or ``None``.

        *mouse_pos* is in **viewport** coordinates. We translate into
        panel-local space using ``panel_rect`` (which falls back to the
        panel's own ``rect`` property when omitted).

        Corners win over edges when they overlap — the four corners are
        tested first, then the edges. That gives the user a forgiving
        diagonal grab radius at every corner.
        """
        if not isinstance(mouse_pos, tuple) or len(mouse_pos) != 2:
            raise TypeError(
                "ResizeHandleManager.handle_at: mouse_pos must be a "
                f"2-tuple; got {mouse_pos!r}"
            )
        if panel_rect is None:
            panel_rect = self._resolve_panel_rect()
        px, py, _, _ = panel_rect
        mx, my = mouse_pos
        local = (int(mx) - int(px), int(my) - int(py))
        # Corners first so they win on overlap.
        for direction in _CORNERS + _EDGES:
            rect = compute_handle_rects(panel_rect, self.HANDLE_SIZE)[direction]
            bx, by, bw, bh = rect
            if bw == 0 or bh == 0:
                continue
            if bx <= local[0] < bx + bw and by <= local[1] < by + bh:
                return ResizeHandle(
                    direction=direction,
                    cursor_kind=_CURSOR_BY_DIRECTION[direction],
                    bounds=rect,
                )
        return None

    def cursor_for(self, direction: str) -> str:
        """Return the CSS cursor name for *direction*."""
        validate_non_empty_str("direction", "cursor_for", direction)
        cursor = _CURSOR_BY_DIRECTION.get(direction)
        if cursor is None:
            raise ValueError(
                "cursor_for: direction must be one of "
                f"{sorted(_CURSOR_BY_DIRECTION)}; got {direction!r}"
            )
        return cursor

    # ------------------------------------------------------------------
    # Drag lifecycle
    # ------------------------------------------------------------------

    def on_resize_start(self, handle: ResizeHandle) -> None:
        """Capture the panel's origin rect so :meth:`on_resize_tick` can
        compute deltas relative to it.
        """
        if not isinstance(handle, ResizeHandle):
            raise TypeError(
                "on_resize_start: handle must be a ResizeHandle; "
                f"got {type(handle).__name__}"
            )
        self._origin_rect = self._resolve_panel_rect()
        self._active_direction = handle.direction

    def on_resize_tick(
        self,
        handle: ResizeHandle,
        mouse_pos: tuple[int, int],
    ) -> tuple[int, int, int, int]:
        """Return the panel's new ``(x, y, w, h)`` for the current mouse pos.

        Min size is enforced — the rect never shrinks below
        ``self._min_size`` in either axis. When dragging an edge that
        pins the panel's south or east side (e.g. the ``"n"`` edge keeps
        ``y + h`` constant) the clamp re-anchors the moving edge back to
        ``min_size``, preserving the fixed side.

        Snap, when a :class:`SnapManager` is supplied, runs after the
        min-size clamp so a snap can't push the rect below the floor.
        """
        if not isinstance(handle, ResizeHandle):
            raise TypeError(
                "on_resize_tick: handle must be a ResizeHandle; "
                f"got {type(handle).__name__}"
            )
        if not isinstance(mouse_pos, tuple) or len(mouse_pos) != 2:
            raise TypeError(
                "on_resize_tick: mouse_pos must be a 2-tuple; "
                f"got {mouse_pos!r}"
            )
        # If on_resize_start wasn't called (or was followed by an
        # on_resize_end) we fall back to the live panel rect — this
        # keeps tests that hit on_resize_tick without lifecycle calls
        # working, and matches the brief's signature.
        origin = self._origin_rect or self._resolve_panel_rect()
        ox, oy, ow, oh = origin
        mx, my = int(mouse_pos[0]), int(mouse_pos[1])
        direction = handle.direction

        # Default: panel keeps its origin.
        new_x, new_y = ox, oy
        new_w, new_h = ow, oh

        if "e" in direction:
            new_w = max(0, mx - ox)
        if "w" in direction:
            new_x = mx
            new_w = max(0, ox + ow - mx)
        if "s" in direction:
            new_h = max(0, my - oy)
        if "n" in direction:
            new_y = my
            new_h = max(0, oy + oh - my)

        rect = (new_x, new_y, new_w, new_h)
        rect = clamp_to_min_size(rect, direction, self._min_size, origin)
        rect = self._maybe_snap(rect)
        return rect

    def on_resize_end(self) -> None:
        """Clear the in-flight resize state.

        After this call :attr:`is_resizing` is ``False`` and the next
        :meth:`on_resize_tick` falls back to the panel's live rect.
        """
        self._origin_rect = None
        self._active_direction = None

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def sticker_kind(self) -> str:
        """Return the corner-sticker glyph kind for the active theme.

        Re-resolves on every call so a runtime theme switch is reflected
        on the next render tick.
        """
        theme_name = self._resolve_theme_name()
        kind = _STICKER_BY_THEME.get(theme_name, _DEFAULT_STICKER)
        self._cached_sticker_kind = kind
        return kind

    def render_handles(
        self,
        draw_list: Any,
        hovered: ResizeHandle | None = None,
    ) -> dict[str, Any]:
        """Render all eight handles into *draw_list*.

        The return value is a small **render manifest** — a dict keyed
        by handle direction with the rect, colour, sticker kind, and
        a ``hovered`` flag. The renderer / tests use it to assert which
        handles drew and what styling each got without scraping a real
        DPG draw list.

        *draw_list* is intentionally untyped: a DPG drawlist handle, a
        PIL image, or a recording stub all work. We try to call the
        common :func:`add_rect_filled` / :func:`add_text` style methods
        when present, but a stub object that just records calls is
        equally accepted — tests inject one.
        """
        panel_rect = self._resolve_panel_rect()
        px, py, _, _ = panel_rect
        handles = self.compute_handles(panel_rect)
        sticker = self.sticker_kind()
        border_rgba = self._resolve_border_color()
        accent_rgba = self._resolve_accent_color()
        manifest: dict[str, Any] = {}

        for handle in handles:
            bx, by, bw, bh = handle.bounds
            if bw == 0 or bh == 0:
                # Tiny panel — skip handles that collapsed to zero area.
                continue
            is_hovered = (
                hovered is not None and hovered.direction == handle.direction
            )
            # Hover styling: scale up + brighter shimmer colour.
            if is_hovered:
                scale = self.HOVER_SCALE
                fill = accent_rgba
                scaled_w = int(round(bw * scale))
                scaled_h = int(round(bh * scale))
                # Re-centre the scaled rect around the original midpoint.
                offset_x = (scaled_w - bw) // 2
                offset_y = (scaled_h - bh) // 2
                draw_rect = (
                    px + bx - offset_x,
                    py + by - offset_y,
                    scaled_w,
                    scaled_h,
                )
            else:
                fill = border_rgba
                draw_rect = (px + bx, py + by, bw, bh)
            self._draw_handle(
                draw_list=draw_list,
                rect=draw_rect,
                fill=fill,
                direction=handle.direction,
                sticker=sticker if handle.direction in _CORNERS else None,
            )
            manifest[handle.direction] = {
                "rect": draw_rect,
                "fill": fill,
                "sticker": sticker if handle.direction in _CORNERS else None,
                "hovered": is_hovered,
            }
        return manifest

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_panel_rect(self) -> tuple[int, int, int, int]:
        """Return the panel's current ``(x, y, w, h)`` rectangle.

        We try several common accessors so the manager can wrap an
        early-stage :class:`MovablePanelWindow` (which may expose
        ``rect`` as a property, a tuple attribute, or a method), and
        fall through to a minimal-size default at the origin so tests
        on a fresh manager still get a usable rect.
        """
        for attr in ("rect", "_rect", "bounds"):
            value = getattr(self._panel, attr, None)
            if callable(value):
                try:
                    value = value()
                except Exception:
                    value = None
            if (
                isinstance(value, tuple)
                and len(value) == 4
                and all(isinstance(v, (int, float)) for v in value)
            ):
                return (
                    int(value[0]),
                    int(value[1]),
                    int(value[2]),
                    int(value[3]),
                )
        # Last-ditch: panel exposed x/y/w/h as separate attributes.
        x = getattr(self._panel, "x", 0)
        y = getattr(self._panel, "y", 0)
        w = getattr(self._panel, "w", self._min_size.width)
        h = getattr(self._panel, "h", self._min_size.height)
        return (int(x), int(y), int(w), int(h))

    def _maybe_snap(
        self,
        rect: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int]:
        """Run the snap manager on *rect* when one is configured."""
        snap = self._snap
        if snap is None:
            return rect
        snap_fn = getattr(snap, "snap_rect", None)
        if not callable(snap_fn):
            return rect
        try:
            snapped = snap_fn(rect)
        except Exception:
            return rect
        if (
            isinstance(snapped, tuple)
            and len(snapped) == 4
            and all(isinstance(v, (int, float)) for v in snapped)
        ):
            return (
                int(snapped[0]),
                int(snapped[1]),
                int(snapped[2]),
                int(snapped[3]),
            )
        return rect

    def _resolve_theme_name(self) -> str:
        """Return the active theme name, or ``"default"`` when none."""
        try:
            from pharos_engine.ui import theme as theme_pkg

            spec = theme_pkg.get_active_theme()
            if spec is not None:
                name = getattr(spec, "name", None)
                if isinstance(name, str) and name:
                    return name
        except Exception:
            pass
        return "default"

    def _resolve_border_color(self) -> tuple[int, int, int, int]:
        """Return ``semantic.border`` from the active theme.

        Falls back to a neutral 50% grey so the handle still draws
        without a theme registered.
        """
        try:
            from pharos_engine.ui import theme as theme_pkg

            spec = theme_pkg.get_active_theme()
            if spec is not None:
                return spec.semantic.border.as_rgba_tuple()
        except Exception:
            pass
        return (128, 128, 128, 255)

    def _resolve_accent_color(self) -> tuple[int, int, int, int]:
        """Return ``semantic.accent`` from the active theme.

        Used for the hover-state shimmer fill. Falls back to a soft
        highlight yellow.
        """
        try:
            from pharos_engine.ui import theme as theme_pkg

            spec = theme_pkg.get_active_theme()
            if spec is not None:
                return spec.semantic.accent.as_rgba_tuple()
        except Exception:
            pass
        return (255, 224, 102, 255)

    def _draw_handle(
        self,
        draw_list: Any,
        rect: tuple[int, int, int, int],
        fill: tuple[int, int, int, int],
        direction: str,
        sticker: str | None,
    ) -> None:
        """Call into *draw_list*'s rect/sticker methods if present.

        Every method invocation is wrapped in a ``try / except`` so a
        partially-implemented draw list (or a test stub that only
        records a subset of calls) doesn't crash the render loop.
        """
        x, y, w, h = rect
        # Filled rect — every drawlist style exposes one of these names.
        for method_name in ("add_rect_filled", "draw_rectangle", "rect_fill"):
            method = getattr(draw_list, method_name, None)
            if callable(method):
                try:
                    method(
                        pmin=(x, y),
                        pmax=(x + w, y + h),
                        color=fill,
                    )
                except TypeError:
                    # Positional fall-back for stubs that just want
                    # (pmin, pmax, color) without kwargs.
                    try:
                        method((x, y), (x + w, y + h), fill)
                    except Exception:
                        pass
                except Exception:
                    pass
                break
        # Corner sticker — pass through to a sticker-aware draw method
        # when one exists; otherwise skip silently.
        if sticker is not None:
            sticker_method = getattr(draw_list, "add_sticker", None)
            if callable(sticker_method):
                try:
                    sticker_method(
                        kind=sticker,
                        rect=rect,
                        direction=direction,
                        color=fill,
                    )
                except Exception:
                    pass


__all__ = [
    "MinSize",
    "PANEL_MIN_SIZES",
    "ResizeHandle",
    "ResizeHandleManager",
    "clamp_to_min_size",
    "compute_handle_rects",
    "min_size_for_panel",
]
