"""Test that 3D modules are not imported on normal engine startup."""
import sys
import importlib


def test_import_does_not_load_3d():
    """Importing slappyengine must NOT trigger 3D module imports."""
    # Remove any cached 3D modules so the check is fresh
    for key in list(sys.modules.keys()):
        if "mesh_pipeline" in key or "pbr_material" in key or "mesh" in key:
            del sys.modules[key]

    import slappyengine  # noqa: F401

    assert "slappyengine.gpu.mesh_pipeline" not in sys.modules
    assert "slappyengine.gpu.pbr_material" not in sys.modules


def test_gpu_mesh_cpu_only():
    """GpuMesh can be created and used without a GPU device."""
    from slappyengine.gpu.mesh import GpuMesh

    mesh = GpuMesh.unit_cube()
    assert mesh.vertex_count == 24
    assert mesh.index_count == 36
    assert len(mesh.vertex_bytes()) == 24 * 48


def test_gpu_mesh_unit_quad():
    from slappyengine.gpu.mesh import GpuMesh

    quad = GpuMesh.unit_quad()
    assert quad.vertex_count == 4
    assert quad.index_count == 6
    assert len(quad.vertex_bytes()) == 4 * 48
    assert len(quad.index_bytes()) == 6 * 4  # 6 uint32 indices


def test_gpu_mesh_vertex_stride():
    """Each vertex must pack to exactly VERTEX_STRIDE bytes."""
    from slappyengine.gpu.mesh import GpuMesh, MeshVertex

    assert GpuMesh.VERTEX_STRIDE == 48

    v = MeshVertex(position=(1.0, 2.0, 3.0))
    assert len(v.pack()) == 48


def test_pbr_material_gpu_bytes():
    from slappyengine.gpu.pbr_material import PbrMaterial

    mat = PbrMaterial(metallic=0.5, roughness=0.3)
    data = mat.to_gpu_bytes()
    # std430 layout: vec4 albedo + 2f metallic/roughness + f ior + f pad
    #                + vec3 emissive + f emissive_strength = 12 × f32 = 48 bytes
    assert len(data) == 48
    assert isinstance(data, bytes)


def test_pbr_material_gpu_bytes_default():
    """Default PbrMaterial produces exactly 48 bytes."""
    from slappyengine.gpu.pbr_material import PbrMaterial

    data = PbrMaterial().to_gpu_bytes()
    assert len(data) == 48


def test_gpu_mesh_index_bytes():
    """Index buffer is packed as uint32 (4 bytes per index)."""
    from slappyengine.gpu.mesh import GpuMesh

    mesh = GpuMesh.unit_cube()
    assert len(mesh.index_bytes()) == 36 * 4


def test_gpu_mesh_upload_idempotent(monkeypatch):
    """upload() must be idempotent — calling twice must not re-create buffers."""
    from slappyengine.gpu.mesh import GpuMesh

    mesh = GpuMesh.unit_cube()

    call_count = [0]

    class _FakeBuf:
        pass

    class _FakeDevice:
        def create_buffer_with_data(self, *, data, usage):
            call_count[0] += 1
            return _FakeBuf()

    class _FakeWgpu:
        class BufferUsage:
            VERTEX = 1
            INDEX = 2

    monkeypatch.setitem(sys.modules, "wgpu", _FakeWgpu())

    mesh.upload(_FakeDevice())
    assert call_count[0] == 2  # vertex + index

    mesh.upload(_FakeDevice())
    assert call_count[0] == 2  # second call must be a no-op
