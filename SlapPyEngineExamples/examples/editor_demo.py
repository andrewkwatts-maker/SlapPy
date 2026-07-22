"""
Editor demo — opens the DPG editor shell with a sample scene.

Requirements: pip install SlapPyEngine[editor]
Run:          python examples/editor_demo.py

What this example sets up
-------------------------
- A 256x256 asset with a single blank layer painted half-blue (water) and
  half-brown (soil), matching the fluid_sandbox example so the material map
  makes sense visually.
- A MaterialMap with water and soil entries.
- An AnimationGraph with two states (idle and run) attached to a second,
  smaller sprite asset so the AnimGraphPanel has something to display.
- Calls engine.run_editor() which opens the Dear PyGui editor shell with
  all registered panels pre-populated from the scene.

If dearpygui is not installed the script prints a friendly message and exits
without raising an unhandled exception.
"""

try:
    import dearpygui.dearpygui  # noqa: F401 — guard before any engine import
except ImportError:
    print("Missing dependency: dearpygui")
    print("Install with:  pip install SlapPyEngine[editor]")
    raise SystemExit(1)

import pharos_engine as se
from pharos_engine.asset import Asset
from pharos_engine.layer import Layer
from pharos_engine.material import MaterialMap, ColorRange
from pharos_engine.scene import Scene
from pharos_engine.animation.graph import AnimationGraph, AnimState, AnimTransition


# ---------------------------------------------------------------------------
# Scene setup
# ---------------------------------------------------------------------------

engine = se.Engine(title="SlapPyEngine — Editor Demo")
scene = Scene(name="EditorDemo")
engine.load_scene(scene)

# ---- Main terrain asset --------------------------------------------------
terrain = Asset(name="terrain", size=(256, 256))
ground = Layer.blank(256, 256, name="Ground")
ground._image_data[:128, :] = [30, 60, 220, 255]   # top half: water (blue)
ground._image_data[128:, :] = [120, 85, 40, 255]   # bottom half: soil (brown)
terrain.add_layer(ground)

terrain.material_map = MaterialMap()
terrain.material_map.add(
    "water",
    ColorRange(r=(0, 40), g=(0, 80), b=(180, 255)),
    alpha_meaning="opacity",
    behaviors=["fluid"],
    params={"viscosity": 0.001, "density": 1.0},
)
terrain.material_map.add(
    "soil",
    ColorRange(r=(80, 160), g=(50, 120), b=(0, 60)),
    alpha_meaning="opacity",
    behaviors=["rigid"],
    params={"density": 1.8, "cohesion": 0.4},
)

scene.add(terrain)

# ---- Sprite asset with animation graph -----------------------------------
sprite = Asset(name="sprite", position=(300.0, 100.0), size=(32, 32))
sprite_layer = Layer.blank(32, 32, name="Sprite")
sprite_layer._image_data[:] = [200, 80, 80, 255]   # solid red placeholder
sprite.add_layer(sprite_layer)

graph = AnimationGraph()
graph.add_state(AnimState(name="idle", clip_indices=[0, 1], loop=True, fps=8.0))
graph.add_state(AnimState(name="run",  clip_indices=[2, 3, 4, 5], loop=True, fps=16.0))
graph.add_transition(AnimTransition(from_state="idle", to_state="run"))
graph.add_transition(AnimTransition(from_state="run",  to_state="idle"))
graph.set_initial("idle")

# Attach the graph directly to the sprite asset so the editor can find it
sprite.anim_graph = graph

scene.add(sprite)

# ---------------------------------------------------------------------------
# Launch editor
# ---------------------------------------------------------------------------

print("Opening SlapPyEngine editor...")
print("Close the editor window to exit.")

engine.run_editor()
