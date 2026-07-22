"""Internal input-validation helpers for the ``topology`` public API.

Generic ``validate_non_negative_int`` lives in :mod:`pharos_engine._validation`
and is re-exported. Note: the previous local implementation accepted
``bool`` silently (``int(True)==1``); the shared validator refuses ``bool``
— that was a latent footgun.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from pharos_engine._validation import validate_non_negative_int


_INT_DTYPES = (np.int8, np.int16, np.int32, np.int64,
               np.uint8, np.uint16, np.uint32, np.uint64)


def validate_edges_array(fn: str, edges: Any, n_nodes: int) -> np.ndarray:
    """Verify ``edges`` is an ``(E, 2)`` integer numpy array with valid ids."""
    if not isinstance(edges, np.ndarray):
        raise TypeError(
            f"{fn}: edges must be a numpy ndarray; got {type(edges).__name__}"
        )
    if edges.dtype.kind not in ("i", "u"):
        raise TypeError(
            f"{fn}: edges must have integer dtype; got {edges.dtype}"
        )
    if edges.ndim != 2 or edges.shape[1] != 2:
        raise ValueError(
            f"{fn}: edges must be (E, 2); got shape {edges.shape}"
        )
    if edges.size > 0:
        emin = int(edges.min())
        emax = int(edges.max())
        if emin < 0:
            raise ValueError(
                f"{fn}: edges must be in [0, n_nodes); got minimum {emin}"
            )
        if emax >= n_nodes:
            raise ValueError(
                f"{fn}: edges must be in [0, n_nodes={n_nodes}); "
                f"got maximum {emax}"
            )
    return edges


def validate_bool_array(name: str, fn: str, arr: Any, expected_len: int) -> np.ndarray:
    """Verify ``arr`` is a 1-D bool numpy array of the given length."""
    if not isinstance(arr, np.ndarray):
        raise TypeError(
            f"{fn}: {name} must be a numpy ndarray; got {type(arr).__name__}"
        )
    if arr.dtype != np.bool_:
        raise TypeError(
            f"{fn}: {name} must be bool; got dtype {arr.dtype}"
        )
    if arr.ndim != 1:
        raise ValueError(
            f"{fn}: {name} must be 1-D; got shape {arr.shape}"
        )
    if arr.shape[0] != expected_len:
        raise ValueError(
            f"{fn}: {name} must have length {expected_len}; "
            f"got length {arr.shape[0]}"
        )
    return arr


__all__ = [
    "validate_non_negative_int",
    "validate_edges_array",
    "validate_bool_array",
]
