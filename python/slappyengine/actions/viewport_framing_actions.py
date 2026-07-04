"""Viewport-framing actions — center-on-selection / frame-all.

Backs two action ids added by the AA1 STUB-triage sprint tick (round 4):

* ``view.center_on_selection`` — pan the viewport camera so its look-at
  target sits at the centroid of the currently-selected entities' AABB.
  When no selection is present the action returns
  ``{"status": "no_selection"}`` so the shell can flash a status hint.
* ``view.frame_all`` — pan **and** zoom the camera so the AABB of every
  entity in the scene fits inside the view. Distance is picked from the
  bounding-sphere radius with a small margin so a single-entity scene
  doesn't collapse the camera into the entity.

Both helpers target the same camera surfaces
:mod:`slappyengine.actions.camera_actions` recognises:

* ``ctx["camera"]`` — direct override (tests pass this).
* ``ctx["shell"]._viewport_panel`` — canonical viewport handle.
* ``ctx["shell"]._camera`` — legacy per-shell camera attribute.

For 3D cameras the actions write ``_cam_target`` (list[3] of floats) and
``_cam_distance`` (float). For 2D shells that only expose ``_pan_x`` /
``_pan_y`` the pan writes those fields — a ``_zoom_level`` override is
touched only when the frame-fit distance is explicitly requested.

Return contract
---------------

* ``{"status": "centered", "target": [x, y, z], "path": ...}``
* ``{"status": "framed", "target": [...], "distance": float, "path": ...}``
* ``{"status": "no_camera"}``  — no camera / viewport panel reachable.
* ``{"status": "no_selection"}`` — for ``center_on_selection`` only.
* ``{"status": "empty_scene"}`` — ``frame_all`` when the scene has 0
  entities.
"""
from __future__ import annotations

import math
from typing import Any


# Same margin ratio used by many DCCs — "frame all" leaves ~15% headroom
# around the bounding sphere so labels don't clip against the viewport
# edge.
_FRAME_MARGIN: float = 1.15

# When a scene contains only a single point-like entity the AABB radius
# collapses to zero. Fall back to this default distance so the camera
# doesn't zoom straight into the entity.
_MIN_FRAME_DISTANCE: float = 5.0

# Match camera_actions' safety clamps.
_MIN_DISTANCE: float = 0.05
_MAX_DISTANCE: float = 10000.0


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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


def _get_scene(ctx: dict[str, Any]) -> Any:
    """Resolve a Scene handle from *ctx*."""
    scene = ctx.get("scene")
    if scene is not None:
        return scene
    shell = _get_shell(ctx)
    if shell is None:
        return None
    engine = getattr(shell, "_engine", None)
    if engine is not None:
        scene = getattr(engine, "scene", None) or getattr(engine, "_scene", None)
        if scene is not None:
            return scene
    return getattr(shell, "_scene", None)


def _list_scene_entities(scene: Any) -> list[Any]:
    """Return every entity in *scene* (mirrors selection_actions helper)."""
    if scene is None:
        return []
    entities_attr = getattr(scene, "entities", None)
    if entities_attr is None:
        raw = getattr(scene, "_entities", None)
        if isinstance(raw, dict):
            return list(raw.values())
        if isinstance(raw, (list, tuple)):
            return list(raw)
        return []
    if callable(entities_attr):
        try:
            got = entities_attr()
        except Exception:  # noqa: BLE001
            return []
        return list(got) if got is not None else []
    try:
        return list(entities_attr)
    except TypeError:
        return []


def _resolve_selection(ctx: dict[str, Any]) -> list[Any]:
    """Return the entities backing the current selection as a list."""
    override = ctx.get("selection")
    if override is not None:
        if isinstance(override, (list, tuple)):
            return [x for x in override if x is not None]
        return [override]
    shell = _get_shell(ctx)
    if shell is None:
        return []
    multi = getattr(shell, "_selected_entities", None)
    if isinstance(multi, (list, tuple)) and multi:
        return [x for x in multi if x is not None]
    single = getattr(shell, "_selected_entity", None)
    if single is not None:
        return [single]
    return []


def _entity_position(entity: Any) -> tuple[float, float, float] | None:
    """Return ``(x, y, z)`` for *entity* (or ``None`` when unavailable).

    Handles three shapes:

    * :class:`slappyengine.entity.Entity` — 2D ``position`` tuple +
      optional ``z_height`` scalar.
    * Duck-typed 3D objects with ``position`` iterable of length ≥ 2.
    * Bare dicts with ``position`` / ``z_height`` keys.
    """
    if entity is None:
        return None
    if isinstance(entity, dict):
        pos = entity.get("position")
        z = entity.get("z_height", 0.0)
    else:
        pos = getattr(entity, "position", None)
        z = getattr(entity, "z_height", 0.0)
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
            zf = float(seq[2])
        except (TypeError, ValueError):
            zf = 0.0
    else:
        try:
            zf = float(z) if z is not None else 0.0
        except (TypeError, ValueError):
            zf = 0.0
    return (x, y, zf)


def _aabb(points: list[tuple[float, float, float]]) -> tuple[
    tuple[float, float, float], tuple[float, float, float]
]:
    """Return ``(mins, maxs)`` for the AABB spanning *points*."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return (
        (min(xs), min(ys), min(zs)),
        (max(xs), max(ys), max(zs)),
    )


def _centroid(points: list[tuple[float, float, float]]) -> tuple[
    float, float, float
]:
    """Return the mean of *points* — used as camera look-at target."""
    n = len(points)
    if n == 0:
        return (0.0, 0.0, 0.0)
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sz = sum(p[2] for p in points)
    return (sx / n, sy / n, sz / n)


def _write_cam_target(
    camera: Any, target: tuple[float, float, float],
) -> bool:
    """Write *target* to ``camera._cam_target`` (or ``_pan_*`` for 2D).

    Returns ``True`` when at least one attribute was updated.
    """
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
    # 2D fallback — write ``_pan_x`` / ``_pan_y`` if present.
    if hasattr(camera, "_pan_x") or hasattr(camera, "_pan_y"):
        try:
            setattr(camera, "_pan_x", float(target[0]))
            setattr(camera, "_pan_y", float(target[1]))
            return True
        except Exception:  # noqa: BLE001
            return False
    return False


def _write_cam_distance(camera: Any, distance: float) -> float:
    """Clamp *distance* into [_MIN_DISTANCE, _MAX_DISTANCE] and write it back.

    Falls back to ``_zoom_level`` for 2D cameras. Returns the actual
    (clamped) value written or the original when nothing changed.
    """
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
        # 2D shells: a larger AABB means the zoom_level shrinks
        # (things look smaller). Map distance → 1 / distance so the
        # frame-all invariant "bigger world → wider view" still holds.
        try:
            zoom = 1.0 / max(clamped, 0.01)
            zoom = max(0.01, min(100.0, zoom))
            setattr(camera, "_zoom_level", zoom)
            return zoom
        except Exception:  # noqa: BLE001
            return distance
    return distance


def _path_for(ctx: dict[str, Any]) -> str:
    """Label used in the result dict's ``path`` field."""
    if ctx.get("camera") is not None:
        return "camera"
    shell = ctx.get("shell")
    if shell is not None and getattr(shell, "_viewport_panel", None) is not None:
        return "shell"
    if shell is not None and getattr(shell, "_camera", None) is not None:
        return "shell"
    return "fallback"


# ---------------------------------------------------------------------------
# Public actions
# ---------------------------------------------------------------------------


def center_on_selection(ctx: dict[str, Any]) -> dict[str, Any]:
    """Pan the viewport camera to the centroid of the current selection.

    * Resolves the selection via ``ctx["selection"]`` → shell slots.
    * Computes the centroid of the selection's ``(x, y, z)`` positions.
    * Writes the centroid to ``camera._cam_target`` (or the 2D pan slots
      when the camera exposes ``_pan_x`` / ``_pan_y`` instead).

    Distance is untouched — this is a *pan*, not a frame-fit. Use
    :func:`frame_all` when you also want to re-zoom.
    """
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

    target = _centroid(points)
    ok = _write_cam_target(camera, target)
    if not ok:
        return {"status": "error", "message": "camera has no pan target"}
    return {
        "status": "centered",
        "target": list(target),
        "count": len(points),
        "path": _path_for(ctx),
    }


def frame_all(ctx: dict[str, Any]) -> dict[str, Any]:
    """Pan and zoom the viewport camera to encompass every scene entity.

    * Enumerates every entity from the active scene (falls back to
      ``ctx["entities"]`` for headless testing).
    * Computes the AABB, centroid, and bounding-sphere radius.
    * Writes ``_cam_target = centroid`` and
      ``_cam_distance = radius * margin`` (default 1.15×).

    Returns
    -------
    dict
        ``{"status": "framed", "target": [...], "distance": float,
        "radius": float, "path": ...}`` on success.
        ``{"status": "empty_scene"}`` when the scene has no entities.
        ``{"status": "no_camera"}`` when no camera is reachable.
    """
    camera = _get_camera(ctx)
    if camera is None:
        return {"status": "no_camera"}

    override_entities = ctx.get("entities")
    if override_entities is not None:
        entities = list(override_entities)
    else:
        scene = _get_scene(ctx)
        entities = _list_scene_entities(scene)

    if not entities:
        return {"status": "empty_scene"}

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
    # Half-diagonal of the AABB = bounding-sphere radius upper bound.
    dx = maxx - minx
    dy = maxy - miny
    dz = maxz - minz
    radius = 0.5 * math.sqrt(dx * dx + dy * dy + dz * dz)
    # Convert bounding-sphere radius to camera distance. Empirically a
    # sphere of radius R sits comfortably in the view at distance
    # R / tan(fov/2) with a small margin. We don't know the FOV here, so
    # we use ``radius * 2`` as a decent generic default and let the
    # margin knob widen it further.
    if radius <= 0.0:
        distance = _MIN_FRAME_DISTANCE
    else:
        distance = max(radius * 2.0 * _FRAME_MARGIN, _MIN_FRAME_DISTANCE)

    ok = _write_cam_target(camera, centroid)
    written = _write_cam_distance(camera, distance)
    if not ok and written == distance:
        # Camera didn't accept either mutation — surface the failure.
        return {"status": "error", "message": "camera has no target/distance"}
    return {
        "status": "framed",
        "target": list(centroid),
        "distance": written,
        "radius": radius,
        "count": len(points),
        "path": _path_for(ctx),
    }


__all__ = [
    "center_on_selection",
    "frame_all",
]
