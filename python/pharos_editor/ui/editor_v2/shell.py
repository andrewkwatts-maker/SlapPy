"""imgui-bundle editor shell — the v2 Nova3D-parity chrome.

Mirrors :file:`H:/Github/Nova3D/engine/editor/EditorApplication.cpp`
lines 1865-1918. Panel bodies live in :mod:`panels`; shell owns the
DockingParams scaffold + menu bar + status bar + shared EditorState.
"""
from __future__ import annotations

from typing import Any

from imgui_bundle import hello_imgui, imgui

from pharos_editor.ui.editor_v2.theme_bridge import apply_theme_to_imgui
from pharos_editor.ui.editor_v2.editor_state import EditorState
from pharos_editor.ui.editor_v2.panels import (
    ConsolePanel,
    ContentBrowserPanel,
    HierarchyPanel,
    PropertiesPanel,
    ViewportPanel,
)


def _active_theme_name() -> str | None:
    try:
        from pharos_editor.themes import ThemeCatalog

        return ThemeCatalog().default().name
    except Exception:
        return None


def _all_theme_names() -> list[str]:
    try:
        from pharos_editor.themes import ThemeCatalog

        return ThemeCatalog().names()
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Docking split scaffold — Nova3D BuildDefaultLayout ratios
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
# Menu bar
# ---------------------------------------------------------------------------

class _MenuBar:
    def __init__(self, state: EditorState, hierarchy: HierarchyPanel) -> None:
        self._state = state
        self._hierarchy = hierarchy
        self._theme_pending: str | None = None
        self._router: Any = None
        try:
            from pharos_editor.tool_router import REGISTRY

            self._router = REGISTRY
        except Exception:
            self._router = None

    def _dispatch(self, action_id: str) -> None:
        if self._router is None:
            self._toast(f"[stub] {action_id}")
            return
        ctx = {
            "engine": self._state.engine,
            "selected_ids": self._state.selected_ids(),
            "editor": "v2",
        }
        try:
            self._router.dispatch(action_id, ctx)
        except NotImplementedError as exc:
            self._toast(f"[not-impl] {action_id}: {exc}")
        except KeyError:
            self._toast(f"[unknown] {action_id}")
        except Exception as exc:
            self._toast(f"[error] {action_id}: {exc}")

    def _toast(self, message: str) -> None:
        try:
            from pharos_engine.telemetry import emit

            emit("editor.v2.menu", message=message, level="info")
        except Exception:
            pass

    def show(self) -> None:
        # File
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

        # Edit
        if imgui.begin_menu("Edit"):
            cs = self._state.command_stack
            undo_label = cs.peek_undo() if cs and cs.can_undo() else None
            redo_label = cs.peek_redo() if cs and cs.can_redo() else None
            if imgui.menu_item(
                f"Undo{': ' + undo_label if undo_label else ''}", "Ctrl+Z",
                False,
            )[0]:
                if cs:
                    cs.undo()
            if imgui.menu_item(
                f"Redo{': ' + redo_label if redo_label else ''}", "Ctrl+Shift+Z",
                False,
            )[0]:
                if cs:
                    cs.redo()
            imgui.separator()
            if imgui.menu_item_simple("Cut", "Ctrl+X"):
                self._dispatch("edit.cut")
            if imgui.menu_item_simple("Copy", "Ctrl+C"):
                self._hierarchy._copy_selection()
            if imgui.menu_item_simple("Paste", "Ctrl+V"):
                self._hierarchy._paste_from_clipboard()
            if imgui.menu_item_simple("Duplicate", "Ctrl+D"):
                self._hierarchy._duplicate_selection()
            if imgui.menu_item_simple("Delete", "Del"):
                self._hierarchy._delete_selection()
            imgui.end_menu()

        # View
        if imgui.begin_menu("View"):
            if imgui.menu_item_simple("Reset Layout"):
                hello_imgui.get_runner_params().docking_params.layout_reset = True
            if imgui.begin_menu("Theme"):
                current = self._state.active_theme
                for name in _all_theme_names():
                    is_current = name == current
                    clicked, _ = imgui.menu_item(name, "", is_current)
                    if clicked and not is_current:
                        self._theme_pending = name
                imgui.end_menu()
            imgui.end_menu()

        # GameObject
        if imgui.begin_menu("GameObject"):
            if imgui.menu_item_simple("Create Empty"):
                self._hierarchy._spawn_default_entity()
            imgui.end_menu()

        # Component
        if imgui.begin_menu("Component"):
            if imgui.menu_item_simple("Add Component…"):
                self._dispatch("component.add")
            imgui.end_menu()

        # AI
        if imgui.begin_menu("AI"):
            if imgui.menu_item_simple("Ollama Manager"):
                self._dispatch("ai.ollama_manager")
            imgui.end_menu()

        # Window (dockable-window visibility)
        if imgui.begin_menu("Window"):
            params = hello_imgui.get_runner_params()
            for w in params.docking_params.dockable_windows:
                clicked, new_vis = imgui.menu_item(w.label, "", w.is_visible)
                if clicked:
                    w.is_visible = new_vis
            imgui.end_menu()

        # Build
        if imgui.begin_menu("Build"):
            if imgui.menu_item_simple("Build Settings…"):
                self._dispatch("build.settings")
            imgui.end_menu()

        # Help
        if imgui.begin_menu("Help"):
            if imgui.menu_item_simple("Documentation"):
                self._dispatch("help.docs")
            if imgui.menu_item_simple("About"):
                self._dispatch("help.about")
            imgui.end_menu()

    def consume_theme_pending(self) -> str | None:
        """One-shot getter used by the shell's per-frame theme applier."""
        t = self._theme_pending
        self._theme_pending = None
        return t


# ---------------------------------------------------------------------------
# Status bar
# ---------------------------------------------------------------------------

class _StatusBar:
    def __init__(self, state: EditorState) -> None:
        self._state = state

    def show(self) -> None:
        entities = self._state.selected_entities()
        if not entities:
            sel_text = "No selection"
        elif len(entities) == 1:
            sel_text = getattr(entities[0], "name", None) or "<unnamed>"
        else:
            sel_text = f"{len(entities)} selected"
        imgui.text(sel_text)
        imgui.same_line()
        imgui.text_disabled(" | Translate | World")

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
# Global hotkeys
# ---------------------------------------------------------------------------

def _apply_global_hotkeys(state: EditorState, hierarchy: HierarchyPanel) -> None:
    """Poll imgui input for editor-wide shortcuts once per frame."""
    io = imgui.get_io()
    if io.want_capture_keyboard:
        # When a text input is focused, don't fire chord hotkeys.
        return
    ctrl = io.key_ctrl
    shift = io.key_shift

    # Undo / redo
    if ctrl and imgui.is_key_pressed(imgui.Key.z, False):
        if state.command_stack:
            if shift:
                state.command_stack.redo()
            else:
                state.command_stack.undo()
    # Copy / paste / duplicate / delete
    if ctrl and imgui.is_key_pressed(imgui.Key.c, False):
        hierarchy._copy_selection()
    if ctrl and imgui.is_key_pressed(imgui.Key.v, False):
        hierarchy._paste_from_clipboard()
    if ctrl and imgui.is_key_pressed(imgui.Key.d, False):
        hierarchy._duplicate_selection()
    if imgui.is_key_pressed(imgui.Key.delete, False):
        hierarchy._delete_selection()
    # Frame selection
    if not ctrl and imgui.is_key_pressed(imgui.Key.f, False):
        hierarchy._frame_selection()


# ---------------------------------------------------------------------------
# Assemble RunnerParams
# ---------------------------------------------------------------------------

def build_runner_params(engine: Any | None = None) -> hello_imgui.RunnerParams:
    if engine is None:
        try:
            from pharos_engine import Engine

            engine = Engine()
        except Exception:
            engine = None

    initial_theme = _active_theme_name()
    state = EditorState.build(engine, initial_theme=initial_theme)

    hierarchy = HierarchyPanel(state)
    properties = PropertiesPanel(state)
    viewport = ViewportPanel(state)
    content_browser = ContentBrowserPanel()
    console = ConsolePanel()
    menu = _MenuBar(state, hierarchy)
    status = _StatusBar(state)

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

    # Global input + pending-theme handler runs before the panels paint.
    def _before_gui() -> None:
        # Consume any theme-pending set by the menu last frame.
        pending = menu.consume_theme_pending()
        if pending:
            apply_theme_to_imgui(pending)
            state.set_theme(pending)
        _apply_global_hotkeys(state, hierarchy)

    params.callbacks.before_imgui_render = _before_gui

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

    def _post_init() -> None:
        apply_theme_to_imgui(initial_theme)
        state.active_theme = initial_theme or ""

    params.callbacks.post_init = _post_init

    return params


def run() -> None:
    """Boot the v2 editor. Blocks until the user closes the window."""
    params = build_runner_params()
    hello_imgui.run(params)
