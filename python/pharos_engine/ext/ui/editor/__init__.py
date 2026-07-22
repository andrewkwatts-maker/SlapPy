"""Extension shim — re-exports from pharos_engine.ui.editor.

This subpackage's canonical home is SlapPyEngine.ext.ui.editor.
Import via either path; both are supported.
Requires the [editor] extra: pip install SlapPyEngine[editor]
"""
from pharos_engine.ui.editor import *  # noqa: F401, F403
from pharos_engine.ui.editor import __all__  # propagate __all__
