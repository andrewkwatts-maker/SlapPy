"""Vehicle-on-terrain physics demo using the hierarchical-hull system.

A simple rectangular iron chassis drives over a bumpy stone/sand terrain.
Wheels are independent rubber circles (Sprint 1 has no joint system, so
the chassis and wheels are *coincident* bodies that interact via collision
only). Contacts kick up dust particles, the chassis deforms (cell field)
under impact, and the whole thing is rendered to a GIF.

Run:
    python examples/physics_vehicle_demo.py

Outputs ``examples/output/physics_vehicle_demo.gif``.
"""
from __future__ import annotations

import time
from pathlib import Path

from slappyengine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)
from slappyengine.physics.particles import ParticleSystem
from slappyengine.physics.post_process import default_post_process_chain
from slappyengine.physics.render import PhysicsRenderer, PointLight, RenderConfig
from slappyengine.physics.shadows import ShadowPass


# ----------------------------------------------------------------------------
# Tunables — at file-scope so tests / users can inspect them.
# ----------------------------------------------------------------------------

OUTPUT_PATH = Path(__file__).resolve().parent / "output" / "physics_vehicle_demo.gif"

WORLD_BOUNDS = (-300.0, -100.0, 300.0, 250.0)
GRAVITY = (0.0, 150.0)                      # slightly lighter than default 196

# Camera / world-view for both the renderer and particle compositor.
WORLD_VIEW = (-300.0, -100.0, 300.0, 250.0)

# Vehicle layout.
CHASSIS_SIZE = (60, 24)
CHASSIS_START = (-220.0, 100.0)
CHASSIS_VELOCITY = (80.0, 0.0)
WHEEL_DIAMETER = 16
WHEEL_OFFSETS = ((-15.0, 20.0), (15.0, 20.0))  # relative to chassis centre

# Terrain layout.
TERRAIN_GROUND_Y = 240.0          # safety floor
TERRAIN_HILLS_BASE_Y = 200.0
TERRAIN_HILL_SIZE = (80, 28)      # rectangular "hill" blocks
TERRAIN_HILL_XS = [-220.0, -110.0, 0.0, 110.0, 220.0]
TERRAIN_HILL_DY = [-8.0, 6.0, -4.0, 10.0, -6.0]   # rolling variation

FRAME_COUNT = 240
FPS = 60
DT = 1.0 / FPS


# ----------------------------------------------------------------------------
# Scene construction
# ----------------------------------------------------------------------------

def _build_world() -> tuple[PhysicsWorld, dict]:
    """Build the world and return (world, refs) where refs holds the chassis
    + wheels so the test / summary can inspect them after the run."""
    world = PhysicsWorld(world_bounds=WORLD_BOUNDS)
    # Override the default gravity in-place — WorldConfig.gravity is read each
    # half-kick, so mutating it here is enough.
    world.config.world.gravity = GRAVITY

    # Long flat ground (catches anything that misses the hills).
    world.create_body(
        make_rect_silhouette(640, 16),
        material="stone",
        position=(0.0, TERRAIN_GROUND_Y),
        fixed=True,
    )

    # Rolling hill terrain — alternating stone / sand for visual variety.
    materials = ["stone", "sand", "stone", "sand", "stone"]
    for x, dy, mat in zip(TERRAIN_HILL_XS, TERRAIN_HILL_DY, materials):
        world.create_body(
            make_rect_silhouette(*TERRAIN_HILL_SIZE),
            material=mat,
            position=(x, TERRAIN_HILLS_BASE_Y + dy),
            fixed=True,
        )

    # Vehicle chassis.
    chassis = world.create_body(
        make_rect_silhouette(*CHASSIS_SIZE),
        material="iron",
        position=CHASSIS_START,
        velocity=CHASSIS_VELOCITY,
    )

    # Wheels — independent rubber circles. With no joint system they don't
    # stay attached, but their coincident start + matching velocity means
    # they roll along under the chassis for most of the run.
    wheels = []
    for dx, dy in WHEEL_OFFSETS:
        wheel = world.create_body(
            make_circle_silhouette(WHEEL_DIAMETER),
            material="rubber",
            position=(CHASSIS_START[0] + dx, CHASSIS_START[1] + dy),
            velocity=CHASSIS_VELOCITY,
        )
        wheels.append(wheel)

    return world, {"chassis": chassis, "wheels": wheels}


def _build_renderer() -> PhysicsRenderer:
    cfg = RenderConfig(
        width=640,
        height=360,
        world_view=WORLD_VIEW,
        bg_top=(12, 14, 30),
        bg_bottom=(40, 30, 55),
        lights=[
            # Warm key light from above-left.
            PointLight(
                position=(-180.0, -50.0),
                color=(255, 220, 180),
                intensity=1.8,
                radius=400.0,
            ),
            # Cool rim light from the right.
            PointLight(
                position=(280.0, 60.0),
                color=(120, 160, 255),
                intensity=1.2,
                radius=350.0,
            ),
        ],
        ambient_intensity=0.35,
        enable_normal_map=True,
        normal_curvature_bias=0.5,
    )
    return PhysicsRenderer(config=cfg)


# ----------------------------------------------------------------------------
# Run loop
# ----------------------------------------------------------------------------

def run_demo(output_path: Path | None = None) -> dict:
    """Run the full vehicle-on-terrain demo and write a GIF.

    Returns a summary dict with: ``total_contacts``, ``particles_emitted``,
    ``runtime_seconds``, ``chassis_start_x``, ``chassis_end_x``,
    ``chassis_displacement``, ``output_path``, ``frame_count``.
    """
    if output_path is None:
        output_path = OUTPUT_PATH

    t0 = time.perf_counter()

    world, refs = _build_world()
    renderer = _build_renderer()
    particles = ParticleSystem(gravity=GRAVITY, air_drag=0.6, max_particles=2048)
    post = default_post_process_chain()
    shadows = ShadowPass(
        light_direction=(0.3, 1.0),
        shadow_length=60.0,
        opacity=0.4,
        softness_px=3.0,
        world_view=WORLD_VIEW,
    )

    chassis = refs["chassis"]
    start_x = chassis.position[0]

    frames = []
    total_contacts = 0
    total_particles = 0

    for _ in range(FRAME_COUNT):
        contacts = world.step(DT)
        total_contacts += len(contacts)

        emitted = particles.emit_from_contacts(contacts, world=world)
        total_particles += emitted
        particles.step(DT)

        frame = renderer.render(world)
        frame = particles.render(frame, world_view=WORLD_VIEW)
        frame = shadows.render(frame, world)
        frame = post.apply(frame)
        frames.append(frame)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    renderer.save_gif(frames, output_path, fps=FPS // 2)

    end_x = chassis.position[0]
    runtime = time.perf_counter() - t0

    summary = {
        "total_contacts": total_contacts,
        "particles_emitted": total_particles,
        "runtime_seconds": runtime,
        "chassis_start_x": start_x,
        "chassis_end_x": end_x,
        "chassis_displacement": end_x - start_x,
        "output_path": str(output_path),
        "frame_count": len(frames),
    }
    return summary


def _print_summary(summary: dict) -> None:
    print("=== physics_vehicle_demo summary ===")
    print(f"  GIF              : {summary['output_path']}")
    print(f"  frames           : {summary['frame_count']}")
    print(f"  runtime (s)      : {summary['runtime_seconds']:.2f}")
    print(f"  total contacts   : {summary['total_contacts']}")
    print(f"  particles emitted: {summary['particles_emitted']}")
    print(
        f"  chassis x        : {summary['chassis_start_x']:.1f} -> "
        f"{summary['chassis_end_x']:.1f}  "
        f"(d = {summary['chassis_displacement']:.1f})"
    )


if __name__ == "__main__":
    summary = run_demo()
    _print_summary(summary)
