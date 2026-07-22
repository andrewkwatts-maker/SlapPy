"""Skeleton runtime — mutable pose state + global matrix palette.

This module ships two headline types:

* :class:`PoseState` — the mutable per-frame pose (translations,
  rotations, scales) for every joint of a skeleton.
* :class:`PosedSkeleton` — a skeleton bound to a live :class:`PoseState`
  that exposes joint-space mutators, bind-pose reset, and topological
  hierarchy walks to produce global-space matrices + skinning-palette
  matrices.

The runtime is designed to plug into the JJ3
``asset_import/skinned_mesh.py`` loader output. Until that lands we
also ship compatible fallback ``Skeleton`` / ``SkeletonNode`` /
``SkinnedMeshData`` dataclasses so downstream code can be developed
against a stable API.

Notes
-----
Quaternions use ``(x, y, z, w)`` layout throughout, matching glTF.
Matrices are row-major ``float32`` ``(4, 4)`` numpy arrays. When
composing transforms we follow ``M = T * R * S`` (standard skeletal
animation convention — scale is applied first in the local frame, then
rotation, then translation).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Fallback Skeleton / SkinnedMeshData dataclasses (JJ3-compatible shim)
# ---------------------------------------------------------------------------

@dataclass
class SkeletonNode:
    """A single joint in a skeleton.

    Parameters
    ----------
    name
        Human-readable joint name (matches glTF ``node.name``).
    parent_index
        Index into the owning ``Skeleton.nodes`` list, or ``-1`` for a
        root joint. Must be strictly less than the child's own index —
        the node array must be topologically pre-sorted.
    translation
        Bind-pose local translation.
    rotation
        Bind-pose local rotation as a ``(x, y, z, w)`` quaternion.
    scale
        Bind-pose local scale.
    """
    name: str
    parent_index: int
    translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)


@dataclass
class Skeleton:
    """A skeleton — a topologically-ordered list of joints.

    Parameters
    ----------
    nodes
        The joint list. Node ``i``'s ``parent_index`` must be ``< i``
        (roots use ``-1``); this lets us walk the hierarchy in one
        forward pass to compute global matrices.
    inverse_bind_matrices
        Optional ``(N, 4, 4)`` float32 IBMs from the source asset. When
        ``None`` the runtime computes them from the bind pose on first
        request.
    """
    nodes: list[SkeletonNode] = field(default_factory=list)
    inverse_bind_matrices: np.ndarray | None = None

    @property
    def joint_count(self) -> int:
        return len(self.nodes)

    def parent_indices(self) -> np.ndarray:
        """Return parent indices as a ``(N,)`` int32 array."""
        return np.array(
            [n.parent_index for n in self.nodes], dtype=np.int32
        )


@dataclass
class SkinnedMeshData:
    """Container for a skinned mesh's CPU-side vertex attributes.

    Parameters
    ----------
    positions
        ``(V, 3)`` float32 bind-pose vertex positions.
    normals
        ``(V, 3)`` float32 bind-pose vertex normals. May be ``None``.
    joints
        ``(V, 4)`` int32 joint indices per vertex.
    weights
        ``(V, 4)`` float32 blend weights per vertex (should sum to ~1).
    indices
        Optional ``(F,)`` int32 triangle indices.
    """
    positions: np.ndarray
    joints: np.ndarray
    weights: np.ndarray
    normals: np.ndarray | None = None
    indices: np.ndarray | None = None

    @property
    def vertex_count(self) -> int:
        return int(self.positions.shape[0])


# ---------------------------------------------------------------------------
# Small matrix helpers (row-major, right-multiply convention)
# ---------------------------------------------------------------------------

def _quat_to_mat3(q: np.ndarray) -> np.ndarray:
    """Convert an ``(x, y, z, w)`` quaternion to a 3x3 rotation matrix.

    Follows the standard glTF / Hamilton right-handed convention.
    """
    x, y, z, w = float(q[0]), float(q[1]), float(q[2]), float(q[3])
    xx = x * x
    yy = y * y
    zz = z * z
    xy = x * y
    xz = x * z
    yz = y * z
    wx = w * x
    wy = w * y
    wz = w * z
    m = np.empty((3, 3), dtype=np.float32)
    m[0, 0] = 1.0 - 2.0 * (yy + zz)
    m[0, 1] = 2.0 * (xy - wz)
    m[0, 2] = 2.0 * (xz + wy)
    m[1, 0] = 2.0 * (xy + wz)
    m[1, 1] = 1.0 - 2.0 * (xx + zz)
    m[1, 2] = 2.0 * (yz - wx)
    m[2, 0] = 2.0 * (xz - wy)
    m[2, 1] = 2.0 * (yz + wx)
    m[2, 2] = 1.0 - 2.0 * (xx + yy)
    return m


def compose_trs(
    translation: np.ndarray,
    rotation: np.ndarray,
    scale: np.ndarray,
) -> np.ndarray:
    """Compose a ``(4, 4)`` TRS matrix from local T/R/S components.

    ``M = T * R * S`` — scale first, then rotate, then translate.
    """
    m = np.eye(4, dtype=np.float32)
    rot3 = _quat_to_mat3(rotation)
    # Bake scale into the rotation columns so M[:3, :3] = R @ diag(S)
    m[:3, 0] = rot3[:, 0] * float(scale[0])
    m[:3, 1] = rot3[:, 1] * float(scale[1])
    m[:3, 2] = rot3[:, 2] * float(scale[2])
    m[:3, 3] = translation.astype(np.float32)
    return m


def _mat_invert_affine(m: np.ndarray) -> np.ndarray:
    """Invert an affine ``(4, 4)`` matrix (no perspective row).

    Uses ``np.linalg.inv`` — fine for the modest sizes we deal with.
    """
    return np.linalg.inv(m).astype(np.float32)


# ---------------------------------------------------------------------------
# PoseState + PosedSkeleton
# ---------------------------------------------------------------------------

@dataclass
class PoseState:
    """Mutable per-frame joint pose.

    Every attribute is a numpy float32 array sized on joint count. The
    ``dirty`` flag lets :class:`PosedSkeleton` cache global matrices
    across calls that don't touch pose state.
    """
    joint_translations: np.ndarray      # (N, 3) float32
    joint_rotations: np.ndarray         # (N, 4) float32 (x, y, z, w)
    joint_scales: np.ndarray            # (N, 3) float32
    dirty: bool = True

    @classmethod
    def zeros(cls, joint_count: int) -> "PoseState":
        """Allocate a bind-neutral pose (all identity transforms)."""
        return cls(
            joint_translations=np.zeros((joint_count, 3), dtype=np.float32),
            joint_rotations=np.tile(
                np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32),
                (joint_count, 1),
            ),
            joint_scales=np.ones((joint_count, 3), dtype=np.float32),
            dirty=True,
        )

    def copy(self) -> "PoseState":
        return PoseState(
            joint_translations=self.joint_translations.copy(),
            joint_rotations=self.joint_rotations.copy(),
            joint_scales=self.joint_scales.copy(),
            dirty=True,
        )


class PosedSkeleton:
    """A skeleton bound to a live :class:`PoseState`.

    The class owns a :class:`PoseState` initialised from the skeleton's
    bind pose. Callers mutate it through :meth:`set_joint_local` (which
    flips the ``dirty`` flag) and pull global matrices via
    :meth:`compute_global_matrices`. The global-matrix cache is
    invalidated on every mutator call.
    """

    def __init__(self, skeleton: Any) -> None:
        if skeleton is None or not hasattr(skeleton, "nodes"):
            raise TypeError(
                "PosedSkeleton expects a Skeleton with a .nodes list; "
                f"got {type(skeleton).__name__}"
            )
        self.skeleton = skeleton
        n = skeleton.joint_count
        self.pose = PoseState.zeros(n)
        self._bind_translations = np.zeros((n, 3), dtype=np.float32)
        self._bind_rotations = np.tile(
            np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32), (n, 1)
        )
        self._bind_scales = np.ones((n, 3), dtype=np.float32)
        self._parent_indices = skeleton.parent_indices()
        for i, node in enumerate(skeleton.nodes):
            self._bind_translations[i] = np.asarray(
                node.translation, dtype=np.float32
            )
            self._bind_rotations[i] = np.asarray(
                node.rotation, dtype=np.float32
            )
            self._bind_scales[i] = np.asarray(node.scale, dtype=np.float32)
        # Seed pose from bind.
        self.reset_to_bind_pose()
        # Cached globals — allocated lazily.
        self._global_matrices: np.ndarray | None = None

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------

    def set_joint_local(
        self,
        joint_index: int,
        translation: np.ndarray | tuple | None = None,
        rotation: np.ndarray | tuple | None = None,
        scale: np.ndarray | tuple | None = None,
    ) -> None:
        """Overwrite a joint's local transform.

        Any of ``translation`` / ``rotation`` / ``scale`` left as
        ``None`` keeps the existing value. Flips ``dirty``.
        """
        if not (0 <= joint_index < self.skeleton.joint_count):
            raise IndexError(
                f"joint_index {joint_index} out of range "
                f"[0, {self.skeleton.joint_count})"
            )
        if translation is not None:
            self.pose.joint_translations[joint_index] = np.asarray(
                translation, dtype=np.float32
            )
        if rotation is not None:
            self.pose.joint_rotations[joint_index] = np.asarray(
                rotation, dtype=np.float32
            )
        if scale is not None:
            self.pose.joint_scales[joint_index] = np.asarray(
                scale, dtype=np.float32
            )
        self.pose.dirty = True
        self._global_matrices = None

    def reset_to_bind_pose(self) -> None:
        """Copy the stored bind transforms back into the live pose."""
        np.copyto(self.pose.joint_translations, self._bind_translations)
        np.copyto(self.pose.joint_rotations, self._bind_rotations)
        np.copyto(self.pose.joint_scales, self._bind_scales)
        self.pose.dirty = True
        self._global_matrices = None

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def compute_global_matrices(self) -> np.ndarray:
        """Return ``(N, 4, 4)`` global-space matrices for every joint.

        Walks the topologically sorted node list once. Cached until the
        next mutator call.
        """
        if self._global_matrices is not None and not self.pose.dirty:
            return self._global_matrices

        n = self.skeleton.joint_count
        globals_ = np.empty((n, 4, 4), dtype=np.float32)
        parents = self._parent_indices
        trans = self.pose.joint_translations
        rots = self.pose.joint_rotations
        scales = self.pose.joint_scales
        for i in range(n):
            local = compose_trs(trans[i], rots[i], scales[i])
            p = int(parents[i])
            if p < 0:
                globals_[i] = local
            else:
                globals_[i] = globals_[p] @ local
        self._global_matrices = globals_
        self.pose.dirty = False
        return globals_

    def compute_skinning_palette(
        self, inverse_bind_matrices: np.ndarray | None = None
    ) -> np.ndarray:
        """Return ``(N, 4, 4)`` skinning matrices = global * IBM.

        When ``inverse_bind_matrices`` is ``None`` we compute them from
        the skeleton's bind pose (this is the JJ3 fallback path).
        """
        globals_ = self.compute_global_matrices()
        n = self.skeleton.joint_count
        if inverse_bind_matrices is None:
            inverse_bind_matrices = self._compute_bind_ibms()
        else:
            inverse_bind_matrices = np.asarray(
                inverse_bind_matrices, dtype=np.float32
            )
            if inverse_bind_matrices.shape != (n, 4, 4):
                raise ValueError(
                    "inverse_bind_matrices must be shape (N, 4, 4) with "
                    f"N == joint_count; got {inverse_bind_matrices.shape}"
                )
        palette = np.empty((n, 4, 4), dtype=np.float32)
        for i in range(n):
            palette[i] = globals_[i] @ inverse_bind_matrices[i]
        return palette

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _compute_bind_ibms(self) -> np.ndarray:
        """Compute inverse-bind matrices from the stored bind pose."""
        n = self.skeleton.joint_count
        parents = self._parent_indices
        bind_globals = np.empty((n, 4, 4), dtype=np.float32)
        for i in range(n):
            local = compose_trs(
                self._bind_translations[i],
                self._bind_rotations[i],
                self._bind_scales[i],
            )
            p = int(parents[i])
            if p < 0:
                bind_globals[i] = local
            else:
                bind_globals[i] = bind_globals[p] @ local
        ibms = np.empty_like(bind_globals)
        for i in range(n):
            ibms[i] = _mat_invert_affine(bind_globals[i])
        return ibms
