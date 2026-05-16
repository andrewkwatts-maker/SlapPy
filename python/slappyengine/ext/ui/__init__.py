"""Extension shim — re-exports from slappyengine.ui.

This subpackage's canonical home is slappyengine.ext.ui.
Import via either path; both are supported.

Note: slappyengine.ui.editor requires the [editor] extra.
"""
from slappyengine.ui import *  # noqa: F401, F403
from slappyengine.ui import __all__  # propagate __all__
