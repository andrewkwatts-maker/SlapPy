"""Skinned-mesh and skeleton data types for the glTF importer (JJ3).

A skinned mesh is a mesh whose vertices are influenced by a hierarchy of
"joints" (bones). At runtime, each vertex is transformed by a weighted
blend of the joint transforms (typically 4-way, matching glTF's
`JOINTS_0` / `WEIGHTS_0` vertex-attribute pair).

This module defines three CPU-side dataclasses that mirror the glTF
skinning model:

* :class:`SkinnedMeshData` — a normal :class:`GpuMesh`-compatible mesh
  augmented with per-vertex ``joints_0`` (Nx4 uint16) + ``weights_0``
  (Nx4 float32) tables, plus a reference to the :class:`Skeleton` and
  the joint-space inverse-bind matrices.
* :class:`SkeletonNode` — a single joint: name, index, parent link,
  local TRS pose, children, inverse-bind matrix.
* :class:`Skeleton` — the full joint hierarchy.

The runtime animation system (JJ4 —
``python/pharos_engine/animation/skeleton.py``) consumes these structures
to build a bone-palette matrix for the vertex shader.

Design notes
------------
* Joint indices are stored as ``uint16`` even when the source glTF uses
  ``uint8``, so downstream code has a single canonical dtype.
* Weights are normalised to sum to 1.0 per vertex when the source data
  does not (glTF allows either). The importer normalises eagerly; the
  dataclass itself does not enforce the invariant so hand-constructed
  test cases remain simple.
* Inverse-bind matrices are stored in column-major order (glTF native)
  as ``float32`` ``(K, 4, 4)`` arrays. Numpy's default row-major layout
  is preserved; consumers that need column-major GPU uploads must
  transpose.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class SkeletonNode:
    """A single joint (bone) in a skeleton.

    Parameters
    ----------
    name
        Joint name from the glTF ``node.name`` field. Falls back to
        ``joint_{index}`` when unnamed.
    index
        Absolute node index in the source glTF's ``nodes`` array. This
        is the value that appears in ``JOINTS_0`` after being remapped
        by ``skin.joints`` — importers should preserve it so downstream
        animation code can match track targets to joints.
    parent_index
        Absolute node index of the parent joint, or ``None`` for the
        root joint of the skeleton.
    local_translation
        Local-space translation (x, y, z) from the source node.
    local_rotation
        Local-space rotation as a quaternion (x, y, z, w). glTF stores
        quaternions in xyzw order; we preserve that convention.
    local_scale
        Local-space scale (x, y, z).
    children
        Absolute node indices of child joints. Empty for leaf joints.
    inverse_bind_matrix
        4x4 float32 matrix that transforms a vertex from mesh space into
        the joint's local bind-pose space. Identity for the bind pose.
    """

    name: str
    index: int
    parent_index: int | None
    local_translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    local_rotation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    local_scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    children: list[int] = field(default_factory=list)
    inverse_bind_matrix: np.ndarray = field(
        default_factory=lambda: np.eye(4, dtype=np.float32)
    )

    def is_root(self) -> bool:
        """Return ``True`` when this joint has no parent."""
        return self.parent_index is None


@dataclass
class Skeleton:
    """A full joint hierarchy attached to one or more skinned meshes.

    Parameters
    ----------
    nodes
        Flat list of :class:`SkeletonNode` instances. ``nodes[i]`` is
        the ``i``-th joint in the skeleton's own indexing (i.e. the
        value stored in ``JOINTS_0`` after glTF remapping). Note that
        ``SkeletonNode.index`` retains the original glTF node index for
        cross-referencing with the scene graph.
    root_index
        Index into ``nodes`` of the root joint. Multiple root joints
        are not supported — pick the shallowest.
    name
        Human-readable name; usually the glTF ``skin.name`` field or
        derived from the skeleton root joint's name.
    """

    nodes: list[SkeletonNode] = field(default_factory=list)
    root_index: int = 0
    name: str = "skeleton"

    def joint_count(self) -> int:
        return len(self.nodes)

    def get_root(self) -> SkeletonNode | None:
        if not self.nodes:
            return None
        return self.nodes[self.root_index]

    def children_of(self, joint_local_index: int) -> list[int]:
        """Return the *local* (into ``self.nodes``) indices of children.

        Note the difference between local (indexes into ``self.nodes``)
        and absolute (node index in the source glTF) — this helper
        translates on the fly so tree-walkers can use a single index
        space.
        """
        node = self.nodes[joint_local_index]
        # Build a lookup of absolute node index -> local index once.
        # For small skeletons a linear scan is fine.
        abs_to_local = {n.index: i for i, n in enumerate(self.nodes)}
        return [abs_to_local[c] for c in node.children if c in abs_to_local]


@dataclass
class SkinnedMeshData:
    """A mesh with joint / weight vertex attributes and a skeleton link.

    ``mesh`` is a normal mesh handle (a :class:`GpuMesh` or a dict, per
    the :func:`_build_mesh_from_primitive` convention). The skinning
    payload lives alongside it so a static consumer can ignore the
    attributes entirely by reading ``.mesh``.

    Parameters
    ----------
    mesh
        Underlying static mesh (positions / normals / UVs / indices).
    joints_0
        Optional (N, 4) uint16 array — per-vertex joint indices. May be
        ``None`` for defensive access, though a real skinned mesh
        always has one.
    weights_0
        Optional (N, 4) float32 array — per-vertex bone weights,
        normalised so each row sums to 1.0.
    inverse_bind_matrices
        Optional (K, 4, 4) float32 array — one matrix per joint.
        Identity when the mesh happens to be authored at bind pose.
    skeleton
        Optional :class:`Skeleton` describing the joint hierarchy.
    skeleton_joints
        Ordered list of absolute node indices — the joints the
        vertex-attribute JOINTS_0 refers into. Equivalent to
        glTF's ``skin.joints`` field.
    skin_root_joint
        Absolute node index of the skeleton's root, or ``None`` when
        the glTF omits it (allowed — consumers walk the ``skeleton``
        instead).
    name
        Human-readable label; defaults to ``skinned_mesh``.
    """

    mesh: Any
    joints_0: np.ndarray | None = None
    weights_0: np.ndarray | None = None
    inverse_bind_matrices: np.ndarray | None = None
    skeleton: Skeleton | None = None
    skeleton_joints: list[int] = field(default_factory=list)
    skin_root_joint: int | None = None
    name: str = "skinned_mesh"

    def vertex_count(self) -> int:
        """Number of vertices in the underlying mesh (via joints table)."""
        if self.joints_0 is None:
            # Fall back to poking the underlying mesh.
            m = self.mesh
            if hasattr(m, "vertex_count"):
                v = m.vertex_count
                return int(v() if callable(v) else v)
            if isinstance(m, dict) and "vertex_count" in m:
                return int(m["vertex_count"])
            if isinstance(m, dict) and "vertices" in m:
                return len(m["vertices"])
            return 0
        return int(self.joints_0.shape[0])

    def joint_count(self) -> int:
        """Number of joints in the attached skeleton (or 0)."""
        if self.skeleton is None:
            return 0
        return self.skeleton.joint_count()

    def is_valid(self) -> bool:
        """Return ``True`` when required skinning attributes are present."""
        return (
            self.joints_0 is not None
            and self.weights_0 is not None
            and self.joints_0.shape == self.weights_0.shape
            and self.joints_0.ndim == 2
            and self.joints_0.shape[1] == 4
        )
