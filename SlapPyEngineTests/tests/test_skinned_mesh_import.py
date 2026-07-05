"""Tests for JJ3 — skinned-mesh support in the glTF importer.

Exercises:

* :class:`SkinnedMeshData` / :class:`SkeletonNode` / :class:`Skeleton`
  dataclasses (shape + defaults).
* Extractor helpers ``_extract_joints_weights``,
  ``_extract_inverse_bind_matrices``, ``_extract_skeleton`` in
  isolation.
* End-to-end ``import_gltf`` on a rigged 2-bone fixture and a matching
  non-skinned fixture (no-regression coverage).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")

from slappyengine.asset_import.gltf_importer import (  # noqa: E402
    _extract_inverse_bind_matrices,
    _extract_joints_weights,
    _extract_skeleton,
    _load_buffers,
    import_gltf,
)
from slappyengine.asset_import.import_result import ImportResult  # noqa: E402
from slappyengine.asset_import.skinned_mesh import (  # noqa: E402
    Skeleton,
    SkeletonNode,
    SkinnedMeshData,
)

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SKINNED_GLTF = FIXTURE_DIR / "skinned_two_bone.gltf"
STATIC_GLTF = FIXTURE_DIR / "static_quad.gltf"


# ---------------------------------------------------------------------------
# Fixture generation on first run — regenerate if the .gltf is missing so
# tests don't require a prior generation step.
# ---------------------------------------------------------------------------

def _ensure_fixtures() -> None:
    if SKINNED_GLTF.exists() and STATIC_GLTF.exists():
        return
    gen = FIXTURE_DIR / "_generate_skinned_two_bone.py"
    if not gen.exists():
        pytest.skip("skinned fixture generator missing")
    import subprocess
    import sys as _sys
    subprocess.check_call([_sys.executable, str(gen)])


@pytest.fixture(scope="module", autouse=True)
def _fixtures_ready():
    _ensure_fixtures()


# ---------------------------------------------------------------------------
# Dataclass sanity
# ---------------------------------------------------------------------------

def test_skeleton_node_defaults():
    n = SkeletonNode(name="root", index=0, parent_index=None)
    assert n.name == "root"
    assert n.index == 0
    assert n.parent_index is None
    assert n.local_translation == (0.0, 0.0, 0.0)
    assert n.local_rotation == (0.0, 0.0, 0.0, 1.0)
    assert n.local_scale == (1.0, 1.0, 1.0)
    assert n.children == []
    assert n.inverse_bind_matrix.shape == (4, 4)
    assert np.allclose(n.inverse_bind_matrix, np.eye(4))
    assert n.is_root() is True


def test_skeleton_node_child_flags_not_root():
    n = SkeletonNode(name="child", index=1, parent_index=0)
    assert n.parent_index == 0
    assert n.is_root() is False


def test_skeleton_dataclass_two_node_tree():
    root = SkeletonNode(name="root", index=0, parent_index=None, children=[1])
    child = SkeletonNode(name="child", index=1, parent_index=0)
    skel = Skeleton(nodes=[root, child], root_index=0, name="rig")
    assert skel.joint_count() == 2
    assert skel.get_root() is root
    assert skel.name == "rig"


def test_skeleton_children_of_translates_abs_to_local():
    root = SkeletonNode(name="root", index=0, parent_index=None, children=[1])
    child = SkeletonNode(name="child", index=1, parent_index=0)
    skel = Skeleton(nodes=[root, child], root_index=0)
    # children_of(0) should return LOCAL index 1, not absolute node 1.
    assert skel.children_of(0) == [1]
    assert skel.children_of(1) == []


def test_skeleton_get_root_empty():
    skel = Skeleton()
    assert skel.get_root() is None
    assert skel.joint_count() == 0


def test_skinned_mesh_data_defaults():
    d = SkinnedMeshData(mesh={"vertices": [], "indices": []})
    assert d.joints_0 is None
    assert d.weights_0 is None
    assert d.inverse_bind_matrices is None
    assert d.skeleton is None
    assert d.skeleton_joints == []
    assert d.skin_root_joint is None
    assert d.is_valid() is False


def test_skinned_mesh_data_is_valid_with_matching_shapes():
    joints = np.zeros((5, 4), dtype=np.uint16)
    weights = np.ones((5, 4), dtype=np.float32) * 0.25
    d = SkinnedMeshData(mesh={}, joints_0=joints, weights_0=weights)
    assert d.is_valid() is True
    assert d.vertex_count() == 5


def test_skinned_mesh_data_is_invalid_on_shape_mismatch():
    joints = np.zeros((5, 4), dtype=np.uint16)
    weights = np.zeros((4, 4), dtype=np.float32)
    d = SkinnedMeshData(mesh={}, joints_0=joints, weights_0=weights)
    assert d.is_valid() is False


# ---------------------------------------------------------------------------
# Extractor helper tests — direct manipulation of gltf objects
# ---------------------------------------------------------------------------

def test_extract_joints_weights_coerces_uint8_to_uint16():
    gltf = pygltflib.GLTF2().load(str(SKINNED_GLTF))
    buffers = _load_buffers(gltf, SKINNED_GLTF.parent)
    prim = gltf.meshes[0].primitives[0]
    joints, weights = _extract_joints_weights(
        gltf,
        prim.attributes.JOINTS_0,
        prim.attributes.WEIGHTS_0,
        buffers,
    )
    assert joints.dtype == np.uint16
    assert joints.shape == (4, 4)
    assert weights.dtype == np.float32
    assert weights.shape == (4, 4)


def test_extract_joints_weights_renormalises_off_spec_weights():
    # Build a synthetic accessor path by constructing a tiny buffer.
    gltf = pygltflib.GLTF2()
    weights = np.array(
        [
            [0.5, 0.5, 0.0, 0.0],  # already normalised
            [2.0, 2.0, 0.0, 0.0],  # sum = 4 -> should become [0.5, 0.5, 0, 0]
            [0.0, 0.0, 0.0, 0.0],  # all-zero row -> preserved
        ],
        dtype=np.float32,
    )
    joints = np.array(
        [
            [0, 1, 0, 0],
            [0, 2, 0, 0],
            [0, 0, 0, 0],
        ],
        dtype=np.uint8,
    )
    blob = joints.tobytes() + weights.tobytes()
    gltf.buffers = [pygltflib.Buffer(byteLength=len(blob))]
    gltf.bufferViews = [
        pygltflib.BufferView(buffer=0, byteOffset=0, byteLength=joints.nbytes),
        pygltflib.BufferView(buffer=0, byteOffset=joints.nbytes, byteLength=weights.nbytes),
    ]
    gltf.accessors = [
        pygltflib.Accessor(bufferView=0, componentType=pygltflib.UNSIGNED_BYTE, count=3, type=pygltflib.VEC4),
        pygltflib.Accessor(bufferView=1, componentType=pygltflib.FLOAT, count=3, type=pygltflib.VEC4),
    ]
    joints_out, weights_out = _extract_joints_weights(gltf, 0, 1, [blob])
    assert weights_out.shape == (3, 4)
    assert np.allclose(weights_out[0].sum(), 1.0)
    assert np.allclose(weights_out[1], [0.5, 0.5, 0.0, 0.0])
    # All-zero rows stay all-zero.
    assert np.allclose(weights_out[2], [0.0, 0.0, 0.0, 0.0])
    # Joints canonical dtype.
    assert joints_out.dtype == np.uint16


def test_extract_joints_weights_handles_none():
    joints, weights = _extract_joints_weights(None, None, None, [])
    assert joints is None
    assert weights is None


def test_extract_inverse_bind_matrices_identity():
    gltf = pygltflib.GLTF2().load(str(SKINNED_GLTF))
    buffers = _load_buffers(gltf, SKINNED_GLTF.parent)
    ibms = _extract_inverse_bind_matrices(gltf, 0, buffers)
    assert ibms.shape == (2, 4, 4)
    assert ibms.dtype == np.float32
    for i in range(ibms.shape[0]):
        assert np.allclose(ibms[i], np.eye(4)), f"IBM {i} is not identity"


def test_extract_inverse_bind_matrices_missing_skin_returns_none():
    gltf = pygltflib.GLTF2().load(str(SKINNED_GLTF))
    buffers = _load_buffers(gltf, SKINNED_GLTF.parent)
    # Out-of-range skin index.
    assert _extract_inverse_bind_matrices(gltf, 99, buffers) is None
    assert _extract_inverse_bind_matrices(gltf, None, buffers) is None


def test_extract_inverse_bind_matrices_absent_falls_back_to_identity():
    gltf = pygltflib.GLTF2().load(str(SKINNED_GLTF))
    buffers = _load_buffers(gltf, SKINNED_GLTF.parent)
    # Drop the IBM accessor reference.
    gltf.skins[0].inverseBindMatrices = None
    ibms = _extract_inverse_bind_matrices(gltf, 0, buffers)
    assert ibms.shape == (2, 4, 4)
    assert np.allclose(ibms[0], np.eye(4))
    assert np.allclose(ibms[1], np.eye(4))


def test_extract_skeleton_two_bone():
    gltf = pygltflib.GLTF2().load(str(SKINNED_GLTF))
    buffers = _load_buffers(gltf, SKINNED_GLTF.parent)
    skel = _extract_skeleton(gltf, 0, buffers)
    assert skel is not None
    assert skel.joint_count() == 2
    # Node ordering follows skin.joints -> [0, 1].
    root = skel.nodes[0]
    child = skel.nodes[1]
    assert root.name == "root_joint"
    assert root.parent_index is None
    assert root.children == [1]
    assert child.name == "child_joint"
    assert child.parent_index == 0
    assert child.children == []
    # Local translations preserved from fixture.
    assert child.local_translation == (0.0, 1.0, 0.0)


def test_extract_skeleton_missing_returns_none():
    gltf = pygltflib.GLTF2().load(str(SKINNED_GLTF))
    buffers = _load_buffers(gltf, SKINNED_GLTF.parent)
    assert _extract_skeleton(gltf, 99, buffers) is None
    assert _extract_skeleton(gltf, None, buffers) is None


def test_extract_skeleton_children_of_walks_tree():
    gltf = pygltflib.GLTF2().load(str(SKINNED_GLTF))
    buffers = _load_buffers(gltf, SKINNED_GLTF.parent)
    skel = _extract_skeleton(gltf, 0, buffers)
    assert skel.children_of(0) == [1]
    assert skel.children_of(1) == []


# ---------------------------------------------------------------------------
# Full import pipeline
# ---------------------------------------------------------------------------

def test_import_gltf_skinned_returns_skinned_mesh_data():
    result = import_gltf(SKINNED_GLTF)
    assert isinstance(result, ImportResult)
    assert result.kind == "scene"
    assert len(result.meshes) == 1
    mesh = result.meshes[0]
    assert isinstance(mesh, SkinnedMeshData)
    assert mesh.is_valid()
    assert mesh.joints_0.shape == (4, 4)
    assert mesh.joints_0.dtype == np.uint16
    assert mesh.weights_0.shape == (4, 4)
    assert mesh.weights_0.dtype == np.float32
    # Every vertex has weight 1 on its declared joint.
    assert np.allclose(mesh.weights_0.sum(axis=1), 1.0)


def test_import_gltf_skinned_populates_skeleton_list():
    result = import_gltf(SKINNED_GLTF)
    assert len(result.skeletons) == 1
    skel = result.skeletons[0]
    assert isinstance(skel, Skeleton)
    assert skel.joint_count() == 2
    assert result.metadata["skeleton_count"] == 1
    assert result.metadata["skinned_mesh_count"] == 1


def test_import_gltf_skinned_attaches_skeleton_to_mesh():
    result = import_gltf(SKINNED_GLTF)
    mesh = result.meshes[0]
    assert mesh.skeleton is not None
    assert mesh.skeleton is result.skeletons[0]
    assert mesh.skeleton_joints == [0, 1]
    assert mesh.skin_root_joint == 0
    assert mesh.inverse_bind_matrices.shape == (2, 4, 4)
    assert np.allclose(mesh.inverse_bind_matrices[0], np.eye(4))


def test_import_gltf_static_no_regression():
    result = import_gltf(STATIC_GLTF)
    assert result.kind == "scene"
    assert len(result.meshes) == 1
    # Static mesh should NOT be wrapped in SkinnedMeshData.
    assert not isinstance(result.meshes[0], SkinnedMeshData)
    assert result.skeletons == []
    assert result.metadata["skeleton_count"] == 0
    assert result.metadata["skinned_mesh_count"] == 0


def test_import_gltf_hierarchy_still_populated_when_skinned():
    result = import_gltf(SKINNED_GLTF)
    # 3 nodes: root_joint, child_joint, mesh_holder.
    assert len(result.hierarchy) == 3
    names = [n["name"] for n in result.hierarchy]
    assert "root_joint" in names
    assert "child_joint" in names
    assert "mesh_holder" in names


def test_import_gltf_metadata_reports_skin_stats():
    result = import_gltf(SKINNED_GLTF)
    md = result.metadata
    assert md["mesh_count"] == 1
    assert md["node_count"] == 3
    assert md["skeleton_count"] == 1
    assert md["skinned_mesh_count"] == 1


def test_import_result_repr_mentions_skeletons():
    result = import_gltf(SKINNED_GLTF)
    r = repr(result)
    assert "skeletons=1" in r


def test_vertex_count_matches_joints_table_size():
    result = import_gltf(SKINNED_GLTF)
    mesh = result.meshes[0]
    assert mesh.vertex_count() == 4
    assert mesh.joint_count() == 2


def test_skinned_mesh_has_underlying_static_mesh():
    result = import_gltf(SKINNED_GLTF)
    mesh = result.meshes[0]
    # The underlying static mesh should still be exposed via .mesh so
    # non-skinning consumers can ignore the skin payload.
    assert mesh.mesh is not None
