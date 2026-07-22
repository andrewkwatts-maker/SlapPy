"""Legacy Nova3D reference. The shipping editor uses notebook_* siblings — see docs/ui_pattern_audit_2026_06_03.md."""
from __future__ import annotations

from typing import Callable


class EditorToolbar:
    """Horizontal toolbar strip: tool mode buttons + snapping toggle.

    Panel protocol
    --------------
    Implements ``build(parent_tag: str | int) -> None`` so it can be embedded
    inside any DPG container.

    Usage::

        toolbar = EditorToolbar()
        toolbar.set_on_tool_change(lambda t: print("tool:", t))
        toolbar.build("toolbar_window")
    """

    TOOL_SELECT    = "select"
    TOOL_TRANSLATE = "translate"
    TOOL_ROTATE    = "rotate"
    TOOL_SCALE     = "scale"

    _TOOLS = [
        (TOOL_SELECT,    "[S]", "Select"),
        (TOOL_TRANSLATE, "[T]", "Move"),
        (TOOL_ROTATE,    "[R]", "Rotate"),
        (TOOL_SCALE,     "[Sc]", "Scale"),
    ]

    _BTN_W = 80
    _BTN_H = 28

    def __init__(self) -> None:
        self.active_tool: str = self.TOOL_SELECT
        self.snap_enabled: bool = False
        self._on_tool_change: Callable[[str], None] | None = None
        self._on_mode_change: Callable[[str], None] | None = None

        self._mode: str = "2D"

        # Maps tool_name -> DPG button tag (assigned during build)
        self._btn_tags: dict[str, str] = {}
        self._snap_tag: str = "toolbar_snap_btn"

        # Mode toggle button tags
        self._mode_2d_tag: str = "tb_mode_2d"
        self._mode_3d_tag: str = "tb_mode_3d"

        # Per-item themes (created lazily in build after context exists)
        self._accent_theme: int | None = None
        self._default_theme: int | None = None
        self._snap_active_theme: int | None = None
        self._mode_active_theme: int | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_on_tool_change(self, cb: Callable[[str], None]) -> None:
        """Register a callback invoked whenever the active tool changes."""
        self._on_tool_change = cb

    def set_on_mode_change(self, cb: Callable[[str], None]) -> None:
        """Register a callback invoked whenever the 2D/3D mode changes."""
        self._on_mode_change = cb

    def get_active_tool(self) -> str:
        """Return the currently active tool name constant."""
        return self.active_tool

    @property
    def mode(self) -> str:
        """Return the current editor mode (``"2D"`` or ``"3D"``)."""
        return self._mode

    # ------------------------------------------------------------------
    # Panel protocol
    # ------------------------------------------------------------------

    def build(self, parent_tag: str | int) -> None:
        """Draw a horizontal toolbar inside *parent_tag*."""
        import dearpygui.dearpygui as dpg
        from pharos_engine.ui.editor.theme import get_accent_button_theme, get_default_button_theme

        self._accent_theme  = get_accent_button_theme()
        self._default_theme = get_default_button_theme()

        # Snap button uses a success-green highlight
        with dpg.theme() as snap_active_t:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button,        [77, 191, 102, 255])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, [100, 210, 125, 255])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive,  [77, 191, 102, 255])
                dpg.add_theme_color(dpg.mvThemeCol_Text,          [26, 26, 31, 255])
        self._snap_active_theme = snap_active_t

        # Mode toggle buttons use a distinct blue highlight
        with dpg.theme() as mode_active_t:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button,        [80, 160, 255, 255])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, [110, 185, 255, 255])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive,  [80, 160, 255, 255])
                dpg.add_theme_color(dpg.mvThemeCol_Text,          [26, 26, 31, 255])
        self._mode_active_theme = mode_active_t

        with dpg.group(horizontal=True, parent=parent_tag):
            # Tool buttons
            for tool_name, prefix, label in self._TOOLS:
                tag = f"toolbar_btn_{tool_name}"
                self._btn_tags[tool_name] = tag
                btn_label = f"{prefix} {label}"
                dpg.add_button(
                    label=btn_label,
                    tag=tag,
                    width=self._BTN_W,
                    height=self._BTN_H,
                    callback=lambda s, a, u=tool_name: self._select_tool(u),
                )

            # Separator spacer
            dpg.add_text("  |  ")

            # Snap toggle
            snap_label = "[Snap] ON" if self.snap_enabled else "[Snap] OFF"
            dpg.add_button(
                label=snap_label,
                tag=self._snap_tag,
                width=90,
                height=self._BTN_H,
                callback=self._toggle_snap,
            )

            # Separator spacer before mode toggle group
            dpg.add_text("  |  ")

            # Mode toggle group (right side)
            dpg.add_button(
                label="2D",
                tag=self._mode_2d_tag,
                width=40,
                height=self._BTN_H,
                callback=lambda: self._set_mode("2D"),
            )
            dpg.add_button(
                label="3D",
                tag=self._mode_3d_tag,
                width=40,
                height=self._BTN_H,
                callback=lambda: self._set_mode("3D"),
            )

        # Apply initial highlights
        self._update_button_highlights()
        self._update_mode_highlights()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _select_tool(self, tool: str) -> None:
        """Switch the active tool and refresh button highlights."""
        self.active_tool = tool
        self._update_button_highlights()
        if self._on_tool_change is not None:
            self._on_tool_change(tool)

    def _toggle_snap(self) -> None:
        """Toggle snap mode on/off."""
        import dearpygui.dearpygui as dpg

        self.snap_enabled = not self.snap_enabled
        label = "[Snap] ON" if self.snap_enabled else "[Snap] OFF"
        dpg.configure_item(self._snap_tag, label=label)

        if self._snap_active_theme is not None and self._default_theme is not None:
            theme = self._snap_active_theme if self.snap_enabled else self._default_theme
            dpg.bind_item_theme(self._snap_tag, theme)

    def _update_button_highlights(self) -> None:
        """Apply or remove the accent theme on each tool button."""
        import dearpygui.dearpygui as dpg

        if self._accent_theme is None or self._default_theme is None:
            return  # build() not yet called

        for tool_name, tag in self._btn_tags.items():
            if not dpg.does_item_exist(tag):
                continue
            theme = self._accent_theme if tool_name == self.active_tool else self._default_theme
            dpg.bind_item_theme(tag, theme)

    def _set_mode(self, mode: str) -> None:
        """Switch the editor between 2D and 3D mode and refresh highlights."""
        self._mode = mode
        self._update_mode_highlights()
        if self._on_mode_change is not None:
            self._on_mode_change(mode)

    def _update_mode_highlights(self) -> None:
        """Apply or remove the mode-active theme on the 2D/3D toggle buttons."""
        import dearpygui.dearpygui as dpg

        if self._mode_active_theme is None or self._default_theme is None:
            return  # build() not yet called

        for tag, label_mode in (
            (self._mode_2d_tag, "2D"),
            (self._mode_3d_tag, "3D"),
        ):
            if not dpg.does_item_exist(tag):
                continue
            theme = self._mode_active_theme if label_mode == self._mode else self._default_theme
            dpg.bind_item_theme(tag, theme)
