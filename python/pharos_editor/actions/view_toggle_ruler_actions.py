"""View toggle-ruler action — flip the viewport ruler overlay.

Backs the ``view.toggle_ruler``
:class:`~pharos_editor.tool_router.ToolAction` row added by the VV4
STUB-triage sprint tick (round 23 after UU4).

Distinct from the sibling overlay-toggle verbs:

* CC1's ``view.toggle_grid`` flips the grid overlay.
* CC1's ``view.toggle_gizmos`` hides / shows the transform gizmo set.
* QQ1's ``view.toggle_stats`` toggles the fps/tri counter HUD.
* PP1's ``view.toggle_wireframe`` flips the whole viewport render mode.

The ruler is the horizontal + vertical measurement bar that ships in
every 2D DCC — Photoshop ``Ctrl+R``, Illustrator ``Ctrl+R``, Krita
``Ctrl+R``, Affinity Photo ``Ctrl+R``. Nova3D's viewport panel
already reserves the top-left corner for the ruler; this verb owns
its visibility gate.

Storage contract
----------------

* Shell attribute: ``_ruler_visible`` (canonical, matches the naming
  used by ``view_toggle_actions._GRID_ATTR`` / ``_GIZMOS_ATTR``).
* Default when the attribute is absent: ``False`` — the ruler is
  hidden by default (matches Photoshop's factory-fresh state; users
  toggle it on demand).

Return contract
---------------

* ``{"status": "toggled", "target": "ruler", "visible": bool,
   "previous": bool}`` — success.
* ``{"status": "no_shell"}`` — no shell reachable and no explicit
  ``ctx["visible"]`` seed to toggle against.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_RULER_ATTR = "_ruler_visible"
_DEFAULT_VISIBLE = False


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _read_flag(shell: Any, default: bool) -> bool:
    if shell is None:
        return default
    val = getattr(shell, _RULER_ATTR, default)
    try:
        return bool(val)
    except Exception:  # noqa: BLE001
        return default


def _write_flag(shell: Any, value: bool) -> bool:
    if shell is None:
        return value
    try:
        setattr(shell, _RULER_ATTR, value)
    except Exception:  # noqa: BLE001
        return value
    hook = getattr(shell, "_on_view_toggle", None)
    if callable(hook):
        try:
            hook(_RULER_ATTR, value)
        except Exception:  # noqa: BLE001
            pass
    return value


def toggle_ruler(ctx: dict[str, Any]) -> dict[str, Any]:
    """Hide / show the viewport ruler overlay.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell — read / write for
          ``_ruler_visible``.
        * ``visible`` (optional bool): explicit initial value; the
          toggle is then applied to *this* rather than the shell
          attribute. Lets tests exercise the flip in isolation.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("toggle_ruler", ctx)
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
        "target": "ruler",
        "visible": bool(effective),
        "previous": current,
    }


__all__ = ["toggle_ruler", "_RULER_ATTR"]
