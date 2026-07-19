"""Editor-side scripting surface.

The :mod:`slappyengine.editor` package hosts modules meant for interactive
work inside the running editor — most notably :mod:`slappyengine.editor.helpers`,
which surfaces 20+ one-liner functions the user can invoke from the
Python REPL panel to shape the current scene without wading through the
full :class:`slappyengine.App` API.

This package is intentionally free of any DearPyGui import at the top so
``import slappyengine.editor`` stays cheap for headless callers.
"""
from __future__ import annotations

from slappyengine.editor import helpers as helpers  # re-export as submodule

__all__ = ["helpers"]
