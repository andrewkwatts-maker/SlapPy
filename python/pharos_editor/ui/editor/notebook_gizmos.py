"""Hand-drawn coloured-pencil transform gizmo overlay.

A drop-in visual reskin of :class:`pharos_editor.ui.editor.gizmo_overlay.GizmoOverlay`
for the *notebook / doodle* theme family. Where the Nova3D overlay paints
crisp vector arrows, rings and squares straight onto a DPG viewport
drawlist, this module emits the same logical handles as **doodled
measurement marks in coloured pencil**:

* Translate — red and blue pencil strokes with mild wobble and small
  hand-drawn arrowheads; the centre handle is a tiny heart.
* Rotate — a dashed pencil ring in the active theme's accent colour
  with star-sparkle tick marks every 30° and a highlighter sweep from
  the centre to the current angle.
* Scale — four corner *bow-tie* brackets matching the toolbar Scale icon
  and a heart pulse at the centre while actively dragging.

Per the U6 audit (``docs/ui_pattern_audit_2026_06_03.md`` §6.1) this is
the "coloured pencil overlay layer" translation of the Nova3D gizmo
contract: 2D handles drawn into a viewport draw list with pixel-space
hit-testing. The class deliberately mirrors the public surface of
:class:`GizmoOverlay` (``render`` / ``hit_test`` / ``set_*``) so a host
shell can swap implementations by name without touching call sites.

The renderer is *draw-list agnostic*: any object exposing
``add_line``, ``add_circle``, ``add_polyline``, ``add_text``,
``add_triangle`` and ``add_quad`` works. The tests drive the class with
a recording :class:`_MockDrawList` instead of Dear PyGui so the contract
runs headless on every CI box.

Wobble is **deterministic** — the perlin-ish offset for a stroke is
hashed from ``(target_pos, mode, axis_index)`` so the same logical
gizmo at the same world position always doodles the same way, which is
what the tests pin.
"""
from __future__ import annotations

import math
from typing import Any, Protocol

from pharos_engine._validation import validate_str


# ---------------------------------------------------------------------------
# Draw-list protocol — narrow enough that DPG, PIL and our mock all fit.
# ---------------------------------------------------------------------------


class DrawListLike(Protocol):
    """Subset of the DPG drawlist API the overlay actually uses."""

    def add_line(self, p1: tuple[float, float], p2: tuple[float, float],
                 color: tuple[int, int, int, int], thickness: float) -> None: ...

    def add_circle(self, center: tuple[float, float], radius: float,
                   color: tuple[int, int, int, int],
                   thickness: float, fill: tuple[int, int, int, int] | None) -> None: ...

    def add_polyline(self, points: list[tuple[float, float]],
                     color: tuple[int, int, int, int], thickness: float) -> None: ...

    def add_triangle(self, p1: tuple[float, float], p2: tuple[float, float],
                     p3: tuple[float, float], color: tuple[int, int, int, int],
                     fill: tuple[int, int, int, int] | None) -> None: ...

    def add_text(self, pos: tuple[float, float], text: str,
                 color: tuple[int, int, int, int]) -> None: ...

    def add_quad(self, p1: tuple[float, float], p2: tuple[float, float],
                 p3: tuple[float, float], p4: tuple[float, float],
                 color: tuple[int, int, int, int],
                 fill: tuple[int, int, int, int] | None) -> None: ...


# ---------------------------------------------------------------------------
# Pencil colours — palette lookup with sane fallbacks.
# ---------------------------------------------------------------------------


_VALID_MODES: tuple[str, ...] = ("translate", "rotate", "scale")

# Fallback colours used when no theme is active or when the active theme
# does not carry the expected token. Tuned to read on cream paper.
_FALLBACK_PENCIL_RED = (210, 75, 90, 235)
_FALLBACK_PENCIL_BLUE = (60, 100, 200, 235)
_FALLBACK_PENCIL_GREEN = (70, 165, 110, 235)
_FALLBACK_ACCENT = (255, 200, 80, 220)
_FALLBACK_HIGHLIGHTER = (255, 230, 90, 160)
_FALLBACK_PAPER_DARK = (60, 50, 80, 200)


def _color_to_rgba(value: Any, fallback: tuple[int, int, int, int]
                   ) -> tuple[int, int, int, int]:
    """Resolve a theme value (Color or RGBA tuple) to an RGBA int tuple."""
    if value is None:
        return fallback
    # theme_spec.Color has as_rgba_tuple()
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


def _resolve_pencil_color(theme: Any, palette_key: str, semantic_attr: str,
                          fallback: tuple[int, int, int, int]
                          ) -> tuple[int, int, int, int]:
    """Look up ``palette[palette_key]`` then ``semantic.semantic_attr``.

    Returns *fallback* if both lookups fail or no theme is active.
    """
    if theme is None:
        return fallback
    pal = getattr(theme, "palette", None)
    if pal is not None:
        entry = None
        # Palette may be either a plain dict[str, Color] or a Palette object
        # exposing .entries.
        if isinstance(pal, dict):
            entry = pal.get(palette_key)
        else:
            entries = getattr(pal, "entries", None)
            if isinstance(entries, dict):
                entry = entries.get(palette_key)
        if entry is not None:
            return _color_to_rgba(entry, fallback)
    sem = getattr(theme, "semantic", None)
    if sem is not None:
        attr = getattr(sem, semantic_attr, None)
        if attr is not None:
            return _color_to_rgba(attr, fallback)
    return fallback


def _shade(rgba: tuple[int, int, int, int], factor: float
           ) -> tuple[int, int, int, int]:
    """Multiply RGB channels by *factor* (clamped to [0, 255])."""
    r = max(0, min(255, int(rgba[0] * factor)))
    g = max(0, min(255, int(rgba[1] * factor)))
    b = max(0, min(255, int(rgba[2] * factor)))
    return (r, g, b, rgba[3])


# ---------------------------------------------------------------------------
# Deterministic wobble — value-noise from a stable hash so the same
# (target_pos, mode, axis) always doodles the same way.
# ---------------------------------------------------------------------------


def _stable_hash(*parts: Any) -> int:
    """A small, deterministic hash usable as a PRNG seed.

    Python's built-in ``hash`` is salted per-interpreter; we want
    repeatable wobble across processes so we roll a tiny FNV-1a over
    the string repr.
    """
    s = "|".join(repr(p) for p in parts)
    h = 2166136261
    for ch in s.encode("utf-8"):
        h ^= ch
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def _wobble_samples(seed: int, count: int, amplitude: float) -> list[float]:
    """Generate *count* smoothed wobble offsets in ``[-amplitude, amplitude]``.

    Uses a stable LCG seeded by *seed* and a 3-tap moving average so the
    output reads as hand-drawn jitter rather than salt-and-pepper noise.
    """
    if count <= 0:
        return []
    state = seed | 1  # keep odd so LCG never collapses to zero
    raw = []
    for _ in range(count + 2):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        # Normalise to roughly [-1, 1].
        raw.append((state / 0x3FFFFFFF) - 1.0)
    smoothed = []
    for i in range(count):
        v = (raw[i] + raw[i + 1] + raw[i + 2]) / 3.0
        smoothed.append(v * amplitude)
    return smoothed


# ---------------------------------------------------------------------------
# Coloured-pencil stroke renderer.
# ---------------------------------------------------------------------------


def _draw_pencil_stroke(
    draw_list: DrawListLike,
    start: tuple[float, float],
    end: tuple[float, float],
    color: tuple[int, int, int, int],
    *,
    thickness: float = 4.0,
    seed: int = 0,
    wobble_px: float = 1.6,
    chalk_overlay: bool = True,
) -> list[tuple[float, float]]:
    """Render a hand-drawn pencil line as a wobbled polyline.

    The stroke is sampled along *start* → *end* with a per-sample
    perpendicular offset drawn from :func:`_wobble_samples`. A second,
    lighter overlay polyline is drawn slightly offset to mimic the soft
    chalk grain of a coloured pencil. Returns the wobbled point list so
    callers can attach arrowheads / endpoint glyphs at the final point.
    """
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 1e-3:
        return [start, end]
    ux, uy = dx / length, dy / length
    # Perpendicular for the wobble offset.
    px, py = -uy, ux

    # Sample density — roughly one segment per 6 px of stroke length, with
    # a hard floor so very short handles still get a couple of waves.
    samples = max(6, int(length / 6.0))
    wobble = _wobble_samples(seed, samples + 1, wobble_px)
    points: list[tuple[float, float]] = []
    for i in range(samples + 1):
        t = i / samples
        x = start[0] + dx * t + px * wobble[i]
        y = start[1] + dy * t + py * wobble[i]
        points.append((x, y))

    draw_list.add_polyline(points, color=color, thickness=thickness)

    if chalk_overlay:
        # Pencil pressure variation: a lighter, slightly offset overlay
        # gives the stroke a soft chalk grain without needing a texture.
        chalk_color = _shade(color, 1.18)
        chalk_color = (chalk_color[0], chalk_color[1], chalk_color[2],
                       max(40, color[3] - 90))
        chalk_points = [
            (x + px * 0.6, y + py * 0.6) for (x, y) in points
        ]
        draw_list.add_polyline(
            chalk_points, color=chalk_color, thickness=max(1.0, thickness * 0.55)
        )
    return points


def _draw_doodle_arrowhead(
    draw_list: DrawListLike,
    tip: tuple[float, float],
    direction: tuple[float, float],
    color: tuple[int, int, int, int],
    size: float = 10.0,
) -> None:
    """Doodled arrowhead — small filled triangle plus two angled tick lines."""
    dx, dy = direction
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    base_x = tip[0] - ux * size
    base_y = tip[1] - uy * size
    left = (base_x + px * size * 0.55, base_y + py * size * 0.55)
    right = (base_x - px * size * 0.55, base_y - py * size * 0.55)
    draw_list.add_triangle(tip, left, right, color=color, fill=color)
    # Two doodle angled lines: a child's "double-flick" arrowhead.
    flick_back_x = tip[0] - ux * size * 1.5
    flick_back_y = tip[1] - uy * size * 1.5
    draw_list.add_line(
        tip, (flick_back_x + px * size * 0.4, flick_back_y + py * size * 0.4),
        color=color, thickness=1.5,
    )
    draw_list.add_line(
        tip, (flick_back_x - px * size * 0.4, flick_back_y - py * size * 0.4),
        color=color, thickness=1.5,
    )


def _draw_heart(
    draw_list: DrawListLike,
    center: tuple[float, float],
    size: float,
    color: tuple[int, int, int, int],
) -> None:
    """Small filled heart shape — two lobes + a bottom triangle."""
    cx, cy = center
    lobe_r = size * 0.35
    left_lobe = (cx - lobe_r, cy - lobe_r * 0.4)
    right_lobe = (cx + lobe_r, cy - lobe_r * 0.4)
    draw_list.add_circle(left_lobe, lobe_r, color=color,
                         thickness=1.0, fill=color)
    draw_list.add_circle(right_lobe, lobe_r, color=color,
                         thickness=1.0, fill=color)
    tip = (cx, cy + size * 0.6)
    base_left = (cx - lobe_r * 1.35, cy)
    base_right = (cx + lobe_r * 1.35, cy)
    draw_list.add_triangle(base_left, base_right, tip,
                           color=color, fill=color)


def _draw_star_sparkle(
    draw_list: DrawListLike,
    center: tuple[float, float],
    size: float,
    color: tuple[int, int, int, int],
) -> None:
    """Four-point star tick mark — two crossed lines."""
    cx, cy = center
    draw_list.add_line(
        (cx - size, cy), (cx + size, cy), color=color, thickness=1.5
    )
    draw_list.add_line(
        (cx, cy - size), (cx, cy + size), color=color, thickness=1.5
    )
    # Mini diagonal accents for a sparkle feel.
    d = size * 0.55
    draw_list.add_line(
        (cx - d, cy - d), (cx + d, cy + d), color=color, thickness=1.0
    )


def _draw_bowtie_bracket(
    draw_list: DrawListLike,
    corner: tuple[float, float],
    inward: tuple[float, float],
    size: float,
    color: tuple[int, int, int, int],
) -> None:
    """Bow-tie corner bracket — two crossed triangles pointing inward.

    *corner* is the outer point of the bracket and *inward* is the unit
    vector pointing toward the gizmo centre. The two triangles meet at
    the corner so the bracket reads as a tied ribbon.
    """
    ix, iy = inward
    px, py = -iy, ix
    cx, cy = corner
    # Outer triangle (small, sits at the corner).
    outer_a = (cx + px * size * 0.55, cy + py * size * 0.55)
    outer_b = (cx - px * size * 0.55, cy - py * size * 0.55)
    draw_list.add_triangle(corner, outer_a, outer_b,
                           color=color, fill=color)
    # Inner triangle pointing along *inward*.
    inner_tip = (cx + ix * size * 1.5, cy + iy * size * 1.5)
    inner_a = (cx + ix * size * 0.4 + px * size * 0.7,
               cy + iy * size * 0.4 + py * size * 0.7)
    inner_b = (cx + ix * size * 0.4 - px * size * 0.7,
               cy + iy * size * 0.4 - py * size * 0.7)
    draw_list.add_triangle(inner_tip, inner_a, inner_b,
                           color=color, fill=color)


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class NotebookGizmoOverlay:
    """Gizmo overlay rendered as hand-drawn pencil sketches.

    Per Nova3D's gizmo contract: 2D translate / rotate / scale handles
    drawn into the viewport draw list with pixel-position hit-testing.

    Visual override: lines have slight wobble (perlin-style offset),
    colours come from the active theme's semantic tokens, and the
    pencil texture is faked with a chalk-grain overlay polyline.

    Parameters
    ----------
    arrow_length, rotate_radius, scale_extent:
        Pixel sizes of the three handle classes. Defaults match the
        Nova3D :class:`GizmoOverlay` constants so a host shell can swap
        the implementations without re-laying-out the viewport.
    """

    HANDLE_RADIUS: int = 9
    ARROW_LEN: int = 50
    ROTATE_RADIUS: int = 45
    SCALE_HANDLE_SIZE: int = 12
    ROTATE_DASH_COUNT: int = 10
    ROTATE_TICK_STEP_DEG: int = 30

    def __init__(
        self,
        *,
        arrow_length: int = ARROW_LEN,
        rotate_radius: int = ROTATE_RADIUS,
        scale_extent: int = SCALE_HANDLE_SIZE,
    ) -> None:
        self._arrow_len = int(arrow_length)
        self._rotate_r = int(rotate_radius)
        self._scale_h = int(scale_extent)

        # Frame state — set in :meth:`render`, queried by :meth:`hit_test`.
        self._last_target: tuple[float, float] | None = None
        self._last_mode: str | None = None
        self._hover_key: str | None = None
        self._active_key: str | None = None
        self._theme_override: Any | None = None
        self._frame_index: int = 0
        # Compat with the legacy GizmoOverlay surface that Engine.run_editor()
        # calls during boot: it sets the camera / entity / tool / mode before
        # the first render. These attributes are stash-only — the notebook
        # render contract is target_world_pos + mode passed directly.
        self._entity: Any | None = None
        self._camera: Any | None = None
        self._tool: str = "select"
        self._mode_3d: bool = False

    # ------------------------------------------------------------------
    # State setters
    # ------------------------------------------------------------------

    def set_entity(self, entity: Any) -> None:
        """Bind the gizmo to *entity*. Pass ``None`` to deselect.

        Compat shim for the legacy `GizmoOverlay.set_entity` contract that
        `Engine.run_editor()` calls during boot. The notebook overlay tracks
        its target via `render(target_world_pos, ...)`; this setter just
        stashes the entity so callers can query `.entity` later.
        """
        self._entity = entity

    def set_camera(self, camera: Any) -> None:
        """Bind the camera used for world-to-screen conversion.

        Compat shim for the legacy `GizmoOverlay.set_camera` contract.
        """
        self._camera = camera

    def set_tool(self, tool: str) -> None:
        """Set the active tool mode: 'select', 'translate', 'rotate', or 'scale'.

        Compat shim for the legacy `GizmoOverlay.set_tool` contract.
        """
        self._tool = tool

    def set_mode(self, mode: str) -> None:
        """Switch between 2D and 3D gizmo rendering.

        Compat shim for the legacy `GizmoOverlay.set_mode` contract. The
        notebook overlay is 2D-only today; 3D mode is recorded but ignored.
        """
        self._mode_3d = (mode == "3D")

    def set_hover(self, key: str | None) -> None:
        """Mark *key* as hovered so the next render grows + shimmers it."""
        self._hover_key = key

    def set_active(self, key: str | None) -> None:
        """Mark *key* as actively dragged — the highlighter underline fires."""
        self._active_key = key

    def set_theme(self, theme: Any) -> None:
        """Override the active theme used for pencil colours.

        Pass ``None`` to fall back to :func:`get_active_theme`.
        """
        self._theme_override = theme

    def advance_frame(self) -> None:
        """Tick the internal frame index used by the heart-pulse animation."""
        self._frame_index += 1

    def update(self) -> None:
        """Per-frame update hook called by `Engine.run_editor()`.

        Compat shim for the legacy `GizmoOverlay.update()` contract. The
        notebook overlay's rendering happens through explicit `render()`
        calls driven by the editor draw loop, so this method just advances
        the heart-pulse frame counter. Safe to call without DPG context.
        """
        self.advance_frame()

    # ------------------------------------------------------------------
    # Theme resolution
    # ------------------------------------------------------------------

    def _theme(self) -> Any:
        if self._theme_override is not None:
            return self._theme_override
        try:
            from pharos_editor.ui.theme import get_active_theme  # local import
            return get_active_theme()
        except Exception:
            return None

    def _pencil_red(self) -> tuple[int, int, int, int]:
        return _resolve_pencil_color(
            self._theme(), "pencil_red", "error", _FALLBACK_PENCIL_RED
        )

    def _pencil_blue(self) -> tuple[int, int, int, int]:
        return _resolve_pencil_color(
            self._theme(), "pencil_blue", "info", _FALLBACK_PENCIL_BLUE
        )

    def _pencil_green(self) -> tuple[int, int, int, int]:
        return _resolve_pencil_color(
            self._theme(), "pencil_green", "success", _FALLBACK_PENCIL_GREEN
        )

    def _accent_color(self) -> tuple[int, int, int, int]:
        return _resolve_pencil_color(
            self._theme(), "accent", "accent", _FALLBACK_ACCENT
        )

    def _highlighter_color(self) -> tuple[int, int, int, int]:
        return _resolve_pencil_color(
            self._theme(), "highlighter_yellow", "warning",
            _FALLBACK_HIGHLIGHTER,
        )

    def _ink_color(self) -> tuple[int, int, int, int]:
        return _resolve_pencil_color(
            self._theme(), "ink_navy", "text_primary", _FALLBACK_PAPER_DARK
        )

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(
        self,
        draw_list: DrawListLike,
        target_world_pos: tuple[float, float],
        mode: str,
    ) -> None:
        """Paint the gizmo for *mode* centred on *target_world_pos*.

        The draw_list is treated as the viewport draw list; coordinates
        are pixel-space so callers are expected to have already done the
        world→screen transform.
        """
        validate_str("mode", "NotebookGizmoOverlay.render", mode)
        if mode not in _VALID_MODES:
            raise ValueError(
                f"NotebookGizmoOverlay.render: mode must be one of "
                f"{_VALID_MODES!r}; got {mode!r}"
            )
        if (
            not isinstance(target_world_pos, (list, tuple))
            or len(target_world_pos) < 2
        ):
            raise TypeError(
                "NotebookGizmoOverlay.render: target_world_pos must be a "
                "2-tuple of floats"
            )
        tx = float(target_world_pos[0])
        ty = float(target_world_pos[1])
        self._last_target = (tx, ty)
        self._last_mode = mode

        if mode == "translate":
            self._render_translate(draw_list, tx, ty)
        elif mode == "rotate":
            self._render_rotate(draw_list, tx, ty)
        elif mode == "scale":
            self._render_scale(draw_list, tx, ty)

    # --- translate -----------------------------------------------------

    def _render_translate(
        self, draw_list: DrawListLike, cx: float, cy: float
    ) -> None:
        target = (cx, cy)
        x_tip = (cx + self._arrow_len, cy)
        y_tip = (cx, cy - self._arrow_len)
        red = self._pencil_red()
        blue = self._pencil_blue()
        ink = self._ink_color()

        x_grow = 1.15 if self._hover_key == "x_axis" else 1.0
        y_grow = 1.15 if self._hover_key == "y_axis" else 1.0

        # X axis — red pencil, doodled arrowhead.
        x_seed = _stable_hash(self._last_target, "translate", 0)
        _draw_pencil_stroke(
            draw_list, target,
            (cx + self._arrow_len * x_grow, cy),
            red, thickness=4.5 * x_grow, seed=x_seed,
        )
        _draw_doodle_arrowhead(
            draw_list, (cx + self._arrow_len * x_grow, cy),
            (1.0, 0.0), red, size=10.0 * x_grow,
        )
        # Heart endpoint dot.
        _draw_heart(draw_list, (cx + self._arrow_len * x_grow, cy),
                    size=self.HANDLE_RADIUS * 0.85 * x_grow, color=red)

        # Y axis — blue pencil.
        y_seed = _stable_hash(self._last_target, "translate", 1)
        _draw_pencil_stroke(
            draw_list, target,
            (cx, cy - self._arrow_len * y_grow),
            blue, thickness=4.5 * y_grow, seed=y_seed,
        )
        _draw_doodle_arrowhead(
            draw_list, (cx, cy - self._arrow_len * y_grow),
            (0.0, -1.0), blue, size=10.0 * y_grow,
        )
        _draw_heart(draw_list, (cx, cy - self._arrow_len * y_grow),
                    size=self.HANDLE_RADIUS * 0.85 * y_grow, color=blue)

        # Centre handle — small ink heart for free-move.
        _draw_heart(draw_list, target,
                    size=self.HANDLE_RADIUS * 0.95, color=ink)

        self._maybe_emit_hover_shimmer(draw_list, target, x_tip, y_tip)
        self._maybe_emit_active_underline(draw_list, target, x_tip, y_tip)

    # --- rotate --------------------------------------------------------

    def _render_rotate(
        self, draw_list: DrawListLike, cx: float, cy: float
    ) -> None:
        accent = self._accent_color()
        ink = self._ink_color()
        r = float(self._rotate_r)

        # Dashed pencil ring — 10 dash segments.
        dash_count = self.ROTATE_DASH_COUNT
        seed = _stable_hash(self._last_target, "rotate", "ring")
        for i in range(dash_count):
            a0 = (2 * math.pi) * (i / dash_count)
            a1 = a0 + (2 * math.pi) / (dash_count * 2)
            seg_start = (cx + math.cos(a0) * r, cy + math.sin(a0) * r)
            seg_end = (cx + math.cos(a1) * r, cy + math.sin(a1) * r)
            _draw_pencil_stroke(
                draw_list, seg_start, seg_end,
                accent, thickness=3.0,
                seed=seed + i, wobble_px=1.0,
                chalk_overlay=False,
            )

        # Tick marks every 30°.
        tick_step = self.ROTATE_TICK_STEP_DEG
        for deg in range(0, 360, tick_step):
            rad = math.radians(deg)
            tick_x = cx + math.cos(rad) * (r + 4.0)
            tick_y = cy + math.sin(rad) * (r + 4.0)
            _draw_star_sparkle(draw_list, (tick_x, tick_y), 3.5, ink)

        # Highlighter sweep from centre to handle dot (top of ring).
        handle = (cx, cy - r)
        if self._active_key == "rotate_handle":
            draw_list.add_line(
                (cx, cy), handle,
                color=self._highlighter_color(),
                thickness=10.0,
            )

        # Handle dot.
        grow = 1.15 if self._hover_key == "rotate_handle" else 1.0
        _draw_heart(draw_list, handle,
                    size=self.HANDLE_RADIUS * grow, color=accent)

        self._maybe_emit_hover_shimmer(draw_list, (cx, cy), handle, handle)

    # --- scale ---------------------------------------------------------

    def _render_scale(
        self, draw_list: DrawListLike, cx: float, cy: float
    ) -> None:
        red = self._pencil_red()
        ink = self._ink_color()
        h = float(self._scale_h) * 1.6
        size = float(self._scale_h)
        corners = {
            "scale_tl": (cx - h, cy - h),
            "scale_tr": (cx + h, cy - h),
            "scale_bl": (cx - h, cy + h),
            "scale_br": (cx + h, cy + h),
        }
        inward = {
            "scale_tl": (1.0, 1.0),
            "scale_tr": (-1.0, 1.0),
            "scale_bl": (1.0, -1.0),
            "scale_br": (-1.0, -1.0),
        }
        for key, corner in corners.items():
            ix, iy = inward[key]
            inv_len = 1.0 / math.sqrt(ix * ix + iy * iy)
            unit = (ix * inv_len, iy * inv_len)
            grow = 1.15 if self._hover_key == key else 1.0
            _draw_bowtie_bracket(
                draw_list, corner, unit, size * grow, red
            )

        # Pencil "guide" stroke around the box outline so the corners
        # read as a unit even when no individual bracket is hovered.
        outline_seed = _stable_hash(self._last_target, "scale", "outline")
        _draw_pencil_stroke(
            draw_list, corners["scale_tl"], corners["scale_tr"],
            ink, thickness=2.0, seed=outline_seed, wobble_px=1.0,
        )
        _draw_pencil_stroke(
            draw_list, corners["scale_tr"], corners["scale_br"],
            ink, thickness=2.0, seed=outline_seed + 1, wobble_px=1.0,
        )
        _draw_pencil_stroke(
            draw_list, corners["scale_br"], corners["scale_bl"],
            ink, thickness=2.0, seed=outline_seed + 2, wobble_px=1.0,
        )
        _draw_pencil_stroke(
            draw_list, corners["scale_bl"], corners["scale_tl"],
            ink, thickness=2.0, seed=outline_seed + 3, wobble_px=1.0,
        )

        # Heart pulse at the centre — radius oscillates with the frame
        # index so callers that tick :meth:`advance_frame` get an
        # animated pulse while actively scaling.
        pulse = 1.0
        if self._active_key and self._active_key.startswith("scale_"):
            pulse = 1.0 + 0.18 * math.sin(self._frame_index * 0.35)
        _draw_heart(draw_list, (cx, cy),
                    size=self.HANDLE_RADIUS * pulse, color=red)

    # --- shared effects -----------------------------------------------

    def _maybe_emit_hover_shimmer(
        self,
        draw_list: DrawListLike,
        center: tuple[float, float],
        x_tip: tuple[float, float],
        y_tip: tuple[float, float],
    ) -> None:
        """Light shimmer ring at the hovered handle."""
        if self._hover_key is None:
            return
        targets = {
            "x_axis": x_tip,
            "y_axis": y_tip,
            "rotate_handle": y_tip,
            "scale_tl": center,
            "scale_tr": center,
            "scale_bl": center,
            "scale_br": center,
        }
        pos = targets.get(self._hover_key, center)
        shimmer_color = (255, 255, 220, 90)
        draw_list.add_circle(
            pos, self.HANDLE_RADIUS * 1.6,
            color=shimmer_color, thickness=1.0, fill=None,
        )

    def _maybe_emit_active_underline(
        self,
        draw_list: DrawListLike,
        center: tuple[float, float],
        x_tip: tuple[float, float],
        y_tip: tuple[float, float],
    ) -> None:
        """Highlighter underline beneath the currently-dragged handle."""
        if self._active_key is None:
            return
        targets = {
            "x_axis": x_tip,
            "y_axis": y_tip,
            "xy_center": center,
        }
        pos = targets.get(self._active_key)
        if pos is None:
            return
        highlighter = self._highlighter_color()
        draw_list.add_line(
            (pos[0] - 14.0, pos[1] + self.HANDLE_RADIUS + 2.0),
            (pos[0] + 14.0, pos[1] + self.HANDLE_RADIUS + 2.0),
            color=highlighter, thickness=6.0,
        )

    # ------------------------------------------------------------------
    # Hit testing
    # ------------------------------------------------------------------

    def hit_test(self, mouse_pos: tuple[int, int]) -> str | None:
        """Return the handle key the mouse is over, or ``None``.

        The result is computed against the last :meth:`render` call.
        Calling ``hit_test`` before any ``render`` returns ``None``.

        Returned keys
        -------------
        translate
            ``"x_axis"`` / ``"y_axis"`` / ``"xy_center"``
        rotate
            ``"rotate_handle"`` / ``"rotate_ring"``
        scale
            ``"scale_tl"`` / ``"scale_tr"`` / ``"scale_bl"`` / ``"scale_br"``
            / ``"scale_center"``
        """
        if self._last_target is None or self._last_mode is None:
            return None
        if (
            not isinstance(mouse_pos, (list, tuple))
            or len(mouse_pos) < 2
        ):
            return None
        mx = float(mouse_pos[0])
        my = float(mouse_pos[1])
        cx, cy = self._last_target
        r = float(self.HANDLE_RADIUS) + 3.0

        if self._last_mode == "translate":
            x_tip = (cx + self._arrow_len, cy)
            y_tip = (cx, cy - self._arrow_len)
            if math.hypot(mx - x_tip[0], my - x_tip[1]) <= r:
                return "x_axis"
            if math.hypot(mx - y_tip[0], my - y_tip[1]) <= r:
                return "y_axis"
            if math.hypot(mx - cx, my - cy) <= r:
                return "xy_center"
            return None

        if self._last_mode == "rotate":
            handle = (cx, cy - self._rotate_r)
            if math.hypot(mx - handle[0], my - handle[1]) <= r:
                return "rotate_handle"
            # Ring band — within a few pixels of the ring radius counts.
            d = math.hypot(mx - cx, my - cy)
            if abs(d - self._rotate_r) <= 5.0:
                return "rotate_ring"
            return None

        if self._last_mode == "scale":
            h = float(self._scale_h) * 1.6
            corners = {
                "scale_tl": (cx - h, cy - h),
                "scale_tr": (cx + h, cy - h),
                "scale_bl": (cx - h, cy + h),
                "scale_br": (cx + h, cy + h),
            }
            for key, (hx, hy) in corners.items():
                if math.hypot(mx - hx, my - hy) <= float(self._scale_h):
                    return key
            if math.hypot(mx - cx, my - cy) <= r:
                return "scale_center"
            return None
        return None


__all__ = [
    "NotebookGizmoOverlay",
    "DrawListLike",
]
