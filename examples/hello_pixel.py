"""Hello Pixel — minimal SlapPyEngine example.

Creates a 256x256 canvas, draws a red cross using numpy array access,
and opens a window. Close the window to exit.

Run:
    python examples/hello_pixel.py
"""
import playslap as se
from playslap.asset import Asset
from playslap.layer import Layer
from playslap.scene import Scene

engine = se.Engine(width=256, height=256, title="Hello Pixel")
scene = Scene(name="HelloPixel")

asset = Asset(name="canvas", size=(256, 256))
layer = Layer.blank(256, 256, name="Canvas")

# Draw a red cross by writing directly into the numpy RGBA array.
# _image_data shape is (height, width, 4) — row-major, uint8.
layer._image_data[:, 128] = [255, 0, 0, 255]   # vertical bar   (all rows, col 128)
layer._image_data[128, :] = [255, 0, 0, 255]   # horizontal bar (row 128, all cols)

asset.add_layer(layer)
scene.add(asset)

engine.load_scene(scene)
engine.run()
