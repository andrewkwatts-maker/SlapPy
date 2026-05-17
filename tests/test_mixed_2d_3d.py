"""Tests for mixed 2D/3D layer scenes — no GPU required."""
import numpy as np
import pytest


def test_layer_modes():
    """Layer can be created in 2D or 3D mode."""
    from slappyengine.layer import Layer

    layer_2d = Layer.blank(64, 64, name="BG")
    layer_3d = Layer.blank(64, 64, name="FG", mode="3D")

    assert layer_2d.mode == "2D"
    assert layer_3d.mode == "3D"


def test_3d_layer_has_mesh_slots():
    """3D layers start with None mesh geometry and material."""
    from slappyengine.layer import Layer

    layer = Layer.blank(64, 64, mode="3D")

    assert layer.mesh_geometry is None
    assert layer.mesh_material is None


def test_3d_layer_accepts_mesh():
    """Assigning a GpuMesh to layer.mesh_geometry works."""
    from slappyengine.layer import Layer
    from slappyengine.gpu.mesh import GpuMesh

    layer = Layer.blank(64, 64, mode="3D")
    layer.mesh_geometry = GpuMesh.unit_cube()

    assert layer.mesh_geometry is not None
    assert layer.mesh_geometry.vertex_count == 24


def test_3d_layer_accepts_material():
    """Assigning a PbrMaterial to layer.mesh_material works."""
    from slappyengine.layer import Layer
    from slappyengine.gpu.pbr_material import PbrMaterial

    layer = Layer.blank(64, 64, mode="3D")
    layer.mesh_material = PbrMaterial(metallic=0.7, roughness=0.2)

    assert layer.mesh_material.metallic == 0.7
    assert layer.mesh_material.roughness == 0.2


def test_mixed_layer_stack():
    """An asset can have both 2D and 3D layers stacked together."""
    from slappyengine.layer import Layer

    # Simulate an asset's layer list
    layers = [
        Layer.blank(128, 128, name="Background"),         # 2D
        Layer.blank(128, 128, name="Midground"),          # 2D
        Layer.blank(128, 128, name="City3D", mode="3D"),  # 3D
    ]

    modes = [l.mode for l in layers]
    assert modes == ["2D", "2D", "3D"]

    # 2D layers have no mesh geometry
    assert layers[0].mesh_geometry is None
    assert layers[1].mesh_geometry is None


def test_2d_layer_has_no_mode_3d_attributes():
    """2D layers have mesh_geometry=None and mesh_material=None by design."""
    from slappyengine.layer import Layer

    layer = Layer.blank(64, 64)

    assert getattr(layer, "mesh_geometry", None) is None
    assert getattr(layer, "mesh_material", None) is None
    assert layer.mode == "2D"


def test_3d_layer_lighting_context():
    """3D layer can have its own LightingContext."""
    from slappyengine.layer import Layer
    from slappyengine.lighting import LightingContext, PointLight

    layer = Layer.blank(64, 64, mode="3D")
    layer.lighting = LightingContext()
    # PointLight.position is a 2D (x, y) tuple; z is a separate field.
    layer.lighting.add_light(
        PointLight(position=(0.0, 0.0), z=100.0, color=(1.0, 0.5, 0.0), radius=200.0)
    )

    assert len(layer.lighting.lights) == 1


def test_3d_layer_default_lighting_is_none():
    """A freshly created 3D layer inherits scene-level lighting (lighting=None)."""
    from slappyengine.layer import Layer

    layer = Layer.blank(64, 64, mode="3D")
    # No LightingContext assigned yet — should defer to scene global.
    assert layer.lighting is None


def test_mode_preserved_after_mesh_assignment():
    """Assigning a mesh does not mutate the layer mode."""
    from slappyengine.layer import Layer
    from slappyengine.gpu.mesh import GpuMesh

    layer = Layer.blank(64, 64, mode="3D")
    layer.mesh_geometry = GpuMesh.unit_quad()

    assert layer.mode == "3D"


def test_unit_cube_index_count():
    """unit_cube() produces exactly 36 indices (6 faces × 2 triangles × 3 verts)."""
    from slappyengine.gpu.mesh import GpuMesh

    mesh = GpuMesh.unit_cube()
    assert mesh.index_count == 36


def test_unit_quad_vertex_count():
    """unit_quad() produces exactly 4 vertices."""
    from slappyengine.gpu.mesh import GpuMesh

    mesh = GpuMesh.unit_quad()
    assert mesh.vertex_count == 4
