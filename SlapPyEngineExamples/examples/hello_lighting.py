"""Hello Lighting — per-layer LightingContext demo.

Two layers are set up with independent lighting so they do not bleed into
each other:

  Background — warm amber directional light, moderate ambient.
  Foreground — dark night sky with a single cool-blue point light.

Each layer's ``lighting`` attribute holds a :class:`LightingContext`.
The engine's scene-level :class:`LightingSystem` is still available for
lights that should affect every layer globally.

Run:
    python examples/hello_lighting.py
"""
import pharos_engine as se
from pharos_engine.asset import Asset
from pharos_engine.layer import Layer
from pharos_engine.scene import Scene
from pharos_engine.lighting import LightingContext, DirectionalLight, PointLight

engine = se.Engine(width=640, height=360, title="Hello Lighting")
scene = Scene(name="HelloLighting")
asset = Asset(name="world", size=(640, 360))

# ------------------------------------------------------------------
# Background layer — warm amber sunlight
# ------------------------------------------------------------------
bg = Layer.blank(640, 360, name="Background")
bg._image_data[:] = [80, 60, 40, 255]   # dark earthy fill so lighting is visible

bg.lighting = LightingContext(
    ambient_color=(0.9, 0.7, 0.4),
    ambient_intensity=0.5,
    mode="local",   # only bg's own lights affect this layer
)
bg.lighting.add_light(
    DirectionalLight(
        direction=(0.5, -1.0),
        color=(1.0, 0.85, 0.5),
        intensity=1.2,
    )
)

# ------------------------------------------------------------------
# Foreground layer — cool dark night sky with a point-light lantern
# ------------------------------------------------------------------
fg = Layer.blank(640, 360, name="Foreground")
fg._image_data[:] = [10, 10, 30, 128]   # semi-transparent night overlay

fg.lighting = LightingContext(
    ambient_color=(0.05, 0.05, 0.2),
    ambient_intensity=0.1,
    mode="local",   # independent — no bleed-through from bg
)
fg.lighting.add_light(
    PointLight(
        position=(320.0, 180.0),
        radius=200.0,
        color=(0.0, 0.5, 1.0),
        intensity=3.0,
    )
)

asset.add_layer(bg)
asset.add_layer(fg)
scene.add(asset)

engine.load_scene(scene)
engine.run()
