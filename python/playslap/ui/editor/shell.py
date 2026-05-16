from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playslap.engine import Engine
    from playslap.ui.editor.toolbar import EditorToolbar
    from playslap.ui.editor.scene_outliner import SceneOutliner
    from playslap.ui.editor.content_browser import ContentBrowser

try:
    from playslap.ui.editor.gizmo_overlay import GizmoOverlay  # noqa: F401
except ImportError:
    GizmoOverlay = None  # type: ignore[assignment,misc]

# ── Layout constants ───────────────────────────────────────────────────────────
TOOLBAR_H = 36
BOTTOM_H  = 220
LEFT_W    = 200
RIGHT_W   = 300


class EditorShell:
    """Main Dear PyGui editor shell.

    This class is part of the optional ``[editor]`` extra.  All ``dearpygui``
    imports are deferred to runtime so the rest of the engine remains
    importable without the extra installed.

    Panel protocol
    --------------
    Any object passed to :meth:`register_panel` must implement::

        def build(self, parent_tag: str | int) -> None: ...

    The method is called during :meth:`setup` with the Dear PyGui tag of the
    parent container the panel should populate.

    Layout
    ------
    A single primary window (``editor_root``) contains a vertical stack:

    1. Toolbar row (h=TOOLBAR_H, no border)
    2. Horizontal main area — left panel | center tabs | right panel
    3. Bottom content browser (h=BOTTOM_H)

    The viewport menu bar is handled by DPG (``dpg.viewport_menu_bar``).
    """

    def __init__(
        self,
        engine: "Engine",
        title: str = "SlapPyEngine Editor",
        width: int = 1400,
        height: int = 900,
    ) -> None:
        self._engine = engine
        self._title = title
        self._width = width
        self._height = height
        self._panels: list = []
        self._viewport_panel = None
        self._code_mode_panel = None
        self._toolbar: "EditorToolbar | None" = None
        self._scene_outliner: "SceneOutliner | None" = None
        self._content_browser: "ContentBrowser | None" = None
        self._gizmo_overlay = None
        self._running = False
        self._play_mode: bool = False

        # Custom title-bar drag state
        self._dragging_window: bool = False
        self._drag_start_mouse: tuple[int, int] = (0, 0)
        self._drag_start_vp: tuple[int, int] = (0, 0)

        # 2D / 3D mode state
        self._editor_mode: str = "2D"

        # Tags for 3D-only panels (may not yet exist; always guarded with does_item_exist)
        self._mesh_inspector_tag: str = "mesh_inspector_panel"
        self._layer_lighting_tag: str = "layer_lighting_panel"

    # ------------------------------------------------------------------
    # Panel registration
    # ------------------------------------------------------------------

    def register_panel(self, panel) -> None:
        """Append *panel* to the list of Details sidebar panels.

        Parameters
        ----------
        panel:
            Any object that implements ``build(parent_tag: str | int) -> None``.
        """
        self._panels.append(panel)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def setup(self) -> None:  # noqa: C901 (complexity — UI layout)
        """Initialise the Dear PyGui context and build the window layout.

        Must be called before :meth:`run`.

        Raises
        ------
        ImportError
            If ``dearpygui`` is not installed.
        """
        try:
            import dearpygui.dearpygui as dpg
        except ImportError as exc:
            raise ImportError(
                "dearpygui is required for the editor shell. "
                "Install it with: pip install playslap[editor]"
            ) from exc

        width  = self._width
        height = self._height

        # ── Auto-wire sub-components if not pre-set ────────────────────────
        if self._toolbar is None:
            from playslap.ui.editor.toolbar import EditorToolbar
            self._toolbar = EditorToolbar()

        if self._scene_outliner is None:
            from playslap.ui.editor.scene_outliner import SceneOutliner
            self._scene_outliner = SceneOutliner()

        if self._content_browser is None:
            from playslap.ui.editor.content_browser import ContentBrowser
            self._content_browser = ContentBrowser()

        # Wire content browser → code mode panel (if both present)
        if self._content_browser is not None and self._code_mode_panel is not None:
            self._content_browser.set_on_open_script(
                self._code_mode_panel.load_script
            )

        # ── DPG context + theme ────────────────────────────────────────────
        dpg.create_context()

        # ── Gizmo overlay — build drawlist after context is created ───────
        if GizmoOverlay is not None and self._gizmo_overlay is None:
            self._gizmo_overlay = GizmoOverlay()
        if self._gizmo_overlay is not None:
            self._gizmo_overlay.build()
            # Wire toolbar tool-change → gizmo mode
            if self._toolbar is not None:
                self._toolbar.set_on_tool_change(self._gizmo_overlay.set_tool)
            # Wire scene outliner selection → gizmo entity
            if self._scene_outliner is not None:
                self._scene_outliner.set_on_select(self._gizmo_overlay.set_entity)

        from playslap.ui.editor.theme import apply_editor_theme
        apply_editor_theme()

        dpg.create_viewport(
            title=self._title,
            width=width,
            height=height,
            decorated=False,            # remove OS window chrome
            clear_color=(0, 0, 0, 0),  # transparent for DWM blur-behind
        )
        dpg.setup_dearpygui()

        # ── Menu bar (handled by viewport — sits above everything) ─────────
        with dpg.viewport_menu_bar():
            with dpg.menu(label="File"):
                dpg.add_menu_item(label="Open Scene", tag="menu_open_scene")
                dpg.add_menu_item(label="Save Scene", tag="menu_save_scene")
            with dpg.menu(label="Edit"):
                dpg.add_menu_item(label="Undo", tag="menu_undo")
            with dpg.menu(label="View"):
                dpg.add_menu_item(label="Reset Layout", tag="menu_reset_layout")

        # ── Derived layout dimensions ──────────────────────────────────────
        TITLEBAR_H = 28
        main_h   = height - TITLEBAR_H - TOOLBAR_H - BOTTOM_H
        center_w = width  - LEFT_W    - RIGHT_W - 6  # 6 px for borders/gaps

        # ── Single primary window ──────────────────────────────────────────
        with dpg.window(
            tag="editor_root",
            no_title_bar=True,
            no_resize=True,
            no_move=True,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        ):

            # ── Row 0: Custom drag bar (replaces OS title bar) ─────────────
            with dpg.group(tag="custom_titlebar", horizontal=True):
                dpg.add_text(
                    f"  ✦ {self._title}",
                    color=(180, 180, 220),
                    tag="tb_title_text",
                )
                dpg.add_spacer(width=-90)  # push buttons to right

                # Minimize button
                dpg.add_button(
                    label="  —  ",
                    width=40,
                    tag="tb_minimize_btn",
                    callback=lambda: dpg.minimize_viewport(),
                )
                # Close button
                dpg.add_button(
                    label="  ✕  ",
                    width=40,
                    tag="tb_close_btn",
                    callback=lambda: dpg.stop_dearpygui(),
                )

            # Register mouse handler for dragging the titlebar
            with dpg.item_handler_registry() as _drag_handler:
                dpg.add_item_clicked_handler(
                    button=0, callback=self._on_titlebar_drag_start
                )
            dpg.bind_item_handler_registry("custom_titlebar", _drag_handler)

            # ── Row 1: Toolbar (h=TOOLBAR_H) ───────────────────────────────
            with dpg.child_window(
                tag="toolbar_row",
                width=-1,
                height=TOOLBAR_H,
                border=False,
                no_scrollbar=True,
            ):
                self._toolbar.build("toolbar_row")
                self._toolbar.set_on_mode_change(self._on_editor_mode_change)

            # ── Row 2: Main content (horizontal group) ─────────────────────
            with dpg.group(horizontal=True):

                # Left panel — tools / scene settings / snapping
                with dpg.child_window(
                    tag="left_panel",
                    width=LEFT_W,
                    height=main_h,
                    border=True,
                ):
                    self._build_left_panel("left_panel")

                # Center panel — Viewport | Code Mode tabs
                with dpg.child_window(
                    tag="center_panel",
                    width=center_w,
                    height=main_h,
                    border=False,
                ):
                    with dpg.tab_bar(tag="center_tabs"):
                        with dpg.tab(label="Viewport", tag="tab_viewport"):
                            with dpg.child_window(
                                tag="viewport_area",
                                width=-1,
                                height=-1,
                                border=True,
                            ):
                                if self._viewport_panel is not None:
                                    self._viewport_panel.build("viewport_area")

                        with dpg.tab(label="Code Mode", tag="tab_code_mode"):
                            with dpg.child_window(
                                tag="code_mode_area",
                                width=-1,
                                height=-1,
                                border=False,
                            ):
                                if self._code_mode_panel is None:
                                    from playslap.ui.editor.code_mode_panel import (
                                        CodeModePanel,
                                    )
                                    self._code_mode_panel = CodeModePanel(self._engine)
                                    # Late-wire to content browser
                                    if self._content_browser is not None:
                                        self._content_browser.set_on_open_script(
                                            self._code_mode_panel.load_script
                                        )
                                self._code_mode_panel.build("code_mode_area")

                # Right panel — Scene (outliner) | Details (properties)
                with dpg.child_window(
                    tag="right_panel",
                    width=-1,
                    height=main_h,
                    border=True,
                ):
                    with dpg.tab_bar(tag="right_tabs"):
                        with dpg.tab(label="Scene", tag="tab_scene"):
                            with dpg.child_window(
                                tag="scene_tab_body",
                                width=-1,
                                height=-1,
                                border=False,
                            ):
                                if self._scene_outliner is not None:
                                    self._scene_outliner.build("scene_tab_body")

                        with dpg.tab(label="Details", tag="tab_details"):
                            with dpg.child_window(
                                tag="details_tab_body",
                                width=-1,
                                height=-1,
                                border=False,
                            ):
                                for panel in self._panels:
                                    panel.build("details_tab_body")

            # ── Row 3: Content browser (h=BOTTOM_H) ────────────────────────
            with dpg.child_window(
                tag="bottom_panel",
                width=-1,
                height=BOTTOM_H,
                border=True,
            ):
                if self._content_browser is not None:
                    self._content_browser.build("bottom_panel")

            # ── Row 4: Status bar ──────────────────────────────────────────
            dpg.add_text("Ready", tag="status_bar", color=(150, 150, 150))

        # ── Bind opaque theme to viewport child window ─────────────────────
        if self._viewport_panel is not None:
            from playslap.ui.editor.theme import get_viewport_opaque_theme
            dpg.bind_item_theme("viewport_area", get_viewport_opaque_theme())

        dpg.set_primary_window("editor_root", True)
        dpg.show_viewport()
        dpg.maximize_viewport()  # ensure always visible

        # Apply DWM glass effect AFTER viewport is shown (so HWND exists)
        from playslap.ui.editor.theme import apply_dwm_glass
        apply_dwm_glass(self._title)

    # ------------------------------------------------------------------
    # Left panel construction
    # ------------------------------------------------------------------

    def _build_left_panel(self, parent: str) -> None:
        import dearpygui.dearpygui as dpg

        dpg.add_text("Tools", parent=parent, color=(180, 180, 200))
        dpg.add_separator(parent=parent)
        dpg.add_spacer(height=4, parent=parent)

        # Tool buttons — vertical, full-width
        tools = [
            ("Select",  "select",    "S"),
            ("Move",    "translate", "T"),
            ("Rotate",  "rotate",    "R"),
            ("Scale",   "scale",     "Sc"),
        ]
        for label, mode, shortcut in tools:
            btn_tag = f"left_tool_{mode}"
            dpg.add_button(
                label=f"[{shortcut}]  {label}",
                tag=btn_tag,
                width=-1,
                height=32,
                parent=parent,
                callback=lambda s, d, m=mode: self._select_tool(m),
            )

        dpg.add_separator(parent=parent)
        dpg.add_spacer(height=4, parent=parent)

        dpg.add_text("Scene", parent=parent, color=(180, 180, 200))
        dpg.add_separator(parent=parent)
        dpg.add_checkbox(
            label="Show Grid", default_value=True, parent=parent
        )
        dpg.add_drag_float(
            label="Grid Size",
            default_value=32.0,
            min_value=1.0,
            max_value=512.0,
            width=-1,
            parent=parent,
        )

        dpg.add_spacer(height=4, parent=parent)
        dpg.add_text("Snapping", parent=parent, color=(180, 180, 200))
        dpg.add_separator(parent=parent)
        dpg.add_drag_float(
            label="Translate",
            default_value=8.0,
            min_value=0.5,
            max_value=128.0,
            width=-1,
            parent=parent,
        )
        dpg.add_drag_float(
            label="Rotate°",
            default_value=15.0,
            min_value=1.0,
            max_value=90.0,
            width=-1,
            parent=parent,
        )
        dpg.add_drag_float(
            label="Scale",
            default_value=0.25,
            min_value=0.05,
            max_value=2.0,
            width=-1,
            parent=parent,
        )

    def _select_tool(self, mode: str) -> None:
        """Activate *mode* in the toolbar and update left-panel button highlights."""
        if self._toolbar is not None:
            self._toolbar._select_tool(mode)

    # ------------------------------------------------------------------
    # 2D / 3D mode
    # ------------------------------------------------------------------

    @property
    def editor_mode(self) -> str:
        """Return the current editor mode (``"2D"`` or ``"3D"``)."""
        return self._editor_mode

    def _on_editor_mode_change(self, mode: str) -> None:
        """Handle 2D/3D mode toggle fired by the toolbar.

        Shows or hides tool panels appropriate to *mode*.  All panel tags are
        checked with ``dpg.does_item_exist`` before touching them so the method
        is safe to call even when 3D panels have not been built yet.
        """
        import dearpygui.dearpygui as dpg

        self._editor_mode = mode

        # Tags for panels that exist in both modes (standard left-panel body)
        standard_2d_tags = ["left_panel"]

        # 3D-only panel tags stored as instance variables
        three_d_tags = [self._mesh_inspector_tag, self._layer_lighting_tag]

        if mode == "2D":
            for tag in standard_2d_tags:
                if dpg.does_item_exist(tag):
                    dpg.configure_item(tag, show=True)
            for tag in three_d_tags:
                if dpg.does_item_exist(tag):
                    dpg.configure_item(tag, show=False)
        else:  # "3D"
            for tag in standard_2d_tags:
                if dpg.does_item_exist(tag):
                    dpg.configure_item(tag, show=True)
            for tag in three_d_tags:
                if dpg.does_item_exist(tag):
                    dpg.configure_item(tag, show=True)

        # Forward mode to viewport camera and gizmo overlay
        if self._viewport_panel is not None and hasattr(self._viewport_panel, "set_mode"):
            self._viewport_panel.set_mode(mode)
        if self._gizmo_overlay is not None and hasattr(self._gizmo_overlay, "set_mode"):
            self._gizmo_overlay.set_mode(mode)

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Enter the Dear PyGui render loop.

        Blocks until the viewport is closed or :meth:`stop` is called.
        Destroys the Dear PyGui context on exit.

        Raises
        ------
        ImportError
            If ``dearpygui`` is not installed.
        """
        try:
            import dearpygui.dearpygui as dpg
        except ImportError as exc:
            raise ImportError(
                "dearpygui is required for the editor shell. "
                "Install it with: pip install playslap[editor]"
            ) from exc

        self._running = True
        while dpg.is_dearpygui_running():
            if self._gizmo_overlay is not None:
                self._gizmo_overlay.update()

            # ── Keyboard shortcuts ─────────────────────────────────────────
            if dpg.is_key_down(dpg.mvKey_Control):
                if dpg.is_key_pressed(dpg.mvKey_S):
                    self._save_project()
                elif dpg.is_key_pressed(dpg.mvKey_Z):
                    self._undo()

            if dpg.is_key_pressed(dpg.mvKey_Delete):
                self._delete_selected()

            if dpg.is_key_pressed(dpg.mvKey_F5):
                self._toggle_play()

            self._update_window_drag()
            dpg.render_dearpygui_frame()
            if self._code_mode_panel is not None:
                self._code_mode_panel.update()
        dpg.destroy_context()
        self._running = False

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def _set_status(self, message: str) -> None:
        """Update the status bar text to *message*."""
        try:
            import dearpygui.dearpygui as dpg
            if dpg.does_item_exist("status_bar"):
                dpg.set_value("status_bar", message)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Keyboard shortcut actions
    # ------------------------------------------------------------------

    def _save_project(self) -> None:
        """Ctrl+S — save the current project via the project manager, if loaded."""
        project_manager = getattr(self._engine, "_project_manager", None)
        if project_manager is not None:
            try:
                project_manager.save()
                self._set_status("Saved")
            except Exception as exc:
                self._set_status(f"Save failed: {exc}")
        else:
            self._set_status("No project loaded")

    def _undo(self) -> None:
        """Ctrl+Z — undo the last action via the undo manager, if available."""
        undo_manager = getattr(self._engine, "_undo_manager", None)
        if undo_manager is not None:
            try:
                undo_manager.undo()
                self._set_status("Undo")
            except Exception as exc:
                self._set_status(f"Undo failed: {exc}")
        else:
            self._set_status("Undo (not yet implemented)")

    def _delete_selected(self) -> None:
        """Delete — remove the currently selected entity from the scene."""
        if self._scene_outliner is None:
            return
        selected = getattr(self._scene_outliner, "selected_entity", None)
        if selected is None:
            return
        scene = getattr(self._engine, "scene", None)
        if scene is not None:
            try:
                scene.remove_entity(selected)
                self._set_status(f"Deleted {selected}")
            except Exception as exc:
                self._set_status(f"Delete failed: {exc}")
        else:
            self._set_status("No active scene")

    def _toggle_play(self) -> None:
        """F5 — toggle between edit mode and play mode."""
        self._play_mode = not self._play_mode
        if self._play_mode:
            self._set_status("Play mode")
            run_fn = getattr(self._engine, "run", None)
            if run_fn is not None:
                threading.Thread(target=run_fn, daemon=True).start()
        else:
            self._set_status("Edit mode")
            stop_fn = getattr(self._engine, "stop", None)
            if stop_fn is not None:
                try:
                    stop_fn()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Custom title-bar drag
    # ------------------------------------------------------------------

    def _on_titlebar_drag_start(self, *_) -> None:
        """Record the initial mouse and viewport positions when drag begins."""
        import dearpygui.dearpygui as dpg
        self._dragging_window = True
        mx, my = dpg.get_mouse_pos(local=False)
        vx, vy = dpg.get_viewport_pos()
        self._drag_start_mouse = (mx, my)
        self._drag_start_vp = (vx, vy)

    def _update_window_drag(self) -> None:
        """Move the viewport to follow the mouse while the drag button is held."""
        import dearpygui.dearpygui as dpg
        if not self._dragging_window:
            return
        if not dpg.is_mouse_button_down(0):
            self._dragging_window = False
            return
        mx, my = dpg.get_mouse_pos(local=False)
        dx = mx - self._drag_start_mouse[0]
        dy = my - self._drag_start_mouse[1]
        dpg.configure_viewport(
            x_pos=self._drag_start_vp[0] + dx,
            y_pos=self._drag_start_vp[1] + dy,
        )

    # ------------------------------------------------------------------
    # Lifecycle (continued)
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Signal the render loop to stop on the next frame.

        The loop checks ``dpg.is_dearpygui_running()`` internally; calling
        this method sets the internal flag so callers can track state, but
        the actual loop termination is driven by Dear PyGui (e.g. the user
        closing the viewport).
        """
        self._running = False
