"""View pixel-scale step actions — bump / drop the viewport scale factor.

Backs the ``view.increase_pixel_scale`` and ``view.decrease_pixel_scale``
:class:`~pharos_engine.tool_router.ToolAction` rows added by the SS1
STUB-triage sprint tick (round 20).

The pixel-scale factor controls how many screen pixels one *simulation*
pixel occupies — retro-pixel renderers pin this to an integer (1 / 2 / 3
/ 4) so sprites stay crisp when the viewport resizes. Aseprite, Godot's
2D pixel demo project, and every emulator ships a pair of hotkeys to step
this integer up or down without touching a settings dialog.

Distinct from Z7's viewport zoom (``view.zoom_in`` / ``view.zoom_out``
/ ``view.zoom_reset``) which multiplies a continuous camera-zoom factor:
these actions step an *integer* pixel-scale used by the framebuffer /
renderer chain. Zoom scales the projection; pixel-scale scales the
rasteriser output.

Shell state
-----------

* ``shell._pixel_scale`` — the current integer scale (default ``1``).
* ``shell._on_pixel_scale`` — optional callback, invoked with the new
  scale on every change so downstream renderer setup can rebuild its
  framebuffer.

Bounds
------

* Increase caps at ``max_scale`` (default 8).
* Decrease clamps at ``min_scale`` (default 1).

Return contract
---------------

* ``{"status": "changed", "target": "pixel_scale", "scale": N,
   "previous": M, "delta": +1 | -1}`` — value stepped.
* ``{"status": "clamped", "target": "pixel_scale", "scale": N,
   "previous": N, "bound": "max" | "min"}`` — already at the
  boundary; no change written.
* ``{"status": "no_shell"}`` — no shell reachable and no explicit
  ``scale`` seed in ``ctx``.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_ATTR = "_pixel_scale"
_HOOK_ATTR = "_on_pixel_scale"

_DEFAULT_MIN = 1
_DEFAULT_MAX = 8


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _read_scale(shell: Any, seed: Any) -> int:
    """Return the current pixel scale.

    Order of resolution: ``ctx["scale"]`` seed → ``shell._pixel_scale``
    → default ``1``.
    """
    if seed is not None:
        try:
            return max(_DEFAULT_MIN, int(seed))
        except (TypeError, ValueError):
            pass
    if shell is None:
        return _DEFAULT_MIN
    raw = getattr(shell, _ATTR, _DEFAULT_MIN)
    try:
        return max(_DEFAULT_MIN, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_MIN


def _write_scale(shell: Any, value: int) -> None:
    if shell is None:
        return
    try:
        setattr(shell, _ATTR, value)
    except Exception:  # noqa: BLE001
        return
    hook = getattr(shell, _HOOK_ATTR, None)
    if callable(hook):
        try:
            hook(value)
        except Exception:  # noqa: BLE001
            pass


def _resolve_bounds(ctx: dict[str, Any]) -> tuple[int, int]:
    """Return ``(min, max)`` bounds honouring caller overrides."""
    min_raw = ctx.get("min_scale", _DEFAULT_MIN)
    max_raw = ctx.get("max_scale", _DEFAULT_MAX)
    try:
        min_v = int(min_raw)
    except (TypeError, ValueError):
        min_v = _DEFAULT_MIN
    try:
        max_v = int(max_raw)
    except (TypeError, ValueError):
        max_v = _DEFAULT_MAX
    if max_v < min_v:
        max_v = min_v
    return (max(_DEFAULT_MIN, min_v), max(_DEFAULT_MIN, max_v))


def increase_pixel_scale(ctx: dict[str, Any]) -> dict[str, Any]:
    """Step ``shell._pixel_scale`` up by 1 (clamped at ``max_scale``).

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell — reads & writes the scale.
        * ``scale`` (optional int): explicit seed for the current value
          (tests use this to run headless without a shell).
        * ``max_scale`` (optional int, default 8): upper bound.
        * ``min_scale`` (optional int, default 1): lower bound (ignored
          by the increase path but honoured symmetrically).

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("increase_pixel_scale", ctx)
    shell = _get_shell(ctx)
    seed = ctx.get("scale")
    if shell is None and seed is None:
        return {"status": "no_shell"}
    lo, hi = _resolve_bounds(ctx)
    current = _read_scale(shell, seed)
    if current >= hi:
        return {
            "status": "clamped",
            "target": "pixel_scale",
            "scale": current,
            "previous": current,
            "bound": "max",
        }
    new = current + 1
    _write_scale(shell, new)
    return {
        "status": "changed",
        "target": "pixel_scale",
        "scale": new,
        "previous": current,
        "delta": 1,
    }


def decrease_pixel_scale(ctx: dict[str, Any]) -> dict[str, Any]:
    """Step ``shell._pixel_scale`` down by 1 (clamped at ``min_scale``).

    Parameters mirror :func:`increase_pixel_scale`.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("decrease_pixel_scale", ctx)
    shell = _get_shell(ctx)
    seed = ctx.get("scale")
    if shell is None and seed is None:
        return {"status": "no_shell"}
    lo, hi = _resolve_bounds(ctx)
    current = _read_scale(shell, seed)
    if current <= lo:
        return {
            "status": "clamped",
            "target": "pixel_scale",
            "scale": current,
            "previous": current,
            "bound": "min",
        }
    new = current - 1
    _write_scale(shell, new)
    return {
        "status": "changed",
        "target": "pixel_scale",
        "scale": new,
        "previous": current,
        "delta": -1,
    }


__all__ = ["increase_pixel_scale", "decrease_pixel_scale"]
