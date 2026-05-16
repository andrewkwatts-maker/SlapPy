"""Extension shim — re-exports from playslap.split_screen.

This module's canonical home is playslap.ext.split_screen.
Import via either path; both are supported.
"""
from playslap.split_screen import (
    Viewport,
    SplitScreenManager,
)

__all__ = [
    "Viewport",
    "SplitScreenManager",
]
