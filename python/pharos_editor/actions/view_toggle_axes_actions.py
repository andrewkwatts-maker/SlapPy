"""View toggle-axes action — flip the viewport world-axis overlay.

Backs the ``view.toggle_axes``
:class:`~pharos_editor.tool_router.ToolAction` row added by the WW4
STUB-triage sprint tick (round 24 after VV4).

Distinct from the sibling overlay-toggle verbs:

* CC1's ``view.toggle_grid`` flips the grid overlay.
* CC1's ``view.toggle_gizmos`` hides / shows the *transform* gizmo set
  (per-object move / rotate / scale handles).
* QQ1's ``view.toggle_stats`` toggles the fps/tri counter HUD.
* PP1's ``view.toggle_wireframe`` flips the whole viewport render mode.
* VV4's ``view.toggle_ruler`` flips the horizontal + vertical measurement
  bar.

The world-axis overlay is the small 3-arrow XYZ widget rendered in the
viewport corner (Blender numpad ``N`` axis widget, Unity scene view
"Axes" toggle, Nova3D viewport corner mini-axes). Distinct from the
transform gizmo — this widget shows *world* orientation, not the
selected-entity local frame.

Storage contract
----------------

* Shell attribute: ``_axes_visible`` (canonical, matches the naming
  used by ``view_toggle_actions._GRID_ATTR`` /
  ``view_toggle_ruler_actions._RULER_ATTR``).
* Default when the attribute is absent: ``True`` — the axis widget
  is shown by default (matches Blender / Unity / Maya factory-fresh
  behaviour; the world-orientation cue is the always-visible sibling
  of the grid).

Return contract
---------------

* ``{"status": "toggled", "target": "axes", "visible": bool,
   "previous": bool}`` — success.
* ``{"status": "no_shell"}`` — no shell reachable and no explicit
  ``ctx["visible"]`` seed to toggle against.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_AXES_ATTR = "_axes_visible"
_DEFAULT_VISIBLE = True


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _read_flag(shell: Any, default: bool) -> bool:
    if shell is None:
        return default
    val = getattr(shell, _AXES_ATTR, default)
    try:
        return bool(val)
    except Exception:  # noqa: BLE001
        return default


def _write_flag(shell: Any, value: bool) -> bool:
    if shell is None:
        return value
    try:
        setattr(shell, _AXES_ATTR, value)
    except Exception:  # noqa: BLE001
        return value
    hook = getattr(shell, "_on_view_toggle", None)
    if callable(hook):
        try:
            hook(_AXES_ATTR, value)
        except Exception:  # noqa: BLE001
            pass
    return value


def toggle_axes(ctx: dict[str, Any]) -> dict[str, Any]:
    """Hide / show the viewport world-axis overlay.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell — read / write for
          ``_axes_visible``.
        * ``visible`` (optional bool): explicit initial value; the
          toggle is then applied to *this* rather than the shell
          attribute. Lets tests exercise the flip in isolation.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("toggle_axes", ctx)
    shell = _get_shell(ctx)
    if shell is None and "visible" not in ctx:
        return {"status": "no_shell"}
    seed = ctx.get("visible")
    if isinstance(seed, bool):
        current = seed
    else:
        current = _read_flag(shell, default=_DEFAULT_VISIBLE)
    new_val = not current
    effective = _write_flag(shell, new_val)
    return {
        "status": "toggled",
        "target": "axes",
        "visible": bool(effective),
        "previous": current,
    }


__all__ = ["toggle_axes", "_AXES_ATTR"]
