"""Internal input-validation helpers for the :class:`Asset` public API.

Shared rejection logic for the :class:`Asset` constructor and its
``add_effect`` / ``add_layer`` / ``from_image`` / ``bake_data_layer``
public methods. Internal pixel/GPU paths trust their inputs.

Engineering policy: validate at the boundary, never silently coerce.
``Asset.from_image(b"player.png")`` would today fail four frames later
when PIL hits the wrong codepath; ``Asset(position=(float("nan"), 0))``
would emit a blank texture every subsequent frame. Refuse loudly here
so the authoring error surfaces at the construction / call site.

O(1) checks only — never scan numpy buffers or stat the filesystem
beyond a single ``Path.exists`` for the explicit ``from_image`` case.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Asset() constructor + assignment-site rejectors
# ---------------------------------------------------------------------------

def validate_name(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a ``str`` (empty allowed — Asset accepts "").

    Raises
    ------
    TypeError
        If ``value`` is not a ``str`` (bool/bytes/None refused).
    """
    if isinstance(value, bool) or not isinstance(value, str):
        raise TypeError(
            f"{fn}: {name} must be a str; got {type(value).__name__}"
        )
    return value


def validate_finite_2tuple(name: str, fn: str, value: Any) -> tuple[float, float]:
    """Confirm ``value`` is a 2-element sequence of finite real numbers.

    Raises
    ------
    TypeError
        If ``value`` is not a 2-element sequence, or members aren't real
        numbers (bool refused — silent ``True → 1.0`` is a footgun).
    ValueError
        If the length isn't 2 or any element is NaN/inf.
    """
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a 2-tuple of floats; "
            f"got {type(value).__name__}"
        )
    if len(value) != 2:
        raise ValueError(
            f"{fn}: {name} must have length 2 (x, y); got length {len(value)}"
        )
    x, y = value[0], value[1]
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise TypeError(
            f"{fn}: {name}[0] must be a real number; got {type(x).__name__}"
        )
    if isinstance(y, bool) or not isinstance(y, (int, float)):
        raise TypeError(
            f"{fn}: {name}[1] must be a real number; got {type(y).__name__}"
        )
    fx, fy = float(x), float(y)
    if not math.isfinite(fx):
        raise ValueError(f"{fn}: {name}[0] must be finite; got {fx!r}")
    if not math.isfinite(fy):
        raise ValueError(f"{fn}: {name}[1] must be finite; got {fy!r}")
    return (fx, fy)


def validate_positive_size_2tuple(name: str, fn: str, value: Any) -> tuple[int, int]:
    """Confirm ``value`` is a 2-element sequence of positive ints.

    Asset texture dimensions must be >= 1 — a ``size=(0, 64)`` Asset is a
    degenerate render target that crashes on the first present.

    Raises
    ------
    TypeError
        If ``value`` is not a 2-element sequence or members aren't ints
        (bool refused).
    ValueError
        If the length isn't 2 or any element is < 1.
    """
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a 2-tuple of ints; "
            f"got {type(value).__name__}"
        )
    if len(value) != 2:
        raise ValueError(
            f"{fn}: {name} must have length 2 (width, height); "
            f"got length {len(value)}"
        )
    w, h = value[0], value[1]
    if isinstance(w, bool) or not isinstance(w, int):
        raise TypeError(
            f"{fn}: {name}[0] (width) must be an int; got {type(w).__name__}"
        )
    if isinstance(h, bool) or not isinstance(h, int):
        raise TypeError(
            f"{fn}: {name}[1] (height) must be an int; got {type(h).__name__}"
        )
    if w < 1:
        raise ValueError(f"{fn}: {name}[0] (width) must be >= 1; got {w}")
    if h < 1:
        raise ValueError(f"{fn}: {name}[1] (height) must be >= 1; got {h}")
    return (w, h)


# ---------------------------------------------------------------------------
# add_effect(mat, blend)
# ---------------------------------------------------------------------------

def validate_node_material(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is a :class:`NodeMaterial` instance.

    The duck-typed check used previously (``mat.wgsl is None`` → ``compile()``)
    blew up only when the bad object reached ``compile``; refuse at the
    boundary so the stack trace points at ``add_effect``.

    Raises
    ------
    TypeError
        If ``value`` is not a :class:`NodeMaterial`.
    """
    # Local import — node_material → asset would be a cycle at module load.
    from slappyengine.material.node_material import NodeMaterial

    if not isinstance(value, NodeMaterial):
        raise TypeError(
            f"{fn}: {name} must be a NodeMaterial; "
            f"got {type(value).__name__}"
        )
    return value


def validate_blend(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a non-empty ``str`` blend mode tag.

    The shader pipeline reads ``mat.blend`` as a string; passing ``None``
    or ``42`` silently turns it into the literal ``"None"`` / ``"42"``
    branch which simply renders nothing in the shader.

    Raises
    ------
    TypeError
        If ``value`` is not a ``str`` (bool refused).
    ValueError
        If ``value`` is the empty string.
    """
    if isinstance(value, bool) or not isinstance(value, str):
        raise TypeError(
            f"{fn}: {name} must be a str; got {type(value).__name__}"
        )
    if value == "":
        raise ValueError(f"{fn}: {name} must not be empty")
    return value


# ---------------------------------------------------------------------------
# add_layer(layer)
# ---------------------------------------------------------------------------

def validate_layer_arg(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is a :class:`Layer` instance.

    Without this check, ``asset.add_layer(None)`` would silently land in
    ``RenderTarget.layers`` and crash on the next ``tick`` when the
    renderer dereferences ``layer.tick``.

    Raises
    ------
    TypeError
        If ``value`` is not a :class:`Layer`.
    """
    from slappyengine.layer import Layer

    if not isinstance(value, Layer):
        raise TypeError(
            f"{fn}: {name} must be a Layer/Layer2D/Layer3D; "
            f"got {type(value).__name__}"
        )
    return value


# ---------------------------------------------------------------------------
# from_image(path, name)
# ---------------------------------------------------------------------------

def validate_existing_file_path(name: str, fn: str, value: Any) -> Path:
    """Confirm ``value`` is a path-like pointing to an existing regular file.

    Refuses ``bytes`` (``Path(b"x")`` is platform-dependent on Windows),
    refuses empty strings, refuses URL-style strings that ``Path`` happily
    accepts but which later file-open will fail on with a generic OSError.

    Raises
    ------
    TypeError
        If ``value`` is not ``str``/``Path`` (bool/bytes/None refused).
    ValueError
        If ``value`` is the empty string.
    FileNotFoundError
        If the path doesn't exist or isn't a regular file.
    """
    if isinstance(value, bool) or not isinstance(value, (str, Path)):
        raise TypeError(
            f"{fn}: {name} must be str or pathlib.Path; "
            f"got {type(value).__name__}"
        )
    if isinstance(value, str) and value == "":
        raise ValueError(f"{fn}: {name} must not be empty")
    if isinstance(value, Path) and str(value) == "":
        raise ValueError(f"{fn}: {name} must not be empty")
    p = Path(value)
    if not p.exists():
        raise FileNotFoundError(
            f"{fn}: {name} not found: {os.fspath(p)!r}"
        )
    if not p.is_file():
        raise FileNotFoundError(
            f"{fn}: {name} is not a regular file: {os.fspath(p)!r}"
        )
    return p


def validate_optional_name(name: str, fn: str, value: Any) -> str | None:
    """Confirm ``value`` is ``None`` or a ``str``.

    Used for the optional ``name`` parameter on :meth:`Asset.from_image`.

    Raises
    ------
    TypeError
        If ``value`` is neither ``None`` nor ``str`` (bool refused).
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, str):
        raise TypeError(
            f"{fn}: {name} must be a str or None; got {type(value).__name__}"
        )
    return value


# ---------------------------------------------------------------------------
# bake_data_layer(output_path)
# ---------------------------------------------------------------------------

def validate_optional_output_path(name: str, fn: str, value: Any) -> Path | None:
    """Confirm ``value`` is ``None`` or a non-empty ``str``/``Path``.

    Returns a :class:`Path` for downstream use, or ``None`` to signal
    "use default path". Does **not** stat the filesystem — the .slap
    writer creates the file.

    Raises
    ------
    TypeError
        If ``value`` is not ``None`` / ``str`` / ``Path``.
    ValueError
        If ``value`` is the empty string.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, Path)):
        raise TypeError(
            f"{fn}: {name} must be str, pathlib.Path, or None; "
            f"got {type(value).__name__}"
        )
    if isinstance(value, str) and value == "":
        raise ValueError(f"{fn}: {name} must not be empty")
    if isinstance(value, Path) and str(value) == "":
        raise ValueError(f"{fn}: {name} must not be empty")
    return Path(value)


__all__ = [
    "validate_name",
    "validate_finite_2tuple",
    "validate_positive_size_2tuple",
    "validate_node_material",
    "validate_blend",
    "validate_layer_arg",
    "validate_existing_file_path",
    "validate_optional_name",
    "validate_optional_output_path",
]
