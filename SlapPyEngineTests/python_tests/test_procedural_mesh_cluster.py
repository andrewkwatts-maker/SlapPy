"""Engine tests for animation/procedural.py, gpu/mesh.py, gpu/cluster_3d.py.
All headless — no GPU upload/dispatch required.
"""
from __future__ import annotations
import struct
import pytest
import numpy as np


# ---------------------------------------------------------------------------
# ControlPoint
# ---------------------------------------------------------------------------

class TestControlPoint:
    def test_instantiates(self):
        from slappyengine.animation.procedural import ControlPoint
        cp = ControlPoint(name="shoulder", uv=(0.5, 0.3))
        assert cp is not None

    def test_name_stored(self):
        from slappyengine.animation.procedural import ControlPoint
        cp = ControlPoint(name="elbow", uv=(0.4, 0.6))
        assert cp.name == "elbow"

    def test_uv_stored(self):
        from slappyengine.animation.procedural import ControlPoint
        cp = ControlPoint(name="wrist", uv=(0.3, 0.8))
        assert cp.uv == (0.3, 0.8)

    def test_default_parent_none(self):
        from slappyengine.animation.procedural import ControlPoint
        cp = ControlPoint(name="root", uv=(0.5, 0.5))
        assert cp.parent is None

    def test_default_constraint_free(self):
        from slappyengine.animation.procedural import ControlPoint
        cp = ControlPoint(name="knee", uv=(0.5, 0.5))
        assert cp.constraint == "free"

    def test_default_angle_range(self):
        from slappyengine.animation.procedural import ControlPoint
        cp = ControlPoint(name="hip", uv=(0.5, 0.5))
        assert cp.min_angle == pytest.approx(-180.0)
        assert cp.max_angle == pytest.approx(180.0)

    def test_custom_parent(self):
        from slappyengine.animation.procedural import ControlPoint
        cp = ControlPoint(name="elbow", uv=(0.4, 0.4), parent="shoulder")
        assert cp.parent == "shoulder"


# ---------------------------------------------------------------------------
# ProceduralRig
# ---------------------------------------------------------------------------

class TestProceduralRigInit:
    def test_instantiates(self):
        from slappyengine.animation.procedural import ProceduralRig
        rig = ProceduralRig()
        assert rig is not None

    def test_no_points_initially(self):
        from slappyengine.animation.procedural import ProceduralRig
        rig = ProceduralRig()
        assert rig.points == []

    def test_add_point(self):
        from slappyengine.animation.procedural import ProceduralRig, ControlPoint
        rig = ProceduralRig()
        cp = ControlPoint(name="root", uv=(0.5, 0.5))
        rig.add_point(cp)
        assert len(rig.points) == 1

    def test_remove_point(self):
        from slappyengine.animation.procedural import ProceduralRig, ControlPoint
        rig = ProceduralRig()
        rig.add_point(ControlPoint(name="a", uv=(0.0, 0.0)))
        rig.remove_point("a")
        assert rig.points == []

    def test_remove_nonexistent_no_crash(self):
        from slappyengine.animation.procedural import ProceduralRig
        rig = ProceduralRig()
        rig.remove_point("ghost")  # should not raise


class TestProceduralRigChain:
    def _three_bone_rig(self):
        from slappyengine.animation.procedural import ProceduralRig, ControlPoint
        rig = ProceduralRig()
        rig.add_point(ControlPoint(name="root",   uv=(0.5, 0.9)))
        rig.add_point(ControlPoint(name="mid",    uv=(0.5, 0.6), parent="root"))
        rig.add_point(ControlPoint(name="tip",    uv=(0.5, 0.3), parent="mid"))
        return rig

    def test_get_chain_root_to_tip(self):
        rig = self._three_bone_rig()
        chain = rig.get_chain("root", "tip")
        assert [cp.name for cp in chain] == ["root", "mid", "tip"]

    def test_get_chain_single_node(self):
        rig = self._three_bone_rig()
        chain = rig.get_chain("root", "root")
        assert [cp.name for cp in chain] == ["root"]

    def test_get_chain_partial(self):
        rig = self._three_bone_rig()
        chain = rig.get_chain("mid", "tip")
        assert [cp.name for cp in chain] == ["mid", "tip"]

    def test_get_chain_missing_returns_partial(self):
        rig = self._three_bone_rig()
        # tip's parent chain stops at root; if root_name not in chain → returns empty or partial
        chain = rig.get_chain("nonexistent_root", "tip")
        assert isinstance(chain, list)


class TestProceduralRigIK:
    def _two_bone_rig(self):
        from slappyengine.animation.procedural import ProceduralRig, ControlPoint
        rig = ProceduralRig()
        rig.add_point(ControlPoint(name="root", uv=(0.5, 0.9)))
        rig.add_point(ControlPoint(name="tip",  uv=(0.5, 0.5), parent="root"))
        return rig

    def test_solve_ik_returns_dict(self):
        rig = self._two_bone_rig()
        result = rig.solve_ik({"tip": (0.6, 0.4)})
        assert isinstance(result, dict)

    def test_solve_ik_all_points_in_result(self):
        rig = self._two_bone_rig()
        result = rig.solve_ik({"tip": (0.6, 0.4)})
        assert "root" in result
        assert "tip" in result

    def test_solve_ik_empty_targets(self):
        rig = self._two_bone_rig()
        result = rig.solve_ik({})
        assert "root" in result

    def test_solve_ik_nonexistent_target_no_crash(self):
        rig = self._two_bone_rig()
        result = rig.solve_ik({"ghost_bone": (0.0, 0.0)})
        assert isinstance(result, dict)


class TestProceduralRigApply:
    def test_apply_to_updates_uv(self):
        from slappyengine.animation.procedural import ProceduralRig, ControlPoint
        rig = ProceduralRig()
        rig.add_point(ControlPoint(name="shoulder", uv=(0.5, 0.3)))
        rig.apply_to(None, {"shoulder": (0.7, 0.2)})
        assert rig._points["shoulder"].uv == (0.7, 0.2)

    def test_apply_to_ignores_unknown_names(self):
        from slappyengine.animation.procedural import ProceduralRig
        rig = ProceduralRig()
        rig.apply_to(None, {"ghost": (0.0, 0.0)})  # should not raise


# ---------------------------------------------------------------------------
# MeshVertex
# ---------------------------------------------------------------------------

class TestMeshVertex:
    def test_instantiates(self):
        from slappyengine.gpu.mesh import MeshVertex
        v = MeshVertex(position=(1.0, 2.0, 3.0))
        assert v is not None

    def test_position_stored(self):
        from slappyengine.gpu.mesh import MeshVertex
        v = MeshVertex(position=(1.0, 2.0, 3.0))
        assert v.position == (1.0, 2.0, 3.0)

    def test_default_normal_up(self):
        from slappyengine.gpu.mesh import MeshVertex
        v = MeshVertex(position=(0.0, 0.0, 0.0))
        assert v.normal == (0.0, 1.0, 0.0)

    def test_default_uv_zero(self):
        from slappyengine.gpu.mesh import MeshVertex
        v = MeshVertex(position=(0.0, 0.0, 0.0))
        assert v.uv == (0.0, 0.0)

    def test_pack_returns_bytes(self):
        from slappyengine.gpu.mesh import MeshVertex
        v = MeshVertex(position=(1.0, 2.0, 3.0))
        result = v.pack()
        assert isinstance(result, bytes)

    def test_pack_length_48(self):
        """3f+3f+2f+4f = 12 floats × 4 bytes = 48 bytes."""
        from slappyengine.gpu.mesh import MeshVertex
        v = MeshVertex(position=(0.0, 0.0, 0.0))
        assert len(v.pack()) == 48

    def test_pack_position_at_offset_0(self):
        from slappyengine.gpu.mesh import MeshVertex
        v = MeshVertex(position=(5.0, 6.0, 7.0))
        data = v.pack()
        x, y, z = struct.unpack_from("3f", data, 0)
        assert x == pytest.approx(5.0)
        assert y == pytest.approx(6.0)
        assert z == pytest.approx(7.0)

    def test_pack_uv_at_offset_24(self):
        from slappyengine.gpu.mesh import MeshVertex
        v = MeshVertex(position=(0.0, 0.0, 0.0), uv=(0.75, 0.25))
        data = v.pack()
        u, vv = struct.unpack_from("2f", data, 24)
        assert u == pytest.approx(0.75)
        assert vv == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# GpuMesh
# ---------------------------------------------------------------------------

class TestGpuMesh:
    def test_instantiates(self):
        from slappyengine.gpu.mesh import GpuMesh, MeshVertex
        verts = [MeshVertex((0.0, 0.0, 0.0)), MeshVertex((1.0, 0.0, 0.0)), MeshVertex((0.0, 1.0, 0.0))]
        mesh = GpuMesh(verts, [0, 1, 2])
        assert mesh is not None

    def test_vertex_count(self):
        from slappyengine.gpu.mesh import GpuMesh, MeshVertex
        verts = [MeshVertex((float(i), 0.0, 0.0)) for i in range(5)]
        mesh = GpuMesh(verts, [])
        assert mesh.vertex_count == 5

    def test_index_count(self):
        from slappyengine.gpu.mesh import GpuMesh, MeshVertex
        verts = [MeshVertex((0.0, 0.0, 0.0))]
        mesh = GpuMesh(verts, [0, 0, 0, 0, 0, 0])
        assert mesh.index_count == 6

    def test_vertex_bytes_length(self):
        from slappyengine.gpu.mesh import GpuMesh, MeshVertex
        verts = [MeshVertex((0.0, 0.0, 0.0)), MeshVertex((1.0, 0.0, 0.0))]
        mesh = GpuMesh(verts, [])
        assert len(mesh.vertex_bytes()) == 2 * 48

    def test_index_bytes_length(self):
        from slappyengine.gpu.mesh import GpuMesh, MeshVertex
        verts = [MeshVertex((0.0, 0.0, 0.0))]
        mesh = GpuMesh(verts, [0, 0, 0])
        # 3 uint32 = 12 bytes
        assert len(mesh.index_bytes()) == 12

    def test_vertex_buffer_none_before_upload(self):
        from slappyengine.gpu.mesh import GpuMesh, MeshVertex
        mesh = GpuMesh([MeshVertex((0.0, 0.0, 0.0))], [0])
        assert mesh.vertex_buffer is None

    def test_index_buffer_none_before_upload(self):
        from slappyengine.gpu.mesh import GpuMesh, MeshVertex
        mesh = GpuMesh([MeshVertex((0.0, 0.0, 0.0))], [0])
        assert mesh.index_buffer is None


class TestGpuMeshUnitCube:
    def test_unit_cube_returns_mesh(self):
        from slappyengine.gpu.mesh import GpuMesh
        m = GpuMesh.unit_cube()
        assert m is not None

    def test_unit_cube_24_vertices(self):
        from slappyengine.gpu.mesh import GpuMesh
        m = GpuMesh.unit_cube()
        assert m.vertex_count == 24  # 4 per face × 6 faces

    def test_unit_cube_36_indices(self):
        from slappyengine.gpu.mesh import GpuMesh
        m = GpuMesh.unit_cube()
        assert m.index_count == 36  # 2 triangles × 3 verts × 6 faces

    def test_unit_cube_vertex_bytes_length(self):
        from slappyengine.gpu.mesh import GpuMesh
        m = GpuMesh.unit_cube()
        assert len(m.vertex_bytes()) == 24 * 48

    def test_unit_quad_4_vertices(self):
        from slappyengine.gpu.mesh import GpuMesh
        m = GpuMesh.unit_quad()
        assert m.vertex_count == 4

    def test_unit_quad_6_indices(self):
        from slappyengine.gpu.mesh import GpuMesh
        m = GpuMesh.unit_quad()
        assert m.index_count == 6


# ---------------------------------------------------------------------------
# Cluster3DSystem — constants and init (headless, no GPU calls)
# ---------------------------------------------------------------------------

class TestCluster3DConstants:
    def test_tiles_x(self):
        from slappyengine.gpu.cluster_3d import TILES_X
        assert TILES_X == 16

    def test_tiles_y(self):
        from slappyengine.gpu.cluster_3d import TILES_Y
        assert TILES_Y == 9

    def test_tiles_z(self):
        from slappyengine.gpu.cluster_3d import TILES_Z
        assert TILES_Z == 24

    def test_total_clusters(self):
        from slappyengine.gpu.cluster_3d import TOTAL_CLUSTERS, TILES_X, TILES_Y, TILES_Z
        assert TOTAL_CLUSTERS == TILES_X * TILES_Y * TILES_Z

    def test_max_lights(self):
        from slappyengine.gpu.cluster_3d import MAX_LIGHTS
        assert MAX_LIGHTS == 256

    def test_max_lights_per_cluster(self):
        from slappyengine.gpu.cluster_3d import MAX_LIGHTS_PER_CLUSTER
        assert MAX_LIGHTS_PER_CLUSTER == 64

    def test_aabb_stride_32(self):
        from slappyengine.gpu.cluster_3d import _AABB_STRIDE
        assert _AABB_STRIDE == 32

    def test_light_stride_32(self):
        from slappyengine.gpu.cluster_3d import _LIGHT_STRIDE
        assert _LIGHT_STRIDE == 32


class TestCluster3DSystemInit:
    def test_instantiates_with_none_gpu(self):
        from slappyengine.gpu.cluster_3d import Cluster3DSystem
        sys = Cluster3DSystem(gpu=None, width=1280, height=720)
        assert sys is not None

    def test_not_ready_without_gpu(self):
        from slappyengine.gpu.cluster_3d import Cluster3DSystem
        sys = Cluster3DSystem(gpu=None, width=640, height=480)
        assert sys._ready is False

    def test_dimensions_stored(self):
        from slappyengine.gpu.cluster_3d import Cluster3DSystem
        sys = Cluster3DSystem(gpu=None, width=1920, height=1080)
        assert sys._width == 1920
        assert sys._height == 1080

    def test_buffers_none_before_init(self):
        from slappyengine.gpu.cluster_3d import Cluster3DSystem
        sys = Cluster3DSystem(gpu=None, width=640, height=480)
        assert sys._cluster_aabb_buf is None
        assert sys._light_buf is None


# ---------------------------------------------------------------------------
# animation/video_import — no-av import guard
# ---------------------------------------------------------------------------

class TestVideoImportGuard:
    def test_extract_frames_raises_importerror_without_av(self):
        try:
            import av  # noqa: F401
            pytest.skip("av is installed; can't test missing-dep path")
        except ImportError:
            pass
        from slappyengine.animation.video_import import extract_frames
        with pytest.raises(ImportError, match="video"):
            extract_frames("dummy.mp4")
