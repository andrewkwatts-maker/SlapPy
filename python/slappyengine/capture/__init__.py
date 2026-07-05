"""
slappyengine.capture
====================

Record renderer output to MP4 / GIF / frame-sequence.

This subpackage was promoted to the engine API for Nova3D parity Sprint 15
(LL2) so that games, tutorials and CI can produce reproducible video
artefacts from any :class:`slappyengine.render.Renderer`-like object.

Public surface
--------------
- :class:`VideoCapture`   — MP4 / MOV via FFmpeg (soft-import of
  ``imageio-ffmpeg``, falls back to the system ``ffmpeg`` binary).
- :class:`GIFCapture`     — animated GIF via PIL (no FFmpeg dependency).
- :class:`FrameDump`      — per-frame PNG dump (zero deps beyond PIL/numpy).
- :class:`CaptureManager` — high-level ``record(renderer, path, ...)`` with
  format auto-detection, timing helpers, and progress callbacks.
- :class:`CaptureResult`  — dataclass returned by ``CaptureManager.record``.
- :data:`FFMPEG_AVAILABLE`     — ``True`` when the FFmpeg backend is usable.
- :func:`get_ffmpeg_executable` — resolved path or ``None``.

Design notes
------------
* All backends share the ``begin() / write_frame(pixels) / close()``
  lifecycle so tests + higher-level tools can treat them uniformly.
* ``pixels`` is always ``HxWx4 uint8`` (matches
  :meth:`slappyengine.render.NullRenderer.read_pixels`). RGB is derived
  by dropping the alpha channel; RGBA is preserved for GIF/PNG paths.
* FFmpeg is soft-imported. Missing binary raises a distinctive
  :class:`FFmpegNotFoundError` so tests can ``pytest.skip(...)`` cleanly.
* Cross-platform: paths go through :class:`pathlib.Path`, and the
  subprocess is spawned with ``creationflags=CREATE_NO_WINDOW`` on Windows
  so batch pipelines don't flash a console window.
"""
from __future__ import annotations

from .capture_manager import CaptureManager, CaptureResult
from .frame_dump import FrameDump
from .gif_capture import GIFCapture
from .video_capture import (
    FFMPEG_AVAILABLE,
    FFmpegNotFoundError,
    VideoCapture,
    get_ffmpeg_executable,
)

__all__ = [
    "CaptureManager",
    "CaptureResult",
    "FFMPEG_AVAILABLE",
    "FFmpegNotFoundError",
    "FrameDump",
    "GIFCapture",
    "VideoCapture",
    "get_ffmpeg_executable",
]
