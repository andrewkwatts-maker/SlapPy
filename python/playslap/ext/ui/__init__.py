"""Extension shim — re-exports from playslap.ui.

This subpackage's canonical home is playslap.ext.ui.
Import via either path; both are supported.

Note: playslap.ui.editor requires the [editor] extra.
"""
from playslap.ui import *  # noqa: F401, F403
from playslap.ui import __all__  # propagate __all__
