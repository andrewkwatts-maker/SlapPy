"""Internal input-validation helpers for the ``topology`` public API.

These helpers exist so :func:`connected_components` (and any future
graph-topology entry point) can share precise error messages without
re-repeating the same checks. They are deliberately not re-exported
through ``__init__``.

Engineering policy: validate at the system boundary; internal solver
calls trust their inputs. O(1) checks only — no whole-array scans.
"""
from __future__ import annotations

from typing import Any

import numpy as np


_INT_DTYPES = (np.int8, np.int16, np.int32, np.int64,
               np.uint8, np.uint16, np.uint32, np.uint64)


def validate_non_negative_int(name: str, fn: str, value: Any) -> int:
    """Coerce *value* to a Python ``int`` after rejecting wrong types.

    Raises
    ------
    TypeError
        If ``value`` is not an int (booleans accepted as ints per Python).
    ValueError
        If ``value`` is negative.
    """
    # Reject floats / numpy floats / strings explicitly — Python's int() would
    # truncate silently otherwise.
    if isinstance(value, bool):
        # bool is subclass of int — promote without complaint.
        return int(value)
    if isinstance(value, (int, np.integer)):
        v = int(value)
    else:
        raise TypeError(
            f"{fn}: {name} must be an int; got {type(value).__name__}"
        )
    if v < 0:
        raise ValueError(
            f"{fn}: {name} must be ≥ 0; got {v}"
        )
    return v


def validate_edges_array(fn: str, edges: Any, n_nodes: int) -> np.ndarray:
    """Verify ``edges`` is an ``(E, 2)`` integer numpy array with valid ids.

    Returns the array (unchanged) so callers can chain.

    Raises
    ------
    TypeError
        If ``edges`` is not a numpy ndarray, or its dtype is not integral.
    ValueError
        If ``edges`` is not 2-D, has the wrong second dimension, or contains
        out-of-range node ids (``< 0`` or ``>= n_nodes``).
    """
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
        # O(1) min/max scan is fine — numpy is C-level and this is a single
        # vector reduction. We do exactly two reductions and no Python loop.
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
    """Verify ``arr`` is a 1-D bool numpy array of the given length.

    Raises
    ------
    TypeError
        If ``arr`` is not a numpy ndarray or has non-bool dtype.
    ValueError
        If ``arr`` is not 1-D or its length differs from ``expected_len``.
    """
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
