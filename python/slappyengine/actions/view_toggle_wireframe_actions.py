"""Viewport wireframe-overlay toggle.

Backs the ``view.toggle_wireframe``
:class:`~slappyengine.tool_router.ToolAction` row added by the PP1
STUB-triage sprint tick (round 17).

Every 3D DCC ships a "wireframe mode" hotkey (Blender ``Z → Wireframe``,
Maya ``4`` / ``5``, Unity's shading dropdown). In SlapPyEngine the
viewport renderer consults ``shell._wireframe_visible`` before drawing
each mesh; the helper flips that flag and returns the *new* state so
tests + toast strings can echo the change.

Behaviour mirrors the r6 :mod:`view_toggle_actions` — resolve the shell,
read the current boolean (defaults to ``False`` since wireframe overlay
is off by default), invert, write back, best-effort call
``shell._on_view_toggle`` for downstream refresh, and return the new
value.

Return contract
---------------

* ``{"status": "toggled", "target": "wireframe", "visible": bool}`` —
  the flag was flipped. ``visible`` reports the *new* value.
* ``{"status": "no_shell"}`` — no shell in ``ctx`` and no explicit
  initial value supplied via ``ctx["visible"]``. Tests can bypass this
  by passing a ``visible`` seed.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_WIREFRAME_ATTR = "_wireframe_visible"


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
    hook = getattr(shell, "_on_view_toggle", None)
    if callable(hook):
        try:
            hook(attr, value)
        except Exception:  # noqa: BLE001
            pass
    return value


def toggle_wireframe(ctx: dict[str, Any]) -> dict[str, Any]:
    """Flip the viewport wireframe overlay on/off.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell — reads
          ``shell._wireframe_visible`` and writes the flipped value.
        * ``visible`` (optional bool): explicit seed for the *current*
          value (tests use this to run headless). Wins over the shell
          attribute when supplied.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("toggle_wireframe", ctx)
    shell = _get_shell(ctx)
    override = ctx.get("visible")
    if override is None and shell is None:
        return {"status": "no_shell"}
    if override is None:
        current = _read_flag(shell, _WIREFRAME_ATTR, default=False)
    else:
        try:
            current = bool(override)
        except Exception:  # noqa: BLE001
            current = False
    new = not current
    _write_flag(shell, _WIREFRAME_ATTR, new)
    return {
        "status": "toggled",
        "target": "wireframe",
        "visible": new,
        "previous": current,
    }


__all__ = ["toggle_wireframe"]
