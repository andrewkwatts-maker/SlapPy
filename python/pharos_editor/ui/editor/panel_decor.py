"""``PanelDecor`` — hand-drawn dividers + washi-tape corner stickers.

The diary editor draws two families of theme-driven ornamentation on top
of ordinary Dear PyGui panels:

* **Hand-drawn dividers** between nested panels — sinuous wavy rules,
  dot chains, dashed rules, doodled star / heart / flower chains, and a
  slightly-wobbly pencil line. Each divider is drawn on the parent
  panel's own drawlist as a *procedural* pattern so no texture asset is
  required.
* **Washi-tape corner stickers** on floating (dragged-out / non-docked)
  windows — small pastel-coloured rectangles rotated a few degrees off
  axis, with a torn-paper edge, a soft drop shadow, and per-theme
  colour choice (:class:`WashiCornerStyle`).

Both families read their defaults from
:class:`pharos_editor.ui.theme.PanelDecorConfig`, so switching theme
swaps the ornament palette automatically.

The module is pure procedural math + drawlist calls; it has no GUI of
its own, holds no DPG state, and is fully headless-safe (every
drawlist call is wrapped in ``try/except`` so the same code path
drives the CI stub and the shipping viewport).

Public surface
--------------

.. code-block:: python

    from pharos_editor.ui.editor.panel_decor import (
        DividerSpec, DividerStyle, PanelDecor,
        WashiCornerSpec, WashiCornerStyle,
        collect_divider_edges, corner_specs_for_floating,
    )

The :class:`PanelDecor` renderer takes a *theme_getter* callable so the
tests can drive it without touching the global theme registry.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Sequence

from pharos_engine._validation import (
    validate_non_empty_str,
    validate_positive_int,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DividerStyle(Enum):
    """Hand-drawn divider styles."""

    WAVY = "wavy"
    DOTTED = "dotted"
    DASHED = "dashed"
    STAR_CHAIN = "star_chain"
    HEART_CHAIN = "heart_chain"
    FLOWER_CHAIN = "flower_chain"
    PENCIL_LINE = "pencil_line"

    @classmethod
    def from_str(cls, value: str) -> "DividerStyle":
        """Coerce a string (theme config or user input) into an enum."""
        if isinstance(value, cls):
            return value
        if not isinstance(value, str) or not value:
            raise ValueError(
                f"DividerStyle.from_str: value must be a non-empty str; "
                f"got {value!r}"
            )
        for member in cls:
            if member.value == value:
                return member
        raise ValueError(
            f"DividerStyle.from_str: unknown style {value!r}; "
            f"known: {[m.value for m in cls]}"
        )


class WashiCornerStyle(Enum):
    """Washi-tape colour palettes for corner stickers."""

    TAPE_PINK = "tape_pink"
    TAPE_BLUE = "tape_blue"
    TAPE_YELLOW = "tape_yellow"
    TAPE_MINT = "tape_mint"
    TAPE_LAVENDER = "tape_lavender"

    @classmethod
    def from_str(cls, value: str) -> "WashiCornerStyle":
        """Coerce a string into an enum member."""
        if isinstance(value, cls):
            return value
        if not isinstance(value, str) or not value:
            raise ValueError(
                f"WashiCornerStyle.from_str: value must be a non-empty str; "
                f"got {value!r}"
            )
        for member in cls:
            if member.value == value:
                return member
        raise ValueError(
            f"WashiCornerStyle.from_str: unknown style {value!r}; "
            f"known: {[m.value for m in cls]}"
        )


# ---------------------------------------------------------------------------
# Style palette
# ---------------------------------------------------------------------------


# Pastel pigments per washi style. Values are 0–255 sRGB with a slight
# translucency so the tape reads like paper against a coloured surface.
_WASHI_PIGMENTS: dict[WashiCornerStyle, tuple[int, int, int, int]] = {
    WashiCornerStyle.TAPE_PINK:     (255, 181, 197, 220),  # #FFB5C5
    WashiCornerStyle.TAPE_BLUE:     (181, 214, 255, 220),  # #B5D6FF
    WashiCornerStyle.TAPE_YELLOW:   (255, 240, 178, 220),  # #FFF0B2
    WashiCornerStyle.TAPE_MINT:     (185, 232, 205, 220),  # #B9E8CD
    WashiCornerStyle.TAPE_LAVENDER: (214, 199, 255, 220),  # #D6C7FF
}


def washi_pigment(style: WashiCornerStyle) -> tuple[int, int, int, int]:
    """Return the ``(r, g, b, a)`` pigment used by *style*.

    Exposed for tests and for adjacent code that wants to render a
    matching secondary sticker without going through :class:`PanelDecor`.
    """
    if not isinstance(style, WashiCornerStyle):
        raise TypeError(
            f"washi_pigment: style must be a WashiCornerStyle; "
            f"got {type(style).__name__}"
        )
    return _WASHI_PIGMENTS[style]


# ---------------------------------------------------------------------------
# Specs
# ---------------------------------------------------------------------------


@dataclass
class DividerSpec:
    """Rendering spec for a single divider stroke.

    Parameters
    ----------
    orientation:
        ``"horizontal"`` or ``"vertical"``.
    style:
        Hand-drawn pattern to trace.
    thickness_px:
        Stroke thickness in pixels. Must be a positive integer.
    color:
        Optional explicit ``(r, g, b, a)`` override. When ``None`` the
        renderer pulls the theme accent colour.
    """

    orientation: str
    style: DividerStyle
    thickness_px: int = 2
    color: tuple[int, int, int, int] | None = None

    def __post_init__(self) -> None:
        fn = "DividerSpec"
        orient = validate_non_empty_str("orientation", fn, self.orientation)
        if orient not in ("horizontal", "vertical"):
            raise ValueError(
                f"{fn}: orientation must be 'horizontal' or 'vertical'; "
                f"got {orient!r}"
            )
        self.orientation = orient
        if not isinstance(self.style, DividerStyle):
            raise TypeError(
                f"{fn}: style must be a DividerStyle; "
                f"got {type(self.style).__name__}"
            )
        self.thickness_px = validate_positive_int(
            "thickness_px", fn, self.thickness_px,
        )
        if self.color is not None:
            if (
                not isinstance(self.color, tuple)
                or len(self.color) != 4
                or not all(isinstance(c, int) for c in self.color)
                or any(c < 0 or c > 255 for c in self.color)
            ):
                raise TypeError(
                    f"{fn}: color must be a 4-tuple of ints in [0, 255] "
                    f"or None; got {self.color!r}"
                )


@dataclass
class WashiCornerSpec:
    """Rendering spec for one washi-tape corner sticker.

    Parameters
    ----------
    corner:
        ``"TL"`` / ``"TR"`` / ``"BL"`` / ``"BR"`` (case-insensitive).
    style:
        Colour palette.
    rotation_deg:
        Rotation applied to the tape rectangle. Small non-zero rotations
        give a hand-placed feel. Any finite float is accepted.
    size_px:
        Tape length along its long axis. The short axis (torn edge) is a
        fixed 12 px for visual consistency.
    tape_style_id:
        Optional reference to a
        :class:`pharos_editor.ui.theme.washi_tape.WashiTapeStyle` id
        (e.g. ``"tape_pink_dots"``). When set, the panel renderer
        prefers the procedural shader library over the legacy pigment
        table; when ``None`` the legacy path is used so themes that
        pre-date the shader library keep working unchanged.
    """

    corner: str
    style: WashiCornerStyle
    rotation_deg: float = 0.0
    size_px: int = 32
    tape_style_id: str | None = None

    def __post_init__(self) -> None:
        fn = "WashiCornerSpec"
        corner = validate_non_empty_str("corner", fn, self.corner).upper()
        if corner not in ("TL", "TR", "BL", "BR"):
            raise ValueError(
                f"{fn}: corner must be one of TL/TR/BL/BR; got {corner!r}"
            )
        self.corner = corner
        if not isinstance(self.style, WashiCornerStyle):
            raise TypeError(
                f"{fn}: style must be a WashiCornerStyle; "
                f"got {type(self.style).__name__}"
            )
        if not isinstance(self.rotation_deg, (int, float)) or isinstance(
            self.rotation_deg, bool
        ):
            raise TypeError(
                f"{fn}: rotation_deg must be a number; "
                f"got {type(self.rotation_deg).__name__}"
            )
        self.rotation_deg = float(self.rotation_deg)
        self.size_px = validate_positive_int("size_px", fn, self.size_px)
        if self.tape_style_id is not None:
            if (
                not isinstance(self.tape_style_id, str)
                or not self.tape_style_id
            ):
                raise TypeError(
                    f"{fn}: tape_style_id must be a non-empty str or None; "
                    f"got {self.tape_style_id!r}"
                )
            # Validate against the shader library — a typo here would
            # silently fall back to the legacy pigment which is the exact
            # bug the shader reference is meant to eliminate.
            from pharos_editor.ui.theme.washi_tape import WASHI_TAPES

            if self.tape_style_id not in WASHI_TAPES:
                raise ValueError(
                    f"{fn}: tape_style_id {self.tape_style_id!r} is not a "
                    f"known WashiTapeStyle; known: {sorted(WASHI_TAPES)}"
                )


# ---------------------------------------------------------------------------
# Divider stroke synthesis
# ---------------------------------------------------------------------------


# Constants match the sprint brief so tests can pin exact point counts.
_WAVY_AMPLITUDE_PX = 4
_WAVY_PERIOD_PX = 16
_WAVY_SAMPLES_PER_PERIOD = 16  # 16 samples/period ≈ 1 point/pixel
_DOTTED_SPACING_PX = 8
_DOTTED_RADIUS_PX = 2
_DASHED_DASH_PX = 8
_DASHED_GAP_PX = 4
_CHAIN_SPACING_PX = 16
_STAR_RADIUS_PX = 4
_HEART_RADIUS_PX = 3
_FLOWER_RADIUS_PX = 4


def sine_wave_points(
    p1: tuple[int, int],
    p2: tuple[int, int],
    amplitude: float = _WAVY_AMPLITUDE_PX,
    period: float = _WAVY_PERIOD_PX,
    samples_per_period: int = _WAVY_SAMPLES_PER_PERIOD,
) -> list[tuple[float, float]]:
    """Sample a sine wave polyline between *p1* and *p2*.

    The returned polyline is oriented along the ``p1 -> p2`` axis with
    the sine excursion applied on the perpendicular axis. Handy for
    horizontal *and* vertical dividers alike; the caller doesn't have
    to rotate anything.

    Returns
    -------
    list of ``(x, y)`` float pairs
        Guaranteed to contain at least two points (the two endpoints)
        even when *p1 == p2*.
    """
    x1, y1 = float(p1[0]), float(p1[1])
    x2, y2 = float(p2[0]), float(p2[1])
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length <= 0.0:
        return [(x1, y1), (x2, y2)]
    ux, uy = dx / length, dy / length
    # Perpendicular unit vector (rotate +90 degrees).
    nx, ny = -uy, ux
    n_samples = max(2, int(round(length / period * samples_per_period)) + 1)
    out: list[tuple[float, float]] = []
    for i in range(n_samples):
        t = i / (n_samples - 1)
        s = t * length
        phase = (s / period) * 2.0 * math.pi
        offset = amplitude * math.sin(phase)
        out.append((x1 + ux * s + nx * offset, y1 + uy * s + ny * offset))
    return out


def dotted_centers(
    p1: tuple[int, int],
    p2: tuple[int, int],
    spacing: float = _DOTTED_SPACING_PX,
) -> list[tuple[float, float]]:
    """Return the dot centres for a dotted divider between *p1* and *p2*."""
    x1, y1 = float(p1[0]), float(p1[1])
    x2, y2 = float(p2[0]), float(p2[1])
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length <= 0.0:
        return [(x1, y1)]
    n = int(length // spacing) + 1
    ux, uy = dx / length, dy / length
    return [(x1 + ux * i * spacing, y1 + uy * i * spacing) for i in range(n)]


def dashed_segments(
    p1: tuple[int, int],
    p2: tuple[int, int],
    dash: float = _DASHED_DASH_PX,
    gap: float = _DASHED_GAP_PX,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Return the individual dash segments for a dashed divider."""
    x1, y1 = float(p1[0]), float(p1[1])
    x2, y2 = float(p2[0]), float(p2[1])
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length <= 0.0:
        return []
    ux, uy = dx / length, dy / length
    stride = dash + gap
    n = max(1, int(length // stride) + 1)
    out: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for i in range(n):
        start_s = i * stride
        end_s = min(start_s + dash, length)
        if end_s <= start_s:
            continue
        out.append((
            (x1 + ux * start_s, y1 + uy * start_s),
            (x1 + ux * end_s, y1 + uy * end_s),
        ))
    return out


def _chain_centers(
    p1: tuple[int, int],
    p2: tuple[int, int],
    spacing: float = _CHAIN_SPACING_PX,
) -> list[tuple[float, float]]:
    x1, y1 = float(p1[0]), float(p1[1])
    x2, y2 = float(p2[0]), float(p2[1])
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length <= 0.0:
        return [(x1, y1)]
    n = int(length // spacing) + 1
    ux, uy = dx / length, dy / length
    # Offset half a spacing so glyphs sit *between* the endpoints, not on top.
    return [
        (x1 + ux * (i * spacing + spacing * 0.5),
         y1 + uy * (i * spacing + spacing * 0.5))
        for i in range(n)
        if (i * spacing + spacing * 0.5) < length
    ]


def star_polygon(
    center: tuple[float, float], radius: float = _STAR_RADIUS_PX,
) -> list[tuple[float, float]]:
    """Return the 8 vertices of a 4-point star centred on *center*.

    Alternates outer / inner radii so a plain filled-polygon call
    renders a plausible pointy star.
    """
    cx, cy = center
    inner = radius * 0.45
    pts: list[tuple[float, float]] = []
    for i in range(8):
        angle = math.pi / 2.0 + i * math.pi / 4.0
        r = radius if (i % 2 == 0) else inner
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return pts


def heart_polygon(
    center: tuple[float, float], radius: float = _HEART_RADIUS_PX,
) -> list[tuple[float, float]]:
    """Return a small closed-polygon heart centred on *center*."""
    cx, cy = center
    pts: list[tuple[float, float]] = []
    # Parametric heart, sampled at 24 evenly-spaced angles.
    for i in range(24):
        t = (i / 24.0) * 2.0 * math.pi
        # Classic ``16 sin^3(t)`` / ``13 cos(t) - 5 cos(2t) - 2 cos(3t) - cos(4t)``
        # heart. Scaled so the bounding radius matches *radius*.
        x = 16.0 * (math.sin(t) ** 3)
        y = -(
            13.0 * math.cos(t)
            - 5.0 * math.cos(2.0 * t)
            - 2.0 * math.cos(3.0 * t)
            - math.cos(4.0 * t)
        )
        pts.append((cx + x * (radius / 16.0), cy + y * (radius / 16.0)))
    return pts


def flower_petals(
    center: tuple[float, float], radius: float = _FLOWER_RADIUS_PX,
) -> list[tuple[float, float]]:
    """Return centres of the 5 petals of a five-petal flower."""
    cx, cy = center
    return [
        (
            cx + radius * math.cos(math.pi / 2.0 + i * 2.0 * math.pi / 5.0),
            cy + radius * math.sin(math.pi / 2.0 + i * 2.0 * math.pi / 5.0),
        )
        for i in range(5)
    ]


# ---------------------------------------------------------------------------
# Washi-tape geometry
# ---------------------------------------------------------------------------


_WASHI_SHORT_EDGE_PX = 12
_WASHI_DASH_SPACING_PX = 6


def _corner_anchor(
    bounds: tuple[int, int, int, int], corner: str,
) -> tuple[int, int]:
    """Return the ``(x, y)`` anchor point for *corner* of *bounds*."""
    x, y, w, h = bounds
    if corner == "TL":
        return (x, y)
    if corner == "TR":
        return (x + w, y)
    if corner == "BL":
        return (x, y + h)
    if corner == "BR":
        return (x + w, y + h)
    raise ValueError(f"_corner_anchor: unknown corner {corner!r}")


def _rotate(
    point: tuple[float, float],
    center: tuple[float, float],
    angle_deg: float,
) -> tuple[float, float]:
    """Rotate *point* around *center* by *angle_deg* degrees."""
    theta = math.radians(angle_deg)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    dx = point[0] - center[0]
    dy = point[1] - center[1]
    return (
        center[0] + dx * cos_t - dy * sin_t,
        center[1] + dx * sin_t + dy * cos_t,
    )


def washi_rect_corners(
    anchor: tuple[float, float],
    corner: str,
    size_px: int,
    rotation_deg: float,
    short_edge_px: int = _WASHI_SHORT_EDGE_PX,
) -> list[tuple[float, float]]:
    """Return the 4 rotated corners of a washi-tape rectangle.

    The tape is oriented along the diagonal of *corner*: TL / BR draw
    from the anchor toward the panel interior (positive diagonal); TR /
    BL take the opposite diagonal so both corners lean the same way
    against the panel edge.
    """
    diag = math.sqrt(0.5)
    if corner == "TL":
        dir_x, dir_y = +diag, +diag
    elif corner == "TR":
        dir_x, dir_y = -diag, +diag
    elif corner == "BR":
        dir_x, dir_y = -diag, -diag
    elif corner == "BL":
        dir_x, dir_y = +diag, -diag
    else:
        raise ValueError(f"washi_rect_corners: unknown corner {corner!r}")
    perp_x, perp_y = -dir_y, dir_x
    half_short = short_edge_px * 0.5
    p0 = (anchor[0] + perp_x * half_short, anchor[1] + perp_y * half_short)
    p1 = (
        anchor[0] + dir_x * size_px + perp_x * half_short,
        anchor[1] + dir_y * size_px + perp_y * half_short,
    )
    p2 = (
        anchor[0] + dir_x * size_px - perp_x * half_short,
        anchor[1] + dir_y * size_px - perp_y * half_short,
    )
    p3 = (anchor[0] - perp_x * half_short, anchor[1] - perp_y * half_short)
    if rotation_deg == 0.0:
        return [p0, p1, p2, p3]
    # Rotate around the anchor so the sticker still hugs the corner.
    return [_rotate(pt, (float(anchor[0]), float(anchor[1])), rotation_deg)
            for pt in (p0, p1, p2, p3)]


# ---------------------------------------------------------------------------
# Nested-panel adjacency helper
# ---------------------------------------------------------------------------


@dataclass
class _Edge:
    """Shared edge between two adjacent panels — used by divider layout."""

    orientation: str
    p1: tuple[int, int]
    p2: tuple[int, int]


def collect_divider_edges(
    panel_bounds: Sequence[tuple[int, int, int, int]],
    tol_px: int = 1,
) -> list[_Edge]:
    """Return every shared edge between the given axis-aligned bounds.

    Each bound is ``(x, y, w, h)``. Two panels share a *vertical* edge
    when panel A's ``x + w`` matches panel B's ``x`` (within *tol_px*)
    and their y-ranges overlap; a *horizontal* edge is the mirror
    condition. The returned edge segments span exactly the y-overlap
    (or x-overlap) so the divider only paints across the shared span.

    Duplicates are suppressed — swapping A and B produces the same edge.
    """
    if not isinstance(panel_bounds, (list, tuple)):
        raise TypeError(
            "collect_divider_edges: panel_bounds must be a list/tuple; "
            f"got {type(panel_bounds).__name__}"
        )
    if tol_px < 0:
        raise ValueError(
            f"collect_divider_edges: tol_px must be >= 0; got {tol_px}"
        )

    edges: list[_Edge] = []
    seen: set[tuple[str, int, int, int, int]] = set()
    n = len(panel_bounds)
    for i in range(n):
        ax, ay, aw, ah = panel_bounds[i]
        for j in range(i + 1, n):
            bx, by, bw, bh = panel_bounds[j]
            # Vertical edge — A on the left, B on the right, or vice versa.
            for (lx, ly, lw, lh, rx, ry, rh) in (
                (ax, ay, aw, ah, bx, by, bh),
                (bx, by, bw, bh, ax, ay, ah),
            ):
                if abs((lx + lw) - rx) <= tol_px:
                    y_top = max(ly, ry)
                    y_bot = min(ly + lh, ry + rh)
                    if y_bot > y_top:
                        edge_x = rx
                        key = ("V", edge_x, y_top, edge_x, y_bot)
                        if key not in seen:
                            seen.add(key)
                            edges.append(_Edge(
                                orientation="vertical",
                                p1=(edge_x, y_top),
                                p2=(edge_x, y_bot),
                            ))
            # Horizontal edge — A on top, B on bottom, or vice versa.
            for (tx, ty, tw, th, uxb, uy, uw) in (
                (ax, ay, aw, ah, bx, by, bw),
                (bx, by, bw, bh, ax, ay, aw),
            ):
                if abs((ty + th) - uy) <= tol_px:
                    x_left = max(tx, uxb)
                    x_right = min(tx + tw, uxb + uw)
                    if x_right > x_left:
                        edge_y = uy
                        key = ("H", x_left, edge_y, x_right, edge_y)
                        if key not in seen:
                            seen.add(key)
                            edges.append(_Edge(
                                orientation="horizontal",
                                p1=(x_left, edge_y),
                                p2=(x_right, edge_y),
                            ))
    return edges


def corner_specs_for_floating(
    is_floating: bool,
    style: WashiCornerStyle | str,
    corners: Sequence[str] = ("TL", "TR", "BL", "BR"),
    size_px: int = 32,
    rotation_seed: float = 0.0,
) -> list[WashiCornerSpec]:
    """Return the per-corner :class:`WashiCornerSpec` list.

    * Floating (dragged-out) windows get one spec per corner in
      *corners*, each with a small deterministic rotation offset for
      the hand-placed feel.
    * Docked windows get an empty list (no washi tape on tiled panels).

    The rotation offset is derived from *rotation_seed* plus a fixed
    per-corner phase so identical seeds always produce identical tape
    tilt patterns — handy for the golden tests.
    """
    if not is_floating:
        return []
    if isinstance(style, str):
        style_enum = WashiCornerStyle.from_str(style)
    elif isinstance(style, WashiCornerStyle):
        style_enum = style
    else:
        raise TypeError(
            "corner_specs_for_floating: style must be str or "
            f"WashiCornerStyle; got {type(style).__name__}"
        )
    if not isinstance(corners, (list, tuple)):
        raise TypeError(
            "corner_specs_for_floating: corners must be a list/tuple; "
            f"got {type(corners).__name__}"
        )
    if size_px <= 0:
        raise ValueError(
            f"corner_specs_for_floating: size_px must be > 0; got {size_px}"
        )

    phases = {"TL": -6.0, "TR": +7.0, "BL": +4.0, "BR": -5.0}
    specs: list[WashiCornerSpec] = []
    for corner in corners:
        c = str(corner).upper()
        if c not in phases:
            raise ValueError(
                f"corner_specs_for_floating: unknown corner {corner!r}; "
                f"expected TL/TR/BL/BR"
            )
        specs.append(WashiCornerSpec(
            corner=c,
            style=style_enum,
            rotation_deg=float(rotation_seed + phases[c]),
            size_px=size_px,
        ))
    return specs


# ---------------------------------------------------------------------------
# PanelDecor renderer
# ---------------------------------------------------------------------------


class PanelDecor:
    """Renders theme-driven decorations on panels.

    Nested panels get hand-drawn dividers between them (see
    :class:`DividerStyle`). Each divider is drawn on the parent's
    drawlist as a procedural pattern. Floating (dragged-out / non-docked)
    windows get washi-tape corner stickers, drawn with a slight rotation
    for a hand-placed feel.

    Theme integration: each :class:`ThemeSpec` has a ``decor:
    PanelDecorConfig`` field that picks the default divider style +
    corner style. Themes can override per panel kind via
    ``PanelDecorConfig.per_kind``.

    The renderer takes a *theme_getter* callable so tests can inject
    a fake theme without touching the global registry.
    """

    def __init__(self, theme_getter: Callable[[], Any]) -> None:
        if not callable(theme_getter):
            raise TypeError(
                "PanelDecor: theme_getter must be callable; "
                f"got {type(theme_getter).__name__}"
            )
        self._theme_getter = theme_getter

    # ------------------------------------------------------------------
    # Theme resolution
    # ------------------------------------------------------------------

    def _resolve_theme(self) -> Any | None:
        try:
            return self._theme_getter()
        except Exception:
            return None

    def _accent_color(self) -> tuple[int, int, int, int]:
        """Return the theme accent as an sRGB tuple with 8-bit alpha."""
        theme = self._resolve_theme()
        try:
            c = theme.semantic.accent  # type: ignore[union-attr]
            return (int(c.r), int(c.g), int(c.b), int(round(c.a * 255)))
        except Exception:
            return (120, 160, 255, 255)

    def default_divider_for_theme(
        self, kind: str | None = None, orientation: str = "horizontal",
    ) -> DividerSpec:
        """Return the theme's default divider for *kind*.

        Passes *kind* through to :meth:`PanelDecorConfig.for_panel` when
        provided so the caller sees per-panel-kind overrides.
        """
        theme = self._resolve_theme()
        divider_name = "wavy"
        thickness = 2
        try:
            decor = theme.decor  # type: ignore[union-attr]
            if kind:
                divider_name, _ = decor.for_panel(kind)
            else:
                divider_name = decor.divider_style
            thickness = int(decor.divider_thickness_px)
        except Exception:
            pass
        return DividerSpec(
            orientation=orientation,
            style=DividerStyle.from_str(divider_name),
            thickness_px=max(1, thickness),
        )

    def default_corner_for_theme(
        self, kind: str | None = None, corner: str = "TL",
    ) -> WashiCornerSpec:
        """Return the theme's default washi-tape corner for *kind*."""
        theme = self._resolve_theme()
        corner_name = "tape_pink"
        size = 32
        try:
            decor = theme.decor  # type: ignore[union-attr]
            if kind:
                _, corner_name = decor.for_panel(kind)
            else:
                corner_name = decor.corner_style
            size = int(decor.corner_size_px)
        except Exception:
            pass
        phases = {"TL": -6.0, "TR": +7.0, "BL": +4.0, "BR": -5.0}
        phase = phases.get(str(corner).upper(), 0.0)
        return WashiCornerSpec(
            corner=corner,
            style=WashiCornerStyle.from_str(corner_name),
            rotation_deg=phase,
            size_px=max(1, size),
        )

    # ------------------------------------------------------------------
    # Divider rendering
    # ------------------------------------------------------------------

    def render_divider(
        self, draw_list: Any,
        p1: tuple[int, int], p2: tuple[int, int],
        spec: DividerSpec,
    ) -> dict[str, int]:
        """Draw *spec*'s divider between *p1* and *p2* on *draw_list*.

        Returns a small ``{"draw_calls": N, ...}`` diagnostics dict so
        tests can assert the expected number of drawlist ops without
        having to hook DPG. The dict is also handy when profiling
        overdraw on complicated split-panel layouts.

        The method is headless-safe — every drawlist call is wrapped in
        try/except, so the same code path drives the CI stub and the
        live viewport.
        """
        if not isinstance(spec, DividerSpec):
            raise TypeError(
                "PanelDecor.render_divider: spec must be a DividerSpec; "
                f"got {type(spec).__name__}"
            )
        if (
            not isinstance(p1, tuple) or len(p1) != 2
            or not isinstance(p2, tuple) or len(p2) != 2
        ):
            raise TypeError(
                "PanelDecor.render_divider: p1 and p2 must be (int, int) "
                f"tuples; got {p1!r}, {p2!r}"
            )

        color = list(spec.color) if spec.color is not None else list(
            self._accent_color()
        )
        thickness = spec.thickness_px
        calls = 0

        if spec.style == DividerStyle.WAVY:
            pts = sine_wave_points(p1, p2)
            calls += _safe_draw_polyline(
                draw_list, pts, color=color, thickness=thickness,
            )
        elif spec.style == DividerStyle.DOTTED:
            for cx, cy in dotted_centers(p1, p2):
                calls += _safe_draw_circle(
                    draw_list, (cx, cy), _DOTTED_RADIUS_PX,
                    color=color, fill=color,
                )
        elif spec.style == DividerStyle.DASHED:
            for a, b in dashed_segments(p1, p2):
                calls += _safe_draw_line(
                    draw_list, a, b, color=color, thickness=thickness,
                )
        elif spec.style == DividerStyle.STAR_CHAIN:
            for center in _chain_centers(p1, p2):
                calls += _safe_draw_polygon(
                    draw_list, star_polygon(center),
                    color=color, fill=color, thickness=1,
                )
        elif spec.style == DividerStyle.HEART_CHAIN:
            for center in _chain_centers(p1, p2):
                calls += _safe_draw_polygon(
                    draw_list, heart_polygon(center),
                    color=color, fill=color, thickness=1,
                )
        elif spec.style == DividerStyle.FLOWER_CHAIN:
            for center in _chain_centers(p1, p2):
                for petal in flower_petals(center):
                    calls += _safe_draw_circle(
                        draw_list, petal, 2.0,
                        color=color, fill=color,
                    )
                calls += _safe_draw_circle(
                    draw_list, center, 1.5,
                    color=color, fill=color,
                )
        elif spec.style == DividerStyle.PENCIL_LINE:
            # Solid line + micro-wobble sampled sine at low amplitude,
            # tapered ends implemented as a thinner "cap" stroke either
            # side of the main run.
            pts = sine_wave_points(p1, p2, amplitude=0.7, period=8.0)
            calls += _safe_draw_polyline(
                draw_list, pts, color=color, thickness=thickness,
            )
            # Tapered ends — draw 2 shorter strokes at half thickness.
            head_thick = max(1, thickness - 1)
            if len(pts) >= 4:
                calls += _safe_draw_polyline(
                    draw_list, pts[:2], color=color, thickness=head_thick,
                )
                calls += _safe_draw_polyline(
                    draw_list, pts[-2:], color=color, thickness=head_thick,
                )
        else:  # pragma: no cover - guarded by DividerStyle enum
            raise ValueError(
                f"PanelDecor.render_divider: unknown style {spec.style!r}"
            )

        return {"draw_calls": calls, "style": spec.style.value}

    # ------------------------------------------------------------------
    # Corner rendering
    # ------------------------------------------------------------------

    def render_corner(
        self, draw_list: Any,
        panel_bounds: tuple[int, int, int, int],
        spec: WashiCornerSpec,
    ) -> dict[str, int]:
        """Draw a washi-tape sticker in *spec*'s corner of *panel_bounds*.

        The tape sits on *panel_bounds*'s anchor point, oriented along
        the diagonal into the panel, and receives an optional
        rotation offset for the hand-placed feel. A soft drop shadow
        is drawn under the tape (offset ``(+2, +2)``) and small dashed
        lines are added on top of the tape to imply a torn edge.

        Returns a diagnostics dict identical in shape to
        :meth:`render_divider`.
        """
        if not isinstance(spec, WashiCornerSpec):
            raise TypeError(
                "PanelDecor.render_corner: spec must be a WashiCornerSpec; "
                f"got {type(spec).__name__}"
            )
        if (
            not isinstance(panel_bounds, tuple)
            or len(panel_bounds) != 4
            or not all(isinstance(v, int) for v in panel_bounds)
        ):
            raise TypeError(
                "PanelDecor.render_corner: panel_bounds must be "
                f"(int, int, int, int); got {panel_bounds!r}"
            )

        anchor = _corner_anchor(panel_bounds, spec.corner)
        rect = washi_rect_corners(
            (float(anchor[0]), float(anchor[1])),
            spec.corner, spec.size_px, spec.rotation_deg,
        )
        pigment = washi_pigment(spec.style)
        pigment_list = [pigment[0], pigment[1], pigment[2], pigment[3]]

        calls = 0

        # Drop shadow — same rectangle, offset (+2, +2), 40% alpha.
        shadow_rect = [(px + 2.0, py + 2.0) for (px, py) in rect]
        shadow = [0, 0, 0, 60]
        calls += _safe_draw_polygon(
            draw_list, shadow_rect, color=shadow, fill=shadow, thickness=0,
        )

        # Body — filled pastel polygon.
        calls += _safe_draw_polygon(
            draw_list, rect,
            color=pigment_list, fill=pigment_list, thickness=1,
        )

        # Torn-paper edge — 3 short dashes evenly spaced along the
        # long axis, drawn slightly darker.
        edge_color = [
            max(0, pigment[0] - 40),
            max(0, pigment[1] - 40),
            max(0, pigment[2] - 40),
            220,
        ]
        # Interpolate along the top long edge (rect[0] -> rect[1]) and
        # bottom (rect[3] -> rect[2]) for the torn dashes.
        for t in (0.25, 0.5, 0.75):
            top_a = _lerp(rect[0], rect[1], t - 0.03)
            top_b = _lerp(rect[0], rect[1], t + 0.03)
            calls += _safe_draw_line(
                draw_list, top_a, top_b,
                color=edge_color, thickness=1,
            )
        for t in (0.25, 0.5, 0.75):
            bot_a = _lerp(rect[3], rect[2], t - 0.03)
            bot_b = _lerp(rect[3], rect[2], t + 0.03)
            calls += _safe_draw_line(
                draw_list, bot_a, bot_b,
                color=edge_color, thickness=1,
            )

        return {"draw_calls": calls, "style": spec.style.value}


# ---------------------------------------------------------------------------
# Drawlist safety wrappers
# ---------------------------------------------------------------------------


def _safe_draw_polyline(
    draw_list: Any,
    points: Sequence[tuple[float, float]],
    color: list[int] | tuple[int, ...],
    thickness: int,
) -> int:
    try:
        draw_list.draw_polyline(
            points=[list(p) for p in points],
            color=list(color),
            thickness=float(thickness),
        )
        return 1
    except Exception:
        return 0


def _safe_draw_line(
    draw_list: Any,
    p1: tuple[float, float],
    p2: tuple[float, float],
    color: list[int] | tuple[int, ...],
    thickness: int,
) -> int:
    try:
        draw_list.draw_line(
            p1=[float(p1[0]), float(p1[1])],
            p2=[float(p2[0]), float(p2[1])],
            color=list(color),
            thickness=float(thickness),
        )
        return 1
    except Exception:
        return 0


def _safe_draw_circle(
    draw_list: Any,
    center: tuple[float, float],
    radius: float,
    color: list[int] | tuple[int, ...],
    fill: list[int] | tuple[int, ...] | None = None,
) -> int:
    try:
        draw_list.draw_circle(
            center=[float(center[0]), float(center[1])],
            radius=float(radius),
            color=list(color),
            fill=list(fill) if fill is not None else None,
        )
        return 1
    except Exception:
        return 0


def _safe_draw_polygon(
    draw_list: Any,
    points: Sequence[tuple[float, float]],
    color: list[int] | tuple[int, ...],
    fill: list[int] | tuple[int, ...] | None,
    thickness: int,
) -> int:
    try:
        draw_list.draw_polygon(
            points=[list(p) for p in points],
            color=list(color),
            fill=list(fill) if fill is not None else None,
            thickness=float(thickness),
        )
        return 1
    except Exception:
        return 0


def _lerp(
    a: tuple[float, float], b: tuple[float, float], t: float,
) -> tuple[float, float]:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


__all__ = [
    "DividerSpec",
    "DividerStyle",
    "PanelDecor",
    "WashiCornerSpec",
    "WashiCornerStyle",
    "collect_divider_edges",
    "corner_specs_for_floating",
    "dashed_segments",
    "dotted_centers",
    "flower_petals",
    "heart_polygon",
    "sine_wave_points",
    "star_polygon",
    "washi_pigment",
    "washi_rect_corners",
]
