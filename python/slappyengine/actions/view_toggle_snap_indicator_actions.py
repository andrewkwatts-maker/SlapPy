"""View toggle-snap-indicator action — flip the snap-point overlay.

Backs the ``view.toggle_snap_indicator``
:class:`~slappyengine.tool_router.ToolAction` row added by the YY4
STUB-triage sprint tick (round 25 after WW4).

Distinct from the sibling overlay-toggle verbs:

* CC1's ``view.toggle_grid`` flips the *grid lines* overlay drawn
  across the viewport.
* CC1's ``view.toggle_gizmos`` hides / shows the transform gizmo
  set (per-object move / rotate / scale handles).
* QQ1's ``view.toggle_stats`` toggles the fps / tri counter HUD.
* PP1's ``view.toggle_wireframe`` flips the whole viewport render
  mode.
* VV4's ``view.toggle_ruler`` flips the horizontal + vertical
  measurement bar.
* WW4's ``view.toggle_axes`` flips the world-axis widget in the
  viewport corner.
* WW4's ``view.toggle_background`` flips the checker-transparency
  background fill.

The snap indicator is the small hint dot / crosshair that appears
next to the cursor when a snap target is under the cursor (Blender's
"Snap Element Indicator", Unity's snap-marker dot, Nova3D's
snap-hint chip). Distinct from ``tools.snap_to_grid`` (which toggles
snap *behaviour* on/off) — this verb only toggles the *visual*
feedback.

Storage contract
----------------

* Shell attribute: ``_snap_indicator_visible`` (canonical, matches
  the naming used by ``view_toggle_actions._GRID_ATTR`` /
  ``view_toggle_ruler_actions._RULER_ATTR`` /
  ``view_toggle_axes_actions._AXES_ATTR`` /
  ``view_toggle_background_actions._BG_ATTR``).
* Default when the attribute is absent: ``True`` — the snap
  indicator is shown by default (matches Blender / Unity
  factory-fresh state — snap feedback is the always-on sibling of
  snap behaviour).

Return contract
---------------

* ``{"status": "toggled", "target": "snap_indicator", "visible": bool,
   "previous": bool}`` — success.
* ``{"status": "no_shell"}`` — no shell reachable and no explicit
  ``ctx["visible"]`` seed to toggle against.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_SNAP_IND_ATTR = "_snap_indicator_visible"
_DEFAULT_VISIBLE = True


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _read_flag(shell: Any, default: bool) -> bool:
    if shell is None:
        return default
    val = getattr(shell, _SNAP_IND_ATTR, default)
    try:
        return bool(val)
    except Exception:  # noqa: BLE001
        return default


def _write_flag(shell: Any, value: bool) -> bool:
    if shell is None:
        return value
    try:
        setattr(shell, _SNAP_IND_ATTR, value)
    except Exception:  # noqa: BLE001
        return value
    hook = getattr(shell, "_on_view_toggle", None)
    if callable(hook):
        try:
            hook(_SNAP_IND_ATTR, value)
        except Exception:  # noqa: BLE001
            pass
    return value


def toggle_snap_indicator(ctx: dict[str, Any]) -> dict[str, Any]:
    """Hide / show the snap-point overlay hint marker.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell — read / write for
          ``_snap_indicator_visible``.
        * ``visible`` (optional bool): explicit initial value; the
          toggle is then applied to *this* rather than the shell
          attribute. Lets tests exercise the flip in isolation.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("toggle_snap_indicator", ctx)
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
        "target": "snap_indicator",
        "visible": bool(effective),
        "previous": current,
    }


__all__ = ["toggle_snap_indicator", "_SNAP_IND_ATTR"]
