"""``slappyengine.tool_router`` — formal editor tool-routing contract.

Every user-invocable editor action (button click, hotkey press, menu
item, spawn-card summon, content-browser context command) flows through
a single :class:`ToolRouter` instance whose registry maps ``action_id``
strings to a :class:`ToolAction` descriptor. The descriptor names an
optional Rust backing (``_core.<module>.<function>`` dotted path) and an
optional Python fallback callable. :meth:`ToolRouter.dispatch` resolves
the Rust symbol at call time (best-effort, cached) and falls back to
Python when the symbol is missing.

Design provenance
-----------------

* ``docs/rust_port_audit_2026_06_02.md`` — the source-of-truth for the
  53-symbol Rust surface. This module encodes the audit's routing intent
  as an executable table.
* ``docs/rust_migration_plan.md`` — steps 1-7 name every Rust kernel by
  their eventual ``_core`` path; this module points editor actions at
  those paths whether or not the kernel has landed yet.
* User directive ``project_architecture_pattern.md`` — *Python = wrapper,
  Rust = engine*. The router encodes that pattern for user-invoked
  actions: perf-sensitive actions get a ``rust_backing`` slot; UI
  chrome / authoring flow gets a Python fallback only.
* ``docs/tool_routing_2026_06_07.md`` — hand-authored table walking every
  action_id, its backing, and its effect.

Public surface
--------------

* :class:`ToolAction` — one row of the registry.
* :class:`ToolRouter` — the registry + dispatch entry point.
* :data:`REGISTRY` — module-level singleton pre-populated at import time
  with every action ``EditorShell._dispatch_editor_command`` knows how to
  route.
* :func:`register_default_actions` — idempotent seed function invoked on
  import; tests may call it a second time and get an empty diff.

Headless safety
---------------

Importing this module never imports ``dearpygui`` or the Rust ``_core``
extension eagerly. ``_core`` is probed lazily on the first
:meth:`ToolRouter.has_rust_backing` / :meth:`ToolRouter.dispatch` call
and cached. When ``_core`` is unavailable the router silently degrades
to the Python fallback, matching the ``HAS_NATIVE`` gate used elsewhere
in the engine.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Callable

from slappyengine._validation import (
    validate_callable,
    validate_non_empty_str,
)


# ---------------------------------------------------------------------------
# ToolAction descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolAction:
    """One row of the editor tool-routing registry.

    Attributes
    ----------
    action_id:
        Stable identifier ``"category.verb"`` — matches the hotkey
        dispatcher's namespaced command ids (``"editor.save"``,
        ``"spawn.rope"``, etc.). Must be non-empty and unique.
    label:
        Human-readable label shown in menus / tooltips.
    rust_backing:
        Dotted path relative to ``slappyengine._core`` (e.g.
        ``"softbody_solver.slappyengine_step"``, ``"hull.convex_hull"``).
        ``None`` when the action has no Rust kernel (pure-UI actions,
        layout toggles, scene-graph mutations without a Rust surface).
        A backing of ``"_core.<module>.<fn>"`` is also accepted as-is —
        the router strips the leading ``_core.`` when resolving.
    python_fallback:
        Callable invoked when the Rust backing is missing or ``None``.
        Signature: ``(ctx: dict[str, Any]) -> Any``. When both are
        ``None`` the action is a "declared but not yet implemented"
        placeholder — :meth:`ToolRouter.dispatch` returns ``None``.
    required_args:
        Names of ``ctx`` keys the Rust backing / fallback expects. The
        router does *not* enforce these — they're documentation for the
        tests and future ``ToolRouter.validate()`` pass. Empty list is
        allowed (no arguments needed).
    category:
        Coarse bucket for menu grouping — ``"file"`` / ``"edit"`` /
        ``"tool"`` / ``"layout"`` / ``"theme"`` / ``"view"`` /
        ``"panel"`` / ``"spawn"`` / ``"content"`` / ``"easter"``. Free-
        form; the router doesn't gate on it.
    """

    action_id: str
    label: str
    rust_backing: str | None = None
    python_fallback: Callable[[dict[str, Any]], Any] | None = None
    required_args: list[str] = field(default_factory=list)
    category: str = "misc"


# ---------------------------------------------------------------------------
# ToolRouter
# ---------------------------------------------------------------------------


class ToolRouter:
    """Central dispatch table for editor tool actions.

    The router owns a ``dict[str, ToolAction]`` keyed by
    :attr:`ToolAction.action_id`. Registration is idempotent per
    ``action_id`` — re-registering the same id with the same
    ``rust_backing`` / ``python_fallback`` is a no-op; re-registering
    with different values raises ``ValueError`` so a typo can't silently
    shadow an existing entry.

    Rust lookups are cached in ``self._rust_cache``. The first call to
    :meth:`has_rust_backing` / :meth:`dispatch` for a given ``action_id``
    imports ``slappyengine._core`` (soft-imported — falls back to
    Python when the extension is missing) and walks the dotted path.
    Missing sub-modules / attributes are stored as ``None`` in the
    cache so subsequent lookups are O(1).
    """

    def __init__(self) -> None:
        self._actions: dict[str, ToolAction] = {}
        # Cached (callable | None) per action_id — populated lazily on
        # first has_rust_backing / dispatch call.
        self._rust_cache: dict[str, Callable[..., Any] | None] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, action: ToolAction) -> None:
        """Add *action* to the registry.

        Idempotent when re-registering the same (action_id,
        rust_backing, python_fallback) triple. Raises ``ValueError``
        when re-registering with different fields to catch copy-paste
        typos.
        """
        if not isinstance(action, ToolAction):
            raise TypeError(
                "ToolRouter.register: action must be a ToolAction; got "
                f"{type(action).__name__}"
            )
        validate_non_empty_str(
            "action_id", "ToolRouter.register", action.action_id,
        )
        validate_non_empty_str(
            "label", "ToolRouter.register", action.label,
        )
        existing = self._actions.get(action.action_id)
        if existing is not None:
            # Idempotency check compares label + rust_backing +
            # required_args + category. We deliberately don't compare
            # python_fallback by identity — lambdas built by
            # :func:`_default_actions` are fresh on every call so an
            # identity check would spuriously fail idempotent seeds.
            if (
                existing.rust_backing == action.rust_backing
                and existing.label == action.label
                and existing.required_args == action.required_args
                and existing.category == action.category
            ):
                # Same registration — quietly no-op.
                return
            raise ValueError(
                f"ToolRouter.register: action_id {action.action_id!r} "
                "already registered with a different backing / fallback"
            )
        self._actions[action.action_id] = action
        # Invalidate any stale cache entry (defensive — a re-register
        # can only reach here when the triple matches, but keep the
        # cache honest anyway).
        self._rust_cache.pop(action.action_id, None)

    def unregister(self, action_id: str) -> bool:
        """Remove *action_id*. Returns ``True`` iff it was present."""
        validate_non_empty_str(
            "action_id", "ToolRouter.unregister", action_id,
        )
        self._rust_cache.pop(action_id, None)
        return self._actions.pop(action_id, None) is not None

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get(self, action_id: str) -> ToolAction | None:
        """Return the :class:`ToolAction` for *action_id* (or ``None``)."""
        validate_non_empty_str(
            "action_id", "ToolRouter.get", action_id,
        )
        return self._actions.get(action_id)

    def list_actions(self) -> list[ToolAction]:
        """Return every registered action, sorted by ``action_id``."""
        return sorted(self._actions.values(), key=lambda a: a.action_id)

    def list_by_category(self, category: str) -> list[ToolAction]:
        """Return every action in *category*, sorted by ``action_id``."""
        validate_non_empty_str(
            "category", "ToolRouter.list_by_category", category,
        )
        return sorted(
            (a for a in self._actions.values() if a.category == category),
            key=lambda a: a.action_id,
        )

    def has_action(self, action_id: str) -> bool:
        """``True`` iff *action_id* is registered."""
        validate_non_empty_str(
            "action_id", "ToolRouter.has_action", action_id,
        )
        return action_id in self._actions

    def has_rust_backing(self, action_id: str) -> bool:
        """``True`` iff *action_id* has a live Rust symbol.

        Resolves the ``rust_backing`` dotted path against the imported
        ``slappyengine._core`` module and caches the result. Returns
        ``False`` when:

        * *action_id* is not registered,
        * the action has ``rust_backing=None``,
        * ``_core`` failed to import (no Rust wheel),
        * the dotted path does not resolve to a callable.
        """
        validate_non_empty_str(
            "action_id", "ToolRouter.has_rust_backing", action_id,
        )
        action = self._actions.get(action_id)
        if action is None or action.rust_backing is None:
            return False
        return self._resolve_rust(action) is not None

    def rust_backing_symbol(self, action_id: str) -> Callable[..., Any] | None:
        """Return the resolved Rust callable for *action_id* (or ``None``)."""
        validate_non_empty_str(
            "action_id", "ToolRouter.rust_backing_symbol", action_id,
        )
        action = self._actions.get(action_id)
        if action is None or action.rust_backing is None:
            return None
        return self._resolve_rust(action)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def dispatch(
        self,
        action_id: str,
        ctx: dict[str, Any] | None = None,
    ) -> Any:
        """Execute the action bound to *action_id*.

        Resolution order:

        1. If the action has a live Rust backing, invoke it as
           ``backing(**ctx)`` — the ``ctx`` dict is unpacked so Rust
           kernels can declare their own keyword parameters. Falls
           through to (2) if the Rust call raises ``TypeError`` (arg
           mismatch — treated as "wrong signature, try Python").
        2. If the action has a Python fallback, invoke it as
           ``fallback(ctx)`` — the whole dict is passed as a single
           argument so shell handlers can pull whichever keys they need.
        3. Otherwise return ``None`` (declared-but-unimplemented action).

        Raises
        ------
        KeyError
            When *action_id* is not registered. Callers that want a
            silent no-op should guard with :meth:`has_action` first.
        """
        validate_non_empty_str(
            "action_id", "ToolRouter.dispatch", action_id,
        )
        if ctx is None:
            ctx = {}
        elif not isinstance(ctx, dict):
            raise TypeError(
                "ToolRouter.dispatch: ctx must be a dict or None; got "
                f"{type(ctx).__name__}"
            )
        action = self._actions.get(action_id)
        if action is None:
            raise KeyError(
                f"ToolRouter.dispatch: unknown action_id {action_id!r} "
                "(not registered)"
            )
        # (1) Prefer Rust.
        rust = self._resolve_rust(action) if action.rust_backing else None
        if rust is not None:
            try:
                return rust(**ctx)
            except TypeError:
                # Signature mismatch — fall through to Python.
                pass
        # (2) Python fallback.
        if action.python_fallback is not None:
            return action.python_fallback(ctx)
        # (3) No-op.
        return None

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def clear_rust_cache(self) -> None:
        """Drop every cached Rust-symbol lookup.

        Used by tests that want to re-probe ``_core`` after monkey-
        patching it, and by hot-reload flows that re-import the Rust
        extension.
        """
        self._rust_cache.clear()

    def _resolve_rust(
        self, action: ToolAction,
    ) -> Callable[..., Any] | None:
        """Look up *action*'s Rust backing (cached).

        Accepts ``"_core.module.fn"`` / ``"module.fn"`` / ``"fn"`` — the
        leading ``_core.`` prefix is stripped, and the router walks the
        remaining dotted path against the imported ``_core`` module.

        Because the shipping ``_core`` extension has a **flat** symbol
        layout (every ``#[pyfunction]`` is registered directly on the
        top-level module — see ``docs/rust_port_audit_2026_06_02.md``
        §1.2), the router also probes the *last* dotted segment against
        the flat namespace when the full path misses. That lets the
        registry name the Rust source file for documentation
        (``softbody_solver.slappyengine_step``) without a routing
        breakage when the wheel exposes the leaf symbol directly
        (``slappyengine_step``).
        """
        aid = action.action_id
        if aid in self._rust_cache:
            return self._rust_cache[aid]
        path = action.rust_backing
        if path is None:
            self._rust_cache[aid] = None
            return None
        # Normalise: strip any leading "_core." so the caller can
        # write either form.
        norm = path[len("_core."):] if path.startswith("_core.") else path
        try:
            core = importlib.import_module("slappyengine._core")
        except Exception:
            self._rust_cache[aid] = None
            return None
        # (a) Try the full dotted path against the imported module.
        parts = norm.split(".")
        symbol: Any = core
        for part in parts:
            symbol = getattr(symbol, part, None)
            if symbol is None:
                break
        # (b) Fall back to probing the last segment against the flat
        # namespace — matches how the shipping wheel is structured.
        if symbol is None or not callable(symbol):
            leaf = parts[-1]
            symbol = getattr(core, leaf, None)
        if not callable(symbol):
            self._rust_cache[aid] = None
            return None
        self._rust_cache[aid] = symbol
        return symbol


# ---------------------------------------------------------------------------
# Default Python fallbacks (side-effect free — return ctx-derived values)
# ---------------------------------------------------------------------------
#
# Each fallback is a *shell delegator*: it looks for ``ctx["shell"]`` (the
# EditorShell instance) and calls the matching public method. When the
# shell key is absent it returns ``None`` so headless tests can still
# drive :meth:`ToolRouter.dispatch` without instantiating the editor.


def _shell_call(ctx: dict[str, Any], method: str, *args: Any) -> Any:
    shell = ctx.get("shell")
    if shell is None:
        return None
    fn = getattr(shell, method, None)
    if not callable(fn):
        return None
    return fn(*args)


def _fb_save(ctx: dict[str, Any]) -> Any:
    return _shell_call(ctx, "_save_project")


def _fb_undo(ctx: dict[str, Any]) -> Any:
    return _shell_call(ctx, "_undo")


def _fb_redo(ctx: dict[str, Any]) -> Any:
    # No _redo method today; route through the engine undo manager the
    # same way _undo does.
    shell = ctx.get("shell")
    if shell is None:
        return None
    manager = getattr(getattr(shell, "_engine", None), "_undo_manager", None)
    if manager is None:
        return None
    redo = getattr(manager, "redo", None)
    if callable(redo):
        try:
            return redo()
        except Exception:
            return None
    return None


def _fb_new(ctx: dict[str, Any]) -> Any:
    return _shell_call(ctx, "menu_new_scene")


def _fb_open(ctx: dict[str, Any]) -> Any:
    path = ctx.get("path")
    return _shell_call(ctx, "menu_open_scene", path)


def _fb_delete(ctx: dict[str, Any]) -> Any:
    return _shell_call(ctx, "_delete_selected")


def _fb_toggle_play(ctx: dict[str, Any]) -> Any:
    return _shell_call(ctx, "_toggle_play")


def _fb_reset_layout(ctx: dict[str, Any]) -> Any:
    return _shell_call(ctx, "reset_layout")


def _fb_toggle_theme_switcher(ctx: dict[str, Any]) -> Any:
    return _shell_call(ctx, "toggle_theme_switcher")


def _fb_cycle_theme(ctx: dict[str, Any]) -> Any:
    return _shell_call(ctx, "cycle_theme")


def _fb_toggle_fullscreen(ctx: dict[str, Any]) -> Any:
    return _shell_call(ctx, "toggle_fullscreen")


def _fb_layout_preset(ctx: dict[str, Any], name: str) -> Any:
    return _shell_call(ctx, "apply_layout_preset", name)


def _fb_toggle_panel(ctx: dict[str, Any], panel_id: str) -> Any:
    return _shell_call(ctx, "toggle_panel", panel_id)


def _fb_set_tool(ctx: dict[str, Any], tool_id: str) -> Any:
    shell = ctx.get("shell")
    if shell is None:
        return None
    # EditorShell tracks the active tool on `_active_tool`. The
    # NotebookToolbar owns the UI-side switch; route through both.
    setattr(shell, "_active_tool", tool_id)
    toolbar = getattr(shell, "_toolbar", None)
    if toolbar is not None:
        set_active = getattr(toolbar, "set_active", None)
        if callable(set_active):
            try:
                set_active(tool_id)
            except Exception:
                pass
    return tool_id


def _fb_toggle_hud(ctx: dict[str, Any]) -> Any:
    shell = ctx.get("shell")
    if shell is None:
        return None
    # Best-effort — most shells store HUD state on their viewport panel.
    hud = getattr(shell, "_hud_visible", True)
    try:
        setattr(shell, "_hud_visible", not hud)
    except Exception:
        return None
    return not hud


def _fb_profiler_toggle(ctx: dict[str, Any]) -> Any:
    return _shell_call(ctx, "toggle_profiler")


def _fb_help(ctx: dict[str, Any]) -> Any:
    return _shell_call(ctx, "show_welcome")


def _fb_spawn(ctx: dict[str, Any], card_id: str) -> Any:
    shell = ctx.get("shell")
    if shell is None:
        return None
    handler = getattr(shell, "_on_spawn", None)
    if not callable(handler):
        return None
    spec = ctx.get("spec", {})
    try:
        return handler(card_id, spec)
    except Exception:
        return None


def _fb_reveal_in_folder(ctx: dict[str, Any]) -> Any:
    # Content-browser action — opens the OS file explorer at ctx["path"].
    path = ctx.get("path")
    if not path:
        return None
    import subprocess
    import sys
    import os as _os
    try:
        if sys.platform.startswith("win"):
            _os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        return None
    return path


def _fb_content_open(ctx: dict[str, Any]) -> Any:
    return _shell_call(ctx, "menu_open_scene", ctx.get("path"))


def _fb_content_import(ctx: dict[str, Any]) -> Any:
    shell = ctx.get("shell")
    if shell is None:
        return None
    browser = getattr(shell, "_content_browser", None)
    if browser is None:
        return None
    handler = getattr(browser, "_on_import_click", None)
    if callable(handler):
        try:
            return handler()
        except Exception:
            return None
    return None


def _fb_content_new_script(ctx: dict[str, Any]) -> Any:
    shell = ctx.get("shell")
    if shell is None:
        return None
    browser = getattr(shell, "_content_browser", None)
    if browser is None:
        return None
    handler = getattr(browser, "_on_new_script", None)
    if callable(handler):
        try:
            return handler()
        except Exception:
            return None
    return None


def _fb_switch_project(ctx: dict[str, Any]) -> Any:
    return _shell_call(ctx, "menu_switch_project")


# ---------------------------------------------------------------------------
# X3 STUB-triage fallbacks (2026-07-04)
#
# The following five wrappers back the ``editor.save_project`` /
# ``editor.new_project`` / ``editor.open_recent`` / ``view.reset_layout`` /
# ``edit.duplicate_selection`` action ids added by
# ``docs/engine_feature_map_2026_07_04.md`` §"Top 5 STUB Fixes". They live
# in :mod:`slappyengine.actions` so headless tests can import them
# directly without spinning up the DPG editor.
# ---------------------------------------------------------------------------


def _fb_save_project(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.project_actions import save_project
    return save_project(ctx)


def _fb_new_project(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.project_actions import new_project
    return new_project(ctx)


def _fb_open_recent(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.project_actions import open_recent
    return open_recent(ctx)


def _fb_view_reset_layout(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.view_actions import reset_layout
    return reset_layout(ctx)


def _fb_duplicate_selection(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_actions import duplicate_selection
    return duplicate_selection(ctx)


# ---------------------------------------------------------------------------
# Y1 STUB-triage fallbacks (2026-07-04, round 2)
#
# Wire the next five STUB rows: selection / clipboard / theme cycling.
# See :mod:`slappyengine.actions.selection_actions` and
# :mod:`slappyengine.actions.theme_actions` for the implementations.
# ---------------------------------------------------------------------------


def _fb_select_all(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.selection_actions import select_all
    return select_all(ctx)


def _fb_deselect_all(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.selection_actions import deselect_all
    return deselect_all(ctx)


def _fb_copy_selection(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.selection_actions import copy_selection
    return copy_selection(ctx)


def _fb_paste_selection(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.selection_actions import paste_selection
    return paste_selection(ctx)


def _fb_theme_cycle(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.theme_actions import cycle_theme
    return cycle_theme(ctx)


# ---------------------------------------------------------------------------
# Z7 STUB-triage fallbacks (2026-07-04, round 3)
#
# Wire five more STUB rows: snap-to-grid toggle, viewport zoom in/out/reset,
# and active-theme export. See :mod:`slappyengine.actions.tool_settings_actions`,
# :mod:`slappyengine.actions.camera_actions`, and
# :mod:`slappyengine.actions.theme_io_actions` for the implementations.
# ---------------------------------------------------------------------------


def _fb_snap_to_grid(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.tool_settings_actions import (
        toggle_snap_to_grid,
    )
    return toggle_snap_to_grid(ctx)


def _fb_zoom_in(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.camera_actions import zoom_in
    return zoom_in(ctx)


def _fb_zoom_out(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.camera_actions import zoom_out
    return zoom_out(ctx)


def _fb_zoom_reset(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.camera_actions import zoom_reset
    return zoom_reset(ctx)


def _fb_export_current_theme(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.theme_io_actions import export_current_theme
    return export_current_theme(ctx)


# ---------------------------------------------------------------------------
# AA1 STUB-triage fallbacks (2026-07-05, round 4)
#
# Wire the next five STUB rows: cut / delete selection, center-on-selection,
# frame-all, and pan-tool activation. See
# :mod:`slappyengine.actions.destructive_edit_actions`,
# :mod:`slappyengine.actions.viewport_framing_actions`, and
# :mod:`slappyengine.actions.tool_mode_actions` for the implementations.
# ---------------------------------------------------------------------------


def _fb_cut_selection(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.destructive_edit_actions import cut_selection
    return cut_selection(ctx)


def _fb_delete_selection(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.destructive_edit_actions import delete_selection
    return delete_selection(ctx)


def _fb_center_on_selection(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.viewport_framing_actions import (
        center_on_selection,
    )
    return center_on_selection(ctx)


def _fb_frame_all(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.viewport_framing_actions import frame_all
    return frame_all(ctx)


def _fb_activate_pan_tool(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.tool_mode_actions import activate_pan_tool
    return activate_pan_tool(ctx)


# ---------------------------------------------------------------------------
# CC6 sprint tick — animated camera moves (7-sprint push).
#
# view.focus_on_selection_animated  — pans + zooms to selection over 800 ms.
# view.frame_all_animated           — animated version of view.frame_all.
#
# Implementation: :mod:`slappyengine.actions.camera_animation_actions`.
# ---------------------------------------------------------------------------


def _fb_focus_on_selection_animated(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.camera_animation_actions import (
        focus_on_selection_animated,
    )
    return focus_on_selection_animated(ctx)


def _fb_frame_all_animated(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.camera_animation_actions import (
        frame_all_animated,
    )
    return frame_all_animated(ctx)


# ---------------------------------------------------------------------------
# BB1 STUB-triage fallbacks (2026-07-05, round 5)
#
# Wire the next five STUB rows: theme import from file, layout save-as /
# load-from-file, and history undo / redo via the process-wide UndoStack.
# See :mod:`slappyengine.actions.theme_import_actions`,
# :mod:`slappyengine.actions.layout_io_actions`, and
# :mod:`slappyengine.actions.history_actions` for the implementations.
# ---------------------------------------------------------------------------


def _fb_theme_import_from_file(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.theme_import_actions import import_from_file
    return import_from_file(ctx)


def _fb_save_layout_as(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.layout_io_actions import save_layout_as
    return save_layout_as(ctx)


def _fb_load_layout_from_file(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.layout_io_actions import load_layout_from_file
    return load_layout_from_file(ctx)


def _fb_edit_undo(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.history_actions import undo
    return undo(ctx)


def _fb_edit_redo(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.history_actions import redo
    return redo(ctx)


# ---------------------------------------------------------------------------
# CC1 STUB-triage fallbacks (2026-07-05, round 6)
#
# Wire five more STUB rows: select-by-name, repeat-last-spawn, grid /
# gizmo overlay toggles, and copy-asset-path clipboard write. See
# :mod:`slappyengine.actions.edit_by_name_actions`,
# :mod:`slappyengine.actions.spawn_history_actions`,
# :mod:`slappyengine.actions.view_toggle_actions`, and
# :mod:`slappyengine.actions.content_shell_actions` for the implementations.
# ---------------------------------------------------------------------------


def _fb_select_by_name(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_by_name_actions import select_by_name
    return select_by_name(ctx)


def _fb_repeat_last_spawn(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.spawn_history_actions import repeat_last
    return repeat_last(ctx)


def _fb_toggle_grid(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.view_toggle_actions import toggle_grid
    return toggle_grid(ctx)


def _fb_toggle_gizmos(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.view_toggle_actions import toggle_gizmos
    return toggle_gizmos(ctx)


def _fb_copy_asset_path(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.content_shell_actions import copy_asset_path
    return copy_asset_path(ctx)


# ---------------------------------------------------------------------------
# DD1 STUB-triage fallbacks (2026-07-05, round 7)
#
# Wire five more STUB rows: layer duplication, reverse theme cycle,
# batch panel close + last-hidden restore, and grid-batch spawn repeat.
# See :mod:`slappyengine.actions.layer_duplicate_actions`,
# :mod:`slappyengine.actions.theme_cycle_reverse_actions`,
# :mod:`slappyengine.actions.panel_visibility_actions`, and
# :mod:`slappyengine.actions.spawn_batch_actions` for the implementations.
# ---------------------------------------------------------------------------


def _fb_duplicate_layer(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.layer_duplicate_actions import duplicate_layer
    return duplicate_layer(ctx)


def _fb_cycle_theme_reverse(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.theme_cycle_reverse_actions import (
        cycle_theme_reverse,
    )
    return cycle_theme_reverse(ctx)


def _fb_close_all_panels(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.panel_visibility_actions import close_all_panels
    return close_all_panels(ctx)


def _fb_restore_last_hidden_panel(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.panel_visibility_actions import (
        restore_last_hidden_panel,
    )
    return restore_last_hidden_panel(ctx)


def _fb_repeat_last_batch(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.spawn_batch_actions import repeat_last_batch
    return repeat_last_batch(ctx)


# ---------------------------------------------------------------------------
# EE1 STUB-triage fallbacks (2026-07-05, round 8)
#
# Wire five more STUB rows: selection group / ungroup, random theme,
# spawn-at-cursor arming, and snap-to-pixel-grid.
# See :mod:`slappyengine.actions.edit_group_actions`,
# :mod:`slappyengine.actions.theme_random_actions`,
# :mod:`slappyengine.actions.spawn_cursor_actions`, and
# :mod:`slappyengine.actions.edit_snap_pixel_actions`.
# ---------------------------------------------------------------------------


def _fb_group_selection(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_group_actions import group_selection
    return group_selection(ctx)


def _fb_ungroup_selection(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_group_actions import ungroup_selection
    return ungroup_selection(ctx)


def _fb_random_theme(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.theme_random_actions import random_theme
    return random_theme(ctx)


def _fb_spawn_at_cursor(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.spawn_cursor_actions import spawn_at_cursor
    return spawn_at_cursor(ctx)


def _fb_snap_to_pixel_grid(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_snap_pixel_actions import snap_to_pixel_grid
    return snap_to_pixel_grid(ctx)


# ---------------------------------------------------------------------------
# FF1 STUB-triage fallbacks (2026-07-05, round 9)
#
# Wire five more STUB rows: content-browser new-folder / rename-asset,
# panel "close others" (companion to DD1 close-all), recursive
# select-children, and theme registry reload. See
# :mod:`slappyengine.actions.content_folder_actions`,
# :mod:`slappyengine.actions.content_rename_actions`,
# :mod:`slappyengine.actions.panel_close_others_actions`,
# :mod:`slappyengine.actions.edit_select_children_actions`, and
# :mod:`slappyengine.actions.theme_reload_actions` for the implementations.
# ---------------------------------------------------------------------------


def _fb_new_folder(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.content_folder_actions import new_folder
    return new_folder(ctx)


def _fb_rename_asset(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.content_rename_actions import rename_asset
    return rename_asset(ctx)


def _fb_close_other_panels(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.panel_close_others_actions import (
        close_other_panels,
    )
    return close_other_panels(ctx)


def _fb_select_children(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_select_children_actions import (
        select_children,
    )
    return select_children(ctx)


def _fb_reload_all_themes(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.theme_reload_actions import reload_all_themes
    return reload_all_themes(ctx)


# ---------------------------------------------------------------------------
# GG1 STUB-triage fallbacks (2026-07-05, round 10)
#
# Wire five more STUB rows: content-browser delete-asset (row 243 flip),
# panel tile-grid + cascade (auto-layout companions to DD1 close-all),
# edit invert-selection (photoshop-style Shift+Ctrl+I), and view
# fullscreen (chrome + panel hide with snapshot/restore). See
# :mod:`slappyengine.actions.content_delete_actions`,
# :mod:`slappyengine.actions.panel_layout_actions`,
# :mod:`slappyengine.actions.edit_invert_selection_actions`, and
# :mod:`slappyengine.actions.view_fullscreen_actions` for the
# implementations.
# ---------------------------------------------------------------------------


def _fb_delete_asset(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.content_delete_actions import delete_asset
    return delete_asset(ctx)


def _fb_tile_grid(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.panel_layout_actions import tile_grid
    return tile_grid(ctx)


def _fb_cascade_panels(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.panel_layout_actions import cascade
    return cascade(ctx)


def _fb_invert_selection(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_invert_selection_actions import (
        invert_selection,
    )
    return invert_selection(ctx)


def _fb_view_fullscreen(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.view_fullscreen_actions import fullscreen
    return fullscreen(ctx)


# ---------------------------------------------------------------------------
# II5 STUB-triage fallbacks (2026-07-05 — round 11 after X3 / Y1 / Z7 /
# AA1 / BB1 / CC1 / DD1 / EE1 / FF1 / GG1)
#
# Five more action ids: tab-through selection (next / previous), paste-
# at-original-position (Illustrator Cmd+Shift+V), row-batch spawn
# (single-line variant of GG1's grid spawn), and content-browser
# duplicate-asset (Explorer-style ``_copy`` suffix). See
# :mod:`slappyengine.actions.edit_select_next_actions`,
# :mod:`slappyengine.actions.edit_paste_original_actions`,
# :mod:`slappyengine.actions.spawn_batch_row_actions`, and
# :mod:`slappyengine.actions.content_duplicate_asset_actions`.
# ---------------------------------------------------------------------------


def _fb_select_next(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_select_next_actions import select_next
    return select_next(ctx)


def _fb_select_previous(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_select_next_actions import (
        select_previous,
    )
    return select_previous(ctx)


def _fb_paste_at_original_position(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_paste_original_actions import (
        paste_at_original_position,
    )
    return paste_at_original_position(ctx)


def _fb_spawn_batch_row(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.spawn_batch_row_actions import spawn_batch_row
    return spawn_batch_row(ctx)


def _fb_duplicate_asset(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.content_duplicate_asset_actions import (
        duplicate_asset,
    )
    return duplicate_asset(ctx)


# ---------------------------------------------------------------------------
# JJ6 STUB-triage fallbacks (2026-07-05 — round 12 after X3 / Y1 / Z7 /
# AA1 / BB1 / CC1 / DD1 / EE1 / FF1 / GG1 / II5)
#
# Five more action ids: hide/show pair, lock/unlock pair, and
# select-by-prefab-kind. See
# :mod:`slappyengine.actions.edit_hide_show_actions`,
# :mod:`slappyengine.actions.edit_lock_unlock_actions`, and
# :mod:`slappyengine.actions.edit_select_by_kind_actions`.
# ---------------------------------------------------------------------------


def _fb_hide_selection(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_hide_show_actions import hide_selection
    return hide_selection(ctx)


def _fb_show_all(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_hide_show_actions import show_all
    return show_all(ctx)


def _fb_lock_selection(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_lock_unlock_actions import lock_selection
    return lock_selection(ctx)


def _fb_unlock_all(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_lock_unlock_actions import unlock_all
    return unlock_all(ctx)


def _fb_select_by_prefab_kind(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_select_by_kind_actions import (
        select_by_prefab_kind,
    )
    return select_by_prefab_kind(ctx)


# ---------------------------------------------------------------------------
# KK7 STUB-triage fallbacks (2026-07-05 — round 13 after X3 / Y1 / Z7 /
# AA1 / BB1 / CC1 / DD1 / EE1 / FF1 / GG1 / II5 / JJ6)
#
# Five more action ids: mirror-X/Y/Z trio, orbit-selection, top-down view.
# See :mod:`slappyengine.actions.edit_mirror_actions`,
# :mod:`slappyengine.actions.view_orbit_actions`, and
# :mod:`slappyengine.actions.view_snap_actions`.
# ---------------------------------------------------------------------------


def _fb_mirror_selection_x(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_mirror_actions import mirror_selection_x
    return mirror_selection_x(ctx)


def _fb_mirror_selection_y(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_mirror_actions import mirror_selection_y
    return mirror_selection_y(ctx)


def _fb_mirror_selection_z(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_mirror_actions import mirror_selection_z
    return mirror_selection_z(ctx)


def _fb_orbit_selection(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.view_orbit_actions import orbit_selection
    return orbit_selection(ctx)


def _fb_top_down_view(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.view_snap_actions import top_down_view
    return top_down_view(ctx)


# ---------------------------------------------------------------------------
# NN2 STUB-triage (round 15 after r14 [capture + render_toggle]) — 5 more
# unwired action ids. See ``docs/feature_map_delta_2026_07_05.md`` for the
# per-id rationale; each Python fallback lives in
# :mod:`slappyengine.actions.view_frame_selected_actions`,
# :mod:`slappyengine.actions.view_reset_view_actions`,
# :mod:`slappyengine.actions.panel_dock_actions`, and
# :mod:`slappyengine.actions.theme_hot_swap_actions`.
# ---------------------------------------------------------------------------


def _fb_frame_selected(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.view_frame_selected_actions import frame_selected
    return frame_selected(ctx)


def _fb_reset_view(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.view_reset_view_actions import reset_view
    return reset_view(ctx)


def _fb_dock_left(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.panel_dock_actions import dock_left
    return dock_left(ctx)


def _fb_dock_right(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.panel_dock_actions import dock_right
    return dock_right(ctx)


def _fb_theme_hot_swap(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.theme_hot_swap_actions import hot_swap
    return hot_swap(ctx)


# ---------------------------------------------------------------------------
# OO1 STUB-triage (round 16 after NN2 round 15) — 5 more unwired action ids
# spanning layer / selection / snap categories. See
# ``docs/feature_map_delta_2026_07_07.md`` for the per-id rationale; each
# Python fallback lives in ``slappyengine.actions.layer_solo_actions``,
# ``layer_merge_down_actions``, ``selection_grow_actions``, and
# ``snap_grid_size_actions``.
# ---------------------------------------------------------------------------


def _fb_layer_solo(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.layer_solo_actions import solo_layer
    return solo_layer(ctx)


def _fb_layer_merge_down(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.layer_merge_down_actions import merge_down
    return merge_down(ctx)


def _fb_selection_grow(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.selection_grow_actions import grow_selection
    return grow_selection(ctx)


def _fb_snap_increase_grid_size(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.snap_grid_size_actions import increase_grid_size
    return increase_grid_size(ctx)


def _fb_snap_decrease_grid_size(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.snap_grid_size_actions import decrease_grid_size
    return decrease_grid_size(ctx)


# ---------------------------------------------------------------------------
# PP1 STUB-triage (round 17 after OO1 round 16) — 5 more unwired action ids
# spanning selection / view / edit categories. See
# ``docs/feature_map_delta_2026_07_08.md`` for the per-id rationale; each
# Python fallback lives in ``slappyengine.actions.selection_shrink_actions``,
# ``selection_invert_by_type_actions``, ``view_toggle_wireframe_actions``,
# ``edit_rename_actions``, and ``edit_duplicate_at_cursor_actions``.
# ---------------------------------------------------------------------------


def _fb_selection_shrink(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.selection_shrink_actions import shrink_selection
    return shrink_selection(ctx)


def _fb_selection_invert_by_type(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.selection_invert_by_type_actions import (
        invert_by_type,
    )
    return invert_by_type(ctx)


def _fb_view_toggle_wireframe(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.view_toggle_wireframe_actions import (
        toggle_wireframe,
    )
    return toggle_wireframe(ctx)


def _fb_edit_rename(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_rename_actions import rename_entity
    return rename_entity(ctx)


def _fb_edit_duplicate_at_cursor(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_duplicate_at_cursor_actions import (
        duplicate_at_cursor,
    )
    return duplicate_at_cursor(ctx)


# ---------------------------------------------------------------------------
# QQ1 STUB-triage (round 18 after PP1 round 17) — 5 more unwired action ids
# spanning spawn / selection / view categories. See
# ``docs/feature_map_delta_2026_07_09.md`` for the per-id rationale; each
# Python fallback lives in ``slappyengine.actions.spawn_origin_actions``,
# ``selection_by_type_actions``, ``selection_by_layer_actions``,
# ``selection_same_material_actions``, and ``view_toggle_stats_actions``.
# ---------------------------------------------------------------------------


def _fb_spawn_at_origin(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.spawn_origin_actions import spawn_at_origin
    return spawn_at_origin(ctx)


def _fb_selection_by_type(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.selection_by_type_actions import select_by_type
    return select_by_type(ctx)


def _fb_selection_by_layer(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.selection_by_layer_actions import (
        select_by_layer,
    )
    return select_by_layer(ctx)


def _fb_selection_same_material(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.selection_same_material_actions import (
        select_same_material,
    )
    return select_same_material(ctx)


def _fb_view_toggle_stats(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.view_toggle_stats_actions import toggle_stats
    return toggle_stats(ctx)


# ---------------------------------------------------------------------------
# RR1 STUB-triage fallbacks (2026-07-10 — round 19 after MM6 / NN2 / OO1 /
# PP1 / QQ1)
#
# Five more STUB rows flipped to WIRED: edit.select_similar (combined
# kind+material signature), theme.reset_to_default (snap active theme
# back to shipped baseline), layer.hide_others (one-shot hide-others,
# no snapshot), layer.isolate (entity-level Blender Numpad-/ isolate
# with toggle-restore), snap.toggle_incremental (numeric-step vs
# freeform snap mode toggle). Python fallback lives in
# ``slappyengine.actions.edit_select_similar_actions``,
# ``theme_reset_default_actions``, ``layer_hide_others_actions``,
# ``layer_isolate_actions``, and ``snap_toggle_incremental_actions``.
# ---------------------------------------------------------------------------


def _fb_edit_select_similar(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_select_similar_actions import (
        select_similar,
    )
    return select_similar(ctx)


def _fb_theme_reset_to_default(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.theme_reset_default_actions import (
        reset_to_default,
    )
    return reset_to_default(ctx)


def _fb_layer_hide_others(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.layer_hide_others_actions import hide_others
    return hide_others(ctx)


def _fb_layer_isolate(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.layer_isolate_actions import isolate
    return isolate(ctx)


def _fb_snap_toggle_incremental(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.snap_toggle_incremental_actions import (
        toggle_incremental,
    )
    return toggle_incremental(ctx)


# ---------------------------------------------------------------------------
# SS1 STUB-triage fallbacks (2026-07-11 — round 20 after RR1)
#
# Five more STUB rows flipped to WIRED: content.reveal_in_explorer
# (selects the item inside the OS explorer — distinct from FF1's
# content.reveal_in_folder which just opens the parent path),
# content.duplicate_folder (folder-only variant of
# content.duplicate_asset), view.increase_pixel_scale /
# view.decrease_pixel_scale (integer framebuffer scale step —
# distinct from Z7's continuous view.zoom_*), and
# spawn.stamp_repeat (hold-and-stamp N copies; distinct from
# spawn.spawn_batch_row + spawn.repeat_last). Python fallbacks live
# in ``slappyengine.actions.content_reveal_explorer_actions``,
# ``content_duplicate_folder_actions``, ``view_pixel_scale_actions``,
# and ``spawn_stamp_repeat_actions``.
# ---------------------------------------------------------------------------


def _fb_content_reveal_in_explorer(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.content_reveal_explorer_actions import (
        reveal_in_explorer,
    )
    return reveal_in_explorer(ctx)


def _fb_content_duplicate_folder(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.content_duplicate_folder_actions import (
        duplicate_folder,
    )
    return duplicate_folder(ctx)


def _fb_view_increase_pixel_scale(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.view_pixel_scale_actions import (
        increase_pixel_scale,
    )
    return increase_pixel_scale(ctx)


def _fb_view_decrease_pixel_scale(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.view_pixel_scale_actions import (
        decrease_pixel_scale,
    )
    return decrease_pixel_scale(ctx)


def _fb_spawn_stamp_repeat(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.spawn_stamp_repeat_actions import (
        stamp_repeat,
    )
    return stamp_repeat(ctx)


# ---------------------------------------------------------------------------
# TT2 STUB-triage fallbacks (2026-07-12 — round 21 after SS1)
#
# Five more STUB rows flipped to WIRED: view.set_zoom (absolute-zoom
# setter — distinct from Z7's zoom_in/zoom_out steps + SS1's integer
# pixel-scale steps), spawn.at_view_center (drop next spawn at the
# viewport focus — distinct from EE1's spawn_at_cursor + QQ1's
# spawn.at_origin), spawn.stamp_random (hold-and-stamp with random
# card selection from the stamp history — distinct from SS1's
# deterministic spawn.stamp_repeat), theme.reload_from_disk
# (targeted single-theme hot-reload — distinct from FF1's whole-
# registry theme.reload_all + RR1's theme.reset_to_default), and
# layer.rename (rename a Z-layer — distinct from PP1's edit.rename for
# entities + FF1's content.rename_asset for files). Python fallbacks
# live in ``slappyengine.actions.view_set_zoom_actions``,
# ``spawn_view_center_actions``, ``spawn_stamp_random_actions``,
# ``theme_reload_from_disk_actions``, and ``layer_rename_actions``.
# ---------------------------------------------------------------------------


def _fb_view_set_zoom(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.view_set_zoom_actions import set_zoom
    return set_zoom(ctx)


def _fb_spawn_at_view_center(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.spawn_view_center_actions import (
        spawn_at_view_center,
    )
    return spawn_at_view_center(ctx)


def _fb_spawn_stamp_random(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.spawn_stamp_random_actions import (
        stamp_random,
    )
    return stamp_random(ctx)


def _fb_theme_reload_from_disk(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.theme_reload_from_disk_actions import (
        reload_from_disk,
    )
    return reload_from_disk(ctx)


def _fb_layer_rename(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.layer_rename_actions import rename_layer
    return rename_layer(ctx)


# ---------------------------------------------------------------------------
# UU4 STUB-triage fallbacks (2026-07-13 — round 22 after TT2)
#
# Five more STUB rows flipped to WIRED:
#   * spawn.at_origin_offset — arm/repeat spawn at (0,0,0)+offset
#     (distinct from QQ1 spawn.at_origin's forced zero drop + TT2
#     spawn.at_view_center's camera-focus drop).
#   * edit.flatten_selection — deep-flatten group hierarchies in one
#     gesture (distinct from EE1 edit.ungroup_selection which only
#     peels a single nesting level).
#   * snap.set_angle_snap — set rotation-gizmo snap step in degrees
#     (distinct from OO1's positional grid-size steps + RR1's
#     snap.toggle_incremental boolean gate).
#   * layer.move_up / layer.move_down — swap the active layer with its
#     immediate Z-neighbour (distinct from OO1 layer.merge_down which
#     collapses two layers into one, + TT2 layer.rename which touches
#     names not order).
# Python fallbacks live in
# ``slappyengine.actions.spawn_origin_offset_actions``,
# ``edit_flatten_selection_actions``, ``snap_angle_snap_actions``, and
# ``layer_reorder_actions``.
# ---------------------------------------------------------------------------


def _fb_spawn_at_origin_offset(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.spawn_origin_offset_actions import (
        spawn_at_origin_offset,
    )
    return spawn_at_origin_offset(ctx)


def _fb_edit_flatten_selection(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.edit_flatten_selection_actions import (
        flatten_selection,
    )
    return flatten_selection(ctx)


def _fb_snap_set_angle_snap(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.snap_angle_snap_actions import set_angle_snap
    return set_angle_snap(ctx)


def _fb_layer_move_up(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.layer_reorder_actions import move_layer_up
    return move_layer_up(ctx)


def _fb_layer_move_down(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.layer_reorder_actions import move_layer_down
    return move_layer_down(ctx)


# ---------------------------------------------------------------------------
# VV4 STUB-triage fallbacks (2026-07-14 — round 23 after UU4)
#
# Five more STUB rows flipped to WIRED:
#   * layer.new                — insert a fresh Z-layer (Photoshop
#     Ctrl+Shift+N). Distinct from DD1 edit.duplicate_layer (clones an
#     existing layer).
#   * layer.delete             — remove the active Z-layer (Photoshop
#     trash-can). Distinct from OO1 layer.merge_down (collapses into
#     neighbour) — this discards. Refuses to delete the last layer.
#   * snap.set_grid_size       — absolute grid-size setter. Distinct
#     from OO1 snap.increase_grid_size / snap.decrease_grid_size (which
#     walk the geometric ladder rung-by-rung) + UU4 snap.set_angle_snap
#     (which sets the rotation-gizmo step, not the positional grid).
#   * view.toggle_ruler        — toggle the viewport ruler overlay
#     (Photoshop Ctrl+R). Distinct from CC1 view.toggle_grid /
#     view.toggle_gizmos, QQ1 view.toggle_stats, PP1
#     view.toggle_wireframe.
#   * spawn.at_last_position   — arm (don't fire) the next spawn at the
#     previous drop coordinate. Distinct from CC1 spawn.repeat_last
#     which fires immediately + QQ1 spawn.at_origin + TT2
#     spawn.at_view_center + UU4 spawn.at_origin_offset.
# Python fallbacks live in
# ``slappyengine.actions.layer_lifecycle_actions``,
# ``snap_set_grid_size_actions``, ``view_toggle_ruler_actions``, and
# ``spawn_last_position_actions``.
# ---------------------------------------------------------------------------


def _fb_layer_new(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.layer_lifecycle_actions import create_layer
    return create_layer(ctx)


def _fb_layer_delete(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.layer_lifecycle_actions import delete_layer
    return delete_layer(ctx)


def _fb_snap_set_grid_size(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.snap_set_grid_size_actions import set_grid_size
    return set_grid_size(ctx)


def _fb_view_toggle_ruler(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.view_toggle_ruler_actions import toggle_ruler
    return toggle_ruler(ctx)


def _fb_spawn_at_last_position(ctx: dict[str, Any]) -> Any:
    from slappyengine.actions.spawn_last_position_actions import (
        spawn_at_last_position,
    )
    return spawn_at_last_position(ctx)


def _fb_easter(ctx: dict[str, Any], creature_id: str, anim: str) -> Any:
    shell = ctx.get("shell")
    if shell is None:
        return None
    scheduler = getattr(shell, "_creature_scheduler", None)
    if scheduler is None:
        return None
    trigger = getattr(scheduler, "trigger", None)
    if callable(trigger):
        try:
            return trigger(creature_id, anim)
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# Default action seed — populates :data:`REGISTRY` at import time
# ---------------------------------------------------------------------------


def _default_actions() -> list[ToolAction]:
    """Return the canonical seed list. Called by :func:`register_default_actions`."""
    return [
        # ── File ─────────────────────────────────────────────────────
        ToolAction(
            action_id="editor.save",
            label="Save",
            rust_backing="slap_format.lz4_compress",
            python_fallback=_fb_save,
            required_args=[],
            category="file",
        ),
        ToolAction(
            action_id="editor.new",
            label="New Scene",
            rust_backing=None,
            python_fallback=_fb_new,
            required_args=[],
            category="file",
        ),
        ToolAction(
            action_id="editor.open",
            label="Open Scene",
            rust_backing="slap_format.lz4_decompress",
            python_fallback=_fb_open,
            required_args=["path"],
            category="file",
        ),
        ToolAction(
            action_id="editor.switch_project",
            label="Switch Project",
            rust_backing=None,
            python_fallback=_fb_switch_project,
            required_args=[],
            category="file",
        ),
        # ── X3 project-lifecycle actions (2026-07-04) ────────────────
        # Wired top-5 STUB actions from engine_feature_map_2026_07_04.
        ToolAction(
            action_id="editor.save_project",
            label="Save Project",
            rust_backing=None,
            python_fallback=_fb_save_project,
            required_args=[],
            category="file",
        ),
        ToolAction(
            action_id="editor.new_project",
            label="New Project",
            rust_backing=None,
            python_fallback=_fb_new_project,
            required_args=["path", "name"],
            category="file",
        ),
        ToolAction(
            action_id="editor.open_recent",
            label="Open Recent Project",
            rust_backing=None,
            python_fallback=_fb_open_recent,
            required_args=[],
            category="file",
        ),
        # ── BB1 STUB-triage: layout I/O to explicit files ──
        ToolAction(
            action_id="file.save_layout_as",
            label="Save Layout As...",
            rust_backing=None,
            python_fallback=_fb_save_layout_as,
            required_args=[],
            category="file",
        ),
        ToolAction(
            action_id="file.load_layout_from_file",
            label="Load Layout from File...",
            rust_backing=None,
            python_fallback=_fb_load_layout_from_file,
            required_args=[],
            category="file",
        ),
        # ── Edit ─────────────────────────────────────────────────────
        ToolAction(
            action_id="editor.undo",
            label="Undo",
            rust_backing=None,  # future _core.command_buffer.undo
            python_fallback=_fb_undo,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="editor.redo",
            label="Redo",
            rust_backing=None,  # future _core.command_buffer.redo
            python_fallback=_fb_redo,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="editor.delete",
            label="Delete Selection",
            rust_backing=None,  # future _core.scene_remove
            python_fallback=_fb_delete,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="editor.copy",
            label="Copy",
            rust_backing=None,
            python_fallback=lambda ctx: _shell_call(ctx, "_copy_selected"),
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="editor.paste",
            label="Paste",
            rust_backing=None,
            python_fallback=lambda ctx: _shell_call(ctx, "_paste_clipboard"),
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="editor.duplicate",
            label="Duplicate",
            rust_backing=None,
            python_fallback=lambda ctx: _shell_call(ctx, "_duplicate_selected"),
            required_args=[],
            category="edit",
        ),
        # X3 STUB-triage: EntityClipboard-backed duplicate flow.
        ToolAction(
            action_id="edit.duplicate_selection",
            label="Duplicate Selection",
            rust_backing=None,
            python_fallback=_fb_duplicate_selection,
            required_args=[],
            category="edit",
        ),
        # ── Y1 STUB-triage: selection / clipboard flows (2026-07-04) ──
        ToolAction(
            action_id="editor.copy_selection",
            label="Copy Selection",
            rust_backing=None,
            python_fallback=_fb_copy_selection,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="editor.paste_selection",
            label="Paste Selection",
            rust_backing=None,
            python_fallback=_fb_paste_selection,
            required_args=[],
            category="edit",
        ),
        # ── AA1 STUB-triage: destructive edits (2026-07-05, round 4) ──
        ToolAction(
            action_id="edit.cut_selection",
            label="Cut Selection",
            rust_backing=None,
            python_fallback=_fb_cut_selection,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="edit.delete_selection",
            label="Delete Selection",
            rust_backing=None,
            python_fallback=_fb_delete_selection,
            required_args=[],
            category="edit",
        ),
        # ── BB1 STUB-triage: history (2026-07-05, round 5) ────────────
        # Distinct from the legacy ``editor.undo`` / ``editor.redo`` —
        # this pair resolves the process-wide UndoStack directly instead
        # of the fragile shell -> engine._undo_manager hop.
        ToolAction(
            action_id="edit.undo",
            label="Undo (History)",
            rust_backing=None,
            python_fallback=_fb_edit_undo,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="edit.redo",
            label="Redo (History)",
            rust_backing=None,
            python_fallback=_fb_edit_redo,
            required_args=[],
            category="edit",
        ),
        # ── CC1 STUB-triage: select-by-name (2026-07-05, round 6) ─────
        ToolAction(
            action_id="edit.select_by_name",
            label="Select by Name...",
            rust_backing=None,
            python_fallback=_fb_select_by_name,
            required_args=["name"],
            category="edit",
        ),
        # ── DD1 STUB-triage: duplicate active layer (round 7) ─────────
        ToolAction(
            action_id="edit.duplicate_layer",
            label="Duplicate Layer",
            rust_backing=None,
            python_fallback=_fb_duplicate_layer,
            required_args=[],
            category="edit",
        ),
        # ── EE1 STUB-triage: group / ungroup / snap-to-pixel (round 8) ─
        ToolAction(
            action_id="edit.group_selection",
            label="Group Selection",
            rust_backing=None,
            python_fallback=_fb_group_selection,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="edit.ungroup_selection",
            label="Ungroup Selection",
            rust_backing=None,
            python_fallback=_fb_ungroup_selection,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="edit.snap_to_pixel_grid",
            label="Snap to Pixel Grid",
            rust_backing=None,
            python_fallback=_fb_snap_to_pixel_grid,
            required_args=[],
            category="edit",
        ),
        # ── Tool changes ─────────────────────────────────────────────
        ToolAction(
            action_id="editor.tool_select",
            label="Select Tool",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_set_tool(ctx, "select"),
            required_args=[],
            category="tool",
        ),
        ToolAction(
            action_id="editor.tool_move",
            label="Move Tool",
            rust_backing="physics.PhysicsWorld",
            python_fallback=lambda ctx: _fb_set_tool(ctx, "move"),
            required_args=[],
            category="tool",
        ),
        ToolAction(
            action_id="editor.tool_rotate",
            label="Rotate Tool",
            rust_backing="math_3d.Quaternion",
            python_fallback=lambda ctx: _fb_set_tool(ctx, "rotate"),
            required_args=[],
            category="tool",
        ),
        ToolAction(
            action_id="editor.tool_scale",
            label="Scale Tool",
            rust_backing="math_3d.Mat4x4",
            python_fallback=lambda ctx: _fb_set_tool(ctx, "scale"),
            required_args=[],
            category="tool",
        ),
        # Y1 STUB-triage: scene-wide selection flows.
        ToolAction(
            action_id="tool.select_all",
            label="Select All",
            rust_backing=None,
            python_fallback=_fb_select_all,
            required_args=[],
            category="tool",
        ),
        ToolAction(
            action_id="tool.deselect_all",
            label="Deselect All",
            rust_backing=None,
            python_fallback=_fb_deselect_all,
            required_args=[],
            category="tool",
        ),
        # Z7 STUB-triage: snap-to-grid tool-setting toggle.
        ToolAction(
            action_id="tool.snap_to_grid",
            label="Toggle Snap to Grid",
            rust_backing=None,
            python_fallback=_fb_snap_to_grid,
            required_args=[],
            category="tool",
        ),
        # AA1 STUB-triage: navigation-mode "pan" tool activation.
        ToolAction(
            action_id="tool.pan",
            label="Pan Tool",
            rust_backing=None,
            python_fallback=_fb_activate_pan_tool,
            required_args=[],
            category="tool",
        ),
        # ── View / layout / theme ────────────────────────────────────
        ToolAction(
            action_id="editor.reset_layout",
            label="Reset Layout",
            rust_backing=None,
            python_fallback=_fb_reset_layout,
            required_args=[],
            category="layout",
        ),
        # X3 STUB-triage: category="view" alias — restores DEFAULT preset
        # via ``apply_layout_preset`` with a headless-safe fallback.
        ToolAction(
            action_id="view.reset_layout",
            label="Reset Layout (View)",
            rust_backing=None,
            python_fallback=_fb_view_reset_layout,
            required_args=[],
            category="view",
        ),
        ToolAction(
            action_id="editor.layout_preset_default",
            label="Layout Preset: Default",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_layout_preset(ctx, "default"),
            required_args=[],
            category="layout",
        ),
        ToolAction(
            action_id="editor.layout_preset_wide_code",
            label="Layout Preset: Wide Code",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_layout_preset(ctx, "wide_code"),
            required_args=[],
            category="layout",
        ),
        ToolAction(
            action_id="editor.layout_preset_focus",
            label="Layout Preset: Focus",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_layout_preset(ctx, "focus"),
            required_args=[],
            category="layout",
        ),
        ToolAction(
            action_id="editor.layout_preset_triple_pane",
            label="Layout Preset: Triple Pane",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_layout_preset(ctx, "triple_pane"),
            required_args=[],
            category="layout",
        ),
        ToolAction(
            action_id="editor.layout_preset_compact",
            label="Layout Preset: Compact",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_layout_preset(ctx, "compact"),
            required_args=[],
            category="layout",
        ),
        ToolAction(
            action_id="editor.toggle_theme_switcher",
            label="Toggle Theme Switcher",
            rust_backing=None,
            python_fallback=_fb_toggle_theme_switcher,
            required_args=[],
            category="theme",
        ),
        ToolAction(
            action_id="editor.cycle_theme",
            label="Cycle Theme",
            rust_backing=None,
            python_fallback=_fb_cycle_theme,
            required_args=[],
            category="theme",
        ),
        # Y1 STUB-triage: category="theme" alias — headless-safe cycle
        # over ``list_registered_themes()`` when no shell is present.
        ToolAction(
            action_id="theme.cycle",
            label="Cycle Theme (headless-safe)",
            rust_backing=None,
            python_fallback=_fb_theme_cycle,
            required_args=[],
            category="theme",
        ),
        ToolAction(
            action_id="editor.toggle_fullscreen",
            label="Toggle Fullscreen",
            rust_backing=None,
            python_fallback=_fb_toggle_fullscreen,
            required_args=[],
            category="view",
        ),
        # Z7 STUB-triage: viewport-camera zoom actions.
        ToolAction(
            action_id="view.zoom_in",
            label="Zoom In",
            rust_backing=None,
            python_fallback=_fb_zoom_in,
            required_args=[],
            category="view",
        ),
        ToolAction(
            action_id="view.zoom_out",
            label="Zoom Out",
            rust_backing=None,
            python_fallback=_fb_zoom_out,
            required_args=[],
            category="view",
        ),
        ToolAction(
            action_id="view.zoom_reset",
            label="Reset Zoom",
            rust_backing=None,
            python_fallback=_fb_zoom_reset,
            required_args=[],
            category="view",
        ),
        # AA1 STUB-triage: viewport framing (pan-only + frame-all).
        ToolAction(
            action_id="view.center_on_selection",
            label="Center on Selection",
            rust_backing=None,
            python_fallback=_fb_center_on_selection,
            required_args=[],
            category="view",
        ),
        ToolAction(
            action_id="view.frame_all",
            label="Frame All",
            rust_backing=None,
            python_fallback=_fb_frame_all,
            required_args=[],
            category="view",
        ),
        # CC6 sprint tick — animation-curve-driven camera moves.
        ToolAction(
            action_id="view.focus_on_selection_animated",
            label="Focus on Selection (Animated)",
            rust_backing=None,
            python_fallback=_fb_focus_on_selection_animated,
            required_args=[],
            category="view",
        ),
        ToolAction(
            action_id="view.frame_all_animated",
            label="Frame All (Animated)",
            rust_backing=None,
            python_fallback=_fb_frame_all_animated,
            required_args=[],
            category="view",
        ),
        # ── CC1 STUB-triage: overlay toggles (2026-07-05, round 6) ────
        ToolAction(
            action_id="view.toggle_grid",
            label="Toggle Grid",
            rust_backing=None,
            python_fallback=_fb_toggle_grid,
            required_args=[],
            category="view",
        ),
        ToolAction(
            action_id="view.toggle_gizmos",
            label="Toggle Gizmos",
            rust_backing=None,
            python_fallback=_fb_toggle_gizmos,
            required_args=[],
            category="view",
        ),
        # Z7 STUB-triage: active-theme YAML export.
        ToolAction(
            action_id="theme.export_current",
            label="Export Current Theme...",
            rust_backing=None,
            python_fallback=_fb_export_current_theme,
            required_args=[],
            category="theme",
        ),
        # BB1 STUB-triage: theme import from a caller-chosen file.
        ToolAction(
            action_id="theme.import_from_file",
            label="Import Theme from File...",
            rust_backing=None,
            python_fallback=_fb_theme_import_from_file,
            required_args=[],
            category="theme",
        ),
        # ── DD1 STUB-triage: reverse theme cycle (round 7) ────────────
        ToolAction(
            action_id="theme.cycle_reverse",
            label="Cycle Theme (Reverse)",
            rust_backing=None,
            python_fallback=_fb_cycle_theme_reverse,
            required_args=[],
            category="theme",
        ),
        # ── EE1 STUB-triage: random-theme picker (round 8) ────────────
        ToolAction(
            action_id="theme.random",
            label="Random Theme",
            rust_backing=None,
            python_fallback=_fb_random_theme,
            required_args=[],
            category="theme",
        ),
        ToolAction(
            action_id="editor.toggle_hud",
            label="Toggle HUD",
            rust_backing=None,
            python_fallback=_fb_toggle_hud,
            required_args=[],
            category="view",
        ),
        ToolAction(
            action_id="editor.profiler_toggle",
            label="Toggle Profiler",
            rust_backing=None,
            python_fallback=_fb_profiler_toggle,
            required_args=[],
            category="view",
        ),
        ToolAction(
            action_id="editor.help",
            label="Help / Welcome",
            rust_backing=None,
            python_fallback=_fb_help,
            required_args=[],
            category="view",
        ),
        ToolAction(
            action_id="editor.play",
            label="Play / Stop",
            rust_backing=None,
            python_fallback=_fb_toggle_play,
            required_args=[],
            category="view",
        ),
        ToolAction(
            action_id="editor.run",
            label="Run",
            rust_backing=None,
            python_fallback=_fb_toggle_play,
            required_args=[],
            category="view",
        ),
        # ── Panel toggles (Ctrl+\, Ctrl+Shift+\, Ctrl+/, Ctrl+Shift+/)
        ToolAction(
            action_id="editor.toggle_panel_outliner",
            label="Toggle Outliner Panel",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_toggle_panel(ctx, "outliner"),
            required_args=[],
            category="panel",
        ),
        ToolAction(
            action_id="editor.toggle_panel_inspector",
            label="Toggle Inspector Panel",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_toggle_panel(ctx, "inspector"),
            required_args=[],
            category="panel",
        ),
        ToolAction(
            action_id="editor.toggle_panel_content_browser",
            label="Toggle Content Browser",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_toggle_panel(ctx, "content_browser"),
            required_args=[],
            category="panel",
        ),
        ToolAction(
            action_id="editor.toggle_panel_code",
            label="Toggle Code Panel",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_toggle_panel(ctx, "code"),
            required_args=[],
            category="panel",
        ),
        ToolAction(
            action_id="editor.toggle_panel_viewport",
            label="Toggle Viewport Panel",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_toggle_panel(ctx, "viewport_panel"),
            required_args=[],
            category="panel",
        ),
        ToolAction(
            action_id="editor.toggle_panel_layer",
            label="Toggle Layer Panel",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_toggle_panel(ctx, "layer_panel"),
            required_args=[],
            category="panel",
        ),
        ToolAction(
            action_id="editor.toggle_panel_behavior",
            label="Toggle Behavior Panel",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_toggle_panel(ctx, "behavior_panel"),
            required_args=[],
            category="panel",
        ),
        ToolAction(
            action_id="editor.toggle_panel_tag_painter",
            label="Toggle Tag Painter",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_toggle_panel(ctx, "tag_painter"),
            required_args=[],
            category="panel",
        ),
        # ── DD1 STUB-triage: batch panel visibility (round 7) ────────
        ToolAction(
            action_id="panel.close_all",
            label="Close All Panels",
            rust_backing=None,
            python_fallback=_fb_close_all_panels,
            required_args=[],
            category="panel",
        ),
        ToolAction(
            action_id="panel.restore_last_hidden",
            label="Restore Last Hidden Panel",
            rust_backing=None,
            python_fallback=_fb_restore_last_hidden_panel,
            required_args=[],
            category="panel",
        ),
        # ── Spawn cards (10 entries — one per SPAWN_CARDS row) ───────
        ToolAction(
            action_id="spawn.rope",
            label="Spawn Rope",
            rust_backing="softbody_solver.slappyengine_step",
            python_fallback=lambda ctx: _fb_spawn(ctx, "rope"),
            required_args=["spec"],
            category="spawn",
        ),
        ToolAction(
            action_id="spawn.ragdoll",
            label="Spawn Ragdoll",
            rust_backing="softbody_solver.slappyengine_step",
            python_fallback=lambda ctx: _fb_spawn(ctx, "ragdoll"),
            required_args=["spec"],
            category="spawn",
        ),
        ToolAction(
            action_id="spawn.humanoid",
            label="Spawn Humanoid",
            rust_backing="ik_solver.solve_ik",
            python_fallback=lambda ctx: _fb_spawn(ctx, "humanoid"),
            required_args=["spec"],
            category="spawn",
        ),
        ToolAction(
            action_id="spawn.ik_chain",
            label="Spawn IK Chain",
            rust_backing="ik_solver.solve_ik",
            python_fallback=lambda ctx: _fb_spawn(ctx, "ik_chain"),
            required_args=["spec"],
            category="spawn",
        ),
        ToolAction(
            action_id="spawn.zone_rect",
            label="Spawn Rect Zone",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_spawn(ctx, "zone_rect"),
            required_args=["spec"],
            category="spawn",
        ),
        ToolAction(
            action_id="spawn.zone_threshold",
            label="Spawn Threshold Zone",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_spawn(ctx, "zone_threshold"),
            required_args=["spec"],
            category="spawn",
        ),
        ToolAction(
            action_id="spawn.light_point",
            label="Spawn Point Light",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_spawn(ctx, "light_point"),
            required_args=["spec"],
            category="spawn",
        ),
        ToolAction(
            action_id="spawn.light_directional",
            label="Spawn Directional Light",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_spawn(ctx, "light_directional"),
            required_args=["spec"],
            category="spawn",
        ),
        ToolAction(
            action_id="spawn.material",
            label="Spawn Material",
            rust_backing="node_compiler.compile_node_graph",
            python_fallback=lambda ctx: _fb_spawn(ctx, "material"),
            required_args=["spec"],
            category="spawn",
        ),
        ToolAction(
            action_id="spawn.emitter",
            label="Spawn Particle Emitter",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_spawn(ctx, "emitter"),
            required_args=["spec"],
            category="spawn",
        ),
        # ── CC1 STUB-triage: replay most-recent spawn (round 6) ───────
        ToolAction(
            action_id="spawn.repeat_last",
            label="Repeat Last Spawn",
            rust_backing=None,
            python_fallback=_fb_repeat_last_spawn,
            required_args=[],
            category="spawn",
        ),
        # ── DD1 STUB-triage: grid-batch repeat (round 7) ──────────────
        ToolAction(
            action_id="spawn.repeat_last_batch",
            label="Repeat Last Spawn (Batch)",
            rust_backing=None,
            python_fallback=_fb_repeat_last_batch,
            required_args=[],
            category="spawn",
        ),
        # ── EE1 STUB-triage: spawn-at-cursor arming (round 8) ─────────
        ToolAction(
            action_id="spawn.spawn_at_cursor",
            label="Spawn at Cursor",
            rust_backing=None,
            python_fallback=_fb_spawn_at_cursor,
            required_args=[],
            category="spawn",
        ),
        # ── Content-browser actions ──────────────────────────────────
        ToolAction(
            action_id="content.open",
            label="Open Asset",
            rust_backing=None,
            python_fallback=_fb_content_open,
            required_args=["path"],
            category="content",
        ),
        ToolAction(
            action_id="content.reveal_in_folder",
            label="Reveal in Folder",
            rust_backing=None,
            python_fallback=_fb_reveal_in_folder,
            required_args=["path"],
            category="content",
        ),
        ToolAction(
            action_id="content.import",
            label="Import Asset...",
            rust_backing="slap_format.lz4_compress",
            python_fallback=_fb_content_import,
            required_args=[],
            category="content",
        ),
        ToolAction(
            action_id="content.new_script",
            label="New Script",
            rust_backing=None,
            python_fallback=_fb_content_new_script,
            required_args=[],
            category="content",
        ),
        # ── CC1 STUB-triage: copy asset path to clipboard (round 6) ──
        ToolAction(
            action_id="content.copy_asset_path",
            label="Copy Asset Path",
            rust_backing=None,
            python_fallback=_fb_copy_asset_path,
            required_args=["path"],
            category="content",
        ),
        # ── FF1 STUB-triage: new folder + rename (round 9) ────────────
        ToolAction(
            action_id="content.new_folder",
            label="New Folder",
            rust_backing=None,
            python_fallback=_fb_new_folder,
            required_args=[],
            category="content",
        ),
        ToolAction(
            action_id="content.rename_asset",
            label="Rename Asset...",
            rust_backing=None,
            python_fallback=_fb_rename_asset,
            required_args=["path", "new_name"],
            category="content",
        ),
        # ── FF1 STUB-triage: solo panel + recursive select + theme
        #    registry reload (round 9) ───────────────────────────────
        ToolAction(
            action_id="panel.close_others",
            label="Close Other Panels",
            rust_backing=None,
            python_fallback=_fb_close_other_panels,
            required_args=[],
            category="panel",
        ),
        ToolAction(
            action_id="edit.select_children",
            label="Select Children",
            rust_backing=None,
            python_fallback=_fb_select_children,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="theme.reload_all",
            label="Reload All Themes",
            rust_backing=None,
            python_fallback=_fb_reload_all_themes,
            required_args=[],
            category="theme",
        ),
        # ── GG1 STUB-triage: content delete + panel layout +
        #    invert selection + view fullscreen (round 10) ────────────
        ToolAction(
            action_id="content.delete_asset",
            label="Delete Asset...",
            rust_backing=None,
            python_fallback=_fb_delete_asset,
            required_args=["path"],
            category="content",
        ),
        ToolAction(
            action_id="panel.tile_grid",
            label="Tile Panels in Grid",
            rust_backing=None,
            python_fallback=_fb_tile_grid,
            required_args=[],
            category="panel",
        ),
        ToolAction(
            action_id="panel.cascade",
            label="Cascade Panels",
            rust_backing=None,
            python_fallback=_fb_cascade_panels,
            required_args=[],
            category="panel",
        ),
        ToolAction(
            action_id="edit.invert_selection",
            label="Invert Selection",
            rust_backing=None,
            python_fallback=_fb_invert_selection,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="view.fullscreen",
            label="Fullscreen (Focus Mode)",
            rust_backing=None,
            python_fallback=_fb_view_fullscreen,
            required_args=[],
            category="view",
        ),
        # ── II5 STUB-triage: tab-select + paste-at-original +
        #    row-batch spawn + content-duplicate (round 11) ────────────
        ToolAction(
            action_id="edit.select_next",
            label="Select Next Entity",
            rust_backing=None,
            python_fallback=_fb_select_next,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="edit.select_previous",
            label="Select Previous Entity",
            rust_backing=None,
            python_fallback=_fb_select_previous,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="edit.paste_at_original_position",
            label="Paste at Original Position",
            rust_backing=None,
            python_fallback=_fb_paste_at_original_position,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="spawn.spawn_batch_row",
            label="Spawn Batch (Row)",
            rust_backing=None,
            python_fallback=_fb_spawn_batch_row,
            required_args=[],
            category="spawn",
        ),
        ToolAction(
            action_id="content.duplicate_asset",
            label="Duplicate Asset",
            rust_backing=None,
            python_fallback=_fb_duplicate_asset,
            required_args=["path"],
            category="content",
        ),
        # ── JJ6 STUB-triage: hide/show + lock/unlock + select-by-kind
        #    (round 12) ────────────────────────────────────────────────
        ToolAction(
            action_id="edit.hide_selection",
            label="Hide Selection",
            rust_backing=None,
            python_fallback=_fb_hide_selection,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="edit.show_all",
            label="Show All",
            rust_backing=None,
            python_fallback=_fb_show_all,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="edit.lock_selection",
            label="Lock Selection",
            rust_backing=None,
            python_fallback=_fb_lock_selection,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="edit.unlock_all",
            label="Unlock All",
            rust_backing=None,
            python_fallback=_fb_unlock_all,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="edit.select_by_prefab_kind",
            label="Select by Prefab Kind",
            rust_backing=None,
            python_fallback=_fb_select_by_prefab_kind,
            required_args=[],
            category="edit",
        ),
        # ── KK7 STUB-triage: mirror-X/Y/Z + orbit-selection + top-down
        #    view (round 13) ────────────────────────────────────────────
        ToolAction(
            action_id="edit.mirror_selection_x",
            label="Mirror Selection (X)",
            rust_backing=None,
            python_fallback=_fb_mirror_selection_x,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="edit.mirror_selection_y",
            label="Mirror Selection (Y)",
            rust_backing=None,
            python_fallback=_fb_mirror_selection_y,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="edit.mirror_selection_z",
            label="Mirror Selection (Z)",
            rust_backing=None,
            python_fallback=_fb_mirror_selection_z,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="view.orbit_selection",
            label="Orbit Selection",
            rust_backing=None,
            python_fallback=_fb_orbit_selection,
            required_args=[],
            category="view",
        ),
        ToolAction(
            action_id="view.top_down_view",
            label="Top-Down View",
            rust_backing=None,
            python_fallback=_fb_top_down_view,
            required_args=[],
            category="view",
        ),
        # ── NN2 STUB-triage: frame-selected + reset-view + panel dock
        #    L/R + theme hot-swap (round 15) ───────────────────────────
        ToolAction(
            action_id="view.frame_selected",
            label="Frame Selected",
            rust_backing=None,
            python_fallback=_fb_frame_selected,
            required_args=[],
            category="view",
        ),
        ToolAction(
            action_id="view.reset_view",
            label="Reset View",
            rust_backing=None,
            python_fallback=_fb_reset_view,
            required_args=[],
            category="view",
        ),
        ToolAction(
            action_id="panel.dock_left",
            label="Dock Panel Left",
            rust_backing=None,
            python_fallback=_fb_dock_left,
            required_args=["panel_id"],
            category="panel",
        ),
        ToolAction(
            action_id="panel.dock_right",
            label="Dock Panel Right",
            rust_backing=None,
            python_fallback=_fb_dock_right,
            required_args=["panel_id"],
            category="panel",
        ),
        ToolAction(
            action_id="theme.hot_swap",
            label="Hot-Swap Theme",
            rust_backing=None,
            python_fallback=_fb_theme_hot_swap,
            required_args=["theme"],
            category="theme",
        ),
        # ── OO1 STUB-triage: layer solo + merge-down + selection grow +
        #    snap grid-size increment / decrement (round 16) ────────────
        ToolAction(
            action_id="layer.solo",
            label="Solo Layer",
            rust_backing=None,
            python_fallback=_fb_layer_solo,
            required_args=[],
            category="layer",
        ),
        ToolAction(
            action_id="layer.merge_down",
            label="Merge Layer Down",
            rust_backing=None,
            python_fallback=_fb_layer_merge_down,
            required_args=[],
            category="layer",
        ),
        ToolAction(
            action_id="selection.grow",
            label="Grow Selection",
            rust_backing=None,
            python_fallback=_fb_selection_grow,
            required_args=[],
            category="selection",
        ),
        ToolAction(
            action_id="snap.increase_grid_size",
            label="Increase Grid Size",
            rust_backing=None,
            python_fallback=_fb_snap_increase_grid_size,
            required_args=[],
            category="snap",
        ),
        ToolAction(
            action_id="snap.decrease_grid_size",
            label="Decrease Grid Size",
            rust_backing=None,
            python_fallback=_fb_snap_decrease_grid_size,
            required_args=[],
            category="snap",
        ),
        # ── PP1 STUB-triage: selection shrink / invert-by-type + view
        #    wireframe + edit rename / duplicate-at-cursor (round 17) ──
        ToolAction(
            action_id="selection.shrink",
            label="Shrink Selection",
            rust_backing=None,
            python_fallback=_fb_selection_shrink,
            required_args=[],
            category="selection",
        ),
        ToolAction(
            action_id="selection.invert_by_type",
            label="Invert Selection by Type",
            rust_backing=None,
            python_fallback=_fb_selection_invert_by_type,
            required_args=[],
            category="selection",
        ),
        ToolAction(
            action_id="view.toggle_wireframe",
            label="Toggle Wireframe",
            rust_backing=None,
            python_fallback=_fb_view_toggle_wireframe,
            required_args=[],
            category="view",
        ),
        ToolAction(
            action_id="edit.rename",
            label="Rename Entity",
            rust_backing=None,
            python_fallback=_fb_edit_rename,
            required_args=["new_name"],
            category="edit",
        ),
        ToolAction(
            action_id="edit.duplicate_at_cursor",
            label="Duplicate at Cursor",
            rust_backing=None,
            python_fallback=_fb_edit_duplicate_at_cursor,
            required_args=[],
            category="edit",
        ),
        # ── QQ1 STUB-triage: spawn-at-origin, selection by type / layer /
        #    material, view toggle-stats overlay (round 18) ──
        ToolAction(
            action_id="spawn.at_origin",
            label="Spawn at Origin",
            rust_backing=None,
            python_fallback=_fb_spawn_at_origin,
            required_args=[],
            category="spawn",
        ),
        ToolAction(
            action_id="selection.by_type",
            label="Select All by Type",
            rust_backing=None,
            python_fallback=_fb_selection_by_type,
            required_args=[],
            category="selection",
        ),
        ToolAction(
            action_id="selection.by_layer",
            label="Select All on Layer",
            rust_backing=None,
            python_fallback=_fb_selection_by_layer,
            required_args=[],
            category="selection",
        ),
        ToolAction(
            action_id="selection.same_material",
            label="Select Same Material",
            rust_backing=None,
            python_fallback=_fb_selection_same_material,
            required_args=[],
            category="selection",
        ),
        ToolAction(
            action_id="view.toggle_stats",
            label="Toggle Stats Overlay",
            rust_backing=None,
            python_fallback=_fb_view_toggle_stats,
            required_args=[],
            category="view",
        ),
        # ── RR1 STUB-triage: select-similar, theme reset-to-default,
        #    layer hide-others + isolate, snap toggle-incremental
        #    (round 19) ──
        ToolAction(
            action_id="edit.select_similar",
            label="Select Similar",
            rust_backing=None,
            python_fallback=_fb_edit_select_similar,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="theme.reset_to_default",
            label="Reset Theme to Default",
            rust_backing=None,
            python_fallback=_fb_theme_reset_to_default,
            required_args=[],
            category="theme",
        ),
        ToolAction(
            action_id="layer.hide_others",
            label="Hide Other Layers",
            rust_backing=None,
            python_fallback=_fb_layer_hide_others,
            required_args=[],
            category="layer",
        ),
        ToolAction(
            action_id="layer.isolate",
            label="Isolate Selection",
            rust_backing=None,
            python_fallback=_fb_layer_isolate,
            required_args=[],
            category="layer",
        ),
        ToolAction(
            action_id="snap.toggle_incremental",
            label="Toggle Incremental Snap",
            rust_backing=None,
            python_fallback=_fb_snap_toggle_incremental,
            required_args=[],
            category="snap",
        ),
        # ── SS1 STUB-triage: content reveal-in-explorer / duplicate-folder,
        #    view pixel-scale up/down, spawn stamp-repeat (round 20) ──
        ToolAction(
            action_id="content.reveal_in_explorer",
            label="Reveal in Explorer",
            rust_backing=None,
            python_fallback=_fb_content_reveal_in_explorer,
            required_args=["path"],
            category="content",
        ),
        ToolAction(
            action_id="content.duplicate_folder",
            label="Duplicate Folder",
            rust_backing=None,
            python_fallback=_fb_content_duplicate_folder,
            required_args=["path"],
            category="content",
        ),
        ToolAction(
            action_id="view.increase_pixel_scale",
            label="Increase Pixel Scale",
            rust_backing=None,
            python_fallback=_fb_view_increase_pixel_scale,
            required_args=[],
            category="view",
        ),
        ToolAction(
            action_id="view.decrease_pixel_scale",
            label="Decrease Pixel Scale",
            rust_backing=None,
            python_fallback=_fb_view_decrease_pixel_scale,
            required_args=[],
            category="view",
        ),
        ToolAction(
            action_id="spawn.stamp_repeat",
            label="Stamp Repeat Spawn",
            rust_backing=None,
            python_fallback=_fb_spawn_stamp_repeat,
            required_args=[],
            category="spawn",
        ),
        # ── TT2 STUB-triage: view.set_zoom, spawn.at_view_center,
        #    spawn.stamp_random, theme.reload_from_disk, layer.rename
        #    (round 21) ──
        ToolAction(
            action_id="view.set_zoom",
            label="Set Zoom",
            rust_backing=None,
            python_fallback=_fb_view_set_zoom,
            required_args=["distance"],
            category="view",
        ),
        ToolAction(
            action_id="spawn.at_view_center",
            label="Spawn at View Center",
            rust_backing=None,
            python_fallback=_fb_spawn_at_view_center,
            required_args=[],
            category="spawn",
        ),
        ToolAction(
            action_id="spawn.stamp_random",
            label="Stamp Random Spawn",
            rust_backing=None,
            python_fallback=_fb_spawn_stamp_random,
            required_args=[],
            category="spawn",
        ),
        ToolAction(
            action_id="theme.reload_from_disk",
            label="Reload Theme from Disk",
            rust_backing=None,
            python_fallback=_fb_theme_reload_from_disk,
            required_args=[],
            category="theme",
        ),
        ToolAction(
            action_id="layer.rename",
            label="Rename Layer",
            rust_backing=None,
            python_fallback=_fb_layer_rename,
            required_args=["new_name"],
            category="layer",
        ),
        # ── UU4 STUB-triage: spawn.at_origin_offset,
        #    edit.flatten_selection, snap.set_angle_snap,
        #    layer.move_up, layer.move_down (round 22) ─────────────────
        ToolAction(
            action_id="spawn.at_origin_offset",
            label="Spawn at Origin + Offset",
            rust_backing=None,
            python_fallback=_fb_spawn_at_origin_offset,
            required_args=[],
            category="spawn",
        ),
        ToolAction(
            action_id="edit.flatten_selection",
            label="Flatten Selection (Deep Ungroup)",
            rust_backing=None,
            python_fallback=_fb_edit_flatten_selection,
            required_args=[],
            category="edit",
        ),
        ToolAction(
            action_id="snap.set_angle_snap",
            label="Set Angle Snap",
            rust_backing=None,
            python_fallback=_fb_snap_set_angle_snap,
            required_args=["degrees"],
            category="snap",
        ),
        ToolAction(
            action_id="layer.move_up",
            label="Move Layer Up",
            rust_backing=None,
            python_fallback=_fb_layer_move_up,
            required_args=[],
            category="layer",
        ),
        ToolAction(
            action_id="layer.move_down",
            label="Move Layer Down",
            rust_backing=None,
            python_fallback=_fb_layer_move_down,
            required_args=[],
            category="layer",
        ),
        # ── VV4 STUB-triage: layer.new, layer.delete,
        #    snap.set_grid_size, view.toggle_ruler,
        #    spawn.at_last_position (round 23) ─────────────────────────
        ToolAction(
            action_id="layer.new",
            label="New Layer",
            rust_backing=None,
            python_fallback=_fb_layer_new,
            required_args=[],
            category="layer",
        ),
        ToolAction(
            action_id="layer.delete",
            label="Delete Layer",
            rust_backing=None,
            python_fallback=_fb_layer_delete,
            required_args=[],
            category="layer",
        ),
        ToolAction(
            action_id="snap.set_grid_size",
            label="Set Grid Size",
            rust_backing=None,
            python_fallback=_fb_snap_set_grid_size,
            required_args=["size"],
            category="snap",
        ),
        ToolAction(
            action_id="view.toggle_ruler",
            label="Toggle Ruler",
            rust_backing=None,
            python_fallback=_fb_view_toggle_ruler,
            required_args=[],
            category="view",
        ),
        ToolAction(
            action_id="spawn.at_last_position",
            label="Spawn at Last Position",
            rust_backing=None,
            python_fallback=_fb_spawn_at_last_position,
            required_args=[],
            category="spawn",
        ),
        # ── Easter eggs (creature triggers) ──────────────────────────
        ToolAction(
            action_id="editor.easter_feed_fox",
            label="Feed the Fox",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_easter(ctx, "fox_01", "feed"),
            required_args=[],
            category="easter",
        ),
        ToolAction(
            action_id="editor.easter_baby_porcupine_roll",
            label="Baby Porcupine Roll",
            rust_backing=None,
            python_fallback=lambda ctx: _fb_easter(
                ctx, "porcupine_01", "ball_up",
            ),
            required_args=[],
            category="easter",
        ),
    ]


def register_default_actions(router: ToolRouter) -> int:
    """Populate *router* with every canonical editor action.

    Returns the count of newly-registered actions (0 when the router
    already had them all — idempotent per :meth:`ToolRouter.register`).
    """
    if not isinstance(router, ToolRouter):
        raise TypeError(
            "register_default_actions: router must be a ToolRouter"
        )
    before = len(router._actions)
    for action in _default_actions():
        router.register(action)
    return len(router._actions) - before


# ---------------------------------------------------------------------------
# Module-level singleton — populated at import time
# ---------------------------------------------------------------------------


REGISTRY: ToolRouter = ToolRouter()
register_default_actions(REGISTRY)


__all__ = [
    "ToolAction",
    "ToolRouter",
    "REGISTRY",
    "register_default_actions",
]
