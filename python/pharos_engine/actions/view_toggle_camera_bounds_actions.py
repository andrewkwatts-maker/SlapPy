"""View toggle-camera-bounds action — flip the camera-frame overlay.

Backs the ``view.toggle_camera_bounds``
:class:`~pharos_engine.tool_router.ToolAction` row added by the AAA4
STUB-triage sprint tick (round 27 after ZZ4).

Distinct from the sibling overlay-toggle verbs:

* CC1's ``view.toggle_grid`` flips the *grid lines* overlay.
* CC1's ``view.toggle_gizmos`` hides / shows the *transform* handles.
* QQ1's ``view.toggle_stats`` toggles the fps HUD.
* PP1's ``view.toggle_wireframe`` flips the whole viewport render
  mode.
* VV4's ``view.toggle_ruler`` flips the measurement bar.
* WW4's ``view.toggle_axes`` flips the world-axis corner widget.
* WW4's ``view.toggle_background`` flips the checker-transparency
  fill.
* YY4's ``view.toggle_snap_indicator`` flips the snap-hint dot.
* ZZ4's ``view.toggle_safe_area`` flips the 90 / 80 % safe-area
  outlines. That verb draws the *inner* action-safe / title-safe
  cinema outlines; this verb draws the *outer* camera-frame
  rectangle — the boundary of what the camera will actually render.
  Blender's Camera → Camera Passepartout / Unity's Camera Preview
  frame / Nova3D's viewport camera-frame outline.

Default state is **hidden** — the camera-frame outline is a
composition-time cue most authoring flows only enable when framing
cinematic shots.

Storage contract
----------------

* Shell attribute: ``_camera_bounds_visible`` (canonical, matches
  the naming used by the other view-overlay flags).
* Default when the attribute is absent: ``False``.

Return contract
---------------

* ``{"status": "toggled", "target": "camera_bounds",
   "visible": bool, "previous": bool}`` — success.
* ``{"status": "no_shell"}`` — no shell reachable and no explicit
  ``ctx["visible"]`` seed to toggle against.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_CAMERA_BOUNDS_ATTR = "_camera_bounds_visible"
_DEFAULT_VISIBLE = False


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _read_flag(shell: Any, default: bool) -> bool:
    if shell is None:
        return default
    val = getattr(shell, _CAMERA_BOUNDS_ATTR, default)
    try:
        return bool(val)
    except Exception:  # noqa: BLE001
        return default


def _write_flag(shell: Any, value: bool) -> bool:
    if shell is None:
        return value
    try:
        setattr(shell, _CAMERA_BOUNDS_ATTR, value)
    except Exception:  # noqa: BLE001
        return value
    hook = getattr(shell, "_on_view_toggle", None)
    if callable(hook):
        try:
            hook(_CAMERA_BOUNDS_ATTR, value)
        except Exception:  # noqa: BLE001
            pass
    return value


def toggle_camera_bounds(ctx: dict[str, Any]) -> dict[str, Any]:
    """Hide / show the camera-frame outline overlay.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell — read / write for
          ``_camera_bounds_visible``.
        * ``visible`` (optional bool): explicit initial value; the
          toggle is then applied to *this* rather than the shell
          attribute. Lets tests exercise the flip in isolation.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("toggle_camera_bounds", ctx)
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
        "target": "camera_bounds",
        "visible": bool(effective),
        "previous": current,
    }


__all__ = ["toggle_camera_bounds", "_CAMERA_BOUNDS_ATTR"]
