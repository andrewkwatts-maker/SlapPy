"""Extension shim — re-exports from slappyengine.ui.

This subpackage's canonical home is SlapPyEngine.ext.ui.
Import via either path; both are supported.

Note: SlapPyEngine.ui.editor requires the [editor] extra.
"""
from slappyengine.ui import *  # noqa: F401, F403
from slappyengine.ui import __all__  # propagate __all__
