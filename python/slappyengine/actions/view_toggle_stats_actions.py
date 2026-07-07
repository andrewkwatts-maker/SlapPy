"""Viewport stats-overlay toggle (FPS / entity count / draw-call HUD).

Backs the ``view.toggle_stats``
:class:`~slappyengine.tool_router.ToolAction` row added by the QQ1
STUB-triage sprint tick (round 18).

Every 3D DCC ships a "show framerate + tri count + draw-call overlay"
toggle: Unity's ``Stats`` button, Unreal's ``stat unit``, Blender's
``Overlays → Statistics``. Distinct from CC1's ``view.toggle_grid`` /
``view.toggle_gizmos`` (visual guide layers) and from
:mod:`view_toggle_wireframe_actions` (shading mode) — the stats overlay
sits on top of the rendered scene as text.

Distinct from ``editor.toggle_hud`` (the whole editor-chrome HUD): the
stats overlay is specifically the viewport perf-counter widget.

The renderer consults ``shell._stats_visible`` before drawing the perf
HUD. Helper flips that flag and best-effort fires
``shell._on_view_toggle("_stats_visible", new_value)`` so downstream
listeners can rebuild.

Return contract
---------------

* ``{"status": "toggled", "target": "stats", "visible": bool,
   "previous": bool}`` — the flag was flipped.
* ``{"status": "no_shell"}`` — no shell in ``ctx`` and no explicit
  ``visible`` seed.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_STATS_ATTR = "_stats_visible"


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


def toggle_stats(ctx: dict[str, Any]) -> dict[str, Any]:
    """Flip the viewport perf-stats overlay on/off.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell — reads
          ``shell._stats_visible`` and writes the flipped value.
        * ``visible`` (optional bool): explicit seed for the *current*
          value (tests use this to run headless). Wins over the shell
          attribute when supplied.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("toggle_stats", ctx)
    shell = _get_shell(ctx)
    override = ctx.get("visible")
    if override is None and shell is None:
        return {"status": "no_shell"}
    if override is None:
        current = _read_flag(shell, _STATS_ATTR, default=False)
    else:
        try:
            current = bool(override)
        except Exception:  # noqa: BLE001
            current = False
    new = not current
    _write_flag(shell, _STATS_ATTR, new)
    return {
        "status": "toggled",
        "target": "stats",
        "visible": new,
        "previous": current,
    }


__all__ = ["toggle_stats"]
