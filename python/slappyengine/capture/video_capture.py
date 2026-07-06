"""
:mod:`slappyengine.capture.video_capture` — FFmpeg-backed MP4/MOV recorder.

The class :class:`VideoCapture` spawns an ``ffmpeg`` subprocess and pipes
raw RGBA frames into its ``stdin``. FFmpeg does the H.264 / HEVC / ProRes
encoding work.

Backends (probed in order):

1. ``imageio-ffmpeg`` — bundled binary, no PATH requirement. Preferred
   because it works on developer machines out of the box.
2. System ``ffmpeg`` — resolved via :func:`shutil.which`. Used on CI
   where FFmpeg is installed system-wide.

Missing both -> :class:`FFmpegNotFoundError`. Callers can query the
module-level :data:`FFMPEG_AVAILABLE` flag before instantiating so tests
can soft-skip.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple, Union

import numpy as np


__all__ = [
    "FFMPEG_AVAILABLE",
    "FFmpegNotFoundError",
    "VideoCapture",
    "get_ffmpeg_executable",
]


class FFmpegNotFoundError(RuntimeError):
    """Raised when neither ``imageio-ffmpeg`` nor a system ``ffmpeg`` are usable."""


def _probe_imageio_ffmpeg() -> Optional[str]:
    """Return the imageio-ffmpeg bundled binary path or ``None`` if absent."""
    try:
        import imageio_ffmpeg  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 — any import failure disqualifies the backend
        return None
    try:
        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:  # noqa: BLE001
        return None


def _probe_system_ffmpeg() -> Optional[str]:
    """Return the system ``ffmpeg`` binary path or ``None`` if absent."""
    return shutil.which("ffmpeg")


def get_ffmpeg_executable() -> Optional[str]:
    """Return the resolved FFmpeg binary path, preferring ``imageio-ffmpeg``.

    Returns ``None`` when no backend is usable — callers should raise
    :class:`FFmpegNotFoundError` in that case (or skip a test).
    """
    return _probe_imageio_ffmpeg() or _probe_system_ffmpeg()


#: ``True`` when at least one FFmpeg backend is importable/discoverable.
#: Computed at import time; tests can gate ``pytest.skip`` on it.
FFMPEG_AVAILABLE: bool = get_ffmpeg_executable() is not None


# Codec -> FFmpeg encoder name. We keep the mapping tiny and predictable;
# advanced users can pass an FFmpeg encoder string directly.
_CODEC_ALIASES = {
    "h264": "libx264",
    "h.264": "libx264",
    "avc": "libx264",
    "hevc": "libx265",
    "h265": "libx265",
    "h.265": "libx265",
    "prores": "prores_ks",
    "vp9": "libvpx-vp9",
    "av1": "libaom-av1",
}


class VideoCapture:
    """Record frames to an MP4/MOV file via an FFmpeg subprocess.

    Parameters
    ----------
    output_path : str or pathlib.Path
        Destination file. Extension typically ``.mp4`` or ``.mov``.
    resolution : (int, int)
        ``(width, height)`` in pixels. Frames written via
        :meth:`write_frame` must match.
    fps : int, default 60
        Frames per second the encoder should tag on the output.
    codec : str, default ``"h264"``
        Human-friendly alias resolved via :data:`_CODEC_ALIASES`; pass an
        FFmpeg encoder name (``"libx264"``, ``"libx265"``, ...) for
        direct control.
    bitrate : str, default ``"8M"``
        FFmpeg-compatible bitrate string.
    pixel_format : str, default ``"yuv420p"``
        Output pixel format — ``yuv420p`` is the most compatible.

    Lifecycle
    ---------
    ``begin()`` -> ``write_frame(pixels)`` xN -> ``close()``.

    ``write_frame`` accepts ``HxWx4 uint8`` (RGBA). RGBA is written to
    FFmpeg's stdin at ``pix_fmt=rgba`` and FFmpeg transcodes to the
    requested output pixel format.
    """

    def __init__(
        self,
        output_path: Union[str, Path],
        resolution: Tuple[int, int],
        fps: int = 60,
        codec: str = "h264",
        bitrate: str = "8M",
        *,
        pixel_format: str = "yuv420p",
    ) -> None:
        if output_path is None or (isinstance(output_path, str) and not output_path):
            raise ValueError("VideoCapture: output_path must be a non-empty path")
        if not isinstance(output_path, (str, Path)):
            raise TypeError(
                f"VideoCapture: output_path must be str or Path; "
                f"got {type(output_path).__name__}"
            )
        if not isinstance(resolution, tuple) or len(resolution) != 2:
            raise TypeError(
                f"VideoCapture: resolution must be (width, height); got {resolution!r}"
            )
        width, height = resolution
        if not isinstance(width, int) or not isinstance(height, int):
            raise TypeError("VideoCapture: resolution components must be int")
        if width <= 0 or height <= 0:
            raise ValueError("VideoCapture: resolution components must be positive")
        if not isinstance(fps, int) or fps <= 0:
            raise ValueError("VideoCapture: fps must be a positive int")

        self.output_path: Path = Path(output_path)
        self.resolution: Tuple[int, int] = (int(width), int(height))
        self.fps: int = int(fps)
        self.codec: str = str(codec)
        self.bitrate: str = str(bitrate)
        self.pixel_format: str = str(pixel_format)

        self._proc: Optional[subprocess.Popen] = None
        self._frames_written: int = 0
        self._closed: bool = False
        self._stderr_tail: str = ""

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    @property
    def frames_written(self) -> int:
        """Number of frames pushed to FFmpeg's stdin so far."""
        return self._frames_written

    @property
    def is_open(self) -> bool:
        """``True`` between ``begin()`` and ``close()``."""
        return self._proc is not None and not self._closed

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def begin(self) -> None:
        """Spawn the FFmpeg subprocess. Idempotent — second call is a no-op."""
        if self._proc is not None:
            return
        exe = get_ffmpeg_executable()
        if exe is None:
            raise FFmpegNotFoundError(
                "VideoCapture: no FFmpeg backend found. Install "
                "'imageio-ffmpeg' (pip install imageio-ffmpeg) or make "
                "sure the 'ffmpeg' binary is on PATH."
            )
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        encoder = _CODEC_ALIASES.get(self.codec.lower(), self.codec)
        w, h = self.resolution
        cmd = [
            exe,
            "-y",
            "-loglevel", "error",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{w}x{h}",
            "-pix_fmt", "rgba",
            "-r", str(self.fps),
            "-i", "-",
            "-an",
            "-vcodec", encoder,
            "-pix_fmt", self.pixel_format,
            "-b:v", self.bitrate,
            "-r", str(self.fps),
            str(self.output_path),
        ]

        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
        self._closed = False
        self._frames_written = 0

    def write_frame(self, pixels: np.ndarray) -> None:
        """Push one ``HxWx4 uint8`` RGBA frame to FFmpeg's stdin.

        Raises
        ------
        RuntimeError
            If called before :meth:`begin` or after :meth:`close`.
        ValueError
            If ``pixels`` does not match the declared resolution or dtype.
        """
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("VideoCapture.write_frame: begin() not called")
        if self._closed:
            raise RuntimeError("VideoCapture.write_frame: capture already closed")
        if pixels is None:
            raise TypeError("VideoCapture.write_frame: pixels must not be None")

        arr = np.asarray(pixels)
        if arr.ndim != 3 or arr.shape[2] != 4:
            raise ValueError(
                f"VideoCapture.write_frame: expected HxWx4 array; got shape {arr.shape}"
            )
        h, w = arr.shape[0], arr.shape[1]
        if (w, h) != self.resolution:
            raise ValueError(
                f"VideoCapture.write_frame: frame size {(w, h)} != "
                f"declared resolution {self.resolution}"
            )
        if arr.dtype != np.uint8:
            arr = arr.astype(np.uint8, copy=False)
        if not arr.flags["C_CONTIGUOUS"]:
            arr = np.ascontiguousarray(arr)
        try:
            self._proc.stdin.write(arr.tobytes())
        except BrokenPipeError as exc:
            # FFmpeg died. Drain stderr for diagnostics.
            self._drain_stderr()
            raise RuntimeError(
                f"VideoCapture.write_frame: FFmpeg pipe closed early. "
                f"stderr tail: {self._stderr_tail}"
            ) from exc
        self._frames_written += 1

    def close(self) -> None:
        """Flush FFmpeg's stdin and wait for the encoder to finish.

        Idempotent — calling twice is safe.
        """
        if self._closed:
            return
        self._closed = True
        if self._proc is None:
            return
        try:
            if self._proc.stdin is not None:
                try:
                    self._proc.stdin.close()
                except BrokenPipeError:
                    pass
            self._drain_stderr()
            self._proc.wait(timeout=30)
        finally:
            self._proc = None

    # ------------------------------------------------------------------
    # Context manager sugar
    # ------------------------------------------------------------------
    def __enter__(self) -> "VideoCapture":
        self.begin()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _drain_stderr(self) -> None:
        """Read whatever's queued on FFmpeg's stderr without blocking indefinitely."""
        if self._proc is None or self._proc.stderr is None:
            return
        try:
            # Non-blocking read: close stdin above so FFmpeg exits, then wait.
            data = self._proc.stderr.read()
            if data:
                text = data.decode("utf-8", errors="replace")
                # Keep only the tail so we don't hold megabytes.
                self._stderr_tail = text[-2048:]
        except Exception:  # noqa: BLE001 — diagnostics only
            pass
