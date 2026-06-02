"""Internal input-validation helpers for the ``slappyengine.gpu`` public API.

Generic validators (``validate_str``, ``validate_positive_int`` …) live in
:mod:`slappyengine._validation`. Domain helpers (``validate_mesh_lists``,
``validate_image_array``, ``validate_filter_mode``) stay here.

These guard the headless / wgpu-free surface of the GPU subpackage —
``GpuMesh.__init__``, ``MeshVertex.pack``, ``MeshRenderer.set_*`` /
``update_camera`` / ``render_to_texture``, ``TextureManager.upload_*`` /
``create_sampler``. The deep wgpu objects (``GPUDevice``, ``GPUBuffer``)
are not type-checked here — wgpu raises clean errors of its own.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from slappyengine._validation import (
    validate_finite_float,
    validate_non_empty_str,
    validate_non_negative_int,
    validate_positive_int,
    validate_str,
)


def validate_vertex_list(name: str, fn: str, value: Any) -> list:
    """Confirm ``value`` is a non-empty list/tuple of vertex objects.

    Refuses ``None`` (previously slipped through ``GpuMesh.__init__`` and
    crashed inside ``vertex_bytes`` with an unhelpful ``NoneType is not
    iterable``).
    """
    if value is None:
        raise TypeError(f"{fn}: {name} must not be None")
    if isinstance(value, (str, bytes, dict, set)):
        raise TypeError(
            f"{fn}: {name} must be a list or tuple of vertices; "
            f"got {type(value).__name__}"
        )
    if not isinstance(value, (list, tuple)):
        raise TypeError(
            f"{fn}: {name} must be a list or tuple of vertices; "
            f"got {type(value).__name__}"
        )
    return list(value)


def validate_index_list(name: str, fn: str, value: Any) -> list:
    """Confirm ``value`` is a list/tuple of non-negative integers."""
    if value is None:
        raise TypeError(f"{fn}: {name} must not be None")
    if isinstance(value, (str, bytes, dict, set)):
        raise TypeError(
            f"{fn}: {name} must be a list or tuple of ints; "
            f"got {type(value).__name__}"
        )
    if not isinstance(value, (list, tuple)):
        raise TypeError(
            f"{fn}: {name} must be a list or tuple of ints; "
            f"got {type(value).__name__}"
        )
    out: list = []
    for i, v in enumerate(value):
        out.append(validate_non_negative_int(f"{name}[{i}]", fn, v))
    if len(out) % 3 != 0:
        raise ValueError(
            f"{fn}: {name} length must be a multiple of 3 (triangle list); "
            f"got {len(out)}"
        )
    return out


def validate_matrix16(name: str, fn: str, value: Any) -> list:
    """Confirm ``value`` is a 16-element sequence of finite floats (mat4x4)."""
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a 16-element sequence of floats; "
            f"got {type(value).__name__}"
        )
    if len(value) != 16:
        raise ValueError(
            f"{fn}: {name} must have length 16 (mat4x4); got length {len(value)}"
        )
    return [validate_finite_float(f"{name}[{i}]", fn, value[i]) for i in range(16)]


def validate_image_array(name: str, fn: str, value: Any) -> np.ndarray:
    """Confirm ``value`` is an ``ndarray`` shaped ``(H, W, C)`` with ``H, W >= 1``."""
    if not isinstance(value, np.ndarray):
        raise TypeError(
            f"{fn}: {name} must be a numpy.ndarray; got {type(value).__name__}"
        )
    if value.ndim != 3:
        raise ValueError(
            f"{fn}: {name} must be 3-dimensional (H, W, C); got ndim={value.ndim}"
        )
    h, w, c = value.shape
    if h < 1 or w < 1:
        raise ValueError(
            f"{fn}: {name} must have H>=1 and W>=1; got shape {value.shape}"
        )
    if c not in (3, 4):
        raise ValueError(
            f"{fn}: {name} must have 3 or 4 channels; got {c}"
        )
    return value


def validate_filter_mode(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is one of ``"nearest"`` or ``"linear"``.

    ``TextureManager.create_sampler`` previously silently treated any
    non-``"nearest"`` value as ``"linear"`` — including typos like
    ``"narest"``.
    """
    validate_non_empty_str(name, fn, value)
    if value not in ("nearest", "linear"):
        raise ValueError(
            f"{fn}: {name} must be 'nearest' or 'linear'; got {value!r}"
        )
    return value


def validate_view_dimension(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is one of the supported texture view dimensions."""
    validate_non_empty_str(name, fn, value)
    if value not in ("2d", "2d-array"):
        raise ValueError(
            f"{fn}: {name} must be '2d' or '2d-array'; got {value!r}"
        )
    return value


def validate_output_format(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a non-empty wgpu format string."""
    return validate_non_empty_str(name, fn, value)


__all__ = [
    "validate_vertex_list",
    "validate_index_list",
    "validate_matrix16",
    "validate_image_array",
    "validate_filter_mode",
    "validate_view_dimension",
    "validate_output_format",
    "validate_positive_int",
    "validate_non_negative_int",
    "validate_str",
    "validate_finite_float",
    "validate_non_empty_str",
]
