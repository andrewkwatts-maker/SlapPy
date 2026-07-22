"""View set-zoom action — jump the viewport camera to an explicit zoom value.

Backs the ``view.set_zoom`` :class:`~pharos_engine.tool_router.ToolAction`
row added by the TT2 STUB-triage sprint tick (round 21 after SS1's
round-20 ``content.reveal_in_explorer`` / ``content.duplicate_folder`` /
``view.increase_pixel_scale`` / ``view.decrease_pixel_scale`` /
``spawn.stamp_repeat`` batch).

Distinct from Z7's ``view.zoom_in`` / ``view.zoom_out`` / ``view.zoom_reset``
(which walk the camera *by* a multiplicative step / snap it back to a
hard-coded default): this verb jumps the camera *to* a supplied absolute
distance. Every DCC ships a numeric zoom entry — Blender's ``N``-panel
zoom field, Unity's Scene camera "size" input, Nova3D's ``Camera →
Zoom…`` dialog — for the "put me at 12 units, exactly" flow.

Distinct from SS1's ``view.increase_pixel_scale`` /
``view.decrease_pixel_scale`` (which mutate an integer framebuffer scale
factor) — this verb targets the *continuous* camera zoom knob (either
``_cam_distance`` in 3D or ``_zoom_level`` in 2D), matching the pair Z7's
actions already target.

Distance resolution
-------------------

* ``ctx["distance"]`` — required numeric target. Interpreted against
  ``_cam_distance`` on 3D shells (world units) and ``_zoom_level`` on
  2D shells (multiplier). The safety clamp mirrors Z7:
  ``_cam_distance`` in ``[0.05, 10000]``; ``_zoom_level`` in
  ``[0.01, 100]``.
* ``ctx["camera"]`` / ``ctx["shell"]`` — resolved via
  :mod:`~pharos_engine.actions.camera_actions` (same
  ``_viewport_panel`` → ``_camera`` walk) so callers can share the
  headless test pattern with Z7's row.

Return contract
---------------

* ``{"status": "set", "distance": float, "previous": float,
   "path": "shell" | "camera" | "fallback"}`` on success.
* ``{"status": "no_camera"}`` when no viewport / camera slot is reachable.
* ``{"status": "missing_distance"}`` when ``ctx["distance"]`` is absent
  or not a finite number.
"""
from __future__ import annotations

import math
from typing import Any

from ._ctx import ensure_ctx
from .camera_actions import (
    _apply_new,
    _get_camera,
    _path_for,
    _read_current,
)


def _coerce_distance(raw: Any) -> float | None:
    """Return *raw* as a finite float, or ``None`` when unusable."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(val):
        return None
    return val


def set_zoom(ctx: dict[str, Any]) -> dict[str, Any]:
    """Jump the viewport camera to the supplied absolute zoom value.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``distance`` (required, numeric): target value written to
          ``_cam_distance`` (3D) or ``_zoom_level`` (2D). Clamped via
          the same bounds Z7's ``zoom_reset`` uses.
        * ``camera`` (optional): direct headless override.
        * ``shell`` (optional): editor shell providing
          ``_viewport_panel`` / ``_camera``.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("set_zoom", ctx)
    target = _coerce_distance(ctx.get("distance"))
    if target is None:
        return {"status": "missing_distance"}
    camera = _get_camera(ctx)
    current = _read_current(camera)
    if current is None:
        return {"status": "no_camera"}
    attr, previous = current
    new_val = _apply_new(camera, attr, target)
    return {
        "status": "set",
        "distance": new_val,
        "previous": previous,
        "path": _path_for(ctx),
    }


__all__ = ["set_zoom"]
