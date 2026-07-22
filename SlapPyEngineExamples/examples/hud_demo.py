"""
HUD demo — in-game HUD using SceneUIEntity.

Shows how to:
  - Create a SceneUIEntity for an in-game heads-up display
  - Update HUD text each frame with simulated game state
  - Composite the UI over the game world using scene.add()
  - Handle mouse clicks on the HUD widget

Run: python examples/hud_demo.py
"""

try:
    import pharos_engine as se
    from pharos_engine.engine import Engine
    from pharos_engine.scene import Scene
    from pharos_engine.asset import Asset
    from pharos_engine.layer import Layer
    from pharos_engine.ui.scene_ui import SceneUIEntity
except ImportError as e:
    print(f"Import error: {e}")
    print("Run 'maturin develop' to build the Rust extension first.")
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Engine + scene
# ---------------------------------------------------------------------------

engine = Engine(title="SlapPyEngine — HUD Demo")
scene = Scene(name="HUDDemo")
engine.load_scene(scene)


# ---------------------------------------------------------------------------
# Player asset (green placeholder sprite)
# ---------------------------------------------------------------------------

player = Asset(name="player", position=(200.0, 200.0), size=(32, 32))
player_layer = Layer.blank(32, 32, name="Body")
player_layer._image_data[:] = [80, 160, 80, 255]   # solid green
player.add_layer(player_layer)
scene.add(player)


# ---------------------------------------------------------------------------
# HUD entity — top-left of screen
# ---------------------------------------------------------------------------

hud = SceneUIEntity(name="hud", position=(10.0, 10.0), size=(220, 90))
hud.set_background(0, 0, 0, 160)          # semi-transparent dark background
hud.set_text_color(255, 255, 255, 255)    # white text
hud.set_text("HP: 100", "Score: 0", "Pos: (200, 200)")
scene.add(hud)


# ---------------------------------------------------------------------------
# Game state — updated via an attached script on the player entity
#
# Entity.tick() calls script.on_tick(entity, dt) for every attached script.
# Scene._tick() calls tick() on every entity, so this runs each frame
# without patching any engine internals.
# ---------------------------------------------------------------------------

class HUDScript:
    """Script that tracks simulated game state and refreshes the HUD."""

    def __init__(self, hud_entity: SceneUIEntity):
        self._hud = hud_entity
        self._health = 100
        self._score = 0
        self._elapsed = 0.0     # seconds since last stat update
        self._frame = 0

    def on_tick(self, entity: Asset, dt: float) -> None:
        self._frame += 1
        self._elapsed += dt

        # Simulate: drain 1 HP and award 10 points every second
        if self._elapsed >= 1.0:
            self._elapsed -= 1.0
            self._health = max(0, self._health - 1)
            self._score += 10

        # Keep position display in sync with the player asset
        px, py = entity.position

        self._hud.set_text(
            f"HP:    {self._health}",
            f"Score: {self._score}",
            f"Pos:   ({px:.0f}, {py:.0f})",
        )

        # Visual feedback: tint HUD red when health is low
        if self._health <= 20:
            self._hud.set_text_color(255, 80, 80, 255)
        else:
            self._hud.set_text_color(255, 255, 255, 255)

        # Log focus state when the HUD is clicked
        # (handle_mouse is called by the engine each frame before _tick)
        if self._hud.focused:
            pass  # focused state available; extend here for keyboard input


player.attach_script(HUDScript(hud))


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

print("SlapPyEngine HUD Demo")
print("  The HUD in the top-left corner updates every second.")
print("  Click on the HUD panel to give it focus (Sprint 9 input routing).")
print("  Close the window to exit.")

engine.run()
