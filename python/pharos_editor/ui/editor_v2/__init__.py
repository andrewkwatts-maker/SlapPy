"""Pharos editor v2 — imgui-bundle backend for Nova3D-parity docking.

The v1 editor at :mod:`pharos_editor.ui.editor` runs on DearPyGui,
which does not expose dear-imgui's ``DockBuilder`` API to Python.
Consequence: floating windows only, no programmatic split-and-tab
layout, panels overlap on boot.

v2 uses `imgui-bundle` (pyimgui-bundle's Python binding around
dear-imgui + Hello ImGui). Hello ImGui's :class:`DockingParams` +
:class:`DockingSplit` API is the direct Python equivalent of what
Nova3D's ``EditorApplication::RenderDockSpace`` does — same split-
node scaffold, same tab-merge affordances, same layout persistence
via ``imgui.ini``.

v2 ships side-by-side with v1 while we migrate panels one at a time.
Once every notebook panel has an imgui-bundle build path, v1
becomes opt-in and eventually retired.

Entry points:
    pharos-edit         v1 (DPG editor, current default)
    pharos-edit-v2      v2 (imgui-bundle editor, new)

Run: ``python -m pharos_editor.ui.editor_v2``
"""
from __future__ import annotations

__all__ = []
