"""Extension shim — re-exports from playslap.animation.

This subpackage's canonical home is playslap.ext.animation.
Import via either path; both are supported.
"""
from playslap.animation import *  # noqa: F401, F403
from playslap.animation import __all__  # propagate __all__
