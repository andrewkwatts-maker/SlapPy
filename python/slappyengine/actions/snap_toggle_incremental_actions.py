"""Snap toggle-incremental action — flip incremental vs freeform snap mode.

Backs the ``snap.toggle_incremental``
:class:`~slappyengine.tool_router.ToolAction` row added by the RR1
STUB-triage sprint tick (round 19).

Distinct from ``tool.snap_to_grid`` (which toggles the *primary*
snap-to-grid behaviour) and OO1's ``snap.increase_grid_size`` /
``snap.decrease_grid_size`` (which step the grid resolution): the
incremental toggle picks between "snap by a fixed step" and "freeform"
gestures. Every DCC that ships numeric snapping exposes this as a
secondary toggle — Blender's ``Shift`` while dragging temporarily
switches into incremental mode, Unity's ``Ctrl`` while dragging locks
to the ProGrids increment, Maya's ``Modeling → Snap → Increment``.

The renderer / drag-tool consults ``shell._snap_incremental_mode``
before rounding drag deltas. This helper flips that flag and best-effort
fires ``shell._on_snap_toggle("_snap_incremental_mode", new_value)``.

Return contract
---------------

* ``{"status": "toggled", "target": "incremental", "enabled": bool,
   "previous": bool}`` — the flag was flipped.
* ``{"status": "no_shell"}`` — no shell in ``ctx`` and no explicit
  ``enabled`` seed.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_INCREMENTAL_ATTR = "_snap_incremental_mode"


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _read_flag(shell: Any, attr: str, default: bool = False) -> bool:
    if shell is None:
        return default
    val = getattr(shell, attr, default)
    try:
        return bool(val)
    except Exception:  # noqa: BLE001
        return default


def _write_flag(shell: Any, attr: str, value: bool) -> bool:
    if shell is None:
        return value
    try:
        setattr(shell, attr, value)
    except Exception:  # noqa: BLE001
        return value
    hook = getattr(shell, "_on_snap_toggle", None)
    if callable(hook):
        try:
            hook(attr, value)
        except Exception:  # noqa: BLE001
            pass
    return value


def toggle_incremental(ctx: dict[str, Any]) -> dict[str, Any]:
    """Flip the incremental-snap mode on/off.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell — reads
          ``shell._snap_incremental_mode`` and writes the flipped value.
        * ``enabled`` (optional bool): explicit seed for the *current*
          value (tests use this to run headless). Wins over the shell
          attribute when supplied.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("toggle_incremental", ctx)
    shell = _get_shell(ctx)
    override = ctx.get("enabled")
    if override is None and shell is None:
        return {"status": "no_shell"}
    if override is None:
        current = _read_flag(shell, _INCREMENTAL_ATTR, default=False)
    else:
        try:
            current = bool(override)
        except Exception:  # noqa: BLE001
            current = False
    new = not current
    _write_flag(shell, _INCREMENTAL_ATTR, new)
    return {
        "status": "toggled",
        "target": "incremental",
        "enabled": new,
        "previous": current,
    }


__all__ = ["toggle_incremental"]
