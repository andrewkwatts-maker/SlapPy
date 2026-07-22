"""Viewport gizmo overlay with hand-drawn move/rotate/scale handles.

This is the *interactive* companion to :mod:`notebook_gizmos` — where
:class:`notebook_gizmos.NotebookGizmoOverlay` focuses on the pencil-styled
*visual reskin* (heart handles, chalk grain, star-tick sparkles), this
module owns the **selection-aware transform overlay** the diary editor
paints on top of the viewport panel:

* A bounding-box driven anchor: ``set_selection_bbox((x, y, w, h))``
  positions the gizmo at the selection AABB centre, auto-hiding when
  the caller passes ``None``.
* Three swappable handle sets (:data:`TOOL_MOVE`, :data:`TOOL_ROTATE`,
  :data:`TOOL_SCALE`) toggled via :meth:`set_tool`.
* A drag lifecycle — :meth:`on_drag_start` / :meth:`on_drag` /
  :meth:`on_drag_end` — that publishes a delta callback registered with
  :meth:`set_on_transform`.

The hand-drawn look is a small, deterministic wobble on every line
(``_hand_drawn_line``): each polyline sample is offset perpendicular to
the segment by a value in ``[-JITTER_PX, +JITTER_PX]`` derived from a
stable FNV-1a hash of the segment endpoints + a per-line seed. Same
inputs → same jitter, so tests can pin exact pixel geometry.

Colours resolve from the active theme's semantic tokens per the diary
brief:

* Move X-axis → ``ThemeSpec.semantic.accent`` (warm colour).
* Move Y-axis → ``ThemeSpec.semantic.primary`` (cool colour).
* Rotate ring → soft gray from ``text_secondary`` fallback.
* Scale handles → soft gray from ``text_secondary`` fallback.

The overlay is draw-list agnostic — a recording mock in the tests, a
real DPG front drawlist in the shell. Any object exposing ``add_line``,
``add_circle``, ``add_polyline`` and ``add_quad`` will drive it.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Protocol

__all__ = [
    "TOOL_MOVE",
    "TOOL_ROTATE",
    "TOOL_SCALE",
    "VALID_TOOLS",
    "NotebookGizmoOverlay",
    "DrawListLike",
]


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Tool identifier for the two-axis move gizmo.
TOOL_MOVE: str = "move"

#: Tool identifier for the rotate arc gizmo.
TOOL_ROTATE: str = "rotate"

#: Tool identifier for the eight-handle scale gizmo.
TOOL_SCALE: str = "scale"

#: Tuple of all valid tool ids — useful for validation.
VALID_TOOLS: tuple[str, str, str] = (TOOL_MOVE, TOOL_ROTATE, TOOL_SCALE)


# ---------------------------------------------------------------------------
# Fallback colours — used when no theme is registered.
# ---------------------------------------------------------------------------

# Warm accent colour for the X-axis arrow (falls back to a friendly amber).
_FALLBACK_ACCENT: tuple[int, int, int, int] = (255, 180, 70, 235)
# Cool primary colour for the Y-axis arrow (falls back to a diary blue).
_FALLBACK_PRIMARY: tuple[int, int, int, int] = (100, 140, 220, 235)
# Neutral gray for the rotate ring + scale corner handles.
_FALLBACK_GRAY: tuple[int, int, int, int] = (120, 110, 140, 220)
_FALLBACK_INK: tuple[int, int, int, int] = (60, 50, 80, 235)


# ---------------------------------------------------------------------------
# Draw-list protocol
# ---------------------------------------------------------------------------


class DrawListLike(Protocol):
    """Narrow subset of DPG's viewport drawlist consumed by the overlay."""

    def add_line(
        self,
        p1: tuple[float, float],
        p2: tuple[float, float],
        color: tuple[int, int, int, int],
        thickness: float,
    ) -> None: ...

    def add_polyline(
        self,
        points: list[tuple[float, float]],
        color: tuple[int, int, int, int],
        thickness: float,
    ) -> None: ...

    def add_circle(
        self,
        center: tuple[float, float],
        radius: float,
        color: tuple[int, int, int, int],
        thickness: float,
        fill: tuple[int, int, int, int] | None,
    ) -> None: ...

    def add_quad(
        self,
        p1: tuple[float, float],
        p2: tuple[float, float],
        p3: tuple[float, float],
        p4: tuple[float, float],
        color: tuple[int, int, int, int],
        fill: tuple[int, int, int, int] | None,
    ) -> None: ...


# ---------------------------------------------------------------------------
# Deterministic hand-drawn jitter helpers.
# ---------------------------------------------------------------------------


def _stable_hash(*parts: Any) -> int:
    """A tiny deterministic hash — stable across processes.

    Python's built-in ``hash()`` is salted per-interpreter which would
    make the wobble non-reproducible across runs. FNV-1a over the string
    repr gives us the reproducibility the tests pin.
    """
    s = "|".join(repr(p) for p in parts)
    h = 2166136261
    for ch in s.encode("utf-8"):
        h ^= ch
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def _jitter_samples(seed: int, count: int, amplitude: float) -> list[float]:
    """Return ``count`` deterministic offsets in ``[-amplitude, amplitude]``.

    Small LCG seeded off *seed* + 3-tap moving average so the resulting
    wobble reads as hand-drawn jitter rather than salt-and-pepper.
    """
    if count <= 0:
        return []
    state = (seed | 1) & 0xFFFFFFFF  # keep odd so the LCG never collapses
    raw = []
    for _ in range(count + 2):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        raw.append((state / 0x3FFFFFFF) - 1.0)
    smoothed = []
    for i in range(count):
        v = (raw[i] + raw[i + 1] + raw[i + 2]) / 3.0
        smoothed.append(v * amplitude)
    return smoothed


def _hand_drawn_line(
    draw_list: DrawListLike,
    start: tuple[float, float],
    end: tuple[float, float],
    color: tuple[int, int, int, int],
    *,
    thickness: float = 2.5,
    seed: int = 0,
    jitter_px: float = 1.4,
    samples: int | None = None,
) -> list[tuple[float, float]]:
    """Draw *start* → *end* as a wobbled polyline and return its points.

    The polyline is sampled along the segment and each sample is offset
    perpendicular to the direction of travel by a value drawn from
    :func:`_jitter_samples`. The result reads as a pencil-drawn line
    without needing a texture.

    Parameters
    ----------
    draw_list:
        Any object exposing ``add_polyline``.
    start, end:
        Segment endpoints in pixel space.
    color:
        RGBA tuple; passed through unchanged to the drawlist.
    thickness:
        Passed through as the ``thickness`` kwarg.
    seed:
        Deterministic seed — same seed + same endpoints → same wobble.
    jitter_px:
        Peak-to-peak jitter amplitude in pixels. The overlay uses a
        1.4 px default which reads as "gentle handmade" without looking
        broken. Tests can pass ``0`` to get a straight line.
    samples:
        Optional override for the sample count. Defaults to one sample
        per 6 px of stroke length with a minimum of 4 samples so short
        handles still get a couple of waves.

    Returns
    -------
    list[tuple[float, float]]
        The wobbled points — callers can inspect the endpoints to place
        arrowheads or heart glyphs at the same wobble.
    """
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 1e-3:
        # Degenerate — emit a single dot-ish polyline.
        draw_list.add_polyline(
            [start, end], color=color, thickness=thickness,
        )
        return [start, end]
    ux, uy = dx / length, dy / length
    px, py = -uy, ux  # perpendicular unit vector

    if samples is None:
        samples = max(4, int(length / 6.0))
    offsets = _jitter_samples(seed, samples + 1, jitter_px)
    points: list[tuple[float, float]] = []
    for i in range(samples + 1):
        t = i / samples
        x = start[0] + dx * t + px * offsets[i]
        y = start[1] + dy * t + py * offsets[i]
        points.append((x, y))
    draw_list.add_polyline(points, color=color, thickness=thickness)
    return points


def _hand_drawn_arc(
    draw_list: DrawListLike,
    center: tuple[float, float],
    radius: float,
    start_angle: float,
    end_angle: float,
    color: tuple[int, int, int, int],
    *,
    thickness: float = 2.5,
    seed: int = 0,
    jitter_px: float = 1.4,
    samples: int = 24,
) -> list[tuple[float, float]]:
    """Draw a wobbled arc and return the sampled points."""
    offsets = _jitter_samples(seed, samples + 1, jitter_px)
    pts: list[tuple[float, float]] = []
    for i in range(samples + 1):
        t = i / samples
        a = start_angle + (end_angle - start_angle) * t
        r = radius + offsets[i]
        pts.append((center[0] + math.cos(a) * r, center[1] + math.sin(a) * r))
    draw_list.add_polyline(pts, color=color, thickness=thickness)
    return pts


def _draw_arrowhead(
    draw_list: DrawListLike,
    tip: tuple[float, float],
    direction: tuple[float, float],
    color: tuple[int, int, int, int],
    *,
    size: float = 10.0,
) -> None:
    """Two-line arrowhead pointing along *direction* from *tip*."""
    dx, dy = direction
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    back_x = tip[0] - ux * size
    back_y = tip[1] - uy * size
    left = (back_x + px * size * 0.55, back_y + py * size * 0.55)
    right = (back_x - px * size * 0.55, back_y - py * size * 0.55)
    draw_list.add_line(tip, left, color=color, thickness=2.0)
    draw_list.add_line(tip, right, color=color, thickness=2.0)


def _draw_handle_box(
    draw_list: DrawListLike,
    center: tuple[float, float],
    half_size: float,
    color: tuple[int, int, int, int],
    *,
    seed: int = 0,
    jitter_px: float = 0.7,
) -> None:
    """Small pencil-boxed handle — 4 hand-drawn edges around *center*."""
    cx, cy = center
    tl = (cx - half_size, cy - half_size)
    tr = (cx + half_size, cy - half_size)
    br = (cx + half_size, cy + half_size)
    bl = (cx - half_size, cy + half_size)
    _hand_drawn_line(draw_list, tl, tr, color,
                     thickness=1.8, seed=seed, jitter_px=jitter_px, samples=4)
    _hand_drawn_line(draw_list, tr, br, color,
                     thickness=1.8, seed=seed + 1, jitter_px=jitter_px, samples=4)
    _hand_drawn_line(draw_list, br, bl, color,
                     thickness=1.8, seed=seed + 2, jitter_px=jitter_px, samples=4)
    _hand_drawn_line(draw_list, bl, tl, color,
                     thickness=1.8, seed=seed + 3, jitter_px=jitter_px, samples=4)


# ---------------------------------------------------------------------------
# Theme resolution helpers
# ---------------------------------------------------------------------------


def _color_to_rgba(
    value: Any, fallback: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    """Coerce a theme Color / tuple to an int RGBA tuple with a fallback."""
    if value is None:
        return fallback
    cvt = getattr(value, "as_rgba_tuple", None)
    if callable(cvt):
        try:
            r, g, b, a = cvt()
            return (int(r), int(g), int(b), int(a))
        except Exception:
            return fallback
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        r = int(value[0])
        g = int(value[1])
        b = int(value[2])
        a = int(value[3]) if len(value) > 3 else 255
        return (r, g, b, a)
    return fallback


def _resolve_semantic(
    theme: Any,
    field_name: str,
    fallback: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    """Look up ``theme.semantic.<field_name>`` with a plain-tuple fallback."""
    if theme is None:
        return fallback
    sem = getattr(theme, "semantic", None)
    if sem is None:
        return fallback
    return _color_to_rgba(getattr(sem, field_name, None), fallback)


# ---------------------------------------------------------------------------
# Public overlay class
# ---------------------------------------------------------------------------


class NotebookGizmoOverlay:
    """Interactive move/rotate/scale gizmo painted on the viewport.

    The overlay tracks a single AABB anchor. Calling
    :meth:`set_selection_bbox` with ``None`` hides the gizmo entirely
    (subsequent :meth:`render` calls become no-ops).

    Handle sets swap via :meth:`set_tool` — see :data:`TOOL_MOVE`,
    :data:`TOOL_ROTATE` and :data:`TOOL_SCALE`. The drag lifecycle
    publishes deltas via a single ``(tool_kind, delta_tuple)`` callback
    registered with :meth:`set_on_transform`.

    Delta shapes
    ------------
    ``TOOL_MOVE``
        ``(dx, dy)`` — world-unit delta from the drag anchor.
    ``TOOL_ROTATE``
        ``(d_radians,)`` — signed angle delta from the anchor point to
        the current mouse position, both measured relative to the
        selection centre.
    ``TOOL_SCALE``
        ``(sx, sy)`` — scale factor derived from the ratio of the
        current mouse distance to the drag-anchor distance from the
        selection centre.
    """

    #: Length of the move-tool arrow shafts in pixels.
    MOVE_ARROW_LEN: int = 60
    #: Radius of the rotate-tool arc in pixels.
    ROTATE_RADIUS: int = 55
    #: Half-size of every scale handle in pixels.
    SCALE_HANDLE_HALF: int = 6
    #: Pixel radius for hit-testing handle centres.
    HIT_RADIUS: int = 10
    #: Peak-to-peak jitter magnitude used for the pencil wobble.
    JITTER_PX: float = 1.4
    #: Number of tick marks around the rotate arc.
    ROTATE_TICK_COUNT: int = 8

    def __init__(self) -> None:
        self._tool: str = TOOL_MOVE
        self._bbox: tuple[float, float, float, float] | None = None
        self._on_transform: Callable[[str, tuple], None] | None = None
        self._theme_override: Any | None = None

        # Drag state.
        self._drag_active: bool = False
        self._drag_handle: str | None = None
        self._drag_anchor_mouse: tuple[float, float] | None = None
        self._drag_anchor_center: tuple[float, float] | None = None
        self._drag_anchor_angle: float | None = None
        self._drag_anchor_dist: float | None = None

    # ------------------------------------------------------------------
    # Public setters
    # ------------------------------------------------------------------

    def set_tool(self, tool: str) -> None:
        """Swap the visible handle set.

        Parameters
        ----------
        tool:
            One of :data:`TOOL_MOVE`, :data:`TOOL_ROTATE`,
            :data:`TOOL_SCALE`. Any other value raises ``ValueError``.
        """
        if tool not in VALID_TOOLS:
            raise ValueError(
                f"NotebookGizmoOverlay.set_tool: tool must be one of "
                f"{VALID_TOOLS!r}; got {tool!r}"
            )
        if tool != self._tool:
            # Swapping tools mid-drag cancels the current transform so
            # deltas from a rotate anchor don't leak into a move handle.
            self._reset_drag()
        self._tool = tool

    def set_selection_bbox(
        self, bbox: tuple[float, float, float, float] | None,
    ) -> None:
        """Anchor the gizmo to the selection AABB centre.

        Passing ``None`` hides the gizmo — subsequent :meth:`render`
        calls become no-ops and :meth:`is_visible` returns ``False``.
        """
        if bbox is None:
            self._bbox = None
            self._reset_drag()
            return
        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            raise TypeError(
                "NotebookGizmoOverlay.set_selection_bbox: bbox must be a "
                "4-tuple (x, y, w, h) or None"
            )
        x, y, w, h = bbox[0], bbox[1], bbox[2], bbox[3]
        self._bbox = (float(x), float(y), float(w), float(h))

    def set_on_transform(
        self, callback: Callable[[str, tuple], None] | None,
    ) -> None:
        """Register the delta callback fired by :meth:`on_drag`.

        Signature: ``callback(tool_kind: str, delta_tuple: tuple)``.
        Passing ``None`` clears the callback so drag events become
        silent no-ops.
        """
        self._on_transform = callback

    def set_theme(self, theme: Any) -> None:
        """Override the active theme for colour resolution.

        Pass ``None`` to fall back to
        :func:`pharos_editor.ui.theme.get_active_theme`.
        """
        self._theme_override = theme

    # ------------------------------------------------------------------
    # Read-only accessors — useful in tests and inspector panels.
    # ------------------------------------------------------------------

    @property
    def tool(self) -> str:
        return self._tool

    @property
    def bbox(self) -> tuple[float, float, float, float] | None:
        return self._bbox

    def is_visible(self) -> bool:
        """Return ``True`` when a selection is set — mirrors auto-hide."""
        return self._bbox is not None

    def is_dragging(self) -> bool:
        return self._drag_active

    def center(self) -> tuple[float, float] | None:
        """Return the pixel centre of the anchored bounding box (or ``None``)."""
        if self._bbox is None:
            return None
        x, y, w, h = self._bbox
        return (x + w * 0.5, y + h * 0.5)

    # ------------------------------------------------------------------
    # Theme resolution
    # ------------------------------------------------------------------

    def _theme(self) -> Any:
        if self._theme_override is not None:
            return self._theme_override
        try:
            from pharos_editor.ui.theme import get_active_theme
            return get_active_theme()
        except Exception:
            return None

    def _x_axis_color(self) -> tuple[int, int, int, int]:
        return _resolve_semantic(self._theme(), "accent", _FALLBACK_ACCENT)

    def _y_axis_color(self) -> tuple[int, int, int, int]:
        return _resolve_semantic(self._theme(), "primary", _FALLBACK_PRIMARY)

    def _gray_color(self) -> tuple[int, int, int, int]:
        return _resolve_semantic(
            self._theme(), "text_secondary", _FALLBACK_GRAY,
        )

    def _ink_color(self) -> tuple[int, int, int, int]:
        return _resolve_semantic(
            self._theme(), "text_primary", _FALLBACK_INK,
        )

    # ------------------------------------------------------------------
    # Handle geometry — used by hit-testing and rendering.
    # ------------------------------------------------------------------

    def handle_positions(self) -> dict[str, tuple[float, float]]:
        """Return a dict of ``handle_id → (px, py)`` for the current tool.

        Empty when no selection is set. Handle ids are stable strings
        matching those returned by :meth:`hit_test` and consumed by
        :meth:`on_drag_start`.
        """
        c = self.center()
        if c is None:
            return {}
        cx, cy = c
        if self._tool == TOOL_MOVE:
            return {
                "move_x": (cx + self.MOVE_ARROW_LEN, cy),
                "move_y": (cx, cy - self.MOVE_ARROW_LEN),
                "move_xy": (cx, cy),
            }
        if self._tool == TOOL_ROTATE:
            # Drag handle at 3 o'clock (angle 0).
            return {
                "rotate_handle": (cx + self.ROTATE_RADIUS, cy),
            }
        if self._tool == TOOL_SCALE:
            x, y, w, h = self._bbox  # type: ignore[misc]
            return {
                "scale_tl": (x, y),
                "scale_tr": (x + w, y),
                "scale_br": (x + w, y + h),
                "scale_bl": (x, y + h),
                "scale_top": (x + w * 0.5, y),
                "scale_right": (x + w, y + h * 0.5),
                "scale_bottom": (x + w * 0.5, y + h),
                "scale_left": (x, y + h * 0.5),
            }
        return {}

    def handle_count(self) -> int:
        """Return the number of handles the current tool exposes."""
        return len(self.handle_positions())

    def hit_test(self, mouse_xy: tuple[float, float]) -> str | None:
        """Return the handle id under *mouse_xy* or ``None``."""
        if not self.is_visible():
            return None
        if not isinstance(mouse_xy, (list, tuple)) or len(mouse_xy) < 2:
            return None
        mx = float(mouse_xy[0])
        my = float(mouse_xy[1])
        r = float(self.HIT_RADIUS)
        best_key: str | None = None
        best_dist = r
        for key, (hx, hy) in self.handle_positions().items():
            d = math.hypot(mx - hx, my - hy)
            if d <= best_dist:
                best_dist = d
                best_key = key
        # For rotate, the arc itself is also draggable — snap to the
        # closest point on the circumference within a small band.
        if best_key is None and self._tool == TOOL_ROTATE:
            c = self.center()
            if c is not None:
                d = math.hypot(mx - c[0], my - c[1])
                if abs(d - self.ROTATE_RADIUS) <= 6.0:
                    return "rotate_ring"
        return best_key

    # ------------------------------------------------------------------
    # Drag lifecycle
    # ------------------------------------------------------------------

    def on_drag_start(
        self,
        handle_id: str,
        mouse_xy: tuple[float, float],
    ) -> None:
        """Record the drag anchor for later delta calculations.

        Called by the shell when the user presses a mouse button while
        hovering a handle. The exact *handle_id* is only used for
        bookkeeping; the delta shape is picked from :attr:`tool`.
        """
        if not self.is_visible():
            return
        if not isinstance(mouse_xy, (list, tuple)) or len(mouse_xy) < 2:
            raise TypeError(
                "NotebookGizmoOverlay.on_drag_start: mouse_xy must be a "
                "2-tuple (x, y)"
            )
        c = self.center()
        if c is None:
            return
        mx = float(mouse_xy[0])
        my = float(mouse_xy[1])
        self._drag_active = True
        self._drag_handle = handle_id
        self._drag_anchor_mouse = (mx, my)
        self._drag_anchor_center = c
        dx = mx - c[0]
        dy = my - c[1]
        self._drag_anchor_angle = math.atan2(dy, dx)
        self._drag_anchor_dist = max(1e-3, math.hypot(dx, dy))

    def on_drag(self, mouse_xy: tuple[float, float]) -> tuple | None:
        """Publish a delta callback for the current drag.

        Returns the delta tuple in addition to firing the callback so
        headless tests don't need to install a callback to inspect the
        payload.

        Delta shapes per tool
        ---------------------
        ``TOOL_MOVE``
            ``(dx, dy)`` — mouse delta from the anchor (world units).
        ``TOOL_ROTATE``
            ``(d_radians,)`` — signed angle delta from the anchor.
        ``TOOL_SCALE``
            ``(sx, sy)`` — ratio of the current mouse-to-centre distance
            to the anchor distance. Same scalar for both axes (uniform
            scale) which matches the diary editor's UX contract.
        """
        if not self._drag_active or self._drag_anchor_mouse is None:
            return None
        if not isinstance(mouse_xy, (list, tuple)) or len(mouse_xy) < 2:
            return None
        mx = float(mouse_xy[0])
        my = float(mouse_xy[1])

        delta: tuple
        if self._tool == TOOL_MOVE:
            ax, ay = self._drag_anchor_mouse
            delta = (mx - ax, my - ay)
        elif self._tool == TOOL_ROTATE:
            c = self._drag_anchor_center or (0.0, 0.0)
            cur_angle = math.atan2(my - c[1], mx - c[0])
            anchor_angle = self._drag_anchor_angle or 0.0
            d = cur_angle - anchor_angle
            # Wrap into (-pi, pi] so a small drag never yields a full turn.
            while d > math.pi:
                d -= 2.0 * math.pi
            while d < -math.pi:
                d += 2.0 * math.pi
            delta = (d,)
        elif self._tool == TOOL_SCALE:
            c = self._drag_anchor_center or (0.0, 0.0)
            cur_dist = math.hypot(mx - c[0], my - c[1])
            anchor_dist = self._drag_anchor_dist or 1.0
            ratio = cur_dist / anchor_dist
            delta = (ratio, ratio)
        else:
            return None

        cb = self._on_transform
        if cb is not None:
            try:
                cb(self._tool, delta)
            except Exception:
                # Delta callbacks must not crash the overlay — swallow
                # user-space errors and keep the drag responsive.
                pass
        return delta

    def on_drag_end(self) -> None:
        """Commit the drag and clear the anchor state."""
        self._reset_drag()

    def _reset_drag(self) -> None:
        self._drag_active = False
        self._drag_handle = None
        self._drag_anchor_mouse = None
        self._drag_anchor_center = None
        self._drag_anchor_angle = None
        self._drag_anchor_dist = None

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, draw_list: DrawListLike) -> None:
        """Paint the current tool's handles onto *draw_list*.

        No-op when :meth:`is_visible` is ``False``.
        """
        if not self.is_visible():
            return
        if draw_list is None:
            return
        c = self.center()
        if c is None:
            return
        if self._tool == TOOL_MOVE:
            self._render_move(draw_list, c)
        elif self._tool == TOOL_ROTATE:
            self._render_rotate(draw_list, c)
        elif self._tool == TOOL_SCALE:
            self._render_scale(draw_list, c)

    # --- move ----------------------------------------------------------

    def _render_move(
        self, draw_list: DrawListLike, center: tuple[float, float],
    ) -> None:
        cx, cy = center
        x_color = self._x_axis_color()
        y_color = self._y_axis_color()
        ink = self._ink_color()

        x_tip = (cx + self.MOVE_ARROW_LEN, cy)
        y_tip = (cx, cy - self.MOVE_ARROW_LEN)

        # X-axis arrow.
        x_seed = _stable_hash(center, self._tool, "x")
        _hand_drawn_line(
            draw_list, (cx, cy), x_tip, x_color,
            thickness=2.8, seed=x_seed, jitter_px=self.JITTER_PX,
        )
        _draw_arrowhead(draw_list, x_tip, (1.0, 0.0), x_color, size=10.0)

        # Y-axis arrow.
        y_seed = _stable_hash(center, self._tool, "y")
        _hand_drawn_line(
            draw_list, (cx, cy), y_tip, y_color,
            thickness=2.8, seed=y_seed, jitter_px=self.JITTER_PX,
        )
        _draw_arrowhead(draw_list, y_tip, (0.0, -1.0), y_color, size=10.0)

        # Centre plane handle — small filled circle.
        draw_list.add_circle(
            (cx, cy), 5.0, color=ink, thickness=1.5, fill=ink,
        )

    # --- rotate --------------------------------------------------------

    def _render_rotate(
        self, draw_list: DrawListLike, center: tuple[float, float],
    ) -> None:
        cx, cy = center
        gray = self._gray_color()
        ink = self._ink_color()

        # Hand-drawn arc — full circle rendered as a single wobbled polyline.
        ring_seed = _stable_hash(center, "rotate", "ring")
        _hand_drawn_arc(
            draw_list, (cx, cy), float(self.ROTATE_RADIUS),
            0.0, 2.0 * math.pi, gray,
            thickness=2.4, seed=ring_seed, jitter_px=self.JITTER_PX,
            samples=48,
        )

        # 8 tick marks around the ring.
        for i in range(self.ROTATE_TICK_COUNT):
            a = (2.0 * math.pi) * (i / self.ROTATE_TICK_COUNT)
            inner = (
                cx + math.cos(a) * (self.ROTATE_RADIUS - 5.0),
                cy + math.sin(a) * (self.ROTATE_RADIUS - 5.0),
            )
            outer = (
                cx + math.cos(a) * (self.ROTATE_RADIUS + 5.0),
                cy + math.sin(a) * (self.ROTATE_RADIUS + 5.0),
            )
            draw_list.add_line(inner, outer, color=ink, thickness=1.5)

        # Drag handle at 3 o'clock (angle 0).
        handle = (cx + self.ROTATE_RADIUS, cy)
        x_color = self._x_axis_color()
        draw_list.add_circle(
            handle, 6.0, color=x_color, thickness=1.5, fill=x_color,
        )

    # --- scale ---------------------------------------------------------

    def _render_scale(
        self, draw_list: DrawListLike, center: tuple[float, float],
    ) -> None:
        gray = self._gray_color()
        ink = self._ink_color()
        half = float(self.SCALE_HANDLE_HALF)

        # Guide rectangle around the selection — hand-drawn dashed feel.
        x, y, w, h = self._bbox  # type: ignore[misc]
        rect_seed = _stable_hash(center, "scale", "rect")
        _hand_drawn_line(
            draw_list, (x, y), (x + w, y), gray,
            thickness=1.4, seed=rect_seed, jitter_px=self.JITTER_PX * 0.7,
        )
        _hand_drawn_line(
            draw_list, (x + w, y), (x + w, y + h), gray,
            thickness=1.4, seed=rect_seed + 1,
            jitter_px=self.JITTER_PX * 0.7,
        )
        _hand_drawn_line(
            draw_list, (x + w, y + h), (x, y + h), gray,
            thickness=1.4, seed=rect_seed + 2,
            jitter_px=self.JITTER_PX * 0.7,
        )
        _hand_drawn_line(
            draw_list, (x, y + h), (x, y), gray,
            thickness=1.4, seed=rect_seed + 3,
            jitter_px=self.JITTER_PX * 0.7,
        )

        # 8 handle boxes — 4 corners + 4 edge midpoints.
        positions = self.handle_positions()
        for i, (key, pos) in enumerate(positions.items()):
            _draw_handle_box(
                draw_list, pos, half, ink,
                seed=_stable_hash(center, "scale", key, i),
                jitter_px=0.5,
            )


# ---------------------------------------------------------------------------
# Expose the internal helper for tests + downstream callers.
# ---------------------------------------------------------------------------

NotebookGizmoOverlay._hand_drawn_line = staticmethod(_hand_drawn_line)
NotebookGizmoOverlay._hand_drawn_arc = staticmethod(_hand_drawn_arc)
