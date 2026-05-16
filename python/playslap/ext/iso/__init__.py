"""Extension shim — re-exports from playslap.iso.

This subpackage's canonical home is playslap.ext.iso.
Import via either path; both are supported.
"""
from playslap.iso import *  # noqa: F401, F403
from playslap.iso import __all__  # propagate __all__
