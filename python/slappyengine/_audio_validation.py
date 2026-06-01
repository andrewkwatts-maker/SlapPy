"""Internal input-validation helpers for the :mod:`slappyengine.audio` API.

Shared rejection logic for :class:`AudioManager` (``load`` / ``play`` /
``play_spatial`` / ``master_volume`` setter) and the module-level
:func:`play_sound` helper.

Engineering policy: validate at the public boundary; the sounddevice /
soundfile backends below trust their inputs. O(1) checks only — never scan
audio buffers here. Don't silently coerce: a NaN ``volume`` would multiply
the sample buffer to NaN every frame after, and a ``str`` masquerading as
a :class:`SoundHandle` would crash inside the playback thread where the
traceback is lost.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any


# Hard cap on the volume scalar passed to ``play`` / ``play_spatial``. The
# manager already clamps ``master_volume`` to [0, 1]; per-call volume is
# allowed in [0, 10] so games can briefly over-drive a sample (e.g. a
# stinger), but we refuse silly values that would clip the output to noise.
_VOLUME_MAX = 10.0


def validate_path(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a non-empty ``str`` or :class:`Path` audio path.

    Returns the path as a ``str`` so the soundfile call site does not need
    a second ``os.fspath`` round-trip. Existence is NOT checked here — the
    audio cache + soundfile already report missing files with a clean
    ``[AudioManager] Failed to load`` message, and unit tests rely on the
    cache hit-path with non-existent fixture paths.

    Raises
    ------
    TypeError
        If ``value`` is not a ``str`` or :class:`Path` (bytes refused — the
        soundfile ``read`` overload that takes bytes interprets them as raw
        audio data, which would silently succeed with garbage samples).
    ValueError
        If ``value`` is empty / whitespace only.
    """
    if not isinstance(value, (str, Path)):
        raise TypeError(
            f"{fn}: {name} must be a str or Path; got {type(value).__name__}"
        )
    s = str(value)
    if not s or not s.strip():
        raise ValueError(f"{fn}: {name} must be a non-empty path")
    return s


def validate_volume(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite ``volume`` scalar in ``[0, _VOLUME_MAX]``.

    Raises
    ------
    TypeError
        If ``value`` is not a real number (bool refused — ``True`` silently
        meaning ``volume=1.0`` is almost certainly a typo).
    ValueError
        If ``value`` is NaN/inf, negative, or > ``_VOLUME_MAX``.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{fn}: {name} must be a real number; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    if v < 0.0:
        raise ValueError(f"{fn}: {name} must be >= 0; got {v}")
    if v > _VOLUME_MAX:
        raise ValueError(
            f"{fn}: {name} must be <= {_VOLUME_MAX}; got {v}"
        )
    return v


def validate_master_volume(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite real number suitable for ``master_volume``.

    The setter clamps the result to ``[0, 1]``, but we still want NaN/inf
    and non-numerics to fail loudly rather than silently clamp to 0 or 1.

    Raises
    ------
    TypeError
        If ``value`` is not a real number (bool refused).
    ValueError
        If ``value`` is NaN/inf.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{fn}: {name} must be a real number; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    return v


def validate_bool(name: str, fn: str, value: Any) -> bool:
    """Confirm ``value`` is a real ``bool`` (not a truthy int / str / None).

    ``play(..., loop=1)`` would silently work via ``if loop:`` — we refuse
    so the caller cannot confuse "loop forever" with "loop 1 extra time".

    Raises
    ------
    TypeError
        If ``value`` is not a ``bool``.
    """
    if not isinstance(value, bool):
        raise TypeError(
            f"{fn}: {name} must be a bool; got {type(value).__name__}"
        )
    return value


def validate_finite_2tuple(name: str, fn: str, value: Any) -> tuple[float, float]:
    """Confirm ``value`` is a 2-element sequence of finite real numbers.

    Used for ``source_pos`` / ``listener_pos`` in :meth:`play_spatial`.

    Raises
    ------
    TypeError
        If ``value`` is not a 2-element sequence, or members aren't numeric
        (bool refused).
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


def validate_positive_finite_float(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite real number > 0.

    Used for ``max_dist`` in :meth:`play_spatial`. A ``max_dist`` of zero
    triggers a div-by-zero in the attenuation calc; NaN/inf would silently
    produce muted output.

    Raises
    ------
    TypeError
        If ``value`` is not a real number (bool refused).
    ValueError
        If ``value`` is NaN/inf or ≤ 0.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{fn}: {name} must be a real number; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    if v <= 0.0:
        raise ValueError(f"{fn}: {name} must be > 0; got {v}")
    return v


def validate_sound_handle_or_none(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is a :class:`SoundHandle` or ``None``.

    The public contract of ``play`` / ``play_spatial`` is "no-op on None";
    a ``str`` or path slipping through would silently produce no audio
    because the data attribute doesn't exist, and the failure would only
    surface inside the daemon thread where it gets swallowed.

    Raises
    ------
    TypeError
        If ``value`` is neither ``None`` nor a :class:`SoundHandle`.
    """
    if value is None:
        return None
    # Import locally to avoid the audio → validation module cycle.
    from slappyengine.audio import SoundHandle

    if not isinstance(value, SoundHandle):
        raise TypeError(
            f"{fn}: {name} must be a SoundHandle or None; "
            f"got {type(value).__name__}"
        )
    return value


def validate_positive_int(name: str, fn: str, value: Any) -> int:
    """Confirm ``value`` is an integer ≥ 1 (refuses ``bool`` and floats).

    Used for ``sample_rate`` overrides on :func:`play_sound`.

    Raises
    ------
    TypeError
        If ``value`` is not a plain ``int``.
    ValueError
        If ``value < 1``.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{fn}: {name} must be an int; got {type(value).__name__}"
        )
    if value < 1:
        raise ValueError(f"{fn}: {name} must be >= 1; got {value}")
    return value


__all__ = [
    "validate_path",
    "validate_volume",
    "validate_master_volume",
    "validate_bool",
    "validate_finite_2tuple",
    "validate_positive_finite_float",
    "validate_sound_handle_or_none",
    "validate_positive_int",
]
