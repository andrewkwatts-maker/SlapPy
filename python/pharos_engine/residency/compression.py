from __future__ import annotations
import numpy as np


def _validate_ndarray(name: str, fn: str, value) -> np.ndarray:
    """Refuse non-ndarray inputs at the boundary.

    ``compress_array(list_of_floats)`` used to die deep in ``.astype``
    with a baffling ``AttributeError``. Catching it here keeps the
    error message anchored at the public call site.
    """
    if not isinstance(value, np.ndarray):
        raise TypeError(
            f"{fn}: {name} must be a numpy.ndarray; got {type(value).__name__}"
        )
    return value


def _validate_bytes(name: str, fn: str, value) -> bytes:
    """Refuse non-bytes inputs (``bytearray`` allowed; ``memoryview`` allowed).

    Empty bytes are permitted — both lz4 and zlib round-trip ``b""`` cleanly
    and existing callers in :mod:`pharos_engine.residency.slap_format`
    serialise zero-length layer payloads.
    """
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError(
            f"{fn}: {name} must be bytes-like; got {type(value).__name__}"
        )
    return bytes(value)


def compress_array(arr: np.ndarray) -> bytes:
    """Compress an ``np.ndarray`` (float32-cast) with lz4 / zlib fallback."""
    _validate_ndarray("arr", "compress_array", arr)
    raw = arr.astype(np.float32).tobytes()
    try:
        import lz4.frame
        return lz4.frame.compress(raw, compression_level=0)
    except ImportError:
        import zlib
        return zlib.compress(raw, level=1)


def decompress_array(data: bytes, shape: tuple[int, ...], dtype=np.float32) -> np.ndarray:
    """Inverse of :func:`compress_array`."""
    _validate_bytes("data", "decompress_array", data)
    if not isinstance(shape, (tuple, list)) or len(shape) == 0:
        raise TypeError(
            f"decompress_array: shape must be a non-empty tuple of ints; "
            f"got {type(shape).__name__}"
        )
    try:
        import lz4.frame
        raw = lz4.frame.decompress(data)
    except ImportError:
        import zlib
        raw = zlib.decompress(data)
    return np.frombuffer(raw, dtype=dtype).reshape(shape)


def compress_raw(data: bytes) -> bytes:
    """Compress arbitrary bytes with lz4 / zlib fallback."""
    _validate_bytes("data", "compress_raw", data)
    try:
        import lz4.frame
        return lz4.frame.compress(data, compression_level=0)
    except ImportError:
        import zlib
        return zlib.compress(data, level=1)


def decompress_raw(data: bytes) -> bytes:
    """Inverse of :func:`compress_raw`."""
    _validate_bytes("data", "decompress_raw", data)
    try:
        import lz4.frame
        return lz4.frame.decompress(data)
    except ImportError:
        import zlib
        return zlib.decompress(data)
