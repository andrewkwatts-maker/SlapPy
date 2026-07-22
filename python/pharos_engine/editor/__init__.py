"""Editor-side scripting surface.

The :mod:`pharos_engine.editor` package hosts modules meant for interactive
work inside the running editor — most notably :mod:`pharos_engine.editor.helpers`,
which surfaces 20+ one-liner functions the user can invoke from the
Python REPL panel to shape the current scene without wading through the
full :class:`pharos_engine.App` API.

This package is intentionally free of any DearPyGui import at the top so
``import pharos_engine.editor`` stays cheap for headless callers.
"""
from __future__ import annotations

from pharos_engine.editor import helpers as helpers  # re-export as submodule

__all__ = ["helpers"]
