"""View-reset action — restore camera orientation, target, and distance to home.

Backs the ``view.reset_view`` :class:`~pharos_editor.tool_router.ToolAction`
row added by the NN2 STUB-triage sprint tick (round 15).

Blender ``Home``, Maya ``A`` (frame all when nothing selected), Unreal
``End`` — every DCC ships a "put the camera back where it started" gesture.
Distinct from :func:`pharos_editor.actions.camera_actions.zoom_reset`
(which only touches the zoom knob) and
:func:`pharos_editor.actions.viewport_framing_actions.frame_all` (which
targets the current *scene*, not a canonical home pose).

Camera contract
---------------

Same three surfaces the other view actions recognise:

* ``ctx["camera"]`` — direct headless override.
* ``ctx["shell"]._viewport_panel`` — canonical DPG viewport handle.
* ``ctx["shell"]._camera`` — legacy per-shell camera attribute.

Mutations (each applied only when the slot exists on the camera):

* ``camera._cam_target`` = ``[0.0, 0.0, 0.0]`` (or ``ctx["target"]``).
* ``camera._cam_distance`` = ``5.0`` (or ``ctx["distance"]``).
* ``camera._cam_yaw`` = ``0.0``.
* ``camera._cam_pitch`` = ``0.0``.
* ``camera._cam_projection`` = ``"perspective"`` (or ``ctx["projection"]``).
* ``camera._zoom_level`` = ``1.0`` for 2D shells that expose the slot.
* ``camera._pan_x`` / ``_pan_y`` = ``0.0`` for 2D shells.

Return contract
---------------

* ``{"status": "reset", "target": [x, y, z], "distance": float,
   "yaw": float, "pitch": float, "projection": str | None,
   "path": ...}`` — success.
* ``{"status": "no_camera"}`` — no camera / viewport is reachable.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_DEFAULT_TARGET: tuple[float, float, float] = (0.0, 0.0, 0.0)
_DEFAULT_DISTANCE: float = 5.0
_DEFAULT_YAW: float = 0.0
_DEFAULT_PITCH: float = 0.0
_DEFAULT_PROJECTION: str = "perspective"
_DEFAULT_ZOOM_LEVEL: float = 1.0

_MIN_DISTANCE: float = 0.05
_MAX_DISTANCE: float = 10000.0


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _get_camera(ctx: dict[str, Any]) -> Any:
    override = ctx.get("camera")
    if override is not None:
        return override
    shell = _get_shell(ctx)
    if shell is None:
        return None
    panel = getattr(shell, "_viewport_panel", None)
    if panel is not None:
        return panel
    return getattr(shell, "_camera", None)


def _resolve_target(ctx: dict[str, Any]) -> tuple[float, float, float]:
    raw = ctx.get("target")
    if raw is None:
        return _DEFAULT_TARGET
    try:
        seq = tuple(raw)
    except TypeError:
        return _DEFAULT_TARGET
    if len(seq) < 2:
        return _DEFAULT_TARGET
    try:
        x = float(seq[0])
        y = float(seq[1])
    except (TypeError, ValueError):
        return _DEFAULT_TARGET
    if len(seq) >= 3:
        try:
            z = float(seq[2])
        except (TypeError, ValueError):
            z = 0.0
    else:
        z = 0.0
    return (x, y, z)


def _resolve_distance(ctx: dict[str, Any]) -> float:
    raw = ctx.get("distance")
    if raw is None:
        return _DEFAULT_DISTANCE
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_DISTANCE
    return max(_MIN_DISTANCE, min(_MAX_DISTANCE, val))


def _write_target(camera: Any, target: tuple[float, float, float]) -> bool:
    existing = getattr(camera, "_cam_target", None)
    if existing is not None:
        try:
            if isinstance(existing, list):
                existing[:] = list(target)
            else:
                setattr(camera, "_cam_target", list(target))
            return True
        except Exception:  # noqa: BLE001
            return False
    return False


def _try_setattr(camera: Any, attr: str, value: Any) -> bool:
    """Write *value* to ``camera.attr`` iff the slot already exists."""
    if not hasattr(camera, attr):
        return False
    try:
        setattr(camera, attr, value)
        return True
    except Exception:  # noqa: BLE001
        return False


def _path_for(ctx: dict[str, Any]) -> str:
    if ctx.get("camera") is not None:
        return "camera"
    shell = ctx.get("shell")
    if shell is not None and getattr(shell, "_viewport_panel", None) is not None:
        return "shell"
    if shell is not None and getattr(shell, "_camera", None) is not None:
        return "shell"
    return "fallback"


def reset_view(ctx: dict[str, Any]) -> dict[str, Any]:
    """Restore the viewport camera to a canonical home pose.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``camera`` / ``shell`` — resolved as elsewhere.
        * ``target`` (optional): replacement look-at point (defaults to
          ``(0, 0, 0)``). Accepts a 2- or 3-tuple.
        * ``distance`` (optional float, default ``5.0``): camera
          distance / zoom knob. Clamped against the safety range.
        * ``projection`` (optional str, default ``"perspective"``):
          written to ``_cam_projection`` when the slot exists.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("reset_view", ctx)
    camera = _get_camera(ctx)
    if camera is None:
        return {"status": "no_camera"}

    target = _resolve_target(ctx)
    distance = _resolve_distance(ctx)
    projection = ctx.get("projection", _DEFAULT_PROJECTION)

    _write_target(camera, target)
    _try_setattr(camera, "_cam_distance", distance)
    _try_setattr(camera, "_cam_yaw", _DEFAULT_YAW)
    _try_setattr(camera, "_cam_pitch", _DEFAULT_PITCH)
    projection_written: str | None = None
    if _try_setattr(camera, "_cam_projection", projection):
        projection_written = projection
    # 2D fallback slots — write only when the camera exposes them.
    _try_setattr(camera, "_zoom_level", _DEFAULT_ZOOM_LEVEL)
    _try_setattr(camera, "_pan_x", 0.0)
    _try_setattr(camera, "_pan_y", 0.0)

    return {
        "status": "reset",
        "target": list(target),
        "distance": distance,
        "yaw": _DEFAULT_YAW,
        "pitch": _DEFAULT_PITCH,
        "projection": projection_written,
        "path": _path_for(ctx),
    }


__all__ = ["reset_view"]
