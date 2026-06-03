from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from slappyengine.engine import Engine
    from slappyengine.projects import Project
    from slappyengine.ui.editor.notebook_toolbar import NotebookToolbar
    from slappyengine.ui.editor.notebook_outliner import NotebookOutliner
    from slappyengine.ui.editor.notebook_inspector import NotebookInspector
    from slappyengine.ui.editor.content_browser import ContentBrowser
    from slappyengine.ui.editor.notebook_project_picker import (
        NotebookProjectPicker,
    )
    from slappyengine.ui.editor.settings import UISettings

try:
    from slappyengine.ui.editor.notebook_gizmos import (
        NotebookGizmoOverlay,  # noqa: F401
    )
except ImportError:
    NotebookGizmoOverlay = None  # type: ignore[assignment,misc]

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
        title: str = "SlapPy Notebook",
        width: int = 1400,
        height: int = 900,
        ui_settings: "UISettings | None" = None,
    ) -> None:
        self._engine = engine
        self._title = title
        self._width = width
        self._height = height
        self._panels: list = []
        self._viewport_panel = None
        self._code_mode_panel = None
        self._toolbar: "NotebookToolbar | None" = None
        self._scene_outliner: "NotebookOutliner | None" = None
        self._inspector: "NotebookInspector | None" = None
        self._content_browser: "ContentBrowser | None" = None
        self._gizmo_overlay = None
        self._running = False
        self._play_mode: bool = False

        # ── settings.ui — keep the dataclass off the engine Config ─────────
        from slappyengine.ui.editor.settings import UISettings
        self._ui_settings: UISettings = ui_settings or UISettings()

        # ── Theme + creature subsystem wiring (filled by setup_theme_subsystem)
        self._creature_scheduler = None
        self._creature_bus_adapter = None
        self._idle_emitter = None
        self._theme_switcher_panel = None

        # ── Notebook ambient-feedback channels ─────────────────────────────
        # Built during ``setup``; constructed here so callers can introspect
        # the bar / hotkey table immediately after instantiation.
        from slappyengine.ui.editor.notebook_status_bar import NotebookStatusBar
        from slappyengine.ui.editor.notebook_hotkeys import NotebookHotkeys

        self._notebook_status_bar = NotebookStatusBar(
            on_theme_indicator_click=self._open_theme_switcher,
        )
        self._notebook_status_bar.set_active_theme_name(
            self._ui_settings.default_theme,
        )
        self._notebook_hotkeys = NotebookHotkeys(
            command_dispatcher=self._dispatch_editor_command,
            easter_eggs=self._ui_settings.easter_eggs,
        )

        # Scene name + save state surfaced in the OS title bar.
        self._scene_name: str = "untitled"
        self._scene_saved: bool = True
        # Latest composed window title — populated by :meth:`_apply_window_title`
        # whether or not DPG is up so tests can inspect the formatter output
        # without a live viewport.
        self._last_window_title: str | None = None

        # Custom title-bar drag state
        self._dragging_window: bool = False
        self._drag_start_mouse: tuple[int, int] = (0, 0)
        self._drag_start_vp: tuple[int, int] = (0, 0)

        # 2D / 3D mode state
        self._editor_mode: str = "2D"

        # Tags for 3D-only panels (may not yet exist; always guarded with does_item_exist)
        self._mesh_inspector_tag: str = "mesh_inspector_panel"
        self._layer_lighting_tag: str = "layer_lighting_panel"

        # First-run welcome panel — lazily constructed in :meth:`show_welcome`.
        self._welcome_panel = None

        # Notebook bookkeeping — outliner selection mirror + active tool.
        self._selected_entity: object | None = None
        self._active_tool: str = "select"

        # ── Project lifecycle state ────────────────────────────────────────
        # The shell tracks the currently open Project, the on-disk scene
        # path, and a dirty bit for unsaved changes. ``_project_picker`` is
        # the headless-safe NotebookProjectPicker the File menu surfaces;
        # constructed lazily so importing the shell never touches the
        # registry singleton on disk.
        self._project: "Project | None" = None
        self._scene_path: Path | None = None
        self._dirty: bool = False
        self._project_picker: "NotebookProjectPicker | None" = None

    # ------------------------------------------------------------------
    # Ambient-feedback helpers (status bar + hotkeys)
    # ------------------------------------------------------------------

    def _open_theme_switcher(self) -> None:
        """Surface the theme-switcher panel — clicked from the status bar.

        Best-effort: if Dear PyGui is running and the panel has a tag,
        focus it; otherwise silently no-op.
        """
        panel = self._theme_switcher_panel
        if panel is None:
            return
        try:
            import dearpygui.dearpygui as dpg

            tag = getattr(panel, "_panel_tag", None) or "theme_switcher_panel"
            if dpg.does_item_exist(tag):
                dpg.focus_item(tag)
        except Exception:
            pass

    def _dispatch_editor_command(self, command: str) -> None:
        """Route a notebook-hotkey command name to a shell action.

        The :class:`NotebookHotkeys` table emits namespaced ids such as
        ``"editor.save"``; we strip the prefix when probing the local
        action table and the engine hook table so callers can subscribe
        with either flavour.
        """
        local = command.split(".", 1)[1] if command.startswith("editor.") else command
        action = {
            "save":             self._save_project,
            "undo":             self._undo,
            "delete":           self._delete_selected,
            "play":             self._toggle_play,
            "run":              self._toggle_play,
        }.get(local)
        if action is not None:
            try:
                action()
            except Exception:
                pass
            return
        hook = getattr(self._engine, local, None)
        if callable(hook):
            try:
                hook()
            except Exception:
                pass
            return
        # Surface unknown commands so users can confirm the press registered.
        if self._notebook_status_bar is not None:
            try:
                self._notebook_status_bar.set_message(
                    f"cmd: {command}", kind="info",
                )
            except Exception:
                pass

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

    def setup_theme_subsystem(self) -> None:
        """Register starter themes, build the creature subsystem, bind the bus.

        Headless-safe — no Dear PyGui calls. ``setup`` calls this before
        any DPG work so theming is ready when the layout starts emitting
        widgets, and tests can drive it directly without stubbing DPG.

        Sequence:

        1. Register every diary-family starter theme.
        2. Apply ``ui_settings.default_theme`` (falls back to the first
           registered theme when the name is unknown).
        3. Build a :class:`CreatureScheduler` and register the fox /
           butterfly / sparkle built-ins on it.
        4. Forward ``ui_settings.creature_animations`` and
           ``reduced_motion`` to the scheduler.
        5. Install a :class:`CreatureBusAdapter` on the global event bus.
        6. Spawn an :class:`IdleEventEmitter` so the main loop can pulse
           ``engine.idle_60s`` / ``engine.idle_120s`` to the bus.
        7. Stash a :class:`ThemeSwitcherPanel` (bound to the scheduler)
           ready for :meth:`register_panel` — happens here so callers can
           reach ``self._theme_switcher_panel`` straight after construction.
        """
        # 1. Register every starter theme.
        from slappyengine.ui.theme.themes import register_starter_themes
        registered = register_starter_themes()

        # 2. Apply the configured default theme (resilient fallback).
        from slappyengine.ui.theme import (
            apply_theme,
            list_registered_themes,
        )
        target = self._ui_settings.default_theme
        known = list_registered_themes()
        if target not in known:
            target = registered[0] if registered else (known[0] if known else "")
        if target:
            try:
                apply_theme(target)
            except LookupError:
                pass

        # 3. Build the scheduler + register built-in creatures.
        from slappyengine.ui.theme.creatures import CreatureScheduler
        from slappyengine.ui.theme.creatures.builtin import register_builtins

        scheduler = CreatureScheduler()
        register_builtins(scheduler)
        self._creature_scheduler = scheduler

        # 4. Apply the master + reduced-motion settings.
        scheduler.set_enabled(self._ui_settings.creature_animations)
        scheduler.set_reduced_motion(self._ui_settings.reduced_motion)

        # 5. Install the bus adapter.
        from slappyengine.ui.theme.creatures import CreatureBusAdapter
        from slappyengine.event_bus import get_default_bus

        bus = get_default_bus()
        adapter = CreatureBusAdapter(scheduler, bus)
        adapter.install()
        self._creature_bus_adapter = adapter

        # 6. Build the idle emitter.
        from slappyengine.ui.theme.creatures import IdleEventEmitter
        self._idle_emitter = IdleEventEmitter(bus)

        # 7. Stage the theme switcher panel so callers can register it.
        from slappyengine.ui.editor.theme_switcher_panel import ThemeSwitcherPanel
        panel = ThemeSwitcherPanel(scheduler=scheduler)
        self._theme_switcher_panel = panel
        self.register_panel(panel)

    def setup_notebook_panels(self) -> None:
        """Auto-wire the notebook panel family on the shell.

        Constructs :class:`NotebookToolbar`, :class:`NotebookOutliner`,
        :class:`NotebookInspector`, and :class:`NotebookGizmoOverlay`,
        and registers the inspector on the Details sidebar. Headless-safe
        — no Dear PyGui calls — so tests can drive this directly without
        a real GUI context.

        Pre-existing values on ``self._toolbar`` / ``self._scene_outliner``
        / ``self._inspector`` / ``self._gizmo_overlay`` are left alone so
        a caller can inject a custom panel before :meth:`setup` runs.

        The Nova3D panel siblings (``EditorToolbar``, ``SceneOutliner``,
        ``PropertyInspector``, ``GizmoOverlay``) are reference-only and
        deliberately never imported by this method.
        """
        if self._toolbar is None:
            from slappyengine.ui.editor.notebook_toolbar import NotebookToolbar
            self._toolbar = NotebookToolbar(
                on_tool_changed=self._on_tool_changed,
            )

        if self._scene_outliner is None:
            from slappyengine.ui.editor.notebook_outliner import NotebookOutliner
            self._scene_outliner = NotebookOutliner(
                world_getter=lambda: getattr(self._engine, "scene", None),
                on_select=self._on_entity_selected,
            )

        if self._inspector is None:
            from slappyengine.ui.editor.notebook_inspector import (
                NotebookInspector,
            )
            self._inspector = NotebookInspector()
            self.register_panel(self._inspector)

        if NotebookGizmoOverlay is not None and self._gizmo_overlay is None:
            self._gizmo_overlay = NotebookGizmoOverlay()

    def setup(self) -> None:  # noqa: C901 (complexity — UI layout)
        """Initialise the Dear PyGui context and build the window layout.

        Must be called before :meth:`run`.

        Wires the Notebook panel family exclusively — :class:`NotebookToolbar`,
        :class:`NotebookOutliner`, :class:`NotebookInspector`, and
        :class:`NotebookGizmoOverlay`. The legacy Nova3D panel siblings
        (``EditorToolbar`` / ``SceneOutliner`` / ``PropertyInspector`` /
        ``GizmoOverlay``) ship as reference-only modules; this method
        never imports them. See ``docs/ui_pattern_audit_2026_06_03.md``.

        Raises
        ------
        ImportError
            If ``dearpygui`` is not installed.
        """
        # Theme + creature wiring runs first so any panel that consults
        # the active theme during ``build`` already has one — the notebook
        # widgets read palette tokens during construction.
        self.setup_theme_subsystem()

        try:
            import dearpygui.dearpygui as dpg
        except ImportError as exc:
            raise ImportError(
                "dearpygui is required for the editor shell. "
                "Install it with: pip install SlapPyEngine[editor]"
            ) from exc

        width  = self._width
        height = self._height

        # ── Auto-wire notebook sub-components if not pre-set ──────────────
        # The Notebook panels are the *only* editor surface — Nova3D
        # variants live on disk for reference but are never wired here.
        self.setup_notebook_panels()

        # Register the spawn menu — the outliner reads
        # ``spawn_menu.SPAWN_ACTIONS`` from its ``+ Add`` popup.  We
        # surface the module on the shell so external code (e.g.
        # plugin layers) can extend ``SPAWN_ACTIONS`` before the
        # outliner is built.
        from slappyengine.ui.editor import spawn_menu as _spawn_menu
        self._spawn_menu = _spawn_menu

        if self._content_browser is None:
            from slappyengine.ui.editor.content_browser import ContentBrowser
            self._content_browser = ContentBrowser()

        # Wire content browser → code mode panel (if both present)
        if self._content_browser is not None and self._code_mode_panel is not None:
            self._content_browser.set_on_open_script(
                self._code_mode_panel.load_script
            )

        # ── DPG context — the notebook theme is the only theme path ───────
        # The Nova3D dark glass theme (``theme.apply_editor_theme``) is
        # intentionally NOT applied. The notebook theme registry owns the
        # entire editor look and was already applied by
        # ``setup_theme_subsystem``.
        dpg.create_context()

        # Normal OS chrome — title bar, resize handles, drag from titlebar.
        # The Nova3D dark theme used decorated=False + transparent clear for
        # DWM blur; the notebook theme paints its own paper-cream background
        # and leaves window management to the host OS where it belongs.
        dpg.create_viewport(
            title=self._title,
            width=width,
            height=height,
            decorated=True,
            resizable=True,
            min_width=800,
            min_height=600,
            clear_color=(251, 247, 236, 255),  # paper cream (theme fallback)
        )
        dpg.setup_dearpygui()

        # ── Menu bar (handled by viewport — sits above everything) ─────────
        with dpg.viewport_menu_bar():
            with dpg.menu(label="File"):
                dpg.add_menu_item(
                    label="New Scene",
                    tag="menu_new_scene",
                    callback=lambda *_: self.new_scene(),
                )
                dpg.add_menu_item(
                    label="Open Scene...",
                    tag="menu_open_scene",
                    callback=lambda *_: self.menu_open_scene(),
                )
                dpg.add_menu_item(
                    label="Save Scene",
                    tag="menu_save_scene",
                    shortcut="Ctrl+S",
                    callback=lambda *_: self.menu_save_scene(),
                )
                dpg.add_menu_item(
                    label="Save Scene As...",
                    tag="menu_save_scene_as",
                    shortcut="Ctrl+Shift+S",
                    callback=lambda *_: self.save_scene_as(),
                )
                dpg.add_separator()
                dpg.add_menu_item(
                    label="Switch Project...",
                    tag="menu_switch_project",
                    callback=lambda *_: self.switch_project(),
                )
                with dpg.menu(
                    label="Recent Projects",
                    tag="menu_recent_projects",
                ):
                    self._populate_recent_projects_menu()
                dpg.add_separator()
                dpg.add_menu_item(
                    label="Quit",
                    tag="menu_quit",
                    callback=lambda *_: self.stop(),
                )
            with dpg.menu(label="Edit"):
                dpg.add_menu_item(
                    label="Undo",
                    tag="menu_undo",
                    callback=lambda *_: self.menu_undo(),
                )
            with dpg.menu(label="View"):
                dpg.add_menu_item(
                    label="Reset Layout",
                    tag="menu_reset_layout",
                    callback=lambda *_: self.menu_reset_layout(),
                )
            with dpg.menu(label="Help"):
                dpg.add_menu_item(
                    label="Welcome",
                    tag="menu_welcome",
                    callback=lambda *_: self.show_welcome(),
                )
                dpg.add_menu_item(
                    label="About",
                    tag="menu_about",
                    callback=lambda *_: self.menu_about(),
                )

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

            # Row 0: OS title bar now handles drag/minimize/close. Keeping an
            # empty group with the legacy tag so downstream code that looks
            # for "custom_titlebar" doesn't blow up.
            dpg.add_group(tag="custom_titlebar")

            # ── Row 1: Toolbar (h=TOOLBAR_H) ───────────────────────────────
            with dpg.child_window(
                tag="toolbar_row",
                width=-1,
                height=TOOLBAR_H,
                border=False,
                no_scrollbar=True,
            ):
                # NotebookToolbar receives its tool-change callback at
                # construction time (see ``setup``); no extra wiring here.
                self._toolbar.build("toolbar_row")

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
                                    from slappyengine.ui.editor.code_mode_panel import (
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

            # ── Row 5: Notebook ambient status bar (washi-tape marginalia)
            try:
                self._notebook_status_bar.build("editor_root")
            except Exception:
                pass

        # ── Install global hotkeys after the root window exists ────────
        try:
            self._notebook_hotkeys.set_creature_scheduler(
                self._creature_scheduler,
            )
        except Exception:
            pass
        try:
            self._notebook_hotkeys.install()
        except Exception:
            pass

        # ── Push notebook-themed window title to the viewport ──────────
        try:
            self._apply_window_title()
        except Exception:
            pass

        dpg.set_primary_window("editor_root", True)
        dpg.show_viewport()
        dpg.maximize_viewport()  # ensure always visible
        # The Nova3D-era DWM blur-behind and viewport opaque theme are
        # intentionally not applied — the notebook theme is paper, not
        # glass.

        # First-run welcome panel — only the very first launch.
        try:
            self._maybe_show_first_run_welcome()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # First-run welcome panel
    # ------------------------------------------------------------------

    def _maybe_show_first_run_welcome(self) -> None:
        """Surface the welcome modal when ``ui.welcome_shown`` is ``False``."""
        from slappyengine.ui.editor.notebook_welcome import NotebookWelcome

        if self._welcome_panel is None:
            self._welcome_panel = NotebookWelcome(
                settings=self._ui_settings,
                on_start_blank=self._welcome_start_blank,
                on_open_demo=self._welcome_open_demo,
                on_dismiss=self._welcome_dismissed,
            )
            if self._creature_scheduler is not None:
                self._welcome_panel.bind_creature_scheduler(
                    self._creature_scheduler,
                )
        if self._welcome_panel.is_first_run():
            self._welcome_panel.build("editor_root")

    def show_welcome(self) -> None:
        """Re-open the welcome modal (Help → Welcome entry-point)."""
        from slappyengine.ui.editor.notebook_welcome import NotebookWelcome

        if self._welcome_panel is None:
            self._welcome_panel = NotebookWelcome(
                settings=self._ui_settings,
                on_start_blank=self._welcome_start_blank,
                on_open_demo=self._welcome_open_demo,
                on_dismiss=self._welcome_dismissed,
            )
            if self._creature_scheduler is not None:
                self._welcome_panel.bind_creature_scheduler(
                    self._creature_scheduler,
                )
        self._welcome_panel.build("editor_root")

    def _welcome_start_blank(self) -> None:
        """Welcome → "Start drawing!" → load a blank scene."""
        scene_new = getattr(self._engine, "new_scene", None)
        if callable(scene_new):
            try:
                scene_new()
            except Exception:
                pass

    def _welcome_open_demo(self, demo_id: str) -> None:
        """Welcome → demo card click → forward to engine.open_example."""
        opener = getattr(self._engine, "open_example", None)
        if callable(opener):
            try:
                opener(f"hello_{demo_id}.py")
            except Exception:
                pass

    def _welcome_dismissed(self) -> None:
        """Welcome panel closed — nothing to forward by default."""
        pass

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
        """Activate *mode* on the notebook toolbar.

        Used by the left-panel quick-select buttons. Routes through the
        :class:`NotebookToolbar`'s public :meth:`set_active` so the
        tool-changed callback (which forwards to the gizmo overlay) still
        fires.
        """
        if self._toolbar is None:
            return
        # NotebookToolbar uses the engine canonical id "move" rather than
        # the legacy "translate" — translate the left-panel label here so
        # the rest of the editor sees the canonical name.
        tool_id = "move" if mode == "translate" else mode
        try:
            self._toolbar.set_active(tool_id)
        except (ValueError, AttributeError):
            # Unknown tool — leave the toolbar state untouched.
            pass

    def _on_tool_changed(self, tool_id: str) -> None:
        """Receive the active-tool name from the notebook toolbar.

        Forwards the value to the notebook gizmo overlay so the next
        :meth:`render` paints the right handle family. The
        :class:`NotebookGizmoOverlay` exposes mode via
        :meth:`render(..., mode=...)` rather than a setter, so we cache
        the value locally and the run loop reads it before each frame.

        Also forwards to ``engine.set_active_tool()`` when present so
        engine-side systems (input-routing, scripted tools) can observe
        the change. The status bar's active tool is updated so users
        get a visual confirmation in the marginalia row.
        """
        # Translate the toolbar's "move" id to the gizmo's "translate"
        # vocabulary — the legacy editor used "translate" and the
        # NotebookGizmoOverlay kept that for compatibility.
        if tool_id == "move":
            tool_id = "translate"
        self._active_tool = tool_id
        # Status bar reflection — surface the tool name in the marginalia.
        if self._notebook_status_bar is not None:
            try:
                self._notebook_status_bar.set_active_tool(tool_id)
            except Exception:
                pass
        # Engine hook — only forward when the engine implements it.
        engine_setter = getattr(self._engine, "set_active_tool", None)
        if callable(engine_setter):
            try:
                engine_setter(tool_id)
            except Exception:
                pass
        # Gizmo overlay — expose set_mode if the overlay carries one so
        # the active manipulator is updated synchronously rather than
        # waiting for the next frame's render() call.
        if self._gizmo_overlay is not None:
            setter = getattr(self._gizmo_overlay, "set_mode", None)
            if callable(setter):
                try:
                    setter(tool_id)
                except Exception:
                    pass

    def handle_spawn(self, card_id: str, spec: dict) -> object | None:
        """Instantiate a spawn-menu card and select it in the outliner.

        Routes the spawn card through the engine's scene. Falls back to a
        soft no-op when no scene is attached. Returns the new entity (or
        ``None`` on failure) so callers can chain follow-up edits.

        Wired as the ``on_spawn`` callback when the shell constructs a
        :class:`NotebookSpawnMenu`.
        """
        scene = getattr(self._engine, "scene", None)
        if scene is None:
            self._set_status(f"Cannot summon {card_id}: no active scene")
            return None
        entity = None
        # Best-effort spec → entity translation by scanning SPAWN_ACTIONS
        # for a matching action_id; falls back to wrapping the spec on a
        # generic carrier so the outliner still gets a row.
        try:
            from slappyengine.ui.editor.spawn_menu import SPAWN_ACTIONS

            for action in SPAWN_ACTIONS:
                if action.get("action_id") == card_id:
                    factory = action.get("factory")
                    if callable(factory):
                        entity = factory(spec, scene=scene, engine=self._engine)
                        break
        except Exception:
            entity = None
        if entity is None:
            # Fallback: stash the spec on a stub entity object so the
            # outliner / inspector can still surface "something happened".
            class _StubEntity:
                def __init__(self, _cid: str, _spec: dict) -> None:
                    self.id = f"{_cid}_{id(self)}"
                    self.name = _spec.get("name", _cid)
                    self.kind = _cid
                    self.parameters = dict(_spec)
                    self.visible = True
                    self.locked = False
                def on_create(self) -> None:  # noqa: D401 - scene hook
                    pass
                def on_destroy(self) -> None:  # noqa: D401 - scene hook
                    pass
            entity = _StubEntity(card_id, spec)
            try:
                scene.add(entity)  # type: ignore[arg-type]
            except Exception:
                # Some Scene impls require Entity subclass — silently swallow.
                pass
        # Select the new entity in the outliner.
        if self._scene_outliner is not None and entity is not None:
            try:
                eid = getattr(entity, "id", None) or getattr(entity, "name", "")
                if isinstance(eid, str) and eid:
                    self._scene_outliner.set_selected(eid)
            except Exception:
                pass
            try:
                self._on_entity_selected(entity)
            except Exception:
                pass
        self._set_status(f"Summoned {card_id}")
        return entity

    def _on_entity_selected(self, entity: object) -> None:
        """Receive a selection event from the notebook outliner.

        Forwards the entity through the three downstream channels:

        1. :class:`NotebookInspector` — repaints the field-journal page
           with the new target's fields (or the empty state when *entity*
           is ``None``).
        2. :class:`NotebookGizmoOverlay` — rebinds the pencil overlay so
           the next ``render`` pass paints handles on the new entity.
        3. :class:`NotebookStatusBar` — bumps the marginalia selection
           segment so the user gets ambient feedback that the click
           registered.

        Tracked on the shell so the Delete shortcut can act on the
        currently-selected entity.
        """
        self._selected_entity = entity
        # 1. NotebookInspector picks up the entity
        if self._inspector is not None:
            try:
                self._inspector.set_target(entity)
            except Exception:
                pass
        # 2. Gizmo overlay binds
        if self._gizmo_overlay is not None:
            try:
                self._gizmo_overlay.set_entity(entity)
            except Exception:
                pass
        # 3. Status bar shows selection count
        if self._notebook_status_bar is not None:
            try:
                self._notebook_status_bar.set_selection_count(
                    1 if entity is not None else 0,
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 2D / 3D mode
    # ------------------------------------------------------------------

    @property
    def editor_mode(self) -> str:
        """Return the current editor mode (``"2D"`` or ``"3D"``)."""
        return self._editor_mode

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Per-frame tick — drives the creature scheduler + idle emitter.
    # ------------------------------------------------------------------

    def tick_subsystems(self, dt: float, draw_list: object | None = None) -> None:
        """Advance the per-frame creature + idle subsystems.

        Called once per frame from :meth:`run` after the DPG render call,
        and may be called directly from headless tests. ``dt`` is the
        wall-clock delta in seconds; ``draw_list`` is the renderer
        handle passed to :meth:`CreatureScheduler.render` (a DPG drawlist
        in production, a recording mock in tests).
        """
        if self._creature_scheduler is not None:
            try:
                self._creature_scheduler.tick(dt)
            except Exception:
                pass
            if draw_list is not None:
                try:
                    self._creature_scheduler.render(draw_list)
                except Exception:
                    pass
        if self._idle_emitter is not None:
            try:
                self._idle_emitter.tick(dt)
            except Exception:
                pass

    def notify_user_activity(self) -> None:
        """Reset the idle emitter — call on any keyboard / mouse / drag input.

        Safe before :meth:`setup_theme_subsystem` runs (no-op when the
        emitter hasn't been built yet).
        """
        if self._idle_emitter is not None:
            self._idle_emitter.reset_activity()

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
                "Install it with: pip install SlapPyEngine[editor]"
            ) from exc

        self._running = True
        import time as _time
        last_t = _time.monotonic()
        while dpg.is_dearpygui_running():
            # Notebook gizmo overlay advances its frame index for the
            # heart-pulse animation; the actual render happens via the
            # viewport drawlist hook (host-supplied), not here.
            if self._gizmo_overlay is not None:
                advance = getattr(self._gizmo_overlay, "advance_frame", None)
                if callable(advance):
                    advance()

            # ── Keyboard shortcuts ─────────────────────────────────────────
            any_input = False
            if dpg.is_key_down(dpg.mvKey_Control):
                if dpg.is_key_pressed(dpg.mvKey_S):
                    self._save_project()
                    any_input = True
                elif dpg.is_key_pressed(dpg.mvKey_Z):
                    self._undo()
                    any_input = True

            if dpg.is_key_pressed(dpg.mvKey_Delete):
                self._delete_selected()
                any_input = True

            if dpg.is_key_pressed(dpg.mvKey_F5):
                self._toggle_play()
                any_input = True

            # Mouse-button activity (any of the standard 3 buttons).
            try:
                if (
                    dpg.is_mouse_button_down(0)
                    or dpg.is_mouse_button_down(1)
                    or dpg.is_mouse_button_down(2)
                ):
                    any_input = True
            except Exception:
                pass

            if any_input:
                self.notify_user_activity()

            self._update_window_drag()
            dpg.render_dearpygui_frame()
            if self._code_mode_panel is not None:
                self._code_mode_panel.update()

            # Drive scheduler + idle emitter once per frame.
            now = _time.monotonic()
            dt = max(0.0, now - last_t)
            last_t = now
            self.tick_subsystems(dt)
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
        # Mirror the message onto the notebook ambient status bar so
        # users get the washi-tape feedback for the same event.
        if self._notebook_status_bar is not None:
            try:
                self._notebook_status_bar.set_message(message, kind="info")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Notebook ambient channels
    # ------------------------------------------------------------------

    @property
    def notebook_status_bar(self):
        """Public accessor for the notebook ambient status bar."""
        return self._notebook_status_bar

    @property
    def notebook_hotkeys(self):
        """Public accessor for the global hotkey registry."""
        return self._notebook_hotkeys

    def set_scene_name(self, scene_name: str, saved: bool = True) -> None:
        """Update the tracked scene name + save state + window title."""
        self._scene_name = scene_name
        self._scene_saved = saved
        if self._notebook_status_bar is not None:
            try:
                self._notebook_status_bar.set_save_state(saved)
            except Exception:
                pass
        try:
            self._apply_window_title()
        except Exception:
            pass

    def _apply_window_title(self) -> None:
        """Push the notebook-themed title to the DPG viewport.

        Only writes to DPG when ``setup`` has already run — calling
        ``does_item_exist`` / ``set_viewport_title`` before a DPG context
        exists segfaults hard on Windows, so we gate every DPG access on
        ``self._running`` + a context check.
        """
        from slappyengine.ui.editor.notebook_window_title import (
            format_window_title,
        )

        # ``project_name=None`` triggers the "(no project)" placeholder.
        project_name = (
            self._project.metadata.name if self._project is not None else None
        )
        # ``_scene_saved`` is the legacy bit; ``_dirty`` is the new one and
        # takes precedence when a project is loaded — the brief asks for an
        # unsaved-flower whenever ``_dirty`` is True.
        saved = self._scene_saved and not self._dirty
        try:
            title = format_window_title(
                self._scene_name,
                saved,
                self._ui_settings.default_theme,
                project_name=project_name,
            )
        except Exception:
            return
        # Remember the latest title even when DPG isn't up yet — tests
        # introspect ``self._last_window_title`` to verify the formatter
        # ran without standing up a viewport.
        self._last_window_title = title
        # Only push to DPG once a context has been created — gated by
        # ``self._running`` which ``run()`` sets True after setup.
        if not self._running:
            return
        try:
            import dearpygui.dearpygui as dpg
            if dpg.does_item_exist("tb_title_text"):
                dpg.set_value("tb_title_text", f"  ✦ {title}")
            try:
                dpg.set_viewport_title(title)
            except Exception:
                pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Project lifecycle — load / save / open / switch
    # ------------------------------------------------------------------

    def set_project(self, project: "Project") -> None:
        """Set the currently open project (no side-effects).

        :meth:`load_project` is the high-level entry point — it calls
        this method then updates the title bar / content browser / status
        bar / event bus. Tests use this setter directly when they want
        to inspect a state mutation without driving the full load.
        """
        # Import here so the shell module can be imported without the
        # projects package being importable (e.g. PyYAML missing).
        from slappyengine.projects import Project as _Project

        if not isinstance(project, _Project):
            raise TypeError(
                "EditorShell.set_project: project must be a Project; "
                f"got {type(project).__name__}"
            )
        self._project = project

    def get_project(self) -> "Project | None":
        """Return the currently open project, or ``None``."""
        return self._project

    def is_dirty(self) -> bool:
        """Return ``True`` iff the current scene has unsaved changes."""
        return self._dirty

    def mark_dirty(self) -> None:
        """Flag the current scene as having unsaved edits + repaint title."""
        self._dirty = True
        self._scene_saved = False
        if self._notebook_status_bar is not None:
            try:
                self._notebook_status_bar.set_save_state(False)
            except Exception:
                pass
        try:
            self._apply_window_title()
        except Exception:
            pass

    def mark_clean(self) -> None:
        """Flag the current scene as freshly saved + repaint title."""
        self._dirty = False
        self._scene_saved = True
        if self._notebook_status_bar is not None:
            try:
                self._notebook_status_bar.set_save_state(True)
            except Exception:
                pass
        try:
            self._apply_window_title()
        except Exception:
            pass

    def load_project(self, project: "Project") -> None:
        """Open *project* — repaint title, content browser, status bar.

        Sequence:

        1. :meth:`set_project` (records the handle).
        2. Updates the OS window title via :meth:`_apply_window_title`.
        3. Re-roots the content browser at ``project.path``.
        4. Loads ``project.scenes_dir / 'main.scene.yaml'`` if present.
        5. Pushes "Loaded notebook: <name>" to the status bar.
        6. Publishes ``engine.scene_loaded`` on the global event bus
           (the deer_01.peek_in creature is bound there).
        7. Registers the project on the recents tracker.
        """
        self.set_project(project)
        # Refresh title even before the rest so the window labelling
        # reflects the new project immediately.
        try:
            self._apply_window_title()
        except Exception:
            pass

        # Re-root the content browser.
        if self._content_browser is not None:
            try:
                self._content_browser._root = Path(project.path)
                self._content_browser._current = Path(project.path)
            except Exception:
                pass

        # Try to load the default scene off disk.
        default_scene = project.scenes_dir / "main.scene.yaml"
        if default_scene.is_file():
            self._scene_path = default_scene
            self._scene_name = default_scene.stem.replace(".scene", "")
            loader = getattr(self._engine, "load_scene", None)
            if callable(loader):
                try:
                    loader(default_scene)
                except TypeError:
                    # Engine.load_scene(scene: Scene) — path overload
                    # isn't implemented yet; tolerated.
                    pass
                except Exception:
                    pass
        else:
            self._scene_path = None
            self._scene_name = "main"

        # Mark clean now that we've loaded a fresh scene (or none).
        self.mark_clean()

        # Status-bar feedback.
        self._set_status(f"Loaded notebook: {project.metadata.name}")

        # Fire the scene_loaded event so the deer creature peeks in.
        try:
            from slappyengine.event_bus import get_default_bus

            get_default_bus().publish(
                "engine.scene_loaded",
                project_name=project.metadata.name,
                scene_path=str(default_scene) if default_scene.is_file() else None,
            )
        except Exception:
            pass

        # Register on the recents tracker.
        try:
            from slappyengine.projects import get_default_registry

            get_default_registry().register(project)
        except Exception:
            pass

    def save_scene(self) -> None:
        """Save the current scene to ``_scene_path``.

        Derives the path from ``project.scenes_dir / 'main.scene.yaml'``
        when ``_scene_path`` is unset. Calls ``engine.save_scene(path)``
        when available; otherwise writes a placeholder YAML stub so the
        Round-Trip "Open → Save" flow still produces a real file on
        disk. Marks the shell clean and fires ``engine.save`` on the
        event bus (butterfly_01.flutter binding).
        """
        if self._project is None:
            self._set_status("No project loaded")
            return

        if self._scene_path is None:
            self._scene_path = (
                self._project.scenes_dir / "main.scene.yaml"
            )

        path = self._scene_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # Prefer engine.save_scene when implemented; otherwise write a
        # minimal stub so the operation still produces an artefact.
        saver = getattr(self._engine, "save_scene", None)
        wrote = False
        if callable(saver):
            try:
                saver(path)
                wrote = True
            except Exception:
                wrote = False
        if not wrote:
            try:
                if not path.exists():
                    path.write_text(
                        f"# {self._scene_name}.scene.yaml — autosaved stub\n"
                        f"name: {self._scene_name}\n"
                        "layers: []\n",
                        encoding="utf-8",
                    )
            except Exception:
                pass

        self.mark_clean()
        self._set_status("Saved")
        try:
            from slappyengine.event_bus import get_default_bus

            get_default_bus().publish("engine.save", path=str(path))
        except Exception:
            pass

    def save_scene_as(self, path: Path | str | None = None) -> Path | None:
        """Save the current scene to a user-chosen path.

        When *path* is ``None`` the shell soft-imports :mod:`tkinter`
        and surfaces a native save dialog; tests pass an explicit path
        to drive the headless branch. Returns the saved path or
        ``None`` if cancelled.
        """
        if path is None:
            try:
                import tkinter as _tk  # noqa: F401
                from tkinter import filedialog

                chosen = filedialog.asksaveasfilename(
                    title="Save Scene As",
                    defaultextension=".scene.yaml",
                    filetypes=[("Scene", "*.scene.yaml"), ("YAML", "*.yaml")],
                )
            except Exception:
                chosen = ""
            if not chosen:
                return None
            path = Path(chosen)
        else:
            path = Path(path)

        self._scene_path = path
        self._scene_name = path.stem.replace(".scene", "") or "scene"
        self.save_scene()
        return path

    def open_scene(self, path: Path | str) -> None:
        """Load *path* into the engine and record it as the current scene.

        Warns via the status bar if *path* sits outside
        ``project.scenes_dir`` — the brief asks for the warning, not a
        hard refusal, since users sometimes pull scenes from sibling
        projects during prototyping.
        """
        path = Path(path)
        if not path.is_file():
            self._set_status(f"Scene not found: {path}")
            return

        if self._project is not None:
            try:
                scenes_root = self._project.scenes_dir.resolve()
                resolved = path.resolve()
                # ``Path.is_relative_to`` is 3.9+; the codebase targets
                # 3.10+ so we use it directly.
                if not resolved.is_relative_to(scenes_root):
                    self._set_status(
                        f"Warning: scene outside project.scenes_dir: {path}"
                    )
            except Exception:
                pass

        loader = getattr(self._engine, "load_scene", None)
        if callable(loader):
            try:
                loader(path)
            except TypeError:
                # Engine.load_scene(scene: Scene) — path overload
                # not yet implemented.
                pass
            except Exception:
                pass
        self._scene_path = path
        self._scene_name = path.stem.replace(".scene", "")
        self.mark_clean()
        self._set_status(f"Opened: {path.name}")

    def new_scene(self) -> None:
        """Reset the editor to a blank scene under the active project."""
        scene_new = getattr(self._engine, "new_scene", None)
        if callable(scene_new):
            try:
                scene_new()
            except Exception:
                pass
        self._scene_path = None
        self._scene_name = "untitled"
        self.mark_clean()

    def get_project_picker(self) -> "NotebookProjectPicker":
        """Return the lazily-constructed :class:`NotebookProjectPicker`."""
        if self._project_picker is None:
            from slappyengine.ui.editor.notebook_project_picker import (
                NotebookProjectPicker,
            )
            self._project_picker = NotebookProjectPicker(
                on_chosen=self.load_project,
            )
        return self._project_picker

    def switch_project(self) -> None:
        """Show the project picker, after offering to save dirty edits.

        Dirty state is best-effort: if the shell can't auto-save (no
        engine.save_scene, no scenes_dir, etc.) we still proceed to the
        picker so the user can recover.
        """
        if self.is_dirty():
            try:
                self.save_scene()
            except Exception:
                pass
        picker = self.get_project_picker()
        picker.show()

    def load_recent_project(self, index: int) -> None:
        """File → Recent Projects → N — open the N-th recents entry."""
        picker = self.get_project_picker()
        try:
            picker.pick_recent(index)
        except IndexError:
            self._set_status(f"No recent project at slot {index + 1}")
        except FileNotFoundError as exc:
            self._set_status(f"Recent project missing: {exc}")
        except Exception as exc:
            self._set_status(f"Open failed: {exc}")

    # ------------------------------------------------------------------
    # Keyboard shortcut actions
    # ------------------------------------------------------------------

    def _save_project(self) -> None:
        """Ctrl+S — save the current scene (project-aware).

        When a project is loaded, routes through :meth:`save_scene`.
        Falls back to the legacy ``engine._project_manager.save()`` hook
        for older fixtures that have not yet adopted the new flow.
        """
        if self._project is not None:
            self.save_scene()
            return
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

    # ------------------------------------------------------------------
    # Menu-bar actions (File / Edit / View / Help)
    # ------------------------------------------------------------------

    def menu_open_scene(self, path: str | None = None) -> bool:
        """File → Open Scene. Opens a file picker, then loads the chosen scene.

        When *path* is provided directly (tests / scripted use) the dialog
        is skipped. Returns ``True`` on success, ``False`` otherwise.

        Routes through :meth:`open_scene` when a project is loaded so the
        scenes-dir warning + dirty-bit reset land consistently. Falls back
        to the legacy ``engine.load_scene`` path otherwise.
        """
        if path is None:
            path = self._prompt_open_scene_path()
        if not path:
            self._set_status("Open Scene cancelled")
            return False
        # Project-aware path — open_scene handles the engine call + title.
        if self._project is not None:
            try:
                self.open_scene(path)
                return True
            except Exception as exc:
                self._set_status(f"Open Scene failed: {exc}")
                return False
        # Legacy path for tests / fixtures without a Project.
        loader = getattr(self._engine, "load_scene", None)
        if loader is None:
            self._set_status("Engine has no load_scene()")
            return False
        try:
            loader(path)
        except Exception as exc:
            self._set_status(f"Open Scene failed: {exc}")
            return False
        try:
            from pathlib import Path as _P
            self.set_scene_name(_P(path).stem, saved=True)
        except Exception:
            pass
        self._set_status(f"Opened {path}")
        return True

    def menu_save_scene(self) -> bool:
        """File → Save Scene. Calls ``engine.save_scene`` if present.

        Falls back to the project-manager save path so the menu and Ctrl+S
        share the same code-path. Also triggers a butterfly flutter via
        the creature bus when available.
        """
        saver = getattr(self._engine, "save_scene", None)
        ok = False
        if callable(saver):
            try:
                saver()
                ok = True
            except Exception as exc:
                self._set_status(f"Save Scene failed: {exc}")
                return False
        else:
            # Fall back to the project-manager path.
            project_manager = getattr(self._engine, "_project_manager", None)
            if project_manager is not None:
                try:
                    project_manager.save()
                    ok = True
                except Exception as exc:
                    self._set_status(f"Save failed: {exc}")
                    return False
        if not ok:
            self._set_status("Save Scene: no project loaded")
            return False
        # Status toast + butterfly flutter (best effort).
        if self._notebook_status_bar is not None:
            try:
                self._notebook_status_bar.set_message("Saved", kind="success")
                self._notebook_status_bar.set_save_state(True)
            except Exception:
                pass
        scheduler = self._creature_scheduler
        if scheduler is not None:
            try:
                scheduler.trigger("butterfly_01", "flutter")
            except Exception:
                pass
        self._scene_saved = True
        try:
            self._apply_window_title()
        except Exception:
            pass
        return True

    def menu_undo(self) -> bool:
        """Edit → Undo. Same surface as Ctrl+Z but always emits a status."""
        undo_manager = getattr(self._engine, "_undo_manager", None)
        if undo_manager is None:
            # Try engine.undo() shortcut as a secondary path.
            engine_undo = getattr(self._engine, "undo", None)
            if callable(engine_undo):
                try:
                    engine_undo()
                    self._set_status("Undo")
                    return True
                except Exception as exc:
                    self._set_status(f"Undo failed: {exc}")
                    return False
            self._set_status("Nothing to undo")
            return False
        try:
            undo_manager.undo()
            self._set_status("Undo")
            return True
        except Exception as exc:
            self._set_status(f"Undo failed: {exc}")
            return False

    def menu_reset_layout(self) -> bool:
        """View → Reset Layout. Restores the default panel docking.

        Best-effort: walks every known DPG panel tag and reconfigures
        its width/height to the constants defined at module scope. When
        DPG is missing this still emits a status message so the user
        knows the click registered.
        """
        try:
            import dearpygui.dearpygui as dpg
        except Exception:
            self._set_status("Reset Layout (DPG unavailable)")
            return False

        height = self._height
        width = self._width
        TITLEBAR_H = 28
        main_h = height - TITLEBAR_H - TOOLBAR_H - BOTTOM_H
        center_w = width - LEFT_W - RIGHT_W - 6

        # Reconfigure every known panel tag (best-effort; missing ones skip).
        for tag, w, h in (
            ("toolbar_row",   -1,       TOOLBAR_H),
            ("left_panel",    LEFT_W,   main_h),
            ("center_panel",  center_w, main_h),
            ("right_panel",   -1,       main_h),
            ("bottom_panel",  -1,       BOTTOM_H),
        ):
            try:
                if dpg.does_item_exist(tag):
                    dpg.configure_item(tag, width=w, height=h)
            except Exception:
                pass
        self._set_status("Layout reset")
        return True

    def menu_about(self) -> dict:
        """Help → About. Returns the about-info dict and shows a modal.

        Returning the dict (rather than only opening a window) lets tests
        verify the payload without driving DPG. The dict carries
        ``version``, ``engine_surface_url``, and ``codename`` keys.
        """
        try:
            from slappyengine import __version__ as _ver
        except Exception:
            _ver = "0.0.0"
        info = {
            "version": _ver,
            "engine_surface_url": (
                "https://github.com/andrewkwatts-maker/SlapPyEngine"
                "/blob/master/docs/engine_surface.md"
            ),
            "codename": "Notebook",
        }
        try:
            import dearpygui.dearpygui as dpg
            modal_tag = "menu_about_modal"
            if not dpg.does_item_exist(modal_tag):
                with dpg.window(
                    label="About SlapPy",
                    modal=True,
                    tag=modal_tag,
                    width=320,
                    height=160,
                ):
                    dpg.add_text(f"SlapPyEngine v{info['version']}")
                    dpg.add_text(f"Codename: {info['codename']}")
                    dpg.add_text("Engine surface:")
                    dpg.add_text(info["engine_surface_url"], wrap=300)
                    dpg.add_button(
                        label="Close",
                        callback=lambda *_: dpg.delete_item(modal_tag),
                    )
            else:
                try:
                    dpg.configure_item(modal_tag, show=True)
                except Exception:
                    pass
        except Exception:
            pass
        self._set_status(f"SlapPyEngine v{info['version']}")
        return info

    @staticmethod
    def _prompt_open_scene_path() -> str:
        """Open a Tk file dialog and return the chosen scene path.

        Returns an empty string when cancelled or when Tk is unavailable.
        Tk is used as the universal fallback because DPG's file dialog
        is opt-in and absent in many headless setups.
        """
        try:
            import tkinter as tk
            from tkinter import filedialog
        except Exception:
            return ""
        try:
            root = tk.Tk()
            root.withdraw()
            try:
                path = filedialog.askopenfilename(
                    title="Open Scene",
                    filetypes=[
                        ("Scene files", "*.scene *.json *.yaml *.yml"),
                        ("All files", "*.*"),
                    ],
                )
            finally:
                try:
                    root.destroy()
                except Exception:
                    pass
            return path or ""
        except Exception:
            return ""

    def _delete_selected(self) -> None:
        """Delete — remove the currently selected entity from the scene."""
        # NotebookOutliner pushes the selection through ``_on_entity_selected``,
        # which mirrors the live entity onto ``self._selected_entity``.
        selected = self._selected_entity
        if selected is None and self._scene_outliner is not None:
            # Legacy SceneOutliner exposes ``selected_entity`` directly —
            # keep the fallback so a non-notebook outliner still works.
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
