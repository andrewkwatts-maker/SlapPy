"""Video capture helper.

The :class:`VideoWriter` writes a sequence of RGB(A) frames to disk.  When
``imageio-ffmpeg`` (or a system ``ffmpeg`` on ``PATH``) is available it emits a
true MP4; otherwise it transparently falls back to an animated GIF and emits a
``RuntimeWarning`` so the caller knows what is going on.

Detection order
---------------

1.  ``import imageio_ffmpeg`` (preferred — vendored binary, no PATH setup).
2.  ``shutil.which("ffmpeg")`` (system-installed ffmpeg on PATH).
3.  Fallback: GIF via :mod:`imageio` (always available because ``imageio`` is
    a dependency of this project's image stack).

Use :meth:`VideoWriter.ffmpeg_available` to pre-check without instantiating
the writer.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, Union

PathLike = Union[str, "os.PathLike[str]"]

INSTALL_HINT = "pip install imageio-ffmpeg"
FALLBACK_WARNING = (
    f"ffmpeg not available - falling back to GIF. Install with: {INSTALL_HINT}"
)


def _try_import_imageio_ffmpeg() -> bool:
    """Return True iff ``imageio_ffmpeg`` is importable AND can locate a binary."""
    try:
        import imageio_ffmpeg  # type: ignore[import-not-found]
    except Exception:
        return False
    # imageio_ffmpeg ships its own binary; confirm it can be located.
    try:
        path = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return False
    return bool(path) and os.path.exists(path)


def _try_system_ffmpeg() -> Optional[str]:
    """Return path to a system ``ffmpeg`` on PATH, or None."""
    return shutil.which("ffmpeg")


class VideoWriter:
    """Frame-by-frame video writer with graceful MP4 -> GIF fallback.

    Parameters
    ----------
    path:
        Output file. Extension determines preferred format (``.mp4``,
        ``.gif``).  If MP4 is requested but ffmpeg is unavailable the
        extension is rewritten to ``.gif`` and a warning is issued.
    fps:
        Frames per second.
    codec:
        ffmpeg codec name (default ``"libx264"``).  Ignored for GIF output.
    quality:
        imageio quality knob (0-10).  Higher is better, larger files.
    try_install_ffmpeg:
        If True and ``imageio_ffmpeg`` is not importable, attempt
        ``python -m pip install imageio-ffmpeg`` once before falling back.
        Off by default to avoid surprise installs.
    """

    def __init__(
        self,
        path: PathLike,
        fps: int = 30,
        codec: str = "libx264",
        quality: int = 8,
        try_install_ffmpeg: bool = False,
    ) -> None:
        self._requested_path = Path(path)
        self.fps = int(fps)
        self.codec = codec
        self.quality = int(quality)
        self._writer: Any = None
        self._closed = False

        if try_install_ffmpeg and not self.ffmpeg_available():
            self._attempt_install()

        wants_mp4 = self._requested_path.suffix.lower() in {".mp4", ".m4v", ".mov"}
        if wants_mp4 and not self.ffmpeg_available():
            warnings.warn(FALLBACK_WARNING, RuntimeWarning, stacklevel=2)
            self.path = self._requested_path.with_suffix(".gif")
            self._mode = "gif"
        elif wants_mp4:
            self.path = self._requested_path
            self._mode = "mp4"
        else:
            self.path = self._requested_path
            self._mode = "gif"

    # ------------------------------------------------------------------ #
    # detection
    # ------------------------------------------------------------------ #
    @classmethod
    def ffmpeg_available(cls) -> bool:
        """True iff we can emit an MP4 (either via imageio_ffmpeg or system ffmpeg)."""
        if _try_import_imageio_ffmpeg():
            return True
        if _try_system_ffmpeg() is not None:
            return True
        return False

    @classmethod
    def ffmpeg_source(cls) -> Optional[str]:
        """Return ``"imageio_ffmpeg"``, ``"system"``, or ``None``.

        Useful for diagnostics / docs.
        """
        if _try_import_imageio_ffmpeg():
            return "imageio_ffmpeg"
        if _try_system_ffmpeg() is not None:
            return "system"
        return None

    # ------------------------------------------------------------------ #
    # writing
    # ------------------------------------------------------------------ #
    def _ensure_writer(self) -> Any:
        if self._writer is not None:
            return self._writer
        try:
            import imageio.v2 as imageio  # type: ignore[import-not-found]
        except Exception:
            import imageio  # type: ignore[import-not-found,no-redef]

        self.path.parent.mkdir(parents=True, exist_ok=True)

        if self._mode == "mp4":
            self._writer = imageio.get_writer(
                str(self.path),
                fps=self.fps,
                codec=self.codec,
                quality=self.quality,
                macro_block_size=None,
            )
        else:
            # GIF
            self._writer = imageio.get_writer(
                str(self.path),
                mode="I",
                fps=self.fps,
            )
        return self._writer

    def append(self, frame: Any) -> None:
        """Append a single RGB(A) frame (HxWx3 or HxWx4 ndarray-like)."""
        if self._closed:
            raise RuntimeError("VideoWriter already closed")
        self._ensure_writer().append_data(frame)

    # convenience alias used by various callers
    write_frame = append

    def extend(self, frames: Iterable[Any]) -> None:
        for f in frames:
            self.append(f)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._writer is not None:
            try:
                self._writer.close()
            finally:
                self._writer = None

    # ------------------------------------------------------------------ #
    # context manager
    # ------------------------------------------------------------------ #
    def __enter__(self) -> "VideoWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - best effort
        try:
            self.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    @staticmethod
    def _attempt_install() -> bool:
        """Try ``python -m pip install imageio-ffmpeg``.  Returns True on success."""
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "imageio-ffmpeg"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            return False
        return _try_import_imageio_ffmpeg()
