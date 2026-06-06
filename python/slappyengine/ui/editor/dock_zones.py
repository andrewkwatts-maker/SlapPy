"""Dock zone preview + dock-on-drop manager for the editor shell.

When the user drags a :class:`MovablePanelWindow` (the editor's draggable
panel base class) around the viewport, the :class:`DockZoneManager`
computes the five canonical dock zones — left, right, top, bottom,
center — based on the live viewport size and shows a semi-transparent
overlay over whichever zone the mouse is currently hovering. Releasing
the drag inside a zone resizes and positions the panel into that zone;
releasing outside any zone leaves the panel floating.

The module is deliberately decoupled from DearPyGui at import time:

* The geometry layer (``compute_zones`` / ``zone_at`` / ``on_drag_*``)
  is pure Python and runs cleanly in CI without a GUI context.
* The DPG drawlist rendering in :meth:`DockZoneManager.render_previews`
  is wrapped in a ``try/except`` so the manager is safe to call on
  headless test machines that lack a DPG context.

Theme integration: the preview tint is sourced from the active
:class:`~slappyengine.ui.theme.ThemeSpec`'s ``semantic.primary`` color
(borders use ``semantic.accent``) — when the user swaps themes the
preview color follows automatically the next time
:meth:`DockZoneManager.render_previews` runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only for type hints
    # Forward reference: MovablePanelWindow is the draggable panel base
    # class shipped alongside the editor shell. We avoid importing it at
    # runtime so the manager stays independent of the panel module.
    from .movable_panel import MovablePanelWindow


# ---------------------------------------------------------------------------
# Public enum + dataclass
# ---------------------------------------------------------------------------


class DockZone(Enum):
    """The six possible dock outcomes a drag operation can resolve to."""

    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"
    CENTER = "center"
    FLOATING = "floating"


@dataclass
class DockZoneTarget:
    """A single dock zone's geometry + preview tint.

    Parameters
    ----------
    zone:
        Which :class:`DockZone` this target represents.
    bounds:
        ``(x, y, w, h)`` of the preview region in viewport pixels.
    color:
        ``(r, g, b, a)`` RGBA tint used for the semi-transparent overlay.
    """

    zone: DockZone
    bounds: tuple[int, int, int, int]
    color: tuple[int, int, int, int]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _semantic_color(field_name: str, default: tuple[int, int, int]) -> tuple[
    int, int, int
]:
    """Pull a ``(r, g, b)`` triple from the active theme's semantic surface.

    Falls back to *default* when no theme is registered yet (e.g. tests
    that exercise the geometry layer without bootstrapping the theme
    registry).
    """
    try:
        from slappyengine.ui.theme import get_active_theme

        theme = get_active_theme()
        color = getattr(theme.semantic, field_name)
        return (int(color.r), int(color.g), int(color.b))
    except Exception:
        return default


# ---------------------------------------------------------------------------
# DockZoneManager
# ---------------------------------------------------------------------------


class DockZoneManager:
    """Manage dock zone previews + dock-on-drop semantics for a viewport.

    Hooks into :class:`MovablePanelWindow`'s drag lifecycle. While a
    panel is being dragged, the manager:

    1. Computes the 5 dock zones (top/bottom/left/right/center) based
       on viewport size.
    2. Checks if the mouse cursor is within any zone bounds.
    3. Renders a semi-transparent overlay over the matching zone.
    4. On drag release, if the cursor is over a zone, resizes + positions
       the panel into that zone.
    """

    #: Fraction of the viewport claimed by each edge dock zone.
    DOCK_ZONE_FRACTION: float = 0.25

    #: Alpha (0-255) applied to the preview tint over a hovered zone.
    PREVIEW_ALPHA: int = 80

    #: Fraction of the viewport claimed by the centre dock zone (per axis).
    CENTER_FRACTION: float = 0.5

    #: Fraction of the viewport a CENTER-docked panel resizes to (per axis).
    CENTER_DOCK_FRACTION: float = 0.6

    #: Default tint when no theme is active.
    _DEFAULT_PRIMARY: tuple[int, int, int] = (120, 160, 255)
    _DEFAULT_ACCENT: tuple[int, int, int] = (120, 160, 255)

    def __init__(self, viewport_size: tuple[int, int]) -> None:
        self._viewport_size: tuple[int, int] = (
            int(viewport_size[0]),
            int(viewport_size[1]),
        )
        # Track which panel (by tag) is currently being dragged. ``None``
        # when no drag is in flight.
        self._dragging_tag: str | None = None
        # Last computed hover zone for the active drag. ``None`` while
        # idle or when the mouse is in FLOATING territory.
        self._active_zone: DockZone | None = None

    # ------------------------------------------------------------------
    # Viewport / geometry
    # ------------------------------------------------------------------

    def update_viewport_size(self, size: tuple[int, int]) -> None:
        """Re-bind the manager to a new viewport size.

        Call this from the editor shell whenever the OS reports a
        resize so subsequent :meth:`compute_zones` returns up-to-date
        bounds.
        """
        self._viewport_size = (int(size[0]), int(size[1]))

    @property
    def viewport_size(self) -> tuple[int, int]:
        """Return the current ``(width, height)`` the manager is sized to."""
        return self._viewport_size

    def compute_zones(self) -> list[DockZoneTarget]:
        """Return the five canonical dock zones for the current viewport.

        Returned order is deterministic: left, right, top, bottom,
        center. Each zone's ``color`` is taken from the active theme's
        ``semantic.primary`` with :attr:`PREVIEW_ALPHA` applied.
        """
        w, h = self._viewport_size
        zone_w = int(w * self.DOCK_ZONE_FRACTION)
        zone_h = int(h * self.DOCK_ZONE_FRACTION)

        # Centre zone spans the middle CENTER_FRACTION of the viewport on
        # both axes (50% × 50% by default).
        cx0 = int(w * (1.0 - self.CENTER_FRACTION) / 2.0)
        cy0 = int(h * (1.0 - self.CENTER_FRACTION) / 2.0)
        cw = int(w * self.CENTER_FRACTION)
        ch = int(h * self.CENTER_FRACTION)

        primary = _semantic_color("primary", self._DEFAULT_PRIMARY)
        tint = (primary[0], primary[1], primary[2], self.PREVIEW_ALPHA)

        return [
            DockZoneTarget(DockZone.LEFT, (0, 0, zone_w, h), tint),
            DockZoneTarget(
                DockZone.RIGHT, (w - zone_w, 0, zone_w, h), tint
            ),
            DockZoneTarget(DockZone.TOP, (0, 0, w, zone_h), tint),
            DockZoneTarget(
                DockZone.BOTTOM, (0, h - zone_h, w, zone_h), tint
            ),
            DockZoneTarget(DockZone.CENTER, (cx0, cy0, cw, ch), tint),
        ]

    def zone_at(self, mouse_pos: tuple[int, int]) -> DockZone:
        """Return which dock zone *mouse_pos* falls inside.

        Edge zones (left/right/top/bottom) win over the centre zone
        when they overlap, matching the user expectation that a cursor
        near a viewport edge docks to the edge rather than to the
        centre. Returns :attr:`DockZone.FLOATING` when the cursor is
        outside every zone (which, given the edge zones tile the
        viewport's outer 25% on each side and the centre fills the
        middle 50% × 50%, only happens when the cursor is outside the
        viewport itself).
        """
        x, y = int(mouse_pos[0]), int(mouse_pos[1])
        w, h = self._viewport_size

        if x < 0 or y < 0 or x >= w or y >= h:
            return DockZone.FLOATING

        zone_w = int(w * self.DOCK_ZONE_FRACTION)
        zone_h = int(h * self.DOCK_ZONE_FRACTION)

        # Edge zones win over centre when they overlap.
        if x < zone_w:
            return DockZone.LEFT
        if x >= w - zone_w:
            return DockZone.RIGHT
        if y < zone_h:
            return DockZone.TOP
        if y >= h - zone_h:
            return DockZone.BOTTOM

        # Centre zone covers the middle CENTER_FRACTION of each axis.
        cx0 = int(w * (1.0 - self.CENTER_FRACTION) / 2.0)
        cy0 = int(h * (1.0 - self.CENTER_FRACTION) / 2.0)
        cw = int(w * self.CENTER_FRACTION)
        ch = int(h * self.CENTER_FRACTION)
        if cx0 <= x < cx0 + cw and cy0 <= y < cy0 + ch:
            return DockZone.CENTER

        return DockZone.FLOATING

    # ------------------------------------------------------------------
    # Drag lifecycle
    # ------------------------------------------------------------------

    def on_drag_start(self, panel_tag: str) -> None:
        """Register that *panel_tag* has begun a drag.

        Until the matching :meth:`on_drag_end` runs, :meth:`on_drag_tick`
        updates the active hover zone so :meth:`render_previews` can
        highlight it.
        """
        self._dragging_tag = str(panel_tag)
        self._active_zone = None

    def on_drag_tick(
        self, panel_tag: str, mouse_pos: tuple[int, int]
    ) -> DockZone | None:
        """Update the active hover zone for the in-flight drag.

        Returns the resolved :class:`DockZone` if the cursor sits in
        one, otherwise ``None`` (so callers can suppress the overlay
        when the cursor is in FLOATING territory).
        """
        if self._dragging_tag != str(panel_tag):
            return None
        zone = self.zone_at(mouse_pos)
        self._active_zone = zone if zone is not DockZone.FLOATING else None
        return self._active_zone

    def on_drag_end(
        self,
        panel_tag: str,
        panel_window: "MovablePanelWindow",
    ) -> DockZone:
        """Finalise the drag — dock the panel into the hovered zone.

        If the cursor sits in a real zone (anything other than
        :attr:`DockZone.FLOATING`), the panel is resized and positioned
        according to the zone's geometry; otherwise the panel is left
        as-is. Returns the resolved :class:`DockZone` either way so
        callers can record telemetry / undo entries.
        """
        if self._dragging_tag != str(panel_tag):
            # Defensive: an end without a matching start just resets state.
            self._dragging_tag = None
            self._active_zone = None
            return DockZone.FLOATING

        zone = self._active_zone or DockZone.FLOATING
        if zone is not DockZone.FLOATING:
            bounds = self._dock_bounds_for(zone)
            self._apply_bounds(panel_window, bounds)
            # Remember the dock slot so later viewport resizes can
            # re-snap the panel. Stored as the lowercase zone name on
            # the panel object (when it supports the attribute) so the
            # field round-trips into layout persistence cheaply. We
            # intentionally do *not* set it for FLOATING releases — the
            # presence of ``docked_to`` is what the viewport-resize
            # path keys off to decide which panels to follow.
            try:
                setattr(panel_window, "docked_to", zone.value)
            except Exception:
                pass
        else:
            # Floating release — clear any prior dock slot so a
            # subsequent viewport resize leaves the panel where the
            # user dropped it. ``setattr`` is wrapped so panels that
            # forbid the attribute (e.g. test doubles using
            # ``__slots__``) don't crash the lifecycle.
            try:
                setattr(panel_window, "docked_to", None)
            except Exception:
                pass

        self._dragging_tag = None
        self._active_zone = None
        return zone

    def redock_panel(self, panel_window: "MovablePanelWindow") -> bool:
        """Re-apply the panel's dock bounds for the current viewport size.

        Called from the editor shell's viewport-resize hook so each
        already-docked panel follows the new viewport dimensions. Reads
        the panel's ``docked_to`` attribute (set on the previous
        successful :meth:`on_drag_end`); panels without a dock slot are
        left untouched.

        Returns ``True`` when the panel was actually re-docked, ``False``
        otherwise (floating, missing attribute, or unknown zone name).
        """
        slot = getattr(panel_window, "docked_to", None)
        if not isinstance(slot, str) or not slot:
            return False
        try:
            zone = DockZone(slot)
        except Exception:
            return False
        if zone is DockZone.FLOATING:
            return False
        bounds = self._dock_bounds_for(zone)
        self._apply_bounds(panel_window, bounds)
        return True

    # ------------------------------------------------------------------
    # Live-drag introspection (used by the editor shell overlay)
    # ------------------------------------------------------------------

    def is_active(self) -> bool:
        """Return ``True`` while a drag is in flight.

        The editor shell's per-frame overlay polls this to decide
        whether to render any dock-zone previews on the live viewport.
        Independent of whether the cursor currently sits inside any
        single zone — the manager may report ``is_active() == True``
        with :meth:`current_zone` returning ``None`` while the cursor
        floats in the dead middle of the screen.
        """
        return self._dragging_tag is not None

    def current_zone(self) -> "DockZone | None":
        """Return the dock zone the cursor is hovering, or ``None``.

        While a drag is in flight (:meth:`is_active`) this returns the
        last value resolved by :meth:`on_drag_tick`; outside a drag it
        always returns ``None``. Used by the editor shell overlay to
        decide which zone rectangle to highlight on the viewport.
        """
        return self._active_zone

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render_previews(
        self, draw_list, active_zone: DockZone | None
    ) -> None:
        """Render the dock zone overlay using a DPG drawlist.

        *draw_list* is the drawlist tag (or item id) the editor shell
        attaches to the viewport. *active_zone* is the zone currently
        under the mouse (typically the value returned by
        :meth:`on_drag_tick`); when ``None`` or :attr:`DockZone.FLOATING`
        no overlay is drawn.

        All DPG calls are wrapped in ``try/except`` so the method is
        safe to call from headless test environments that lack a DPG
        context.
        """
        if active_zone is None or active_zone is DockZone.FLOATING:
            return

        try:
            import dearpygui.dearpygui as dpg
        except Exception:
            return

        try:
            target = next(
                z for z in self.compute_zones() if z.zone is active_zone
            )
        except StopIteration:
            return

        x, y, w, h = target.bounds
        primary = list(target.color)
        accent_rgb = _semantic_color("accent", self._DEFAULT_ACCENT)
        border = [accent_rgb[0], accent_rgb[1], accent_rgb[2], 220]

        try:
            dpg.draw_rectangle(
                pmin=(x, y),
                pmax=(x + w, y + h),
                color=border,
                fill=primary,
                thickness=2.0,
                parent=draw_list,
            )
        except Exception:
            # Headless DPG / no live drawlist — silently degrade.
            return

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _dock_bounds_for(
        self, zone: DockZone
    ) -> tuple[int, int, int, int]:
        """Return the ``(x, y, w, h)`` a panel should snap to for *zone*.

        Distinct from :meth:`compute_zones` because CENTER docks the
        panel to a tighter 60% × 60% box (the preview overlay uses the
        full 50% × 50% hit region).
        """
        w, h = self._viewport_size
        if zone is DockZone.LEFT:
            return (0, 0, int(w * self.DOCK_ZONE_FRACTION), h)
        if zone is DockZone.RIGHT:
            zone_w = int(w * self.DOCK_ZONE_FRACTION)
            return (w - zone_w, 0, zone_w, h)
        if zone is DockZone.TOP:
            return (0, 0, w, int(h * self.DOCK_ZONE_FRACTION))
        if zone is DockZone.BOTTOM:
            zone_h = int(h * self.DOCK_ZONE_FRACTION)
            return (0, h - zone_h, w, zone_h)
        if zone is DockZone.CENTER:
            cw = int(w * self.CENTER_DOCK_FRACTION)
            ch = int(h * self.CENTER_DOCK_FRACTION)
            cx = (w - cw) // 2
            cy = (h - ch) // 2
            return (cx, cy, cw, ch)
        # FLOATING returns a zero-size box; callers should never invoke
        # this path but we keep it for completeness.
        return (0, 0, 0, 0)

    @staticmethod
    def _apply_bounds(
        panel_window: "MovablePanelWindow",
        bounds: tuple[int, int, int, int],
    ) -> None:
        """Resize and reposition *panel_window* to match *bounds*.

        Supports three duck-typed contracts in priority order:

        1. ``set_bounds(x, y, w, h)`` — single call, used by
           :class:`MovablePanelWindow` (it also propagates the change
           to the live DPG window via ``configure_item``).
        2. ``set_position(x, y)`` + ``set_size(w, h)`` — paired
           accessor mutators, the fallback when ``set_bounds`` is
           absent but the wrapper still routes through DPG.
        3. ``position`` + ``size`` property assignment — used by the
           pure-data ``FakePanel`` test doubles.

        Failures are swallowed so a partial / stub panel object doesn't
        crash the dock pipeline; ``None`` ``panel_window`` is silently
        ignored so the shell's degenerate "drag ended but no window"
        path stays a no-op.
        """
        if panel_window is None:
            return
        x, y, w, h = bounds
        try:
            set_bounds = getattr(panel_window, "set_bounds", None)
            if callable(set_bounds):
                set_bounds(x, y, w, h)
                return
        except Exception:
            pass
        try:
            set_position = getattr(panel_window, "set_position", None)
            set_size = getattr(panel_window, "set_size", None)
            if callable(set_position) and callable(set_size):
                set_position(x, y)
                set_size(w, h)
                return
        except Exception:
            pass
        try:
            panel_window.position = (x, y)
            panel_window.size = (w, h)
        except Exception:
            pass


__all__ = ["DockZone", "DockZoneTarget", "DockZoneManager"]
