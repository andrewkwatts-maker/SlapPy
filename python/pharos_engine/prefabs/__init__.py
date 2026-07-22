"""``pharos_engine.prefabs`` — reusable entity templates via ``.prefab.yaml``.

A *prefab* is a small YAML recipe that describes one entity (or a
composition of entities) so spawn cards, level authoring tools, and
gameplay code can share definitions. Every prefab bundles:

* A body-spec dict — the shape passed to a
  :class:`pharos_engine.dynamics.World` builder (one of the seven
  supported kinds: ``point`` / ``circle`` / ``box`` / ``rope`` /
  ``ragdoll`` / ``chain`` / ``composite``).
* Optional joint-spec dicts wired between the primary body's nodes.
* Optional child prefab names for composition.
* Free-form metadata for editor / gameplay tagging.

Prefabs are managed by :class:`PrefabLibrary`, which mirrors the
:class:`pharos_editor.ui.theme.user_themes.UserThemeStore` pattern:
baked files ship inside the wheel at
``python/pharos_engine/prefabs/baked/`` and are copied into
``~/.pharos_engine/prefabs/`` on first use so downstream code can edit
them without touching the installed package.

Two-line usage::

    lib = PrefabLibrary()
    lib.load_baked()                  # register the 6 shipping prefabs
    prefab = lib.get("crate")
    bodies = prefab.spawn(world, (0.0, 0.0))
"""
from __future__ import annotations

from .library import PrefabLibrary
from .prefab import CATEGORIES, Prefab
from .preview_baker import DIARY_PALETTE, PreviewBaker

__all__ = [
    "CATEGORIES",
    "DIARY_PALETTE",
    "Prefab",
    "PrefabLibrary",
    "PreviewBaker",
]
