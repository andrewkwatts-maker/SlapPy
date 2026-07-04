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
    from slappyengine.ui.editor.movable_panel import MovablePanelWindow
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
        self._layer_panel = None
        self._tag_painter = None
        self._behavior_panel = None
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
        # Extra-surface notebook panels (hidden by default; toggleable
        # via the View menu). Constructed in :meth:`setup_notebook_panels`.
        self._telemetry_panel = None
        self._post_process_panel = None
        self._animation_panel = None
        self._theming_editor = None

        # ── User-override layer (loaded on setup) ──────────────────────────
        # Populated by :meth:`load_user_overrides`; consumers should treat
        # ``None`` as "no user overrides discovered yet".
        self._user_override_bundle = None

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

        # Movable panel wrappers — populated by :meth:`setup` (or by
        # tests calling :meth:`compose_default_panel_layout` directly).
        # Keyed by short panel name (``"toolbar"``, ``"outliner"``, …).
        self._panel_windows: dict[str, "MovablePanelWindow"] = {}

        # ── Snap + dock-zone live-drag managers ──────────────────────────
        # Constructed eagerly so `compose_default_panel_layout` can wire
        # each MovablePanelWindow against the same instances. The tick
        # loop polls each panel's DPG position per frame and applies
        # snap correction. SnapManager / DockZoneManager are pure-logic
        # modules; soft-import to keep the editor importable when one
        # is missing.
        try:
            from slappyengine.ui.editor.snap_manager import SnapManager
            self._snap_manager = SnapManager()
            self._snap_manager.set_viewport_size(self._width, self._height)
        except Exception:
            self._snap_manager = None
        try:
            from slappyengine.ui.editor.dock_zones import DockZoneManager
            self._dock_zones = DockZoneManager((self._width, self._height))
        except Exception:
            self._dock_zones = None
        # Last-known panel positions/sizes used to detect drag/resize in
        # the polled tick loop. Filled by `tick_subsystems`.
        self._last_panel_pos: dict[str, tuple[int, int]] = {}
        self._last_panel_size: dict[str, tuple[int, int]] = {}
        self._actively_dragging: str | None = None

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

        # ── Layout persistence ─────────────────────────────────────────────
        # The persistence layer is constructed lazily — falls back to the
        # user-wide ``~/.slappyengine/default_layout.yaml`` when no project
        # is loaded so the editor still remembers the user's chrome
        # before the project picker runs. ``_layout_state`` holds the
        # most recently applied layout so tests can verify what was
        # actually pushed without re-loading from disk.
        from slappyengine.ui.editor.layout_persistence import LayoutPersistence
        self._layout_persistence: LayoutPersistence = LayoutPersistence(None)
        self._layout_state = None  # type: ignore[assignment]

        # ── Diary shell — book-of-pages workspace ---------------------------
        # Constructed lazily via :meth:`get_diary_shell` so a plugin that
        # replaces the workspace layout can supply its own instance
        # before :meth:`setup` runs. Ctrl+Tab / Ctrl+Shift+Tab and per-
        # page ``editor.diary_switch_<id>`` commands are dispatched
        # through :meth:`_dispatch_editor_command`.
        self._diary_shell = None  # type: ignore[assignment]
        try:
            from slappyengine.ui.editor.diary_shell import DiaryShell
            self._diary_shell = DiaryShell(self)
            self._diary_shell.install_hotkeys(self._notebook_hotkeys)
        except Exception:
            self._diary_shell = None

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

        Every editor action ships as a :class:`ToolAction` in
        :data:`slappyengine.tool_router.REGISTRY`. This dispatcher
        builds a ``ctx`` dict from the current shell state (selection,
        active tool, project) and hands off to
        :meth:`ToolRouter.dispatch`. Unknown ids fall through to the
        legacy engine-hook probe so untracked host code can still fire
        arbitrary engine methods.

        Provenance: ``docs/tool_routing_2026_06_07.md`` — the tool
        routing contract this call site implements.
        """
        from slappyengine.tool_router import REGISTRY as _ROUTER

        local = command.split(".", 1)[1] if command.startswith("editor.") else command
        # Diary-shell page-cycling + direct-switch commands stay bespoke
        # — they route to a scoped sub-shell, not to a router action.
        if local.startswith("diary_"):
            diary = getattr(self, "_diary_shell", None)
            if diary is not None:
                try:
                    diary.dispatch_command(command)
                except Exception:
                    pass
            return
        # Prefer the tool router when the command is registered.
        if _ROUTER.has_action(command):
            ctx: dict[str, Any] = {
                "shell": self,
                "engine": self._engine,
                "selection": self._selected_entity,
                "active_tool": self._active_tool,
                "project": self._project,
            }
            try:
                _ROUTER.dispatch(command, ctx)
            except Exception:
                pass
            return
        # Legacy fallback path — engine hook probe.
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
    # Layout preset + window-management helpers
    # ------------------------------------------------------------------

    # Canonical theme cycle order — matches the welcome-screen swatch row.
    _THEME_CYCLE: tuple[str, ...] = (
        "teengirl_notebook",
        "cozy_diary",
        "bullet_journal",
        "scrapbook_summer",
        "cottagecore_garden",
        "kawaii_planner",
    )

    def apply_layout_preset(self, preset_name: str) -> None:
        """View → Layout Presets → *preset_name*. Reshape every panel.

        Routes through :func:`apply_preset` so the preset's panel-state
        dict lands on ``self._panel_layout_state`` and any DPG windows
        are reconfigured. Pushes a status toast naming the preset for
        ambient feedback.
        """
        from slappyengine.ui.editor.layout_presets import apply_preset

        try:
            preset = apply_preset(self, preset_name)
        except KeyError:
            self._set_status(f"Unknown layout preset: {preset_name}")
            return
        if self._notebook_status_bar is not None:
            try:
                self._notebook_status_bar.set_message(
                    f"Preset: {preset.name}", kind="info",
                )
            except Exception:
                pass

    def reset_layout(self) -> None:
        """Ctrl+0 / View → Reset Layout — drop persisted state, re-apply Default.

        Resets every persistence layer at once:

        * the in-memory ``_panel_layout_state`` cache used by the
          preset / toggle pipeline,
        * the legacy ``<project>/layout.yaml`` file written by the older
          preset implementation, and
        * the new ``<project>/.slappy/layout.yaml`` snapshot produced by
          :class:`LayoutPersistence` (or the user-wide fallback when no
          project is loaded).

        Then re-applies the canonical Default preset followed by the
        notebook-family :data:`DEFAULT_LAYOUT` so both subsystems agree
        on the chrome.
        """
        # Clear any cached panel state.
        self._panel_layout_state: dict = {}
        # Best-effort delete of the legacy ``project/layout.yaml`` path.
        project = self._project
        if project is not None:
            try:
                legacy = project.path / "layout.yaml"
                if legacy.is_file():
                    legacy.unlink()
            except Exception:
                pass
        # Drop the new ``.slappy/layout.yaml`` snapshot.
        persistence = getattr(self, "_layout_persistence", None)
        if persistence is not None:
            try:
                persistence.reset()
            except Exception:
                pass
        # Re-apply the legacy preset (drives layout_presets / DPG menus).
        try:
            self.apply_layout_preset("default")
        except Exception:
            pass
        # Re-apply the new notebook-family default so panel state lands
        # consistently on both subsystems.
        if persistence is not None:
            try:
                from slappyengine.ui.editor.default_layouts import (
                    DEFAULT_LAYOUT,
                )

                persistence.apply_to_shell(self, DEFAULT_LAYOUT)
            except Exception:
                pass
        try:
            self._set_status("Layout reset")
        except Exception:
            pass

    def toggle_panel(self, panel_id: str) -> bool:
        """Toggle the visibility of *panel_id* in the active layout state.

        Updates ``self._panel_layout_state[panel_id].visible`` and best-
        effort calls ``dpg.configure_item(tag, show=...)`` on the
        matching DPG window tag. Returns the new ``visible`` value.

        The viewport panel is special-cased: it's always visible (the
        wrapper is built with ``no_close=True``) so toggling is a no-op
        that reports the panel as still visible.
        """
        from slappyengine.ui.editor.layout_presets import PanelLayoutState

        # Viewport is always visible — never hide the GPU canvas.
        if panel_id == "viewport_panel":
            if self._notebook_status_bar is not None:
                try:
                    self._notebook_status_bar.set_message(
                        "viewport: always visible", kind="info",
                    )
                except Exception:
                    pass
            return True

        state_dict = getattr(self, "_panel_layout_state", None)
        if not isinstance(state_dict, dict):
            state_dict = {}
            self._panel_layout_state = state_dict
        # Resolve the wrapper *before* mutating state so we can seed the
        # initial PanelLayoutState.visible from the wrapper's current
        # visibility — otherwise toggling a hidden panel for the first
        # time would re-hide it (the default visible=True flips to False).
        existing_wrapper = self._panel_windows.get(panel_id) if isinstance(
            self._panel_windows, dict,
        ) else None
        current = state_dict.get(panel_id)
        if current is None:
            seed_visible = True
            if existing_wrapper is not None:
                try:
                    seed_visible = bool(existing_wrapper.is_visible())
                except Exception:
                    pass
            # Placeholder geometry so the canonical PanelLayoutState
            # validator accepts the construction; the real geometry
            # arrives the next time the user applies a preset.
            current = PanelLayoutState(
                panel_id=panel_id, position=(0, 0), size=(100, 100),
                visible=seed_visible,
            )
            state_dict[panel_id] = current
        current.visible = not current.visible
        tag_map = {
            "toolbar":         "toolbar_row",
            "outliner":        "scene_tab_body",
            "viewport":        "viewport_area",
            "inspector":       "details_tab_body",
            "content_browser": "bottom_panel",
            "code":            "code_mode_area",
            "status_bar":      "status_bar",
        }
        # Movable-panel wrappers are the canonical home for every
        # panel that owns its own dpg.window — outliner, inspector,
        # status bar, plus the Nova3D-legacy panels surfaced via
        # ``register_panel``. Resolve from the wrapper registry first
        # so the wrapper's tracked ``_visible`` flag stays the source
        # of truth; fall back to the hard-coded tag_map for panels
        # that are still embedded as child-windows.
        wrapper = self._panel_windows.get(panel_id)
        tag: str | None = None
        if wrapper is not None:
            try:
                tag = wrapper.get_window_tag()
                if current.visible:
                    wrapper.show()
                else:
                    wrapper.hide()
            except Exception:
                pass
        else:
            tag = tag_map.get(panel_id)
        # Gate on _running because ``dpg.does_item_exist`` segfaults
        # without a context.
        if tag is not None and getattr(self, "_running", False):
            try:
                import dearpygui.dearpygui as dpg
                if dpg.does_item_exist(tag):
                    dpg.configure_item(tag, show=current.visible)
                    # Showing the panel pops it above its neighbours
                    # — issue show_item + focus_item so it's actually
                    # raised, not just toggled in DPG bookkeeping.
                    if current.visible:
                        try:
                            dpg.show_item(tag)
                        except Exception:
                            pass
                        try:
                            dpg.focus_item(tag)
                        except Exception:
                            pass
            except Exception:
                pass
        if self._notebook_status_bar is not None:
            try:
                state_str = "shown" if current.visible else "hidden"
                self._notebook_status_bar.set_message(
                    f"{panel_id}: {state_str}", kind="info",
                )
            except Exception:
                pass
        return current.visible

    def toggle_theme_switcher(self) -> None:
        """Ctrl+T — open / focus the theme switcher panel."""
        self._open_theme_switcher()

    def cycle_theme(self) -> str:
        """Ctrl+Shift+T — rotate to the next diary theme. Returns its id."""
        current = self._ui_settings.default_theme
        cycle = self._THEME_CYCLE
        try:
            idx = cycle.index(current)
        except ValueError:
            idx = -1
        next_theme = cycle[(idx + 1) % len(cycle)]
        try:
            from slappyengine.ui.theme import apply_theme

            apply_theme(next_theme)
        except Exception:
            pass
        self._ui_settings.default_theme = next_theme
        if self._notebook_status_bar is not None:
            try:
                self._notebook_status_bar.set_active_theme_name(next_theme)
                self._notebook_status_bar.set_message(
                    f"Theme: {next_theme}", kind="info",
                )
            except Exception:
                pass
        return next_theme

    def toggle_fullscreen(self) -> None:
        """F11 — flip DPG viewport between maximised and windowed."""
        if not hasattr(self, "_fullscreen"):
            self._fullscreen = False
        self._fullscreen = not self._fullscreen
        # Gate on _running — DPG viewport calls segfault without a context.
        if not getattr(self, "_running", False):
            return
        try:
            import dearpygui.dearpygui as dpg

            try:
                dpg.toggle_viewport_fullscreen()
            except Exception:
                # Older DPG builds — fall back to maximise/restore.
                try:
                    if self._fullscreen:
                        dpg.maximize_viewport()
                    else:
                        dpg.minimize_viewport()
                except Exception:
                    pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Diary-shell accessor
    # ------------------------------------------------------------------

    def get_diary_shell(self):
        """Return the :class:`DiaryShell` orchestrating the tabbed pages.

        Constructed eagerly in ``__init__`` — this getter exists so the
        callable surface stays symmetric with the other subsystem
        accessors (``get_notebook_hotkeys`` etc.). Returns ``None`` when
        the module import failed at construction time.
        """
        return self._diary_shell

    # ------------------------------------------------------------------
    # Panel registration
    # ------------------------------------------------------------------

    def register_panel(self, panel) -> None:
        """Register *panel* on the shell so the layout composer can place it.

        Two registration paths run side-by-side:

        * The panel is appended to ``self._panels`` (the legacy details-
          sidebar list). External callers that walk this list to inject
          custom rendering continue to work.
        * The panel is routed to a *named slot* on the shell when its
          class matches a known kind — ``LayerPanel`` /
          ``ViewportPanel`` / ``TagPainter`` / ``BehaviorPanel`` /
          ``NotebookInspector`` / ``NotebookMaterialEditor``. The slots
          are read by :meth:`compose_default_panel_layout` to build a
          :class:`MovablePanelWindow` for each, so every legacy panel
          ends up with its own movable, themed, snappable dpg.window
          instead of being trapped inside the primary ``editor_root``
          child window.

        Parameters
        ----------
        panel:
            Any object that implements ``build(parent_tag: str | int) -> None``.
        """
        self._panels.append(panel)

        # ── Route well-known panel types into named slots. The check is
        # by class name string so we never import the panel module here
        # — keeping :mod:`slappyengine.ui.editor.shell` import-cheap.
        cls_name = type(panel).__name__
        slot_map = {
            "LayerPanel": "_layer_panel",
            "ViewportPanel": "_viewport_panel",
            "TagPainter": "_tag_painter",
            "BehaviorPanel": "_behavior_panel",
            "NotebookInspector": "_inspector",
            "NotebookMaterialEditor": "_material_editor",
        }
        slot = slot_map.get(cls_name)
        if slot is not None and getattr(self, slot, None) is None:
            try:
                setattr(self, slot, panel)
            except Exception:
                pass

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

    # ------------------------------------------------------------------
    # User overrides — ~/.slappyengine/ui/
    # ------------------------------------------------------------------

    def load_user_overrides(self) -> None:
        """Discover + fold user overrides from ``~/.slappyengine/ui/``.

        Called from :meth:`setup` after the built-in notebook panels are
        constructed so user panels can layer on top. Never raises — the
        :class:`UserOverrideLoader` logs individual file failures and
        the shell degrades to a base editor when the whole load fails.

        Behaviour
        ---------

        * User panels are handed to :meth:`register_panel` and stashed
          on ``self._user_override_bundle.panels`` for a subsequent
          "View > User" submenu.
        * Hotkey bindings are merged into
          :attr:`NotebookHotkeys.BINDINGS` (user entries win on
          collision).
        * Hotkey commands (``user.<name>()``) are wrapped into a
          fallback dispatcher chained through
          :meth:`_dispatch_notebook_command`.
        * Spawn actions are appended to the SPAWN menu module.
        * WGSL shaders are handed to the matching theme registry.
        """
        try:
            from slappyengine.ui.user_overrides import UserOverrideLoader
        except Exception:
            return

        loader = UserOverrideLoader()
        try:
            loader.ensure_scaffolded()
        except Exception:
            pass
        try:
            bundle = loader.load_all()
        except Exception:
            return

        self._user_override_bundle = bundle

        # Panels — register on the shell so the layout composer can pick
        # them up. If the panel does not implement ``build`` it will
        # simply be skipped by the compositor — that's fine.
        for panel in bundle.panels:
            try:
                self.register_panel(panel)
            except Exception:
                pass

        # Hotkeys — merge into the class-level BINDINGS. User keys win.
        if bundle.hotkey_bindings:
            try:
                self._notebook_hotkeys.BINDINGS.update(bundle.hotkey_bindings)
            except Exception:
                pass

        # Spawn actions — extend ``spawn_menu.SPAWN_ACTIONS`` if we have
        # it wired up already.
        if bundle.spawn_actions:
            try:
                from slappyengine.ui.editor import spawn_menu as _sm
                for card in bundle.spawn_actions:
                    _sm.SPAWN_ACTIONS.append(card)
            except Exception:
                pass

        # Shaders — hand each to the correct registry by kind.
        if bundle.shaders:
            self._register_user_shaders(bundle)

    def _register_user_shaders(self, bundle) -> None:  # type: ignore[no-untyped-def]
        """Route ``bundle.shaders`` into the theme registries by kind."""
        for shader_id, wgsl in bundle.shaders.items():
            kind = bundle.shader_kinds.get(shader_id, "")
            try:
                if kind == "page_linings":
                    from slappyengine.ui.theme.page_linings.library import (
                        PAGE_LININGS, LiningStyle,
                    )
                    PAGE_LININGS[shader_id] = LiningStyle(  # type: ignore[call-arg]
                        style_id=shader_id,
                        display_name=shader_id,
                        wgsl_source=wgsl,
                    )
                elif kind == "washi_tape":
                    from slappyengine.ui.theme.washi_tape.library import (
                        WASHI_TAPES, WashiTapeStyle,
                    )
                    WASHI_TAPES[shader_id] = WashiTapeStyle(
                        id=shader_id,
                        display_name=shader_id,
                        wgsl_source=wgsl,
                    )
                elif kind == "edge_strokes":
                    from slappyengine.ui.theme.edge_strokes.library import (
                        EDGE_STROKES, EdgeStrokeStyle,
                    )
                    EDGE_STROKES[shader_id] = EdgeStrokeStyle(
                        style_id=shader_id,
                        thickness_px=1.0,
                        alpha=1.0,
                        wgsl_source=wgsl,
                    )
            except Exception:
                # Never let a broken registry hijack editor startup.
                continue

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

        # ── Extra-surface panels (hidden by default; toggleable via View menu)
        if self._telemetry_panel is None:
            try:
                from slappyengine.ui.editor.notebook_telemetry_panel import (
                    NotebookTelemetryPanel,
                )
                self._telemetry_panel = NotebookTelemetryPanel()
            except Exception:
                self._telemetry_panel = None

        if self._post_process_panel is None:
            try:
                from slappyengine.ui.editor.notebook_post_process_panel import (
                    NotebookPostProcessPanel,
                )
                self._post_process_panel = NotebookPostProcessPanel()
            except Exception:
                self._post_process_panel = None

        if self._animation_panel is None:
            try:
                from slappyengine.ui.editor.notebook_animation_panel import (
                    NotebookAnimationPanel,
                )
                self._animation_panel = NotebookAnimationPanel()
            except Exception:
                self._animation_panel = None

        if self._theming_editor is None:
            try:
                from slappyengine.ui.editor.notebook_theming_editor import (
                    NotebookThemingEditor,
                )
                self._theming_editor = NotebookThemingEditor()
            except Exception:
                self._theming_editor = None

    def compose_default_panel_layout(self) -> dict[str, "MovablePanelWindow"]:
        """Build the default :class:`MovablePanelWindow` set + sensible dock positions.

        Headless-safe: every wrapper is just a Python object. The
        wrappers are not built (no DPG calls) until :meth:`setup` runs.

        Layout policy (defaults track the editor's primary viewport
        size — see ``self._width`` / ``self._height``):

        * **toolbar** — top edge, full-width, fixed height, no resize.
        * **outliner** — left dock under the toolbar.
        * **inspector** — right dock under the toolbar.
        * **content_browser** — bottom dock, full-width.
        * **status_bar** — very bottom, full-width, fixed height,
          no resize.
        * **code_panel** — floating centre, hidden by default.
        * **spawn_menu** — modal floating centre, hidden by default.
        * **material_editor** — right dock alternative, hidden by
          default.
        * **theme_switcher** — floating centre-right, hidden by
          default.
        * **welcome** — modal, hidden by default.
        * **project_picker** — modal, hidden by default.

        Returns the dict so callers can chain follow-up layout edits.
        """
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        windows: dict[str, "MovablePanelWindow"] = {}

        w = self._width
        h = self._height
        TITLEBAR_H = 28
        # The notebook-themed status bar sits a fixed 24 px tall.
        STATUS_H = 24

        # ── Toolbar — top edge, full width.
        if self._toolbar is not None:
            windows["toolbar"] = MovablePanelWindow(
                self._toolbar,
                title="Toolbar",
                kind="toolbar",
                default_pos=(0, TITLEBAR_H),
                default_size=(max(800, w), TOOLBAR_H),
                min_size=(800, TOOLBAR_H),
                closable=False,
                no_resize=True,  # fixed height
            )

        # ── Outliner — left dock.
        if self._scene_outliner is not None:
            outliner_y = TITLEBAR_H + TOOLBAR_H
            outliner_h = max(300, h - outliner_y - BOTTOM_H - STATUS_H)
            windows["outliner"] = MovablePanelWindow(
                self._scene_outliner,
                title="Scene",
                kind="sidebar",
                default_pos=(0, outliner_y),
                default_size=(max(240, LEFT_W), outliner_h),
                min_size=(240, 300),
                closable=False,
            )

        # ── Inspector — right dock.
        if self._inspector is not None:
            insp_x = max(0, w - RIGHT_W)
            insp_y = TITLEBAR_H + TOOLBAR_H
            insp_h = max(400, h - insp_y - BOTTOM_H - STATUS_H)
            windows["inspector"] = MovablePanelWindow(
                self._inspector,
                title="Inspector",
                kind="sidebar",
                default_pos=(insp_x, insp_y),
                default_size=(max(280, RIGHT_W), insp_h),
                min_size=(280, 400),
                closable=False,
            )

        # ── Content browser — bottom dock.
        if self._content_browser is not None:
            cb_y = max(0, h - BOTTOM_H - STATUS_H)
            windows["content_browser"] = MovablePanelWindow(
                self._content_browser,
                title="Notebook",
                kind="sidebar",
                default_pos=(0, cb_y),
                default_size=(max(320, w), BOTTOM_H),
                min_size=(320, 180),
                closable=False,
            )

        # ── Code panel — floating, hidden by default.
        if self._code_mode_panel is not None:
            cp = MovablePanelWindow(
                self._code_mode_panel,
                title="Code",
                kind="code_pane",
                default_pos=(max(0, (w - 720) // 2), max(0, (h - 480) // 2)),
                default_size=(720, 480),
                min_size=(480, 320),
                closable=True,
            )
            cp.hide()
            windows["code_panel"] = cp

        # ── Spawn menu — modal floating, hidden by default.
        spawn = getattr(self, "_spawn_menu_panel", None)
        if spawn is not None:
            sm = MovablePanelWindow(
                spawn,
                title="+ Add",
                kind="modal",
                default_pos=(max(0, (w - 700) // 2), max(0, (h - 500) // 2)),
                default_size=(700, 500),
                min_size=(600, 400),
                closable=True,
                modal=True,
            )
            sm.hide()
            windows["spawn_menu"] = sm

        # ── Material editor — right-dock alternative, hidden by default.
        mat = getattr(self, "_material_editor", None)
        if mat is not None:
            me = MovablePanelWindow(
                mat,
                title="Material",
                kind="sidebar",
                default_pos=(max(0, w - RIGHT_W), TITLEBAR_H + TOOLBAR_H),
                default_size=(max(280, RIGHT_W), 500),
                min_size=(280, 400),
                closable=True,
            )
            me.hide()
            windows["material_editor"] = me

        # ── Theme switcher — floating, hidden by default.
        if self._theme_switcher_panel is not None:
            ts = MovablePanelWindow(
                self._theme_switcher_panel,
                title="Theme",
                kind="sidebar",
                default_pos=(max(0, w - 320), TITLEBAR_H + TOOLBAR_H + 200),
                default_size=(300, 380),
                min_size=(280, 360),
                closable=True,
            )
            ts.hide()
            windows["theme_switcher"] = ts

        # ── Telemetry stream viewer — floating, hidden by default.
        telemetry_panel = getattr(self, "_telemetry_panel", None)
        if telemetry_panel is not None:
            tp = MovablePanelWindow(
                telemetry_panel,
                title="Telemetry",
                kind="sidebar",
                default_pos=(max(0, w - 420), TITLEBAR_H + TOOLBAR_H + 60),
                default_size=(400, 320),
                min_size=(360, 240),
                closable=True,
            )
            tp.hide()
            windows["telemetry_panel"] = tp

        # ── Post-process chain editor — floating, hidden by default.
        pp_panel = getattr(self, "_post_process_panel", None)
        if pp_panel is not None:
            pp = MovablePanelWindow(
                pp_panel,
                title="Post-Process",
                kind="sidebar",
                default_pos=(max(0, w - 380), TITLEBAR_H + TOOLBAR_H + 100),
                default_size=(360, 360),
                min_size=(320, 280),
                closable=True,
            )
            pp.hide()
            windows["post_process_panel"] = pp

        # ── Animation timeline / curve editor — floating, hidden by default.
        anim_panel = getattr(self, "_animation_panel", None)
        if anim_panel is not None:
            ap = MovablePanelWindow(
                anim_panel,
                title="Timeline",
                kind="default",
                default_pos=(max(0, (w - 520) // 2), max(0, h - 380)),
                default_size=(520, 320),
                min_size=(420, 320),
                closable=True,
            )
            ap.hide()
            windows["animation_panel"] = ap

        # ── Theming editor — floating, hidden by default (Ctrl+Shift+P).
        theming_editor = getattr(self, "_theming_editor", None)
        if theming_editor is not None:
            te = MovablePanelWindow(
                theming_editor,
                title="Theming",
                kind="sidebar",
                default_pos=(max(0, (w - 460) // 2), max(0, (h - 540) // 2)),
                default_size=(460, 540),
                min_size=(420, 480),
                closable=True,
            )
            te.hide()
            windows["theming_editor"] = te

        # ── Status bar — very bottom edge, full width, fixed height.
        # ``no_move=True`` so the user can't accidentally drag the
        # ambient-feedback strip off-screen, and ``no_title_bar=True``
        # so it visually reads as a footer instead of a window.
        if self._notebook_status_bar is not None:
            windows["status_bar"] = MovablePanelWindow(
                self._notebook_status_bar,
                title="Status",
                kind="status_bar",
                default_pos=(0, max(0, h - STATUS_H)),
                default_size=(max(400, w), STATUS_H),
                min_size=(400, STATUS_H),
                closable=False,
                no_move=True,
                no_resize=True,
                no_title_bar=True,
            )

        # ── Welcome — modal, hidden by default (shown on first-run only).
        if self._welcome_panel is not None:
            wl = MovablePanelWindow(
                self._welcome_panel,
                title="Welcome",
                kind="modal",
                default_pos=(max(0, (w - 600) // 2), max(0, (h - 500) // 2)),
                default_size=(600, 500),
                min_size=(600, 500),
                closable=True,
                modal=True,
                no_resize=True,
            )
            wl.hide()
            windows["welcome"] = wl

        # ── Project picker — modal, hidden by default.
        picker = self._project_picker
        if picker is not None:
            pp = MovablePanelWindow(
                picker,
                title="Pick a notebook",
                kind="modal",
                default_pos=(max(0, (w - 520) // 2), max(0, (h - 460) // 2)),
                default_size=(520, 460),
                min_size=(480, 420),
                closable=True,
                modal=True,
                no_resize=True,
            )
            pp.hide()
            windows["project_picker"] = pp

        # ── Nova3D-legacy panels — wrapped so they get docking + snap
        # behaviour like the notebook panels. Each is opt-in via the
        # View menu (or hotkey toggle); only the viewport is shown by
        # default because the GPU surface always needs an anchor.
        top_y = TITLEBAR_H + TOOLBAR_H
        sidebar_height = max(400, h - top_y - BOTTOM_H - STATUS_H)
        # The center column lives between the left + right docks.
        center_width = max(320, w - max(240, LEFT_W) - max(280, RIGHT_W) - 16)

        # Layer panel — narrow side-strip below the outliner; hidden by
        # default because the layer stack is niche compared to the
        # outliner/inspector pair.
        if self._layer_panel is not None:
            lp = MovablePanelWindow(
                self._layer_panel,
                title="Layers",
                kind="sidebar",
                default_pos=(0, top_y + 320),
                default_size=(260, 200),
                min_size=(240, 160),
                closable=True,
            )
            lp.hide()
            windows["layer_panel"] = lp

        # Viewport — the GPU canvas, anchored centre-stage. Always
        # visible; the close button is suppressed so users can't
        # accidentally dismiss the world view.
        if self._viewport_panel is not None:
            vp = MovablePanelWindow(
                self._viewport_panel,
                title="Viewport",
                kind="viewport",
                default_pos=(max(240, LEFT_W) + 8, top_y),
                default_size=(center_width, sidebar_height),
                min_size=(320, 320),
                closable=False,
            )
            windows["viewport_panel"] = vp

        # Tag painter — opt-in tool; tucked to the right-ish edge under
        # the inspector and hidden until requested.
        if self._tag_painter is not None:
            tp = MovablePanelWindow(
                self._tag_painter,
                title="Tag Painter",
                kind="sidebar",
                default_pos=(max(0, w - 280), top_y + 250),
                default_size=(280, 250),
                min_size=(260, 220),
                closable=True,
            )
            tp.hide()
            windows["tag_painter"] = tp

        # Behavior panel — AI-assisted scripting; floats over the
        # workspace because it's a heavyweight modal-ish tool.
        if self._behavior_panel is not None:
            bp = MovablePanelWindow(
                self._behavior_panel,
                title="Behavior",
                kind="default",
                default_pos=(
                    max(0, (w - 480) // 2),
                    max(0, (h - 320) // 2),
                ),
                default_size=(480, 320),
                min_size=(420, 280),
                closable=True,
            )
            bp.hide()
            windows["behavior_panel"] = bp

        # ── Catch-all wrap for any panel registered via ``register_panel``
        # that didn't land on a named slot. Without this loop, custom
        # plugin panels (or future panel classes the slot_map doesn't
        # know about) end up appended to ``self._panels`` and never
        # actually rendered. Wrap each into a floating, hidden-by-
        # default movable window so users can summon them via the View
        # menu / hotkeys.
        known_panel_objects: set[int] = set()
        for w_known in windows.values():
            try:
                known_panel_objects.add(id(w_known.panel))
            except Exception:
                pass
        # Status bar is reachable via ``self._notebook_status_bar`` and
        # owns its own wrapper; never re-wrap.
        if self._notebook_status_bar is not None:
            known_panel_objects.add(id(self._notebook_status_bar))
        legacy_y = TITLEBAR_H + TOOLBAR_H + 40
        legacy_x = max(0, w - 360)
        legacy_offset = 0
        for legacy in list(self._panels):
            if legacy is None:
                continue
            if id(legacy) in known_panel_objects:
                continue
            cls_name = type(legacy).__name__
            # Derive a stable short key from the class name.
            key = cls_name.lower()
            if key in windows:
                # Already taken — fall back to an id-tagged key.
                key = f"{key}_{id(legacy) & 0xFFFF:04x}"
            try:
                wrapper = MovablePanelWindow(
                    legacy,
                    title=cls_name,
                    kind="sidebar",
                    default_pos=(legacy_x, legacy_y + legacy_offset),
                    default_size=(320, 280),
                    min_size=(280, 200),
                    closable=True,
                )
            except Exception:
                continue
            wrapper.hide()
            windows[key] = wrapper
            known_panel_objects.add(id(legacy))
            legacy_offset += 24

        self._panel_windows = windows

        # Register each movable window with the SnapManager so dragging
        # one snaps against the others. The SnapManager expects an object
        # exposing `.tag`, `.x`, `.y`, `.width`, `.height` — adapt each
        # MovablePanelWindow on the fly via a tiny duck.
        if self._snap_manager is not None:
            for short_name, win in windows.items():
                tag = getattr(win, "_window_tag", None) or getattr(
                    win, "window_tag", None
                )
                if tag is None:
                    continue
                pos = win.get_position() if hasattr(win, "get_position") else (0, 0)
                size = win.get_size() if hasattr(win, "get_size") else (0, 0)
                try:
                    from dataclasses import dataclass, field

                    class _PanelHandle:
                        __slots__ = ("tag", "x", "y", "width", "height")

                        def __init__(self, tag, x, y, w, h):
                            self.tag = tag
                            self.x = x
                            self.y = y
                            self.width = w
                            self.height = h

                    self._snap_manager.register_panel(
                        _PanelHandle(tag, pos[0], pos[1], size[0], size[1])
                    )
                except Exception:
                    pass
        return windows

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

        # ── User-override layer — ~/.slappyengine/ui/ ─────────────────────
        # Loaded AFTER the built-in panels + spawn menu are wired so user
        # panels layer on top and user spawn cards land alongside the
        # built-in deck. Never raises — see ``load_user_overrides``.
        try:
            self.load_user_overrides()
        except Exception:
            pass

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
        # Tell the DPG theme bridge that a context is up so it stops
        # routing every call through the headless stub. The bridge will
        # rebuild the global theme handle here too.
        try:
            from slappyengine.ui.theme.dpg_bridge import (
                apply_theme_to_dpg,
                mark_dpg_context_ready,
            )
            from slappyengine.ui.theme import get_active_theme

            mark_dpg_context_ready(True)
            try:
                apply_theme_to_dpg(get_active_theme())
            except Exception:
                pass
        except Exception:
            pass

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
                    label="New Diary Page",
                    tag="menu_new_diary_page",
                    callback=lambda *_: self.new_diary_page(),
                )
                dpg.add_menu_item(
                    label="Open Diary Page...",
                    tag="menu_open_diary_page",
                    callback=lambda *_: self.open_diary_page(),
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
                    shortcut="Ctrl+0",
                    callback=lambda *_: self.menu_reset_layout(),
                )
                # ── Layout Presets submenu ───────────────────────────
                with dpg.menu(
                    label="Layout Presets",
                    tag="menu_layout_presets",
                ):
                    self._populate_layout_presets_menu()
                # ── Nova3D-legacy panel toggles ──────────────────────
                dpg.add_separator()
                dpg.add_menu_item(
                    label="Show Layer Panel",
                    tag="menu_show_layer_panel",
                    callback=lambda *_: self.toggle_panel("layer_panel"),
                )
                dpg.add_menu_item(
                    label="Show Tag Painter",
                    tag="menu_show_tag_painter",
                    callback=lambda *_: self.toggle_panel("tag_painter"),
                )
                dpg.add_menu_item(
                    label="Show Behavior Panel",
                    tag="menu_show_behavior_panel",
                    callback=lambda *_: self.toggle_panel("behavior_panel"),
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

        # ── Background primary window ─────────────────────────────────────
        # The legacy ``editor_root`` window now serves as a *background*
        # container only — the panels themselves are individual
        # :class:`MovablePanelWindow` instances and own their own
        # dpg.window with no_move=False / no_resize=False. Keeping the
        # background window around means downstream code that looks for
        # the ``editor_root`` / ``custom_titlebar`` / ``status_bar``
        # tags still works.
        with dpg.window(
            tag="editor_root",
            no_title_bar=True,
            no_resize=True,
            no_move=True,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        ):
            dpg.add_group(tag="custom_titlebar")
            dpg.add_text("Ready", tag="status_bar", color=(150, 150, 150))

        # ── Lazy code-mode-panel construction (needs the engine handle).
        if self._code_mode_panel is None:
            try:
                from slappyengine.ui.editor.code_mode_panel import (
                    CodeModePanel,
                )

                self._code_mode_panel = CodeModePanel(self._engine)
                if self._content_browser is not None:
                    self._content_browser.set_on_open_script(
                        self._code_mode_panel.load_script
                    )
            except Exception:
                pass

        # ── Movable panel windows — each panel becomes its own
        # ── floating, themed, resizable dpg.window. Toolbar +
        # ── status-bar windows pin ``no_resize=True``; sidebars
        # ── + modals are fully movable + resizable.
        self.compose_default_panel_layout()
        for window in self._panel_windows.values():
            try:
                window.build()
            except Exception:
                pass

        # ── DiaryShell — build the index-tab strip + activate first page ──
        # After every wrapper is built we can safely flip visibility on
        # them. DiaryShell.build() picks the first registered page as
        # the initial active page, hiding every panel that doesn't
        # belong there.
        diary = getattr(self, "_diary_shell", None)
        if diary is not None:
            try:
                diary.build()
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

        # ── Per-frame panel drag polling ──────────────────────────────────
        # DPG handles drag/resize natively via the window title bar +
        # corners. We poll each panel's current position/size against the
        # last-known values; when they change we hand off to SnapManager
        # to compute a snapped position and write it back via DPG.
        self._tick_panel_drag()

        # Snap-guide + dock-zone live-feedback overlay. Runs every
        # frame so the moment a drag ends the overlay is cleared on
        # the next tick; cheap when no drag is in flight.
        self._render_drag_overlay()

        # ── Status-bar live signals ────────────────────────────────────────
        if self._notebook_status_bar is not None:
            try:
                self._notebook_status_bar.tick(dt)
            except Exception:
                pass
            # FPS + mouse queries require an active DPG context (segfault
            # on Windows otherwise), so gate them on _running.
            if self._running:
                try:
                    import dearpygui.dearpygui as dpg
                    dt_dpg = dpg.get_delta_time()
                    if dt_dpg > 1e-6:
                        self._notebook_status_bar.set_fps(1.0 / dt_dpg)
                    mx, my = dpg.get_mouse_pos(local=False)
                    self._notebook_status_bar.set_world_cursor(int(mx), int(my))
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Live drag overlay — snap guides + dock zone previews
    # ------------------------------------------------------------------

    #: DPG tag for the lazily-created viewport drawlist that hosts the
    #: snap-guide lines and the dock-zone preview rectangles. Lives in
    #: front of every panel so the user sees feedback while dragging.
    _OVERLAY_DRAWLIST_TAG: str = "editor_drag_overlay"

    def _ensure_overlay_drawlist(self) -> str:
        """Lazily create the viewport drawlist used by :meth:`_render_drag_overlay`.

        Returns the drawlist tag. Headless-safe: if Dear PyGui can't be
        imported, or if the drawlist creation fails (no live context),
        the constant tag is still returned so callers can swallow
        downstream errors uniformly.
        """
        tag = self._OVERLAY_DRAWLIST_TAG
        try:
            import dearpygui.dearpygui as dpg
        except Exception:
            return tag
        try:
            if dpg.does_item_exist(tag):
                return tag
        except Exception:
            return tag
        try:
            dpg.add_viewport_drawlist(front=True, tag=tag)
        except Exception:
            # Headless / no viewport — fall through; caller will skip
            # subsequent draw calls when they raise.
            pass
        return tag

    def _get_active_theme(self):
        """Return the active :class:`ThemeSpec`, or ``None`` if unavailable.

        Wrapped so the overlay can fetch the accent colour without
        crashing in CI runs that never registered any starter themes
        (e.g. tests that instantiate :class:`EditorShell` directly).
        """
        try:
            from slappyengine.ui.theme import get_active_theme
            return get_active_theme()
        except Exception:
            return None

    def _render_drag_overlay(self) -> None:
        """Render snap guides + dock-zone previews on the live viewport.

        Called once per frame from :meth:`tick_subsystems` right after
        the drag-poll block. The overlay is wiped on every frame and
        re-populated only while a drag is in flight, so the moment the
        user releases the mouse all guides disappear without any
        explicit cleanup hook.

        Headless-safe: every Dear PyGui call sits inside its own
        ``try/except`` so a missing context never crashes the tick
        loop.
        """
        if not self._running:
            return
        try:
            import dearpygui.dearpygui as dpg
        except Exception:
            return
        dl = self._ensure_overlay_drawlist()
        try:
            dpg.delete_item(dl, children_only=True)
        except Exception:
            return

        # ── Snap guide lines ─────────────────────────────────────────
        if self._snap_manager is not None and bool(
            getattr(self._snap_manager, "is_dragging", False)
        ):
            guide_color: tuple[int, int, int, int] = (255, 111, 181, 220)
            try:
                t = self._get_active_theme()
                if t is not None and hasattr(t, "semantic") and t.semantic:
                    c = t.semantic.accent
                    guide_color = (int(c.r), int(c.g), int(c.b), 220)
            except Exception:
                pass

            ax_target = getattr(self._snap_manager, "active_snap_x", None)
            ay_target = getattr(self._snap_manager, "active_snap_y", None)
            ax = ax_target.position if ax_target is not None else None
            ay = ay_target.position if ay_target is not None else None
            if ax is not None:
                try:
                    dpg.draw_line(
                        parent=dl,
                        p1=(ax, 0),
                        p2=(ax, self._height),
                        color=guide_color,
                        thickness=1,
                    )
                except Exception:
                    pass
            if ay is not None:
                try:
                    dpg.draw_line(
                        parent=dl,
                        p1=(0, ay),
                        p2=(self._width, ay),
                        color=guide_color,
                        thickness=1,
                    )
                except Exception:
                    pass

        # ── Dock zone preview rectangles ─────────────────────────────
        if self._dock_zones is not None:
            try:
                is_active = self._dock_zones.is_active()
            except Exception:
                is_active = False
            if is_active:
                try:
                    active = self._dock_zones.current_zone()
                except Exception:
                    active = None
                if active is not None:
                    try:
                        zones = self._dock_zones.compute_zones()
                    except Exception:
                        zones = []
                    for zone in zones:
                        if zone.zone is not active:
                            continue
                        x, y, w, h = zone.bounds
                        try:
                            dpg.draw_rectangle(
                                parent=dl,
                                pmin=(x, y),
                                pmax=(x + w, y + h),
                                color=zone.color,
                                fill=zone.color,
                                thickness=2,
                            )
                        except Exception:
                            pass

    def _tick_panel_drag(self) -> None:
        """Poll each movable panel's DPG position; apply snap on drag."""
        if not self._panel_windows or not self._running:
            return
        try:
            import dearpygui.dearpygui as dpg
        except Exception:
            return
        any_dragging: str | None = None
        for short_name, window in self._panel_windows.items():
            tag = getattr(window, "_window_tag", None) or getattr(
                window, "window_tag", None
            )
            if tag is None:
                continue
            try:
                if not dpg.does_item_exist(tag):
                    continue
                cur_pos = tuple(dpg.get_item_pos(tag))
                cur_w = dpg.get_item_width(tag) or 0
                cur_h = dpg.get_item_height(tag) or 0
            except Exception:
                continue
            cur_pos_t = (int(cur_pos[0]), int(cur_pos[1]))
            cur_size_t = (int(cur_w), int(cur_h))
            last_pos = self._last_panel_pos.get(short_name)
            last_size = self._last_panel_size.get(short_name)
            self._last_panel_pos[short_name] = cur_pos_t
            self._last_panel_size[short_name] = cur_size_t
            if last_pos is None or last_size is None:
                continue
            # Position changed → drag in progress
            if cur_pos_t != last_pos:
                any_dragging = tag
                # Lazily inform SnapManager that a drag is underway. If we
                # haven't seen this tag dragging before, start the snap
                # session so target snapshots get built once.
                if self._snap_manager is not None:
                    try:
                        if self._actively_dragging != tag:
                            self._snap_manager.on_drag_start(tag)
                        snapped = self._snap_manager.on_drag_tick(
                            tag, cur_pos_t
                        )
                        if snapped != cur_pos_t:
                            dpg.configure_item(tag, pos=list(snapped))
                            self._last_panel_pos[short_name] = snapped
                    except Exception:
                        pass
                if self._dock_zones is not None:
                    try:
                        mx, my = dpg.get_mouse_pos(local=False)
                        self._dock_zones.on_drag_tick(tag, (int(mx), int(my)))
                    except Exception:
                        pass
        # End of drag: nothing is moving this frame but we had something
        # actively dragging the previous frame.
        if any_dragging is None and self._actively_dragging is not None:
            try:
                if self._snap_manager is not None:
                    self._snap_manager.on_drag_end(self._actively_dragging)
            except Exception:
                pass
            try:
                if self._dock_zones is not None:
                    self._dock_zones.on_drag_end(
                        self._actively_dragging,
                        self._find_window_by_tag(self._actively_dragging),
                    )
            except Exception:
                pass
        self._actively_dragging = any_dragging

    def _find_window_by_tag(self, tag: str) -> "MovablePanelWindow | None":
        """Return the :class:`MovablePanelWindow` whose DPG tag is *tag*.

        Linear scan over the small ``self._panel_windows`` map (a handful
        of panels — never enough to warrant a reverse index). Returns
        ``None`` when no panel matches, so callers can fall through to
        a safe no-op when the shell sees a stray tag (e.g. a panel that
        was destroyed mid-drag).
        """
        if not tag:
            return None
        for win in self._panel_windows.values():
            wt = getattr(win, "_window_tag", None) or getattr(
                win, "window_tag", None
            )
            if wt == tag:
                return win
        return None

    def on_viewport_resize(self, width: int, height: int) -> None:
        """React to an OS-level editor-window resize.

        Re-binds the snap + dock-zone managers to the new viewport
        dimensions and recomputes the bounds of every panel currently
        snapped to a dock zone so the docked layout follows the new
        viewport. Floating panels (``docked_to is None``) are left
        wherever the user dropped them.

        Safe to call without a live DPG context — the underlying
        ``MovablePanelWindow.set_bounds`` already guards on the build
        flag.
        """
        try:
            self._width = int(width)
            self._height = int(height)
        except Exception:
            return
        if self._snap_manager is not None:
            try:
                self._snap_manager.set_viewport_size(
                    self._width, self._height
                )
            except Exception:
                pass
        if self._dock_zones is not None:
            try:
                self._dock_zones.update_viewport_size(
                    (self._width, self._height)
                )
            except Exception:
                pass
            for win in self._panel_windows.values():
                try:
                    self._dock_zones.redock_panel(win)
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
        # Reset the bridge so any post-loop theme work routes to the
        # headless stub instead of crashing on the destroyed context.
        try:
            from slappyengine.ui.theme.dpg_bridge import mark_dpg_context_ready

            mark_dpg_context_ready(False)
        except Exception:
            pass
        self._running = False

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def _set_status(self, message: str) -> None:
        """Update the status bar text to *message*.

        Gated on ``self._running`` because Dear PyGui's ``does_item_exist``
        segfaults hard on Windows when no context has been created yet —
        the lifecycle tests drive this method headlessly.
        """
        if self._running:
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
        """Flag the current scene as freshly saved + repaint title.

        Also persists the current panel layout so a save-driven clean
        state (Ctrl+S, autosave, etc.) always lands the user's chrome on
        disk — independent of whether ``save_scene`` actually wrote
        anything (e.g. for engines without a ``save_scene`` hook).
        """
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
        try:
            self._persist_layout()
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

        # Status bar — project segment + dirty marker.
        if self._notebook_status_bar is not None:
            try:
                self._notebook_status_bar.set_project_name(
                    project.metadata.name,
                )
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

        # ── Layout persistence — re-root, then restore ─────────────────────
        # Re-construct the persistence handle against the project root so
        # subsequent save()/load() target ``<project>/.slappy/layout.yaml``.
        # When a layout exists on disk, replay it through ``apply_to_shell``.
        try:
            from slappyengine.ui.editor.layout_persistence import (
                LayoutPersistence,
            )
            self._layout_persistence = LayoutPersistence(project.path)
            saved_layout = self._layout_persistence.load()
            if saved_layout is not None:
                self._layout_persistence.apply_to_shell(self, saved_layout)
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
        # Persist the current panel layout alongside the scene so a crash
        # right after a save still preserves the user's chrome.
        try:
            self._persist_layout()
        except Exception:
            pass
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

    def get_diary_page(self) -> "NotebookDiaryPage":
        """Return the lazily-constructed :class:`NotebookDiaryPage`.

        The diary panel hosts a script editor with a live viewport on the
        left (running a small :class:`slappyengine.studio.Stage`) and the
        script source on the right. Constructed on first use so the
        startup path stays cheap when no diaries are open.
        """
        panel = getattr(self, "_diary_page", None)
        if panel is None:
            from slappyengine.ui.editor.notebook_diary_page import (
                NotebookDiaryPage,
            )
            panel = NotebookDiaryPage(engine=self._engine)
            self._diary_page = panel
        return panel

    def new_diary_page(self) -> "NotebookDiaryPage":
        """File menu hook — open a blank diary with the default scaffold."""
        panel = self.get_diary_page()
        from pathlib import Path as _Path
        panel.open_diary(_Path("untitled.diary.py"))
        return panel

    def open_diary_page(self, path: Any | None = None) -> "NotebookDiaryPage":
        """File menu hook — file picker filtered to ``*.diary.py``.

        When *path* is given (test path), it's loaded directly. Otherwise
        the call defers to ``engine.open_diary_picker`` when present, or
        records the intent for a follow-up sprint to wire a real picker.
        """
        panel = self.get_diary_page()
        if path is not None:
            from pathlib import Path as _Path
            panel.open_diary(_Path(path))
            return panel
        picker = getattr(self._engine, "open_diary_picker", None)
        if callable(picker):
            try:
                picker(panel)
            except Exception:
                pass
        return panel

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

    def list_recent_project_labels(self, limit: int = 5) -> list[str]:
        """Return the labels rendered under ``File → Recent Projects``.

        Each label is the project's display ``name`` (preferred) or its
        on-disk ``path`` when the registry entry has no cached name. The
        list is truncated to *limit* entries (default 5 — matches the
        notebook-picker brief).
        """
        try:
            from slappyengine.projects import get_default_registry

            registry = get_default_registry()
            recents = registry.list_recent(limit=limit)
        except Exception:
            return []
        labels: list[str] = []
        for entry in recents:
            labels.append(entry.name or entry.path)
        return labels

    def _populate_recent_projects_menu(self) -> None:
        """Fill ``File → Recent Projects`` with up to 5 recents.

        Headless-safe — silently no-ops when ``dearpygui`` is missing
        or the parent menu tag does not exist.
        """
        try:
            import dearpygui.dearpygui as dpg
        except Exception:
            return
        labels = self.list_recent_project_labels(limit=5)
        if not labels:
            try:
                dpg.add_menu_item(
                    label="(no recent projects)",
                    enabled=False,
                )
            except Exception:
                pass
            return
        for index, label in enumerate(labels):
            try:
                dpg.add_menu_item(
                    label=f"{index + 1}. {label}",
                    callback=lambda s, d, idx=index: self.load_recent_project(idx),
                )
            except Exception:
                pass

    def _populate_layout_presets_menu(self) -> None:
        """Fill ``View → Layout Presets`` with one entry per preset.

        Headless-safe — silently no-ops when ``dearpygui`` is missing.
        """
        try:
            import dearpygui.dearpygui as dpg
        except Exception:
            return
        from slappyengine.ui.editor.layout_presets import PRESETS

        for preset_id, preset in PRESETS.items():
            try:
                shortcut = preset.shortcut.replace("ctrl+", "Ctrl+").upper().replace(
                    "CTRL+", "Ctrl+",
                ) if preset.shortcut else ""
                dpg.add_menu_item(
                    label=preset.name,
                    shortcut=shortcut,
                    callback=lambda s, d, pid=preset_id: self.apply_layout_preset(pid),
                )
            except Exception:
                pass

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

        Persists the current panel layout one last time so the next launch
        starts in the same configuration the user just left.
        """
        try:
            self._persist_layout()
        except Exception:
            pass
        self._running = False

    # ------------------------------------------------------------------
    # Layout persistence
    # ------------------------------------------------------------------

    def _persist_layout(self) -> None:
        """Snapshot the current panel state and write it to disk.

        Best-effort: silently no-ops if persistence isn't wired up yet
        (e.g. tests that construct an ``EditorShell`` then never call
        :meth:`setup`). Subclasses that override panel construction can
        rely on this being called from :meth:`save_scene`, :meth:`stop`,
        and the autosave timer.

        See :meth:`reset_layout` for the inverse operation.
        """
        persistence = getattr(self, "_layout_persistence", None)
        if persistence is None:
            return
        try:
            layout = persistence.snapshot_from_shell(self)
            persistence.save(layout)
        except Exception:
            pass
