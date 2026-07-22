"""``panel_extras`` — decorative washi tape that spills PAST panel edges.

The floating notebook panels get a little "physical" flourish: strips of
washi tape rendered slightly *outside* the window rectangle so they look
like they were slapped over the top edge and dangle over the desktop.

The trick is a ``dpg.viewport_drawlist(front=True)`` — a drawlist that
lives on top of every window and isn't clipped by any of them. Each
frame the :class:`ExtendedPanelDecorator` walks its registered panels,
queries their current position + size, and paints one washi-tape
rectangle per :class:`ExtendedCornerSpec`.

Docked panels don't need this decoration (they're flush against a
neighbour) so :meth:`ExtendedPanelDecorator.render_all` skips any panel
whose :attr:`~MovablePanelWindow.docked_to` isn't the sentinel
``"floating"`` or ``None``.

The module is deliberately headless-safe: every DPG call sits inside
its own ``try/except`` and the washi-tape helper library is soft-imported
so unit tests can run against a plain recording stub. That's how
:mod:`PharosEngineTests.tests.test_extended_corners` drives the
renderer without a live viewport.

Public surface
--------------

.. code-block:: python

    from pharos_editor.ui.editor.panel_extras import (
        ExtendedCornerSpec,
        ExtendedPanelDecorator,
        default_extended_corners_for_theme,
    )
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Sequence

from pharos_engine._validation import (
    validate_non_empty_str,
    validate_positive_int,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pharos_editor.ui.editor.movable_panel import MovablePanelWindow


# ---------------------------------------------------------------------------
# Corner anchors
# ---------------------------------------------------------------------------

_VALID_CORNERS = ("TL", "TR", "BL", "BR")


def _corner_base(
    bounds: tuple[int, int, int, int], corner: str,
) -> tuple[int, int]:
    """Return the ``(x, y)`` anchor point of *corner* on *bounds*.

    ``bounds`` is ``(x, y, w, h)`` — the top-left origin + width/height as
    reported by DPG. TL is the anchor at ``(x, y)``, TR at ``(x+w, y)``,
    BL at ``(x, y+h)`` and BR at ``(x+w, y+h)``.
    """
    x, y, w, h = bounds
    if corner == "TL":
        return (x, y)
    if corner == "TR":
        return (x + w, y)
    if corner == "BL":
        return (x, y + h)
    if corner == "BR":
        return (x + w, y + h)
    raise ValueError(f"_corner_base: unknown corner {corner!r}")


# ---------------------------------------------------------------------------
# ExtendedCornerSpec
# ---------------------------------------------------------------------------


@dataclass
class ExtendedCornerSpec:
    """A washi-tape corner sticker that extends beyond the panel bounds.

    Rendered via DPG's ``viewport_drawlist`` (which is not clipped to any
    window), positioned relative to the panel corner + an offset.

    Parameters
    ----------
    corner:
        One of ``TL`` / ``TR`` / ``BL`` / ``BR`` (case-insensitive).
    tape_style:
        Identifier of the washi-tape style. When the U1 washi-tape
        library is available it's fed straight into ``render_tape``;
        otherwise :mod:`panel_decor`'s :class:`WashiCornerStyle` is used
        as a fallback so tape colouring still works.
    tape_size_px:
        ``(long_edge, short_edge)`` size of the tape strip in pixels.
        The long edge runs along the panel's edge, the short edge is
        perpendicular to it. Both dimensions must be positive.
    offset_px:
        ``(dx, dy)`` shift applied to the corner anchor **before**
        drawing. Negative components pull the tape *outward* past the
        panel edge — that's the whole point of the decoration.
    rotation_deg:
        Degrees to rotate the tape rectangle about its own anchor point.
        Small non-zero angles give the hand-placed feel.
    z_order:
        Sort key: lower z draws first, higher z draws on top. Ties are
        broken by the order corners were attached (stable sort).
    """

    corner: str
    tape_style: str
    tape_size_px: tuple[int, int] = (48, 16)
    offset_px: tuple[int, int] = (-8, -6)
    rotation_deg: float = 0.0
    z_order: int = 10

    def __post_init__(self) -> None:
        fn = "ExtendedCornerSpec"
        corner = validate_non_empty_str("corner", fn, self.corner).upper()
        if corner not in _VALID_CORNERS:
            raise ValueError(
                f"{fn}: corner must be one of TL/TR/BL/BR; got {corner!r}"
            )
        self.corner = corner
        # tape_style is a bare identifier so YAML themes can carry it —
        # we don't couple this dataclass to any enum from panel_decor.
        self.tape_style = validate_non_empty_str(
            "tape_style", fn, self.tape_style,
        )
        if (
            not isinstance(self.tape_size_px, tuple)
            or len(self.tape_size_px) != 2
        ):
            raise TypeError(
                f"{fn}: tape_size_px must be a (long, short) tuple; "
                f"got {self.tape_size_px!r}"
            )
        long_edge, short_edge = self.tape_size_px
        validate_positive_int("tape_size_px[0]", fn, long_edge)
        validate_positive_int("tape_size_px[1]", fn, short_edge)
        self.tape_size_px = (int(long_edge), int(short_edge))
        if (
            not isinstance(self.offset_px, tuple)
            or len(self.offset_px) != 2
            or not all(isinstance(v, int) for v in self.offset_px)
        ):
            raise TypeError(
                f"{fn}: offset_px must be an (int, int) tuple; "
                f"got {self.offset_px!r}"
            )
        if not isinstance(self.rotation_deg, (int, float)) or isinstance(
            self.rotation_deg, bool,
        ):
            raise TypeError(
                f"{fn}: rotation_deg must be a number; "
                f"got {type(self.rotation_deg).__name__}"
            )
        self.rotation_deg = float(self.rotation_deg)
        if not isinstance(self.z_order, int) or isinstance(self.z_order, bool):
            raise TypeError(
                f"{fn}: z_order must be an int; "
                f"got {type(self.z_order).__name__}"
            )


# ---------------------------------------------------------------------------
# Soft-import for U1 washi-tape library
# ---------------------------------------------------------------------------


def _load_tape_renderer() -> Callable[..., Any] | None:
    """Return U1's ``render_tape`` if importable, else ``None``.

    The library is optional at build time — when it isn't installed we
    fall back to the built-in :mod:`panel_decor` pigment palette so the
    tape still draws as a coloured polygon.
    """
    try:
        from pharos_editor.ui.theme.washi_tape import render_tape  # type: ignore
        return render_tape
    except Exception:
        return None


def _fallback_pigment(style: str) -> tuple[int, int, int, int]:
    """Look up an RGBA colour for *style* using :mod:`panel_decor`.

    Unknown style names fall back to a neutral cream tape so the sticker
    is never invisible. This helper is what keeps :class:`ExtendedPanelDecorator`
    functional in CI where U1's library is not present.
    """
    try:
        from pharos_editor.ui.editor.panel_decor import (
            WashiCornerStyle,
            washi_pigment,
        )
        return washi_pigment(WashiCornerStyle.from_str(style))
    except Exception:
        return (245, 235, 200, 220)


# ---------------------------------------------------------------------------
# Rotation math (used both by ExtendedPanelDecorator and by tests)
# ---------------------------------------------------------------------------


def _rotate_around(
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


def _tape_polygon(
    anchor: tuple[float, float],
    corner: str,
    tape_size_px: tuple[int, int],
    rotation_deg: float,
) -> list[tuple[float, float]]:
    """Return the 4 corners of the tape polygon.

    The tape's long edge runs along the panel edge that owns *corner*
    (horizontal for TL / TR, vertical for BL / BR — actually all four are
    horizontal-relative so the "washi across the top / bottom" reads
    consistently). The short edge is perpendicular. Both dimensions are
    measured in pixels via *tape_size_px* ``(long, short)``.

    The tape is centred on *anchor* along its long axis so callers can
    apply a positive-outward *offset* and still get a tape strip that
    straddles the corner rather than dangling from it.
    """
    long_edge, short_edge = tape_size_px
    half_long = long_edge * 0.5
    half_short = short_edge * 0.5
    # Base rectangle: horizontal tape centred on origin.
    base = [
        (-half_long, -half_short),
        (+half_long, -half_short),
        (+half_long, +half_short),
        (-half_long, +half_short),
    ]
    # Auto-tilt so BL / BR tape leans the "opposite" way when unspecified —
    # subtle detail, easily overridden via *rotation_deg*.
    corner_lean = {
        "TL": 0.0, "TR": 0.0, "BL": 0.0, "BR": 0.0,
    }.get(corner, 0.0)
    total_angle = float(rotation_deg) + corner_lean
    ax, ay = float(anchor[0]), float(anchor[1])
    return [
        _rotate_around((ax + bx, ay + by), (ax, ay), total_angle)
        for (bx, by) in base
    ]


# ---------------------------------------------------------------------------
# ExtendedPanelDecorator
# ---------------------------------------------------------------------------


class ExtendedPanelDecorator:
    """Renders extended washi-tape corners for :class:`MovablePanelWindow`.

    Uses ``dpg.viewport_drawlist(front=True)`` so decorations sit on top
    of the panel window AND spill past its edges. Each frame,
    :meth:`render_all` queries the panel's current position + size and
    draws the tape strips accordingly.

    The renderer is headless-safe. When Dear PyGui isn't importable the
    decorator still walks its bookkeeping (attach / detach / is_floating
    all keep working) so tests can drive the full state machine.

    Parameters
    ----------
    tape_registry:
        Optional handle to U1's washi-tape registry. When ``None`` the
        decorator soft-imports :func:`pharos_editor.ui.theme.washi_tape.render_tape`
        on first use, and falls back to a coloured polygon when the
        library isn't installed.
    """

    def __init__(self, tape_registry: Any | None = None) -> None:
        self._tape_registry = tape_registry
        # Preserve insertion order so tests can assert deterministic draw
        # sequences without needing a stable-hash workaround.
        self._panels: dict[str, tuple[Any, list[ExtendedCornerSpec]]] = {}
        # Lazy handle to the U1 tape renderer, resolved once per instance.
        self._tape_renderer: Callable[..., Any] | None | Any = _load_tape_renderer()
        # Diagnostics from the last render_all — handy for tests + profiling.
        self.last_draw_calls: int = 0
        self.last_visited_panels: int = 0

    # ------------------------------------------------------------------
    # Bookkeeping
    # ------------------------------------------------------------------

    def _panel_key(self, panel_window: "MovablePanelWindow") -> str:
        """Return a stable dict key for *panel_window*.

        Uses the DPG window tag when available; otherwise falls back to
        :func:`id` so unbuilt panels still route correctly.
        """
        try:
            tag = panel_window.get_window_tag()
        except Exception:
            tag = None
        if isinstance(tag, str) and tag:
            return tag
        return f"panel_id_{id(panel_window)}"

    def attach(
        self,
        panel_window: "MovablePanelWindow",
        specs: Sequence[ExtendedCornerSpec],
    ) -> None:
        """Attach a list of :class:`ExtendedCornerSpec` to *panel_window*.

        Overwrites any previous registration for the same panel so the
        theme switcher can re-attach with a fresh spec list without
        first calling :meth:`detach`.
        """
        if panel_window is None:
            raise TypeError(
                "ExtendedPanelDecorator.attach: panel_window must not be None"
            )
        if not isinstance(specs, (list, tuple)):
            raise TypeError(
                "ExtendedPanelDecorator.attach: specs must be a list/tuple; "
                f"got {type(specs).__name__}"
            )
        clean: list[ExtendedCornerSpec] = []
        for i, s in enumerate(specs):
            if not isinstance(s, ExtendedCornerSpec):
                raise TypeError(
                    "ExtendedPanelDecorator.attach: specs[{}] must be "
                    "ExtendedCornerSpec; got {}".format(i, type(s).__name__)
                )
            clean.append(s)
        # Also stamp the list onto the panel window so downstream code
        # (theme switcher, layout persistence) can inspect it without
        # having to route through the decorator.
        try:
            panel_window.extended_corners = list(clean)  # type: ignore[attr-defined]
        except Exception:
            pass
        self._panels[self._panel_key(panel_window)] = (panel_window, list(clean))

    def detach(self, panel_window: "MovablePanelWindow") -> None:
        """Remove all extended corners for *panel_window*.

        No-op when the panel wasn't attached — makes cleanup during
        teardown idempotent.
        """
        if panel_window is None:
            return
        key = self._panel_key(panel_window)
        self._panels.pop(key, None)
        try:
            panel_window.extended_corners = []  # type: ignore[attr-defined]
        except Exception:
            pass

    def get_specs(
        self, panel_window: "MovablePanelWindow",
    ) -> list[ExtendedCornerSpec]:
        """Return a copy of the currently-attached specs for *panel_window*."""
        entry = self._panels.get(self._panel_key(panel_window))
        if entry is None:
            return []
        return list(entry[1])

    def attached_panels(self) -> list[Any]:
        """Return the list of currently-attached panel windows."""
        return [pw for (pw, _specs) in self._panels.values()]

    # ------------------------------------------------------------------
    # Predicates
    # ------------------------------------------------------------------

    def is_floating(self, panel_window: "MovablePanelWindow") -> bool:
        """Return ``True`` iff *panel_window* is currently floating.

        ``MovablePanelWindow.docked_to`` is the source of truth. The
        sentinel ``"floating"`` and ``None`` both count as floating
        (older layout files stamp ``None``, newer YAML uses the string).
        """
        try:
            docked_to = getattr(panel_window, "docked_to", None)
        except Exception:
            return False
        if docked_to is None:
            return True
        if isinstance(docked_to, str) and docked_to.lower() == "floating":
            return True
        return False

    # ------------------------------------------------------------------
    # Per-frame render
    # ------------------------------------------------------------------

    def render_all(self, draw_list_tag: Any) -> dict[str, int]:
        """Render every attached panel's extended corners on *draw_list_tag*.

        *draw_list_tag* is either the DPG tag of a viewport drawlist
        (str / int) or a recording stub with ``draw_image`` /
        ``draw_polygon`` methods — the latter is what unit tests use to
        inspect the emitted ops without a live viewport.

        Returns a diagnostics dict ``{"draw_calls": N,
        "visited_panels": M, "skipped_docked": K}`` so tests can assert
        the exact drawlist ops without hooking a live viewport.

        Docked panels are skipped — they sit flush against a neighbour
        and don't need the physical-tape flourish. Panels with no attached
        specs are also skipped cheaply.
        """
        if draw_list_tag is None:
            raise TypeError(
                "ExtendedPanelDecorator.render_all: draw_list_tag must not be None"
            )
        draw_calls = 0
        visited = 0
        skipped = 0
        for panel_window, specs in self._panels.values():
            if not specs:
                continue
            if not self.is_floating(panel_window):
                skipped += 1
                continue
            bounds = self._resolve_bounds(panel_window)
            if bounds is None:
                continue
            visited += 1
            # Stable sort by z_order so drawing order is deterministic
            # and low-z tape sits under high-z tape.
            for spec in sorted(specs, key=lambda s: s.z_order):
                draw_calls += self._draw_one(draw_list_tag, bounds, spec)
        self.last_draw_calls = draw_calls
        self.last_visited_panels = visited
        return {
            "draw_calls": draw_calls,
            "visited_panels": visited,
            "skipped_docked": skipped,
        }

    # ------------------------------------------------------------------
    # Bounds resolution
    # ------------------------------------------------------------------

    def _resolve_bounds(
        self, panel_window: "MovablePanelWindow",
    ) -> tuple[int, int, int, int] | None:
        """Return ``(x, y, w, h)`` for *panel_window* or ``None`` on failure.

        Prefers a live DPG query so animated / snapped moves show up
        immediately; falls back to the panel's cached position + size
        (which the wrapper keeps in sync with :meth:`set_position` /
        :meth:`set_size`) when DPG isn't available *or* the panel hasn't
        been built yet.

        The live path is guarded on ``panel_window.is_built`` — calling
        ``dpg.does_item_exist`` before ``create_context`` segfaults on
        Windows, so the wrapper's own ``_built`` bit is our gate.
        """
        panel_is_built = bool(getattr(panel_window, "is_built", False))
        if panel_is_built:
            try:
                import dearpygui.dearpygui as dpg  # type: ignore[import-not-found]
            except Exception:
                dpg = None  # type: ignore[assignment]
            tag: str | None = None
            try:
                tag = panel_window.get_window_tag()
            except Exception:
                tag = None
            if dpg is not None and isinstance(tag, str) and tag:
                try:
                    if dpg.does_item_exist(tag):
                        pos = dpg.get_item_pos(tag)
                        w = dpg.get_item_width(tag)
                        h = dpg.get_item_height(tag)
                        if (
                            pos is not None
                            and w is not None
                            and h is not None
                        ):
                            return (
                                int(pos[0]), int(pos[1]),
                                int(w), int(h),
                            )
                except Exception:
                    pass
        try:
            x, y = panel_window.get_position()
            w, h = panel_window.get_size()
            return (int(x), int(y), int(w), int(h))
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Single-tape draw
    # ------------------------------------------------------------------

    def _draw_one(
        self,
        draw_list_tag: str | int,
        bounds: tuple[int, int, int, int],
        spec: ExtendedCornerSpec,
    ) -> int:
        """Draw one tape strip. Returns the number of drawlist ops emitted."""
        base_x, base_y = _corner_base(bounds, spec.corner)
        ax = base_x + spec.offset_px[0]
        ay = base_y + spec.offset_px[1]
        polygon = _tape_polygon(
            (float(ax), float(ay)),
            spec.corner,
            spec.tape_size_px,
            spec.rotation_deg,
        )
        pigment = _fallback_pigment(spec.tape_style)
        color_list = [pigment[0], pigment[1], pigment[2], pigment[3]]

        # Prefer U1's render_tape when available (it lays down a proper
        # textured tape with alpha edges). Fall back to a filled polygon
        # so headless CI still exercises the geometry path.
        renderer = self._tape_renderer
        if renderer is not None:
            try:
                renderer(
                    draw_list_tag,
                    polygon=polygon,
                    style=spec.tape_style,
                    rotation_deg=spec.rotation_deg,
                )
                return 1
            except Exception:
                # Fall through to the coloured-polygon path so a broken
                # tape library never leaves the corner blank.
                pass

        return _safe_draw_image(
            draw_list_tag, polygon, color_list, spec,
        )


# ---------------------------------------------------------------------------
# Drawlist wrappers
# ---------------------------------------------------------------------------


def _safe_draw_image(
    draw_list_tag: str | int,
    polygon: list[tuple[float, float]],
    color: list[int],
    spec: ExtendedCornerSpec,
) -> int:
    """Emit ``draw_image``-style call on *draw_list_tag*.

    Uses the polygon-based fallback when the drawlist doesn't have a
    ``draw_image`` method — tests can hand us a recording stub with either
    surface and see one op recorded either way.
    """
    # First path: a raw object with recording methods (unit tests).
    if hasattr(draw_list_tag, "draw_image"):
        try:
            pmin = (min(p[0] for p in polygon), min(p[1] for p in polygon))
            pmax = (max(p[0] for p in polygon), max(p[1] for p in polygon))
            draw_list_tag.draw_image(  # type: ignore[attr-defined]
                texture_tag=spec.tape_style,
                pmin=list(pmin),
                pmax=list(pmax),
                color=list(color),
                rotation_deg=float(spec.rotation_deg),
                polygon=[list(p) for p in polygon],
            )
            return 1
        except Exception:
            pass
    if hasattr(draw_list_tag, "draw_polygon"):
        try:
            draw_list_tag.draw_polygon(  # type: ignore[attr-defined]
                points=[list(p) for p in polygon],
                color=list(color),
                fill=list(color),
                thickness=1.0,
            )
            return 1
        except Exception:
            return 0

    # Second path: a DPG tag — route through the live module.
    try:
        import dearpygui.dearpygui as dpg  # type: ignore[import-not-found]
    except Exception:
        return 0
    try:
        dpg.draw_polygon(
            points=[list(p) for p in polygon],
            color=color,
            fill=color,
            thickness=1.0,
            parent=draw_list_tag,
        )
        return 1
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Theme-driven default specs
# ---------------------------------------------------------------------------


def default_extended_corners_for_theme(
    theme: Any | None,
    kind: str | None = None,
) -> list[ExtendedCornerSpec]:
    """Return the default TL / TR extended corner list for *theme*.

    The floating-window brief calls for two tape strips per panel — one
    over the TL corner and one over the TR corner — each 48×16 px and
    each offset -8 px inward horizontally (so it hangs past the corner
    outward) and -6 px vertically. When *theme* is ``None`` or its
    ``decor`` is missing the fallback tape style is ``"tape_pink"``.

    *kind* is forwarded to :meth:`PanelDecorConfig.for_panel` so themes
    that override per panel kind (toolbar / sidebar / …) get their
    override applied. Unknown / missing kinds fall through to the theme
    default.
    """
    style = "tape_pink"
    if theme is not None:
        try:
            decor = getattr(theme, "decor", None)
            if decor is not None:
                if kind:
                    try:
                        _, corner_style = decor.for_panel(kind)
                        style = corner_style or style
                    except Exception:
                        style = getattr(decor, "corner_style", style)
                else:
                    style = getattr(decor, "corner_style", style)
        except Exception:
            pass
    return [
        ExtendedCornerSpec(
            corner="TL",
            tape_style=style,
            tape_size_px=(48, 16),
            offset_px=(-8, -6),
            rotation_deg=-8.0,
            z_order=10,
        ),
        ExtendedCornerSpec(
            corner="TR",
            tape_style=style,
            tape_size_px=(48, 16),
            offset_px=(-40, -6),
            rotation_deg=+7.0,
            z_order=10,
        ),
    ]


__all__ = [
    "ExtendedCornerSpec",
    "ExtendedPanelDecorator",
    "default_extended_corners_for_theme",
]
