"""``HighlighterSlider`` — slider styled as a highlighter strip."""
from __future__ import annotations

from typing import Callable

from pharos_engine._validation import (
    validate_callable,
    validate_finite_float,
    validate_non_empty_str,
)
from pharos_editor.ui.widgets._dpg_base import _NotebookWidget


class HighlighterSlider(_NotebookWidget):
    """Float slider rendered as a highlighter strip.

    Parameters
    ----------
    label:
        Visible label.
    value:
        Initial value.  Clamped to ``[min, max]``.
    min / max:
        Slider range.  ``min`` must be strictly less than ``max``.
    callback:
        Invoked with the new value when the user drags the slider.
    """

    def __init__(
        self,
        label: str,
        value: float,
        min: float,
        max: float,
        callback: Callable,
    ) -> None:
        super().__init__()
        self.label = validate_non_empty_str("label", "HighlighterSlider", label)
        self.min = validate_finite_float("min", "HighlighterSlider", min)
        self.max = validate_finite_float("max", "HighlighterSlider", max)
        if self.min >= self.max:
            raise ValueError(
                "HighlighterSlider: min must be strictly less than max; "
                f"got min={self.min!r}, max={self.max!r}"
            )
        v = validate_finite_float("value", "HighlighterSlider", value)
        # Clamp on construction so callers can't get a slider whose
        # initial value falls outside its own bounds.
        if v < self.min:
            v = self.min
        elif v > self.max:
            v = self.max
        self.value = v
        self.callback = validate_callable(
            "callback", "HighlighterSlider", callback,
        )

        theme = self._theme
        self._highlight_color = theme.color("highlight", (255, 240, 120, 200))
        self._ink_color = theme.color("ink", (40, 40, 60, 255))
        self._nine_slice = theme.nine_slice_path("highlighter_slider")

        self._value_tag: str | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def highlight_color(self) -> tuple[int, int, int, int]:
        return self._highlight_color

    @property
    def nine_slice_path(self) -> str:
        return self._nine_slice

    # ------------------------------------------------------------------
    # Build / interaction
    # ------------------------------------------------------------------

    def build(self, parent_tag: str | int) -> None:
        dpg = self._safe_dpg()
        if dpg is None:
            return

        root_tag = f"highlighter_slider_{id(self)}"
        self._value_tag = root_tag
        try:
            dpg.add_slider_float(
                label=self.label,
                default_value=float(self.value),
                min_value=float(self.min),
                max_value=float(self.max),
                parent=parent_tag,
                tag=root_tag,
                callback=self._on_change,
            )
        except Exception:
            pass

        self._mark_built(parent_tag, root_tag)

    def _on_change(self, sender, app_data, user_data) -> None:
        try:
            self.value = float(app_data)
        except (TypeError, ValueError):
            return
        try:
            self.callback(self.value)
        except TypeError:
            # Caller registered a 3-arg DPG callback — forward as-is.
            try:
                self.callback(sender, app_data, user_data)
            except Exception:
                pass

    def set_value(self, value: float) -> None:
        """Programmatically update the slider value (and fire the callback)."""
        v = validate_finite_float("value", "HighlighterSlider.set_value", value)
        if v < self.min:
            v = self.min
        elif v > self.max:
            v = self.max
        self.value = v
        try:
            self.callback(self.value)
        except TypeError:
            try:
                self.callback(self._value_tag, self.value, None)
            except Exception:
                pass

    def refresh_theme(self) -> None:
        super().refresh_theme()
        theme = self._theme
        self._highlight_color = theme.color(
            "highlight", self._highlight_color,
        )
        self._ink_color = theme.color("ink", self._ink_color)
        self._nine_slice = theme.nine_slice_path("highlighter_slider")


__all__ = ["HighlighterSlider"]
