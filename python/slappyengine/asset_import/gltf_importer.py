"""glTF 2.0 / GLB importer via pygltflib (soft dep).

.gltf files are JSON + external buffer / image files.
.glb files bundle everything into a single binary container.

The parser walks the glTF scene graph, resolves every mesh primitive
into a :class:`slappyengine.gpu.mesh.GpuMesh`-compatible object, and
emits the node hierarchy as a flat list of dicts (with ``children``
referring back into the list by index).

Missing ``pygltflib`` raises :class:`ImportDependencyError` with a
``pip install`` hint — no silent fallback.
"""
from __future__ import annotations

import time
import warnings
from pathlib import Path
from typing import Any

import numpy as np

from .import_result import ImportDependencyError, ImportResult, TextureData


def _import_pygltflib():
    """Soft-import pygltflib. Raise with hint if missing."""
    try:
        import pygltflib  # noqa: PLC0415
        return pygltflib
    except ImportError as e:
        warnings.warn(
            "pygltflib is not installed — .gltf/.glb import is unavailable. "
            "Install with: pip install pygltflib",
            stacklevel=3,
        )
        raise ImportDependencyError(
            "pygltflib is required for .gltf/.glb import. "
            "Install with: pip install pygltflib"
        ) from e


# Component types used by glTF accessors.
_COMPONENT_DTYPES = {
    5120: np.int8,     # BYTE
    5121: np.uint8,    # UNSIGNED_BYTE
    5122: np.int16,    # SHORT
    5123: np.uint16,   # UNSIGNED_SHORT
    5125: np.uint32,   # UNSIGNED_INT
    5126: np.float32,  # FLOAT
}
_TYPE_COUNTS = {
    "SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4,
    "MAT2": 4, "MAT3": 9, "MAT4": 16,
}


def _accessor_to_ndarray(gltf, accessor_idx: int, buffers: list[bytes]) -> np.ndarray:
    """Slice out the numpy view for a glTF accessor."""
    acc = gltf.accessors[accessor_idx]
    view = gltf.bufferViews[acc.bufferView]
    buf = buffers[view.buffer]
    dtype = _COMPONENT_DTYPES[acc.componentType]
    n_comp = _TYPE_COUNTS[acc.type]
    start = (view.byteOffset or 0) + (acc.byteOffset or 0)
    itemsize = np.dtype(dtype).itemsize
    length = acc.count * n_comp * itemsize
    raw = buf[start:start + length]
    arr = np.frombuffer(raw, dtype=dtype)
    if n_comp > 1:
        arr = arr.reshape(-1, n_comp)
    return arr


def _load_buffers(gltf, base_dir: Path) -> list[bytes]:
    """Materialise every glTF buffer into a bytes object.

    Handles:
    * embedded base64 (data URIs)
    * external files (relative to gltf path)
    * GLB inline buffer (uri is None)
    """
    import base64

    out: list[bytes] = []
    for buf in gltf.buffers:
        uri = buf.uri
        if uri is None:
            # GLB inline binary chunk — pygltflib exposes it via
            # gltf.binary_blob().
            blob = gltf.binary_blob() if callable(getattr(gltf, "binary_blob", None)) else b""
            out.append(bytes(blob or b""))
        elif uri.startswith("data:"):
            # data URI, e.g. "data:application/octet-stream;base64,AAAA..."
            _, _, b64 = uri.partition(",")
            out.append(base64.b64decode(b64))
        else:
            ext_path = base_dir / uri
            out.append(ext_path.read_bytes())
    return out


def _build_mesh_from_primitive(
    positions: np.ndarray,
    normals: np.ndarray | None,
    uvs: np.ndarray | None,
    indices: np.ndarray | None,
) -> Any:
    """Assemble a GpuMesh from primitive attribute arrays."""
    try:
        from slappyengine.gpu.mesh import GpuMesh, MeshVertex  # noqa: PLC0415
    except Exception:
        GpuMesh = None
        MeshVertex = None

    n_verts = int(positions.shape[0])
    vertices: list[Any] = []
    for i in range(n_verts):
        pos = tuple(float(x) for x in positions[i])
        nrm = (
            tuple(float(x) for x in normals[i])
            if normals is not None
            else (0.0, 1.0, 0.0)
        )
        uv = (
            tuple(float(x) for x in uvs[i])
            if uvs is not None
            else (0.0, 0.0)
        )
        if MeshVertex is not None:
            vertices.append(MeshVertex(position=pos, normal=nrm, uv=uv))
        else:
            vertices.append({"position": pos, "normal": nrm, "uv": uv})

    if indices is None:
        # Non-indexed — synthesise 0..N-1.
        idx_list = list(range(n_verts))
    else:
        idx_list = [int(x) for x in indices.flatten()]

    if GpuMesh is not None:
        try:
            return GpuMesh(vertices, idx_list)
        except Exception:
            pass

    return {
        "vertices": vertices,
        "indices": idx_list,
        "vertex_count": len(vertices),
        "triangle_count": len(idx_list) // 3,
    }


def import_gltf(path: str | Path) -> ImportResult:
    """Load a .gltf or .glb file into an :class:`ImportResult`.

    Returns
    -------
    ImportResult
        ``kind="scene"``. ``meshes`` holds one entry per mesh primitive,
        ``materials`` holds a dict per glTF material (baseColor, metallic,
        roughness, and texture indices), ``hierarchy`` is a flat node
        list where each dict has ``name``, ``mesh_index`` (or -1),
        ``translation``, ``rotation``, ``scale``, ``children``.
    """
    pygltflib = _import_pygltflib()
    path = Path(path)
    t0 = time.perf_counter()

    if path.suffix.lower() == ".glb":
        gltf = pygltflib.GLTF2().load_binary(str(path))
    else:
        gltf = pygltflib.GLTF2().load(str(path))

    base_dir = path.parent
    buffers = _load_buffers(gltf, base_dir)

    # ------------------------------------------------------------------
    # Meshes — each glTF mesh may have multiple primitives; we emit one
    # GpuMesh per primitive.
    # ------------------------------------------------------------------
    meshes: list[Any] = []
    gltf_mesh_to_first_prim: list[int] = []  # gltf mesh idx -> our meshes[] idx

    for mesh in gltf.meshes or []:
        gltf_mesh_to_first_prim.append(len(meshes))
        for prim in mesh.primitives:
            attrs = prim.attributes
            pos_idx = getattr(attrs, "POSITION", None)
            if pos_idx is None:
                continue
            positions = _accessor_to_ndarray(gltf, pos_idx, buffers)
            normals = None
            uvs = None
            nrm_idx = getattr(attrs, "NORMAL", None)
            if nrm_idx is not None:
                normals = _accessor_to_ndarray(gltf, nrm_idx, buffers)
            uv_idx = getattr(attrs, "TEXCOORD_0", None)
            if uv_idx is not None:
                uvs = _accessor_to_ndarray(gltf, uv_idx, buffers)
            indices = None
            if prim.indices is not None:
                indices = _accessor_to_ndarray(gltf, prim.indices, buffers)
            meshes.append(
                _build_mesh_from_primitive(positions, normals, uvs, indices)
            )

    # ------------------------------------------------------------------
    # Materials
    # ------------------------------------------------------------------
    materials: list[dict[str, Any]] = []
    for mat in gltf.materials or []:
        pbr = getattr(mat, "pbrMetallicRoughness", None)
        m: dict[str, Any] = {
            "name": getattr(mat, "name", None) or f"material_{len(materials)}",
        }
        if pbr is not None:
            bc = getattr(pbr, "baseColorFactor", None)
            if bc is not None:
                m["baseColor"] = tuple(bc)
            m["metallic"] = getattr(pbr, "metallicFactor", 1.0)
            m["roughness"] = getattr(pbr, "roughnessFactor", 1.0)
            bct = getattr(pbr, "baseColorTexture", None)
            if bct is not None and getattr(bct, "index", None) is not None:
                m["baseColor_texture_index"] = bct.index
        nrm = getattr(mat, "normalTexture", None)
        if nrm is not None and getattr(nrm, "index", None) is not None:
            m["normal_texture_index"] = nrm.index
        materials.append(m)

    # ------------------------------------------------------------------
    # Textures — decode PNG/JPEG images via PIL if available. When PIL
    # or an image resource is missing, we emit a placeholder entry so
    # material→texture indices stay valid.
    # ------------------------------------------------------------------
    textures: list[TextureData] = []
    try:
        from PIL import Image as _PIL  # noqa: PLC0415
    except Exception:
        _PIL = None

    for img_ref in gltf.images or []:
        pixels = np.zeros((1, 1, 4), dtype=np.uint8)
        width, height, channels, fmt = 1, 1, 4, "RGBA"
        try:
            if _PIL is not None:
                if img_ref.uri:
                    if img_ref.uri.startswith("data:"):
                        import base64, io  # noqa: PLC0415
                        _, _, b64 = img_ref.uri.partition(",")
                        img = _PIL.open(io.BytesIO(base64.b64decode(b64)))
                    else:
                        img = _PIL.open(str(base_dir / img_ref.uri))
                    img = img.convert("RGBA")
                    pixels = np.asarray(img, dtype=np.uint8)
                    height, width = int(img.height), int(img.width)
        except Exception:
            # Placeholder stays 1x1 opaque.
            pass
        textures.append(TextureData(pixels, width, height, channels, fmt))

    # ------------------------------------------------------------------
    # Hierarchy — flatten nodes.
    # ------------------------------------------------------------------
    hierarchy: list[dict[str, Any]] = []
    for i, node in enumerate(gltf.nodes or []):
        n: dict[str, Any] = {
            "name": getattr(node, "name", None) or f"node_{i}",
            "mesh_index": (
                gltf_mesh_to_first_prim[node.mesh]
                if node.mesh is not None and node.mesh < len(gltf_mesh_to_first_prim)
                else -1
            ),
            "translation": tuple(node.translation or (0.0, 0.0, 0.0)),
            "rotation": tuple(node.rotation or (0.0, 0.0, 0.0, 1.0)),
            "scale": tuple(node.scale or (1.0, 1.0, 1.0)),
            "children": list(node.children or []),
        }
        hierarchy.append(n)

    dt_ms = (time.perf_counter() - t0) * 1000.0
    return ImportResult(
        kind="scene",
        meshes=meshes,
        textures=textures,
        materials=materials,
        hierarchy=hierarchy,
        metadata={
            "source_path": str(path),
            "importer_used": "import_gltf",
            "load_ms": dt_ms,
            "mesh_count": len(meshes),
            "material_count": len(materials),
            "texture_count": len(textures),
            "node_count": len(hierarchy),
            "is_glb": path.suffix.lower() == ".glb",
        },
    )
