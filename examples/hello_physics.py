"""Hello Physics — pixel compute physics demo.

Scatters 500 sand-coloured pixels near the top of a 256x256 canvas and
enables the scene's pixel physics pass. On each GPU frame the engine
dispatches the built-in ``pixel_physics`` compute shader (gravity + stacking)
so pixels fall and pile up at the bottom.

The pixel physics pass is opt-in: set ``scene.pixel_physics_enabled = True``
before calling ``engine.run()``. The compute shader is dispatched
automatically inside the engine draw loop for every Asset with a wired
AssetComputeAPI.

Run:
    python examples/hello_physics.py
"""
import random
import numpy as np
import playslap as se
from playslap.asset import Asset
from playslap.layer import Layer
from playslap.scene import Scene

engine = se.Engine(width=256, height=256, title="Hello Physics")
scene = Scene(name="HelloPhysics")

asset = Asset(name="sandbox", size=(256, 256))
layer = Layer.blank(256, 256, name="Sand")

# Scatter coloured sand pixels near the top of the canvas.
# _image_data is a (height, width, 4) uint8 numpy array — index as [y, x].
img = layer._image_data
rng = random.Random(42)   # fixed seed for reproducibility
for _ in range(500):
    x = rng.randint(10, 245)
    y = rng.randint(5, 30)
    r = rng.randint(180, 240)
    g = rng.randint(150, 200)
    img[y, x] = [r, g, 80, 255]

asset.add_layer(layer)
scene.add(asset)

# Enable per-pixel gravity simulation. The engine dispatches
# the "pixel_physics" WGSL compute shader each frame for every Asset
# whose AssetComputeAPI is wired (happens automatically in engine._wire_compute).
scene.pixel_physics_enabled = True

engine.load_scene(scene)
engine.run()
