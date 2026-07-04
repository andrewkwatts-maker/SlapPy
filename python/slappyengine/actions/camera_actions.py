"""Camera-lifecycle actions — viewport zoom in / out / reset.

Backs the ``view.zoom_in`` / ``view.zoom_out`` / ``view.zoom_reset``
:class:`~slappyengine.tool_router.ToolAction` rows added by the Z7
STUB-triage sprint tick.

The three actions mutate the viewport camera state used by the DPG
``ViewportPanel`` renderer. In 3D mode this is the orbit-camera distance
(``_cam_distance``); in 2D mode it's the ortho zoom-level. The panel
already exposes ``_cam_distance`` as its authoritative zoom knob, so the
actions target that attribute preferentially and fall back to the
generic ``_zoom_level`` slot for 2D-only fake shells.

Design goals
------------

* **Headless-safe** — callers may pass ``ctx["camera"]`` (a bare object
  with ``_cam_distance`` / ``_zoom_level``) instead of a full shell. That
  makes the actions testable without instantiating DPG.
* **Multiplicative stepping** — each ``zoom_in`` divides the distance by
  ``ctx["step"]`` (default 1.2); each ``zoom_out`` multiplies. That
  produces a stable perceptual zoom feel across large ranges.
* **Clamped range** — distances below 0.05 world-units or above 10000
  are clamped so a runaway wheel spin can't send the camera through the
  target or into oblivion.

Return contract
---------------

* ``{"status": "zoomed", "distance": float, "delta": float, "path": ...}``
  on success (where ``path`` is either ``"shell"`` / ``"camera"`` /
  ``"fallback"``).
* ``{"status": "no_camera"}`` when no viewport / camera slot is reachable
  and the caller hasn't supplied a headless ``camera`` object either.
"""
from __future__ import annotations

from typing import Any


# Reset defaults — match ViewportPanel.__init__.
_DEFAULT_CAM_DISTANCE: float = 5.0
_DEFAULT_ZOOM_LEVEL: float = 1.0

# Safety clamps so a runaway wheel spin can't send the camera to infinity.
_MIN_DISTANCE: float = 0.05
_MAX_DISTANCE: float = 10000.0
_MIN_ZOOM_LEVEL: float = 0.01
_MAX_ZOOM_LEVEL: float = 100.0

# Default multiplicative step per click.
_DEFAULT_STEP: float = 1.2


def _get_camera(ctx: dict[str, Any]) -> Any:
    """Resolve a camera-like object from *ctx*.

    Search order:

    1. ``ctx["camera"]`` — direct override (tests pass this).
    2. ``ctx["shell"]._viewport_panel`` — the canonical viewport handle.
    3. ``ctx["shell"]._camera`` — legacy per-shell camera attribute.
    """
    override = ctx.get("camera")
    if override is not None:
        return override
    shell = ctx.get("shell")
    if shell is None:
        return None
    panel = getattr(shell, "_viewport_panel", None)
    if panel is not None:
        return panel
    return getattr(shell, "_camera", None)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _resolve_step(ctx: dict[str, Any]) -> float:
    step = ctx.get("step")
    if step is None:
        return _DEFAULT_STEP
    try:
        step = float(step)
    except (TypeError, ValueError):
        return _DEFAULT_STEP
    # Guard against zero / negative multipliers that would collapse the
    # camera state.
    if step <= 0.0:
        return _DEFAULT_STEP
    return step


def _read_current(camera: Any) -> tuple[str, float] | None:
    """Return ``(attr_name, value)`` for the camera's current zoom knob."""
    if camera is None:
        return None
    dist = getattr(camera, "_cam_distance", None)
    if dist is not None:
        try:
            return ("_cam_distance", float(dist))
        except (TypeError, ValueError):
            pass
    zl = getattr(camera, "_zoom_level", None)
    if zl is not None:
        try:
            return ("_zoom_level", float(zl))
        except (TypeError, ValueError):
            pass
    return None


def _apply_new(camera: Any, attr: str, value: float) -> float:
    """Clamp *value* against per-attr range and write it back to *camera*."""
    if attr == "_cam_distance":
        clamped = _clamp(value, _MIN_DISTANCE, _MAX_DISTANCE)
    else:
        clamped = _clamp(value, _MIN_ZOOM_LEVEL, _MAX_ZOOM_LEVEL)
    try:
        setattr(camera, attr, clamped)
    except Exception:  # noqa: BLE001
        return value
    return clamped


def _path_for(ctx: dict[str, Any]) -> str:
    """Return the label used in the result dict's ``path`` field."""
    if ctx.get("camera") is not None:
        return "camera"
    shell = ctx.get("shell")
    if shell is not None and getattr(shell, "_viewport_panel", None) is not None:
        return "shell"
    if shell is not None and getattr(shell, "_camera", None) is not None:
        return "shell"
    return "fallback"


def zoom_in(ctx: dict[str, Any]) -> dict[str, Any]:
    """Zoom the viewport camera in by one step.

    Divides ``_cam_distance`` by ``ctx["step"]`` (default 1.2) or the
    2D ``_zoom_level`` by the same amount, then clamps against the
    per-attribute safety range. Returns the new distance for the status
    bar readout.
    """
    camera = _get_camera(ctx)
    current = _read_current(camera)
    if current is None:
        return {"status": "no_camera"}
    attr, value = current
    step = _resolve_step(ctx)
    if attr == "_cam_distance":
        new_val = _apply_new(camera, attr, value / step)
    else:
        # Zooming *in* on a 2D ortho camera means the ``_zoom_level``
        # multiplier grows (things look bigger).
        new_val = _apply_new(camera, attr, value * step)
    return {
        "status": "zoomed",
        "distance": new_val,
        "delta": new_val - value,
        "path": _path_for(ctx),
    }


def zoom_out(ctx: dict[str, Any]) -> dict[str, Any]:
    """Zoom the viewport camera out by one step.

    Mirror of :func:`zoom_in` — ``_cam_distance`` grows or the ortho
    ``_zoom_level`` shrinks.
    """
    camera = _get_camera(ctx)
    current = _read_current(camera)
    if current is None:
        return {"status": "no_camera"}
    attr, value = current
    step = _resolve_step(ctx)
    if attr == "_cam_distance":
        new_val = _apply_new(camera, attr, value * step)
    else:
        new_val = _apply_new(camera, attr, value / step)
    return {
        "status": "zoomed",
        "distance": new_val,
        "delta": new_val - value,
        "path": _path_for(ctx),
    }


def zoom_reset(ctx: dict[str, Any]) -> dict[str, Any]:
    """Restore the viewport camera to its default zoom.

    Writes ``_cam_distance = 5.0`` (matches :class:`ViewportPanel`'s
    ctor default) or ``_zoom_level = 1.0`` for 2D shells. Callers may
    override the reset target via ``ctx["distance"]`` — useful for the
    "recenter on selection" flow that computes an ideal distance from
    the current selection's bounding box.
    """
    camera = _get_camera(ctx)
    current = _read_current(camera)
    if current is None:
        return {"status": "no_camera"}
    attr, old_value = current
    override = ctx.get("distance")
    if override is not None:
        try:
            target = float(override)
        except (TypeError, ValueError):
            target = (
                _DEFAULT_CAM_DISTANCE
                if attr == "_cam_distance"
                else _DEFAULT_ZOOM_LEVEL
            )
    else:
        target = (
            _DEFAULT_CAM_DISTANCE
            if attr == "_cam_distance"
            else _DEFAULT_ZOOM_LEVEL
        )
    new_val = _apply_new(camera, attr, target)
    return {
        "status": "reset",
        "distance": new_val,
        "previous": old_value,
        "path": _path_for(ctx),
    }


__all__ = [
    "zoom_in",
    "zoom_out",
    "zoom_reset",
]
