"""Extension shim — re-exports from playslap.net.

This subpackage's canonical home is playslap.ext.net.
Import via either path; both are supported.
Requires the [network] extra: pip install playslap[network]
"""
from playslap.net import *  # noqa: F401, F403
from playslap.net import __all__  # propagate __all__
