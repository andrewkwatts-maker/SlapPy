"""SceneNode + Transform3D — Nova3D pillar 5 (parent-transform inheritance).

Provides a lightweight hierarchical scene-graph node with local/world
transforms.  Each ``SceneNode`` may optionally wrap an :class:`Entity`
for rendering.  Parent-transform inheritance is computed lazily via
``world_transform()`` / ``world_matrix()``.

The Rust ``_core.scene_walk.walk_transforms`` kernel accelerates
batched hierarchy traversal; this Python implementation is the
reference / correctness baseline.

Composition rules
-----------------
- Translation:  world_pos = parent_world_pos + parent_world_rot * (parent_scale * local_pos)
- Rotation:     Euler-XYZ chain multiplied through the parent chain
- Scale:        component-wise product

Cycle safety
------------
``add_child()`` walks the parent chain of ``self`` — if ``child`` appears
in that chain, or ``child is self``, ``ValueError`` is raised.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from pharos_engine.entity import Entity


# ---------------------------------------------------------------------------
# Transform3D
# ---------------------------------------------------------------------------


@dataclass
class Transform3D:
    """3D affine transform expressed as position + Euler-XYZ + scale.

    ``rotation_euler`` is stored in radians.  ``scale`` defaults to
    unit (1,1,1) so a default-constructed ``Transform3D`` is the
    identity.
    """

    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_euler: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)

    # ------------------------------------------------------------------
    # Matrix conversion
    # ------------------------------------------------------------------

    def to_matrix(self) -> np.ndarray:
        """Return a 4x4 row-major transform matrix (T * Rz * Ry * Rx * S)."""
        rx, ry, rz = self.rotation_euler
        sx, sy, sz = self.scale
        px, py, pz = self.position

        cx, sxr = np.cos(rx), np.sin(rx)
        cy, syr = np.cos(ry), np.sin(ry)
        cz, szr = np.cos(rz), np.sin(rz)

        # Rotation matrix R = Rz * Ry * Rx (XYZ intrinsic Euler convention).
        # Applies rx first (about local X), then ry, then rz.
        rot = np.array([
            [cz * cy,                    cz * syr * sxr - szr * cx,    cz * syr * cx + szr * sxr,   0.0],
            [szr * cy,                   szr * syr * sxr + cz * cx,    szr * syr * cx - cz * sxr,   0.0],
            [-syr,                       cy * sxr,                     cy * cx,                     0.0],
            [0.0, 0.0, 0.0, 1.0],
        ], dtype=np.float64)

        scale = np.diag([sx, sy, sz, 1.0]).astype(np.float64)
        rs = rot @ scale
        rs[0, 3] = px
        rs[1, 3] = py
        rs[2, 3] = pz
        return rs

    @classmethod
    def identity(cls) -> "Transform3D":
        return cls()

    def compose(self, child: "Transform3D") -> "Transform3D":
        """Return ``self * child`` — child expressed in self's frame."""
        parent_m = self.to_matrix()
        child_m = child.to_matrix()
        world_m = parent_m @ child_m
        return _matrix_to_transform(world_m)


def _matrix_to_transform(m: np.ndarray) -> Transform3D:
    """Decompose a 4x4 matrix into a Transform3D (assumes non-shear)."""
    px, py, pz = float(m[0, 3]), float(m[1, 3]), float(m[2, 3])

    col0 = np.array([m[0, 0], m[1, 0], m[2, 0]], dtype=np.float64)
    col1 = np.array([m[0, 1], m[1, 1], m[2, 1]], dtype=np.float64)
    col2 = np.array([m[0, 2], m[1, 2], m[2, 2]], dtype=np.float64)
    sx = float(np.linalg.norm(col0))
    sy = float(np.linalg.norm(col1))
    sz = float(np.linalg.norm(col2))

    if sx > 1e-12:
        col0 /= sx
    if sy > 1e-12:
        col1 /= sy
    if sz > 1e-12:
        col2 /= sz

    r00, r01, r02 = float(col0[0]), float(col1[0]), float(col2[0])
    r10, r11, r12 = float(col0[1]), float(col1[1]), float(col2[1])
    r20, r21, r22 = float(col0[2]), float(col1[2]), float(col2[2])

    # Inverse of R = Rz * Ry * Rx (XYZ intrinsic Euler)
    # R[2,0] = -sin(ry), R[2,1] = cy*sx, R[2,2] = cy*cx
    # R[1,0] = sz*cy,   R[0,0] = cz*cy
    ry = float(np.arcsin(max(-1.0, min(1.0, -r20))))
    if abs(r20) < 0.99999:
        rx = float(np.arctan2(r21, r22))
        rz = float(np.arctan2(r10, r00))
    else:
        # Gimbal lock fallback: fold rz into rx
        rx = float(np.arctan2(-r12, r11))
        rz = 0.0

    return Transform3D(
        position=(px, py, pz),
        rotation_euler=(rx, ry, rz),
        scale=(sx, sy, sz),
    )


# ---------------------------------------------------------------------------
# SceneNode
# ---------------------------------------------------------------------------


class SceneNode:
    """A hierarchical scene-graph node with parent-transform inheritance.

    Each node owns a local ``Transform3D``; world-space transforms are
    computed on demand by walking the parent chain.  An optional
    :class:`Entity` may be attached for rendering.
    """

    def __init__(
        self,
        name: str = "",
        local_transform: Transform3D | None = None,
        entity: "Entity | None" = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.name: str = name
        self.local_transform: Transform3D = (
            local_transform if local_transform is not None else Transform3D()
        )
        self.parent: "SceneNode | None" = None
        self.children: list["SceneNode"] = []
        self.entity: "Entity | None" = entity
        self.metadata: dict[str, Any] = metadata if metadata is not None else {}

    # ------------------------------------------------------------------
    # Hierarchy management
    # ------------------------------------------------------------------

    def add_child(self, child: "SceneNode") -> None:
        """Attach *child* as a direct descendant of this node.

        Raises ``ValueError`` if the operation would create a cycle
        (i.e. ``child`` is an ancestor of ``self``, or ``child is self``).
        """
        if child is self:
            raise ValueError("SceneNode.add_child: cannot add a node as its own child")

        # Walk own parent chain to ensure `child` is not already an ancestor
        cursor: "SceneNode | None" = self
        while cursor is not None:
            if cursor is child:
                raise ValueError(
                    f"SceneNode.add_child: adding {child.name!r} under {self.name!r} "
                    "would create a cycle"
                )
            cursor = cursor.parent

        # Detach from previous parent, if any
        if child.parent is not None and child in child.parent.children:
            child.parent.children.remove(child)

        child.parent = self
        self.children.append(child)

    def remove_child(self, child: "SceneNode") -> None:
        """Detach *child* from this node.  No-op if not a direct child."""
        if child in self.children:
            self.children.remove(child)
            child.parent = None

    # ------------------------------------------------------------------
    # World-space transform
    # ------------------------------------------------------------------

    def world_transform(self) -> Transform3D:
        """Compose local transforms up the parent chain to world space."""
        chain: list[SceneNode] = []
        cursor: "SceneNode | None" = self
        while cursor is not None:
            chain.append(cursor)
            cursor = cursor.parent
        # Root-first
        chain.reverse()

        world = Transform3D.identity()
        for node in chain:
            world = world.compose(node.local_transform)
        return world

    def world_matrix(self) -> np.ndarray:
        """Return the 4x4 world-space matrix for this node."""
        cursor: "SceneNode | None" = self
        chain: list[SceneNode] = []
        while cursor is not None:
            chain.append(cursor)
            cursor = cursor.parent
        chain.reverse()

        m = np.eye(4, dtype=np.float64)
        for node in chain:
            m = m @ node.local_transform.to_matrix()
        return m

    # ------------------------------------------------------------------
    # Traversal
    # ------------------------------------------------------------------

    def walk(self) -> Iterator["SceneNode"]:
        """Depth-first traversal — yields self, then each subtree in order."""
        yield self
        for child in self.children:
            yield from child.walk()

    def find_by_name(self, name: str) -> "SceneNode | None":
        """Return the first descendant (or self) whose ``name`` matches."""
        for node in self.walk():
            if node.name == name:
                return node
        return None

    # ------------------------------------------------------------------
    # Debug
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"SceneNode(name={self.name!r}, "
            f"children={len(self.children)}, "
            f"pos={self.local_transform.position})"
        )
