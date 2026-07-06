"""Capture actions — start / stop MP4 recording + one-shot screenshot.

Backs the ``capture.start_recording`` / ``capture.stop_recording`` /
``capture.screenshot`` :class:`~slappyengine.tool_router.ToolAction`
rows added by the MM6 STUB-triage sprint tick (round 14 after JJ6 +
KK7 + LL landings). Each helper delegates to the LL2
:mod:`slappyengine.capture` subpackage.

Design notes
------------

* Recording state is stashed on ``shell._capture_state`` as a small
  dict ``{"backend": VideoCapture, "path": Path, "started_at": float,
  "frames": int}`` so ``stop_recording`` can find it later. A duplicate
  ``start_recording`` call while a session is live returns
  ``{"status": "already_recording"}`` distinct from a fresh success so
  the toast can differentiate.
* ``stop_recording`` calls ``close()`` on the LL2 backend and clears the
  session. When no session is live it returns ``{"status":
  "not_recording"}`` so callers can hint at the missed toggle.
* ``screenshot`` is a *one-shot* — it does not touch the recording
  state. It uses ``CaptureManager.capture_screenshot`` for its PNG /
  JPG dispatch, so it round-trips the same resolver + Pillow surface as
  the demo tools.

All three helpers accept ``ctx["path"]`` (str or ``pathlib.Path``);
recording defaults to ``recordings/<timestamp>.mp4`` under the shell's
project root, screenshot defaults to ``screenshots/<timestamp>.png``.

Return contract
---------------

* ``{"status": "recording", "path": str, "resolution": (w, h),
   "fps": int, "backend": "video"}`` — recording started.
* ``{"status": "already_recording", "path": str}`` — a session is
  live; the caller must ``stop_recording`` first.
* ``{"status": "no_renderer"}`` — no renderer reachable from ``ctx``.
* ``{"status": "stopped", "path": str, "frames": int,
   "wall_time_seconds": float}`` — recording finalised.
* ``{"status": "not_recording"}`` — ``stop_recording`` called with no
  live session.
* ``{"status": "captured", "path": str, "format": "png"|"jpg"|...}``
  — screenshot saved.
* ``{"status": "capture_unavailable", "reason": str}`` — the LL2
  capture subpackage failed to import (soft-import gate).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ._ctx import ensure_ctx


_SESSION_ATTR = "_capture_state"
_DEFAULT_FPS = 60
_DEFAULT_RESOLUTION = (1280, 720)


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _get_renderer(ctx: dict[str, Any]) -> Any:
    """Same renderer resolver as :mod:`render_toggle_actions`."""
    override = ctx.get("renderer")
    if override is not None:
        return override
    shell = _get_shell(ctx)
    if shell is None:
        return None
    r = getattr(shell, "_renderer", None)
    if r is not None:
        return r
    panel = getattr(shell, "_viewport_panel", None)
    if panel is None:
        return None
    return getattr(panel, "_renderer", None) or getattr(panel, "renderer", None)


def _project_root(shell: Any) -> Path:
    """Best-effort project-root resolution used by default paths."""
    if shell is None:
        return Path(".").resolve()
    root = getattr(shell, "_project_root", None) or getattr(
        shell, "project_root", None,
    )
    if root is None:
        return Path(".").resolve()
    return Path(root)


def _default_path(shell: Any, subdir: str, ext: str) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    root = _project_root(shell)
    return root / subdir / f"capture_{stamp}{ext}"


def _resolve_path(ctx: dict[str, Any], subdir: str, ext: str) -> Path:
    raw = ctx.get("path")
    if raw is None:
        return _default_path(_get_shell(ctx), subdir, ext)
    return Path(raw)


def _resolve_resolution(
    ctx: dict[str, Any], renderer: Any,
) -> tuple[int, int]:
    """Pick ``(w, h)`` from ctx override → renderer probe → default."""
    override = ctx.get("resolution")
    if override is not None:
        try:
            return int(override[0]), int(override[1])
        except Exception:  # noqa: BLE001
            pass
    size = getattr(renderer, "window_size", None) or getattr(
        renderer, "resolution", None,
    )
    if size is not None:
        try:
            return int(size[0]), int(size[1])
        except Exception:  # noqa: BLE001
            pass
    return _DEFAULT_RESOLUTION


def _get_session(shell: Any) -> dict[str, Any] | None:
    if shell is None:
        return None
    return getattr(shell, _SESSION_ATTR, None)


def _set_session(shell: Any, session: dict[str, Any] | None) -> None:
    if shell is None:
        return
    try:
        setattr(shell, _SESSION_ATTR, session)
    except Exception:  # noqa: BLE001
        pass


def start_recording(ctx: dict[str, Any]) -> dict[str, Any]:
    """Start an LL2 :class:`VideoCapture` session against the current renderer.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``renderer`` / ``shell`` — resolved as elsewhere.
        * ``path`` (optional str/Path): output MP4. Default:
          ``recordings/capture_<timestamp>.mp4`` under the project root.
        * ``fps`` (optional int): playback frame rate. Default 60.
        * ``resolution`` (optional 2-tuple): overrides the renderer's
          declared size. Default: ``renderer.window_size`` or
          ``(1280, 720)``.
        * ``codec`` / ``bitrate`` (optional str): forwarded to
          :class:`VideoCapture`.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("start_recording", ctx)
    shell = _get_shell(ctx)
    renderer = _get_renderer(ctx)
    if renderer is None:
        return {"status": "no_renderer"}
    existing = _get_session(shell)
    if isinstance(existing, dict) and existing.get("backend") is not None:
        prev_path = existing.get("path")
        return {
            "status": "already_recording",
            "path": str(prev_path) if prev_path is not None else None,
        }
    try:
        from slappyengine.capture import (
            FFMPEG_AVAILABLE,
            FFmpegNotFoundError,
            VideoCapture,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "capture_unavailable",
            "reason": f"import failed: {exc!r}",
        }
    if not FFMPEG_AVAILABLE:
        return {
            "status": "capture_unavailable",
            "reason": "no FFmpeg backend (install imageio-ffmpeg or ffmpeg)",
        }
    path = _resolve_path(ctx, "recordings", ".mp4")
    resolution = _resolve_resolution(ctx, renderer)
    fps = int(ctx.get("fps") or _DEFAULT_FPS)
    codec = ctx.get("codec") or "h264"
    bitrate = ctx.get("bitrate") or "8M"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001
        pass
    try:
        backend = VideoCapture(
            path,
            resolution=resolution,
            fps=fps,
            codec=codec,
            bitrate=bitrate,
        )
    except FFmpegNotFoundError as exc:
        return {
            "status": "capture_unavailable",
            "reason": str(exc),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "capture_unavailable",
            "reason": f"VideoCapture init failed: {exc!r}",
        }
    # Best-effort ``begin()`` — some backends require it before
    # ``write_frame``. Missing method is a soft error.
    if hasattr(backend, "begin"):
        try:
            backend.begin()
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "capture_unavailable",
                "reason": f"VideoCapture.begin failed: {exc!r}",
            }
    session = {
        "backend": backend,
        "path": path,
        "started_at": time.perf_counter(),
        "frames": 0,
        "fps": fps,
        "resolution": resolution,
    }
    _set_session(shell, session)
    return {
        "status": "recording",
        "path": str(path),
        "resolution": resolution,
        "fps": fps,
        "backend": "video",
    }


def stop_recording(ctx: dict[str, Any]) -> dict[str, Any]:
    """Close the LL2 VideoCapture session started by :func:`start_recording`.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` — the session holder.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("stop_recording", ctx)
    shell = _get_shell(ctx)
    session = _get_session(shell)
    if not isinstance(session, dict) or session.get("backend") is None:
        return {"status": "not_recording"}
    backend = session.get("backend")
    path = session.get("path")
    frames = int(session.get("frames") or 0)
    started_at = session.get("started_at")
    if hasattr(backend, "close"):
        try:
            backend.close()
        except Exception as exc:  # noqa: BLE001
            # Even on close failure we clear the session so the shell
            # can retry — otherwise the "already recording" gate wedges.
            _set_session(shell, None)
            return {
                "status": "stopped_with_error",
                "path": str(path) if path is not None else None,
                "frames": frames,
                "error": repr(exc),
            }
    _set_session(shell, None)
    wall = 0.0
    if isinstance(started_at, (int, float)):
        wall = max(0.0, time.perf_counter() - float(started_at))
    return {
        "status": "stopped",
        "path": str(path) if path is not None else None,
        "frames": frames,
        "wall_time_seconds": wall,
    }


def screenshot(ctx: dict[str, Any]) -> dict[str, Any]:
    """One-shot LL2 :meth:`CaptureManager.capture_screenshot` fire.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``renderer`` / ``shell`` — resolved as elsewhere.
        * ``path`` (optional str/Path): output image. Default:
          ``screenshots/capture_<timestamp>.png`` under the project root.
        * ``resolution`` (optional 2-tuple): overrides the renderer's
          declared size.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("screenshot", ctx)
    renderer = _get_renderer(ctx)
    if renderer is None:
        return {"status": "no_renderer"}
    try:
        from slappyengine.capture import CaptureManager
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "capture_unavailable",
            "reason": f"import failed: {exc!r}",
        }
    path = _resolve_path(ctx, "screenshots", ".png")
    resolution_override = ctx.get("resolution")
    resolution: tuple[int, int] | None = None
    if resolution_override is not None:
        try:
            resolution = (
                int(resolution_override[0]),
                int(resolution_override[1]),
            )
        except Exception:  # noqa: BLE001
            resolution = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001
        pass
    manager = CaptureManager()
    try:
        result = manager.capture_screenshot(
            renderer, path, resolution=resolution,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "capture_unavailable",
            "reason": f"capture_screenshot failed: {exc!r}",
        }
    return {
        "status": "captured",
        "path": str(result.path),
        "format": result.format,
        "wall_time_seconds": result.wall_time_seconds,
    }


__all__ = [
    "start_recording",
    "stop_recording",
    "screenshot",
]
