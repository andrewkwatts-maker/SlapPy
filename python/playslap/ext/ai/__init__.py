"""Extension shim — re-exports from playslap.ai.

This subpackage's canonical home is playslap.ext.ai.
Import via either path; both are supported.
Requires the [ai] extra: pip install playslap[ai]
"""
from playslap.ai import *  # noqa: F401, F403
from playslap.ai import __all__  # propagate __all__
