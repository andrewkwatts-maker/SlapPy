"""
:mod:`pharos_engine.capture.frame_dump` — per-frame PNG dumper.

Zero-dependency fallback: writes each frame as a numbered PNG file into
a target directory. Useful when neither FFmpeg nor a GIF is desired
(e.g. per-frame regression baselines).
"""
from __future__ import annotations

from pathlib import Path
from typing import Tuple, Union

import numpy as np

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except Exception:  # noqa: BLE001
    Image = None  # type: ignore[assignment]
    _PIL_AVAILABLE = False


__all__ = ["FrameDump"]


class FrameDump:
    """Write each captured frame as ``frame_00000.png`` into a directory.

    Parameters
    ----------
    output_path : str or pathlib.Path
        Destination directory. Created if missing.
    resolution : (int, int)
        ``(width, height)`` — each frame must match.
    fps : int, default 60
        Kept for interface parity with :class:`VideoCapture` /
        :class:`GIFCapture`; recorded into an accompanying ``manifest.txt``.
    prefix : str, default ``"frame_"``
        File-name prefix. Frames are numbered ``prefix + 5-digit-index + .png``.
    digits : int, default 5
        Zero-padding width for the frame index.
    """

    def __init__(
        self,
        output_path: Union[str, Path],
        resolution: Tuple[int, int],
        fps: int = 60,
        *,
        prefix: str = "frame_",
        digits: int = 5,
    ) -> None:
        if not _PIL_AVAILABLE:
            raise RuntimeError(
                "FrameDump: Pillow (PIL) is required. Install with `pip install pillow`."
            )
        if not isinstance(resolution, tuple) or len(resolution) != 2:
            raise TypeError(
                f"FrameDump: resolution must be (width, height); got {resolution!r}"
            )
        width, height = resolution
        if not isinstance(width, int) or not isinstance(height, int):
            raise TypeError("FrameDump: resolution components must be int")
        if width <= 0 or height <= 0:
            raise ValueError("FrameDump: resolution components must be positive")
        if not isinstance(fps, int) or fps <= 0:
            raise ValueError("FrameDump: fps must be a positive int")
        if not isinstance(digits, int) or digits < 1:
            raise ValueError("FrameDump: digits must be >= 1")
        if not isinstance(prefix, str):
            raise TypeError("FrameDump: prefix must be a str")

        self.output_path: Path = Path(output_path)
        self.resolution: Tuple[int, int] = (int(width), int(height))
        self.fps: int = int(fps)
        self.prefix: str = prefix
        self.digits: int = int(digits)

        self._frames_written: int = 0
        self._open: bool = False
        self._closed: bool = False

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    @property
    def frames_written(self) -> int:
        return self._frames_written

    @property
    def is_open(self) -> bool:
        return self._open and not self._closed

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def begin(self) -> None:
        if self._closed:
            raise RuntimeError("FrameDump: cannot re-begin a closed capture")
        self.output_path.mkdir(parents=True, exist_ok=True)
        self._open = True
        self._frames_written = 0

    def write_frame(self, pixels: np.ndarray) -> None:
        if not self._open:
            raise RuntimeError("FrameDump.write_frame: begin() not called")
        if self._closed:
            raise RuntimeError("FrameDump.write_frame: capture already closed")
        arr = np.asarray(pixels)
        if arr.ndim != 3 or arr.shape[2] != 4:
            raise ValueError(
                f"FrameDump.write_frame: expected HxWx4 array; got shape {arr.shape}"
            )
        h, w = arr.shape[0], arr.shape[1]
        if (w, h) != self.resolution:
            raise ValueError(
                f"FrameDump.write_frame: frame size {(w, h)} != "
                f"declared resolution {self.resolution}"
            )
        if arr.dtype != np.uint8:
            arr = arr.astype(np.uint8, copy=False)
        name = f"{self.prefix}{self._frames_written:0{self.digits}d}.png"
        Image.fromarray(arr, mode="RGBA").save(self.output_path / name, format="PNG")
        self._frames_written += 1

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._open = False
        # Drop a tiny manifest so post-hoc callers can recover fps + count.
        manifest = self.output_path / "manifest.txt"
        try:
            manifest.write_text(
                f"fps={self.fps}\n"
                f"frames={self._frames_written}\n"
                f"width={self.resolution[0]}\n"
                f"height={self.resolution[1]}\n"
                f"prefix={self.prefix}\n"
                f"digits={self.digits}\n",
                encoding="utf-8",
            )
        except OSError:
            # Manifest is a nice-to-have; do not fail close over it.
            pass

    # ------------------------------------------------------------------
    # Context manager sugar
    # ------------------------------------------------------------------
    def __enter__(self) -> "FrameDump":
        self.begin()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
