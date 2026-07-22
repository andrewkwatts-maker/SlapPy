"""View-snap action — jump the camera to a canonical axis-aligned view.

Backs the ``view.top_down_view`` :class:`~pharos_editor.tool_router.ToolAction`
row added by the KK7 STUB-triage sprint tick (round 13 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1 / FF1 / GG1 / II5 / JJ6).

Blender ``Numpad 7`` (top), ``Numpad 1`` (front), ``Numpad 3`` (side) —
every DCC ships a "snap to top-down orthographic" hotkey. This helper
writes the canonical yaw / pitch pair, flips the camera into
orthographic projection (``_cam_projection = "ortho"`` on cameras that
carry the slot), and retargets to the scene / selection centroid when
one is available. If nothing is selected the camera keeps its current
target but still snaps orientation — matches Blender behaviour when the
viewer taps Numpad-7 with no selection.

Camera contract
---------------

* ``camera._cam_yaw`` = ``0`` (radians).
* ``camera._cam_pitch`` = ``-π/2`` (radians, camera looking straight
  down — matches OpenGL Y-up right-hand convention).
* ``camera._cam_projection`` = ``"ortho"`` when the slot exists.
* ``camera._cam_target`` retargeted to centroid when a selection /
  entities override is provided.

Return contract
---------------

* ``{"status": "snapped", "view": "top_down",
   "yaw": 0.0, "pitch": -π/2, "projection": "ortho",
   "target": [x, y, z] | None, "path": ...}`` on success.
* ``{"status": "no_camera"}`` when no camera / viewport is reachable.
"""
from __future__ import annotations

import math
from typing import Any

from ._ctx import ensure_ctx


# Canonical "top down" pose — camera above +Z axis looking straight
# down at the XY plane.
_TOP_DOWN_YAW: float = 0.0
_TOP_DOWN_PITCH: float = -math.pi * 0.5


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


def _resolve_focus_points(ctx: dict[str, Any]) -> list[tuple[float, float, float]]:
    """Collect focus points from the selection / entities override.

    Returns an empty list when there's nothing to retarget on — the
    camera keeps its previous look-at target in that case.
    """
    override = ctx.get("selection")
    entities: list[Any] = []
    if override is not None:
        if isinstance(override, (list, tuple, set)):
            entities = [x for x in override if x is not None]
        else:
            entities = [override]
    else:
        entities_override = ctx.get("entities")
        if entities_override is not None:
            entities = [e for e in entities_override if e is not None]
        else:
            shell = _get_shell(ctx)
            if shell is not None:
                multi = getattr(shell, "_selected_entities", None)
                if isinstance(multi, (list, tuple, set)) and multi:
                    entities = [x for x in multi if x is not None]
                else:
                    single = getattr(shell, "_selected_entity", None)
                    if single is not None:
                        entities = [single]
    points: list[tuple[float, float, float]] = []
    for entity in entities:
        if isinstance(entity, dict):
            pos = entity.get("position")
            z_fallback = entity.get("z_height", 0.0)
        else:
            pos = getattr(entity, "position", None)
            z_fallback = getattr(entity, "z_height", 0.0)
        if pos is None:
            continue
        try:
            seq = tuple(pos)
        except TypeError:
            continue
        if len(seq) < 2:
            continue
        try:
            x = float(seq[0])
            y = float(seq[1])
        except (TypeError, ValueError):
            continue
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
        points.append((x, y, z))
    return points


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


def top_down_view(ctx: dict[str, Any]) -> dict[str, Any]:
    """Snap the viewport camera to a top-down orthographic pose.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``camera`` / ``shell`` — resolved as elsewhere.
        * ``selection`` / ``entities`` (optional): retarget hint. When
          present the camera's ``_cam_target`` is written to the
          centroid of the supplied points.
        * ``projection`` (optional str, default ``"ortho"``): the value
          written to ``camera._cam_projection`` when the slot exists.
          Pass ``"perspective"`` to keep the perspective projection.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("top_down_view", ctx)
    camera = _get_camera(ctx)
    if camera is None:
        return {"status": "no_camera"}

    try:
        setattr(camera, "_cam_yaw", _TOP_DOWN_YAW)
    except Exception:  # noqa: BLE001
        pass
    try:
        setattr(camera, "_cam_pitch", _TOP_DOWN_PITCH)
    except Exception:  # noqa: BLE001
        pass

    projection = ctx.get("projection", "ortho")
    projection_written: str | None = None
    if hasattr(camera, "_cam_projection"):
        try:
            setattr(camera, "_cam_projection", projection)
            projection_written = projection
        except Exception:  # noqa: BLE001
            projection_written = None

    points = _resolve_focus_points(ctx)
    target: list[float] | None = None
    if points:
        centroid = _centroid(points)
        if _write_target(camera, centroid):
            target = list(centroid)

    return {
        "status": "snapped",
        "view": "top_down",
        "yaw": _TOP_DOWN_YAW,
        "pitch": _TOP_DOWN_PITCH,
        "projection": projection_written,
        "target": target,
        "path": _path_for(ctx),
    }


__all__ = ["top_down_view"]
