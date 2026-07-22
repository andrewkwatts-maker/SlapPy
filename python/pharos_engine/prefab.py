"""Prefab I/O — Nova3D pillar 5 (prefab YAML serialisation + instantiation).

A :class:`Prefab` wraps a root :class:`SceneNode` sub-tree plus an
optional variant/override map, and provides YAML round-trip and
deep-copy instantiation.  Prefabs are the primary content-authoring
unit for Nova3D scenes.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from pharos_engine.scene_node import SceneNode, Transform3D


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------


def _node_to_dict(node: SceneNode) -> dict[str, Any]:
    return {
        "name": node.name,
        "transform": {
            "position": list(node.local_transform.position),
            "rotation_euler": list(node.local_transform.rotation_euler),
            "scale": list(node.local_transform.scale),
        },
        "metadata": dict(node.metadata),
        "children": [_node_to_dict(c) for c in node.children],
    }


def _dict_to_node(data: dict[str, Any]) -> SceneNode:
    tdata = data.get("transform", {})
    tf = Transform3D(
        position=tuple(tdata.get("position", (0.0, 0.0, 0.0))),
        rotation_euler=tuple(tdata.get("rotation_euler", (0.0, 0.0, 0.0))),
        scale=tuple(tdata.get("scale", (1.0, 1.0, 1.0))),
    )
    node = SceneNode(
        name=data.get("name", ""),
        local_transform=tf,
        metadata=dict(data.get("metadata", {})),
    )
    for cdata in data.get("children", []):
        node.add_child(_dict_to_node(cdata))
    return node


# ---------------------------------------------------------------------------
# Prefab
# ---------------------------------------------------------------------------


@dataclass
class Prefab:
    """A reusable scene sub-tree, YAML-serialisable and deep-copyable."""

    root: SceneNode
    overrides: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # YAML round-trip
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> None:
        payload = {
            "version": 1,
            "root": _node_to_dict(self.root),
            "overrides": dict(self.overrides),
        }
        Path(path).write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Prefab":
        text = Path(path).read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
        root = _dict_to_node(data.get("root", {"name": "root"}))
        overrides = dict(data.get("overrides", {}))
        return cls(root=root, overrides=overrides)

    # ------------------------------------------------------------------
    # Instantiation
    # ------------------------------------------------------------------

    def instantiate(self, parent: SceneNode | None = None) -> SceneNode:
        """Deep-copy this prefab's root tree and optionally attach it.

        The returned node (and its subtree) is completely independent
        of the prefab — mutating the instance does not mutate the
        template.
        """
        cloned_root = _clone_subtree(self.root)
        if parent is not None:
            parent.add_child(cloned_root)
        return cloned_root


def _clone_subtree(node: SceneNode) -> SceneNode:
    """Return an independent deep copy of *node* and its descendants.

    Entity references are shallow-copied (deep-copying arbitrary
    entities is unsafe — scripts, GPU handles etc.), but transforms,
    metadata and the tree structure are fully cloned.
    """
    new_tf = Transform3D(
        position=tuple(node.local_transform.position),
        rotation_euler=tuple(node.local_transform.rotation_euler),
        scale=tuple(node.local_transform.scale),
    )
    new_node = SceneNode(
        name=node.name,
        local_transform=new_tf,
        entity=node.entity,  # shallow — see docstring
        metadata=copy.deepcopy(node.metadata),
    )
    for child in node.children:
        new_node.add_child(_clone_subtree(child))
    return new_node
