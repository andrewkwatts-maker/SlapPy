"""Extension shim — re-exports from slappyengine.net.

This subpackage's canonical home is slappyengine.ext.net.
Import via either path; both are supported.
Requires the [network] extra: pip install slappyengine[network]
"""
from slappyengine.net import *  # noqa: F401, F403
from slappyengine.net import __all__  # propagate __all__
