"""View toggle-background action — flip the viewport checker background.

Backs the ``view.toggle_background``
:class:`~pharos_editor.tool_router.ToolAction` row added by the WW4
STUB-triage sprint tick (round 24 after VV4).

Distinct from the sibling overlay-toggle verbs:

* CC1's ``view.toggle_grid`` flips the grid *lines* overlay drawn
  ON TOP of the viewport background — this verb owns the background
  fill pattern behind those lines.
* CC1's ``view.toggle_gizmos`` / QQ1's ``view.toggle_stats`` / PP1's
  ``view.toggle_wireframe`` / VV4's ``view.toggle_ruler`` all live
  above the background layer.

The background is the transparency-checkerboard / solid-fill layer
rendered behind the scene (Photoshop's checkerboard, Aseprite's
"Show Grid" for the transparency board, Blender image editor's
"Show Background" toggle). Toggling it off shows a solid theme-tinted
fill instead so the user can preview the scene against a plain
background before export.

Storage contract
----------------

* Shell attribute: ``_background_visible`` (canonical, matches the
  naming used by ``view_toggle_actions._GRID_ATTR`` /
  ``view_toggle_ruler_actions._RULER_ATTR`` /
  ``view_toggle_axes_actions._AXES_ATTR``).
* Default when the attribute is absent: ``True`` — the checker
  background is shown by default (matches Photoshop / Aseprite
  factory-fresh state — transparency indicator is the always-on
  sibling).

Return contract
---------------

* ``{"status": "toggled", "target": "background", "visible": bool,
   "previous": bool}`` — success.
* ``{"status": "no_shell"}`` — no shell reachable and no explicit
  ``ctx["visible"]`` seed to toggle against.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_BG_ATTR = "_background_visible"
_DEFAULT_VISIBLE = True


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _read_flag(shell: Any, default: bool) -> bool:
    if shell is None:
        return default
    val = getattr(shell, _BG_ATTR, default)
    try:
        return bool(val)
    except Exception:  # noqa: BLE001
        return default


def _write_flag(shell: Any, value: bool) -> bool:
    if shell is None:
        return value
    try:
        setattr(shell, _BG_ATTR, value)
    except Exception:  # noqa: BLE001
        return value
    hook = getattr(shell, "_on_view_toggle", None)
    if callable(hook):
        try:
            hook(_BG_ATTR, value)
        except Exception:  # noqa: BLE001
            pass
    return value


def toggle_background(ctx: dict[str, Any]) -> dict[str, Any]:
    """Hide / show the viewport checker background layer.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell — read / write for
          ``_background_visible``.
        * ``visible`` (optional bool): explicit initial value; the
          toggle is then applied to *this* rather than the shell
          attribute. Lets tests exercise the flip in isolation.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("toggle_background", ctx)
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
        "target": "background",
        "visible": bool(effective),
        "previous": current,
    }


__all__ = ["toggle_background", "_BG_ATTR"]
