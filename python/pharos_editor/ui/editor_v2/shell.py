"""imgui-bundle editor shell — the v2 Nova3D-parity chrome.

Mirrors :file:`H:/Github/Nova3D/engine/editor/EditorApplication.cpp`
lines 1865-1918 (`BuildDefaultLayout` / `RenderDockSpace`). Same
5-panel layout Nova3D screenshotted:

::

    +------------+-------------------------+
    | Hierarchy  |                         |
    |            |        Viewport         |
    +------------+                         |
    | Properties |                         |
    +------------+-------------+-----------+
    | Content Browser          | Console   |
    +--------------------------+-----------+

Split ratios ported verbatim from Nova3D:
- LeftColumn = 0.18 of viewport width
- LeftColumn split: LeftBottom (Properties) = 0.45 of column height
- MainDockSpace split: Bottom = 0.28 of viewport height
- Bottom split: BottomRight (Console) = 0.35 of bottom width
"""
from __future__ import annotations

from imgui_bundle import hello_imgui, imgui


def _make_docking_splits() -> list[hello_imgui.DockingSplit]:
    """Build the four DockingSplit calls that partition MainDockSpace.

    Ports Nova3D's ``BuildDefaultLayout`` (EditorApplication.cpp:1885-1906).
    """
    splits: list[hello_imgui.DockingSplit] = []

    # Split 1: carve LeftColumn off the left 18% of MainDockSpace.
    s = hello_imgui.DockingSplit()
    s.initial_dock = "MainDockSpace"
    s.new_dock = "LeftColumn"
    s.direction = imgui.Dir.left
    s.ratio = 0.18
    splits.append(s)

    # Split 2: split LeftColumn vertically 55/45 for Hierarchy/Properties.
    s = hello_imgui.DockingSplit()
    s.initial_dock = "LeftColumn"
    s.new_dock = "LeftBottom"
    s.direction = imgui.Dir.down
    s.ratio = 0.45
    splits.append(s)

    # Split 3: carve Bottom off the bottom 28% of remaining MainDockSpace.
    s = hello_imgui.DockingSplit()
    s.initial_dock = "MainDockSpace"
    s.new_dock = "Bottom"
    s.direction = imgui.Dir.down
    s.ratio = 0.28
    splits.append(s)

    # Split 4: carve BottomRight off the right 35% of Bottom.
    s = hello_imgui.DockingSplit()
    s.initial_dock = "Bottom"
    s.new_dock = "BottomRight"
    s.direction = imgui.Dir.right
    s.ratio = 0.35
    splits.append(s)

    return splits


# ---------------------------------------------------------------------------
# Panel bodies (POC — real panels come from pharos_editor.ui.editor v1 in a
# later sprint via a compatibility adapter). For now: placeholder GUI so we
# can visually verify the DockBuilder scaffold matches Nova3D's screenshot.
# ---------------------------------------------------------------------------

def _hierarchy_body() -> None:
    imgui.text("Hierarchy")
    imgui.separator()
    imgui.text_disabled("(scene tree — Sprint 2 wires the outliner)")


def _properties_body() -> None:
    imgui.text("Properties")
    imgui.separator()
    imgui.text_disabled("No object selected")


def _viewport_body() -> None:
    imgui.text("Viewport")
    imgui.separator()
    avail = imgui.get_content_region_avail()
    dl = imgui.get_window_draw_list()
    ox, oy = imgui.get_cursor_screen_pos()
    # Draw a placeholder grid so it's clear the viewport got the centre slot.
    step = 40.0
    grid_col = imgui.get_color_u32(imgui.ImVec4(0.20, 0.22, 0.28, 1.0))
    x = 0.0
    while x < avail.x:
        dl.add_line(imgui.ImVec2(ox + x, oy), imgui.ImVec2(ox + x, oy + avail.y), grid_col)
        x += step
    y = 0.0
    while y < avail.y:
        dl.add_line(imgui.ImVec2(ox, oy + y), imgui.ImVec2(ox + avail.x, oy + y), grid_col)
        y += step
    # Placeholder axis crosshair at centre.
    cx = ox + avail.x * 0.5
    cy = oy + avail.y * 0.5
    axis_x = imgui.get_color_u32(imgui.ImVec4(0.90, 0.30, 0.30, 1.0))
    axis_z = imgui.get_color_u32(imgui.ImVec4(0.30, 0.50, 0.90, 1.0))
    dl.add_line(imgui.ImVec2(cx - 30, cy), imgui.ImVec2(cx + 30, cy), axis_x, 2.0)
    dl.add_line(imgui.ImVec2(cx, cy - 30), imgui.ImVec2(cx, cy + 30), axis_z, 2.0)


def _content_browser_body() -> None:
    imgui.text("Content Browser")
    imgui.separator()
    imgui.text_disabled("Assets/")


def _console_body() -> None:
    imgui.text("Console")
    imgui.separator()
    imgui.text_colored(imgui.ImVec4(0.31, 0.81, 0.69, 1.0), "[info] editor v2 booted (imgui-bundle)")
    imgui.text_disabled("[dbg]  telemetry bus wiring: Sprint 3")


# ---------------------------------------------------------------------------
# Menu bar — Nova3D-style 9-item top row
# ---------------------------------------------------------------------------

def _show_menu_bar() -> None:
    if imgui.begin_menu("File"):
        imgui.menu_item_simple("New Scene")
        imgui.menu_item_simple("Open Scene…")
        imgui.separator()
        imgui.menu_item_simple("Save")
        imgui.menu_item_simple("Save As…")
        imgui.separator()
        imgui.menu_item_simple("Exit")
        imgui.end_menu()
    if imgui.begin_menu("Edit"):
        imgui.menu_item_simple("Undo", "Ctrl+Z")
        imgui.menu_item_simple("Redo", "Ctrl+Shift+Z")
        imgui.separator()
        imgui.menu_item_simple("Cut", "Ctrl+X")
        imgui.menu_item_simple("Copy", "Ctrl+C")
        imgui.menu_item_simple("Paste", "Ctrl+V")
        imgui.menu_item_simple("Duplicate", "Ctrl+D")
        imgui.menu_item_simple("Delete", "Del")
        imgui.end_menu()
    if imgui.begin_menu("View"):
        imgui.menu_item_simple("Reset Layout")
        imgui.end_menu()
    if imgui.begin_menu("GameObject"):
        imgui.menu_item_simple("Create Empty")
        imgui.end_menu()
    if imgui.begin_menu("Component"):
        imgui.menu_item_simple("Add Component…")
        imgui.end_menu()
    if imgui.begin_menu("AI"):
        imgui.menu_item_simple("Ollama Manager")
        imgui.end_menu()
    if imgui.begin_menu("Window"):
        imgui.menu_item_simple("Hierarchy")
        imgui.menu_item_simple("Properties")
        imgui.menu_item_simple("Viewport")
        imgui.menu_item_simple("Content Browser")
        imgui.menu_item_simple("Console")
        imgui.end_menu()
    if imgui.begin_menu("Build"):
        imgui.menu_item_simple("Build Settings…")
        imgui.end_menu()
    if imgui.begin_menu("Help"):
        imgui.menu_item_simple("Documentation")
        imgui.menu_item_simple("About")
        imgui.end_menu()


# ---------------------------------------------------------------------------
# Status bar (bottom strip)
# ---------------------------------------------------------------------------

def _show_status_bar() -> None:
    imgui.text("No selection")
    imgui.same_line()
    imgui.text(" | Translate | World")
    # Right-align FPS + mem.
    io = imgui.get_io()
    fps_text = f"{io.framerate:>5.0f} FPS"
    tw = imgui.calc_text_size(fps_text).x
    imgui.same_line(imgui.get_window_width() - tw - 12)
    imgui.text_colored(imgui.ImVec4(0.31, 0.81, 0.69, 1.0), fps_text)


# ---------------------------------------------------------------------------
# Assemble DockingParams + RunnerParams
# ---------------------------------------------------------------------------

def build_runner_params() -> hello_imgui.RunnerParams:
    """Assemble the Hello ImGui RunnerParams for the v2 editor."""
    params = hello_imgui.RunnerParams()
    params.app_window_params.window_title = "Pharos Editor v2"
    params.app_window_params.window_geometry.size = (1400, 900)
    params.imgui_window_params.default_imgui_window_type = (
        hello_imgui.DefaultImGuiWindowType.provide_full_screen_dock_space
    )
    params.imgui_window_params.enable_viewports = True
    params.imgui_window_params.show_menu_bar = True
    params.imgui_window_params.show_status_bar = True
    params.callbacks.show_menus = _show_menu_bar
    params.callbacks.show_status = _show_status_bar

    # Build the dockable-window set.
    windows: list[hello_imgui.DockableWindow] = []
    for name, dock, body in [
        ("Hierarchy",       "LeftColumn", _hierarchy_body),
        ("Properties",      "LeftBottom", _properties_body),
        ("Viewport",        "MainDockSpace", _viewport_body),
        ("Content Browser", "Bottom",     _content_browser_body),
        ("Console",         "BottomRight", _console_body),
    ]:
        w = hello_imgui.DockableWindow()
        w.label = name
        w.dock_space_name = dock
        w.gui_function = body
        w.is_visible = True
        w.can_be_closed = True
        windows.append(w)

    params.docking_params = hello_imgui.DockingParams()
    params.docking_params.dockable_windows = windows
    params.docking_params.docking_splits = _make_docking_splits()
    params.docking_params.layout_name = "Default"

    return params


def run() -> None:
    """Boot the v2 editor. Blocks until the user closes the window."""
    params = build_runner_params()
    hello_imgui.run(params)
