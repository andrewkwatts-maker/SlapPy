"""
Pharos Engine — Fluid Sandbox

Demonstrates the material system and fluid simulation.
Blue pixels flow as water; brown pixels clump as soil.
(Compute shaders implemented in M4 — this example shows the API.)
"""
import numpy as np
import pharos_engine as se
from pharos_engine.asset import Asset
from pharos_engine.layer import Layer
from pharos_engine.material import MaterialMap, ColorRange
from pharos_engine.scene import Scene

engine = se.Engine(title="Fluid Sandbox")
scene = Scene(name="Sandbox")
engine.load_scene(scene)

# Create an asset with one layer
asset = Asset(name="sandbox", size=(256, 256))
layer = Layer.blank(256, 256, name="Ground")
# Paint some blue and brown pixels manually
layer._image_data[:128, :] = [30, 60, 220, 255]   # water (blue, top half)
layer._image_data[128:, :] = [120, 85, 40, 255]   # soil (brown, bottom half)
asset.add_layer(layer)

# Build a material map from color ranges
asset.material_map = MaterialMap()
asset.material_map.add(
    "water",
    ColorRange(r=(0, 40), g=(0, 80), b=(180, 255)),
    alpha_meaning="opacity",
    behaviors=["fluid"],
    params={"viscosity": 0.001, "density": 1.0},
)
asset.material_map.add(
    "soil",
    ColorRange(r=(80, 160), g=(50, 120), b=(0, 60)),
    behaviors=["rigid"],
    params={"density": 1.8, "cohesion": 0.4},
)

# Optional: apply a NodeMaterial vortex effect (requires _core extension)
try:
    from pharos_engine.material.node_material import (
        NodeMaterial, UVNode, GravityWarpNode, SampleTextureNode, FinalColorNode
    )
    mat = NodeMaterial("vortex")
    uv = mat.node(UVNode())
    warp = mat.node(GravityWarpNode(strength=0.5, radius=0.4))
    sample = mat.node(SampleTextureNode())
    out = mat.node(FinalColorNode())
    mat.connect(uv, "uv", warp, "uv")
    mat.connect(warp, "out_uv", sample, "uv")
    mat.connect(sample, "color", out, "color")
    asset.add_effect(mat, blend="normal")
except (ImportError, RuntimeError):
    pass  # _core not available in this environment

scene.add(asset)

engine.run()
