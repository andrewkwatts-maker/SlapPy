"""Internal input-validation helpers for the ``telemetry`` public API.

Thin re-export shim — all validators are generic and live in
:mod:`slappyengine._validation`.
"""
from __future__ import annotations

from slappyengine._validation import (
    validate_bool,
    validate_callable,
    validate_non_negative_int,
    validate_str,
)


__all__ = [
    "validate_str",
    "validate_callable",
    "validate_non_negative_int",
    "validate_bool",
]
