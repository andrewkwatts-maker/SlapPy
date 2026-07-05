"""AssetImportDispatcher — pick the right importer from a file extension.

Extension routing table (case-insensitive):

* ``.obj``                                → :func:`import_obj`
* ``.gltf``, ``.glb``                     → :func:`import_gltf`
* ``.fbx``                                → :func:`import_fbx` (soft)
* ``.ply``                                → :func:`import_ply` (soft)
* ``.stl``                                → :func:`import_stl` (soft)
* ``.png``, ``.jpg``, ``.jpeg``, ``.webp``, ``.tga`` → :func:`import_texture`

Anything else raises :class:`ImportError` with a helpful message
listing the supported extensions.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .import_result import ImportResult
from .gltf_importer import import_gltf
from .obj_importer import import_obj
from .stub_importer import import_fbx, import_ply, import_stl
from .texture_importer import import_texture


# Extension → importer function.
_MESH_EXT: dict[str, Callable[[str | Path], ImportResult]] = {
    ".obj": import_obj,
    ".gltf": import_gltf,
    ".glb": import_gltf,
    ".fbx": import_fbx,
    ".ply": import_ply,
    ".stl": import_stl,
}
_TEXTURE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".tga"}
_ALL_EXT = set(_MESH_EXT.keys()) | _TEXTURE_EXT


class AssetImportDispatcher:
    """Dispatch an asset path to the correct importer by extension.

    Usage
    -----
    >>> from slappyengine.asset_import import AssetImportDispatcher
    >>> disp = AssetImportDispatcher()
    >>> result = disp.import_asset("assets/character.obj")
    >>> mesh = result.primary_mesh    # move / position / update via this
    """

    # Public — expose the routing tables so tests / editor UI can
    # introspect supported formats without importing internals.
    MESH_EXTENSIONS: tuple[str, ...] = tuple(sorted(_MESH_EXT.keys()))
    TEXTURE_EXTENSIONS: tuple[str, ...] = tuple(sorted(_TEXTURE_EXT))
    SUPPORTED_EXTENSIONS: tuple[str, ...] = tuple(sorted(_ALL_EXT))

    def __init__(self) -> None:
        self._extra: dict[str, Callable[[str | Path], ImportResult]] = {}

    def register(
        self,
        ext: str,
        fn: Callable[[str | Path], ImportResult],
    ) -> None:
        """Register a custom importer for ``ext`` (e.g. ``".usd"``)."""
        if not ext.startswith("."):
            ext = "." + ext
        self._extra[ext.lower()] = fn

    def classify(self, path: str | Path) -> str:
        """Return ``"mesh"`` / ``"texture"`` / ``"unknown"`` for ``path``."""
        ext = Path(path).suffix.lower()
        if ext in _MESH_EXT or ext in self._extra:
            return "mesh"
        if ext in _TEXTURE_EXT:
            return "texture"
        return "unknown"

    def import_asset(self, path: str | Path) -> ImportResult:
        """Dispatch by file extension and return an :class:`ImportResult`.

        Raises
        ------
        ImportError
            If the extension is not one of the supported formats.
        FileNotFoundError
            If ``path`` does not exist on disk.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Asset not found: {p}")
        ext = p.suffix.lower()
        if ext in self._extra:
            return self._extra[ext](p)
        if ext in _MESH_EXT:
            return _MESH_EXT[ext](p)
        if ext in _TEXTURE_EXT:
            return import_texture(p)
        raise ImportError(
            f"Unsupported asset extension {ext!r} for {p.name!r}. "
            f"Supported: {', '.join(sorted(_ALL_EXT))}."
        )


# ---------------------------------------------------------------------------
# Module-level convenience — matches the HH1 top-level shim signatures.
# ---------------------------------------------------------------------------

_default_dispatcher: AssetImportDispatcher | None = None


def _get_dispatcher() -> AssetImportDispatcher:
    global _default_dispatcher
    if _default_dispatcher is None:
        _default_dispatcher = AssetImportDispatcher()
    return _default_dispatcher


def import_asset(path: str | Path) -> ImportResult:
    """Free-function dispatch — uses a lazy shared dispatcher instance."""
    return _get_dispatcher().import_asset(path)


def load_model(path: str | Path) -> Any:
    """Load ``path`` and return the primary mesh handle.

    This is the ergonomic one-liner the user asked for:
    "takes file path, deduces type, get handle of object returned,
    able to use handle to move / position / update."

    The returned mesh handle is a
    :class:`slappyengine.gpu.mesh.GpuMesh` when the wgpu-backed
    ``gpu.mesh`` module is importable; otherwise a plain dict with
    ``vertices`` / ``indices`` / ``vertex_count`` fields.

    Returns
    -------
    GpuMesh | dict
        The first mesh in the imported asset. For .gltf/.glb scenes,
        that is the first primitive of the first mesh.
    """
    result = import_asset(path)
    return result.primary_mesh


def load_texture(path: str | Path):
    """Load ``path`` as a texture and return the first :class:`TextureData`."""
    result = import_asset(path)
    return result.primary_texture
