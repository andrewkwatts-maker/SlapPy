<!-- handauthored: do not regenerate -->
# pharos_engine.asset_import — API Reference

> Hand-written reference for the HH5 / JJ3 asset-import subpackage.
> 3D-mesh + texture + cubemap loaders with a single dispatch entry
> point. Sibling references:
> [`render_scene_walker.md`](render_scene_walker.md) is the walker that
> routes `params["mesh_path"]` through the loaders below;
> [`animation_skeleton.md`](animation_skeleton.md) consumes the
> :class:`SkinnedMeshData` glTF importer returns.

## Overview

`pharos_engine.asset_import` is the "read an asset off disk, return a
uniform :class:`ImportResult`" layer. Every loader — OBJ, glTF, HDR
cubemap, texture — returns the same shape so downstream code (JJ5 scene
walker, JJ4 skinned mesh runtime, editor thumbnail cache) never has to
branch on the file extension.

Format-specific dispatch runs through :class:`AssetImportDispatcher`;
the module-level helpers (`import_asset`, `load_model`, `load_texture`)
use a lazy shared dispatcher so `from pharos_engine.asset_import import
load_model` is cheap.

Every real loader **soft-imports** its heavy dependency
(`pygltflib`, `PIL`, `imageio`, `struct`+`plyfile`). Missing deps raise
:class:`ImportDependencyError` with the specific extra name so the
caller's install advice is unambiguous.

## Public surface

```python
from pharos_engine.asset_import import (
    AssetImportDispatcher,
    ImportDependencyError,
    ImportResult,
    MtlMaterialDef,
    Skeleton, SkeletonNode, SkinnedMeshData,
    TextureData,
    import_asset,
    import_cubemap, import_hdr_cubemap,
    import_fbx, import_gltf, import_obj, import_obj_with_materials,
    import_ply, import_stl, import_texture,
    load_model, load_texture,
    mtl_to_material, parse_mtl, resolve_mtl_references,
)
```

## Classes

### `ImportResult`

_dataclass — defined in `pharos_engine.asset_import.import_result`_

Uniform return shape for every loader.

| Field | Type | Notes |
|-------|------|-------|
| `meshes` | `list[Mesh \| GpuMesh]` | May be empty for texture-only files. |
| `textures` | `list[TextureData]` | RGBA `uint8` buffers. |
| `materials` | `list[dict]` | MTL / glTF materials. |
| `skeletons` | `list[Skeleton]` | JJ3 skinned imports only. |
| `warnings` | `list[str]` | Non-fatal parse issues. |

Exposes `.primary_mesh`, `.primary_texture`, `.primary_material`,
`.primary_skeleton` for one-liner callers.

### `AssetImportDispatcher`

_class — defined in `pharos_engine.asset_import.dispatcher`_

```python
disp = AssetImportDispatcher()
result = disp.import_asset("scene.gltf")
```

Registered by file extension. Users may `register(".myfmt", loader_fn)`
to add custom loaders.

### `TextureData`

_dataclass — defined in `pharos_engine.asset_import.import_result`_

CPU-side texture buffer with `pixels: np.ndarray[uint8]`,
`width: int`, `height: int`, `channels: int`, `source_path: str | None`.

### `SkinnedMeshData` / `Skeleton` / `SkeletonNode`

_dataclasses — defined in `pharos_engine.asset_import.skinned_mesh`_

Emitted by the glTF importer when the file carries skinning data.
Re-exported from :mod:`pharos_engine.animation` so animation callers
don't have to know about the importer surface — see
[`animation_skeleton.md`](animation_skeleton.md).

### `MtlMaterialDef`

_dataclass — defined in `pharos_engine.asset_import.mtl_resolver`_

Parsed record from an OBJ MTL sidecar (`Ka`, `Kd`, `Ks`, `Ns`, `map_Kd`,
`map_Bump`). Consumers convert to engine :class:`Material` via
:func:`mtl_to_material`.

### `ImportDependencyError`

_exception — defined in `pharos_engine.asset_import.import_result`_

Raised when a loader needs an optional dep that is not installed. The
message names the pip extra (`[assets]`, `[hdr]`, etc.) to install.

## Functions

### `import_asset(path) -> ImportResult`

_defined in `pharos_engine.asset_import.dispatcher`_

Format-agnostic dispatch — infers the loader from the file extension.

### `load_model(path) -> Mesh | GpuMesh`

_defined in `pharos_engine.asset_import.dispatcher`_

Ergonomic one-liner returning the primary mesh handle. Raises
:class:`FileNotFoundError` when the path is missing,
:class:`ImportDependencyError` when the loader's optional dep is not
installed, `ValueError` when the file has no meshes.

### `load_texture(path) -> TextureData`

_defined in `pharos_engine.asset_import.dispatcher`_

Primary-texture ergonomic one-liner.

### Format-specific loaders

- `import_obj(path) -> ImportResult` — Wavefront OBJ.
- `import_obj_with_materials(path) -> ImportResult` — OBJ + MTL sidecar.
- `import_gltf(path) -> ImportResult` — glTF 2.0, incl. JJ3 skinning.
- `import_ply(path)` / `import_stl(path)` / `import_fbx(path)` — stub
  loaders that raise :class:`ImportDependencyError` in the shipped
  wheel; concrete implementations plug in via the dispatcher.
- `import_texture(path) -> TextureData` — PNG / JPG via PIL.
- `import_cubemap(paths_dict) -> ImportResult` — six-face cubemap.
- `import_hdr_cubemap(path) -> ImportResult` — HDR equirect -> cubemap.

### MTL helpers

- `parse_mtl(text) -> list[MtlMaterialDef]`
- `resolve_mtl_references(obj_path, mtl_names) -> list[Path]`
- `mtl_to_material(mtl_def) -> pharos_engine.material.Material`

## Usage

```python
from pharos_engine.asset_import import load_model, load_texture

mesh = load_model("assets/character.obj")   # returns Mesh
tex = load_texture("assets/tile.png")       # returns TextureData

# Full dispatcher for multi-mesh files:
from pharos_engine.asset_import import AssetImportDispatcher
disp = AssetImportDispatcher()
result = disp.import_asset("assets/scene.gltf")
for i, m in enumerate(result.meshes):
    print(f"mesh {i}: {m}")
if result.primary_skeleton is not None:
    from pharos_engine.animation import Animator
    animator = Animator(result.primary_mesh, result.primary_skeleton)
```

## Skip the wrapper

`pharos_engine.asset_import` is Python-only. There is **no** Rust
equivalent under `pharos_engine._core`; every loader is thin glue over
`pygltflib` / `PIL` / `imageio`. Bypassing the wrapper would mean
importing those libraries directly — reasonable if you need a feature
the loader does not expose (e.g. glTF morph targets), but you lose
:class:`ImportResult` uniformity and the dispatcher's soft-dep handling.

## See also

- [`render_scene_walker.md`](render_scene_walker.md) — routes
  `params["mesh_path"]` through :func:`import_asset`.
- [`animation_skeleton.md`](animation_skeleton.md) — JJ4 runtime that
  consumes :class:`SkinnedMeshData` / :class:`Skeleton`.
- [`material.md`](material.md) — target of :func:`mtl_to_material`.
- [`../pyproject_extras_2026_07_05.md`](../pyproject_extras_2026_07_05.md)
  — `[assets]` pip extra.
