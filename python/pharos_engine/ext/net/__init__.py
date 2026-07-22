"""Extension shim — re-exports from pharos_engine.net.

This subpackage's canonical home is Pharos Engine.ext.net.
Import via either path; both are supported.
Requires the [network] extra: pip install Pharos Engine[network]
"""
from pharos_engine.net import *  # noqa: F401, F403
from pharos_engine.net import __all__  # propagate __all__
