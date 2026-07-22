"""Extension shim — re-exports from pharos_engine.ui.

This subpackage's canonical home is SlapPyEngine.ext.ui.
Import via either path; both are supported.

Note: SlapPyEngine.ui.editor requires the [editor] extra.
"""
from pharos_engine.ui import *  # noqa: F401, F403
from pharos_engine.ui import __all__  # propagate __all__
