"""``InkStampBadge`` — round badge with a slightly-off-center ink stamp look.

A small round badge that supports an icon + a text label + palette
colour theming.  The visual conceit is an "ink stamp": the badge draws
a filled circle with a slight offset over a darker rim, plus an
optional glyph rendered on top.  Colours come from the theme's
``palette`` — recognised keys are ``ink``, ``accent``, and ``paper``.
"""
from __future__ import annotations

from typing import Any, Callable

from pharos_engine._validation import (
    validate_finite_float,
    validate_non_empty_str,
    validate_str,
)
from pharos_engine.ui.widgets._dpg_base import _NotebookWidget


class InkStampBadge(_NotebookWidget):
    """Round badge decorated as an ink stamp.

    Parameters
    ----------
    label:
        Visible text.  Must be a non-empty string.
    icon:
        Optional glyph / emoji to draw above the label.  Empty string
        omits the icon.
    color_slot:
        Which palette slot to read for the stamp fill.  Default
        ``"accent"``.  Must be a known palette slot; unknown slots fall
        back to the accent colour.
    offset_px:
        Ink smear offset in pixels.  Both x and y.  Clamped to
        ``[-8, 8]``.  Default 2.
    on_click:
        Optional callback fired when the badge is clicked.  Receives the
        widget itself.
    """

    _VALID_SLOTS: frozenset[str] = frozenset(
        {"ink", "accent", "paper", "highlight", "washi", "heart"}
    )

    def __init__(
        self,
        label: str,
        *,
        icon: str = "",
        color_slot: str = "accent",
        offset_px: float = 2.0,
        on_click: Callable | None = None,
    ) -> None:
        super().__init__()
        self.label = validate_non_empty_str("label", "InkStampBadge", label)
        if not isinstance(icon, str):
            raise TypeError(
                f"InkStampBadge: icon must be str; got {type(icon).__name__}"
            )
        self.icon = icon
        slot = validate_str(
            "color_slot", "InkStampBadge", color_slot, allow_empty=False,
        )
        if slot not in self._VALID_SLOTS:
            raise ValueError(
                "InkStampBadge: color_slot must be one of "
                f"{sorted(self._VALID_SLOTS)}; got {slot!r}"
            )
        self.color_slot = slot
        off = validate_finite_float(
            "offset_px", "InkStampBadge", offset_px,
        )
        if off < -8.0:
            off = -8.0
        elif off > 8.0:
            off = 8.0
        self.offset_px = off

        if on_click is not None and not callable(on_click):
            raise TypeError(
                f"InkStampBadge: on_click must be callable or None; "
                f"got {type(on_click).__name__}"
            )
        self.on_click: Callable | None = on_click

        theme = self._theme
        self._stamp_color = theme.color(self.color_slot, (220, 120, 160, 255))
        self._ink_color = theme.color("ink", (40, 40, 60, 255))
        # Slightly darker rim for the ink-stamp look.
        self._rim_color = (
            max(0, self._stamp_color[0] - 60),
            max(0, self._stamp_color[1] - 60),
            max(0, self._stamp_color[2] - 60),
            self._stamp_color[3],
        )

        self._button_tag: str | None = None

    # ------------------------------------------------------------------
    # Pickle support
    # ------------------------------------------------------------------

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        state["_button_tag"] = None
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
    def stamp_color(self) -> tuple[int, int, int, int]:
        return self._stamp_color

    @property
    def rim_color(self) -> tuple[int, int, int, int]:
        return self._rim_color

    @property
    def ink_color(self) -> tuple[int, int, int, int]:
        return self._ink_color

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def set_color_slot(self, color_slot: str) -> None:
        """Swap which palette slot the stamp draws from."""
        slot = validate_str(
            "color_slot", "InkStampBadge.set_color_slot",
            color_slot, allow_empty=False,
        )
        if slot not in self._VALID_SLOTS:
            raise ValueError(
                "InkStampBadge.set_color_slot: color_slot must be one of "
                f"{sorted(self._VALID_SLOTS)}; got {slot!r}"
            )
        self.color_slot = slot
        self.refresh_theme()

    def click(self) -> None:
        """Programmatically fire the click callback (headless)."""
        self._on_click(self._button_tag, None, None)

    def _on_click(self, sender, app_data, user_data) -> None:
        if not self._enabled or self.on_click is None:
            return
        try:
            self.on_click(self)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, parent_tag: str | int) -> None:
        dpg = self._safe_dpg()
        if dpg is None:
            return

        root_tag = f"ink_stamp_badge_{id(self)}"
        self._button_tag = f"{root_tag}__btn"
        badge_text = f"{self.icon} {self.label}".strip()
        try:
            with dpg.group(parent=parent_tag, tag=root_tag):
                dpg.add_button(
                    label=badge_text,
                    tag=self._button_tag,
                    callback=self._on_click,
                )
        except Exception:
            try:
                dpg.add_button(
                    label=badge_text,
                    parent=parent_tag,
                    tag=self._button_tag,
                    callback=self._on_click,
                )
            except Exception:
                pass

        self._mark_built(parent_tag, root_tag)

    def refresh_theme(self) -> None:
        super().refresh_theme()
        theme = self._theme
        self._stamp_color = theme.color(self.color_slot, self._stamp_color)
        self._ink_color = theme.color("ink", self._ink_color)
        self._rim_color = (
            max(0, self._stamp_color[0] - 60),
            max(0, self._stamp_color[1] - 60),
            max(0, self._stamp_color[2] - 60),
            self._stamp_color[3],
        )


__all__ = ["InkStampBadge"]
