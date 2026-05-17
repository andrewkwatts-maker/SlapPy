"""Extension shim — re-exports from slappyengine.split_screen.

This module's canonical home is SlapPyEngine.ext.split_screen.
Import via either path; both are supported.
"""
from slappyengine.split_screen import (
    Viewport,
    SplitScreenManager,
)

__all__ = [
    "Viewport",
    "SplitScreenManager",
]
