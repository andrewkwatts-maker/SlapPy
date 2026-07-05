"""Ready-made HUD widgets — health bar, stamina bar, ammo counter, etc.

Each HUD widget is a small class with three affordances:

* Data fields you mutate from your game state (``value``, ``max_value``,
  ``ammo``, …).
* A ``.build(ui)`` method that emits :class:`DrawCommand` records via
  the passed-in :class:`ImmediateUI`.
* Simple invariants — mostly clamping ``value`` into the legal range so
  a wonky game tick doesn't cause a crash mid-frame.

Widgets don't own persistent state beyond their fields, so callers can
re-instantiate them freely if that fits the game architecture better
than a long-lived instance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .immediate_ui import ImmediateUI


RGBA = tuple[float, float, float, float]

_RED: RGBA = (0.86, 0.24, 0.24, 1.0)
_GREEN: RGBA = (0.28, 0.72, 0.36, 1.0)
_YELLOW: RGBA = (0.94, 0.82, 0.28, 1.0)
_WHITE: RGBA = (0.94, 0.96, 0.98, 1.0)
_TRANSPARENT: RGBA = (0.0, 0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# HealthBar
# ---------------------------------------------------------------------------


@dataclass
class HealthBar:
    """A labelled HP bar.

    Attributes
    ----------
    position, size:
        Screen-space top-left and size in pixels.
    value:
        Current HP.
    max_value:
        Full HP; must be > 0.
    label:
        Short prefix (e.g. ``"HP"``). Empty → no label.
    fill_color:
        Colour of the filled portion. Defaults to a saturated red.
    """

    position: tuple[float, float] = (16.0, 16.0)
    size: tuple[float, float] = (180.0, 14.0)
    value: float = 100.0
    max_value: float = 100.0
    label: str = "HP"
    fill_color: RGBA = _RED

    def build(self, ui: "ImmediateUI") -> None:
        if self.max_value <= 0:
            raise ValueError("HealthBar: max_value must be > 0")
        ratio = max(0.0, min(1.0, self.value / self.max_value))
        # Reuse the progress_bar draw path; add a label on top.
        ui.progress_bar(
            f"__healthbar_{id(self):x}",
            self.position,
            self.size,
            ratio,
        )
        if self.label:
            ui.label(
                f"__healthbar_lbl_{id(self):x}",
                f"{self.label} {int(self.value)}/{int(self.max_value)}",
                (self.position[0] + 4.0, self.position[1] - 1.0),
            )


# ---------------------------------------------------------------------------
# StaminaBar
# ---------------------------------------------------------------------------


@dataclass
class StaminaBar:
    """A stamina bar (green fill by convention)."""

    position: tuple[float, float] = (16.0, 34.0)
    size: tuple[float, float] = (180.0, 10.0)
    value: float = 100.0
    max_value: float = 100.0
    fill_color: RGBA = _GREEN

    def build(self, ui: "ImmediateUI") -> None:
        if self.max_value <= 0:
            raise ValueError("StaminaBar: max_value must be > 0")
        ratio = max(0.0, min(1.0, self.value / self.max_value))
        ui.progress_bar(
            f"__staminabar_{id(self):x}",
            self.position,
            self.size,
            ratio,
        )


# ---------------------------------------------------------------------------
# AmmoCounter
# ---------------------------------------------------------------------------


@dataclass
class AmmoCounter:
    """A textual ammo counter (``current / reserve``)."""

    position: tuple[float, float] = (16.0, 60.0)
    current: int = 0
    reserve: int = 0
    weapon_name: str = ""

    def build(self, ui: "ImmediateUI") -> None:
        curr = max(0, int(self.current))
        res = max(0, int(self.reserve))
        text = f"{curr} / {res}"
        if self.weapon_name:
            text = f"{self.weapon_name}  {text}"
        ui.label(f"__ammo_{id(self):x}", text, self.position)


# ---------------------------------------------------------------------------
# Minimap (thin wrapper)
# ---------------------------------------------------------------------------


@dataclass
class Minimap:
    """A minimap surface — background rect + optional textured overlay.

    The minimap doesn't try to render map data itself; it emits a rect
    (or a textured quad when :attr:`texture_id` is set) so the game's
    renderer can supply the map texture out-of-band. Marker points can
    be added via :meth:`add_marker` and are drawn as small filled
    rectangles.
    """

    position: tuple[float, float] = (16.0, 80.0)
    size: tuple[float, float] = (128.0, 128.0)
    texture_id: int | None = None
    markers: list[tuple[float, float, RGBA]] = field(default_factory=list)

    def add_marker(
        self, x: float, y: float, color: RGBA = _WHITE
    ) -> None:
        """Add a marker at screen-space ``(x, y)`` with the given colour."""
        self.markers.append((float(x), float(y), color))

    def build(self, ui: "ImmediateUI") -> None:
        from .draw_command import DrawCommand
        # Panel-style background so the minimap reads as a UI slot.
        with ui.panel(
            f"__minimap_{id(self):x}",
            self.position,
            self.size,
            title=None,
            movable=False,
        ):
            pass
        # Optional textured overlay (renderer looks up texture_id).
        if self.texture_id is not None:
            ui._commands.append(  # direct emit — no widget id needed
                DrawCommand(
                    kind="textured_quad",
                    position=self.position,
                    size=self.size,
                    color=(1.0, 1.0, 1.0, 1.0),
                    texture_id=int(self.texture_id),
                    z_order=20,
                )
            )
        # Markers.
        for i, (mx, my, mcol) in enumerate(self.markers):
            ui._commands.append(
                DrawCommand(
                    kind="rect",
                    position=(mx - 1.0, my - 1.0),
                    size=(2.0, 2.0),
                    color=mcol,
                    z_order=21,
                )
            )


# ---------------------------------------------------------------------------
# Compass
# ---------------------------------------------------------------------------


@dataclass
class Compass:
    """A heading readout — draws the current bearing as a text label.

    Attributes
    ----------
    heading_deg:
        Bearing in degrees, ``0.0`` = north, wraps mod 360.
    """

    position: tuple[float, float] = (16.0, 220.0)
    heading_deg: float = 0.0

    _CARDINALS: tuple[str, ...] = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

    def build(self, ui: "ImmediateUI") -> None:
        bearing = float(self.heading_deg) % 360.0
        # Snap to nearest 45° for the cardinal readout.
        idx = int(round(bearing / 45.0)) % len(self._CARDINALS)
        cardinal = self._CARDINALS[idx]
        text = f"{cardinal}  {bearing:5.1f}°"
        ui.label(f"__compass_{id(self):x}", text, self.position)


# ---------------------------------------------------------------------------
# Toast
# ---------------------------------------------------------------------------


@dataclass
class Toast:
    """A pop-up notification that fades after a fixed duration.

    Attributes
    ----------
    message:
        Text drawn inside the toast rect.
    duration_s:
        Total lifetime in seconds; defaults to 2.
    remaining_s:
        Countdown that :meth:`build` decrements each frame using
        ``ui._dt``. Callers who prefer explicit tick control can drive
        it directly.
    """

    message: str = ""
    position: tuple[float, float] = (16.0, 240.0)
    size: tuple[float, float] = (240.0, 28.0)
    duration_s: float = 2.0
    remaining_s: float = 2.0

    def __post_init__(self) -> None:
        # Keep remaining_s in [0, duration_s].
        self.remaining_s = max(0.0, min(float(self.remaining_s), float(self.duration_s)))

    @property
    def is_alive(self) -> bool:
        return self.remaining_s > 0.0

    def tick(self, dt: float) -> None:
        """Decrement :attr:`remaining_s` by *dt*, clamping at zero."""
        self.remaining_s = max(0.0, self.remaining_s - float(dt))

    def build(self, ui: "ImmediateUI") -> None:
        # Auto-tick from the UI's frame dt.
        self.tick(getattr(ui, "_dt", 0.0))
        if not self.is_alive:
            return
        from .draw_command import DrawCommand
        alpha = self.remaining_s / self.duration_s if self.duration_s > 0 else 1.0
        # Background — panel-bg colour with alpha fade.
        bg = ui.theme.panel_bg_color
        bg_faded: RGBA = (bg[0], bg[1], bg[2], bg[3] * alpha)
        text_col = ui.theme.text_color
        text_faded: RGBA = (
            text_col[0], text_col[1], text_col[2], text_col[3] * alpha,
        )
        ui._commands.append(
            DrawCommand(
                kind="rect",
                position=self.position,
                size=self.size,
                color=bg_faded,
                z_order=100,
            )
        )
        ui._commands.append(
            DrawCommand(
                kind="text",
                position=(self.position[0] + 8.0, self.position[1] + 6.0),
                size=self.size,
                color=text_faded,
                text=self.message,
                z_order=101,
            )
        )


__all__ = [
    "AmmoCounter",
    "Compass",
    "HealthBar",
    "Minimap",
    "StaminaBar",
    "Toast",
]
