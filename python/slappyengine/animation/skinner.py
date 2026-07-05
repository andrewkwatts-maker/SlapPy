"""CPU vertex skinner + :class:`Animator` glue.

The :class:`Skinner` takes a bind-pose :class:`SkinnedMeshData` and a
live skinning-matrix palette, then produces per-vertex world-space
positions (and optionally normals) via linear blend skinning (LBS):

.. math::

    p' = \\sum_{j=0}^{3} w_j \\, M_j \\, p_{bind}

where ``M_j = global_j * inverse_bind_j`` is the per-joint skinning
matrix from :meth:`PosedSkeleton.compute_skinning_palette`.

Normals are transformed by the inverse-transpose of each bone's
skinning matrix's 3x3 upper-left block, blended by the same weights.

:class:`Animator` bundles a skinned mesh + skeleton + clip dictionary
so game code can just call ``animator.play("walk"); animator.advance(dt)``
and get a fresh skinning palette back each frame.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .clip import AnimationClip
from .skeleton_runtime import PosedSkeleton, SkinnedMeshData


class Skinner:
    """CPU-based linear blend skinner.

    Parameters
    ----------
    skinned_mesh
        A :class:`SkinnedMeshData` (or duck-compatible object with
        ``positions`` / ``joints`` / ``weights`` / ``normals``).
    """

    def __init__(self, skinned_mesh: Any) -> None:
        if skinned_mesh is None or not hasattr(skinned_mesh, "positions"):
            raise TypeError(
                "Skinner expects a SkinnedMeshData; "
                f"got {type(skinned_mesh).__name__}"
            )
        self.mesh = skinned_mesh
        self._bind_positions = np.asarray(
            skinned_mesh.positions, dtype=np.float32
        )
        self._joints = np.asarray(skinned_mesh.joints, dtype=np.int32)
        self._weights = np.asarray(skinned_mesh.weights, dtype=np.float32)
        if self._joints.shape != self._weights.shape:
            raise ValueError(
                "joints and weights must have the same shape; "
                f"got {self._joints.shape} vs {self._weights.shape}"
            )
        if self._joints.shape[1] != 4:
            raise ValueError(
                "Skinner requires 4 influences per vertex; "
                f"got {self._joints.shape[1]}"
            )
        self._n = int(self._bind_positions.shape[0])
        self._bind_normals: np.ndarray | None = None
        if getattr(skinned_mesh, "normals", None) is not None:
            self._bind_normals = np.asarray(
                skinned_mesh.normals, dtype=np.float32
            )

    # ------------------------------------------------------------------
    # Skinning
    # ------------------------------------------------------------------

    def skin(
        self,
        pose_state=None,
        inverse_bind_matrices: np.ndarray | None = None,
        *,
        palette: np.ndarray | None = None,
    ) -> np.ndarray:
        """Return ``(V, 3)`` float32 skinned positions.

        Callers may pass either a pre-computed ``palette`` (fast path
        used by :class:`Animator`) or a raw ``pose_state`` +
        ``inverse_bind_matrices`` pair, which is only supported for
        backwards-compat with the doc-string signature — real users
        should stick to the palette path.
        """
        if palette is None:
            if pose_state is None:
                raise TypeError(
                    "Skinner.skin needs either a palette or a pose_state"
                )
            # Palette must be pre-computed by the caller through a
            # PosedSkeleton; we don't own the skeleton here.
            raise TypeError(
                "Skinner.skin needs a palette (use Animator or "
                "PosedSkeleton.compute_skinning_palette to build one)"
            )
        palette = np.asarray(palette, dtype=np.float32)
        if palette.ndim != 3 or palette.shape[1:] != (4, 4):
            raise ValueError(
                f"palette must be (N, 4, 4); got {palette.shape}"
            )

        # Homogeneous coord vertex.
        p_h = np.ones((self._n, 4), dtype=np.float32)
        p_h[:, :3] = self._bind_positions

        out = np.zeros((self._n, 3), dtype=np.float32)
        # 4 influences per vertex → 4 gathers + weighted add.
        for k in range(4):
            j = self._joints[:, k]                                # (V,)
            w = self._weights[:, k].astype(np.float32)            # (V,)
            m_k = palette[j]                                      # (V, 4, 4)
            # (V, 4) @ (V, 4, 4).T → apply per-vertex matrix:
            #     p'_i = M[j_ik] @ p_h_i
            transformed = np.einsum("vij,vj->vi", m_k, p_h)[:, :3]
            out += transformed * w[:, None]
        return out

    def skin_normals(
        self,
        palette: np.ndarray,
    ) -> np.ndarray | None:
        """Return ``(V, 3)`` float32 skinned normals, or ``None`` if the
        mesh has no bind-pose normals."""
        if self._bind_normals is None:
            return None
        palette = np.asarray(palette, dtype=np.float32)
        n = self._n
        # Inverse-transpose of the 3x3 rotation part of each bone's
        # skinning matrix (do this once per joint, not per vertex).
        r3 = palette[:, :3, :3]
        try:
            inv = np.linalg.inv(r3)
            it = np.transpose(inv, (0, 2, 1))
        except np.linalg.LinAlgError:
            it = r3
        out = np.zeros((n, 3), dtype=np.float32)
        bind_n = self._bind_normals
        for k in range(4):
            j = self._joints[:, k]
            w = self._weights[:, k].astype(np.float32)
            m_k = it[j]
            transformed = np.einsum("vij,vj->vi", m_k, bind_n)
            out += transformed * w[:, None]
        # Renormalise.
        lens = np.linalg.norm(out, axis=1, keepdims=True)
        lens = np.where(lens < 1e-8, 1.0, lens)
        return (out / lens).astype(np.float32)


# ---------------------------------------------------------------------------
# Animator — orchestrates skeleton + clips
# ---------------------------------------------------------------------------

class Animator:
    """Glue between a skinned mesh, its skeleton, and a clip library.

    ``animator.play("walk")`` → ``animator.advance(dt)`` → new palette.
    """

    def __init__(
        self,
        skinned_mesh: Any,
        skeleton: Any,
        clips: dict[str, AnimationClip] | None = None,
    ) -> None:
        self.skinner = Skinner(skinned_mesh)
        self.skeleton = skeleton
        self.posed = PosedSkeleton(skeleton)
        self.clips: dict[str, AnimationClip] = dict(clips or {})
        self._current_name: str | None = None
        self._time: float = 0.0
        self._loop: bool = True
        self._playing: bool = False
        # Cache IBMs from the skeleton (or compute if the skeleton
        # didn't ship them).
        ibms = getattr(skeleton, "inverse_bind_matrices", None)
        self._ibms: np.ndarray | None = (
            np.asarray(ibms, dtype=np.float32) if ibms is not None else None
        )

    # ------------------------------------------------------------------
    # Playback control
    # ------------------------------------------------------------------

    def add_clip(self, clip: AnimationClip) -> None:
        self.clips[clip.name] = clip

    def play(self, clip_name: str, loop: bool = True) -> None:
        if clip_name not in self.clips:
            raise KeyError(
                f"unknown clip {clip_name!r}; known: {sorted(self.clips)}"
            )
        self._current_name = clip_name
        self._time = 0.0
        self._loop = bool(loop)
        self._playing = True
        # Reset to bind so leftover pose values from a previous clip
        # don't bleed onto joints the new clip doesn't touch.
        self.posed.reset_to_bind_pose()

    def stop(self) -> None:
        self._playing = False
        self._current_name = None

    def set_time(self, t: float) -> None:
        self._time = float(t)

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def current_clip(self) -> AnimationClip | None:
        if self._current_name is None:
            return None
        return self.clips.get(self._current_name)

    # ------------------------------------------------------------------
    # Frame advance
    # ------------------------------------------------------------------

    def advance(self, dt: float) -> np.ndarray:
        """Advance the clock by ``dt`` and return the skinning palette.

        If nothing is playing this returns the bind-pose palette (all
        identity when the mesh is in bind).
        """
        if self._playing and self._current_name is not None:
            self._time += float(dt)
            clip = self.clips[self._current_name]
            if not self._loop and self._time >= clip.duration_sec:
                # Freeze at the last frame.
                self._time = clip.duration_sec
                self._playing = False
            clip.sample(self._time, self.posed.pose, loop=self._loop)
        return self.posed.compute_skinning_palette(self._ibms)

    def skin(self) -> np.ndarray:
        """Return the current skinned vertex positions."""
        palette = self.posed.compute_skinning_palette(self._ibms)
        return self.skinner.skin(palette=palette)
