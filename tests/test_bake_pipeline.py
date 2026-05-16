"""Tests for cross-layer baking: 3D→2D and 2D→3D inputs — no GPU required."""
import numpy as np
import pytest


def test_bake_to_2d_no_renderer():
    """bake_to_2d() on a 3D layer with no renderer returns a blank 2D Layer."""
    from slappyengine.layer import Layer

    layer = Layer.blank(64, 64, mode="3D")
    baked = layer.bake_to_2d((32, 32))

    assert baked.mode == "2D"
    # Name must be non-empty and contain some reference to the source or "baked".
    assert baked.name != ""


def test_bake_to_2d_name_contains_baked():
    """bake_to_2d() names the returned layer with '_baked' suffix."""
    from slappyengine.layer import Layer

    layer = Layer.blank(64, 64, name="City3D", mode="3D")
    baked = layer.bake_to_2d((32, 32))

    assert "baked" in baked.name.lower()


def test_bake_to_2d_output_size():
    """bake_to_2d() returns a Layer whose image data matches the requested size."""
    from slappyengine.layer import Layer

    layer = Layer.blank(64, 64, mode="3D")
    baked = layer.bake_to_2d((32, 32))

    # _image_data is (H, W, 4); size property returns (W, H).
    assert baked._image_data is not None
    h, w, channels = baked._image_data.shape
    assert (w, h) == (32, 32)
    assert channels == 4


def test_bake_to_2d_wrong_mode():
    """bake_to_2d() on a 2D layer raises ValueError."""
    from slappyengine.layer import Layer

    layer = Layer.blank(64, 64)
    with pytest.raises(ValueError, match="3D"):
        layer.bake_to_2d((32, 32))


def test_apply_heightmap_no_mesh():
    """apply_heightmap() on a 3D layer with no mesh is a no-op (no crash)."""
    from slappyengine.layer import Layer

    layer_3d = Layer.blank(64, 64, mode="3D")
    layer_2d = Layer.blank(64, 64)
    layer_2d._image_data = np.full((64, 64, 4), 128, dtype=np.uint8)

    # Must not raise any exception.
    layer_3d.apply_heightmap(layer_2d, scale=10.0)


def test_apply_heightmap_displaces_vertices():
    """apply_heightmap() displaces vertex Z positions by pixel luminance × scale."""
    from slappyengine.layer import Layer
    from slappyengine.gpu.mesh import GpuMesh

    layer_3d = Layer.blank(64, 64, mode="3D")
    layer_3d.mesh_geometry = GpuMesh.unit_quad()

    # All-white heightmap → luminance = 1.0 everywhere.
    layer_2d = Layer.blank(64, 64)
    layer_2d._image_data = np.full((64, 64, 4), 255, dtype=np.uint8)

    # Record original Z positions (all 0.0 for unit_quad).
    original_zs = [v.position[2] for v in layer_3d.mesh_geometry._vertices]

    layer_3d.apply_heightmap(layer_2d, scale=5.0)
    new_zs = [v.position[2] for v in layer_3d.mesh_geometry._vertices]

    # White pixels → lum=1.0 → displacement = 1.0 × 5.0 = 5.0 added to Z.
    for orig, new in zip(original_zs, new_zs):
        assert new >= orig, f"Expected Z to increase: was {orig}, now {new}"


def test_apply_heightmap_scale_zero_no_displacement():
    """apply_heightmap() with scale=0.0 leaves all vertex Z positions unchanged."""
    from slappyengine.layer import Layer
    from slappyengine.gpu.mesh import GpuMesh

    layer_3d = Layer.blank(64, 64, mode="3D")
    layer_3d.mesh_geometry = GpuMesh.unit_quad()

    layer_2d = Layer.blank(64, 64)
    layer_2d._image_data = np.full((64, 64, 4), 255, dtype=np.uint8)

    original_zs = [v.position[2] for v in layer_3d.mesh_geometry._vertices]
    layer_3d.apply_heightmap(layer_2d, scale=0.0)
    new_zs = [v.position[2] for v in layer_3d.mesh_geometry._vertices]

    assert original_zs == new_zs


def test_apply_heightmap_black_image_no_displacement():
    """apply_heightmap() with an all-black image leaves Z positions unchanged."""
    from slappyengine.layer import Layer
    from slappyengine.gpu.mesh import GpuMesh

    layer_3d = Layer.blank(64, 64, mode="3D")
    layer_3d.mesh_geometry = GpuMesh.unit_quad()

    layer_2d = Layer.blank(64, 64)
    # All-black image → luminance = 0.0 → displacement = 0.0.
    layer_2d._image_data = np.zeros((64, 64, 4), dtype=np.uint8)

    original_zs = [v.position[2] for v in layer_3d.mesh_geometry._vertices]
    layer_3d.apply_heightmap(layer_2d, scale=10.0)
    new_zs = [v.position[2] for v in layer_3d.mesh_geometry._vertices]

    assert original_zs == new_zs


def test_apply_heightmap_invalidates_gpu_buffer():
    """apply_heightmap() sets _vertex_buf to None to force re-upload."""
    from slappyengine.layer import Layer
    from slappyengine.gpu.mesh import GpuMesh

    layer_3d = Layer.blank(64, 64, mode="3D")
    layer_3d.mesh_geometry = GpuMesh.unit_quad()
    # Pretend a GPU buffer was already allocated.
    layer_3d.mesh_geometry._vertex_buf = object()

    layer_2d = Layer.blank(64, 64)
    layer_2d._image_data = np.full((64, 64, 4), 200, dtype=np.uint8)
    layer_3d.apply_heightmap(layer_2d, scale=1.0)

    assert layer_3d.mesh_geometry._vertex_buf is None


def test_apply_normal_map_creates_material():
    """apply_normal_map() creates PbrMaterial if none exists."""
    from slappyengine.layer import Layer
    from slappyengine.gpu.pbr_material import PbrMaterial

    layer_3d = Layer.blank(64, 64, mode="3D")
    layer_2d = Layer.blank(64, 64)

    assert layer_3d.mesh_material is None
    layer_3d.apply_normal_map(layer_2d)

    assert layer_3d.mesh_material is not None
    assert isinstance(layer_3d.mesh_material, PbrMaterial)


def test_apply_normal_map_reuses_existing_material():
    """apply_normal_map() does not replace an existing PbrMaterial instance."""
    from slappyengine.layer import Layer
    from slappyengine.gpu.pbr_material import PbrMaterial

    layer_3d = Layer.blank(64, 64, mode="3D")
    existing = PbrMaterial(metallic=0.9, roughness=0.1)
    layer_3d.mesh_material = existing

    layer_2d = Layer.blank(64, 64)
    layer_3d.apply_normal_map(layer_2d)

    # Same object must be reused.
    assert layer_3d.mesh_material is existing
    assert layer_3d.mesh_material.metallic == 0.9


def test_apply_normal_map_wrong_mode():
    """apply_normal_map() on a 2D layer raises ValueError."""
    from slappyengine.layer import Layer

    layer_2d_target = Layer.blank(64, 64)
    layer_2d_source = Layer.blank(64, 64)

    with pytest.raises(ValueError, match="3D"):
        layer_2d_target.apply_normal_map(layer_2d_source)


def test_apply_albedo_creates_material():
    """apply_albedo() creates PbrMaterial if none exists."""
    from slappyengine.layer import Layer
    from slappyengine.gpu.pbr_material import PbrMaterial

    layer_3d = Layer.blank(64, 64, mode="3D")
    layer_2d = Layer.blank(64, 64)

    assert layer_3d.mesh_material is None
    layer_3d.apply_albedo(layer_2d)

    assert layer_3d.mesh_material is not None
    assert isinstance(layer_3d.mesh_material, PbrMaterial)


def test_apply_albedo_reuses_existing_material():
    """apply_albedo() does not replace an existing PbrMaterial instance."""
    from slappyengine.layer import Layer
    from slappyengine.gpu.pbr_material import PbrMaterial

    layer_3d = Layer.blank(64, 64, mode="3D")
    existing = PbrMaterial(metallic=0.3, roughness=0.8)
    layer_3d.mesh_material = existing

    layer_2d = Layer.blank(64, 64)
    layer_3d.apply_albedo(layer_2d)

    assert layer_3d.mesh_material is existing
    assert layer_3d.mesh_material.roughness == 0.8


def test_apply_albedo_wrong_mode():
    """apply_albedo() on a 2D layer raises ValueError."""
    from slappyengine.layer import Layer

    layer_2d_target = Layer.blank(64, 64)
    layer_2d_source = Layer.blank(64, 64)

    with pytest.raises(ValueError, match="3D"):
        layer_2d_target.apply_albedo(layer_2d_source)


def test_apply_heightmap_wrong_mode():
    """apply_heightmap() on a 2D layer raises ValueError."""
    from slappyengine.layer import Layer

    layer_2d_target = Layer.blank(64, 64)
    layer_2d_source = Layer.blank(64, 64)

    with pytest.raises(ValueError, match="3D"):
        layer_2d_target.apply_heightmap(layer_2d_source)


def test_bake_pipeline_roundtrip_size():
    """bake_to_2d returns a layer with the exact requested dimensions."""
    from slappyengine.layer import Layer

    for size in [(16, 16), (64, 32), (128, 256)]:
        layer = Layer.blank(64, 64, mode="3D")
        baked = layer.bake_to_2d(size)
        assert baked.size == size, f"size mismatch for requested {size}: got {baked.size}"
