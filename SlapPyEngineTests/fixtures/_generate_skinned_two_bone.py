"""Regenerate skinned_two_bone.gltf + .bin using pygltflib.

Run standalone whenever the fixture layout changes. The fixture models a
simple 2-bone skeleton (root + child) skinning a 4-vertex 2-triangle
quad in bind pose.

Skeleton layout:
    node 0  root_joint     (translation 0,0,0)
    node 1  child_joint    (translation 0,1,0, parented under root)
    node 2  mesh_holder    (holds mesh, references skin)

Skin:
    joints = [0, 1]
    skeleton = 0
    inverseBindMatrices = 2 identity matrices

Vertices (quad in xz plane):
    v0 (0,0,0) — joint 0, weight 1
    v1 (1,0,0) — joint 0, weight 1
    v2 (0,0,1) — joint 1, weight 1
    v3 (1,0,1) — joint 1, weight 1

Triangles: (0,1,2) and (1,3,2)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pygltflib

HERE = Path(__file__).resolve().parent


def _pad4(b: bytes) -> bytes:
    while len(b) % 4:
        b += b"\x00"
    return b


def build_skinned_two_bone(out_gltf: Path, out_bin: Path) -> None:
    # ------------------------------------------------------------------
    # 1) Build the binary blob (concatenated buffer).
    # ------------------------------------------------------------------
    positions = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0],
            [1.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )
    normals = np.array(
        [
            [0.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    joints = np.array(
        [
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [1, 0, 0, 0],
            [1, 0, 0, 0],
        ],
        dtype=np.uint8,
    )
    weights = np.array(
        [
            [1.0, 0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    indices = np.array([0, 1, 2, 1, 3, 2], dtype=np.uint16)
    # 2 identity IBMs, column-major flat (identity's transpose is
    # itself so this is trivial).
    ibms = np.tile(np.eye(4, dtype=np.float32), (2, 1, 1))
    ibms_bytes = ibms.tobytes()

    # Serialise into one buffer, each accessor slice 4-byte aligned.
    parts = [
        ("positions", positions.tobytes()),
        ("normals", normals.tobytes()),
        ("joints", joints.tobytes()),
        ("weights", weights.tobytes()),
        ("indices", indices.tobytes()),
        ("ibms", ibms_bytes),
    ]
    offsets: dict[str, int] = {}
    lengths: dict[str, int] = {}
    blob = b""
    for name, data in parts:
        # Align to 4 bytes.
        while len(blob) % 4:
            blob += b"\x00"
        offsets[name] = len(blob)
        lengths[name] = len(data)
        blob += data

    out_bin.write_bytes(blob)
    bin_uri = out_bin.name

    # ------------------------------------------------------------------
    # 2) Build the glTF JSON via pygltflib dataclasses.
    # ------------------------------------------------------------------
    gltf = pygltflib.GLTF2()

    gltf.buffers = [pygltflib.Buffer(byteLength=len(blob), uri=bin_uri)]

    def bv(name: str, target: int | None = None) -> int:
        v = pygltflib.BufferView(
            buffer=0,
            byteOffset=offsets[name],
            byteLength=lengths[name],
        )
        if target is not None:
            v.target = target
        gltf.bufferViews.append(v)
        return len(gltf.bufferViews) - 1

    ARRAY_BUFFER = 34962
    ELEMENT_ARRAY_BUFFER = 34963

    pos_bv = bv("positions", ARRAY_BUFFER)
    nrm_bv = bv("normals", ARRAY_BUFFER)
    joint_bv = bv("joints", ARRAY_BUFFER)
    weight_bv = bv("weights", ARRAY_BUFFER)
    idx_bv = bv("indices", ELEMENT_ARRAY_BUFFER)
    ibm_bv = bv("ibms", None)

    gltf.accessors.append(
        pygltflib.Accessor(
            bufferView=pos_bv,
            componentType=pygltflib.FLOAT,
            count=4,
            type=pygltflib.VEC3,
            min=[0.0, 0.0, 0.0],
            max=[1.0, 0.0, 1.0],
        )
    )
    pos_acc = 0

    gltf.accessors.append(
        pygltflib.Accessor(
            bufferView=nrm_bv,
            componentType=pygltflib.FLOAT,
            count=4,
            type=pygltflib.VEC3,
        )
    )
    nrm_acc = 1

    gltf.accessors.append(
        pygltflib.Accessor(
            bufferView=joint_bv,
            componentType=pygltflib.UNSIGNED_BYTE,
            count=4,
            type=pygltflib.VEC4,
        )
    )
    joint_acc = 2

    gltf.accessors.append(
        pygltflib.Accessor(
            bufferView=weight_bv,
            componentType=pygltflib.FLOAT,
            count=4,
            type=pygltflib.VEC4,
        )
    )
    weight_acc = 3

    gltf.accessors.append(
        pygltflib.Accessor(
            bufferView=idx_bv,
            componentType=pygltflib.UNSIGNED_SHORT,
            count=6,
            type=pygltflib.SCALAR,
        )
    )
    idx_acc = 4

    gltf.accessors.append(
        pygltflib.Accessor(
            bufferView=ibm_bv,
            componentType=pygltflib.FLOAT,
            count=2,
            type=pygltflib.MAT4,
        )
    )
    ibm_acc = 5

    prim_attrs = pygltflib.Attributes(
        POSITION=pos_acc,
        NORMAL=nrm_acc,
        JOINTS_0=joint_acc,
        WEIGHTS_0=weight_acc,
    )
    prim = pygltflib.Primitive(attributes=prim_attrs, indices=idx_acc, mode=4)
    gltf.meshes.append(pygltflib.Mesh(primitives=[prim], name="quad"))

    gltf.skins.append(
        pygltflib.Skin(
            inverseBindMatrices=ibm_acc,
            joints=[0, 1],
            skeleton=0,
            name="two_bone",
        )
    )

    # Node 0: root joint. Node 1: child joint. Node 2: mesh holder.
    root_node = pygltflib.Node(
        name="root_joint",
        translation=[0.0, 0.0, 0.0],
        rotation=[0.0, 0.0, 0.0, 1.0],
        scale=[1.0, 1.0, 1.0],
        children=[1],
    )
    child_node = pygltflib.Node(
        name="child_joint",
        translation=[0.0, 1.0, 0.0],
        rotation=[0.0, 0.0, 0.0, 1.0],
        scale=[1.0, 1.0, 1.0],
    )
    mesh_node = pygltflib.Node(name="mesh_holder", mesh=0, skin=0)
    gltf.nodes = [root_node, child_node, mesh_node]

    gltf.scenes.append(pygltflib.Scene(nodes=[0, 2]))
    gltf.scene = 0

    gltf.asset = pygltflib.Asset(version="2.0", generator="slappyengine JJ3 test fixture")

    gltf.save(str(out_gltf))


def build_static_quad(out_gltf: Path, out_bin: Path) -> None:
    """Non-skinned quad for regression coverage — no JOINTS_0/WEIGHTS_0."""
    positions = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0],
            [1.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )
    normals = np.array(
        [
            [0.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    indices = np.array([0, 1, 2, 1, 3, 2], dtype=np.uint16)
    blob = b""
    offs = {}
    lens = {}
    for name, data in [
        ("positions", positions.tobytes()),
        ("normals", normals.tobytes()),
        ("indices", indices.tobytes()),
    ]:
        while len(blob) % 4:
            blob += b"\x00"
        offs[name] = len(blob)
        lens[name] = len(data)
        blob += data
    out_bin.write_bytes(blob)

    gltf = pygltflib.GLTF2()
    gltf.buffers = [pygltflib.Buffer(byteLength=len(blob), uri=out_bin.name)]
    gltf.bufferViews = [
        pygltflib.BufferView(buffer=0, byteOffset=offs["positions"], byteLength=lens["positions"], target=34962),
        pygltflib.BufferView(buffer=0, byteOffset=offs["normals"], byteLength=lens["normals"], target=34962),
        pygltflib.BufferView(buffer=0, byteOffset=offs["indices"], byteLength=lens["indices"], target=34963),
    ]
    gltf.accessors = [
        pygltflib.Accessor(bufferView=0, componentType=pygltflib.FLOAT, count=4, type=pygltflib.VEC3, min=[0.0, 0.0, 0.0], max=[1.0, 0.0, 1.0]),
        pygltflib.Accessor(bufferView=1, componentType=pygltflib.FLOAT, count=4, type=pygltflib.VEC3),
        pygltflib.Accessor(bufferView=2, componentType=pygltflib.UNSIGNED_SHORT, count=6, type=pygltflib.SCALAR),
    ]
    prim = pygltflib.Primitive(
        attributes=pygltflib.Attributes(POSITION=0, NORMAL=1),
        indices=2,
        mode=4,
    )
    gltf.meshes = [pygltflib.Mesh(primitives=[prim], name="static_quad")]
    gltf.nodes = [pygltflib.Node(name="quad_node", mesh=0)]
    gltf.scenes = [pygltflib.Scene(nodes=[0])]
    gltf.scene = 0
    gltf.asset = pygltflib.Asset(version="2.0", generator="slappyengine JJ3 test fixture")
    gltf.save(str(out_gltf))


if __name__ == "__main__":
    build_skinned_two_bone(
        HERE / "skinned_two_bone.gltf",
        HERE / "skinned_two_bone.bin",
    )
    build_static_quad(
        HERE / "static_quad.gltf",
        HERE / "static_quad.bin",
    )
    print("wrote:", HERE / "skinned_two_bone.gltf")
    print("wrote:", HERE / "static_quad.gltf")
