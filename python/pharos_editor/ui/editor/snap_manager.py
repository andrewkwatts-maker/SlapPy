"""Window snap-to-edge subsystem for the Pharos Engine editor.

The :class:`SnapManager` is hooked into each ``MovablePanelWindow`` drag
handler.  When the user drags a panel close to (a) a viewport edge,
(b) a sibling panel edge, or (c) — optionally — a grid line, the panel's
position is "magnetised" to that target, producing the familiar
snap-and-click feel of Photoshop / Blender / Figma window managers.

This module is **pure logic** — it computes integer ``(x, y)`` positions
and a list of active :class:`SnapTarget` records.  Guide-line drawing,
viewport size queries, and event wiring all live in the DPG layer
(``MovablePanelWindow``); the manager merely exposes hooks they call.

Design notes
------------
* The manager keeps a registry ``{tag: panel}`` of registered panels so
  the consumer never has to pass the full list on every drag tick.
* ``compute_snap_targets`` is called once at ``on_drag_start`` and the
  result is cached for the drag duration — sibling panel positions do
  not move while another panel is being dragged.
* ``on_drag_tick`` returns the **snapped** ``(x, y)`` the caller should
  apply.  When no snap fires, the raw mouse position passes through
  unchanged.
* Guide-line state is exposed via :attr:`active_snap_x` / ``_y`` so the
  GUI layer can render the dashed accent guide(s) without having to
  re-run the snap search.

The accent colour for guides is read from the active editor theme — the
manager does not import DPG and does not draw anything itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable, Protocol

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SnapTarget:
    """A single snap target — viewport edge / panel edge / grid line.

    Parameters
    ----------
    axis:
        ``"x"`` for a vertical line (constant x), ``"y"`` for a
        horizontal line (constant y).
    position:
        The pixel coordinate of the target line on its axis.
    kind:
        One of ``"viewport_edge"``, ``"panel_edge"``, ``"grid_line"``.
    source_tag:
        For ``"panel_edge"`` targets, the DPG tag of the sibling panel
        the target was derived from.  ``None`` otherwise.
    """

    axis: str
    position: int
    kind: str
    source_tag: str | None = None


@dataclass
class SnapConfig:
    """Tuning knobs for :class:`SnapManager`.

    All distances are in screen pixels.
    """

    threshold_px: int = 12
    grid_size: int = 16
    enable_viewport_edges: bool = True
    enable_panel_edges: bool = True
    enable_grid: bool = False
    show_guide_lines: bool = True


# ---------------------------------------------------------------------------
# Panel protocol — what the manager needs from a "MovablePanelWindow"
# ---------------------------------------------------------------------------


class _PanelLike(Protocol):
    """Minimum interface SnapManager needs from a panel.

    The real :class:`MovablePanelWindow` has many more attributes; we
    only require these four so the manager stays testable without DPG.
    """

    tag: str
    x: int
    y: int
    width: int
    height: int


# ---------------------------------------------------------------------------
# SnapManager
# ---------------------------------------------------------------------------


@dataclass
class _DragState:
    """Internal cache held for the duration of a single drag operation."""

    panel_tag: str
    start_mouse: tuple[int, int]
    start_panel: tuple[int, int]
    targets: list[SnapTarget] = field(default_factory=list)
    active_x: SnapTarget | None = None
    active_y: SnapTarget | None = None


class SnapManager:
    """Coordinates window snapping during drag operations.

    Lifecycle::

        mgr = SnapManager()
        mgr.register_panel(panel_a)
        mgr.register_panel(panel_b)
        ...
        mgr.on_drag_start("panel_a")        # cache targets
        new_xy = mgr.on_drag_tick("panel_a", (mx, my))
        ...
        mgr.on_drag_end("panel_a")          # clear active guides
    """

    # The (W, H) used when no viewport size has been registered.
    DEFAULT_VIEWPORT: tuple[int, int] = (1280, 720)
    # Height of the editor's top menu bar — the y=0 snap target is moved
    # down by this many pixels so panels don't slip under the menu.
    DEFAULT_MENU_BAR_HEIGHT: int = 22

    def __init__(self, config: SnapConfig | None = None) -> None:
        self.config: SnapConfig = config if config is not None else SnapConfig()
        self._panels: dict[str, _PanelLike] = {}
        self._viewport_size: tuple[int, int] = self.DEFAULT_VIEWPORT
        self._menu_bar_height: int = self.DEFAULT_MENU_BAR_HEIGHT
        self._drag: _DragState | None = None
        # Guide-line colour — RGBA, defaults to a neutral accent.  The
        # editor shell overwrites this on theme change.
        self._guide_color: tuple[int, int, int, int] = (120, 160, 255, 220)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_panel(self, panel_window: _PanelLike) -> None:
        """Add a panel to the registry.

        The panel must expose ``tag``, ``x``, ``y``, ``width``,
        ``height``.  Re-registering with the same tag overwrites.
        """
        self._panels[panel_window.tag] = panel_window

    def unregister_panel(self, panel_window: _PanelLike) -> None:
        """Remove a panel from the registry (no-op if absent)."""
        self._panels.pop(panel_window.tag, None)
        # If the unregistered panel was being dragged, clear state.
        if self._drag is not None and self._drag.panel_tag == panel_window.tag:
            self._drag = None

    # ------------------------------------------------------------------
    # Viewport / theme setters (called by editor shell)
    # ------------------------------------------------------------------

    def set_viewport_size(self, width: int, height: int) -> None:
        """Update the working viewport size used for edge targets."""
        self._viewport_size = (int(width), int(height))

    def set_menu_bar_height(self, height: int) -> None:
        """Update the top menu-bar height so the y=top edge clears it."""
        self._menu_bar_height = int(height)

    def set_guide_color(self, rgba: tuple[int, int, int, int]) -> None:
        """Update the dashed-guide accent colour (called on theme switch)."""
        if len(rgba) == 3:
            r, g, b = rgba  # type: ignore[misc]
            self._guide_color = (int(r), int(g), int(b), 220)
        else:
            r, g, b, a = rgba
            self._guide_color = (int(r), int(g), int(b), int(a))

    @property
    def guide_color(self) -> tuple[int, int, int, int]:
        return self._guide_color

    # ------------------------------------------------------------------
    # Target computation
    # ------------------------------------------------------------------

    def compute_snap_targets(self, dragged_panel_tag: str) -> list[SnapTarget]:
        """Return every active snap target *except* those owned by the
        dragged panel itself."""
        targets: list[SnapTarget] = []
        cfg = self.config

        if cfg.enable_viewport_edges:
            vw, vh = self._viewport_size
            targets.append(SnapTarget("x", 0, "viewport_edge"))
            targets.append(SnapTarget("x", int(vw), "viewport_edge"))
            targets.append(SnapTarget("y", int(self._menu_bar_height), "viewport_edge"))
            targets.append(SnapTarget("y", int(vh), "viewport_edge"))

        if cfg.enable_panel_edges:
            for tag, panel in self._panels.items():
                if tag == dragged_panel_tag:
                    continue
                left = int(panel.x)
                right = int(panel.x + panel.width)
                top = int(panel.y)
                bottom = int(panel.y + panel.height)
                targets.append(SnapTarget("x", left, "panel_edge", tag))
                targets.append(SnapTarget("x", right, "panel_edge", tag))
                targets.append(SnapTarget("y", top, "panel_edge", tag))
                targets.append(SnapTarget("y", bottom, "panel_edge", tag))

        if cfg.enable_grid and cfg.grid_size > 0:
            vw, vh = self._viewport_size
            step = int(cfg.grid_size)
            # Vertical grid lines (axis=x).
            x = 0
            while x <= vw:
                targets.append(SnapTarget("x", x, "grid_line"))
                x += step
            # Horizontal grid lines (axis=y).
            y = 0
            while y <= vh:
                targets.append(SnapTarget("y", y, "grid_line"))
                y += step

        return targets

    # ------------------------------------------------------------------
    # Drag lifecycle
    # ------------------------------------------------------------------

    def on_drag_start(self, panel_tag: str) -> None:
        """Cache the snap targets for the duration of the drag.

        Idempotent — calling twice with the same tag simply refreshes.
        Unknown tags are silently ignored (the editor may register
        panels in any order).
        """
        panel = self._panels.get(panel_tag)
        if panel is None:
            return
        self._drag = _DragState(
            panel_tag=panel_tag,
            start_mouse=(0, 0),       # filled on first tick
            start_panel=(int(panel.x), int(panel.y)),
            targets=self.compute_snap_targets(panel_tag),
        )

    def on_drag_tick(
        self,
        panel_tag: str,
        mouse_pos: tuple[int, int],
    ) -> tuple[int, int]:
        """Return the (possibly snapped) ``(x, y)`` the panel should adopt.

        The caller passes the **desired** top-left of the panel — i.e.
        the position it would move to absent any snapping.  The manager
        compares the panel's four edges against every cached snap target
        and adjusts the x and y axes independently.  On each axis, the
        first matching target within ``threshold_px`` wins.
        """
        if self._drag is None or self._drag.panel_tag != panel_tag:
            # Drag not started for this tag — pass through.
            return (int(mouse_pos[0]), int(mouse_pos[1]))

        panel = self._panels.get(panel_tag)
        if panel is None:
            return (int(mouse_pos[0]), int(mouse_pos[1]))

        desired_x, desired_y = int(mouse_pos[0]), int(mouse_pos[1])
        width, height = int(panel.width), int(panel.height)
        threshold = int(self.config.threshold_px)

        snapped_x = desired_x
        snapped_y = desired_y
        self._drag.active_x = None
        self._drag.active_y = None

        for tgt in self._drag.targets:
            if tgt.axis == "x" and self._drag.active_x is None:
                # Panel's two vertical edges.
                left = desired_x
                right = desired_x + width
                if abs(left - tgt.position) <= threshold:
                    snapped_x = tgt.position
                    self._drag.active_x = tgt
                elif abs(right - tgt.position) <= threshold:
                    snapped_x = tgt.position - width
                    self._drag.active_x = tgt
            elif tgt.axis == "y" and self._drag.active_y is None:
                top = desired_y
                bottom = desired_y + height
                if abs(top - tgt.position) <= threshold:
                    snapped_y = tgt.position
                    self._drag.active_y = tgt
                elif abs(bottom - tgt.position) <= threshold:
                    snapped_y = tgt.position - height
                    self._drag.active_y = tgt

            if self._drag.active_x is not None and self._drag.active_y is not None:
                break

        return (snapped_x, snapped_y)

    def on_drag_end(self, panel_tag: str) -> None:
        """Clear the cached drag state and any active guide lines."""
        if self._drag is not None and self._drag.panel_tag == panel_tag:
            self._drag = None

    # ------------------------------------------------------------------
    # Accessors used by the GUI for guide-line rendering
    # ------------------------------------------------------------------

    @property
    def active_snap_x(self) -> SnapTarget | None:
        """The currently-fired x-axis snap, or ``None``."""
        return self._drag.active_x if self._drag is not None else None

    @property
    def active_snap_y(self) -> SnapTarget | None:
        return self._drag.active_y if self._drag is not None else None

    @property
    def is_dragging(self) -> bool:
        return self._drag is not None

    @property
    def registered_tags(self) -> list[str]:
        return list(self._panels.keys())

    def iter_targets(self) -> Iterable[SnapTarget]:
        """Iterate over the cached targets of the current drag, if any."""
        if self._drag is None:
            return iter(())
        return iter(self._drag.targets)


__all__ = ["SnapTarget", "SnapConfig", "SnapManager"]
