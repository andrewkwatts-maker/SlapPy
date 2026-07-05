"""ImportResult / TextureData — return types from asset importers.

The dispatcher (``AssetImportDispatcher``) always returns an
:class:`ImportResult` regardless of file kind. Fields not relevant to a
particular importer are left as empty lists / dicts, so downstream code
can uniformly inspect ``result.meshes`` / ``result.textures`` /
``result.hierarchy`` without checking ``kind`` first.

Convention
----------
``kind`` is one of:

* ``"mesh"``    — .obj / .fbx / .ply / .stl
* ``"texture"`` — .png / .jpg / .jpeg / .webp / .tga
* ``"scene"``   — .gltf / .glb (contains meshes + hierarchy + materials)

``metadata`` always contains at least ``source_path`` and
``importer_used``; importers may add ``load_ms``, ``vertex_count``, etc.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class TextureData:
    """CPU-side texture buffer.

    ``pixels`` is a ``numpy.ndarray`` of dtype ``uint8`` and shape
    ``(H, W, C)`` where ``C`` is 1, 3, or 4.
    """

    pixels: np.ndarray
    width: int
    height: int
    channels: int
    format: str = "RGB"  # "RGB" | "RGBA" | "grayscale"

    def __post_init__(self) -> None:
        # Cheap sanity so consumers can trust the shape without re-checking.
        if self.pixels.ndim == 2:
            # Grayscale — normalise to (H, W, 1) shape? We leave it as-is
            # but ensure `channels` matches.
            if self.channels != 1:
                self.channels = 1
        elif self.pixels.ndim == 3:
            if self.pixels.shape[2] != self.channels:
                self.channels = int(self.pixels.shape[2])


@dataclass
class ImportResult:
    """Uniform return type from every asset importer.

    Parameters
    ----------
    kind
        Category of the asset (``"mesh"`` / ``"texture"`` / ``"scene"``).
    meshes
        A list of ``GpuMesh``-compatible objects. Left empty for pure
        texture imports. Element type is deliberately untyped so we
        don't force an eager import of :mod:`slappyengine.gpu.mesh`
        (which pulls in wgpu).
    textures
        A list of :class:`TextureData` for direct-texture imports as
        well as embedded textures in .gltf/.glb.
    materials
        A list of dicts describing PBR materials (baseColor, metallic,
        roughness, normal_texture_index, ...). Format is intentionally
        loose so games can attach extra fields.
    hierarchy
        A list of node dicts describing the scene tree. Each dict has
        ``name``, ``mesh_index`` (or -1), ``translation``, ``rotation``,
        ``scale``, ``children`` (list of ints indexing back into
        ``hierarchy``). Only populated by scene importers.
    metadata
        Free-form metadata bag. Always contains ``source_path`` and
        ``importer_used``.
    """

    kind: str
    meshes: list[Any] = field(default_factory=list)
    textures: list[TextureData] = field(default_factory=list)
    materials: list[dict[str, Any]] = field(default_factory=list)
    hierarchy: list[dict[str, Any]] = field(default_factory=list)
    skeletons: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience — treat the result like a handle
    # ------------------------------------------------------------------

    @property
    def primary_mesh(self) -> Any | None:
        """Return the first mesh, or ``None`` if there are none."""
        return self.meshes[0] if self.meshes else None

    @property
    def primary_texture(self) -> TextureData | None:
        """Return the first texture, or ``None`` if there are none."""
        return self.textures[0] if self.textures else None

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"ImportResult(kind={self.kind!r}, "
            f"meshes={len(self.meshes)}, "
            f"textures={len(self.textures)}, "
            f"materials={len(self.materials)}, "
            f"hierarchy_nodes={len(self.hierarchy)}, "
            f"skeletons={len(self.skeletons)})"
        )


class ImportDependencyError(ImportError):
    """Raised when an importer needs an optional dep that isn't installed.

    The message always contains a ``pip install`` hint so callers know
    how to unblock themselves.
    """
