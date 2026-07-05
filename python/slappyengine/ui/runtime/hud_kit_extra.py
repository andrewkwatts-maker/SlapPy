"""Extra HUD widgets — Crosshair, ScoreCounter, ObjectiveMarker.

These live in a separate module because :mod:`hud_kit` is HH7-frozen
(the original six widgets remain the reference for the runtime layer).
The additions here follow the same conventions:

* Small dataclass-ish widgets that mutate freely from the game state.
* A ``.build(ui)`` method that emits :class:`DrawCommand`s via the
  passed-in :class:`ImmediateUI`.
* No external state — safe to re-instantiate every frame.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .draw_command import DrawCommand

if TYPE_CHECKING:
    from .immediate_ui import ImmediateUI


RGBA = tuple[float, float, float, float]

_WHITE: RGBA = (0.94, 0.96, 0.98, 1.0)
_AMBER: RGBA = (0.98, 0.72, 0.20, 1.0)
_CYAN: RGBA = (0.30, 0.82, 0.98, 1.0)


# ---------------------------------------------------------------------------
# Crosshair — 4-line reticle in the centre of the viewport.
# ---------------------------------------------------------------------------


@dataclass
class Crosshair:
    """A simple 4-line reticle drawn at the viewport centre.

    Attributes
    ----------
    center:
        Screen-space centre in pixels. Defaults to ``(640, 360)`` which
        is the middle of a 1280x720 viewport.
    gap:
        Empty pixel radius around the centre — mimics an FPS crosshair
        where the lines don't touch.
    length:
        Pixel length of each of the four line segments.
    thickness:
        Reserved for the future; the current renderer treats lines as
        1-pixel wide. Kept as an attribute so themes can carry it.
    color:
        Reticle ink colour; alpha respected.
    """

    center: tuple[float, float] = (640.0, 360.0)
    gap: float = 4.0
    length: float = 8.0
    thickness: float = 1.0
    color: RGBA = _WHITE

    def build(self, ui: "ImmediateUI") -> None:
        cx, cy = self.center
        g = float(self.gap)
        L = float(self.length)
        # Emit four DrawCommand("line", ...) segments. The size vector
        # encodes the (dx, dy) to the second endpoint per DrawCommand
        # semantics.
        segments = (
            # Left arm  →  (cx - g - L, cy)  to  (cx - g, cy)
            ((cx - g - L, cy), (L, 0.0)),
            # Right arm →  (cx + g, cy)      to  (cx + g + L, cy)
            ((cx + g, cy), (L, 0.0)),
            # Top arm   →  (cx, cy - g - L)  to  (cx, cy - g)
            ((cx, cy - g - L), (0.0, L)),
            # Bottom arm→  (cx, cy + g)      to  (cx, cy + g + L)
            ((cx, cy + g), (0.0, L)),
        )
        for pos, size in segments:
            ui._commands.append(
                DrawCommand(
                    kind="line",
                    position=pos,
                    size=size,
                    color=self.color,
                    z_order=90,
                )
            )


# ---------------------------------------------------------------------------
# ScoreCounter — animated integer readout.
# ---------------------------------------------------------------------------


@dataclass
class ScoreCounter:
    """A numeric score display that eases toward its target value.

    Calling :meth:`set_value` starts an animation from the current
    displayed value to the new one; :meth:`build` advances the eased
    value using ``ui._dt`` each frame.

    Attributes
    ----------
    position:
        Screen-space anchor for the text.
    label:
        Optional prefix — e.g. ``"SCORE"``.
    value:
        The target value the counter animates toward.
    displayed_value:
        The currently interpolated value; ``build`` mutates this.
    animation_speed:
        Units per second the displayed value climbs toward ``value``.
        A value of ``100`` means +100 points show in 1 second.
    """

    position: tuple[float, float] = (16.0, 16.0)
    label: str = "SCORE"
    value: int = 0
    displayed_value: float = 0.0
    animation_speed: float = 200.0
    color: RGBA = _AMBER

    def set_value(self, new_value: int) -> None:
        """Kick off an animation toward *new_value*.

        The displayed value is preserved so the counter counts up (or
        down) smoothly instead of snapping.
        """
        self.value = int(new_value)

    def is_animating(self) -> bool:
        """True while ``displayed_value`` has not yet reached ``value``."""
        return abs(float(self.value) - float(self.displayed_value)) > 0.5

    def build(self, ui: "ImmediateUI") -> None:
        dt = float(getattr(ui, "_dt", 0.0))
        target = float(self.value)
        current = float(self.displayed_value)
        speed = max(1.0, float(self.animation_speed))

        step = speed * dt
        if target > current:
            current = min(target, current + step)
        elif target < current:
            current = max(target, current - step)
        self.displayed_value = current

        text = (
            f"{self.label}: {int(round(current))}"
            if self.label
            else f"{int(round(current))}"
        )
        ui.label(
            f"__scorecounter_{id(self):x}",
            text,
            self.position,
            color=self.color,
        )


# ---------------------------------------------------------------------------
# ObjectiveMarker — 3D world position projected to screen space.
# ---------------------------------------------------------------------------


@dataclass
class ObjectiveMarker:
    """A quest / waypoint marker that follows a 3D world position.

    The widget takes the camera's view + projection matrices at build
    time to project the objective's world position into screen space.
    When the objective is off-screen the marker clamps to the viewport
    edge and points inward — mirroring the affordance from most modern
    open-world HUDs.

    Attributes
    ----------
    world_pos:
        Objective's world-space position ``(x, y, z)``.
    viewport_size:
        Screen size in pixels ``(w, h)``.
    view_matrix, projection_matrix:
        4x4 column-major matrices from :class:`Camera3D`. Callers set
        these each frame before :meth:`build`.
    icon_size:
        Marker footprint in pixels.
    label:
        Optional text drawn next to the marker when on-screen.
    color:
        Marker ink colour.
    """

    world_pos: tuple[float, float, float] = (0.0, 0.0, 0.0)
    viewport_size: tuple[int, int] = (1280, 720)
    view_matrix: object = None   # np.ndarray | None; typed loose to keep hud_kit_extra numpy-free at import
    projection_matrix: object = None
    icon_size: float = 16.0
    label: str = ""
    color: RGBA = _CYAN

    _last_screen_pos: tuple[float, float] = (0.0, 0.0)
    _last_on_screen: bool = True

    def project(self) -> tuple[tuple[float, float], bool]:
        """Project ``world_pos`` to screen space.

        Returns
        -------
        A ``((sx, sy), on_screen)`` tuple. When ``on_screen`` is False,
        ``(sx, sy)`` is clamped to the viewport edge along the projected
        direction so the caller can draw an off-screen indicator.
        """
        import numpy as np  # local import — keeps module cheap to load

        vw, vh = self.viewport_size
        cx, cy = vw * 0.5, vh * 0.5

        if self.view_matrix is None or self.projection_matrix is None:
            # No camera set → sit in the middle so the widget always
            # produces a sensible screen coordinate.
            return ((cx, cy), True)

        view = np.asarray(self.view_matrix, dtype=np.float32)
        proj = np.asarray(self.projection_matrix, dtype=np.float32)
        wp = np.array(
            [self.world_pos[0], self.world_pos[1], self.world_pos[2], 1.0],
            dtype=np.float32,
        )
        clip = proj @ (view @ wp)
        # w-divide → NDC; if the objective is behind the camera the
        # clip.w flips sign and NDC.x/y flip too, which we treat as
        # off-screen.
        w = float(clip[3])
        if abs(w) < 1e-6:
            return ((cx, cy), False)
        ndc_x = float(clip[0]) / w
        ndc_y = float(clip[1]) / w
        behind = w < 0.0

        sx = (ndc_x * 0.5 + 0.5) * vw
        sy = (1.0 - (ndc_y * 0.5 + 0.5)) * vh

        on_screen = (
            not behind
            and 0.0 <= sx <= float(vw)
            and 0.0 <= sy <= float(vh)
        )

        if not on_screen:
            # Off-screen: clamp along the ray from the viewport centre
            # toward the projected point (flip direction when behind).
            dx, dy = sx - cx, sy - cy
            if behind:
                dx, dy = -dx, -dy
            length = math.hypot(dx, dy)
            if length < 1e-6:
                return ((cx, cy), False)
            # Scale the direction so it just touches the viewport edge.
            margin = float(self.icon_size)
            half_w = max(1.0, cx - margin)
            half_h = max(1.0, cy - margin)
            scale_x = half_w / abs(dx) if dx != 0.0 else float("inf")
            scale_y = half_h / abs(dy) if dy != 0.0 else float("inf")
            scale = min(scale_x, scale_y)
            sx = cx + dx * scale
            sy = cy + dy * scale

        return ((sx, sy), on_screen)

    def build(self, ui: "ImmediateUI") -> None:
        (sx, sy), on_screen = self.project()
        self._last_screen_pos = (sx, sy)
        self._last_on_screen = on_screen

        s = float(self.icon_size)
        half = s * 0.5
        # Filled square (or diamond, when off-screen we tint alpha).
        col = self.color if on_screen else (
            self.color[0], self.color[1], self.color[2], self.color[3] * 0.7
        )
        ui._commands.append(
            DrawCommand(
                kind="rect",
                position=(sx - half, sy - half),
                size=(s, s),
                color=col,
                z_order=95,
            )
        )
        # Optional label — only when on-screen; off-screen markers are
        # too transient to read.
        if self.label and on_screen:
            ui.label(
                f"__objmarker_{id(self):x}",
                self.label,
                (sx + half + 4.0, sy - half),
                color=col,
            )


__all__ = [
    "Crosshair",
    "ObjectiveMarker",
    "ScoreCounter",
]
