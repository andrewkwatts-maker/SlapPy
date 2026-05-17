"""Extension shim — re-exports from slappyengine.net.

This subpackage's canonical home is SlapPyEngine.ext.net.
Import via either path; both are supported.
Requires the [network] extra: pip install SlapPyEngine[network]
"""
from slappyengine.net import *  # noqa: F401, F403
from slappyengine.net import __all__  # propagate __all__
