"""slappyengine.asset_import — 3D-asset / texture importer subpackage.

Public surface
--------------
* :class:`AssetImportDispatcher` — dispatch by file extension.
* :func:`import_asset`           — free-function dispatch, uses a
  lazy shared dispatcher.
* :func:`load_model`             — return the first mesh handle
  (ergonomic one-liner: takes path, deduces type, returns handle).
* :func:`load_texture`           — return the first
  :class:`TextureData` handle.
* :class:`ImportResult`          — uniform result dataclass.
* :class:`TextureData`           — CPU-side texture buffer.
* :class:`ImportDependencyError` — raised when an optional lib is
  needed but not installed.
* Format-specific helpers: :func:`import_obj`, :func:`import_gltf`,
  :func:`import_texture`, :func:`import_ply`, :func:`import_stl`,
  :func:`import_fbx`.

Quickstart
----------
>>> from slappyengine.asset_import import load_model
>>> mesh = load_model("assets/character.obj")
>>> # mesh is a GpuMesh — use it with the HH4 renderer.

>>> from slappyengine.asset_import import AssetImportDispatcher
>>> disp = AssetImportDispatcher()
>>> result = disp.import_asset("scene.gltf")
>>> for i, m in enumerate(result.meshes):
...     print(f"mesh {i}: {m}")
"""
from __future__ import annotations

from .dispatcher import (
    AssetImportDispatcher,
    import_asset,
    load_model,
    load_texture,
)
from .gltf_importer import import_gltf
from .import_result import (
    ImportDependencyError,
    ImportResult,
    TextureData,
)
from .obj_importer import import_obj
from .stub_importer import import_fbx, import_ply, import_stl
from .texture_importer import import_texture

__all__ = [
    "AssetImportDispatcher",
    "ImportDependencyError",
    "ImportResult",
    "TextureData",
    "import_asset",
    "import_fbx",
    "import_gltf",
    "import_obj",
    "import_ply",
    "import_stl",
    "import_texture",
    "load_model",
    "load_texture",
]
