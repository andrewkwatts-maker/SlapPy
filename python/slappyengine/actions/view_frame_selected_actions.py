"""View-frame-selected action — pan AND zoom to fit the current selection.

Backs the ``view.frame_selected`` :class:`~slappyengine.tool_router.ToolAction`
row added by the NN2 STUB-triage sprint tick (round 15 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1 / FF1 / GG1 / II5 / JJ6 / KK7 /
MM6 [capture + render_toggle]).

Blender ``.`` (period on numpad, "Frame Selected"), Maya ``F``, Unreal ``F``,
Unity ``F`` — every DCC ships this "zoom to what I have selected" gesture.
Distinct from the already-wired :func:`slappyengine.actions.viewport_framing_actions.center_on_selection`
(which only *pans* without changing zoom) and :func:`frame_all` (which
targets the *entire scene*, not the current selection).

Camera contract
---------------

Same three surfaces the other view actions recognise:

* ``ctx["camera"]`` — direct headless override (tests).
* ``ctx["shell"]._viewport_panel`` — canonical DPG viewport handle.
* ``ctx["shell"]._camera`` — legacy per-shell camera attribute.

Selection resolution:

* ``ctx["selection"]`` — explicit override (list / tuple / single entity).
* ``ctx["shell"]._selected_entities`` — multi-select shell slot.
* ``ctx["shell"]._selected_entity`` — legacy single-select slot.

Mutations:

* ``camera._cam_target`` (list of 3 floats) — retargeted to selection
  centroid.
* ``camera._cam_distance`` (float) — re-computed from selection AABB
  bounding-sphere radius, clamped, multiplicatively margined via
  ``ctx["margin"]`` (default ``1.15``).
* Falls back to ``_pan_x`` / ``_pan_y`` + ``_zoom_level`` for 2D
  cameras — matches ``viewport_framing_actions`` conventions.

Return contract
---------------

* ``{"status": "framed", "target": [x, y, z], "distance": float,
   "radius": float, "count": N, "path": ...}`` — success.
* ``{"status": "no_camera"}`` — no camera / viewport is reachable.
* ``{"status": "no_selection"}`` — the shell reports an empty
  selection (distinct from ``no_positions`` so a status-bar hint can
  distinguish "nothing selected" from "selection has no positional
  entities").
* ``{"status": "no_positions"}`` — selection had entries but none of
  them carry a position slot.
"""
from __future__ import annotations

import math
from typing import Any

from ._ctx import ensure_ctx


# Match viewport_framing_actions clamps so a subsequent frame_all doesn't
# drop into a different range.
_FRAME_MARGIN: float = 1.15
_MIN_FRAME_DISTANCE: float = 5.0
_MIN_DISTANCE: float = 0.05
_MAX_DISTANCE: float = 10000.0
_MIN_ZOOM_LEVEL: float = 0.01
_MAX_ZOOM_LEVEL: float = 100.0


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


def _aabb(points: list[tuple[float, float, float]]) -> tuple[
    tuple[float, float, float], tuple[float, float, float]
]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return (
        (min(xs), min(ys), min(zs)),
        (max(xs), max(ys), max(zs)),
    )


def _resolve_margin(ctx: dict[str, Any]) -> float:
    raw = ctx.get("margin")
    if raw is None:
        return _FRAME_MARGIN
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return _FRAME_MARGIN
    if val <= 0.0:
        return _FRAME_MARGIN
    return val


def _write_cam_target(
    camera: Any, target: tuple[float, float, float],
) -> bool:
    if camera is None:
        return False
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
    # 2D fallback.
    if hasattr(camera, "_pan_x") or hasattr(camera, "_pan_y"):
        try:
            setattr(camera, "_pan_x", float(target[0]))
            setattr(camera, "_pan_y", float(target[1]))
            return True
        except Exception:  # noqa: BLE001
            return False
    return False


def _write_cam_distance(camera: Any, distance: float) -> float:
    if camera is None:
        return distance
    clamped = max(_MIN_DISTANCE, min(_MAX_DISTANCE, distance))
    if hasattr(camera, "_cam_distance"):
        try:
            setattr(camera, "_cam_distance", clamped)
            return clamped
        except Exception:  # noqa: BLE001
            return distance
    if hasattr(camera, "_zoom_level"):
        try:
            zoom = 1.0 / max(clamped, 0.01)
            zoom = max(_MIN_ZOOM_LEVEL, min(_MAX_ZOOM_LEVEL, zoom))
            setattr(camera, "_zoom_level", zoom)
            return zoom
        except Exception:  # noqa: BLE001
            return distance
    return distance


def _path_for(ctx: dict[str, Any]) -> str:
    if ctx.get("camera") is not None:
        return "camera"
    shell = ctx.get("shell")
    if shell is not None and getattr(shell, "_viewport_panel", None) is not None:
        return "shell"
    if shell is not None and getattr(shell, "_camera", None) is not None:
        return "shell"
    return "fallback"


def frame_selected(ctx: dict[str, Any]) -> dict[str, Any]:
    """Pan and zoom the viewport camera to tightly fit the current selection.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``camera`` / ``shell`` — resolved as elsewhere.
        * ``selection`` (optional): explicit selection override.
        * ``margin`` (optional float, default ``1.15``): multiplicative
          headroom around the selection's bounding sphere.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("frame_selected", ctx)
    camera = _get_camera(ctx)
    if camera is None:
        return {"status": "no_camera"}

    entities = _resolve_selection(ctx)
    if not entities:
        return {"status": "no_selection"}

    points = [
        p for p in (_entity_position(e) for e in entities) if p is not None
    ]
    if not points:
        return {"status": "no_positions"}

    (minx, miny, minz), (maxx, maxy, maxz) = _aabb(points)
    centroid = (
        0.5 * (minx + maxx),
        0.5 * (miny + maxy),
        0.5 * (minz + maxz),
    )
    dx = maxx - minx
    dy = maxy - miny
    dz = maxz - minz
    radius = 0.5 * math.sqrt(dx * dx + dy * dy + dz * dz)
    margin = _resolve_margin(ctx)
    if radius <= 0.0:
        distance = _MIN_FRAME_DISTANCE
    else:
        distance = max(radius * 2.0 * margin, _MIN_FRAME_DISTANCE)

    ok_target = _write_cam_target(camera, centroid)
    written = _write_cam_distance(camera, distance)
    if not ok_target and written == distance:
        return {"status": "error", "message": "camera has no target/distance"}

    return {
        "status": "framed",
        "target": list(centroid),
        "distance": written,
        "radius": radius,
        "count": len(points),
        "margin": margin,
        "path": _path_for(ctx),
    }


__all__ = ["frame_selected"]
