"""View-orbit action — spin the camera around the selection centroid.

Backs the ``view.orbit_selection`` :class:`~pharos_engine.tool_router.ToolAction`
row added by the KK7 STUB-triage sprint tick (round 13 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1 / FF1 / GG1 / II5 / JJ6).

Blender ``Numpad 4/6/8/2``, Maya ``Alt+Left drag``, Unreal ``F`` +
orbit — every DCC ships a "spin the camera around what I'm looking at"
gesture. This helper rotates the viewport camera's yaw / pitch around
the selection centroid by ``ctx["yaw_deg"]`` / ``ctx["pitch_deg"]``
increments (default ``15°`` yaw / ``0°`` pitch — matches Blender's
Numpad-4 step).

Camera contract
---------------

Same three surfaces the other view actions recognise:

* ``ctx["camera"]`` — direct headless override (tests).
* ``ctx["shell"]._viewport_panel`` — canonical DPG viewport handle.
* ``ctx["shell"]._camera`` — legacy per-shell camera attribute.

Mutations:

* ``camera._cam_yaw`` (radians) — incremented / installed.
* ``camera._cam_pitch`` (radians) — incremented / installed and
  clamped to ``[-π/2 + ε, π/2 - ε]`` so the camera can't flip.
* ``camera._cam_target`` — retargeted to the selection centroid.
* ``camera._cam_distance`` — untouched (a follow-up ``view.frame_all``
  can re-fit the zoom).

Return contract
---------------

* ``{"status": "orbited", "yaw": rad, "pitch": rad,
   "yaw_deg": deg, "pitch_deg": deg, "target": [x, y, z], "count": N,
   "path": ...}`` on success.
* ``{"status": "no_camera"}`` when no camera is reachable.
* ``{"status": "no_selection"}`` when nothing is selected.
* ``{"status": "no_positions"}`` when the resolved selection has no
  position-carrying entries.
"""
from __future__ import annotations

import math
from typing import Any

from ._ctx import ensure_ctx


_DEFAULT_YAW_STEP_DEG: float = 15.0
_DEFAULT_PITCH_STEP_DEG: float = 0.0

# Keep the camera off the north / south poles so up-vector math stays
# well-defined. Matches Blender's Numpad-8 clamp behaviour.
_PITCH_EPSILON: float = math.radians(1.0)
_PITCH_MIN: float = -math.pi * 0.5 + _PITCH_EPSILON
_PITCH_MAX: float = math.pi * 0.5 - _PITCH_EPSILON


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _get_camera(ctx: dict[str, Any]) -> Any:
    """Resolve a camera-like object (mirrors camera_actions._get_camera)."""
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


def _resolve_selection(ctx: dict[str, Any]) -> list[Any]:
    override = ctx.get("selection")
    if override is not None:
        if isinstance(override, (list, tuple, set)):
            return [x for x in override if x is not None]
        return [override]
    shell = _get_shell(ctx)
    if shell is None:
        return []
    multi = getattr(shell, "_selected_entities", None)
    if isinstance(multi, (list, tuple, set)) and multi:
        return [x for x in multi if x is not None]
    single = getattr(shell, "_selected_entity", None)
    if single is not None:
        return [single]
    return []


def _entity_position(entity: Any) -> tuple[float, float, float] | None:
    if entity is None:
        return None
    if isinstance(entity, dict):
        pos = entity.get("position")
        z_fallback = entity.get("z_height", 0.0)
    else:
        pos = getattr(entity, "position", None)
        z_fallback = getattr(entity, "z_height", 0.0)
    if pos is None:
        return None
    try:
        seq = tuple(pos)
    except TypeError:
        return None
    if len(seq) < 2:
        return None
    try:
        x = float(seq[0])
        y = float(seq[1])
    except (TypeError, ValueError):
        return None
    if len(seq) >= 3:
        try:
            z = float(seq[2])
        except (TypeError, ValueError):
            z = 0.0
    else:
        try:
            z = float(z_fallback) if z_fallback is not None else 0.0
        except (TypeError, ValueError):
            z = 0.0
    return (x, y, z)


def _centroid(points: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    n = len(points)
    if n == 0:
        return (0.0, 0.0, 0.0)
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sz = sum(p[2] for p in points)
    return (sx / n, sy / n, sz / n)


def _write_target(camera: Any, target: tuple[float, float, float]) -> bool:
    existing = getattr(camera, "_cam_target", None)
    try:
        if isinstance(existing, list):
            existing[:] = list(target)
        else:
            setattr(camera, "_cam_target", list(target))
        return True
    except Exception:  # noqa: BLE001
        return False


def _read_float(camera: Any, attr: str) -> float:
    v = getattr(camera, attr, None)
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _resolve_step(ctx: dict[str, Any], key: str, default: float) -> float:
    raw = ctx.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _path_for(ctx: dict[str, Any]) -> str:
    if ctx.get("camera") is not None:
        return "camera"
    shell = ctx.get("shell")
    if shell is None:
        return "fallback"
    if getattr(shell, "_viewport_panel", None) is not None:
        return "shell"
    if getattr(shell, "_camera", None) is not None:
        return "shell"
    return "fallback"


def orbit_selection(ctx: dict[str, Any]) -> dict[str, Any]:
    """Orbit the viewport camera around the selection centroid.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``camera`` / ``shell`` — resolved as elsewhere.
        * ``selection`` (optional): explicit selection override.
        * ``yaw_deg`` (optional float, default ``15``): yaw increment.
          Positive spins camera counter-clockwise (right-hand rule on Y).
        * ``pitch_deg`` (optional float, default ``0``): pitch increment.
          Positive pitches the camera upward.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("orbit_selection", ctx)
    camera = _get_camera(ctx)
    if camera is None:
        return {"status": "no_camera"}

    selection = _resolve_selection(ctx)
    if not selection:
        return {"status": "no_selection"}

    points = [
        p for p in (_entity_position(e) for e in selection) if p is not None
    ]
    if not points:
        return {"status": "no_positions"}

    target = _centroid(points)
    _write_target(camera, target)

    yaw_step = math.radians(
        _resolve_step(ctx, "yaw_deg", _DEFAULT_YAW_STEP_DEG),
    )
    pitch_step = math.radians(
        _resolve_step(ctx, "pitch_deg", _DEFAULT_PITCH_STEP_DEG),
    )
    yaw = _read_float(camera, "_cam_yaw") + yaw_step
    pitch = _read_float(camera, "_cam_pitch") + pitch_step
    pitch = max(_PITCH_MIN, min(_PITCH_MAX, pitch))

    try:
        setattr(camera, "_cam_yaw", yaw)
    except Exception:  # noqa: BLE001
        pass
    try:
        setattr(camera, "_cam_pitch", pitch)
    except Exception:  # noqa: BLE001
        pass

    return {
        "status": "orbited",
        "yaw": yaw,
        "pitch": pitch,
        "yaw_deg": math.degrees(yaw),
        "pitch_deg": math.degrees(pitch),
        "target": list(target),
        "count": len(points),
        "path": _path_for(ctx),
    }


__all__ = ["orbit_selection"]
