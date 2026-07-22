"""Vehicle-on-terrain physics demo with the constraint solver wiring the
wheels to the chassis.

This is the companion to :mod:`examples.physics_vehicle_demo`.  The
original demo predates the joint system, so its chassis and wheels are
free-flying bodies that disintegrate the moment the assembly hits a
bump.  Here we bolt the assembly together with two
:class:`~pharos_engine.physics.constraints.PinConstraint` joints solved
each frame by a :class:`~pharos_engine.physics.constraints.ConstraintSolver`
running at 8 iterations for stability across the bumpy terrain.

Run::

    python examples/physics_vehicle_jointed_demo.py

Outputs ``examples/output/physics_vehicle_jointed_demo.gif`` and prints a
summary including the average chassis<->wheel distance throughout the
run -- a direct measurement of how well the joints hold the assembly
together.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

from pharos_engine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)
from pharos_engine.physics.constraints import (
    ConstraintSolver,
    PinConstraint,
)
from pharos_engine.physics.particles import ParticleSystem
from pharos_engine.physics.post_process import default_post_process_chain
from pharos_engine.physics.render import PhysicsRenderer, PointLight, RenderConfig


# ----------------------------------------------------------------------------
# Tunables -- file-scope so tests / users can inspect them.
# ----------------------------------------------------------------------------

OUTPUT_PATH = Path(__file__).resolve().parent / "output" / "physics_vehicle_jointed_demo.gif"

WORLD_BOUNDS = (-300.0, -100.0, 300.0, 250.0)
GRAVITY = (0.0, 150.0)
WORLD_VIEW = (-300.0, -100.0, 300.0, 250.0)

# Vehicle layout.
CHASSIS_SIZE = (60, 24)
CHASSIS_START = (-220.0, 100.0)
CHASSIS_VELOCITY = (80.0, 0.0)
WHEEL_DIAMETER = 16
# Wheels placed one under each end of the chassis.  Chassis is 60x24,
# so its local bottom corners are at (+/-15, +12) -- the joint local
# anchor on the chassis side.  The wheel local anchor is (0, 0) (its
# own centre), so the joint pulls the wheel centre to the chassis
# bottom corner.  Starting the wheels at world (-235, 120) / (-205,
# 120) gives the joint an initial 8 px violation, which would launch
# the assembly skyward through the velocity-impulse half of the
# correction; we instead start them at the joint's equilibrium
# (-235, 112) / (-205, 112) so the run begins in a coherent state and
# we measure how well the solver *keeps* it that way across hills.
WHEEL_WORLD_START = ((-235.0, 112.0), (-205.0, 112.0))
JOINT_LOCAL_ANCHORS_A = ((-15.0, 12.0), (15.0, 12.0))  # on chassis
JOINT_LOCAL_ANCHOR_B = (0.0, 0.0)                      # on wheel centre
# Joint-target distance between chassis CoM and wheel CoM.  When the
# pin is satisfied the wheel sits at the chassis-local point
# (+/-15, +12), so the centre-to-centre distance is hypot(15, 12).
INITIAL_CHASSIS_WHEEL_DISTANCE = math.hypot(15.0, 12.0)  # approx 19.21

# Terrain layout (matches the un-jointed demo so visuals are comparable).
TERRAIN_GROUND_Y = 240.0
TERRAIN_HILLS_BASE_Y = 200.0
TERRAIN_HILL_SIZE = (80, 28)
TERRAIN_HILL_XS = [-220.0, -110.0, 0.0, 110.0, 220.0]
TERRAIN_HILL_DY = [-8.0, 6.0, -4.0, 10.0, -6.0]
TERRAIN_MATERIALS = ["stone", "sand", "stone", "sand", "stone"]

FRAME_COUNT = 240
FPS = 60
DT = 1.0 / FPS

CONSTRAINT_ITERATIONS = 8


# ----------------------------------------------------------------------------
# Scene construction
# ----------------------------------------------------------------------------


def _build_world() -> tuple[PhysicsWorld, dict]:
    world = PhysicsWorld(world_bounds=WORLD_BOUNDS)
    world.config.world.gravity = GRAVITY

    # Long flat safety ground.
    world.create_body(
        make_rect_silhouette(640, 16),
        material="stone",
        position=(0.0, TERRAIN_GROUND_Y),
        fixed=True,
    )

    # Bumpy stone/sand hills.
    for x, dy, mat in zip(TERRAIN_HILL_XS, TERRAIN_HILL_DY, TERRAIN_MATERIALS):
        world.create_body(
            make_rect_silhouette(*TERRAIN_HILL_SIZE),
            material=mat,
            position=(x, TERRAIN_HILLS_BASE_Y + dy),
            fixed=True,
        )

    # Chassis.
    chassis = world.create_body(
        make_rect_silhouette(*CHASSIS_SIZE),
        material="iron",
        position=CHASSIS_START,
        velocity=CHASSIS_VELOCITY,
    )

    # Wheels at the spec'd absolute world positions, matching the chassis
    # velocity so the assembly starts coherent.
    wheels = []
    for wx, wy in WHEEL_WORLD_START:
        wheel = world.create_body(
            make_circle_silhouette(WHEEL_DIAMETER),
            material="rubber",
            position=(wx, wy),
            velocity=CHASSIS_VELOCITY,
        )
        wheels.append(wheel)

    return world, {"chassis": chassis, "wheels": wheels}


def _build_solver(refs: dict) -> ConstraintSolver:
    """Wire two PinConstraints (chassis<->left wheel, chassis<->right wheel)
    into a single solver and crank the iteration count up to 8 -- the
    rolling terrain is rough enough that the default 4 visibly stretches
    the assembly on the steeper hill crests."""
    solver = ConstraintSolver(iterations=CONSTRAINT_ITERATIONS)
    chassis = refs["chassis"]
    for wheel, local_a in zip(refs["wheels"], JOINT_LOCAL_ANCHORS_A):
        solver.add(
            PinConstraint(
                body_a=chassis,
                body_b=wheel,
                local_anchor_a=local_a,
                local_anchor_b=JOINT_LOCAL_ANCHOR_B,
            )
        )
    return solver


def _build_renderer() -> PhysicsRenderer:
    cfg = RenderConfig(
        width=640,
        height=360,
        world_view=WORLD_VIEW,
        bg_top=(10, 12, 28),
        bg_bottom=(45, 28, 60),
        lights=[
            PointLight(
                position=(-180.0, -50.0),
                color=(255, 220, 180),
                intensity=1.8,
                radius=400.0,
            ),
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
    """Build, simulate, render, and write the GIF.

    Returns a summary dict with the same fields as the un-jointed demo,
    plus ``avg_chassis_wheel_distance`` (list of two floats, one per
    wheel), ``max_chassis_wheel_distance`` (same), ``broken_constraints``
    (int), and ``constraint_iterations``.
    """
    if output_path is None:
        output_path = OUTPUT_PATH

    t0 = time.perf_counter()

    world, refs = _build_world()
    renderer = _build_renderer()
    psys = ParticleSystem(gravity=GRAVITY, air_drag=0.6, max_particles=2048)
    post_chain = default_post_process_chain()
    solver = _build_solver(refs)

    chassis = refs["chassis"]
    wheels = refs["wheels"]
    start_x = chassis.position[0]

    frames: list = []
    total_contacts = 0
    total_particles = 0

    # Per-wheel running stats for the chassis<->wheel separation.
    dist_sum = [0.0, 0.0]
    dist_max = [0.0, 0.0]
    dist_samples = 0
    # Recorded per-frame distances so the test can sample specific frames.
    per_frame_distances: list[tuple[float, float]] = []

    for _f in range(FRAME_COUNT):
        contacts = world.step(DT)
        solver.solve(world, DT)

        total_contacts += len(contacts)

        emitted = psys.emit_from_contacts(
            contacts,
            world=world,
            hulls=world.hulls,
            body_lookup=world._body_for_hull,
        )
        total_particles += emitted
        psys.step(DT)

        frame = renderer.render(world)
        frame = psys.render(frame, world_view=WORLD_VIEW)
        frame = post_chain.apply(frame)
        frames.append(frame)

        # Sample the chassis<->wheel CoM separation.
        cx, cy = chassis.position
        d_l = math.hypot(wheels[0].position[0] - cx, wheels[0].position[1] - cy)
        d_r = math.hypot(wheels[1].position[0] - cx, wheels[1].position[1] - cy)
        per_frame_distances.append((d_l, d_r))
        dist_sum[0] += d_l
        dist_sum[1] += d_r
        dist_max[0] = max(dist_max[0], d_l)
        dist_max[1] = max(dist_max[1], d_r)
        dist_samples += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    renderer.save_gif(frames, output_path, fps=FPS // 2)

    end_x = chassis.position[0]
    runtime = time.perf_counter() - t0

    avg = [dist_sum[i] / max(1, dist_samples) for i in range(2)]

    summary = {
        "total_contacts": total_contacts,
        "particles_emitted": total_particles,
        "runtime_seconds": runtime,
        "chassis_start_x": start_x,
        "chassis_end_x": end_x,
        "chassis_displacement": end_x - start_x,
        "output_path": str(output_path),
        "frame_count": len(frames),
        "avg_chassis_wheel_distance": avg,
        "max_chassis_wheel_distance": list(dist_max),
        "initial_chassis_wheel_distance": INITIAL_CHASSIS_WHEEL_DISTANCE,
        "per_frame_chassis_wheel_distance": per_frame_distances,
        "broken_constraints": len(solver.broken),
        "active_constraints": len(solver.constraints),
        "constraint_iterations": CONSTRAINT_ITERATIONS,
    }
    return summary


def _print_summary(summary: dict) -> None:
    print("=== physics_vehicle_jointed_demo summary ===")
    print(f"  GIF                : {summary['output_path']}")
    print(f"  frames             : {summary['frame_count']}")
    print(f"  runtime (s)        : {summary['runtime_seconds']:.2f}")
    print(f"  total contacts     : {summary['total_contacts']}")
    print(f"  particles emitted  : {summary['particles_emitted']}")
    print(
        f"  chassis x          : {summary['chassis_start_x']:.1f} -> "
        f"{summary['chassis_end_x']:.1f}  "
        f"(d = {summary['chassis_displacement']:.1f})"
    )
    print(f"  joint iterations   : {summary['constraint_iterations']}")
    print(f"  joints active/broken: {summary['active_constraints']}/{summary['broken_constraints']}")
    initial = summary["initial_chassis_wheel_distance"]
    avg = summary["avg_chassis_wheel_distance"]
    mx = summary["max_chassis_wheel_distance"]
    print(
        f"  chassis<->wheel L  : avg={avg[0]:.2f}  max={mx[0]:.2f}  "
        f"(target={initial:.2f})"
    )
    print(
        f"  chassis<->wheel R  : avg={avg[1]:.2f}  max={mx[1]:.2f}  "
        f"(target={initial:.2f})"
    )


if __name__ == "__main__":
    summary = run_demo()
    _print_summary(summary)
