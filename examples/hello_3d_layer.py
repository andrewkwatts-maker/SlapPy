"""Hello 3D Layer — 3D mesh on a 3D-mode layer, composited over a 2D background.

A 2D background layer provides the sky/ground colour. A separate layer with
mode="3D" holds a unit cube mesh with a metallic PBR material. The engine
renders the 3D layer to an offscreen texture each frame and blits it on top
of the 2D scene.

Camera matrices are identity in the current sprint; the cube appears
at the centre of the viewport in a orthographic-like projection.

Run:
    python examples/hello_3d_layer.py
"""
import slappyengine as se
from slappyengine.asset import Asset
from slappyengine.layer import Layer
from slappyengine.scene import Scene
from slappyengine.gpu.mesh import GpuMesh
from slappyengine.gpu.pbr_material import PbrMaterial
from slappyengine.lighting import LightingContext, PointLight

engine = se.Engine(width=640, height=360, title="Hello 3D Layer")
scene = Scene(name="Hello3DLayer")
asset = Asset(name="world", size=(640, 360))

# ------------------------------------------------------------------
# 2D background — simple gradient-ish sky colour
# ------------------------------------------------------------------
bg = Layer.blank(640, 360, name="Background")
bg._image_data[:] = [30, 30, 60, 255]   # dark blue-grey sky

asset.add_layer(bg)

# ------------------------------------------------------------------
# 3D layer — unit cube with a rust-coloured metallic PBR material
# ------------------------------------------------------------------
cube_layer = Layer.blank(640, 360, name="Cube3D", mode="3D")
cube_layer.mesh_geometry = GpuMesh.unit_cube()
cube_layer.mesh_material = PbrMaterial(
    metallic=0.8,
    roughness=0.2,
    albedo_color=(0.7, 0.3, 0.1, 1.0),
)

# Independent point light for the 3D layer
cube_layer.lighting = LightingContext()
cube_layer.lighting.add_light(
    PointLight(
        position=(320.0, 180.0),
        color=(1.0, 0.9, 0.7),
        radius=400.0,
        intensity=2.0,
    )
)

asset.add_layer(cube_layer)
scene.add(asset)

engine.load_scene(scene)
engine.run()
