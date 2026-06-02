"""Lazy video export helpers.

All heavy dependencies are imported inside the functions that need them so the
engine import surface stays small.  GIF export uses PIL (already an engine
dependency).  MP4 / WebM export requires the optional ``[video]`` extra:

    pip install slappyengine[video]

which pulls in ``imageio`` and ``imageio-ffmpeg``.  These are NOT installed by
default.
"""
from __future__ import annotations

from typing import Iterable, Sequence, Union
from pathlib import Path

# PIL.Image is forward-declared as Any so this module imports without PIL loaded.
ImageLike = "object"


def write_gif(
    frames: "Sequence[object]",
    out_path: "str | Path",
    fps: float = 30.0,
    loop: int = 0,
    colors: int = 128,
) -> Path:
    """Write a list of PIL Images to an animated GIF.

    Parameters
    ----------
    frames:
        Iterable of ``PIL.Image.Image`` instances (RGBA or RGB).  Empty input
        raises ``ValueError``.
    out_path:
        Destination ``.gif`` path.
    fps:
        Playback frames per second.  Duration per frame = ``1000 / fps`` ms.
    loop:
        ``0`` = loop forever, ``N`` = loop N times.
    colors:
        Palette size for the GIF quantiser (max 256).

    Returns
    -------
    Path
        Absolute path of the written file.
    """
    from PIL import Image  # lazy

    frame_list = list(frames)
    if not frame_list:
        raise ValueError("write_gif() requires at least one frame")

    palette_frames = [
        f.convert("P", palette=Image.ADAPTIVE, colors=colors)
        if f.mode != "P" else f
        for f in frame_list
    ]
    duration_ms = int(round(1000.0 / float(fps)))

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    palette_frames[0].save(
        out,
        save_all=True,
        append_images=palette_frames[1:],
        duration=duration_ms,
        loop=loop,
        disposal=2,
        optimize=False,
    )
    return out.resolve()


def write_mp4(
    frames: "Sequence[object]",
    out_path: "str | Path",
    fps: float = 30.0,
    quality: int = 7,
) -> Path:
    """Write a list of PIL Images to an MP4 (h264) via imageio.

    Requires the optional ``[video]`` extra.  Raises ``ImportError`` with an
    install hint when imageio is not available.

    Parameters
    ----------
    frames:
        Iterable of PIL Images (any mode; converted to RGB internally).
    out_path:
        Destination ``.mp4`` path.
    fps:
        Playback frames per second.
    quality:
        imageio-ffmpeg quality value (1=worst, 10=best).
    """
    try:
        import imageio.v3 as iio  # lazy
    except ImportError as e:
        raise ImportError(
            "MP4 export requires the [video] extra: pip install slappyengine[video]"
        ) from e

    import numpy as np  # lazy (already a deep engine dep, but keep local)

    frame_list = list(frames)
    if not frame_list:
        raise ValueError("write_mp4() requires at least one frame")
    rgb_arrays = [np.asarray(f.convert("RGB")) for f in frame_list]

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    iio.imwrite(
        out,
        rgb_arrays,
        fps=fps,
        codec="libx264",
        quality=quality,
    )
    return out.resolve()


def have_mp4_support() -> bool:
    """Return True when the [video] extra is installed (imageio importable)."""
    try:
        import imageio  # noqa: F401
        import imageio_ffmpeg  # noqa: F401
        return True
    except ImportError:
        return False
