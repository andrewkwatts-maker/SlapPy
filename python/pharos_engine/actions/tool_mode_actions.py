"""Tool-mode actions — activate the pan / navigation tool.

Backs the ``tool.pan`` action id added by the AA1 STUB-triage sprint
tick (round 4). Complements the existing ``editor.tool_select`` /
``editor.tool_move`` / ``editor.tool_rotate`` / ``editor.tool_scale``
router entries which target the four :class:`NotebookToolbar` sticker
buttons.

``pan`` is intentionally *not* one of the four sticker-button tools —
the notebook toolbar's ``set_active`` rejects unknown ids (see
``notebook_toolbar.py::set_active`` valid-set gate). So this action only
mutates the shell's ``_active_tool`` slot + broadcasts to the status
bar's active-tool readout when available. The middle-mouse drag handler
and space-bar pan-shortcut both check ``shell._active_tool == "pan"``
to decide whether to translate ``_cam_target`` on left-drag.

Design provenance
-----------------

* ``docs/engine_feature_map_2026_07_04.md`` §"Top 10 Broken/Stub Fixes"
  suggested ``tool.pan`` as one of the round-4 STUB targets.
* ``python/pharos_engine/tool_router.py::_fb_set_tool`` — the sibling
  helper this module deliberately does **not** call (that helper also
  pokes the toolbar, which would reject ``"pan"``).

Return contract
---------------

* ``{"status": "activated", "tool": "pan", "path": "shell"}`` on the
  happy path (shell present, ``_active_tool`` mutated).
* ``{"status": "activated", "tool": "pan", "path": "fallback"}`` when
  running headless — the action still returns a valid confirmation dict
  so callers can toast "Pan tool active" without special-casing.
* ``{"status": "error", "message": str}`` when writing to
  ``shell._active_tool`` blew up.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


# The tool id used across the shell, status bar, and viewport drag
# handler. Exposed as a module-level constant so tests and downstream
# panels can import a canonical name rather than hard-code the string.
PAN_TOOL_ID: str = "pan"


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _notify_status_bar(shell: Any, tool_id: str) -> None:
    """Best-effort — mirror the tool id on the notebook status bar."""
    if shell is None:
        return
    status_bar = getattr(shell, "_notebook_status_bar", None)
    if status_bar is None:
        return
    setter = getattr(status_bar, "set_active_tool", None)
    if callable(setter):
        try:
            setter(tool_id)
        except Exception:  # noqa: BLE001
            pass


def _notify_engine(shell: Any, tool_id: str) -> None:
    """Best-effort — poke ``engine.set_active_tool`` when present."""
    if shell is None:
        return
    engine = getattr(shell, "_engine", None)
    if engine is None:
        return
    setter = getattr(engine, "set_active_tool", None)
    if callable(setter):
        try:
            setter(tool_id)
        except Exception:  # noqa: BLE001
            pass


def activate_pan_tool(ctx: dict[str, Any]) -> dict[str, Any]:
    """Set the shell's active tool to ``"pan"``.

    Deliberately bypasses the :class:`NotebookToolbar` sticker-button
    ``set_active`` check because ``pan`` is not one of the four
    modal-transform tools (Select / Move / Rotate / Scale). The status-
    bar readout is still updated so the user gets visible feedback.

    When ``ctx["shell"]`` is absent (headless test / notebook-mode
    caller) the action returns a fallback-path confirmation dict — the
    action still round-trips a boolean success so the router remains
    testable.

    Parameters (via ``ctx``)
    ------------------------
    * ``shell`` — :class:`EditorShell` handle. Optional.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("activate_pan_tool", ctx)
    shell = _get_shell(ctx)
    if shell is None:
        return {
            "status": "activated",
            "tool": PAN_TOOL_ID,
            "path": "fallback",
        }

    try:
        setattr(shell, "_active_tool", PAN_TOOL_ID)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    _notify_status_bar(shell, PAN_TOOL_ID)
    _notify_engine(shell, PAN_TOOL_ID)
    return {
        "status": "activated",
        "tool": PAN_TOOL_ID,
        "path": "shell",
    }


__all__ = [
    "PAN_TOOL_ID",
    "activate_pan_tool",
]
