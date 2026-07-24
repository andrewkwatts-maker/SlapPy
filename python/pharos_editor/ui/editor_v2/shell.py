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

Split ratios ported verbatim from Nova3D. Real panel bodies live in
:mod:`pharos_editor.ui.editor_v2.panels`; the shell just owns the
DockingParams scaffold + menu / status bar + theme hook.
"""
from __future__ import annotations

from typing import Any

from imgui_bundle import hello_imgui, imgui

from pharos_editor.ui.editor_v2.theme_bridge import apply_theme_to_imgui
from pharos_editor.ui.editor_v2.panels import (
    ConsolePanel,
    ContentBrowserPanel,
    HierarchyPanel,
    PropertiesPanel,
    ViewportPanel,
)


def _active_theme_name() -> str | None:
    """Read the same ThemeCatalog v1 uses so v2 boots into the user's theme."""
    try:
        from pharos_editor.themes import ThemeCatalog

        return ThemeCatalog().default().name
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Docking split scaffold — mirrors Nova3D BuildDefaultLayout ratios
# ---------------------------------------------------------------------------

def _make_docking_splits() -> list[hello_imgui.DockingSplit]:
    splits: list[hello_imgui.DockingSplit] = []

    s = hello_imgui.DockingSplit()
    s.initial_dock = "MainDockSpace"
    s.new_dock = "LeftColumn"
    s.direction = imgui.Dir.left
    s.ratio = 0.18
    splits.append(s)

    s = hello_imgui.DockingSplit()
    s.initial_dock = "LeftColumn"
    s.new_dock = "LeftBottom"
    s.direction = imgui.Dir.down
    s.ratio = 0.45
    splits.append(s)

    s = hello_imgui.DockingSplit()
    s.initial_dock = "MainDockSpace"
    s.new_dock = "Bottom"
    s.direction = imgui.Dir.down
    s.ratio = 0.28
    splits.append(s)

    s = hello_imgui.DockingSplit()
    s.initial_dock = "Bottom"
    s.new_dock = "BottomRight"
    s.direction = imgui.Dir.right
    s.ratio = 0.35
    splits.append(s)

    return splits


# ---------------------------------------------------------------------------
# Menu bar — wired to ToolRouter when possible; graceful stubs otherwise
# ---------------------------------------------------------------------------

class _MenuBar:
    """Builds the top menu strip; dispatches leaf clicks through ToolRouter."""

    def __init__(self, engine: Any, hierarchy: HierarchyPanel) -> None:
        self._engine = engine
        self._hierarchy = hierarchy
        self._router: Any = None
        try:
            from pharos_editor.tool_router import REGISTRY

            self._router = REGISTRY
        except Exception:
            self._router = None

    def _dispatch(self, action_id: str) -> None:
        """Send an action through ToolRouter with a minimal editor context."""
        if self._router is None:
            self._toast(f"[stub] {action_id} — ToolRouter not loaded")
            return
        ctx = {
            "engine": self._engine,
            "selected_id": self._hierarchy._selected,
            "editor": "v2",
        }
        try:
            self._router.dispatch(action_id, ctx)
        except NotImplementedError as exc:
            self._toast(f"[not-impl] {action_id}: {exc}")
        except KeyError:
            self._toast(f"[unknown] {action_id}")
        except Exception as exc:  # noqa: broad — menu clicks must never crash the shell
            self._toast(f"[error] {action_id}: {exc}")

    def _toast(self, message: str) -> None:
        """Emit an info-level telemetry event; the Console panel picks it up."""
        try:
            from pharos_engine.telemetry import emit

            emit("editor.v2.menu", message=message, level="info")
        except Exception:
            pass

    def show(self) -> None:
        if imgui.begin_menu("File"):
            if imgui.menu_item_simple("New Scene"):
                self._dispatch("scene.new")
            if imgui.menu_item_simple("Open Scene…"):
                self._dispatch("scene.open")
            imgui.separator()
            if imgui.menu_item_simple("Save", "Ctrl+S"):
                self._dispatch("scene.save")
            if imgui.menu_item_simple("Save As…", "Ctrl+Shift+S"):
                self._dispatch("scene.save_as")
            imgui.separator()
            if imgui.menu_item_simple("Exit"):
                hello_imgui.get_runner_params().app_shall_exit = True
            imgui.end_menu()

        if imgui.begin_menu("Edit"):
            if imgui.menu_item_simple("Undo", "Ctrl+Z"):
                self._dispatch("edit.undo")
            if imgui.menu_item_simple("Redo", "Ctrl+Shift+Z"):
                self._dispatch("edit.redo")
            imgui.separator()
            if imgui.menu_item_simple("Cut", "Ctrl+X"):
                self._dispatch("edit.cut")
            if imgui.menu_item_simple("Copy", "Ctrl+C"):
                self._dispatch("edit.copy")
            if imgui.menu_item_simple("Paste", "Ctrl+V"):
                self._dispatch("edit.paste")
            if imgui.menu_item_simple("Duplicate", "Ctrl+D"):
                self._dispatch("edit.duplicate")
            if imgui.menu_item_simple("Delete", "Del"):
                self._dispatch("edit.delete")
            imgui.end_menu()

        if imgui.begin_menu("View"):
            if imgui.menu_item_simple("Reset Layout"):
                params = hello_imgui.get_runner_params()
                params.docking_params.layout_reset = True
            imgui.end_menu()

        if imgui.begin_menu("GameObject"):
            if imgui.menu_item_simple("Create Empty"):
                self._hierarchy._spawn_default_entity()
            imgui.end_menu()

        if imgui.begin_menu("Component"):
            if imgui.menu_item_simple("Add Component…"):
                self._dispatch("component.add")
            imgui.end_menu()

        if imgui.begin_menu("AI"):
            if imgui.menu_item_simple("Ollama Manager"):
                self._dispatch("ai.ollama_manager")
            imgui.end_menu()

        if imgui.begin_menu("Window"):
            # Toggle panel visibility via DockingParams.dockable_windows.
            params = hello_imgui.get_runner_params()
            for w in params.docking_params.dockable_windows:
                clicked, new_visible = imgui.menu_item(w.label, "", w.is_visible)
                if clicked:
                    w.is_visible = new_visible
            imgui.end_menu()

        if imgui.begin_menu("Build"):
            if imgui.menu_item_simple("Build Settings…"):
                self._dispatch("build.settings")
            imgui.end_menu()

        if imgui.begin_menu("Help"):
            if imgui.menu_item_simple("Documentation"):
                self._dispatch("help.docs")
            if imgui.menu_item_simple("About"):
                self._dispatch("help.about")
            imgui.end_menu()


# ---------------------------------------------------------------------------
# Status bar — selection, tool, coord space, FPS, ready badge
# ---------------------------------------------------------------------------

class _StatusBar:
    def __init__(self, hierarchy: HierarchyPanel) -> None:
        self._hierarchy = hierarchy

    def show(self) -> None:
        ent = self._hierarchy.selected_entity()
        sel_text = getattr(ent, "name", None) if ent else None
        imgui.text(sel_text if sel_text else "No selection")
        imgui.same_line()
        imgui.text_disabled(" | Translate | World")

        # Right-align FPS + Ready badge.
        io = imgui.get_io()
        fps_text = f"{io.framerate:>5.0f} FPS"
        ready_text = "  Ready  "
        rw = imgui.calc_text_size(fps_text).x + imgui.calc_text_size(ready_text).x + 30
        imgui.same_line(imgui.get_window_width() - rw)
        accent = imgui.ImVec4(0.31, 0.81, 0.69, 1.0)
        imgui.text_colored(accent, fps_text)
        imgui.same_line()
        imgui.text_colored(accent, ready_text)


# ---------------------------------------------------------------------------
# Assemble RunnerParams
# ---------------------------------------------------------------------------

def build_runner_params(engine: Any | None = None) -> hello_imgui.RunnerParams:
    """Assemble the Hello ImGui RunnerParams for the v2 editor.

    Parameters
    ----------
    engine:
        Optional preconstructed pharos_engine.Engine. When ``None``,
        the shell constructs its own Engine so smoke tests can boot v2
        without wiring an outer app.
    """
    if engine is None:
        try:
            from pharos_engine import Engine

            engine = Engine()
        except Exception:
            engine = None

    # Panel state objects — one instance each, kept alive across frames.
    hierarchy = HierarchyPanel(engine)
    properties = PropertiesPanel(hierarchy)
    viewport = ViewportPanel()
    content_browser = ContentBrowserPanel()
    console = ConsolePanel()
    menu = _MenuBar(engine, hierarchy)
    status = _StatusBar(hierarchy)

    params = hello_imgui.RunnerParams()
    params.app_window_params.window_title = "Pharos Editor v2"
    params.app_window_params.window_geometry.size = (1400, 900)
    params.imgui_window_params.default_imgui_window_type = (
        hello_imgui.DefaultImGuiWindowType.provide_full_screen_dock_space
    )
    params.imgui_window_params.enable_viewports = True
    params.imgui_window_params.show_menu_bar = True
    params.imgui_window_params.show_status_bar = True
    params.callbacks.show_menus = menu.show
    params.callbacks.show_status = status.show

    windows: list[hello_imgui.DockableWindow] = []
    for label, dock, body in [
        ("Hierarchy",       "LeftColumn",    hierarchy.gui),
        ("Properties",      "LeftBottom",    properties.gui),
        ("Viewport",        "MainDockSpace", viewport.gui),
        ("Content Browser", "Bottom",        content_browser.gui),
        ("Console",         "BottomRight",   console.gui),
    ]:
        w = hello_imgui.DockableWindow()
        w.label = label
        w.dock_space_name = dock
        w.gui_function = body
        w.is_visible = True
        w.can_be_closed = True
        windows.append(w)

    params.docking_params = hello_imgui.DockingParams()
    params.docking_params.dockable_windows = windows
    params.docking_params.docking_splits = _make_docking_splits()
    params.docking_params.layout_name = "Default"

    _initial_theme = _active_theme_name()

    def _post_init() -> None:
        apply_theme_to_imgui(_initial_theme)

    params.callbacks.post_init = _post_init

    return params


def run() -> None:
    """Boot the v2 editor. Blocks until the user closes the window."""
    params = build_runner_params()
    hello_imgui.run(params)
