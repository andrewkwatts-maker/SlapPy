"""Internal input-validation helpers for the ``slappyengine.compute`` and
``slappyengine.post_process`` GPU dispatch paths (hardening round 14).

Generic validators (``validate_str``, ``validate_positive_int`` …) live in
:mod:`slappyengine._validation`. The dispatch- and shader-loader-specific
helpers below stay here because they encode wgpu-specific limits
(``MAX_WORKGROUPS_PER_DIM``) and the bind-group entry shape.

These guard:

* ``ComputePass.__init__`` / ``ComputePass.from_source`` /
  ``ComputePass.from_wgsl`` — refuse ``bytes`` source, empty entry-point,
  non-existent shader paths.
* ``ComputePipeline.dispatch`` (and any direct caller) — refuse non-
  positive, NaN, or oversize workgroup counts before they reach
  ``dispatch_workgroups`` (wgpu raises an opaque ``RuntimeError`` deep
  in the driver; the silent-acceptance failure is workgroup_count=0
  which is a no-op pass that returns empty readback).
* ``PostProcessExecutor`` bind-group resolution — refuse duplicate
  binding indices and negative binding indices before they hit
  ``device.create_bind_group`` (wgpu silently uses the LAST entry for
  a duplicate binding index in some backends).
* ``ComputeLibrary.register`` — refuse empty shader names and
  ``bytes``-typed sources that would never compile as WGSL.

Engineering policy: O(N) at most (bind-group entries are tiny). The
slow path is the bug message, not the happy path.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

import numpy as np

from slappyengine._validation import (
    validate_finite_float,
    validate_int,
    validate_non_empty_str,
    validate_non_negative_int,
    validate_positive_int,
    validate_str,
)

# wgpu / WebGPU per-dimension dispatch limit. WebGPU 1.0 mandates support
# for at least 65535 workgroups per dimension; many native backends accept
# more but we refuse > 65535 at the boundary so cross-backend code stays
# portable. (Vulkan: maxComputeWorkGroupCount = 65535 typical.)
MAX_WORKGROUPS_PER_DIM = 65535


# ---------------------------------------------------------------------------
# Workgroup-count validators (ComputePipeline.dispatch path)
# ---------------------------------------------------------------------------


def validate_workgroup_count(name: str, fn: str, value: Any) -> int:
    """Confirm ``value`` is an int in ``[1, MAX_WORKGROUPS_PER_DIM]``.

    Refuses ``bool`` (``True``→1 silently dispatching a single workgroup
    was a real bug surface in the lighting passes), refuses ``float`` —
    even integral ones like ``1.0`` — because ``dispatch_workgroups``
    requires ints and the implicit ``int(...)`` would also accept NaN-
    cast-to-zero on some Pythons.

    Raises
    ------
    TypeError
        If *value* is not a plain ``int`` / ``np.integer``.
    ValueError
        If *value* is < 1 or > ``MAX_WORKGROUPS_PER_DIM``.
    """
    # Reject NaN/inf-bearing floats *before* the int coercion in
    # validate_positive_int. ``int(math.nan)`` raises ValueError on CPython
    # but the error is not friendly; explicit refusal at the boundary is
    # consistent with every other engine path.
    if isinstance(value, float):
        if math.isnan(value):
            raise ValueError(
                f"{fn}: {name} must be a positive int; got NaN"
            )
        if math.isinf(value):
            raise ValueError(
                f"{fn}: {name} must be a positive int; got {value!r}"
            )
        raise TypeError(
            f"{fn}: {name} must be an int; got {type(value).__name__}"
        )
    if isinstance(value, np.floating):
        # numpy floats follow the same rules as Python floats.
        fv = float(value)
        if math.isnan(fv):
            raise ValueError(
                f"{fn}: {name} must be a positive int; got NaN"
            )
        raise TypeError(
            f"{fn}: {name} must be an int; got {type(value).__name__}"
        )
    return validate_positive_int(name, fn, value, maximum=MAX_WORKGROUPS_PER_DIM)


def validate_workgroup_3tuple(
    name: str, fn: str, value: Any
) -> tuple[int, int, int]:
    """Confirm ``value`` is a 3-element sequence of workgroup counts.

    Each component must satisfy :func:`validate_workgroup_count`.
    """
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a 3-tuple of ints; "
            f"got {type(value).__name__}"
        )
    if len(value) != 3:
        raise ValueError(
            f"{fn}: {name} must have length 3 (x, y, z); "
            f"got length {len(value)}"
        )
    x = validate_workgroup_count(f"{name}[0]", fn, value[0])
    y = validate_workgroup_count(f"{name}[1]", fn, value[1])
    z = validate_workgroup_count(f"{name}[2]", fn, value[2])
    return (x, y, z)


# ---------------------------------------------------------------------------
# Shader-loader validators (ComputePass / ComputeLibrary)
# ---------------------------------------------------------------------------


def validate_shader_source(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a non-empty WGSL source string.

    Refuses ``bytes`` outright: ``device.create_shader_module(code=b"...")``
    would later raise ``TypeError: 'bytes' object is not str`` inside wgpu
    — the message lacks the call site and tracebacks land deep in the
    driver. The boundary refusal points straight at the caller.
    """
    if isinstance(value, (bytes, bytearray)):
        raise TypeError(
            f"{fn}: {name} must be a str (WGSL source); "
            f"got {type(value).__name__} — decode to str first"
        )
    return validate_non_empty_str(name, fn, value)


def validate_entry_point(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a non-empty entry-point identifier.

    WGSL identifiers cannot start with a digit but the full grammar is
    not enforced here — the shader compiler reports those clearly. The
    boundary refusal targets the silent-acceptance case: empty string
    silently dispatches against the first entry point in the module,
    which is almost never what the caller meant.
    """
    return validate_non_empty_str(name, fn, value)


def validate_shader_label(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a ``str`` (empty allowed — used as a debug label)."""
    return validate_str(name, fn, value, allow_empty=True)


def validate_shader_path(name: str, fn: str, value: Any) -> Path:
    """Confirm ``value`` points at an existing shader file.

    Refuses ``bool`` and ``bytes``. Refuses non-existent paths up-front
    so callers don't waste a GPU encoder allocation only to discover the
    shader is missing when ``read_text`` raises ``FileNotFoundError``.
    """
    if isinstance(value, bool) or not isinstance(value, (str, Path, os.PathLike)):
        raise TypeError(
            f"{fn}: {name} must be str or pathlib.Path; "
            f"got {type(value).__name__}"
        )
    s = str(value)
    if s == "":
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


# ---------------------------------------------------------------------------
# Bind-group entry validator (PostProcessExecutor)
# ---------------------------------------------------------------------------


def validate_bind_group_entries(
    name: str, fn: str, value: Any
) -> list[dict]:
    """Confirm ``value`` is a list of bind-group entries with unique bindings.

    Each entry must be a ``dict`` with an integer ``"binding"`` key and a
    ``"resource"`` key. The validator refuses:

    * non-list input (``None`` / ``dict`` / ``tuple-of-non-dicts``)
    * missing ``"binding"`` or ``"resource"`` keys
    * ``bool`` masquerading as a binding index (``True`` → ``1``)
    * negative binding indices
    * duplicate binding indices (wgpu silently keeps the LAST entry on
      some backends — this is the highest-value silent-acceptance bug
      caught by this round of hardening)
    """
    if value is None:
        raise TypeError(f"{fn}: {name} must not be None")
    if isinstance(value, (str, bytes, dict, set)):
        raise TypeError(
            f"{fn}: {name} must be a list of bind-group entries; "
            f"got {type(value).__name__}"
        )
    if not isinstance(value, (list, tuple)):
        raise TypeError(
            f"{fn}: {name} must be a list of bind-group entries; "
            f"got {type(value).__name__}"
        )
    out: list[dict] = []
    seen: set[int] = set()
    for i, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise TypeError(
                f"{fn}: {name}[{i}] must be a dict with 'binding' and "
                f"'resource' keys; got {type(entry).__name__}"
            )
        if "binding" not in entry:
            raise ValueError(
                f"{fn}: {name}[{i}] is missing required key 'binding'"
            )
        if "resource" not in entry:
            raise ValueError(
                f"{fn}: {name}[{i}] is missing required key 'resource'"
            )
        binding = entry["binding"]
        # Refuse bool — ``True`` would silently mean ``binding=1``.
        if isinstance(binding, bool):
            raise TypeError(
                f"{fn}: {name}[{i}].binding must be an int; "
                f"got {type(binding).__name__}"
            )
        idx = validate_non_negative_int(
            f"{name}[{i}].binding", fn, binding
        )
        if idx in seen:
            raise ValueError(
                f"{fn}: {name} has duplicate binding index {idx} "
                f"(at entry {i}); wgpu silently keeps the LAST entry on "
                f"some backends — make the bindings unique"
            )
        seen.add(idx)
        out.append(entry)
    return out


__all__ = [
    "MAX_WORKGROUPS_PER_DIM",
    "validate_workgroup_count",
    "validate_workgroup_3tuple",
    "validate_shader_source",
    "validate_entry_point",
    "validate_shader_label",
    "validate_shader_path",
    "validate_bind_group_entries",
    # re-exports for callers
    "validate_finite_float",
    "validate_int",
    "validate_non_empty_str",
    "validate_non_negative_int",
    "validate_positive_int",
    "validate_str",
]
