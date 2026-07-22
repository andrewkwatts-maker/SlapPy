"""``RibbonTab`` — vertical tab with a hand-drawn ribbon extending past the panel edge.

The tab is a small labelled selectable that sits along the left edge of a
notebook panel; a decorative ribbon strip visually extends past the
container edge so multiple ribbons look "layered".  The widget owns the
selectable / hoverable / disabled tri-state; a concrete theme paints the
ribbon texture via ``palette["accent"]`` + ``palette["ink"]``.

Emitted callbacks:

* ``on_click`` — fired when the tab is selected.
* ``on_change`` — fired when the selected / disabled state changes.
"""
from __future__ import annotations

from typing import Any, Callable

from pharos_engine._validation import (
    validate_bool,
    validate_non_empty_str,
    validate_positive_int,
)
from pharos_editor.ui.widgets._dpg_base import _NotebookWidget


class RibbonTab(_NotebookWidget):
    """Vertical selectable tab with a ribbon extension.

    Parameters
    ----------
    label:
        Visible label.
    selected:
        Initial selected state.  ``False`` by default.
    on_click:
        Optional callback invoked when the tab is selected.  Receives the
        widget itself.
    on_change:
        Optional callback invoked when either ``selected`` or ``enabled``
        toggles.  Receives ``(selected: bool, enabled: bool)``.
    ribbon_length_px:
        How far the ribbon extends past the panel edge (default 24 px).
    """

    def __init__(
        self,
        label: str,
        *,
        selected: bool = False,
        on_click: Callable | None = None,
        on_change: Callable | None = None,
        ribbon_length_px: int = 24,
    ) -> None:
        super().__init__()
        self.label = validate_non_empty_str("label", "RibbonTab", label)
        self.selected = validate_bool("selected", "RibbonTab", selected)
        self.ribbon_length_px = validate_positive_int(
            "ribbon_length_px", "RibbonTab", ribbon_length_px,
        )
        # Callbacks are optional so headless tests can construct with None.
        if on_click is not None and not callable(on_click):
            raise TypeError(
                f"RibbonTab: on_click must be callable or None; "
                f"got {type(on_click).__name__}"
            )
        if on_change is not None and not callable(on_change):
            raise TypeError(
                f"RibbonTab: on_change must be callable or None; "
                f"got {type(on_change).__name__}"
            )
        self.on_click: Callable | None = on_click
        self.on_change: Callable | None = on_change

        self._hovered: bool = False

        theme = self._theme
        self._accent_color = theme.color("accent", (220, 120, 160, 255))
        self._ink_color = theme.color("ink", (40, 40, 60, 255))
        self._paper_color = theme.color("paper", (250, 246, 235, 255))
        self._nine_slice = theme.nine_slice_path("ribbon_tab")

        self._selectable_tag: str | None = None
        self._ribbon_tag: str | None = None

    # ------------------------------------------------------------------
    # Pickle support
    # ------------------------------------------------------------------

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        state["_selectable_tag"] = None
        state["_ribbon_tag"] = None
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
    def paper_color(self) -> tuple[int, int, int, int]:
        return self._paper_color

    @property
    def nine_slice_path(self) -> str:
        return self._nine_slice

    @property
    def hovered(self) -> bool:
        return self._hovered

    @property
    def state(self) -> str:
        """Return a semantic state string: ``selected`` / ``disabled`` /
        ``hovered`` / ``idle``.
        """
        if not self._enabled:
            return "disabled"
        if self.selected:
            return "selected"
        if self._hovered:
            return "hovered"
        return "idle"

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def set_selected(self, selected: bool) -> None:
        """Programmatically toggle the selected state."""
        was = self.selected
        self.selected = validate_bool("selected", "RibbonTab.set_selected", selected)
        if self.selected != was:
            self._fire_change()

    def set_hover(self, hovered: bool) -> None:
        """Simulate hover for headless tests.  Not called by DPG."""
        self._hovered = bool(hovered)

    def _fire_click(self) -> None:
        if not self._enabled:
            return
        if not self.selected:
            self.selected = True
            self._fire_change()
        if self.on_click is not None:
            try:
                self.on_click(self)
            except Exception:
                pass

    def _fire_change(self) -> None:
        if self.on_change is not None:
            try:
                self.on_change(self.selected, self._enabled)
            except Exception:
                pass

    def set_enabled(self, enabled: bool) -> None:
        was = self._enabled
        super().set_enabled(enabled)
        if was != self._enabled:
            self._fire_change()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _on_selectable(self, sender, app_data, user_data) -> None:
        if not self._enabled:
            return
        self.selected = bool(app_data)
        self._fire_change()
        if self.on_click is not None:
            try:
                self.on_click(self)
            except Exception:
                pass

    def build(self, parent_tag: str | int) -> None:
        dpg = self._safe_dpg()
        if dpg is None:
            return

        root_tag = f"ribbon_tab_{id(self)}"
        self._selectable_tag = f"{root_tag}__sel"
        self._ribbon_tag = f"{root_tag}__ribbon"
        try:
            with dpg.group(parent=parent_tag, tag=root_tag):
                dpg.add_selectable(
                    label=self.label,
                    default_value=bool(self.selected),
                    tag=self._selectable_tag,
                    callback=self._on_selectable,
                )
                # Ribbon strip — visualised as a coloured text row so the
                # widget renders without needing a full drawlist context.
                dpg.add_text(
                    "▬" * (self.ribbon_length_px // 4 or 1),
                    color=list(self._accent_color),
                    tag=self._ribbon_tag,
                )
        except Exception:
            try:
                dpg.add_selectable(
                    label=self.label,
                    default_value=bool(self.selected),
                    parent=parent_tag,
                    tag=self._selectable_tag,
                    callback=self._on_selectable,
                )
            except Exception:
                pass

        self._mark_built(parent_tag, root_tag)

    def refresh_theme(self) -> None:
        super().refresh_theme()
        theme = self._theme
        self._accent_color = theme.color("accent", self._accent_color)
        self._ink_color = theme.color("ink", self._ink_color)
        self._paper_color = theme.color("paper", self._paper_color)
        self._nine_slice = theme.nine_slice_path("ribbon_tab")


__all__ = ["RibbonTab"]
