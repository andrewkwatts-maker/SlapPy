"""``slappyengine.scenes`` — YAML scene serialisation (FF3).

A *scene* is a lightweight authoring document that describes the
entities placed into a :class:`slappyengine.dynamics.World`. Each scene
round-trips through YAML (``*.scene.yaml``) so hand-editing, VCS diffs,
and headless editor tooling all use the same on-disk shape.

Two-line usage::

    from slappyengine.scenes import Scene, SceneFile, SceneRegistry
    scene = SceneFile.read("levels/pit.scene.yaml")

Module layout
~~~~~~~~~~~~~

* :mod:`slappyengine.scenes.scene` — :class:`Scene` dataclass with
  :meth:`Scene.add_entity` / :meth:`Scene.apply_to_world` /
  :meth:`Scene.snapshot_from_world` / :meth:`Scene.to_yaml`.
* :mod:`slappyengine.scenes.scene_file` — :class:`SceneFile` static
  read/write/validate helpers with atomic writes.
* :mod:`slappyengine.scenes.scene_registry` — :class:`SceneRegistry`
  filesystem discovery + in-memory cache.

The subpackage is deliberately named ``scenes`` (plural) to avoid
shadowing the runtime :mod:`slappyengine.scene` module, which owns the
live :class:`~slappyengine.scene.Scene` (entities, event bus, GPU state).
The serialisation :class:`Scene` here is a separate, disk-shaped
authoring type.
"""
from __future__ import annotations

from .scene import (
    SCHEMA_VERSION,
    Scene,
    SceneValidationError,
)
from .scene_file import SCENE_SUFFIX, SceneFile
from .scene_registry import SceneRegistry

__all__ = [
    "SCENE_SUFFIX",
    "SCHEMA_VERSION",
    "Scene",
    "SceneFile",
    "SceneRegistry",
    "SceneValidationError",
]
