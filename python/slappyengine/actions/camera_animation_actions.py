"""Animation-curve-driven camera moves — pan-to / zoom-to / focus / frame-all.

Backs two new router actions added by the CC6 sprint tick:

* ``view.focus_on_selection_animated`` — pans + zooms to selection with
  800 ms ``ease_in_out`` (default). Non-blocking — the caller must drive
  :meth:`CameraAnimator.tick` from the frame loop so the interpolated
  camera state advances.
* ``view.frame_all_animated`` — animated version of
  :func:`slappyengine.actions.viewport_framing_actions.frame_all`.

Design goals
------------

* **Non-blocking** — animator.tween_to_position returns immediately with a
  :class:`CameraTweenState`; the caller pumps ``tick(now_ms)`` from the
  frame loop. This matches how the editor's ViewportPanel already threads
  the render clock.
* **Headless-safe** — the animator never touches DPG; every method
  operates on the same duck-typed ``camera`` surface used by
  :mod:`~slappyengine.actions.camera_actions` (``_cam_target``,
  ``_cam_distance``, ``_pan_x`` / ``_pan_y``, ``_zoom_level``).
* **Six easing curves** — ``linear``, ``ease_in``, ``ease_out``,
  ``ease_in_out``, ``bounce`` (Penner-style trailing bounce), and ``back``
  (small overshoot before settling). All expose ``t ∈ [0, 1] → [0, 1]``
  (bounce / back deliberately step outside the codomain at the tails —
  that's the visual point).
* **Concurrent tweens** — the animator holds separate slots for position
  and zoom so a caller can e.g. tween-to-position while a zoom-out is
  still resolving. :meth:`focus_on_entity` starts both simultaneously.

Return / status contract
------------------------

* ``tween_to_position`` / ``tween_to_zoom`` / ``focus_on_entity`` /
  ``frame_all_animated`` return the :class:`CameraTweenState` for the
  newly-scheduled tween (or ``None`` when the camera lacks the required
  slot / the entity has no positional data).
* Router fallbacks return a small dict shaped like the surrounding
  camera actions: ``{"status": "tween_started", ...}`` /
  ``{"status": "no_camera"}`` / ``{"status": "no_selection"}`` /
  ``{"status": "empty_scene"}``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

from ._ctx import ensure_ctx


# ---------------------------------------------------------------------------
# Easing curves
# ---------------------------------------------------------------------------


def _ease_linear(t: float) -> float:
    return t


def _ease_in(t: float) -> float:
    # Quadratic ease-in — accelerates from rest.
    return t * t


def _ease_out(t: float) -> float:
    # Quadratic ease-out — decelerates to rest.
    return 1.0 - (1.0 - t) * (1.0 - t)


def _ease_in_out(t: float) -> float:
    # Cubic ease-in-out — Google Material's default motion curve.
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0


def _ease_bounce(t: float) -> float:
    # Standard Penner bounce-out — 4-segment quadratic bounce that
    # oscillates on approach and lands cleanly at t=1.
    n1 = 7.5625
    d1 = 2.75
    if t < 1.0 / d1:
        return n1 * t * t
    if t < 2.0 / d1:
        t2 = t - 1.5 / d1
        return n1 * t2 * t2 + 0.75
    if t < 2.5 / d1:
        t2 = t - 2.25 / d1
        return n1 * t2 * t2 + 0.9375
    t2 = t - 2.625 / d1
    return n1 * t2 * t2 + 0.984375


def _ease_back(t: float) -> float:
    # "Back" ease-out — anticipatory overshoot before settling at 1. Uses
    # the standard Penner constants (c1 = 1.70158, c3 = c1 + 1) so the
    # curve exceeds 1.0 mid-flight before returning.
    c1 = 1.70158
    c3 = c1 + 1.0
    u = t - 1.0
    return 1.0 + c3 * u * u * u + c1 * u * u


# Exposed as an ordinary dict so callers can add curves at runtime for
# per-scene motion vocabularies without patching this module.
EasingCurves: dict[str, Callable[[float], float]] = {
    "linear":      _ease_linear,
    "ease_in":     _ease_in,
    "ease_out":    _ease_out,
    "ease_in_out": _ease_in_out,
    "bounce":      _ease_bounce,
    "back":        _ease_back,
}


_DEFAULT_EASING: str = "ease_in_out"
_DEFAULT_POS_DURATION_MS: float = 800.0
_DEFAULT_ZOOM_DURATION_MS: float = 500.0
_DEFAULT_FOCUS_DURATION_MS: float = 1000.0
_DEFAULT_FRAME_ALL_DURATION_MS: float = 1200.0

# AABB → camera-distance heuristic (matches viewport_framing_actions).
_FRAME_MARGIN: float = 1.15
_MIN_FRAME_DISTANCE: float = 5.0

# Match the safety clamps in camera_actions / viewport_framing_actions.
_MIN_DISTANCE: float = 0.05
_MAX_DISTANCE: float = 10000.0
_MIN_ZOOM_LEVEL: float = 0.01
_MAX_ZOOM_LEVEL: float = 100.0


# ---------------------------------------------------------------------------
# CameraTweenState
# ---------------------------------------------------------------------------


@dataclass
class CameraTweenState:
    """Snapshot of an active camera tween.

    The animator schedules position and zoom tweens in separate slots so
    focus / frame-all can drive both concurrently. The ``camera`` handle
    is kept so :meth:`CameraAnimator.tick` can mutate it directly without
    re-resolving from a context each frame.
    """

    start_time_ms: float
    duration_ms: float
    from_pos: tuple[float, float, float] | None
    to_pos: tuple[float, float, float] | None
    from_zoom: float | None
    to_zoom: float | None
    easing_kind: str = _DEFAULT_EASING
    camera: Any = None
    kind: str = "position"  # "position" | "zoom" | "combined"
    done: bool = False
    _final_position_written: bool = field(default=False, repr=False)
    _final_zoom_written: bool = field(default=False, repr=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _read_position(camera: Any) -> tuple[float, float, float] | None:
    """Return the current camera ``_cam_target`` (or 2D pan slots)."""
    if camera is None:
        return None
    tgt = getattr(camera, "_cam_target", None)
    if tgt is not None:
        try:
            seq = tuple(tgt)
        except TypeError:
            seq = None
        if seq is not None and len(seq) >= 2:
            try:
                x = float(seq[0])
                y = float(seq[1])
                z = float(seq[2]) if len(seq) >= 3 else 0.0
                return (x, y, z)
            except (TypeError, ValueError):
                pass
    # 2D fallback.
    if hasattr(camera, "_pan_x") or hasattr(camera, "_pan_y"):
        try:
            x = float(getattr(camera, "_pan_x", 0.0) or 0.0)
            y = float(getattr(camera, "_pan_y", 0.0) or 0.0)
            return (x, y, 0.0)
        except (TypeError, ValueError):
            return None
    return None


def _write_position(camera: Any, pos: tuple[float, float, float]) -> bool:
    """Write ``pos`` to the camera. Mirrors viewport_framing_actions."""
    if camera is None:
        return False
    existing = getattr(camera, "_cam_target", None)
    if existing is not None:
        try:
            if isinstance(existing, list):
                existing[:] = list(pos)
            else:
                setattr(camera, "_cam_target", list(pos))
            return True
        except Exception:  # noqa: BLE001
            return False
    if hasattr(camera, "_pan_x") or hasattr(camera, "_pan_y"):
        try:
            setattr(camera, "_pan_x", float(pos[0]))
            setattr(camera, "_pan_y", float(pos[1]))
            return True
        except Exception:  # noqa: BLE001
            return False
    return False


def _read_zoom(camera: Any) -> tuple[str, float] | None:
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


def _write_zoom(camera: Any, value: float) -> float:
    """Write *value* to the camera's zoom slot with per-attr clamping."""
    if camera is None:
        return value
    if hasattr(camera, "_cam_distance"):
        clamped = _clamp(value, _MIN_DISTANCE, _MAX_DISTANCE)
        try:
            setattr(camera, "_cam_distance", clamped)
            return clamped
        except Exception:  # noqa: BLE001
            return value
    if hasattr(camera, "_zoom_level"):
        clamped = _clamp(value, _MIN_ZOOM_LEVEL, _MAX_ZOOM_LEVEL)
        try:
            setattr(camera, "_zoom_level", clamped)
            return clamped
        except Exception:  # noqa: BLE001
            return value
    return value


def _entity_position(entity: Any) -> tuple[float, float, float] | None:
    """Same shape parser as viewport_framing_actions._entity_position."""
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


def _entity_aabb(entity: Any) -> tuple[
    tuple[float, float, float], tuple[float, float, float]
] | None:
    """Return ``(mins, maxs)`` for the entity's AABB, or ``None``.

    Uses ``entity.aabb()`` / ``entity.bounds`` when available; otherwise
    falls back to a zero-extent box around ``entity.position``.
    """
    if entity is None:
        return None
    # Try an explicit AABB accessor.
    for name in ("aabb", "get_aabb", "bounds"):
        accessor = getattr(entity, name, None)
        if accessor is None:
            continue
        try:
            box = accessor() if callable(accessor) else accessor
        except Exception:  # noqa: BLE001
            continue
        try:
            mn, mx = box
            mn = tuple(float(v) for v in mn)
            mx = tuple(float(v) for v in mx)
            if len(mn) >= 2 and len(mx) >= 2:
                mn = (mn[0], mn[1], mn[2] if len(mn) >= 3 else 0.0)
                mx = (mx[0], mx[1], mx[2] if len(mx) >= 3 else 0.0)
                return (mn, mx)
        except Exception:  # noqa: BLE001
            continue
    pos = _entity_position(entity)
    if pos is None:
        return None
    return (pos, pos)


def _resolve_easing(kind: str | None) -> str:
    if kind is None:
        return _DEFAULT_EASING
    if kind in EasingCurves:
        return kind
    return _DEFAULT_EASING


def _lerp(a: float, b: float, u: float) -> float:
    return a + (b - a) * u


def _lerp_pos(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    u: float,
) -> tuple[float, float, float]:
    return (_lerp(a[0], b[0], u), _lerp(a[1], b[1], u), _lerp(a[2], b[2], u))


# ---------------------------------------------------------------------------
# CameraAnimator
# ---------------------------------------------------------------------------


class CameraAnimator:
    """Drives non-blocking camera tweens.

    The animator holds at most one active position tween and one active
    zoom tween per camera slot; scheduling a new tween cancels the prior
    one for that slot so :meth:`tick` never fights itself. Callers pump
    :meth:`tick` from the frame loop with a monotonic ``now_ms`` clock.
    """

    def __init__(self) -> None:
        # We deliberately keep separate slots for position and zoom so
        # focus_on_entity can drive both concurrently without racing.
        self._pos_tween: CameraTweenState | None = None
        self._zoom_tween: CameraTweenState | None = None
        # For frame_all_animated we may schedule a "combined" tween
        # against a fresh camera — expose the last combined state so
        # tests can introspect it. This is aliased to whichever of
        # _pos_tween / _zoom_tween is newer.
        self._last_combined: CameraTweenState | None = None

    # -- Introspection --------------------------------------------------

    def active_count(self) -> int:
        """Return the number of active (not-done) tweens."""
        n = 0
        if self._pos_tween is not None and not self._pos_tween.done:
            n += 1
        if self._zoom_tween is not None and not self._zoom_tween.done:
            n += 1
        return n

    @property
    def position_tween(self) -> CameraTweenState | None:
        return self._pos_tween

    @property
    def zoom_tween(self) -> CameraTweenState | None:
        return self._zoom_tween

    # -- Cancellation ---------------------------------------------------

    def stop_all(self) -> int:
        """Cancel every active tween. Returns the number cancelled."""
        n = 0
        if self._pos_tween is not None and not self._pos_tween.done:
            self._pos_tween.done = True
            n += 1
        if self._zoom_tween is not None and not self._zoom_tween.done:
            self._zoom_tween.done = True
            n += 1
        self._pos_tween = None
        self._zoom_tween = None
        self._last_combined = None
        return n

    # -- Scheduling primitives -----------------------------------------

    def tween_to_position(
        self,
        camera: Any,
        target_pos: Any,
        duration_ms: float = _DEFAULT_POS_DURATION_MS,
        easing: str = _DEFAULT_EASING,
        now_ms: float = 0.0,
    ) -> CameraTweenState | None:
        """Start a pan tween toward ``target_pos``.

        Returns ``None`` when the camera lacks a pan slot or the target
        cannot be parsed. Otherwise returns the :class:`CameraTweenState`
        for the scheduled tween; the caller must drive :meth:`tick` from
        the frame loop.
        """
        current = _read_position(camera)
        if current is None:
            return None
        try:
            seq = tuple(target_pos)
        except TypeError:
            return None
        if len(seq) < 2:
            return None
        try:
            tx = float(seq[0])
            ty = float(seq[1])
            tz = float(seq[2]) if len(seq) >= 3 else 0.0
        except (TypeError, ValueError):
            return None
        try:
            dur = max(1.0, float(duration_ms))
        except (TypeError, ValueError):
            dur = _DEFAULT_POS_DURATION_MS
        state = CameraTweenState(
            start_time_ms=float(now_ms),
            duration_ms=dur,
            from_pos=current,
            to_pos=(tx, ty, tz),
            from_zoom=None,
            to_zoom=None,
            easing_kind=_resolve_easing(easing),
            camera=camera,
            kind="position",
        )
        # Cancel any in-flight position tween.
        if self._pos_tween is not None:
            self._pos_tween.done = True
        self._pos_tween = state
        self._last_combined = state
        return state

    def tween_to_zoom(
        self,
        camera: Any,
        target_zoom: float,
        duration_ms: float = _DEFAULT_ZOOM_DURATION_MS,
        easing: str = _DEFAULT_EASING,
        now_ms: float = 0.0,
    ) -> CameraTweenState | None:
        """Start a zoom tween toward ``target_zoom``.

        Returns ``None`` when the camera lacks a zoom slot or the target
        is not a finite number.
        """
        current = _read_zoom(camera)
        if current is None:
            return None
        try:
            tz = float(target_zoom)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(tz):
            return None
        try:
            dur = max(1.0, float(duration_ms))
        except (TypeError, ValueError):
            dur = _DEFAULT_ZOOM_DURATION_MS
        state = CameraTweenState(
            start_time_ms=float(now_ms),
            duration_ms=dur,
            from_pos=None,
            to_pos=None,
            from_zoom=current[1],
            to_zoom=tz,
            easing_kind=_resolve_easing(easing),
            camera=camera,
            kind="zoom",
        )
        if self._zoom_tween is not None:
            self._zoom_tween.done = True
        self._zoom_tween = state
        return state

    def focus_on_entity(
        self,
        camera: Any,
        entity: Any,
        duration_ms: float = _DEFAULT_FOCUS_DURATION_MS,
        easing: str = _DEFAULT_EASING,
        now_ms: float = 0.0,
    ) -> CameraTweenState | None:
        """Pan + zoom to fit ``entity``'s AABB.

        Returns the position tween state (the zoom tween is chained to
        the same duration/easing). Returns ``None`` when the entity has
        no positional data.
        """
        if camera is None or entity is None:
            return None
        box = _entity_aabb(entity)
        if box is None:
            return None
        (mn, mx) = box
        centroid = (
            0.5 * (mn[0] + mx[0]),
            0.5 * (mn[1] + mx[1]),
            0.5 * (mn[2] + mx[2]),
        )
        dx, dy, dz = mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]
        radius = 0.5 * math.sqrt(dx * dx + dy * dy + dz * dz)
        if radius <= 0.0:
            distance = _MIN_FRAME_DISTANCE
        else:
            distance = max(radius * 2.0 * _FRAME_MARGIN, _MIN_FRAME_DISTANCE)
        pos_state = self.tween_to_position(
            camera, centroid, duration_ms=duration_ms, easing=easing,
            now_ms=now_ms,
        )
        if pos_state is not None:
            pos_state.kind = "combined"
        self.tween_to_zoom(
            camera, distance, duration_ms=duration_ms, easing=easing,
            now_ms=now_ms,
        )
        return pos_state

    def frame_all_animated(
        self,
        camera: Any,
        entities: Any,
        duration_ms: float = _DEFAULT_FRAME_ALL_DURATION_MS,
        easing: str = _DEFAULT_EASING,
        now_ms: float = 0.0,
    ) -> CameraTweenState | None:
        """Animated ``frame_all`` — pan + zoom to encompass all entities."""
        if camera is None:
            return None
        try:
            ents = list(entities) if entities is not None else []
        except TypeError:
            return None
        points = [
            p for p in (_entity_position(e) for e in ents) if p is not None
        ]
        if not points:
            return None
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        zs = [p[2] for p in points]
        minx, miny, minz = min(xs), min(ys), min(zs)
        maxx, maxy, maxz = max(xs), max(ys), max(zs)
        centroid = (
            0.5 * (minx + maxx),
            0.5 * (miny + maxy),
            0.5 * (minz + maxz),
        )
        dx, dy, dz = maxx - minx, maxy - miny, maxz - minz
        radius = 0.5 * math.sqrt(dx * dx + dy * dy + dz * dz)
        if radius <= 0.0:
            distance = _MIN_FRAME_DISTANCE
        else:
            distance = max(radius * 2.0 * _FRAME_MARGIN, _MIN_FRAME_DISTANCE)
        pos_state = self.tween_to_position(
            camera, centroid, duration_ms=duration_ms, easing=easing,
            now_ms=now_ms,
        )
        if pos_state is not None:
            pos_state.kind = "combined"
        self.tween_to_zoom(
            camera, distance, duration_ms=duration_ms, easing=easing,
            now_ms=now_ms,
        )
        return pos_state

    # -- Frame-loop driver ---------------------------------------------

    def tick(self, now_ms: float) -> int:
        """Advance every active tween. Returns the count that ran.

        Each call re-computes the eased fraction ``u ∈ [0, 1]`` and
        writes the interpolated position / zoom back to the camera. When
        ``u >= 1`` the tween's final value is written and the slot is
        flagged done (but retained so tests can inspect it).
        """
        try:
            now = float(now_ms)
        except (TypeError, ValueError):
            return 0
        driven = 0
        # -- Position ---------------------------------------------------
        pt = self._pos_tween
        if pt is not None and not pt.done and pt.from_pos is not None and pt.to_pos is not None:
            u = (now - pt.start_time_ms) / pt.duration_ms
            if u >= 1.0:
                if not pt._final_position_written:
                    _write_position(pt.camera, pt.to_pos)
                    pt._final_position_written = True
                pt.done = True
            elif u <= 0.0:
                _write_position(pt.camera, pt.from_pos)
            else:
                curve = EasingCurves.get(pt.easing_kind, _ease_in_out)
                v = curve(u)
                pos = _lerp_pos(pt.from_pos, pt.to_pos, v)
                _write_position(pt.camera, pos)
            driven += 1
        # -- Zoom -------------------------------------------------------
        zt = self._zoom_tween
        if zt is not None and not zt.done and zt.from_zoom is not None and zt.to_zoom is not None:
            u = (now - zt.start_time_ms) / zt.duration_ms
            if u >= 1.0:
                if not zt._final_zoom_written:
                    _write_zoom(zt.camera, zt.to_zoom)
                    zt._final_zoom_written = True
                zt.done = True
            elif u <= 0.0:
                _write_zoom(zt.camera, zt.from_zoom)
            else:
                curve = EasingCurves.get(zt.easing_kind, _ease_in_out)
                v = curve(u)
                val = _lerp(zt.from_zoom, zt.to_zoom, v)
                _write_zoom(zt.camera, val)
            driven += 1
        return driven


# ---------------------------------------------------------------------------
# Module-level animator (used by the router fallbacks so a single global
# clock/state is shared across editor UI actions).
# ---------------------------------------------------------------------------


_MODULE_ANIMATOR: CameraAnimator = CameraAnimator()


def get_module_animator() -> CameraAnimator:
    """Return the process-wide default :class:`CameraAnimator` singleton."""
    return _MODULE_ANIMATOR


# ---------------------------------------------------------------------------
# Router fallbacks (view.focus_on_selection_animated, view.frame_all_animated)
# ---------------------------------------------------------------------------


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


def _get_scene(ctx: dict[str, Any]) -> Any:
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


def _resolve_animator(ctx: dict[str, Any]) -> CameraAnimator:
    override = ctx.get("animator")
    if isinstance(override, CameraAnimator):
        return override
    shell = _get_shell(ctx)
    if shell is not None:
        stored = getattr(shell, "_camera_animator", None)
        if isinstance(stored, CameraAnimator):
            return stored
    return _MODULE_ANIMATOR


def _resolve_now_ms(ctx: dict[str, Any]) -> float:
    """Return the frame-loop ``now_ms`` clock or ``0.0``."""
    raw = ctx.get("now_ms")
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _fb_tween_to_position(ctx: dict[str, Any]) -> dict[str, Any]:
    """Router fallback: schedule an animated pan to ``ctx["target"]``.

    Returns ``{"status": "tween_started", "target": [...],
    "duration_ms": float, "easing": str}`` on success.
    """
    ensure_ctx("tween_to_position", ctx)
    camera = _get_camera(ctx)
    if camera is None:
        return {"status": "no_camera"}
    target = ctx.get("target")
    if target is None:
        return {"status": "no_target"}
    duration = ctx.get("duration_ms", _DEFAULT_POS_DURATION_MS)
    easing = ctx.get("easing", _DEFAULT_EASING)
    animator = _resolve_animator(ctx)
    now = _resolve_now_ms(ctx)
    state = animator.tween_to_position(
        camera, target, duration_ms=duration, easing=easing, now_ms=now,
    )
    if state is None:
        return {"status": "error", "message": "invalid target or camera"}
    return {
        "status": "tween_started",
        "target": list(state.to_pos or ()),
        "duration_ms": state.duration_ms,
        "easing": state.easing_kind,
    }


def _fb_focus_on_entity(ctx: dict[str, Any]) -> dict[str, Any]:
    """Router fallback: focus on ``ctx["entity"]`` (or first selection)."""
    ensure_ctx("focus_on_entity", ctx)
    camera = _get_camera(ctx)
    if camera is None:
        return {"status": "no_camera"}
    entity = ctx.get("entity")
    if entity is None:
        selection = _resolve_selection(ctx)
        if not selection:
            return {"status": "no_selection"}
        entity = selection[0]
    duration = ctx.get("duration_ms", _DEFAULT_FOCUS_DURATION_MS)
    easing = ctx.get("easing", _DEFAULT_EASING)
    animator = _resolve_animator(ctx)
    now = _resolve_now_ms(ctx)
    state = animator.focus_on_entity(
        camera, entity, duration_ms=duration, easing=easing, now_ms=now,
    )
    if state is None:
        return {"status": "error", "message": "entity has no position"}
    return {
        "status": "tween_started",
        "target": list(state.to_pos or ()),
        "duration_ms": state.duration_ms,
        "easing": state.easing_kind,
    }


def focus_on_selection_animated(ctx: dict[str, Any]) -> dict[str, Any]:
    """Router action: pan + zoom to selection centroid over 800 ms.

    Uses the ``ease_in_out`` curve by default; caller may override via
    ``ctx["easing"]`` / ``ctx["duration_ms"]``.
    """
    ensure_ctx("focus_on_selection_animated", ctx)
    camera = _get_camera(ctx)
    if camera is None:
        return {"status": "no_camera"}
    selection = _resolve_selection(ctx)
    if not selection:
        return {"status": "no_selection"}
    duration = ctx.get("duration_ms", _DEFAULT_POS_DURATION_MS)
    easing = ctx.get("easing", _DEFAULT_EASING)
    animator = _resolve_animator(ctx)
    now = _resolve_now_ms(ctx)
    # Aggregate every selection point into a single bounding sphere.
    points = [
        p for p in (_entity_position(e) for e in selection) if p is not None
    ]
    if not points:
        return {"status": "no_positions"}
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    centroid = (
        0.5 * (min(xs) + max(xs)),
        0.5 * (min(ys) + max(ys)),
        0.5 * (min(zs) + max(zs)),
    )
    dx = max(xs) - min(xs)
    dy = max(ys) - min(ys)
    dz = max(zs) - min(zs)
    radius = 0.5 * math.sqrt(dx * dx + dy * dy + dz * dz)
    if radius <= 0.0:
        distance = _MIN_FRAME_DISTANCE
    else:
        distance = max(radius * 2.0 * _FRAME_MARGIN, _MIN_FRAME_DISTANCE)
    pos_state = animator.tween_to_position(
        camera, centroid, duration_ms=duration, easing=easing, now_ms=now,
    )
    animator.tween_to_zoom(
        camera, distance, duration_ms=duration, easing=easing, now_ms=now,
    )
    if pos_state is None:
        return {"status": "error", "message": "camera has no pan slot"}
    return {
        "status": "tween_started",
        "target": list(pos_state.to_pos or ()),
        "distance": distance,
        "duration_ms": duration,
        "easing": easing,
        "count": len(points),
    }


def frame_all_animated(ctx: dict[str, Any]) -> dict[str, Any]:
    """Router action: animated frame_all.

    Enumerates every scene entity (or ``ctx["entities"]`` for headless
    tests) and pans/zooms to encompass their AABB with an 1200 ms
    ``ease_in_out`` curve by default.
    """
    ensure_ctx("frame_all_animated", ctx)
    camera = _get_camera(ctx)
    if camera is None:
        return {"status": "no_camera"}
    override_entities = ctx.get("entities")
    if override_entities is not None:
        try:
            entities = list(override_entities)
        except TypeError:
            return {"status": "error", "message": "entities not iterable"}
    else:
        scene = _get_scene(ctx)
        entities = _list_scene_entities(scene)
    if not entities:
        return {"status": "empty_scene"}
    duration = ctx.get("duration_ms", _DEFAULT_FRAME_ALL_DURATION_MS)
    easing = ctx.get("easing", _DEFAULT_EASING)
    animator = _resolve_animator(ctx)
    now = _resolve_now_ms(ctx)
    state = animator.frame_all_animated(
        camera, entities, duration_ms=duration, easing=easing, now_ms=now,
    )
    if state is None:
        return {"status": "no_positions"}
    return {
        "status": "tween_started",
        "target": list(state.to_pos or ()),
        "duration_ms": state.duration_ms,
        "easing": state.easing_kind,
        "count": len([e for e in entities if _entity_position(e) is not None]),
    }


__all__ = [
    "CameraTweenState",
    "CameraAnimator",
    "EasingCurves",
    "focus_on_selection_animated",
    "frame_all_animated",
    "get_module_animator",
    "_fb_tween_to_position",
    "_fb_focus_on_entity",
]
