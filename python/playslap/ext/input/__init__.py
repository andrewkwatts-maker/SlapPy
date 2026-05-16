"""Extension shim — re-exports from playslap.input.

This subpackage's canonical home is playslap.ext.input.
Import via either path; both are supported.
"""
from playslap.input import *  # noqa: F401, F403
from playslap.input import __all__  # propagate __all__
