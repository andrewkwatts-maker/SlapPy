"""Top-right FPS + Ready badge HUD for the v2 editor.

Nova3D shows a persistent perf readout in the upper-right corner
outside the panel dockspace (243 FPS + green ``Ready`` badge). This
module reproduces that via a non-interactive borderless imgui window
positioned via a `Cond_.always` set_next_window_pos each frame so it
tracks viewport resizes.
"""
from __future__ import annotations

from imgui_bundle import imgui


class PerfHud:
    """Small overlay window pinned to the top-right of the viewport."""

    PADDING: int = 12
    WIDTH: int = 128
    HEIGHT: int = 46

    def __init__(self) -> None:
        self._badge_state: str = "Ready"

    def set_badge(self, state: str) -> None:
        """Flip the badge text (e.g. 'Compiling…' during a shader rebuild)."""
        self._badge_state = state

    def show(self) -> None:
        """Render the HUD. Call once per frame from ``callbacks.show_gui``."""
        io = imgui.get_io()
        fps = io.framerate
        # Colour-code the FPS: green >= 60, yellow 30-60, red < 30.
        if fps >= 60:
            fps_col = imgui.ImVec4(0.31, 0.81, 0.69, 1.0)
        elif fps >= 30:
            fps_col = imgui.ImVec4(0.95, 0.75, 0.20, 1.0)
        else:
            fps_col = imgui.ImVec4(0.95, 0.35, 0.30, 1.0)

        vp = imgui.get_main_viewport()
        pos = imgui.ImVec2(
            vp.work_pos.x + vp.work_size.x - self.WIDTH - self.PADDING,
            vp.work_pos.y + self.PADDING,
        )
        imgui.set_next_window_pos(pos, imgui.Cond_.always)
        imgui.set_next_window_size(imgui.ImVec2(self.WIDTH, self.HEIGHT), imgui.Cond_.always)
        imgui.set_next_window_bg_alpha(0.55)
        flags = (
            imgui.WindowFlags_.no_decoration
            | imgui.WindowFlags_.no_move
            | imgui.WindowFlags_.no_docking
            | imgui.WindowFlags_.no_focus_on_appearing
            | imgui.WindowFlags_.no_nav
            | imgui.WindowFlags_.no_saved_settings
            | imgui.WindowFlags_.always_auto_resize
        )
        if imgui.begin("##perf_hud", None, flags):
            imgui.text_colored(fps_col, f"{fps:>5.0f} FPS")
            badge_col = (
                imgui.ImVec4(0.31, 0.81, 0.69, 1.0)
                if self._badge_state == "Ready"
                else imgui.ImVec4(0.95, 0.75, 0.20, 1.0)
            )
            imgui.text_colored(badge_col, self._badge_state)
        imgui.end()
