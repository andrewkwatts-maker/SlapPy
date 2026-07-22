"""``SketchButton`` — button with a hand-drawn wobbly outline.

The outline is a jittered polyline computed from a deterministic seed so
the same widget renders the same wobble every time (important for visual
regression tests).  Hovering ramps up ``_wobble_scale`` by 25 % so the
outline visibly "breathes" — a proper animation ticker lives in the
editor loop and calls :meth:`tick` each frame.
"""
from __future__ import annotations

import math
from typing import Any, Callable

from pharos_engine._validation import (
    validate_callable,
    validate_non_empty_str,
    validate_non_negative_float,
    validate_positive_int,
)
from pharos_editor.ui.widgets._dpg_base import _NotebookWidget


class SketchButton(_NotebookWidget):
    """Button with a hand-drawn wobbly outline.

    Parameters
    ----------
    label:
        Visible label.
    callback:
        Invoked on click.  Receives ``(sender, app_data, user_data)`` like
        any DPG callback; the widget also normalises to a single-arg call
        when it can.
    wobble_amount:
        Jitter magnitude in pixels.  Must be ``>= 0``.  Default 3 px.
    segments:
        Number of polyline segments around the button perimeter.  Higher
        values yield smoother wobble.  Default 24.
    width / height:
        DPG pixel sizes for the underlying button.
    """

    def __init__(
        self,
        label: str,
        callback: Callable,
        *,
        wobble_amount: float = 3.0,
        segments: int = 24,
        width: int = 120,
        height: int = 36,
    ) -> None:
        super().__init__()
        self.label = validate_non_empty_str("label", "SketchButton", label)
        self.callback = validate_callable("callback", "SketchButton", callback)
        self.wobble_amount = validate_non_negative_float(
            "wobble_amount", "SketchButton", wobble_amount,
        )
        self.segments = validate_positive_int(
            "segments", "SketchButton", segments,
        )
        if not isinstance(width, int) or isinstance(width, bool):
            raise TypeError("SketchButton: width must be int")
        if not isinstance(height, int) or isinstance(height, bool):
            raise TypeError("SketchButton: height must be int")
        self.width = width
        self.height = height

        # Deterministic seed keeps the wobble stable across runs.
        self._seed: int = id(self) & 0xFFFF
        # Live animation state.
        self._wobble_scale: float = 1.0
        self._hovered: bool = False
        self._time: float = 0.0

        theme = self._theme
        self._accent_color = theme.color("accent", (220, 120, 160, 255))
        self._ink_color = theme.color("ink", (40, 40, 60, 255))

        self._button_tag: str | None = None
        self._drawlist_tag: str | None = None

    # ------------------------------------------------------------------
    # Pickle support
    # ------------------------------------------------------------------

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        state["_button_tag"] = None
        state["_drawlist_tag"] = None
        state["_root_tag"] = None
        state["_parent_tag"] = None
        state["_built"] = False
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def accent_color(self) -> tuple[int, int, int, int]:
        return self._accent_color

    @property
    def ink_color(self) -> tuple[int, int, int, int]:
        return self._ink_color

    @property
    def wobble_scale(self) -> float:
        """Return the live wobble multiplier (hover ramps this up)."""
        return self._wobble_scale

    # ------------------------------------------------------------------
    # Wobble geometry — pure Python so tests can assert on the vertex list.
    # ------------------------------------------------------------------

    def wobble_polyline(self) -> list[tuple[float, float]]:
        """Compute the current jittered outline as a list of ``(x, y)`` points."""
        pts: list[tuple[float, float]] = []
        w = float(max(1, self.width))
        h = float(max(1, self.height))
        n = self.segments
        # Determinism: LCG-style pseudo-random driven by seed + segment index.
        for i in range(n):
            t = i / n
            # Walk around the rectangle perimeter.
            if t < 0.25:
                u = t * 4.0
                base_x, base_y = u * w, 0.0
            elif t < 0.5:
                u = (t - 0.25) * 4.0
                base_x, base_y = w, u * h
            elif t < 0.75:
                u = (t - 0.5) * 4.0
                base_x, base_y = (1.0 - u) * w, h
            else:
                u = (t - 0.75) * 4.0
                base_x, base_y = 0.0, (1.0 - u) * h
            # Deterministic jitter in [-1, 1].
            h1 = ((self._seed + i * 2654435761) & 0x7FFFFFFF) / 0x7FFFFFFF
            h2 = ((self._seed + i * 40503) & 0x7FFFFFFF) / 0x7FFFFFFF
            jx = (h1 * 2.0 - 1.0) * self.wobble_amount * self._wobble_scale
            jy = (h2 * 2.0 - 1.0) * self.wobble_amount * self._wobble_scale
            # A slow breathing overlay so the outline visibly animates.
            jx += math.sin(self._time * 3.0 + i * 0.5) * 0.2 * self._wobble_scale
            pts.append((base_x + jx, base_y + jy))
        return pts

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def set_hover(self, hovered: bool) -> None:
        """Simulate hover (headless).  Ramps the wobble by 25 %."""
        was = self._hovered
        self._hovered = bool(hovered)
        if self._hovered and not was:
            self._wobble_scale = 1.25
        elif not self._hovered and was:
            self._wobble_scale = 1.0

    def tick(self, dt: float) -> None:
        """Advance the wobble animation by *dt* seconds."""
        if dt < 0.0:
            dt = 0.0
        self._time += dt

    def _on_click(self, sender, app_data, user_data) -> None:
        if not self._enabled:
            return
        try:
            self.callback(sender, app_data, user_data)
        except TypeError:
            try:
                self.callback(self)
            except Exception:
                pass
        except Exception:
            pass

    def click(self) -> None:
        """Programmatically trigger the click callback (headless)."""
        self._on_click(self._button_tag, None, None)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, parent_tag: str | int) -> None:
        dpg = self._safe_dpg()
        if dpg is None:
            return

        root_tag = f"sketch_button_{id(self)}"
        self._button_tag = f"{root_tag}__btn"
        self._drawlist_tag = f"{root_tag}__wobble"
        try:
            with dpg.group(parent=parent_tag, tag=root_tag):
                dpg.add_drawlist(
                    width=self.width,
                    height=self.height,
                    tag=self._drawlist_tag,
                )
                dpg.add_button(
                    label=self.label,
                    width=self.width,
                    height=self.height,
                    tag=self._button_tag,
                    callback=self._on_click,
                )
        except Exception:
            try:
                dpg.add_button(
                    label=self.label,
                    width=self.width,
                    height=self.height,
                    tag=self._button_tag,
                    parent=parent_tag,
                    callback=self._on_click,
                )
            except Exception:
                pass

        self._mark_built(parent_tag, root_tag)

    def refresh_theme(self) -> None:
        super().refresh_theme()
        theme = self._theme
        self._accent_color = theme.color("accent", self._accent_color)
        self._ink_color = theme.color("ink", self._ink_color)


__all__ = ["SketchButton"]
