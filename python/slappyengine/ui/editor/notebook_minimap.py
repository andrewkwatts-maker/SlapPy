"""``NotebookMinimap`` — diary-themed top-down minimap panel (FF6).

A small (default 200x200) floating panel that renders a top-down
miniature of the current scene into a 180x180 drawlist:

* Ruled-paper background.
* Each entity as a small coloured dot; colour comes from
  :data:`ENTITY_KIND_COLORS` and is looked up by "kind"
  (``prop``/``character``/``vehicle``/``particle``/``structural``).
* Camera viewport as a hand-drawn rectangle (deterministic ±1 px jitter
  per BB4 / Z2 style).
* Grid overlay every 10 world units.

Interactions
------------
* **Left-click** on the minimap invokes the ``on_pan_request(x, y)``
  callback with the *world* coordinate under the cursor (so the editor
  shell can pan its camera to that spot).
* **Right-click drag** offsets the minimap view (independent of the
  camera pan).
* **Scroll wheel** zooms the minimap in / out (clamped to a sane range).

Public API
----------
* :meth:`set_camera` — bind current camera state (any object with
  ``position`` + ``zoom`` + ``_viewport_size`` attributes).
* :meth:`set_scene` — bind current scene (FF3 ``Scene`` if present else
  duck-typed on ``scene.entities``).
* :meth:`set_world_bounds` — optional explicit ``(x, y, w, h)`` bounds.
* :meth:`refresh` — recomputes bounds and re-renders.
* :meth:`_project_world_to_minimap` / :meth:`_project_minimap_to_world`
  — round-tripping projection helpers.

Every ``dearpygui`` call is funnelled through ``_safe_dpg`` so the
panel imports and builds under a stub DPG in headless CI.
"""
from __future__ import annotations

import os
import types
from typing import Any, Callable, Iterable

__all__ = [
    "NotebookMinimap",
    "ENTITY_KIND_COLORS",
    "classify_entity",
]


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _is_real_dpg(dpg: Any) -> bool:
    """Return ``True`` when *dpg* is the real ``dearpygui.dearpygui`` module."""
    inner = getattr(dpg, "internal_dpg", None)
    if not isinstance(inner, types.ModuleType):
        return False
    return getattr(inner, "__name__", "").startswith("dearpygui")


def _headless_env_active() -> bool:
    """Return ``True`` when ``SLAPPY_HEADLESS=1`` (or truthy) is set."""
    val = os.environ.get("SLAPPY_HEADLESS", "")
    return val.strip().lower() in ("1", "true", "yes", "on")


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` if usable, else ``None``."""
    try:
        import dearpygui.dearpygui as dpg  # type: ignore[import-not-found]
    except Exception:
        return None
    if _is_real_dpg(dpg) and _headless_env_active():
        return None
    return dpg


# ---------------------------------------------------------------------------
# Entity kind palette
# ---------------------------------------------------------------------------


#: Canonical entity-kind → RGBA dot colour table.
ENTITY_KIND_COLORS: dict[str, tuple[int, int, int, int]] = {
    "prop":       (160, 160, 160, 255),   # gray
    "character":  (240, 130, 180, 255),   # pink
    "vehicle":    ( 80, 140, 220, 255),   # blue
    "particle":   (240, 220,  90, 255),   # yellow
    "structural": ( 90, 180, 120, 255),   # green
}

#: Fallback colour for unknown / uncategorised entities.
_DEFAULT_KIND_COLOR: tuple[int, int, int, int] = (110, 110, 110, 255)

_KIND_SET: frozenset[str] = frozenset(ENTITY_KIND_COLORS.keys())

# Tag / class-name heuristics used by :func:`classify_entity`.
_TAG_KIND_HINTS: tuple[tuple[str, str], ...] = (
    ("character", "character"),
    ("npc",       "character"),
    ("player",    "character"),
    ("enemy",     "character"),
    ("humanoid",  "character"),
    ("vehicle",   "vehicle"),
    ("car",       "vehicle"),
    ("bike",      "vehicle"),
    ("drone",     "vehicle"),
    ("particle",  "particle"),
    ("spark",     "particle"),
    ("fx",        "particle"),
    ("smoke",     "particle"),
    ("structure", "structural"),
    ("structural","structural"),
    ("wall",      "structural"),
    ("building",  "structural"),
    ("terrain",   "structural"),
    ("prop",      "prop"),
    ("item",      "prop"),
    ("pickup",    "prop"),
)


def classify_entity(entity: Any) -> str:
    """Return the minimap kind string for *entity*.

    Resolution order:

    1. Explicit ``entity.minimap_kind`` attribute (if one of the known
       kinds — otherwise ignored).
    2. Explicit ``entity.kind`` attribute (same rule).
    3. Any tag in ``entity.tags`` matching a keyword in
       :data:`_TAG_KIND_HINTS`.
    4. Class-name substring match against the same keyword set.
    5. Fallback ``"prop"``.
    """
    for attr in ("minimap_kind", "kind"):
        val = getattr(entity, attr, None)
        if isinstance(val, str) and val in _KIND_SET:
            return val

    tags = getattr(entity, "tags", None)
    tag_seq: list[str] = []
    if isinstance(tags, (set, frozenset, list, tuple)):
        tag_seq = [str(t).lower() for t in tags if isinstance(t, str)]
    for tag in tag_seq:
        for needle, kind in _TAG_KIND_HINTS:
            if needle in tag:
                return kind

    try:
        cls_name = type(entity).__name__.lower()
    except Exception:
        cls_name = ""
    for needle, kind in _TAG_KIND_HINTS:
        if needle in cls_name:
            return kind

    return "prop"


def _kind_color(kind: str) -> tuple[int, int, int, int]:
    return ENTITY_KIND_COLORS.get(kind, _DEFAULT_KIND_COLOR)


# ---------------------------------------------------------------------------
# Entity position helper
# ---------------------------------------------------------------------------


def _entity_position(entity: Any) -> tuple[float, float] | None:
    """Extract an ``(x, y)`` position from *entity*, else ``None``."""
    pos = getattr(entity, "position", None)
    if isinstance(pos, (list, tuple)) and len(pos) >= 2:
        try:
            return (float(pos[0]), float(pos[1]))
        except (TypeError, ValueError):
            return None
    # Fallback: separate ``x`` / ``y`` attributes.
    x = getattr(entity, "x", None)
    y = getattr(entity, "y", None)
    if x is not None and y is not None:
        try:
            return (float(x), float(y))
        except (TypeError, ValueError):
            return None
    return None


def _iter_scene_entities(scene: Any) -> list[Any]:
    """Return a plain list of entities from a Scene-like *scene*."""
    if scene is None:
        return []
    ents = getattr(scene, "entities", None)
    if ents is None:
        return []
    if isinstance(ents, (list, tuple)):
        return list(ents)
    try:
        return list(ents)
    except TypeError:
        return []


# ---------------------------------------------------------------------------
# Deterministic jitter — mirror BB4 / Z2 hand-drawn style.
# ---------------------------------------------------------------------------


def _fnv_hash(seed: Any) -> int:
    h = 2166136261
    for ch in repr(seed).encode("utf-8"):
        h ^= ch
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def _jitter(seed: int, amplitude: float) -> float:
    """Deterministic ``[-amplitude, amplitude]`` offset from *seed*."""
    norm = (_fnv_hash(seed) / 0xFFFFFFFF) * 2.0 - 1.0
    return norm * amplitude


# ---------------------------------------------------------------------------
# NotebookMinimap
# ---------------------------------------------------------------------------


class NotebookMinimap:
    """Top-down minimap panel with hand-drawn viewport rectangle.

    The panel is entirely headless-safe: all Dear PyGui calls are guarded
    through :func:`_safe_dpg`, and the projection helpers plus interaction
    handlers work without a live DPG context. That's what lets the tests
    exercise :meth:`on_left_click` / :meth:`on_right_drag` / :meth:`on_scroll`
    without booting a viewport.
    """

    TITLE: str = "Minimap"

    #: MovablePanelWindow minimums. The wrapper honours these + the body
    #: drawlist stays 180x180 with 10 px of chrome margin.
    MIN_WIDTH: int = 200
    MIN_HEIGHT: int = 200

    #: Default outer panel size.
    DEFAULT_WIDTH: int = 200
    DEFAULT_HEIGHT: int = 200

    #: Drawlist body size.
    BODY_WIDTH: int = 180
    BODY_HEIGHT: int = 180

    #: Grid step in *world* units.
    GRID_STEP: float = 10.0

    #: Zoom clamp bounds.
    MIN_ZOOM: float = 0.25
    MAX_ZOOM: float = 8.0

    #: Scroll wheel zoom factor (per notch).
    ZOOM_STEP: float = 1.2

    #: Default world bounds when the scene is empty.
    DEFAULT_BOUNDS: tuple[float, float, float, float] = (-50.0, -50.0, 100.0, 100.0)

    #: Padding fraction added around auto-fit bounds so entities don't
    #: sit right on the edge.
    AUTO_FIT_PADDING: float = 0.10

    _ROOT_TAG_PREFIX: str = "notebook_minimap_root"
    _DRAWLIST_TAG_PREFIX: str = "notebook_minimap_draw"

    def __init__(
        self,
        *,
        on_pan_request: Callable[[float, float], None] | None = None,
        world_bounds: tuple[float, float, float, float] | None = None,
    ) -> None:
        if on_pan_request is not None and not callable(on_pan_request):
            raise TypeError(
                "NotebookMinimap: on_pan_request must be callable or None; "
                f"got {type(on_pan_request).__name__}"
            )

        self._on_pan_request: Callable[[float, float], None] | None = on_pan_request
        self._camera: Any = None
        self._scene: Any = None
        self._entities: list[Any] = []

        # World bounds — either user-set (explicit) or auto-fit.
        self._explicit_bounds: tuple[float, float, float, float] | None = None
        if world_bounds is not None:
            self.set_world_bounds(world_bounds)
        self._world_bounds: tuple[float, float, float, float] = (
            self._explicit_bounds
            if self._explicit_bounds is not None
            else self.DEFAULT_BOUNDS
        )

        # View state — pan offset (in *world* units) and zoom multiplier.
        self._view_offset: tuple[float, float] = (0.0, 0.0)
        self._zoom: float = 1.0

        # Right-drag anchor — populated by :meth:`begin_right_drag`.
        self._right_drag_anchor: tuple[int, int] | None = None
        self._right_drag_start_offset: tuple[float, float] = (0.0, 0.0)

        # Build lifecycle.
        self._built: bool = False
        self._parent_tag: str | int | None = None
        self._root_tag: str = f"{self._ROOT_TAG_PREFIX}_{id(self)}"
        self._drawlist_tag: str = f"{self._DRAWLIST_TAG_PREFIX}_{id(self)}"

        # Frame counter — bumped by :meth:`refresh` so jitter is animated
        # deterministically between refreshes.
        self._frame_index: int = 0

        # Call log — headless test hook, records every rendered primitive.
        self.render_log: list[tuple[str, tuple[Any, ...]]] = []

    # ==================================================================
    # Bindings
    # ==================================================================

    def set_camera(self, camera: Any) -> None:
        """Bind the current camera. ``None`` clears the binding."""
        self._camera = camera

    def set_scene(self, scene: Any) -> None:
        """Bind the current scene and repopulate the entity cache."""
        self._scene = scene
        self._entities = _iter_scene_entities(scene)
        if self._explicit_bounds is None:
            self._world_bounds = self._auto_fit_bounds()

    def set_world_bounds(
        self, bounds: tuple[float, float, float, float] | None,
    ) -> None:
        """Set explicit world bounds ``(x, y, w, h)`` or clear (``None``)."""
        if bounds is None:
            self._explicit_bounds = None
            self._world_bounds = self._auto_fit_bounds()
            return
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
            raise TypeError(
                "NotebookMinimap.set_world_bounds: bounds must be a "
                f"(x, y, w, h) 4-tuple; got {bounds!r}"
            )
        x, y, w, h = bounds
        try:
            x_f = float(x)
            y_f = float(y)
            w_f = float(w)
            h_f = float(h)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                "NotebookMinimap.set_world_bounds: bounds must be numeric; "
                f"got {bounds!r}"
            ) from exc
        if w_f <= 0.0 or h_f <= 0.0:
            raise ValueError(
                "NotebookMinimap.set_world_bounds: width, height must be > 0; "
                f"got {(w_f, h_f)!r}"
            )
        self._explicit_bounds = (x_f, y_f, w_f, h_f)
        self._world_bounds = self._explicit_bounds

    # ==================================================================
    # State accessors
    # ==================================================================

    @property
    def camera(self) -> Any:
        return self._camera

    @property
    def scene(self) -> Any:
        return self._scene

    @property
    def entities(self) -> list[Any]:
        return list(self._entities)

    @property
    def world_bounds(self) -> tuple[float, float, float, float]:
        return self._world_bounds

    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def view_offset(self) -> tuple[float, float]:
        return self._view_offset

    @property
    def frame_index(self) -> int:
        return self._frame_index

    @property
    def on_pan_request(self) -> Callable[[float, float], None] | None:
        return self._on_pan_request

    @on_pan_request.setter
    def on_pan_request(self, cb: Callable[[float, float], None] | None) -> None:
        if cb is not None and not callable(cb):
            raise TypeError(
                "NotebookMinimap.on_pan_request must be callable or None; "
                f"got {type(cb).__name__}"
            )
        self._on_pan_request = cb

    # ==================================================================
    # Auto-fit
    # ==================================================================

    def _auto_fit_bounds(self) -> tuple[float, float, float, float]:
        """Compute a bounding rect around the current entity positions.

        Falls back to :attr:`DEFAULT_BOUNDS` when the scene is empty.
        Adds :attr:`AUTO_FIT_PADDING` × extent slack on each side so
        entities never sit right on the minimap edge.
        """
        positions: list[tuple[float, float]] = []
        for e in self._entities:
            p = _entity_position(e)
            if p is not None:
                positions.append(p)
        if not positions:
            return self.DEFAULT_BOUNDS
        xs = [p[0] for p in positions]
        ys = [p[1] for p in positions]
        min_x = min(xs)
        max_x = max(xs)
        min_y = min(ys)
        max_y = max(ys)
        w = max_x - min_x
        h = max_y - min_y
        if w <= 0.0:
            w = 20.0
            min_x -= 10.0
        if h <= 0.0:
            h = 20.0
            min_y -= 10.0
        pad_x = w * self.AUTO_FIT_PADDING
        pad_y = h * self.AUTO_FIT_PADDING
        return (min_x - pad_x, min_y - pad_y, w + 2 * pad_x, h + 2 * pad_y)

    # ==================================================================
    # Projection helpers
    # ==================================================================

    def _project_world_to_minimap(self, x: float, y: float) -> tuple[float, float]:
        """Map world ``(x, y)`` → minimap pixel ``(px, py)`` in [0, BODY].

        Honours ``self._view_offset`` (pan) and ``self._zoom`` so the
        round-trip with :meth:`_project_minimap_to_world` holds regardless
        of the view state.
        """
        bx, by, bw, bh = self._world_bounds
        ox, oy = self._view_offset
        # World → normalised [0, 1] against the bounds.
        # Apply pan by shifting the world coord *before* normalisation, and
        # zoom by re-centring around the bounds midpoint.
        cx = bx + bw * 0.5
        cy = by + bh * 0.5
        # Effective span shrinks with zoom (zoom > 1 → zoom in).
        eff_w = bw / self._zoom
        eff_h = bh / self._zoom
        # Shift the visible window centre by the pan offset.
        vis_x0 = cx - eff_w * 0.5 + ox
        vis_y0 = cy - eff_h * 0.5 + oy
        nx = (x - vis_x0) / eff_w
        ny = (y - vis_y0) / eff_h
        px = nx * self.BODY_WIDTH
        py = ny * self.BODY_HEIGHT
        return (px, py)

    def _project_minimap_to_world(
        self, px: float, py: float,
    ) -> tuple[float, float]:
        """Inverse of :meth:`_project_world_to_minimap`."""
        bx, by, bw, bh = self._world_bounds
        ox, oy = self._view_offset
        cx = bx + bw * 0.5
        cy = by + bh * 0.5
        eff_w = bw / self._zoom
        eff_h = bh / self._zoom
        vis_x0 = cx - eff_w * 0.5 + ox
        vis_y0 = cy - eff_h * 0.5 + oy
        nx = px / self.BODY_WIDTH
        ny = py / self.BODY_HEIGHT
        x = vis_x0 + nx * eff_w
        y = vis_y0 + ny * eff_h
        return (x, y)

    # ==================================================================
    # Interactions
    # ==================================================================

    def on_left_click(self, px: int, py: int) -> tuple[float, float] | None:
        """Left-click on the minimap → pan camera to world coord.

        Returns the world coordinate the click resolved to (so callers +
        tests can assert on it without going through the callback). When
        the click falls outside the drawlist body the call returns
        ``None`` and skips the callback.
        """
        if not self._point_in_body(px, py):
            return None
        wx, wy = self._project_minimap_to_world(float(px), float(py))
        if self._on_pan_request is not None:
            try:
                self._on_pan_request(wx, wy)
            except Exception:
                # A broken callback must not crash the panel.
                pass
        # Also drive the camera directly when it exposes a position slot,
        # so a shell that only wired `set_camera` still pans.
        cam = self._camera
        if cam is not None and hasattr(cam, "position"):
            try:
                cam.position = (wx, wy)
            except Exception:
                pass
        return (wx, wy)

    def begin_right_drag(self, px: int, py: int) -> None:
        """Record the anchor for a right-click drag (pans the minimap view)."""
        self._right_drag_anchor = (int(px), int(py))
        self._right_drag_start_offset = self._view_offset

    def on_right_drag(self, px: int, py: int) -> tuple[float, float]:
        """Update the view offset while the right-drag is in flight.

        Returns the new ``(ox, oy)`` offset in world units.
        """
        if self._right_drag_anchor is None:
            self.begin_right_drag(px, py)
        assert self._right_drag_anchor is not None  # for type checker
        ax, ay = self._right_drag_anchor
        dx_px = px - ax
        dy_px = py - ay
        bx, by, bw, bh = self._world_bounds
        # Convert pixel delta → world delta using the current visible span.
        eff_w = bw / self._zoom
        eff_h = bh / self._zoom
        dwx = -dx_px * (eff_w / self.BODY_WIDTH)
        dwy = -dy_px * (eff_h / self.BODY_HEIGHT)
        sx, sy = self._right_drag_start_offset
        self._view_offset = (sx + dwx, sy + dwy)
        return self._view_offset

    def end_right_drag(self) -> None:
        """Clear the right-drag anchor."""
        self._right_drag_anchor = None

    def on_scroll(self, notches: float) -> float:
        """Scroll-wheel zoom. Positive notches zoom in, negative out.

        Returns the new (clamped) zoom.
        """
        try:
            n = float(notches)
        except (TypeError, ValueError):
            raise TypeError(
                "NotebookMinimap.on_scroll: notches must be numeric; "
                f"got {type(notches).__name__}"
            )
        factor = self.ZOOM_STEP ** n
        new_zoom = self._zoom * factor
        # Clamp.
        new_zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, new_zoom))
        self._zoom = new_zoom
        return self._zoom

    def _point_in_body(self, px: int, py: int) -> bool:
        return 0 <= px <= self.BODY_WIDTH and 0 <= py <= self.BODY_HEIGHT

    # ==================================================================
    # Refresh + render
    # ==================================================================

    def refresh(self) -> None:
        """Re-compute bounds (if auto-fit) and repaint the drawlist."""
        # Re-scan entities from the scene each refresh so newly-added
        # ones show up without a fresh :meth:`set_scene` call.
        if self._scene is not None:
            self._entities = _iter_scene_entities(self._scene)
        if self._explicit_bounds is None:
            self._world_bounds = self._auto_fit_bounds()
        self._render()

    def _render(self) -> None:
        """Paint the current state onto the drawlist (headless-safe)."""
        self._frame_index += 1
        self.render_log = []
        self._render_background()
        self._render_grid()
        self._render_entities()
        self._render_viewport()

    # ------------------------------------------------------------------
    # Individual paint passes
    # ------------------------------------------------------------------

    def _render_background(self) -> None:
        """Draw the ruled-paper background."""
        dpg = _safe_dpg()
        paper = (250, 246, 235, 255)
        rule = (200, 200, 220, 200)
        self.render_log.append(("bg_rect", (0, 0, self.BODY_WIDTH, self.BODY_HEIGHT, paper)))
        # Horizontal ruled lines every 20 px — mimics diary paper.
        for py in range(20, self.BODY_HEIGHT, 20):
            self.render_log.append(("bg_rule", (0, py, self.BODY_WIDTH, py, rule)))
            if dpg is not None:
                try:
                    dpg.draw_line(
                        p1=[0, py], p2=[self.BODY_WIDTH, py],
                        color=list(rule), thickness=1.0,
                        parent=self._drawlist_tag,
                    )
                except Exception:
                    pass
        if dpg is not None:
            try:
                dpg.draw_rectangle(
                    pmin=[0, 0],
                    pmax=[self.BODY_WIDTH, self.BODY_HEIGHT],
                    color=list(paper),
                    fill=list(paper),
                    parent=self._drawlist_tag,
                )
            except Exception:
                pass

    def _render_grid(self) -> None:
        """Draw the world-space 10-unit grid overlay."""
        dpg = _safe_dpg()
        grid = (180, 180, 200, 120)
        bx, by, bw, bh = self._world_bounds
        step = self.GRID_STEP
        # First grid line ≥ bx that is a multiple of step.
        x0 = bx - (bx % step)
        y0 = by - (by % step)
        # Vertical grid lines (constant x).
        x = x0
        count = 0
        while x <= bx + bw + step and count < 512:
            p0 = self._project_world_to_minimap(x, by)
            p1 = self._project_world_to_minimap(x, by + bh)
            self.render_log.append(("grid_v", (p0, p1, grid)))
            if dpg is not None:
                try:
                    dpg.draw_line(
                        p1=[p0[0], p0[1]], p2=[p1[0], p1[1]],
                        color=list(grid), thickness=0.8,
                        parent=self._drawlist_tag,
                    )
                except Exception:
                    pass
            x += step
            count += 1
        # Horizontal grid lines (constant y).
        y = y0
        count = 0
        while y <= by + bh + step and count < 512:
            p0 = self._project_world_to_minimap(bx, y)
            p1 = self._project_world_to_minimap(bx + bw, y)
            self.render_log.append(("grid_h", (p0, p1, grid)))
            if dpg is not None:
                try:
                    dpg.draw_line(
                        p1=[p0[0], p0[1]], p2=[p1[0], p1[1]],
                        color=list(grid), thickness=0.8,
                        parent=self._drawlist_tag,
                    )
                except Exception:
                    pass
            y += step
            count += 1

    def _render_entities(self) -> None:
        """Draw each entity as a small colour-coded dot."""
        dpg = _safe_dpg()
        radius = 2.5
        for e in self._entities:
            pos = _entity_position(e)
            if pos is None:
                continue
            kind = classify_entity(e)
            color = _kind_color(kind)
            px, py = self._project_world_to_minimap(pos[0], pos[1])
            if not self._point_in_body(int(px), int(py)):
                # Still record for tests; skip the DPG draw so we don't
                # paint outside the body.
                self.render_log.append(("dot_offscreen", (px, py, kind, color)))
                continue
            self.render_log.append(("dot", (px, py, kind, color)))
            if dpg is not None:
                try:
                    dpg.draw_circle(
                        center=[px, py],
                        radius=radius,
                        color=list(color),
                        fill=list(color),
                        parent=self._drawlist_tag,
                    )
                except Exception:
                    pass

    def _render_viewport(self) -> None:
        """Draw the camera viewport as a hand-drawn (jittered) rectangle."""
        cam = self._camera
        if cam is None:
            return
        cam_pos = getattr(cam, "position", None)
        if not isinstance(cam_pos, (list, tuple)) or len(cam_pos) < 2:
            return
        try:
            cx = float(cam_pos[0])
            cy = float(cam_pos[1])
        except (TypeError, ValueError):
            return
        vp_size = getattr(cam, "_viewport_size", None)
        if not isinstance(vp_size, (list, tuple)) or len(vp_size) < 2:
            vp_size = (800, 600)
        try:
            vw = float(vp_size[0])
            vh = float(vp_size[1])
        except (TypeError, ValueError):
            vw, vh = 800.0, 600.0
        cam_zoom = getattr(cam, "zoom", 1.0)
        try:
            cam_zoom_f = float(cam_zoom)
            if cam_zoom_f <= 0.0:
                cam_zoom_f = 1.0
        except (TypeError, ValueError):
            cam_zoom_f = 1.0
        # World-space extent visible through the camera.
        half_w = 0.5 * vw / cam_zoom_f
        half_h = 0.5 * vh / cam_zoom_f
        tl_w = (cx - half_w, cy - half_h)
        tr_w = (cx + half_w, cy - half_h)
        br_w = (cx + half_w, cy + half_h)
        bl_w = (cx - half_w, cy + half_h)
        corners = [
            self._project_world_to_minimap(*tl_w),
            self._project_world_to_minimap(*tr_w),
            self._project_world_to_minimap(*br_w),
            self._project_world_to_minimap(*bl_w),
        ]
        # Apply deterministic ±1 px jitter per corner per frame.
        jittered: list[tuple[float, float]] = []
        for i, (px, py) in enumerate(corners):
            jx = _jitter(self._frame_index * 977 + i * 31, 1.0)
            jy = _jitter(self._frame_index * 977 + i * 31 + 17, 1.0)
            jittered.append((px + jx, py + jy))
        color = (60, 60, 90, 255)
        self.render_log.append(("viewport_rect", tuple(jittered)))
        dpg = _safe_dpg()
        if dpg is not None:
            edges = [
                (jittered[0], jittered[1]),
                (jittered[1], jittered[2]),
                (jittered[2], jittered[3]),
                (jittered[3], jittered[0]),
            ]
            for p0, p1 in edges:
                try:
                    dpg.draw_line(
                        p1=[p0[0], p0[1]], p2=[p1[0], p1[1]],
                        color=list(color), thickness=1.6,
                        parent=self._drawlist_tag,
                    )
                except Exception:
                    pass

    # ==================================================================
    # Build
    # ==================================================================

    def build(self, parent_tag: str | int) -> None:
        """Render the panel under *parent_tag* — headless-safe."""
        self._parent_tag = parent_tag
        self._built = True
        dpg = _safe_dpg()
        # Always run a paint pass so ``render_log`` reflects the built state.
        try:
            self._render()
        except Exception:
            pass
        if dpg is None:
            return

        try:
            with dpg.group(tag=self._root_tag, parent=parent_tag):
                try:
                    dpg.add_text(self.TITLE)
                except Exception:
                    pass
                try:
                    dpg.add_drawlist(
                        width=self.BODY_WIDTH,
                        height=self.BODY_HEIGHT,
                        tag=self._drawlist_tag,
                    )
                except Exception:
                    pass
                # Wire the mouse handlers to the drawlist.
                try:
                    with dpg.item_handler_registry(tag=f"{self._root_tag}_hnd"):
                        dpg.add_item_clicked_handler(callback=self._dpg_on_click)
                except Exception:
                    pass
                try:
                    dpg.bind_item_handler_registry(
                        self._drawlist_tag, f"{self._root_tag}_hnd",
                    )
                except Exception:
                    pass
                # Re-run the paint pass now that the drawlist tag exists.
                try:
                    self._render()
                except Exception:
                    pass
        except Exception:
            try:
                dpg.add_text(self.TITLE, parent=parent_tag)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # DPG mouse handler shims (kept tiny — real routing lives in the
    # public :meth:`on_left_click` / :meth:`on_right_drag` methods).
    # ------------------------------------------------------------------

    def _dpg_on_click(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Route DPG's ``item_clicked`` event to :meth:`on_left_click`."""
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            pos = dpg.get_mouse_pos(local=True)
            px = int(pos[0])
            py = int(pos[1])
        except Exception:
            return
        try:
            self.on_left_click(px, py)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Public helper aliases for tests + callers.
# ---------------------------------------------------------------------------


NotebookMinimap.classify_entity = staticmethod(classify_entity)  # type: ignore[assignment]
NotebookMinimap.ENTITY_KIND_COLORS = ENTITY_KIND_COLORS  # type: ignore[assignment]
