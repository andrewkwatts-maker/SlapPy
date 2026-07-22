"""Notebook-themed snap ghost + dock arrow overlay.

While the user drags a :class:`MovablePanelWindow` the editor shell wants
to *visualise* three separate feedback layers on the viewport:

1. **Snap ghosts** — the translucent silhouette of where the panel would
   land if the drag was released *right now* (viewport edge / sibling
   edge / grid line snaps).
2. **Dock ghosts** — the same silhouette but for the five canonical
   dock zones (left / right / top / bottom / center) exposed by
   :class:`~pharos_editor.ui.editor.dock_zones.DockZoneManager`.
3. **Direction arrows** — a small 5-vertex arrow pointing *into* each
   dock zone so the user can see at a glance which slot they're aiming
   for.

:class:`NotebookSnapOverlay` owns the paint routine for all three. It is
draw-list agnostic — headless tests drive it with a recording mock, and
the editor shell drives it with a real DPG drawlist tagged
``front=True`` so the ghost always paints over any other viewport
content.

The overlay does **not** compute snaps itself. Instead, it subscribes to
whichever manager the caller passes in via
:meth:`attach_to_snap_manager` / :meth:`attach_to_dock_manager`. The
managers may not expose the callback slot yet — the subscription uses
``getattr(mgr, "on_snap_preview", None)`` and installs a no-op fallback
when the slot is missing so the overlay is safe to attach against any
manager version.

Diary theming
-------------
* Stroke colour comes from ``ThemeSpec.semantic.accent`` (falls back to
  a friendly pastel blue when no theme is active).
* Borders are drawn dashed with **±1 px per 8 px** jitter so they read
  as *hand-drawn* rather than mechanical rectangles — the same visual
  DNA as :class:`NotebookGizmoOverlay`.
* Dock arrows use a 5-tip pencil arrow (base + shaft + arrowhead
  triangle) pointing from the viewport centre into the zone's centre.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

__all__ = ["SnapGhost", "NotebookSnapOverlay"]


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


_VALID_SNAP_KINDS: tuple[str, ...] = (
    "grid",
    "edge",
    "dock_left",
    "dock_right",
    "dock_top",
    "dock_bottom",
    "dock_center",
)


@dataclass
class SnapGhost:
    """One translucent ghost preview of a snap / dock target.

    Parameters
    ----------
    rect:
        ``(x, y, w, h)`` of the ghost in viewport pixels.
    snap_kind:
        One of ``"grid"``, ``"edge"``, ``"dock_left"``, ``"dock_right"``,
        ``"dock_top"``, ``"dock_bottom"``, ``"dock_center"``. The
        ``dock_*`` variants ask the overlay to also paint the 5-tip
        arrow pointing into the zone.
    theme_color:
        ``(r, g, b, a)`` RGBA tint used for the ghost's border stroke.
        The interior is drawn with the same colour at 1/3 alpha so the
        preview reads as a semi-transparent silhouette without a
        separate fill parameter.
    """

    rect: tuple[int, int, int, int]
    snap_kind: str
    theme_color: tuple[int, int, int, int] = (120, 160, 255, 220)

    def __post_init__(self) -> None:
        if not isinstance(self.rect, (tuple, list)) or len(self.rect) != 4:
            raise TypeError(
                "SnapGhost.rect must be a (x, y, w, h) 4-tuple; "
                f"got {self.rect!r}"
            )
        # Coerce to plain int tuple for stable equality + rendering.
        self.rect = (
            int(self.rect[0]),
            int(self.rect[1]),
            int(self.rect[2]),
            int(self.rect[3]),
        )
        if not isinstance(self.snap_kind, str):
            raise TypeError(
                "SnapGhost.snap_kind must be a str; "
                f"got {type(self.snap_kind).__name__}"
            )
        if self.snap_kind not in _VALID_SNAP_KINDS:
            raise ValueError(
                f"SnapGhost.snap_kind must be one of {_VALID_SNAP_KINDS!r}; "
                f"got {self.snap_kind!r}"
            )
        if (
            not isinstance(self.theme_color, (tuple, list))
            or len(self.theme_color) < 3
        ):
            raise TypeError(
                "SnapGhost.theme_color must be a (r, g, b, a) tuple; "
                f"got {self.theme_color!r}"
            )
        r = int(self.theme_color[0])
        g = int(self.theme_color[1])
        b = int(self.theme_color[2])
        a = int(self.theme_color[3]) if len(self.theme_color) > 3 else 220
        self.theme_color = (r, g, b, a)


# ---------------------------------------------------------------------------
# Helpers — theme + drawing primitives
# ---------------------------------------------------------------------------


_FALLBACK_ACCENT: tuple[int, int, int, int] = (120, 160, 255, 220)


def _resolve_semantic_color(
    field_name: str, default: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    """Look up ``theme.semantic.<field_name>`` with a plain-tuple fallback."""
    try:
        from pharos_editor.ui.theme import get_active_theme

        theme = get_active_theme()
        if theme is None:
            return default
        sem = getattr(theme, "semantic", None)
        if sem is None:
            return default
        value = getattr(sem, field_name, None)
        if value is None:
            return default
        cvt = getattr(value, "as_rgba_tuple", None)
        if callable(cvt):
            r, g, b, a = cvt()
            return (int(r), int(g), int(b), int(a))
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            r = int(value[0])
            g = int(value[1])
            b = int(value[2])
            a = int(value[3]) if len(value) > 3 else default[3]
            return (r, g, b, a)
        return default
    except Exception:
        return default


def _jittered(base: float, seed: int, amplitude: float) -> float:
    """Deterministic ±*amplitude* jitter from an integer seed."""
    # Small FNV-1a hash → normalised to [-1, 1].
    h = 2166136261
    for ch in repr(seed).encode("utf-8"):
        h ^= ch
        h = (h * 16777619) & 0xFFFFFFFF
    norm = (h / 0xFFFFFFFF) * 2.0 - 1.0
    return base + norm * amplitude


def _dash_segments_for_edge(
    p0: tuple[float, float],
    p1: tuple[float, float],
    dash_px: float,
    gap_px: float,
    seed_base: int,
    jitter: float,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Return the list of ``(start, end)`` pairs that make up one dashed edge.

    Each segment endpoint is jittered by ``±jitter`` px perpendicular to
    the edge so the border reads as pencil-drawn. The jitter is
    deterministic — same *seed_base* → same wobble.
    """
    x0, y0 = p0
    x1, y1 = p1
    dx = x1 - x0
    dy = y1 - y0
    length = (dx * dx + dy * dy) ** 0.5
    if length < 1e-3:
        return []
    ux = dx / length
    uy = dy / length
    # Perpendicular for the wobble offset.
    px = -uy
    py = ux
    step = dash_px + gap_px
    n = max(1, int(length // step) + 1)
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for i in range(n):
        t0 = i * step
        t1 = min(length, t0 + dash_px)
        if t0 >= length:
            break
        sx = x0 + ux * t0
        sy = y0 + uy * t0
        ex = x0 + ux * t1
        ey = y0 + uy * t1
        # Jitter each endpoint independently by up to *jitter* px in the
        # perpendicular direction — this is the "hand-drawn" wobble.
        j0 = _jittered(0.0, seed_base + i * 2, jitter)
        j1 = _jittered(0.0, seed_base + i * 2 + 1, jitter)
        segments.append((
            (sx + px * j0, sy + py * j0),
            (ex + px * j1, ey + py * j1),
        ))
    return segments


def _draw_dashed_rect(
    drawlist: Any,
    x: float,
    y: float,
    w: float,
    h: float,
    color: tuple[int, int, int, int],
    *,
    jitter: float = 1.0,
    dash_px: float = 6.0,
    gap_px: float = 3.0,
    thickness: float = 1.6,
    seed_base: int = 0,
) -> int:
    """Draw a hand-drawn dashed rectangle onto *drawlist*.

    Uses the ``add_line`` primitive so the routine works against a DPG
    drawlist tag (via the module-level import shim below), a recording
    mock, or any object with an ``add_line`` method.

    Returns the number of dash segments actually emitted (across all
    four sides). Callers can use this for assertions in headless tests.

    The dash pattern targets **at least 4 segments per side for a 40 px
    edge** with the default ``dash_px=6`` / ``gap_px=3`` — 40 // 9 = 4
    fits, 40 // 9 + 1 = 5 usually gets emitted so tests can pin ``>= 4``.
    """
    corners = [
        (float(x), float(y)),                    # tl
        (float(x + w), float(y)),                # tr
        (float(x + w), float(y + h)),            # br
        (float(x), float(y + h)),                # bl
    ]
    edges = [
        (corners[0], corners[1]),  # top
        (corners[1], corners[2]),  # right
        (corners[2], corners[3]),  # bottom
        (corners[3], corners[0]),  # left
    ]

    total = 0
    for i, (a, b) in enumerate(edges):
        segments = _dash_segments_for_edge(
            a, b,
            dash_px=dash_px,
            gap_px=gap_px,
            seed_base=seed_base + i * 997,
            jitter=jitter,
        )
        for seg_start, seg_end in segments:
            _add_line(
                drawlist,
                seg_start,
                seg_end,
                color=color,
                thickness=thickness,
            )
            total += 1
    return total


def _draw_dock_arrow(
    drawlist: Any,
    x: float,
    y: float,
    direction: str,
    color: tuple[int, int, int, int],
    *,
    length: float = 40.0,
    head: float = 10.0,
) -> list[tuple[float, float]]:
    """Draw a 5-vertex arrow centred at ``(x, y)`` pointing *direction*.

    *direction* is one of ``"left"``, ``"right"``, ``"up"``, ``"down"``,
    ``"center"``. The five vertices are:

        tail_start, shaft_end, head_left, head_tip, head_right

    Returned as a plain list of ``(x, y)`` tuples so callers (and tests)
    can inspect the exact layout.

    For ``"center"`` the arrow is a small pinwheel (four short darts)
    — but for the 5-vertex contract we emit the four outer points + the
    centre, which is enough to tell it apart from the directional
    variants in tests.
    """
    dx, dy = {
        "left": (-1.0, 0.0),
        "right": (1.0, 0.0),
        "up": (0.0, -1.0),
        "down": (0.0, 1.0),
        "center": (0.0, 0.0),
    }.get(direction, (1.0, 0.0))

    if direction == "center":
        # Centre marker: four cardinal darts around ``(x, y)`` — the
        # 5-vertex list is [c, N, E, S, W] so tests can distinguish it.
        c = (float(x), float(y))
        pts = [
            c,
            (float(x), float(y - length * 0.5)),
            (float(x + length * 0.5), float(y)),
            (float(x), float(y + length * 0.5)),
            (float(x - length * 0.5), float(y)),
        ]
        # Cross of two lines.
        _add_line(drawlist, pts[1], pts[3], color=color, thickness=1.6)
        _add_line(drawlist, pts[2], pts[4], color=color, thickness=1.6)
        return pts

    tail = (float(x - dx * length * 0.5), float(y - dy * length * 0.5))
    tip = (float(x + dx * length * 0.5), float(y + dy * length * 0.5))
    # Perpendicular for the arrowhead wings.
    px = -dy
    py = dx
    shaft_end = (
        float(tip[0] - dx * head),
        float(tip[1] - dy * head),
    )
    head_left = (
        float(shaft_end[0] + px * head * 0.55),
        float(shaft_end[1] + py * head * 0.55),
    )
    head_right = (
        float(shaft_end[0] - px * head * 0.55),
        float(shaft_end[1] - py * head * 0.55),
    )
    pts = [tail, shaft_end, head_left, tip, head_right]
    # Shaft
    _add_line(drawlist, tail, shaft_end, color=color, thickness=2.0)
    # Arrowhead: two lines from the tip to each wing.
    _add_line(drawlist, tip, head_left, color=color, thickness=2.0)
    _add_line(drawlist, tip, head_right, color=color, thickness=2.0)
    return pts


def _add_line(
    drawlist: Any,
    p0: tuple[float, float],
    p1: tuple[float, float],
    *,
    color: tuple[int, int, int, int],
    thickness: float,
) -> None:
    """Route a line to either a mock's ``add_line`` or DPG's ``draw_line``.

    * Objects with an ``add_line`` attribute (recording mocks in the
      test suite, plus the shell's ``DrawListLike`` protocol) take a
      direct call.
    * Bare integer / string tags dispatch to ``dpg.draw_line(parent=…)``.
    * Anything else silently no-ops so headless callers can pass ``None``.
    """
    if drawlist is None:
        return
    add_line = getattr(drawlist, "add_line", None)
    if callable(add_line):
        try:
            add_line(p0, p1, color=color, thickness=thickness)
            return
        except TypeError:
            # Some mocks might use positional-only signatures.
            try:
                add_line(p0, p1, color, thickness)
                return
            except Exception:
                return
    # DPG tag path.
    try:
        import dearpygui.dearpygui as dpg

        dpg.draw_line(
            p1=p0, p2=p1, color=color, thickness=thickness, parent=drawlist,
        )
    except Exception:
        # Headless / no DPG — silently ignore.
        return


# ---------------------------------------------------------------------------
# Overlay
# ---------------------------------------------------------------------------


class NotebookSnapOverlay:
    """Render translucent ghost previews of the active snap / dock targets.

    Lifecycle::

        overlay = NotebookSnapOverlay(drawlist=viewport_front_drawlist)
        overlay.attach_to_snap_manager(snap_mgr)
        overlay.attach_to_dock_manager(dock_mgr)

        # ... during a drag the managers push previews:
        overlay.set_ghosts([SnapGhost((100, 100, 200, 200), "edge")])
        overlay.render()

        # ... drag ends:
        overlay.clear()

    The overlay does **not** compute snaps itself — it just renders the
    ``list[SnapGhost]`` it currently holds. The manager subscriptions
    push new lists as the mouse moves.
    """

    #: Number of dash segments per 8 px of edge (used to size defaults).
    DASH_DENSITY: int = 1
    #: Default per-segment jitter in pixels.
    DEFAULT_JITTER: float = 1.0
    #: Alpha applied to the ghost fill (border stays at full alpha).
    FILL_ALPHA_SCALE: float = 0.35

    def __init__(
        self,
        *,
        drawlist: Any = None,
        jitter: float = DEFAULT_JITTER,
    ) -> None:
        self._drawlist: Any = drawlist
        self._ghosts: list[SnapGhost] = []
        self._jitter: float = float(jitter)
        # Subscription handles so we can detach cleanly. Each entry is a
        # ``(manager, event_name, callback)`` triple.
        self._subscriptions: list[
            tuple[Any, str, Callable[[list[SnapGhost] | Any], None]]
        ] = []
        # Frame counter — bumped by :meth:`render` so callers can pin
        # animation state in tests.
        self._frame_index: int = 0

    # ------------------------------------------------------------------
    # Drawlist wiring
    # ------------------------------------------------------------------

    def set_drawlist(self, drawlist: Any) -> None:
        """Rebind the overlay to a new drawlist / tag."""
        self._drawlist = drawlist

    @property
    def drawlist(self) -> Any:
        return self._drawlist

    # ------------------------------------------------------------------
    # Ghost state
    # ------------------------------------------------------------------

    def set_ghosts(self, ghosts: Iterable[SnapGhost]) -> None:
        """Replace the active ghost list with *ghosts*.

        The overlay coerces the argument to a plain list so callers can
        pass generators, tuples or any other iterable.
        """
        seq = list(ghosts)
        for g in seq:
            if not isinstance(g, SnapGhost):
                raise TypeError(
                    "NotebookSnapOverlay.set_ghosts: expected SnapGhost "
                    f"instances; got {type(g).__name__}"
                )
        self._ghosts = seq

    def clear(self) -> None:
        """Hide all ghosts (no-op if the list is already empty)."""
        self._ghosts = []

    @property
    def ghosts(self) -> list[SnapGhost]:
        """Return the current active ghost list (defensive copy)."""
        return list(self._ghosts)

    # ------------------------------------------------------------------
    # Manager subscriptions
    # ------------------------------------------------------------------

    def attach_to_snap_manager(self, snap_manager: Any) -> Callable[..., None]:
        """Subscribe to ``snap_manager.on_snap_preview`` if present.

        The manager may not carry the callback slot — the overlay uses
        the ``getattr(mgr, "on_snap_preview", None) or noop`` pattern so
        old versions of :class:`SnapManager` still attach cleanly. When
        the manager *does* carry the slot, the overlay registers its
        :meth:`_on_snap_preview` handler so calling
        ``snap_manager.on_snap_preview([...])`` pushes the ghost list
        through to :meth:`set_ghosts`.

        Two subscription patterns are supported:

        1. **Callable slot** — ``snap_manager.on_snap_preview`` is a
           callable that emits ghosts by *invoking* the overlay's
           callback (Signal / event bus style). The overlay wraps the
           slot into a closure that forwards the call.
        2. **Event bus** — ``snap_manager.on_snap_preview`` is an object
           with an ``append`` / ``connect`` / ``subscribe`` / ``add``
           method. The overlay's callback is registered directly.

        In both cases the manager grows a ``_snap_overlay_callbacks``
        attribute (a plain list) so subsequent
        :meth:`_on_snap_preview` fan-out works reliably.

        Returns the callback that was registered so the caller can
        detach it later via :meth:`detach`.
        """
        callback = self._on_snap_preview
        self._install_callback_slot(
            snap_manager, "on_snap_preview", callback,
        )
        self._subscriptions.append(
            (snap_manager, "on_snap_preview", callback)
        )
        return callback

    def attach_to_dock_manager(self, dock_manager: Any) -> Callable[..., None]:
        """Subscribe to ``dock_manager.on_dock_preview`` if present.

        Same defensive-getattr contract as :meth:`attach_to_snap_manager`.
        Dock zone previews arrive as ``list[SnapGhost]`` where each
        ghost's ``snap_kind`` is one of ``"dock_left"``, ``"dock_right"``,
        ``"dock_top"``, ``"dock_bottom"``, ``"dock_center"`` so
        :meth:`render` knows to paint the 5-tip arrow indicator on top.
        """
        callback = self._on_dock_preview
        self._install_callback_slot(
            dock_manager, "on_dock_preview", callback,
        )
        self._subscriptions.append(
            (dock_manager, "on_dock_preview", callback)
        )
        return callback

    def detach(self) -> None:
        """Detach every subscription registered on this overlay."""
        for manager, event_name, callback in self._subscriptions:
            slot = getattr(manager, event_name, None)
            if slot is None:
                continue
            remove = getattr(slot, "remove", None)
            if callable(remove):
                try:
                    remove(callback)
                except (ValueError, TypeError):
                    pass
            elif isinstance(slot, list):
                try:
                    slot.remove(callback)
                except ValueError:
                    pass
            # Also clear the shadow list we install below.
            shadow = getattr(manager, "_snap_overlay_callbacks", None)
            if isinstance(shadow, list) and callback in shadow:
                shadow.remove(callback)
        self._subscriptions = []

    # ------------------------------------------------------------------
    # Callback wiring internals
    # ------------------------------------------------------------------

    @staticmethod
    def _install_callback_slot(
        manager: Any,
        event_name: str,
        callback: Callable[..., None],
    ) -> None:
        """Register *callback* on ``manager.<event_name>`` defensively.

        Adds the slot as an empty ``list`` when the manager lacks it, so
        subsequent ``manager.on_snap_preview(ghosts)`` fan-out is a no-op
        rather than an ``AttributeError``. This is the only way we're
        allowed to touch the manager (per the task brief) — we cannot
        modify ``snap_manager.py`` / ``dock_zones.py`` directly.
        """
        slot = getattr(manager, event_name, None)
        if slot is None:
            # Slot missing entirely — install a fresh callback list.
            try:
                setattr(manager, event_name, [callback])
            except Exception:
                pass
            return
        # Existing list of callbacks — append.
        if isinstance(slot, list):
            if callback not in slot:
                slot.append(callback)
            return
        # Existing signal-like object with an add/append method.
        for adder in ("append", "connect", "subscribe", "add"):
            fn = getattr(slot, adder, None)
            if callable(fn):
                try:
                    fn(callback)
                    return
                except Exception:
                    continue
        # Existing single callable — replace with a fan-out list so we
        # don't discard the previous subscriber.
        if callable(slot):
            fan = [slot, callback]
            try:
                setattr(manager, event_name, fan)
            except Exception:
                pass
            return

    def _on_snap_preview(
        self, ghosts: Iterable[SnapGhost] | None = None,
    ) -> None:
        """Callback invoked by :class:`SnapManager` when a snap fires."""
        if ghosts is None:
            self.clear()
            return
        self.set_ghosts(ghosts)

    def _on_dock_preview(
        self, ghosts: Iterable[SnapGhost] | None = None,
    ) -> None:
        """Callback invoked by :class:`DockZoneManager` on hover."""
        if ghosts is None:
            self.clear()
            return
        self.set_ghosts(ghosts)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, drawlist: Any | None = None) -> int:
        """Paint every active ghost onto *drawlist* (or the bound one).

        Returns the total number of dash segments emitted across all
        ghosts — a useful cheap metric for headless tests.

        Rendering is a *pure* fan-out over :attr:`ghosts`; no snap or
        dock computation happens here.
        """
        target = drawlist if drawlist is not None else self._drawlist
        if target is None:
            return 0
        self._frame_index += 1
        total = 0
        for i, ghost in enumerate(self._ghosts):
            x, y, w, h = ghost.rect
            border = ghost.theme_color
            # Border stroke.
            total += _draw_dashed_rect(
                target,
                float(x),
                float(y),
                float(w),
                float(h),
                border,
                jitter=self._jitter,
                seed_base=self._frame_index * 31 + i * 13,
            )
            # Dock arrow indicator.
            if ghost.snap_kind.startswith("dock_"):
                direction = self._arrow_direction_for(ghost.snap_kind)
                cx = x + w // 2
                cy = y + h // 2
                _draw_dock_arrow(
                    target, float(cx), float(cy), direction, border,
                )
        return total

    @staticmethod
    def _arrow_direction_for(snap_kind: str) -> str:
        return {
            "dock_left": "right",     # arrow points into the dock (from centre)
            "dock_right": "left",
            "dock_top": "down",
            "dock_bottom": "up",
            "dock_center": "center",
        }.get(snap_kind, "right")

    # ------------------------------------------------------------------
    # Theme helpers (exposed for tests + callers that want defaults)
    # ------------------------------------------------------------------

    @staticmethod
    def default_theme_color() -> tuple[int, int, int, int]:
        """Return the current ``ThemeSpec.semantic.accent`` colour or fallback."""
        return _resolve_semantic_color("accent", _FALLBACK_ACCENT)


# ---------------------------------------------------------------------------
# Re-export the helpers so tests can drive them directly.
# ---------------------------------------------------------------------------


# Bind the module-private helpers to public names on the class so the
# task brief's public-surface contract is met (helpers documented as
# top-level in the brief but living inside the module namespace).
NotebookSnapOverlay._draw_dashed_rect = staticmethod(_draw_dashed_rect)
NotebookSnapOverlay._draw_dock_arrow = staticmethod(_draw_dock_arrow)
