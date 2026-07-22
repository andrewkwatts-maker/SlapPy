"""Extension shim — re-exports from pharos_engine.ai.

This subpackage's canonical home is Pharos Engine.ext.ai.
Import via either path; both are supported.
Requires the [ai] extra: pip install Pharos Engine[ai]
"""
from pharos_engine.ai import *  # noqa: F401, F403
from pharos_engine.ai import __all__  # propagate __all__
