"""Shared UBO packing helper for the post-process passes.

Background
----------
Every post-process pass that drives a WGSL shader needs to pack a
uniform-buffer-object (UBO) blob whose byte layout exactly matches the
shader's ``var<uniform> params : Params`` struct.  Historically each
pass spelled this out inline with ``struct.pack("<...", ...)`` and a
human-maintained format string in a docstring comment.  This is brittle:
the Sprint 2D and Sprint 7B regressions were both "format string drifted
away from the WGSL declaration" bugs.

This helper centralises the rules.  Callers describe the UBO as a list of
:class:`UboField` records (name + dtype + optional explicit offset) and
``pack_struct`` does the layout computation, type-checking, and
``struct.pack`` for them.  Crucially, **byte-for-byte parity with the
legacy inline implementations is mandatory** — the executor's runtime
splice (see :func:`slappyengine.post_process.executor._splice_runtime_params`)
relies on stable offsets, so this module is engineered to reproduce
every legacy layout exactly when the same fields are supplied in the
same order.

WGSL std140-style alignment
---------------------------
The layout rules are a subset of the WGSL uniform-storage rules:

* ``f32`` / ``u32`` / ``i32`` are 4-byte aligned and 4 bytes wide.
* ``vec2f`` is 8-byte aligned and 8 bytes wide.
* ``vec3f`` is 16-byte aligned and **12 bytes wide** (the trailing 4
  bytes are *not* automatically padded — the next field may pack into
  them if its size and alignment fit).
* ``vec4f`` is 16-byte aligned and 16 bytes wide.

The total struct size is rounded up to a multiple of 16 bytes to match
the std140 rule WGSL inherits from std140.  This matches the legacy
inline layouts byte-for-byte.

Mixing dtype-driven layout with explicit offsets
------------------------------------------------
A field may pin its own ``offset`` (in bytes).  When set, the field is
placed at exactly that offset, ignoring the running cursor — useful for
preserving legacy layouts where a vec3 is followed by a u32 packed into
its trailing pad slot.  When unset (``offset = -1``) the cursor advances
according to the dtype's natural alignment rule above.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Any, Iterable


# Size of each dtype in bytes.  ``vec3f`` is 12 (not 16) by design —
# WGSL only forces the *alignment* of a vec3 to 16, not its size.
_SIZE: dict[str, int] = {
    "f32":   4,
    "u32":   4,
    "i32":   4,
    "vec2f": 8,
    "vec3f": 12,
    "vec4f": 16,
}

# Required alignment (in bytes) of each dtype, per WGSL spec §10.3.5.
_ALIGN: dict[str, int] = {
    "f32":   4,
    "u32":   4,
    "i32":   4,
    "vec2f": 8,
    "vec3f": 16,
    "vec4f": 16,
}

# ``struct`` format codes used to pack each dtype.  Vector types pack as
# repeated scalars; ``vec3f`` packs three f32s contiguously (12 bytes),
# matching the WGSL data layout.
_STRUCT_CODE: dict[str, str] = {
    "f32":   "f",
    "u32":   "I",
    "i32":   "i",
    "vec2f": "ff",
    "vec3f": "fff",
    "vec4f": "ffff",
}

# Number of scalar values each dtype consumes from the ``values`` dict.
_COMPONENT_COUNT: dict[str, int] = {
    "f32":   1,
    "u32":   1,
    "i32":   1,
    "vec2f": 2,
    "vec3f": 3,
    "vec4f": 4,
}


@dataclass
class UboField:
    """One scalar/vector field inside a UBO struct.

    Attributes
    ----------
    name
        Key used to look the value up in the dict passed to
        :func:`pack_struct`.
    dtype
        One of ``"f32"``, ``"u32"``, ``"i32"``, ``"vec2f"``, ``"vec3f"``,
        ``"vec4f"``.
    offset
        Byte offset of the field inside the struct.  Use ``-1`` (the
        default) to let :func:`compute_offsets` assign the offset
        according to the WGSL alignment rules.  Set explicitly when a
        legacy layout needs to be reproduced byte-for-byte.
    """

    name: str
    dtype: str
    offset: int = -1


def _aligned_up(value: int, alignment: int) -> int:
    """Round ``value`` up to the nearest multiple of ``alignment``."""
    if alignment <= 0:
        raise ValueError(f"alignment must be > 0; got {alignment}")
    return ((value + alignment - 1) // alignment) * alignment


def compute_offsets(fields: Iterable[UboField]) -> int:
    """Assign byte offsets to ``fields`` in place and return total size.

    Walks ``fields`` in order.  For each field whose ``offset`` is the
    sentinel ``-1`` the offset is computed by aligning the running
    cursor up to the dtype's natural alignment.  Fields with a pinned
    ``offset`` are placed there exactly; the cursor jumps to
    ``offset + size`` after them.

    The returned size is rounded up to a multiple of 16 bytes to match
    the std140 / WGSL uniform-storage rule.  Callers can rely on the
    return value as ``len(pack_struct(fields, values))``.

    Raises
    ------
    KeyError
        If any field's ``dtype`` is not recognised.
    """
    cursor = 0
    fields_list = list(fields)
    for f in fields_list:
        if f.dtype not in _SIZE:
            raise KeyError(
                f"UboField {f.name!r}: unknown dtype {f.dtype!r}; "
                f"expected one of {sorted(_SIZE)}"
            )
        size = _SIZE[f.dtype]
        align = _ALIGN[f.dtype]
        if f.offset < 0:
            f.offset = _aligned_up(cursor, align)
        cursor = f.offset + size
    # WGSL requires the struct size be aligned to its strictest member,
    # but for uniform buffers we round up to 16 bytes for std140-compat.
    return _aligned_up(cursor, 16)


def pack_layout_str(fields: Iterable[UboField]) -> str:
    """Produce a ``struct.pack`` format string equivalent to ``fields``.

    The result includes the ``<`` little-endian prefix and inserts
    ``Nx`` pad bytes wherever two consecutive fields are not adjacent
    (because of alignment or because an explicit offset created a gap),
    plus a trailing pad to the final 16-byte alignment.

    This is exposed so callers that still want to drive ``struct.pack``
    by hand can sanity-check their format string against the canonical
    layout — for example, regression tests can assert
    ``pack_layout_str(FIELDS) == "<ffff"`` for the bloom UBO.
    """
    fields_list = list(fields)
    total = compute_offsets(fields_list)
    parts: list[str] = ["<"]
    cursor = 0
    for f in fields_list:
        if f.offset > cursor:
            parts.append(f"{f.offset - cursor}x")
        parts.append(_STRUCT_CODE[f.dtype])
        cursor = f.offset + _SIZE[f.dtype]
    if total > cursor:
        parts.append(f"{total - cursor}x")
    return "".join(parts)


def _coerce_scalar(name: str, dtype: str, raw: Any) -> Any:
    """Type-check + coerce a scalar component, raising on invalid input."""
    if isinstance(raw, bool):
        # ``bool`` is an ``int`` subclass; allow it for integer dtypes
        # (it's the canonical encoding for flag bits) but never silently
        # promote it to a float.
        if dtype == "f32":
            raise TypeError(
                f"UBO field {name!r} ({dtype}): expected float; "
                f"got bool {raw!r}"
            )
        return int(raw)
    if dtype == "f32":
        if not isinstance(raw, (int, float)):
            raise TypeError(
                f"UBO field {name!r} ({dtype}): expected float; "
                f"got {type(raw).__name__}"
            )
        f = float(raw)
        if not math.isfinite(f):
            raise ValueError(
                f"UBO field {name!r} ({dtype}): value must be finite; "
                f"got {raw!r}"
            )
        return f
    if dtype in ("u32", "i32"):
        if not isinstance(raw, int):
            raise TypeError(
                f"UBO field {name!r} ({dtype}): expected int; "
                f"got {type(raw).__name__}"
            )
        if dtype == "u32" and raw < 0:
            raise ValueError(
                f"UBO field {name!r} ({dtype}): unsigned, got {raw}"
            )
        return raw
    raise KeyError(f"UBO field {name!r}: unsupported scalar dtype {dtype!r}")


def pack_struct(
    fields: Iterable[UboField],
    values: dict[str, Any],
) -> bytes:
    """Pack ``values`` into a uniform-buffer blob following ``fields``.

    Parameters
    ----------
    fields
        Field descriptors.  Offsets are computed (mutated in place) by
        :func:`compute_offsets` if not already pinned.
    values
        Maps each ``field.name`` to either a single scalar (for ``f32``
        / ``u32`` / ``i32``) or an iterable of N scalars (for vec dtypes
        of width N).  Booleans are accepted for integer dtypes (they
        encode flag bits) but rejected for ``f32`` to keep accidental
        ``True``/``False`` slips obvious.

    Returns
    -------
    bytes
        A blob of length ``compute_offsets(fields)`` — i.e. rounded up
        to a multiple of 16 bytes.  Trailing pad bytes are NUL.

    Raises
    ------
    KeyError
        If ``values`` is missing a field, or a dtype is unknown.
    TypeError
        If a value is the wrong Python type for its dtype.
    ValueError
        If an ``f32`` value is non-finite, a ``u32`` is negative, or a
        vector value has the wrong component count.
    """
    fields_list = list(fields)
    total = compute_offsets(fields_list)
    out = bytearray(total)

    for f in fields_list:
        if f.name not in values:
            raise KeyError(f"UBO field {f.name!r}: no value supplied")
        raw = values[f.name]
        n_components = _COMPONENT_COUNT[f.dtype]
        if n_components == 1:
            comp = _coerce_scalar(f.name, f.dtype, raw)
            packed = struct.pack("<" + _STRUCT_CODE[f.dtype], comp)
        else:
            # Vector dtype: accept any iterable of the right length.
            try:
                items = list(raw)
            except TypeError as exc:
                raise TypeError(
                    f"UBO field {f.name!r} ({f.dtype}): value must be "
                    f"iterable of {n_components} floats; got "
                    f"{type(raw).__name__}"
                ) from exc
            if len(items) != n_components:
                raise ValueError(
                    f"UBO field {f.name!r} ({f.dtype}): expected "
                    f"{n_components} components, got {len(items)}"
                )
            # All vector dtypes are float in WGSL — coerce each
            # component through the f32 path so NaN/inf rejection still
            # fires per component.
            coerced = [
                _coerce_scalar(f.name, "f32", c) for c in items
            ]
            packed = struct.pack(
                "<" + _STRUCT_CODE[f.dtype], *coerced,
            )
        out[f.offset:f.offset + len(packed)] = packed

    return bytes(out)


__all__ = [
    "UboField",
    "compute_offsets",
    "pack_layout_str",
    "pack_struct",
]
