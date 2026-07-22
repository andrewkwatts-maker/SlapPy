"""PharosEditor: notebook-style editor for PharosEngine.

Ships as a separate PyPI wheel (``pharos-editor``) that depends on
``pharos-engine``. The editor is optional at runtime — an ``App`` boots
without it when ``enable_editor=False`` (the default).

Contents:
- ``ui/``           DearPyGui panels, themes, gizmos, notebook shell
- ``editor/``       scripting helpers for the running editor
- ``actions/``      editor command actions (edit, select, layer, panel...)
- ``tool_router``   routes UI events to engine mutations
"""
from __future__ import annotations

__version__ = "0.3.0b1"
__author__ = "PharosEngine Contributors"
