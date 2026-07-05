"""Perf regression tooling for SlapPyEngine.

This sub-package provides a lightweight, dependency-free perf tripwire
that measures per-frame time on the ``hello_ragdoll`` demo and flags
regressions against a committed YAML baseline.

Public surface
--------------

* :class:`PerfResult` — a dataclass describing a single benchmark run.
* :class:`ComparisonReport` — the outcome of comparing a fresh run to
  a baseline (pass/fail plus per-metric deltas).
* :class:`PerfTripwire` — the runner, YAML I/O, and comparison helpers.
* :data:`DEFAULT_BASELINE_PATH` — the on-disk YAML baseline that ships
  with the package (``baseline_ragdoll.yaml``).

The CLI entry point lives at :mod:`slappyengine.perf.cli` and is spelt
``python -m slappyengine.perf.tripwire``.

Public symbols are re-exported lazily via ``__getattr__`` so that
``python -m slappyengine.perf.tripwire`` does not trip Python's
"module found in sys.modules before execution" ``RuntimeWarning``.
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "DEFAULT_BASELINE_PATH",
    "ComparisonReport",
    "PerfResult",
    "PerfTripwire",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import tripwire as _tripwire

        return getattr(_tripwire, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(list(globals().keys()) + __all__))
