"""``slappyengine.actions`` — headless-safe callbacks for editor menu actions.

Every ``ToolRouter`` action in :mod:`slappyengine.tool_router` that
mutates persistent state (project files, editor layout, entity clipboard)
lives here as a small pure Python helper so it can be unit-tested without
spinning up the DPG-backed editor shell.

Design provenance
-----------------

* ``docs/engine_feature_map_2026_07_04.md`` §"Top 10 Broken/Stub Fixes"
  identified five action ids that had no Python fallback wired in the
  router — this module is their landing site.
* ``docs/tool_routing_2026_06_07.md`` §5 recommends a per-action helper
  module so tests can invoke the callback with a synthetic ``ctx``
  dict (no shell, no DPG).

Each helper takes a single ``ctx: dict`` argument matching the router's
Python-fallback signature, resolves whichever shell / registry / clipboard
handle it needs from that dict (or falls back to a headless-safe default),
and returns a small result dict describing what happened. Return values
are used by the tests and by editor status-bar toast strings; a ``None``
return means "no-op" (missing dependency / cancelled by user).
"""
from __future__ import annotations

from .project_actions import (
    save_project as save_project,
    new_project as new_project,
    open_recent as open_recent,
)
from .view_actions import reset_layout as reset_layout
from .edit_actions import duplicate_selection as duplicate_selection


__all__ = [
    "save_project",
    "new_project",
    "open_recent",
    "reset_layout",
    "duplicate_selection",
]
