"""Extension shim — re-exports from playslap.ui.editor.

This subpackage's canonical home is playslap.ext.ui.editor.
Import via either path; both are supported.
Requires the [editor] extra: pip install playslap[editor]
"""
from playslap.ui.editor import *  # noqa: F401, F403
from playslap.ui.editor import __all__  # propagate __all__
