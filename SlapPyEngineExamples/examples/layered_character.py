"""
layered_character.py — Demonstrates the layer reveal system.

Layers: Skin (top) → Muscle (revealed when skin health < threshold) → Bone (final)
Health module channels: health, max_health
Damage: each tick, skin health drops; when it falls below 0.3, the layer alpha fades.
"""
import numpy as np
from pharos_engine import Engine
from pharos_engine.scene import Scene
from pharos_engine.asset import Asset
from pharos_engine.layer import Layer
from pharos_engine.camera import Camera
from pharos_engine.material import MaterialMap, ColorRange
from pharos_engine.modules.health import HealthModule
from pharos_engine.animation.procedural import ProceduralRig, ControlPoint


def make_warrior(width: int = 64, height: int = 128) -> Asset:
    asset = Asset(name="warrior", size=(width, height))

    # Skin layer — red-ish flesh tone
    skin = Layer.blank(width, height, name="skin")
    # Fill with a skin colour (RGBA 220, 180, 150, 255)
    skin._image_data = np.full((height, width, 4), [220, 180, 150, 255], dtype=np.uint8)
    skin.opacity = 1.0
    asset.add_layer(skin)

    # Muscle layer — deep red
    muscle = Layer.blank(width, height, name="muscle")
    muscle._image_data = np.full((height, width, 4), [180, 60, 60, 255], dtype=np.uint8)
    muscle.opacity = 0.0   # hidden until skin wears away
    asset.add_layer(muscle)

    # Bone layer — white/grey
    bone = Layer.blank(width, height, name="bone")
    bone._image_data = np.full((height, width, 4), [240, 235, 220, 255], dtype=np.uint8)
    bone.opacity = 0.0   # hidden until muscle wears away
    asset.add_layer(bone)

    return asset


def make_arm_rig() -> ProceduralRig:
    rig = ProceduralRig()
    rig.add_point(ControlPoint("shoulder", uv=(0.5, 0.2)))
    rig.add_point(ControlPoint("elbow",    uv=(0.5, 0.4), parent="shoulder"))
    rig.add_point(ControlPoint("hand",     uv=(0.5, 0.6), parent="elbow"))
    return rig


def simulate_damage(asset: Asset, dt: float, skin_health: list[float]) -> None:
    """
    Each tick, reduce the skin health state variable.
    Update layer opacity based on current health values.
    (Without GPU compute wired, we mutate opacity directly as a demo.)
    """
    DAMAGE_RATE = 0.05   # from config ideally, but demo is standalone
    REVEAL_THRESHOLD = 0.3

    skin_health[0] = max(0.0, skin_health[0] - DAMAGE_RATE * dt)
    h = skin_health[0]

    if len(asset.layers) >= 3:
        skin_layer   = asset.layers[0]
        muscle_layer = asset.layers[1]
        bone_layer   = asset.layers[2]

        skin_layer.opacity   = h
        muscle_layer.opacity = 1.0 - h if h < REVEAL_THRESHOLD else 0.0
        bone_layer.opacity   = 1.0 - h if h < REVEAL_THRESHOLD * 0.3 else 0.0


def main() -> None:
    engine = Engine(title="Layered Character Demo", width=640, height=480)
    engine.register_module(HealthModule)

    warrior = make_warrior()
    warrior.position = (288.0, 176.0)   # roughly centred

    arm_rig = make_arm_rig()

    scene = Scene(name="CharDemo")
    scene.camera = Camera()
    scene.add(warrior)

    # Simulate IK: move hand toward a target UV each tick
    target_uv = [0.5, 0.8]
    skin_health = [1.0]

    tick_count = [0]
    original_on_tick = warrior.tick

    def warrior_tick(dt: float) -> None:
        original_on_tick(dt)
        tick_count[0] += 1

        # Solve arm IK toward a slowly moving target
        target_uv[0] = 0.5 + 0.2 * np.sin(tick_count[0] * 0.05)
        target_uv[1] = 0.6 + 0.1 * np.cos(tick_count[0] * 0.05)
        pose = arm_rig.solve_ik({"hand": (target_uv[0], target_uv[1])})

        # Apply damage each tick
        simulate_damage(warrior, dt, skin_health)

        if tick_count[0] % 60 == 0:
            h = skin_health[0]
            print(f"Tick {tick_count[0]:4d} | skin health: {h:.2f} | "
                  f"hand UV: ({pose.get('hand', target_uv)[0]:.2f}, "
                  f"{pose.get('hand', target_uv)[1]:.2f})")

    warrior.tick = warrior_tick

    engine.load_scene(scene)
    engine.run()


if __name__ == "__main__":
    main()
