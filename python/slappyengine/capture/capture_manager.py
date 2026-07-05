"""
:mod:`slappyengine.capture.capture_manager` — high-level record()/screenshot().

Auto-detects the backend from the output extension:

* ``.mp4`` / ``.mov`` / ``.mkv`` / ``.webm``  -> :class:`VideoCapture`
* ``.gif``                                    -> :class:`GIFCapture`
* directory (no extension, or trailing ``/``) -> :class:`FrameDump`
* ``.png`` / ``.jpg`` / ``.jpeg`` / ``.bmp``  -> single-frame screenshot

Renderer contract
-----------------
The manager treats a *renderer* as any object exposing:

* ``begin_frame()`` — start a new frame (optional; only called if present)
* ``end_frame()``   — finish the frame (optional; only called if present)
* ``read_pixels() -> HxWx4 uint8 np.ndarray`` — mandatory

Additionally, if the renderer exposes ``.window_size = (w, h)`` we use it
to seed the capture's resolution when the caller doesn't pass one.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple, Union

import numpy as np

from .frame_dump import FrameDump
from .gif_capture import GIFCapture
from .video_capture import FFMPEG_AVAILABLE, FFmpegNotFoundError, VideoCapture


__all__ = ["CaptureManager", "CaptureResult"]


_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
_GIF_EXTS = {".gif"}
_IMG_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}


@dataclass
class CaptureResult:
    """Outcome of :meth:`CaptureManager.record` or ``capture_screenshot``."""

    path: Path
    format: str  # "mp4" | "gif" | "frames" | "png" | "jpg" | ...
    frames_written: int
    wall_time_seconds: float
    avg_fps: float
    warnings: List[str] = field(default_factory=list)


class CaptureManager:
    """Coordinate a capture backend against a renderer-like object."""

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    @staticmethod
    def detect_format(output_path: Union[str, Path]) -> str:
        """Return the backend key: ``"video"``, ``"gif"``, ``"frames"``, or ``"image"``.

        A path with no extension (or an existing directory) is treated as
        a frame-dump target.
        """
        p = Path(output_path)
        # Explicit trailing separator or existing directory: frame dump.
        s = str(output_path)
        if s.endswith(("/", "\\")) or (p.exists() and p.is_dir()):
            return "frames"
        ext = p.suffix.lower()
        if ext in _VIDEO_EXTS:
            return "video"
        if ext in _GIF_EXTS:
            return "gif"
        if ext in _IMG_EXTS:
            return "image"
        if not ext:
            return "frames"
        raise ValueError(
            f"CaptureManager: cannot infer capture format from path {output_path!r}"
        )

    # ------------------------------------------------------------------
    # Renderer plumbing
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_resolution(
        renderer: Any, override: Optional[Tuple[int, int]]
    ) -> Tuple[int, int]:
        if override is not None:
            return int(override[0]), int(override[1])
        size = getattr(renderer, "window_size", None) or getattr(
            renderer, "resolution", None
        )
        if size is None:
            # Fall back to one probe frame.
            probe = np.asarray(renderer.read_pixels())
            if probe.ndim != 3 or probe.shape[2] != 4:
                raise ValueError(
                    "CaptureManager: renderer.read_pixels() returned a non-HxWx4 array"
                )
            return int(probe.shape[1]), int(probe.shape[0])
        return int(size[0]), int(size[1])

    @staticmethod
    def _render_one(renderer: Any) -> np.ndarray:
        if hasattr(renderer, "begin_frame"):
            renderer.begin_frame()
        if hasattr(renderer, "end_frame"):
            renderer.end_frame()
        pixels = renderer.read_pixels()
        return np.asarray(pixels)

    # ------------------------------------------------------------------
    # record()
    # ------------------------------------------------------------------
    def record(
        self,
        renderer: Any,
        output_path: Union[str, Path],
        *,
        frames: Optional[int] = None,
        seconds: Optional[float] = None,
        fps: int = 60,
        resolution: Optional[Tuple[int, int]] = None,
        codec: str = "h264",
        bitrate: str = "8M",
        loop: int = 0,
        on_frame_written: Optional[Callable[[int, Optional[int]], None]] = None,
    ) -> CaptureResult:
        """Record ``frames`` (or ``seconds * fps``) frames from *renderer*.

        Exactly one of ``frames`` or ``seconds`` must be provided.

        Parameters
        ----------
        renderer :
            Object with ``read_pixels()`` (and optionally ``begin_frame`` /
            ``end_frame``, ``window_size``).
        output_path :
            Destination. Extension picks the backend.
        frames, seconds :
            Duration. Provide one; the other is derived.
        fps :
            Playback frame rate (also used to derive ``frames`` from
            ``seconds``).
        resolution :
            Override the renderer's declared resolution.
        codec, bitrate :
            Forwarded to :class:`VideoCapture` when applicable.
        loop :
            Forwarded to :class:`GIFCapture`.
        on_frame_written :
            Optional callback ``(n, total_or_None) -> None`` fired after
            each frame is written. Exceptions in the callback are captured
            as :attr:`CaptureResult.warnings` — they do not stop capture.
        """
        if frames is None and seconds is None:
            raise ValueError(
                "CaptureManager.record: must pass frames= or seconds="
            )
        if frames is not None and seconds is not None:
            raise ValueError(
                "CaptureManager.record: pass frames= or seconds=, not both"
            )
        if seconds is not None:
            if seconds < 0:
                raise ValueError("CaptureManager.record: seconds must be >= 0")
            frames = int(round(seconds * fps))
        assert frames is not None  # for the type-checker
        if frames < 0:
            raise ValueError("CaptureManager.record: frames must be >= 0")

        kind = self.detect_format(output_path)
        if kind == "image":
            raise ValueError(
                "CaptureManager.record: single-image extension "
                f"({Path(output_path).suffix}) — call capture_screenshot() instead"
            )

        # Resolve resolution before spawning the backend — a probe frame
        # may be needed and we want any errors surfaced before we spin up
        # FFmpeg.
        res = self._resolve_resolution(renderer, resolution)

        warnings: List[str] = []
        backend: Any
        if kind == "video":
            if not FFMPEG_AVAILABLE:
                raise FFmpegNotFoundError(
                    "CaptureManager.record: video output requested but no "
                    "FFmpeg backend is available. Install imageio-ffmpeg or ffmpeg."
                )
            backend = VideoCapture(
                output_path,
                resolution=res,
                fps=fps,
                codec=codec,
                bitrate=bitrate,
            )
            fmt_label = Path(output_path).suffix.lower().lstrip(".") or "mp4"
        elif kind == "gif":
            backend = GIFCapture(output_path, resolution=res, fps=fps, loop=loop)
            fmt_label = "gif"
            warnings.extend(backend.warnings)
        else:  # "frames"
            backend = FrameDump(output_path, resolution=res, fps=fps)
            fmt_label = "frames"

        # ------------------------------------------------------------------
        # Drive the capture loop.
        # ------------------------------------------------------------------
        wall_start_ns = time.perf_counter_ns()
        frames_written = 0
        backend.begin()
        try:
            for i in range(frames):
                pixels = self._render_one(renderer)
                backend.write_frame(pixels)
                frames_written += 1
                if on_frame_written is not None:
                    try:
                        on_frame_written(frames_written, frames)
                    except Exception as exc:  # noqa: BLE001
                        warnings.append(
                            f"on_frame_written callback raised: {exc!r}"
                        )
        finally:
            backend.close()

        wall_ns = time.perf_counter_ns() - wall_start_ns
        wall_s = wall_ns / 1e9
        avg_fps = frames_written / wall_s if wall_s > 0 else 0.0

        return CaptureResult(
            path=Path(output_path),
            format=fmt_label,
            frames_written=frames_written,
            wall_time_seconds=wall_s,
            avg_fps=avg_fps,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # capture_screenshot()
    # ------------------------------------------------------------------
    def capture_screenshot(
        self,
        renderer: Any,
        output_path: Union[str, Path],
        *,
        resolution: Optional[Tuple[int, int]] = None,
    ) -> CaptureResult:
        """Render a single frame and save it as a PNG (or JPEG/BMP)."""
        try:
            from PIL import Image
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "capture_screenshot: Pillow (PIL) is required"
            ) from exc

        path = Path(output_path)
        ext = path.suffix.lower()
        if ext == "":
            # Default to PNG when no extension is given.
            path = path.with_suffix(".png")
            ext = ".png"
        if ext not in _IMG_EXTS:
            raise ValueError(
                f"capture_screenshot: {ext!r} is not a supported image extension"
            )

        # Resolution is needed only to validate the frame shape; the
        # actual bitmap is what read_pixels returns.
        _ = self._resolve_resolution(renderer, resolution)
        wall_start_ns = time.perf_counter_ns()
        pixels = np.asarray(self._render_one(renderer))
        if pixels.ndim != 3 or pixels.shape[2] != 4:
            raise ValueError(
                "capture_screenshot: renderer.read_pixels() must return HxWx4 uint8"
            )
        if pixels.dtype != np.uint8:
            pixels = pixels.astype(np.uint8, copy=False)

        path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.fromarray(pixels, mode="RGBA")
        # JPEG cannot hold alpha; drop it.
        if ext in {".jpg", ".jpeg"}:
            img = img.convert("RGB")
        img.save(path)

        wall_s = (time.perf_counter_ns() - wall_start_ns) / 1e9
        return CaptureResult(
            path=path,
            format=ext.lstrip("."),
            frames_written=1,
            wall_time_seconds=wall_s,
            avg_fps=1.0 / wall_s if wall_s > 0 else 0.0,
            warnings=[],
        )
