from __future__ import annotations
import numpy as np


def compress_array(arr: np.ndarray) -> bytes:
    raw = arr.astype(np.float32).tobytes()
    try:
        import lz4.frame
        return lz4.frame.compress(raw, compression_level=0)
    except ImportError:
        import zlib
        return zlib.compress(raw, level=1)


def decompress_array(data: bytes, shape: tuple[int, ...], dtype=np.float32) -> np.ndarray:
    try:
        import lz4.frame
        raw = lz4.frame.decompress(data)
    except ImportError:
        import zlib
        raw = zlib.decompress(data)
    return np.frombuffer(raw, dtype=dtype).reshape(shape)


def compress_raw(data: bytes) -> bytes:
    try:
        import lz4.frame
        return lz4.frame.compress(data, compression_level=0)
    except ImportError:
        import zlib
        return zlib.compress(data, level=1)


def decompress_raw(data: bytes) -> bytes:
    try:
        import lz4.frame
        return lz4.frame.decompress(data)
    except ImportError:
        import zlib
        return zlib.decompress(data)
