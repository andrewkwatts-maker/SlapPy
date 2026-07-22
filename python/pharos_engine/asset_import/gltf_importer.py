"""glTF 2.0 / GLB importer via pygltflib (soft dep).

.gltf files are JSON + external buffer / image files.
.glb files bundle everything into a single binary container.

The parser walks the glTF scene graph, resolves every mesh primitive
into a :class:`pharos_engine.gpu.mesh.GpuMesh`-compatible object, and
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
from .skinned_mesh import Skeleton, SkeletonNode, SkinnedMeshData


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
        from pharos_engine.gpu.mesh import GpuMesh, MeshVertex  # noqa: PLC0415
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


def _extract_joints_weights(
    gltf,
    joints_accessor_idx: int | None,
    weights_accessor_idx: int | None,
    buffers: list[bytes],
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Extract JOINTS_0 + WEIGHTS_0 attributes from a mesh primitive.

    Both attributes are always 4-component per vertex in glTF 2.0. This
    helper normalises the joint dtype to ``uint16`` (glTF permits
    ``uint8`` or ``uint16``) and re-normalises weights so each row sums
    to 1.0 when the source authoring tool did not — accepted per the
    glTF spec but easier to consume when guaranteed.

    Returns
    -------
    (joints, weights)
        ``joints`` is ``(N, 4)`` ``uint16``; ``weights`` is ``(N, 4)``
        ``float32``. Either may be ``None`` when the corresponding
        accessor index is ``None`` (i.e. the primitive is not skinned).
    """
    joints = None
    weights = None

    if joints_accessor_idx is not None:
        raw = _accessor_to_ndarray(gltf, joints_accessor_idx, buffers)
        # Ensure 2D (N, 4).
        if raw.ndim == 1:
            raw = raw.reshape(-1, 4)
        # Canonical dtype: uint16, so shaders and downstream code have
        # one code path.
        joints = raw.astype(np.uint16, copy=False)

    if weights_accessor_idx is not None:
        raw_w = _accessor_to_ndarray(gltf, weights_accessor_idx, buffers)
        if raw_w.ndim == 1:
            raw_w = raw_w.reshape(-1, 4)
        weights = raw_w.astype(np.float32, copy=False)
        # Renormalise rows whose sum ≠ 1 (within tolerance). Rows that
        # sum to 0 (i.e. no bone influence) are left alone.
        sums = weights.sum(axis=1)
        needs_norm = ~np.isclose(sums, 1.0, atol=1e-4) & (sums > 0.0)
        if np.any(needs_norm):
            # Broadcast divide with safety on zero sums.
            weights = weights.copy()
            weights[needs_norm] = weights[needs_norm] / sums[needs_norm, None]

    return joints, weights


def _extract_inverse_bind_matrices(
    gltf,
    skin_index: int,
    buffers: list[bytes],
) -> np.ndarray | None:
    """Read the K x 4 x 4 IBM accessor for a skin, or return identities.

    Per glTF spec, if a skin omits ``inverseBindMatrices`` every joint
    is assumed to have an identity IBM. We materialise identities
    explicitly so downstream code doesn't need to special-case ``None``.
    """
    if skin_index is None or gltf.skins is None or skin_index >= len(gltf.skins):
        return None
    skin = gltf.skins[skin_index]
    n_joints = len(skin.joints or [])
    if getattr(skin, "inverseBindMatrices", None) is None:
        # Identity fallback.
        return np.tile(np.eye(4, dtype=np.float32), (n_joints, 1, 1))
    raw = _accessor_to_ndarray(gltf, skin.inverseBindMatrices, buffers)
    # glTF stores each matrix as 16 floats, column-major.
    # _accessor_to_ndarray reshapes MAT4 to (-1, 16) since n_comp=16.
    if raw.ndim == 2 and raw.shape[1] == 16:
        matrices = raw.reshape(-1, 4, 4).astype(np.float32, copy=False)
    elif raw.ndim == 1:
        matrices = raw.reshape(-1, 4, 4).astype(np.float32, copy=False)
    else:
        matrices = raw.astype(np.float32, copy=False)
    # glTF matrices are column-major; numpy interprets the flat 16
    # floats as row-major. Transpose the last two axes so consumers
    # can treat matrices[i] as a standard row-major 4x4.
    matrices = np.transpose(matrices, (0, 2, 1))
    return matrices


def _extract_skeleton(
    gltf,
    skin_index: int,
    buffers: list[bytes],
) -> Skeleton | None:
    """Walk gltf.skins[skin_index] + gltf.nodes to build a Skeleton.

    Returns ``None`` if the skin is missing or has no joints.
    """
    if skin_index is None or gltf.skins is None or skin_index >= len(gltf.skins):
        return None
    skin = gltf.skins[skin_index]
    joint_indices = list(skin.joints or [])
    if not joint_indices:
        return None

    ibms = _extract_inverse_bind_matrices(gltf, skin_index, buffers)

    # Build parent map: absolute node index -> parent absolute node
    # index. glTF stores children lists, not parent pointers, so we
    # invert by scanning nodes once.
    parent_of: dict[int, int] = {}
    for i, node in enumerate(gltf.nodes or []):
        for child in node.children or []:
            parent_of[child] = i

    # Skin.skeleton is optional — it names the common ancestor of the
    # joints. When absent, we detect the root as the joint whose parent
    # is either not in the joint set or missing.
    joint_set = set(joint_indices)
    declared_root = getattr(skin, "skeleton", None)

    nodes: list[SkeletonNode] = []
    for local_i, abs_i in enumerate(joint_indices):
        gnode = gltf.nodes[abs_i] if abs_i < len(gltf.nodes or []) else None
        parent = parent_of.get(abs_i)
        # For skeleton purposes we treat parents outside the joint set
        # as "no parent" — the joint is effectively a root.
        parent_in_skeleton = parent if parent in joint_set else None
        ibm = (
            ibms[local_i]
            if ibms is not None and local_i < ibms.shape[0]
            else np.eye(4, dtype=np.float32)
        )
        translation = (0.0, 0.0, 0.0)
        rotation = (0.0, 0.0, 0.0, 1.0)
        scale = (1.0, 1.0, 1.0)
        name = f"joint_{abs_i}"
        children: list[int] = []
        if gnode is not None:
            if gnode.translation is not None:
                translation = tuple(float(x) for x in gnode.translation)
            if gnode.rotation is not None:
                rotation = tuple(float(x) for x in gnode.rotation)
            if gnode.scale is not None:
                scale = tuple(float(x) for x in gnode.scale)
            if gnode.name:
                name = gnode.name
            # Only surface children that are joints of this skin.
            children = [c for c in (gnode.children or []) if c in joint_set]
        nodes.append(
            SkeletonNode(
                name=name,
                index=int(abs_i),
                parent_index=(int(parent_in_skeleton) if parent_in_skeleton is not None else None),
                local_translation=translation,
                local_rotation=rotation,
                local_scale=scale,
                children=children,
                inverse_bind_matrix=ibm,
            )
        )

    # Determine root local index.
    root_local = 0
    if declared_root is not None and declared_root in joint_indices:
        root_local = joint_indices.index(declared_root)
    else:
        # First joint whose parent isn't in the skeleton.
        for i, n in enumerate(nodes):
            if n.parent_index is None:
                root_local = i
                break

    name = skin.name or (nodes[root_local].name if nodes else "skeleton")
    return Skeleton(nodes=nodes, root_index=root_local, name=name)


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
    # Skeletons — build one Skeleton per glTF skin so mesh primitives
    # can reference them by skin index.
    # ------------------------------------------------------------------
    skeletons: list[Skeleton] = []
    for skin_idx in range(len(gltf.skins or [])):
        skel = _extract_skeleton(gltf, skin_idx, buffers)
        if skel is not None:
            skeletons.append(skel)

    # gltf mesh idx -> skin idx (looked up via first node that references
    # that mesh with a skin). glTF binds mesh↔skin at the node level.
    mesh_to_skin: dict[int, int] = {}
    for node in gltf.nodes or []:
        if node.mesh is not None and node.skin is not None:
            mesh_to_skin.setdefault(node.mesh, node.skin)

    # ------------------------------------------------------------------
    # Meshes — each glTF mesh may have multiple primitives; we emit one
    # GpuMesh per primitive. When a primitive has JOINTS_0/WEIGHTS_0 we
    # wrap the mesh in a SkinnedMeshData with the linked skeleton.
    # ------------------------------------------------------------------
    meshes: list[Any] = []
    gltf_mesh_to_first_prim: list[int] = []  # gltf mesh idx -> our meshes[] idx

    for mesh_i, mesh in enumerate(gltf.meshes or []):
        gltf_mesh_to_first_prim.append(len(meshes))
        skin_idx = mesh_to_skin.get(mesh_i)
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
            base_mesh = _build_mesh_from_primitive(positions, normals, uvs, indices)

            joints_idx = getattr(attrs, "JOINTS_0", None)
            weights_idx = getattr(attrs, "WEIGHTS_0", None)
            if joints_idx is not None or weights_idx is not None:
                joints_arr, weights_arr = _extract_joints_weights(
                    gltf, joints_idx, weights_idx, buffers
                )
                skel = None
                skel_joints: list[int] = []
                skin_root: int | None = None
                ibms = None
                if skin_idx is not None and skin_idx < len(skeletons):
                    skel = skeletons[skin_idx]
                    src_skin = gltf.skins[skin_idx]
                    skel_joints = list(src_skin.joints or [])
                    skin_root = src_skin.skeleton
                    ibms = _extract_inverse_bind_matrices(
                        gltf, skin_idx, buffers
                    )
                meshes.append(
                    SkinnedMeshData(
                        mesh=base_mesh,
                        joints_0=joints_arr,
                        weights_0=weights_arr,
                        inverse_bind_matrices=ibms,
                        skeleton=skel,
                        skeleton_joints=skel_joints,
                        skin_root_joint=skin_root,
                        name=getattr(mesh, "name", None) or f"skinned_mesh_{mesh_i}",
                    )
                )
            else:
                meshes.append(base_mesh)

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
    skinned_count = sum(1 for m in meshes if isinstance(m, SkinnedMeshData))
    return ImportResult(
        kind="scene",
        meshes=meshes,
        textures=textures,
        materials=materials,
        hierarchy=hierarchy,
        skeletons=skeletons,
        metadata={
            "source_path": str(path),
            "importer_used": "import_gltf",
            "load_ms": dt_ms,
            "mesh_count": len(meshes),
            "material_count": len(materials),
            "texture_count": len(textures),
            "node_count": len(hierarchy),
            "skeleton_count": len(skeletons),
            "skinned_mesh_count": skinned_count,
            "is_glb": path.suffix.lower() == ".glb",
        },
    )
