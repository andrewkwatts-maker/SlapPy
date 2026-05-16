from __future__ import annotations
from pathlib import Path
import numpy as np

def extract_frames(video_path: str | Path, max_frames: int = 256) -> list[np.ndarray]:
    """Extract frames from a video file as RGBA numpy arrays.

    Requires [extra: video] — pip install slappyengine[video]
    """
    try:
        import av
    except ImportError as e:
        raise ImportError(
            "Video import requires: pip install slappyengine[video]"
        ) from e

    frames = []
    with av.open(str(video_path)) as container:
        for i, frame in enumerate(container.decode(video=0)):
            if i >= max_frames:
                break
            img = frame.to_image().convert("RGBA")
            frames.append(np.asarray(img, dtype=np.uint8))
    return frames
