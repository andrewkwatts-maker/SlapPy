"""Panel-visibility batch actions — close-all + restore-last-hidden.

Backs two :class:`~pharos_engine.tool_router.ToolAction` rows added by
the DD1 STUB-triage sprint tick (round 7):

* ``panel.close_all`` — hide every currently-visible panel and remember
  the list on a stack so the next ``panel.restore_last_hidden`` call can
  bring them back.
* ``panel.restore_last_hidden`` — un-hide the most recent panel batch
  (or, when the stack is empty, the single most recently toggled panel).

Both actions maintain a shell-owned stack ``shell._hidden_panel_stack``.
Each entry is a ``list[str]`` of panel ids — a single-panel toggle
pushes a 1-item entry, ``panel.close_all`` pushes an N-item entry with
every panel it just hid. This lets ``restore_last_hidden`` reverse
either operation cleanly.

Return contract
---------------

* ``{"status": "closed", "panels": [id, ...], "count": N}`` — the batch
  hide succeeded. ``count`` is ``0`` when everything was already hidden.
* ``{"status": "restored", "panels": [id, ...], "count": N}`` — the
  most recent batch has been re-shown.
* ``{"status": "no_shell"}`` — no shell reachable via ctx.
* ``{"status": "empty_stack"}`` — restore called with nothing on the
  stack. Legal state on fresh editors.

The viewport panel (``"viewport_panel"``) is deliberately skipped in
``panel.close_all`` — it's always-visible in the shell (matches the
existing ``EditorShell.toggle_panel`` special case) so hiding it would
be silently ignored anyway.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


# Canonical panel ids. Kept in-sync with :data:`tool_router` panel
# toggle rows so ``close_all`` can operate without an introspection API.
_PANEL_IDS: tuple[str, ...] = (
    "outliner",
    "inspector",
    "content_browser",
    "code",
    "layer_panel",
    "behavior_panel",
    "tag_painter",
)

_SKIP_IDS: frozenset[str] = frozenset({"viewport_panel"})


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _panel_ids(ctx: dict[str, Any]) -> list[str]:
    """Return the panel-id list to operate on.

    ``ctx["panels"]`` overrides the default list — tests / shells with
    a bespoke panel set use this so we don't hard-code the roster.
    """
    override = ctx.get("panels")
    if isinstance(override, (list, tuple)) and override:
        return [str(p) for p in override if isinstance(p, str)]
    return list(_PANEL_IDS)


def _is_visible(shell: Any, panel_id: str) -> bool:
    """Best-effort check of *panel_id* current visibility on *shell*.

    Walks three surfaces in order:

    * ``shell._panel_windows[panel_id].is_visible()`` — MovablePanel API.
    * ``shell._panel_layout_state[panel_id].visible`` — persisted flag.
    * Defaults to ``True`` — the DPG editor's post-init state.
    """
    windows = getattr(shell, "_panel_windows", None)
    if isinstance(windows, dict):
        wrapper = windows.get(panel_id)
        if wrapper is not None:
            checker = getattr(wrapper, "is_visible", None)
            if callable(checker):
                try:
                    return bool(checker())
                except Exception:  # noqa: BLE001
                    pass
    state = getattr(shell, "_panel_layout_state", None)
    if isinstance(state, dict):
        entry = state.get(panel_id)
        if entry is not None:
            vis = getattr(entry, "visible", None)
            if vis is not None:
                try:
                    return bool(vis)
                except Exception:  # noqa: BLE001
                    pass
    return True


def _set_panel_visibility(shell: Any, panel_id: str, visible: bool) -> bool:
    """Apply *visible* to *panel_id*. Returns True on best-effort success.

    Route order:

    1. ``shell.set_panel_visible(id, visible)`` — canonical setter.
    2. ``shell.toggle_panel(id)`` — flip only when current != target.
    """
    setter = getattr(shell, "set_panel_visible", None)
    if callable(setter):
        try:
            setter(panel_id, visible)
            return True
        except Exception:  # noqa: BLE001
            pass
    toggler = getattr(shell, "toggle_panel", None)
    if callable(toggler):
        current = _is_visible(shell, panel_id)
        if current != visible:
            try:
                toggler(panel_id)
                return True
            except Exception:  # noqa: BLE001
                return False
        return True
    return False


def _push_stack(shell: Any, panels: list[str]) -> None:
    """Append *panels* to ``shell._hidden_panel_stack`` (create if missing)."""
    stack = getattr(shell, "_hidden_panel_stack", None)
    if not isinstance(stack, list):
        stack = []
        try:
            setattr(shell, "_hidden_panel_stack", stack)
        except Exception:  # noqa: BLE001
            return
    stack.append(list(panels))


def _pop_stack(shell: Any) -> list[str] | None:
    """Pop the most recent batch from the stack; return ``None`` when empty."""
    stack = getattr(shell, "_hidden_panel_stack", None)
    if not isinstance(stack, list) or not stack:
        return None
    return stack.pop()


def close_all_panels(ctx: dict[str, Any]) -> dict[str, Any]:
    """Hide every currently-visible panel; push the batch onto the stack.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (required): the editor shell owning the panels.
        * ``panels`` (optional list[str]): override the panel roster
          — tests use this to constrain the sweep to a subset.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("close_all_panels", ctx)
    shell = _get_shell(ctx)
    if shell is None:
        return {"status": "no_shell"}

    closed: list[str] = []
    for pid in _panel_ids(ctx):
        if pid in _SKIP_IDS:
            continue
        if not _is_visible(shell, pid):
            continue
        ok = _set_panel_visibility(shell, pid, False)
        if ok:
            closed.append(pid)

    if closed:
        _push_stack(shell, closed)

    return {"status": "closed", "panels": closed, "count": len(closed)}


def restore_last_hidden_panel(ctx: dict[str, Any]) -> dict[str, Any]:
    """Un-hide the most recently hidden panel batch.

    Pops the top of ``shell._hidden_panel_stack`` and calls
    ``shell.set_panel_visible(id, True)`` (or the toggle fallback) on
    every id in the batch.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (required): the editor shell.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("restore_last_hidden_panel", ctx)
    shell = _get_shell(ctx)
    if shell is None:
        return {"status": "no_shell"}

    batch = _pop_stack(shell)
    if batch is None:
        return {"status": "empty_stack"}

    restored: list[str] = []
    for pid in batch:
        ok = _set_panel_visibility(shell, pid, True)
        if ok:
            restored.append(pid)

    return {"status": "restored", "panels": restored, "count": len(restored)}


__all__ = [
    "close_all_panels",
    "restore_last_hidden_panel",
    "_PANEL_IDS",
]
