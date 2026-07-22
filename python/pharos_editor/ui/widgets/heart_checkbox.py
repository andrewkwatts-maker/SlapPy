"""``HeartCheckbox`` — heart-shaped checkbox primitive."""
from __future__ import annotations

from typing import Callable

from pharos_engine._validation import (
    validate_bool,
    validate_callable,
    validate_non_empty_str,
)
from pharos_editor.ui.widgets._dpg_base import _NotebookWidget


class HeartCheckbox(_NotebookWidget):
    """Boolean checkbox that "fills the heart" when checked.

    Parameters
    ----------
    label:
        Visible label.
    value:
        Initial checked state.
    callback:
        Invoked with the new boolean value on each toggle.
    """

    def __init__(
        self,
        label: str,
        value: bool,
        callback: Callable,
    ) -> None:
        super().__init__()
        self.label = validate_non_empty_str("label", "HeartCheckbox", label)
        self.value = validate_bool("value", "HeartCheckbox", value)
        self.callback = validate_callable("callback", "HeartCheckbox", callback)

        theme = self._theme
        self._heart_color = theme.color("heart", (230, 80, 120, 255))
        self._ink_color = theme.color("ink", (40, 40, 60, 255))
        self._nine_slice = theme.nine_slice_path("heart_checkbox")

        self._value_tag: str | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def heart_color(self) -> tuple[int, int, int, int]:
        return self._heart_color

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

        root_tag = f"heart_checkbox_{id(self)}"
        self._value_tag = root_tag
        try:
            dpg.add_checkbox(
                label=self.label,
                default_value=bool(self.value),
                parent=parent_tag,
                tag=root_tag,
                callback=self._on_change,
            )
        except Exception:
            pass

        self._mark_built(parent_tag, root_tag)

    def _on_change(self, sender, app_data, user_data) -> None:
        self.value = bool(app_data)
        try:
            self.callback(self.value)
        except TypeError:
            try:
                self.callback(sender, app_data, user_data)
            except Exception:
                pass

    def toggle(self) -> bool:
        """Flip the value programmatically and fire the callback.  Returns new state."""
        self.value = not self.value
        try:
            self.callback(self.value)
        except TypeError:
            try:
                self.callback(self._value_tag, self.value, None)
            except Exception:
                pass
        return self.value

    def set_value(self, value: bool) -> None:
        """Programmatically set the checked state and fire the callback."""
        v = validate_bool("value", "HeartCheckbox.set_value", value)
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
        self._heart_color = theme.color("heart", self._heart_color)
        self._ink_color = theme.color("ink", self._ink_color)
        self._nine_slice = theme.nine_slice_path("heart_checkbox")


__all__ = ["HeartCheckbox"]
