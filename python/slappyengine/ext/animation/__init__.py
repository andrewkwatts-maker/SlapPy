"""Extension shim — re-exports from slappyengine.animation.

This subpackage's canonical home is slappyengine.ext.animation.
Import via either path; both are supported.
"""
from slappyengine.animation import *  # noqa: F401, F403
from slappyengine.animation import __all__  # propagate __all__
