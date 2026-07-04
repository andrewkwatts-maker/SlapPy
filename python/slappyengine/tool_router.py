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
        # ── View / layout / theme ────────────────────────────────────
        ToolAction(
            action_id="editor.reset_layout",
            label="Reset Layout",
            rust_backing=None,
            python_fallback=_fb_reset_layout,
            required_args=[],
            category="layout",
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
        ToolAction(
            action_id="editor.toggle_fullscreen",
            label="Toggle Fullscreen",
            rust_backing=None,
            python_fallback=_fb_toggle_fullscreen,
            required_args=[],
            category="view",
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
