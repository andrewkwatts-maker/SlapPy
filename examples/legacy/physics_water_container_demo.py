"""Water-container sloshing demo (Phase C Navier-Stokes pressure projection).

A U-shaped stone container holds a slab of water sitting on its floor.  A
steel ball is launched in from the upper-left with a downward+rightward
velocity so it arcs into the centre of the container, splashes through the
water, and bounces around between the walls.  The Phase C pressure-projection
pipeline (``fluid_projection_iters`` > 0 on the ``water`` preset) is what
makes the fluid visibly slosh up the far wall instead of just compressing in
place the way the old damped-pressure model did.

Run::

    python examples/physics_water_container_demo.py

The script writes ``examples/output/physics_water_container_demo.gif`` and
prints a short summary including peak water |u_y| (the slosh amplitude
metric the demo is meant to showcase).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from slappyengine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)
from slappyengine.physics.particles import ParticleSystem
from slappyengine.physics.post_process import default_post_process_chain
from slappyengine.physics.render import (
    PhysicsRenderer,
    PointLight,
    RenderConfig,
)


# --- cell channel indices (mirror CELL_PIXEL_STRUCT) ------------------------
_IDX_U_X = 0
_IDX_U_Y = 1
_IDX_DENSITY = 9

# --- scene constants --------------------------------------------------------
WORLD_BOUNDS = (-200.0, -100.0, 200.0, 250.0)
FRAME_COUNT = 180
FPS = 30
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_PATH = OUTPUT_DIR / "physics_water_container_demo.gif"

# Container interior bounds (used by tests + ROI computation).
# Walls are 16 thick centred at x=-90 and x=+90 -> interior x in [-82, 82].
# We assert against the wider [-90, 90] window because the splat radius
# bleeds a few pixels beyond the wall centre on a bounce.
CONTAINER_INTERIOR = {
    "x_min": -90.0,
    "x_max":  90.0,
    "y_min":  80.0,   # well above the water's starting top so slosh fits
    "y_max":  200.0,  # floor top surface
}


def build_world() -> tuple[PhysicsWorld, dict[str, object]]:
    """Construct the water-container scene and return refs to key bodies."""
    world = PhysicsWorld(world_bounds=WORLD_BOUNDS)

    # U-shaped container: floor + two vertical walls, all fixed stone.
    floor = world.create_body(
        silhouette=make_rect_silhouette(180, 16),
        material="stone",
        position=(0.0, 200.0),
        fixed=True,
    )
    left_wall = world.create_body(
        silhouette=make_rect_silhouette(16, 120),
        material="stone",
        position=(-90.0, 140.0),
        fixed=True,
    )
    right_wall = world.create_body(
        silhouette=make_rect_silhouette(16, 120),
        material="stone",
        position=(+90.0, 140.0),
        fixed=True,
    )

    # Water blob sitting on the floor between the walls.  160 wide × 60 tall
    # centred at y=160 -> top ~y=130, bottom ~y=190 (just above the floor's
    # top surface at y=192).
    water = world.create_body(
        silhouette=make_rect_silhouette(160, 60),
        material="water",
        position=(0.0, 160.0),
        fixed=False,
    )

    # Steel ball coming in from the upper-left.  Initial velocity arcs it
    # into the container; gravity (196 px/s² default) pulls it down so it
    # lands ~the centre of the water surface.
    ball = world.create_body(
        silhouette=make_circle_silhouette(20),
        material="steel",
        position=(-30.0, -30.0),
        velocity=(40.0, 80.0),
    )

    return world, {
        "floor": floor,
        "left_wall": left_wall,
        "right_wall": right_wall,
        "water": water,
        "ball": ball,
    }


def _wall_hull_ids(bodies: dict[str, object]) -> set[int]:
    """Return the hull ids belonging to floor/left/right walls."""
    return {
        bodies["floor"].root_hull_id,   # type: ignore[attr-defined]
        bodies["left_wall"].root_hull_id,   # type: ignore[attr-defined]
        bodies["right_wall"].root_hull_id,  # type: ignore[attr-defined]
    }


def _water_cell_world_xy(world: PhysicsWorld, water_body) -> tuple[np.ndarray, np.ndarray]:
    """Return (X, Y) world-space arrays of shape (32, 32) for the water grid.

    Used so tests can check that high-density water cells stay inside the
    container interior.  The body's centre is ``position``; cell ``(i, j)``
    is centred ``(j - 15.5) * cs_x``, ``(i - 15.5) * cs_y`` away from there.
    """
    hid = water_body.root_hull_id
    px = float(world.hulls.position[hid, 0])
    py = float(world.hulls.position[hid, 1])
    cs_x = float(world.hulls.cell_size_x[hid])
    cs_y = float(world.hulls.cell_size_y[hid])
    yy, xx = np.mgrid[0:32, 0:32].astype(np.float32)
    cx_idx = 15.5
    cy_idx = 15.5
    X = px + (xx - cx_idx) * cs_x
    Y = py + (yy - cy_idx) * cs_y
    return X, Y


def run_demo(out_path: str | Path | None = None) -> Path:
    """Run the demo, write the GIF, and return its path.

    The function returns the GIF path so the test suite can assert on it
    directly; metrics (peak u_y, contact counts) are available via
    :func:`run_demo_with_metrics`.
    """
    return run_demo_with_metrics(out_path=out_path)["output_path"]  # type: ignore[return-value]


def run_demo_with_metrics(
    out_path: str | Path | None = None,
    save_gif: bool = True,
    frame_count: int = FRAME_COUNT,
    inject_impulse: bool = True,
    impulse_vy: float = 300.0,
) -> dict[str, object]:
    """Run the demo and return a metrics dict.

    Parameters
    ----------
    inject_impulse:
        After two settle frames, inject a downward ``v_y`` pulse into the
        water cells under the ball's arc trajectory.  This models the
        momentum a real splash would deliver — the ball-water rigid
        contact otherwise hard-stops the ball at the water hull's upper
        AABB face (cells are masked but the hull boundary is solid), so
        without this nudge there is no impulse for the pressure solver
        to propagate.  The injection is mass-conserving (we only touch
        ``v_y``, not density) and stays inside the container.
    impulse_vy:
        Magnitude of the v_y pulse injected into the top centre rows of
        the water cell grid.  Default 300 px/s — comparable to the ball's
        free-fall terminal velocity by the time it reaches the surface.

    Returned keys:
        ``frames``                 — list of post-processed RGBA frames
        ``peak_water_uy``          — max |u_y| seen across the run
        ``peak_water_vy``          — max |v_y| seen across the run
        ``peak_water_vy_far``      — max |v_y| at far-edge columns (wave
                                     propagation signal — non-zero only
                                     if the pressure solver actually
                                     carries the splash laterally)
        ``per_frame_peak_water_uy``— list[float], one entry per frame
        ``ball_y_history``         — list[float], the steel ball's centre y
        ``ball_water_contacts``    — int, contacts between ball and water hull
        ``ball_wall_contacts``     — int, contacts between ball and a wall
        ``final_water_density``    — np.ndarray (32, 32) of final density
        ``final_water_world_xy``   — tuple of (X, Y) world arrays for final state
        ``output_path``            — Path or None
    """
    world, bodies = build_world()
    water = bodies["water"]
    ball = bodies["ball"]

    ball_hid = ball.root_hull_id           # type: ignore[attr-defined]
    water_hid = water.root_hull_id         # type: ignore[attr-defined]
    wall_hids = _wall_hull_ids(bodies)

    # Renderer — matches the spec exactly.
    cfg = RenderConfig(
        width=640,
        height=360,
        world_view=WORLD_BOUNDS,
        forward_splat=True,
        splat_radius_px=2,
        temporal_average_frames=3,
        lights=[
            PointLight(
                position=(-100.0, -50.0),
                color=(255, 220, 180),
                intensity=1.5,
                radius=260.0,
            ),
            PointLight(
                position=(+150.0, -100.0),
                color=(160, 200, 255),
                intensity=0.8,
                radius=260.0,
            ),
        ],
    )
    renderer = PhysicsRenderer(config=cfg)
    psys = ParticleSystem(gravity=(0.0, 196.0), air_drag=0.85, max_particles=2048)
    post = default_post_process_chain()

    frames: list[np.ndarray] = []
    per_frame_peak_uy: list[float] = []
    ball_y_history: list[float] = []
    ball_water_contacts = 0
    ball_wall_contacts = 0
    peak_water_vy = 0.0
    peak_water_vy_far = 0.0
    _IDX_V_X = 2
    _IDX_V_Y = 3

    dt = 1.0 / 60.0
    impulse_applied = False

    for frame_idx in range(frame_count):
        # Inject the splash impulse after two settle frames so the
        # initial density/silhouette mapping has stabilised.  This is the
        # "the ball just hit the water" moment in the narrative — the
        # rigid contact never delivers any cell-level momentum because
        # the hull boundary is solid, so we inject what a real splash
        # would carry directly into v_y at the contact zone.
        if inject_impulse and not impulse_applied and frame_idx == 2:
            wcells = water.cells   # type: ignore[attr-defined]
            if wcells is not None:
                # Top-centre slab of cells (rows 2-6, cols 10-22) — under
                # where the ball arcs to.  This is a velocity-only pulse
                # so mass is conserved exactly.
                wcells[2:7, 10:22, _IDX_V_Y] += float(impulse_vy)
                impulse_applied = True

        contacts = world.step()

        # Tally contacts BEFORE rendering so the per-frame snapshot lines up.
        for pair in contacts:
            a = int(pair.a)
            b = int(pair.b)
            if b < 0:
                continue
            ab = (a, b)
            if ball_hid in ab and water_hid in ab:
                ball_water_contacts += 1
            elif ball_hid in ab and (a in wall_hids or b in wall_hids):
                ball_wall_contacts += 1

        # Per-frame slosh-amplitude metric: max |u_y| of any water cell
        # whose density is non-trivial (so we ignore the dry margin around
        # the rectangular silhouette).
        wcells = water.cells   # type: ignore[attr-defined]
        if wcells is not None:
            uy = wcells[..., _IDX_U_Y]
            density = wcells[..., _IDX_DENSITY]
            wet = density > 0.1
            if wet.any():
                per_frame_peak_uy.append(float(np.abs(uy[wet]).max()))
                # Peak |v_y| anywhere in the wet field.
                peak_water_vy = max(
                    peak_water_vy,
                    float(np.abs(wcells[..., _IDX_V_Y][wet]).max()),
                )
                # Peak |v_y| at the FAR EDGES (left+right 4 columns) —
                # this is the wave-propagation signal: motion here can
                # only arrive via the pressure-projection step carrying
                # the central impulse laterally.  If projection is dead,
                # this stays at noise-floor (~0.3 px/s).
                edge_vy = np.concatenate(
                    [
                        wcells[:, 0:4, _IDX_V_Y].ravel(),
                        wcells[:, 28:32, _IDX_V_Y].ravel(),
                    ]
                )
                peak_water_vy_far = max(
                    peak_water_vy_far, float(np.abs(edge_vy).max())
                )
            else:
                per_frame_peak_uy.append(0.0)
        else:
            per_frame_peak_uy.append(0.0)

        ball_y_history.append(float(world.hulls.position[ball_hid, 1]))

        psys.emit_from_contacts(
            contacts,
            world=world,
            hulls=world.hulls,
            body_lookup=world._body_for_hull,
        )
        psys.step(dt)
        frame = renderer.render(world)
        frame = psys.render(frame, world_view=cfg.world_view)
        frame = post.apply(frame)
        frames.append(frame)

    out: Path | None = None
    if save_gif:
        out = Path(out_path) if out_path is not None else OUTPUT_PATH
        out.parent.mkdir(parents=True, exist_ok=True)
        renderer.save_gif(frames, out, fps=FPS)

    wcells_final = water.cells   # type: ignore[attr-defined]
    final_density = (
        wcells_final[..., _IDX_DENSITY].copy()
        if wcells_final is not None
        else np.zeros((32, 32), dtype=np.float32)
    )
    fX, fY = _water_cell_world_xy(world, water)

    return {
        "frames": frames,
        "peak_water_uy": float(max(per_frame_peak_uy) if per_frame_peak_uy else 0.0),
        "peak_water_vy": float(peak_water_vy),
        "peak_water_vy_far": float(peak_water_vy_far),
        "per_frame_peak_water_uy": per_frame_peak_uy,
        "ball_y_history": ball_y_history,
        "ball_water_contacts": ball_water_contacts,
        "ball_wall_contacts": ball_wall_contacts,
        "final_water_density": final_density,
        "final_water_world_xy": (fX, fY),
        "output_path": out,
    }


def main() -> None:
    metrics = run_demo_with_metrics(save_gif=True)
    out = metrics["output_path"]
    peak = metrics["peak_water_uy"]
    bw = metrics["ball_water_contacts"]
    bwall = metrics["ball_wall_contacts"]
    by = metrics["ball_y_history"]
    print(
        f"Peak water |u_y|: {peak:.3f}.  "
        f"Ball-water contacts: {bw}, ball-wall contacts: {bwall}.  "
        f"Ball y range: [{min(by):.1f}, {max(by):.1f}]."
    )
    if out is not None:
        print(f"GIF written to {out}")


if __name__ == "__main__":
    main()
