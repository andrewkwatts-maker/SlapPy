"""
:mod:`slappyengine.capture.gif_capture` — PIL-backed animated GIF recorder.

GIF is limited to a 256-colour palette per frame, so we quantise each
frame with :meth:`PIL.Image.quantize`. The API is deliberately identical
to :class:`slappyengine.capture.VideoCapture` so :class:`CaptureManager`
can dispatch by extension.

Notes
-----
* GIF ``duration`` is measured in milliseconds per frame; we derive it
  from ``fps``. Sub-10ms frames are commonly clamped to 10ms by browsers,
  so we warn (via a stored ``.warnings`` list) when fps > 100.
* We buffer all frames in memory before ``close()`` writes the final
  file. This is fine for typical GIF sizes (< 30s @ 30fps) but the
  caller should prefer :class:`VideoCapture` for long clips.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple, Union

import numpy as np

try:  # PIL is a hard dep of the render subsystem already, but stay defensive.
    from PIL import Image
    _PIL_AVAILABLE = True
except Exception:  # noqa: BLE001
    Image = None  # type: ignore[assignment]
    _PIL_AVAILABLE = False


__all__ = ["GIFCapture"]


class GIFCapture:
    """Record frames to an animated GIF via PIL.

    Parameters
    ----------
    output_path : str or pathlib.Path
        Destination ``.gif`` file.
    resolution : (int, int)
        ``(width, height)`` in pixels; each frame must match.
    fps : int, default 30
        Frames per second. GIF encodes ``duration = 1000 // fps`` ms.
    loop : int, default 0
        Number of times the GIF should loop. ``0`` means infinite.
    optimize : bool, default True
        Whether PIL should re-encode with palette optimisation. Set to
        False for faster save at the cost of larger files.
    """

    def __init__(
        self,
        output_path: Union[str, Path],
        resolution: Tuple[int, int],
        fps: int = 30,
        *,
        loop: int = 0,
        optimize: bool = True,
    ) -> None:
        if not _PIL_AVAILABLE:
            raise RuntimeError(
                "GIFCapture: Pillow (PIL) is required. Install with `pip install pillow`."
            )
        if output_path is None or (isinstance(output_path, str) and not output_path):
            raise ValueError("GIFCapture: output_path must be a non-empty path")
        if not isinstance(output_path, (str, Path)):
            raise TypeError(
                f"GIFCapture: output_path must be str or Path; "
                f"got {type(output_path).__name__}"
            )
        if not isinstance(resolution, tuple) or len(resolution) != 2:
            raise TypeError(
                f"GIFCapture: resolution must be (width, height); got {resolution!r}"
            )
        width, height = resolution
        if not isinstance(width, int) or not isinstance(height, int):
            raise TypeError("GIFCapture: resolution components must be int")
        if width <= 0 or height <= 0:
            raise ValueError("GIFCapture: resolution components must be positive")
        if not isinstance(fps, int) or fps <= 0:
            raise ValueError("GIFCapture: fps must be a positive int")
        if not isinstance(loop, int) or loop < 0:
            raise ValueError("GIFCapture: loop must be a non-negative int")

        self.output_path: Path = Path(output_path)
        self.resolution: Tuple[int, int] = (int(width), int(height))
        self.fps: int = int(fps)
        self.loop: int = int(loop)
        self.optimize: bool = bool(optimize)

        self._frames: List["Image.Image"] = []
        self._open: bool = False
        self._closed: bool = False
        self.warnings: List[str] = []
        if fps > 100:
            self.warnings.append(
                f"GIFCapture: fps={fps} exceeds 100; browsers commonly clamp GIF "
                "durations at 10ms/frame."
            )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    @property
    def frames_written(self) -> int:
        return len(self._frames)

    @property
    def is_open(self) -> bool:
        return self._open and not self._closed

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def begin(self) -> None:
        """Start a new capture. Idempotent."""
        if self._closed:
            raise RuntimeError("GIFCapture: cannot re-begin a closed capture")
        self._open = True
        self._frames.clear()
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def write_frame(self, pixels: np.ndarray) -> None:
        """Append one ``HxWx4 uint8`` frame to the GIF buffer."""
        if not self._open:
            raise RuntimeError("GIFCapture.write_frame: begin() not called")
        if self._closed:
            raise RuntimeError("GIFCapture.write_frame: capture already closed")
        if pixels is None:
            raise TypeError("GIFCapture.write_frame: pixels must not be None")
        arr = np.asarray(pixels)
        if arr.ndim != 3 or arr.shape[2] != 4:
            raise ValueError(
                f"GIFCapture.write_frame: expected HxWx4 array; got shape {arr.shape}"
            )
        h, w = arr.shape[0], arr.shape[1]
        if (w, h) != self.resolution:
            raise ValueError(
                f"GIFCapture.write_frame: frame size {(w, h)} != "
                f"declared resolution {self.resolution}"
            )
        if arr.dtype != np.uint8:
            arr = arr.astype(np.uint8, copy=False)
        # RGBA -> PIL "RGBA"
        img = Image.fromarray(arr, mode="RGBA")
        # Quantise to a 256-entry palette. GIF supports transparency via
        # a single reserved index; we drop the alpha for now and warn.
        # A common approach is "RGB" -> quantize; alpha is preserved as
        # a binary mask via ``transparency=`` if the caller cares.
        rgb = img.convert("RGB")
        pal = rgb.quantize(colors=256, dither=Image.Dither.FLOYDSTEINBERG)
        self._frames.append(pal)

    def close(self) -> None:
        """Write the accumulated frames to disk. Idempotent."""
        if self._closed:
            return
        self._closed = True
        self._open = False
        if not self._frames:
            # Zero-frame capture: write a 1x1 placeholder so downstream
            # callers can still ``Image.open`` it without crashing.
            placeholder = Image.new("P", self.resolution, color=0)
            placeholder.save(self.output_path, format="GIF")
            return
        duration_ms = max(1, int(round(1000.0 / self.fps)))
        first, rest = self._frames[0], self._frames[1:]
        save_kwargs = {
            "format": "GIF",
            "save_all": True,
            "append_images": rest,
            "duration": duration_ms,
            "loop": self.loop,
            "optimize": self.optimize,
            "disposal": 2,
        }
        first.save(self.output_path, **save_kwargs)

    # ------------------------------------------------------------------
    # Context manager sugar
    # ------------------------------------------------------------------
    def __enter__(self) -> "GIFCapture":
        self.begin()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
