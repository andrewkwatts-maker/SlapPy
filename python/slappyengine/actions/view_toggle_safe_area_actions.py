"""View toggle-safe-area action — flip the safe-area guide overlay.

Backs the ``view.toggle_safe_area``
:class:`~slappyengine.tool_router.ToolAction` row added by the ZZ4
STUB-triage sprint tick (round 26 after YY4).

Distinct from the sibling overlay-toggle verbs:

* CC1's ``view.toggle_grid`` flips the *grid lines* overlay drawn
  across the viewport.
* CC1's ``view.toggle_gizmos`` hides / shows the *transform* gizmo set
  (per-object move / rotate / scale handles).
* QQ1's ``view.toggle_stats`` toggles the fps / tri counter HUD.
* PP1's ``view.toggle_wireframe`` flips the whole viewport render
  mode.
* VV4's ``view.toggle_ruler`` flips the horizontal + vertical
  measurement bar.
* WW4's ``view.toggle_axes`` flips the world-axis widget in the
  viewport corner.
* WW4's ``view.toggle_background`` flips the checker-transparency
  background fill.
* YY4's ``view.toggle_snap_indicator`` flips the snap-point hint dot.

The safe-area overlay is the 90% action-safe + 80% title-safe outline
drawn on top of the camera-viewport frame — Blender's Camera →
Viewport Display → Safe Areas, Unity's Camera Preview safe-area gizmo,
Nova3D's viewport corner safe-area lines. Distinct from
``view.toggle_axes`` (world orientation cue) — the safe-area cue lives
in *screen space*, framing composition rather than the world.

Default state is **hidden** — matching Blender / Unity / Maya
factory-fresh; safe-area is a video-composition tool that most
authoring flows only turn on when authoring cinematic captures.

Storage contract
----------------

* Shell attribute: ``_safe_area_visible`` (canonical, matches the
  naming used by other view-overlay flags).
* Default when the attribute is absent: ``False`` — the safe-area
  outline is hidden by default.

Return contract
---------------

* ``{"status": "toggled", "target": "safe_area", "visible": bool,
   "previous": bool}`` — success.
* ``{"status": "no_shell"}`` — no shell reachable and no explicit
  ``ctx["visible"]`` seed to toggle against.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_SAFE_AREA_ATTR = "_safe_area_visible"
_DEFAULT_VISIBLE = False


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _read_flag(shell: Any, default: bool) -> bool:
    if shell is None:
        return default
    val = getattr(shell, _SAFE_AREA_ATTR, default)
    try:
        return bool(val)
    except Exception:  # noqa: BLE001
        return default


def _write_flag(shell: Any, value: bool) -> bool:
    if shell is None:
        return value
    try:
        setattr(shell, _SAFE_AREA_ATTR, value)
    except Exception:  # noqa: BLE001
        return value
    hook = getattr(shell, "_on_view_toggle", None)
    if callable(hook):
        try:
            hook(_SAFE_AREA_ATTR, value)
        except Exception:  # noqa: BLE001
            pass
    return value


def toggle_safe_area(ctx: dict[str, Any]) -> dict[str, Any]:
    """Hide / show the safe-area (action-safe + title-safe) overlay.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell — read / write for
          ``_safe_area_visible``.
        * ``visible`` (optional bool): explicit initial value; the
          toggle is then applied to *this* rather than the shell
          attribute. Lets tests exercise the flip in isolation.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("toggle_safe_area", ctx)
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
        "target": "safe_area",
        "visible": bool(effective),
        "previous": current,
    }


__all__ = ["toggle_safe_area", "_SAFE_AREA_ATTR"]
