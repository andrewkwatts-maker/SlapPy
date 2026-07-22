"""PNG / JPEG / WebP / TGA texture loader via PIL.

Returns an :class:`ImportResult` with ``kind="texture"``. The pixel
buffer is a ``numpy.ndarray`` of shape ``(H, W, C)`` and dtype
``uint8`` — ready to hand off to :class:`pharos_engine.gpu.TextureManager`
without further conversion.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from .import_result import ImportDependencyError, ImportResult, TextureData


def _import_pil():
    """Soft-import PIL. Raise :class:`ImportDependencyError` if missing."""
    try:
        from PIL import Image  # noqa: PLC0415
        return Image
    except ImportError as e:  # pragma: no cover - PIL is a base install dep
        raise ImportDependencyError(
            "PIL/Pillow is required for texture import. "
            "Install with: pip install Pillow"
        ) from e


def import_texture(path: str | Path) -> ImportResult:
    """Load a texture file into an :class:`ImportResult`.

    Supports .png, .jpg, .jpeg, .webp, .tga (anything PIL can decode).
    RGB images produce ``TextureData(channels=3, format="RGB")``,
    RGBA images produce ``TextureData(channels=4, format="RGBA")``,
    single-channel images produce ``TextureData(channels=1,
    format="grayscale")``.
    """
    Image = _import_pil()
    path = Path(path)
    t0 = time.perf_counter()

    img = Image.open(str(path))
    mode = img.mode

    # Normalise mode → (target_mode, channels, format_str)
    if mode == "RGBA" or mode == "LA" or "A" in mode:
        if mode != "RGBA":
            img = img.convert("RGBA")
        channels = 4
        fmt = "RGBA"
    elif mode in ("L", "1", "I", "F"):
        img = img.convert("L")
        channels = 1
        fmt = "grayscale"
    else:
        # RGB / P / CMYK / YCbCr etc.
        img = img.convert("RGB")
        channels = 3
        fmt = "RGB"

    pixels = np.asarray(img, dtype=np.uint8)
    if pixels.ndim == 2 and channels != 1:
        # Shouldn't happen given the mode branch above, but guard.
        channels = 1
        fmt = "grayscale"

    height = int(img.height)
    width = int(img.width)

    tex = TextureData(
        pixels=pixels,
        width=width,
        height=height,
        channels=channels,
        format=fmt,
    )
    dt_ms = (time.perf_counter() - t0) * 1000.0
    return ImportResult(
        kind="texture",
        textures=[tex],
        metadata={
            "source_path": str(path),
            "importer_used": "import_texture",
            "load_ms": dt_ms,
            "width": width,
            "height": height,
            "channels": channels,
            "format": fmt,
        },
    )
