"""Viewport-overlay toggles — grid + gizmos.

Backs two :class:`~pharos_engine.tool_router.ToolAction` rows added by
the CC1 STUB-triage sprint tick (round 6):

* ``view.toggle_grid`` — flip the editor viewport's grid overlay.
* ``view.toggle_gizmos`` — flip every visible gizmo overlay.

Both actions treat the shell as the source of truth: they read the
current boolean, invert it, write it back onto the shell (so the DPG
draw callback observes the new state next tick), and best-effort call
any published notification hook (``shell.on_view_toggle`` etc.). When
no shell is reachable the actions still return the intended new state
so headless tests can assert on the toggle semantics.

Return contract
---------------

* ``{"status": "toggled", "target": "grid" | "gizmos", "visible": bool}``
  — the flag was flipped. ``visible`` reports the *new* value.
* ``{"status": "no_shell"}`` — no shell in ``ctx`` and no explicit
  initial value supplied via ``ctx["visible"]``. Tests can bypass this
  by passing a ``visible`` seed.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx

# Attribute the shell (or a headless stand-in) uses to track each flag.
_GRID_ATTR = "_grid_visible"
_GIZMOS_ATTR = "_gizmos_visible"


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _read_flag(shell: Any, attr: str, default: bool = True) -> bool:
    """Return ``getattr(shell, attr, default)`` coerced to bool.

    A shell that has never seen the toggle before returns *default*
    (grid + gizmos both default *on* — matches the DPG editor's
    initial-state).
    """
    if shell is None:
        return default
    val = getattr(shell, attr, default)
    try:
        return bool(val)
    except Exception:  # noqa: BLE001
        return default


def _write_flag(shell: Any, attr: str, value: bool) -> bool:
    """Write *value* onto *shell.attr*. Returns the effective value."""
    if shell is None:
        return value
    try:
        setattr(shell, attr, value)
    except Exception:  # noqa: BLE001
        return value
    # Fire the shell's overlay-refresh hook if it exposes one.
    hook = getattr(shell, "_on_view_toggle", None)
    if callable(hook):
        try:
            hook(attr, value)
        except Exception:  # noqa: BLE001
            pass
    return value


def toggle_grid(ctx: dict[str, Any]) -> dict[str, Any]:
    """Flip the viewport grid overlay on/off.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` — the editor shell. Read/write for ``_grid_visible``.
        * ``visible`` (optional bool): explicit initial value. When
          provided the toggle is applied to *this* value instead of
          probing the shell — lets tests exercise the flip in
          isolation.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("toggle_grid", ctx)
    shell = _get_shell(ctx)
    if shell is None and "visible" not in ctx:
        return {"status": "no_shell"}
    seed = ctx.get("visible")
    if isinstance(seed, bool):
        current = seed
    else:
        current = _read_flag(shell, _GRID_ATTR, default=True)
    new_val = not current
    effective = _write_flag(shell, _GRID_ATTR, new_val)
    return {
        "status": "toggled",
        "target": "grid",
        "visible": bool(effective),
        "previous": current,
    }


def toggle_gizmos(ctx: dict[str, Any]) -> dict[str, Any]:
    """Hide / show every gizmo overlay.

    Symmetric to :func:`toggle_grid`. Mirrors the shell attribute
    ``_gizmos_visible`` (plural — matches "gizmos" as a set of
    overlays: transform gizmo, selection marquee, IK bone lines, etc.).

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("toggle_gizmos", ctx)
    shell = _get_shell(ctx)
    if shell is None and "visible" not in ctx:
        return {"status": "no_shell"}
    seed = ctx.get("visible")
    if isinstance(seed, bool):
        current = seed
    else:
        current = _read_flag(shell, _GIZMOS_ATTR, default=True)
    new_val = not current
    effective = _write_flag(shell, _GIZMOS_ATTR, new_val)
    return {
        "status": "toggled",
        "target": "gizmos",
        "visible": bool(effective),
        "previous": current,
    }


__all__ = [
    "toggle_grid",
    "toggle_gizmos",
    "_GRID_ATTR",
    "_GIZMOS_ATTR",
]
