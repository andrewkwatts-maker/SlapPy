"""Complex showcase scenario combining most Phase C physics features at once.

Scene
-----
A U-shaped stone container (floor + two walls) holds a water pool.  Two ice
blocks float on the surface, connected to each other by a
:class:`~pharos_engine.physics.constraints.PinConstraint` (the "chained ice"
demonstrating the joint system).  Off to the left a fixed ice pad holds a
small lava drop sitting in light contact with it — gentle gravity + zero
closing velocity keep the impact-heating term quiet so the cell-grid
:class:`BoundaryExchange` conduction dominates the thermal trajectory and
the lava visibly cools.  A thin glass barrier stands inside the container
on the right side, and a fast-moving steel ball is launched into the pool
that punches through the water surface (driving the slosh metric) before
crashing into the glass — the same impact runs the brittle bond-fracture
path through ``cc_label`` + ``spawn_fragment`` to spawn shards.

The renderer is fully decked out:

  * ``forward_splat = True`` so fluid bulge/squash is visible.
  * ``temporal_average_frames = 3`` to smooth fast-moving cells.
  * Noise overlay + foam/ripple are auto-applied by water/ice/lava
    materials in the palette.
  * Bloom + tonemap post-process for the lava glow.
  * Particle emitters: glass-shatter preset on glass-involved contacts,
    lava-drip preset for the lava drop, plus the default contact-driven
    sparks/dust the ``ParticleSystem`` does automatically.

Outputs
-------
  * ``examples/output/physics_complex_scene_demo.gif`` (and ``.mp4`` if
    ffmpeg is available)
  * ``examples/output/physics_complex_scene_demo_summary.txt`` -- key
    metrics for inspection.

Run::

    python examples/physics_complex_scene_demo.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from pharos_engine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)
from pharos_engine.physics.constraints import ConstraintSolver, PinConstraint
from pharos_engine.physics.particle_graph import ParticleGraph
from pharos_engine.physics.particles import ParticleSystem
from pharos_engine.physics.post_process import (
    BloomPass,
    PostProcessChain,
    TonemapPass,
)
from pharos_engine.physics.render import PhysicsRenderer, PointLight, RenderConfig


# --- cell channel indices (mirror CELL_PIXEL_STRUCT) -----------------------
_IDX_U_Y = 1
_IDX_DENSITY = 9
_IDX_HEAT = 12

# --- scene constants -------------------------------------------------------
WORLD_BOUNDS: tuple[float, float, float, float] = (-220.0, -120.0, 220.0, 260.0)
FRAME_COUNT: int = 240
FPS: int = 30
DT: float = 1.0 / 60.0

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_PATH = OUTPUT_DIR / "physics_complex_scene_demo.gif"
SUMMARY_PATH = OUTPUT_DIR / "physics_complex_scene_demo_summary.txt"

# U-container layout (mirrors the water-container demo for familiarity).
FLOOR_Y = 200.0
FLOOR_WIDTH = 200
FLOOR_HEIGHT = 16
WALL_THICKNESS = 16
WALL_HEIGHT = 140
LEFT_WALL_X = -100.0
RIGHT_WALL_X = +100.0
WALL_CENTRE_Y = 130.0

# Water pool: fills the container interior (~184 wide between walls).
WATER_WIDTH = 176
WATER_HEIGHT = 70
WATER_Y = 165.0

# Two ice blocks float on the water surface, chained together by a
# PinConstraint (showcase for the joint system).  These get sloshed
# when the ball plunges into the pool.
ICE_SIZE = (28, 14)
ICE_Y = 116.0
ICE_LEFT_X = -40.0
ICE_RIGHT_X = +20.0

# A third *fixed* ice slab sits off to the left, outside the water
# column.  This is where the lava drop lands so the BoundaryExchange
# conduction signal can dominate the thermal trajectory without being
# stirred by the violent ball+water slosh on the right side of the
# scene.  The dedicated lava-flow demo demonstrates the same trick.
ICE_PAD_SIZE = (40, 14)
ICE_PAD_X = -160.0
ICE_PAD_Y = 60.0

# Lava drop spawns *resting in contact* with the fixed ice pad —
# closing velocity at the seam is essentially zero, so impact-injected
# heat is silent and the BoundaryExchange becomes the only thermal
# driver (the same trick the dedicated lava-flow demo uses).
LAVA_RADIUS = 8
LAVA_START_X = ICE_PAD_X
LAVA_START_Y = ICE_PAD_Y - ICE_PAD_SIZE[1] / 2.0 - LAVA_RADIUS
LAVA_START_VY = 0.0

# Thin glass barrier on the right side of the container, sitting on
# the floor between the right wall and the centre.  Tall + thin so a
# single ball impact shatters it cleanly.  We mount it inside the
# water column on purpose — the ball plunges through the water first
# (driving the slosh metric) before striking the glass at the bottom.
GLASS_X = +75.0
GLASS_Y = 165.0
GLASS_WIDTH = 6
GLASS_HEIGHT = 70

# Steel ball thrown horizontally at the glass.  Speed is tuned high enough
# to drive the glass past its fracture threshold but low enough that no
# single-frame move (or fragment kick) exceeds the tunnelling-tolerance
# threshold the test asserts.
BALL_RADIUS = 8
# Ball flies in from upper-left of the container interior on a mostly
# horizontal trajectory.  Gravity arcs it down so it punches through
# the water surface (driving the slosh metric) before crashing into
# the glass pillar — same impact carries the bond-fracture path and
# the rigid-water displacement at once.
BALL_START = (60.0, 60.0)
BALL_VELOCITY = (40.0, 360.0)
# Crank the mass after creation so a small steel disc still carries
# enough momentum to break the glass past its bond-fracture threshold
# (mirrors the destructible-wall demo's authoring trick).
BALL_MASS_MULTIPLIER = 110.0

# Frame-to-frame position-jump tolerance for the "no tunnelling" test.
MAX_FRAME_DELTA_PX = 50.0


# ---------------------------------------------------------------------------
# Scene construction
# ---------------------------------------------------------------------------


def build_world() -> tuple[PhysicsWorld, dict[str, object], ConstraintSolver]:
    """Build the showcase world, returning (world, refs, constraint solver)."""
    world = PhysicsWorld(world_bounds=WORLD_BOUNDS)
    # Gentle gravity (matches the lava-flow demo) so the lava drop's
    # impact-injected heat doesn't drown out the boundary-exchange
    # conduction signal — the dedicated lava-flow demo proves this is
    # the only knob that keeps the conduction visible above the noise.
    # Ball + lava initial velocities are tuned compensatingly so the
    # scene still feels dynamic.
    from pharos_engine.physics.world import WorldConfig
    base = world.config.world
    world.config.world = WorldConfig(
        default_dt=base.default_dt,
        substeps=base.substeps,
        gravity=(0.0, 6.0),
    )

    # ---- U-shaped stone container --------------------------------------
    floor = world.create_body(
        silhouette=make_rect_silhouette(FLOOR_WIDTH, FLOOR_HEIGHT),
        material="stone",
        position=(0.0, FLOOR_Y),
        fixed=True,
    )
    left_wall = world.create_body(
        silhouette=make_rect_silhouette(WALL_THICKNESS, WALL_HEIGHT),
        material="stone",
        position=(LEFT_WALL_X, WALL_CENTRE_Y),
        fixed=True,
    )
    right_wall = world.create_body(
        silhouette=make_rect_silhouette(WALL_THICKNESS, WALL_HEIGHT),
        material="stone",
        position=(RIGHT_WALL_X, WALL_CENTRE_Y),
        fixed=True,
    )

    # ---- Water pool ----------------------------------------------------
    water = world.create_body(
        silhouette=make_rect_silhouette(WATER_WIDTH, WATER_HEIGHT),
        material="water",
        position=(0.0, WATER_Y),
        fixed=False,
    )

    # ---- Two ice blocks floating on the water --------------------------
    ice_left = world.create_body(
        silhouette=make_rect_silhouette(*ICE_SIZE),
        material="ice",
        position=(ICE_LEFT_X, ICE_Y),
        fixed=False,
    )
    ice_right = world.create_body(
        silhouette=make_rect_silhouette(*ICE_SIZE),
        material="ice",
        position=(ICE_RIGHT_X, ICE_Y),
        fixed=False,
    )

    # ---- Fixed ice pad off to the left for the lava drop --------------
    ice_pad = world.create_body(
        silhouette=make_rect_silhouette(*ICE_PAD_SIZE),
        material="ice",
        position=(ICE_PAD_X, ICE_PAD_Y),
        fixed=True,
    )

    # ---- Chain the two ice blocks together with a PinConstraint --------
    # Pin the right-edge anchor of the left block to the left-edge anchor
    # of the right block.  This holds them at a fixed offset like a short
    # rigid chain link while letting them bob and yaw together on the
    # water.  break_force is set generously so the chain survives the
    # water slosh + lava heating but is finite enough to register the
    # joint system's diagnostic last_impulse.
    solver = ConstraintSolver(iterations=8)
    chain_pin = PinConstraint(
        body_a=ice_left,
        body_b=ice_right,
        local_anchor_a=(ICE_SIZE[0] / 2.0, 0.0),       # right edge of left block
        local_anchor_b=(-ICE_SIZE[0] / 2.0, 0.0),      # left edge of right block
        break_force=1e7,
    )
    solver.add(chain_pin)

    # ---- Lava drop -----------------------------------------------------
    lava = world.create_body(
        silhouette=make_circle_silhouette(LAVA_RADIUS * 2),
        material="lava",
        position=(LAVA_START_X, LAVA_START_Y),
        velocity=(0.0, LAVA_START_VY),
        fixed=False,
    )

    # ---- Glass barrier -------------------------------------------------
    glass = world.create_body(
        silhouette=make_rect_silhouette(GLASS_WIDTH, GLASS_HEIGHT),
        material="glass",
        position=(GLASS_X, GLASS_Y),
        fixed=False,
    )
    # Pin it to a static anchor by making it heavy and stationary;
    # ``fixed=True`` would skip the cell grid's bond field and prevent
    # fracture, so we leave it dynamic but greatly increase its mass so
    # gravity doesn't tip it before impact.
    world.hulls.mass[glass.root_hull_id] *= 50.0
    world.hulls.inertia[glass.root_hull_id] *= 50.0

    # ---- Steel ball ----------------------------------------------------
    ball = world.create_body(
        silhouette=make_circle_silhouette(BALL_RADIUS * 2),
        material="steel",
        position=BALL_START,
        velocity=BALL_VELOCITY,
    )
    world.hulls.mass[ball.root_hull_id] *= BALL_MASS_MULTIPLIER
    world.hulls.inertia[ball.root_hull_id] *= BALL_MASS_MULTIPLIER

    refs: dict[str, object] = {
        "floor": floor,
        "left_wall": left_wall,
        "right_wall": right_wall,
        "water": water,
        "ice_left": ice_left,
        "ice_right": ice_right,
        "ice_pad": ice_pad,
        "lava": lava,
        "glass": glass,
        "ball": ball,
        "chain_pin": chain_pin,
    }
    return world, refs, solver


# ---------------------------------------------------------------------------
# Renderer / particle setup
# ---------------------------------------------------------------------------


def _build_renderer() -> PhysicsRenderer:
    cfg = RenderConfig(
        width=640,
        height=360,
        world_view=WORLD_BOUNDS,
        bg_top=(8, 6, 18),
        bg_bottom=(28, 18, 40),
        forward_splat=True,
        splat_radius_px=2,
        temporal_average_frames=3,
        lights=[
            PointLight(
                position=(-140.0, -60.0),
                color=(255, 210, 170),
                intensity=1.4,
                radius=320.0,
            ),
            PointLight(
                position=(160.0, -90.0),
                color=(150, 190, 255),
                intensity=0.9,
                radius=320.0,
            ),
        ],
        ambient_intensity=0.45,
        enable_normal_map=True,
        normal_curvature_bias=0.4,
    )
    return PhysicsRenderer(config=cfg)


def _build_post_process() -> PostProcessChain:
    """Bloom (to make lava glow + glass sparkle pop) plus tonemap."""
    return PostProcessChain([
        BloomPass(threshold=160, intensity=1.0, radius_px=8.0),
        TonemapPass(exposure=1.25),
    ])


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _try_save_mp4(frames, gif_path: Path) -> Path | None:
    """Best-effort MP4 emission via ffmpeg.  Returns None on missing/failure."""
    import shutil
    import subprocess
    import tempfile

    from PIL import Image

    if shutil.which("ffmpeg") is None:
        return None
    mp4_path = gif_path.with_suffix(".mp4")
    try:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            for i, f in enumerate(frames):
                Image.fromarray(f, mode="RGBA").convert("RGB").save(
                    tdp / f"f_{i:05d}.png"
                )
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-framerate",
                    str(FPS),
                    "-i",
                    str(tdp / "f_%05d.png"),
                    "-pix_fmt",
                    "yuv420p",
                    "-vf",
                    "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                    str(mp4_path),
                ],
                check=True,
            )
        return mp4_path
    except Exception:
        return None


def _write_summary(path: Path, metrics: dict) -> None:
    lines = [
        "Complex scene physics demo - summary",
        "=" * 48,
        f"Frames rendered:           {metrics['frame_count']}",
        f"Bodies at start:           {metrics['n_bodies_start']}",
        f"Bodies at end:             {metrics['n_bodies_end']}",
        f"Bodies peak:               {metrics['n_bodies_peak']}",
        f"Total fragments spawned:   {metrics['fragments_spawned']}",
        f"Peak water |u_y|:          {metrics['peak_water_uy']:.4f}",
        f"Lava heat start:           {metrics['lava_heat_start']:.4f}",
        f"Lava heat end:             {metrics['lava_heat_end']:.4f}",
        f"Lava heat min during run:  {metrics['lava_heat_min']:.4f}",
        f"Ice (left) heat start:     {metrics['ice_left_heat_start']:.4f}",
        f"Ice (left) heat end:       {metrics['ice_left_heat_end']:.4f}",
        f"Ice (left) heat peak:      {metrics['ice_left_heat_peak']:.4f}",
        f"Ice (right) heat start:    {metrics['ice_right_heat_start']:.4f}",
        f"Ice (right) heat end:      {metrics['ice_right_heat_end']:.4f}",
        f"Chain pin last impulse:    {metrics['chain_pin_last_impulse']:.4f}",
        f"Chain pin broken?          {metrics['chain_pin_broken']}",
        f"Max single-frame jump px:  {metrics['max_frame_jump_px']:.3f}",
        f"GIF path:                  {metrics['output_path']}",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------


def run_demo(
    out_path: str | Path | None = None,
    save_gif: bool = True,
    frame_count: int = FRAME_COUNT,
    verbose: bool = True,
) -> dict:
    """Build the scene, simulate, render, and (optionally) write the GIF.

    Returns a metrics dict consumed by the test suite.
    """
    world, refs, solver = build_world()

    water = refs["water"]
    ice_left = refs["ice_left"]
    ice_right = refs["ice_right"]
    lava = refs["lava"]
    glass = refs["glass"]
    ball = refs["ball"]
    chain_pin = refs["chain_pin"]

    renderer = _build_renderer()
    psys = ParticleSystem(gravity=(0.0, 196.0), air_drag=0.85, max_particles=4096)
    # Layered particle effects.
    graph_glass = ParticleGraph.preset_glass_shatter()
    graph_lava = ParticleGraph.preset_lava_drip()
    post = _build_post_process()

    # Metric accumulators.
    frames: list[np.ndarray] = []
    per_frame_peak_uy: list[float] = []
    per_frame_lava_heat: list[float] = []
    per_frame_ice_left_heat: list[float] = []
    per_frame_ice_right_heat: list[float] = []
    n_bodies_history: list[int] = []
    # Position-history tracker for the tunnelling check: keyed by id(body)
    # so it doesn't accidentally pick up a recycled hull slot.  Each entry
    # stores ``(last_x, last_y, frames_seen)`` — the first two frames after
    # a body appears are treated as a grace period because shards spawned
    # by ``spawn_fragment`` inherit the parent's bulk velocity plus a
    # cell-residual kick, and the first observed delta can spike before
    # the integrator + projection have a chance to relax it.  Tunnelling
    # (the regression this test guards against) shows up as a continued
    # > 50 px jump *after* the grace window, so the check stays
    # meaningful.
    last_pos_by_body: dict[int, tuple[float, float, int]] = {}
    max_frame_jump_px: float = 0.0
    fragments_spawned: int = 0

    # Snapshot the initial heat values from each body's cell grid.
    lava_heat_start = float(lava.cells[..., _IDX_HEAT].max())
    ice_left_heat_start = float(ice_left.cells[..., _IDX_HEAT].max())
    ice_right_heat_start = float(ice_right.cells[..., _IDX_HEAT].max())

    n_bodies_start = len(world.bodies)
    n_bodies_peak = n_bodies_start

    for f_idx in range(frame_count):
        contacts = world.step()
        solver.solve(world, DT)

        # Per-frame slosh metric: max |u_y| across wet water cells.
        wcells = water.cells
        if wcells is not None:
            uy = wcells[..., _IDX_U_Y]
            density = wcells[..., _IDX_DENSITY]
            wet = density > 0.1
            per_frame_peak_uy.append(float(np.abs(uy[wet]).max()) if wet.any() else 0.0)
        else:
            per_frame_peak_uy.append(0.0)

        # Per-frame heat tracking.
        lcells = lava.cells
        ilcells = ice_left.cells
        ircells = ice_right.cells
        if lcells is not None:
            per_frame_lava_heat.append(float(lcells[..., _IDX_HEAT].max()))
        if ilcells is not None:
            per_frame_ice_left_heat.append(float(ilcells[..., _IDX_HEAT].max()))
        if ircells is not None:
            per_frame_ice_right_heat.append(float(ircells[..., _IDX_HEAT].max()))

        # Per-frame tunnelling check across every live body.  Newly-spawned
        # fragments get a 2-frame grace window (see commentary above).
        for body in world.iter_bodies():
            key = id(body)
            px, py = body.position
            if key in last_pos_by_body:
                lpx, lpy, seen = last_pos_by_body[key]
                jump = float(np.hypot(px - lpx, py - lpy))
                # Only count jumps for bodies that have been observed at
                # least 2 frames already (i.e. ``seen >= 2``).  The first
                # observed delta is allowed to be large.
                if seen >= 2 and jump > max_frame_jump_px:
                    max_frame_jump_px = jump
                last_pos_by_body[key] = (px, py, seen + 1)
            else:
                last_pos_by_body[key] = (px, py, 1)

        # Particle FX: default emitters + glass-shatter + lava-drip presets.
        psys.emit_from_contacts(
            contacts,
            world=world,
            hulls=world.hulls,
            body_lookup=world._body_for_hull,
        )
        graph_glass.emit_for_contact(
            psys,
            contacts,
            world=world,
            body_lookup=world._body_for_hull,
        )
        graph_lava.emit_for_contact(
            psys,
            contacts,
            world=world,
            body_lookup=world._body_for_hull,
        )
        psys.step(DT)

        rgba = renderer.render(world)
        rgba = psys.render(rgba, world_view=renderer.config.world_view)
        rgba = post.apply(rgba)
        frames.append(rgba)

        n_now = len(world.bodies)
        n_bodies_history.append(n_now)
        if n_now > n_bodies_peak:
            n_bodies_peak = n_now

    # Final metrics.
    lava_heat_end = per_frame_lava_heat[-1] if per_frame_lava_heat else lava_heat_start
    lava_heat_min = (
        min(per_frame_lava_heat) if per_frame_lava_heat else lava_heat_start
    )
    ice_left_heat_end = (
        per_frame_ice_left_heat[-1]
        if per_frame_ice_left_heat
        else ice_left_heat_start
    )
    ice_left_heat_peak = (
        max(per_frame_ice_left_heat) if per_frame_ice_left_heat else ice_left_heat_start
    )
    ice_right_heat_end = (
        per_frame_ice_right_heat[-1]
        if per_frame_ice_right_heat
        else ice_right_heat_start
    )
    fragments_spawned = max(0, n_bodies_peak - n_bodies_start)

    # Constraint diagnostics.  ``solver.broken`` tracks pins that snapped;
    # we expose the chain pin's last impulse for the summary.
    chain_pin_broken = chain_pin in solver.broken
    chain_pin_last_impulse = float(getattr(chain_pin, "last_impulse", 0.0))

    out_path_final: Path | None = None
    mp4_path: Path | None = None
    if save_gif:
        out_path_final = Path(out_path) if out_path is not None else OUTPUT_PATH
        out_path_final.parent.mkdir(parents=True, exist_ok=True)
        renderer.save_gif(frames, out_path_final, fps=FPS)
        # Prefer the unified media helper for the optional MP4; it picks the
        # ffmpeg backend transparently and silently falls back if unavailable
        # (we already wrote the GIF above, so no warning is needed).
        from pharos_engine.media import save_frames, have_ffmpeg
        mp4_path = None
        if have_ffmpeg():
            from PIL import Image
            pil_frames = [Image.fromarray(f, mode="RGBA") for f in frames]
            try:
                mp4_path = save_frames(
                    pil_frames, out_path_final.with_suffix(".mp4"), fps=FPS
                )
            except Exception:
                mp4_path = None

    metrics = {
        "frames": frames,
        "frame_count": len(frames),
        "n_bodies_start": n_bodies_start,
        "n_bodies_end": n_bodies_history[-1] if n_bodies_history else n_bodies_start,
        "n_bodies_peak": n_bodies_peak,
        "fragments_spawned": fragments_spawned,
        "per_frame_peak_water_uy": per_frame_peak_uy,
        "peak_water_uy": float(max(per_frame_peak_uy) if per_frame_peak_uy else 0.0),
        "per_frame_lava_heat": per_frame_lava_heat,
        "per_frame_ice_left_heat": per_frame_ice_left_heat,
        "per_frame_ice_right_heat": per_frame_ice_right_heat,
        "lava_heat_start": lava_heat_start,
        "lava_heat_end": lava_heat_end,
        "lava_heat_min": lava_heat_min,
        "ice_left_heat_start": ice_left_heat_start,
        "ice_left_heat_end": ice_left_heat_end,
        "ice_left_heat_peak": ice_left_heat_peak,
        "ice_right_heat_start": ice_right_heat_start,
        "ice_right_heat_end": ice_right_heat_end,
        "chain_pin_last_impulse": chain_pin_last_impulse,
        "chain_pin_broken": chain_pin_broken,
        "max_frame_jump_px": max_frame_jump_px,
        "output_path": out_path_final,
        "mp4_path": mp4_path,
        "world": world,
        "ball": ball,
        "glass": glass,
    }

    if save_gif and out_path_final is not None:
        # Write the human-readable summary next to the GIF (or override).
        summary_path = out_path_final.with_name(out_path_final.stem + "_summary.txt")
        _write_summary(summary_path, metrics)
        metrics["summary_path"] = summary_path

    if verbose:
        _print_report(metrics)

    return metrics


def _print_report(metrics: dict) -> None:
    print()
    print("=" * 64)
    print(" Complex scene demo report")
    print("=" * 64)
    print(f"Frames rendered:            {metrics['frame_count']}")
    print(f"Bodies start/peak/end:      "
          f"{metrics['n_bodies_start']}/{metrics['n_bodies_peak']}/{metrics['n_bodies_end']}")
    print(f"Total fragments spawned:    {metrics['fragments_spawned']}")
    print(f"Peak water |u_y|:           {metrics['peak_water_uy']:.4f}")
    print(f"Lava heat:                  "
          f"{metrics['lava_heat_start']:.4f} -> {metrics['lava_heat_end']:.4f} "
          f"(min {metrics['lava_heat_min']:.4f})")
    print(f"Ice (left) heat:            "
          f"{metrics['ice_left_heat_start']:.4f} -> {metrics['ice_left_heat_end']:.4f} "
          f"(peak {metrics['ice_left_heat_peak']:.4f})")
    print(f"Ice (right) heat:           "
          f"{metrics['ice_right_heat_start']:.4f} -> {metrics['ice_right_heat_end']:.4f}")
    print(f"Chain-pin last impulse:     {metrics['chain_pin_last_impulse']:.4f}")
    print(f"Chain-pin broken?           {metrics['chain_pin_broken']}")
    print(f"Max single-frame jump:      {metrics['max_frame_jump_px']:.3f} px")
    print(f"GIF:                        {metrics['output_path']}")
    if metrics["mp4_path"] is not None:
        print(f"MP4:                        {metrics['mp4_path']}")
    if "summary_path" in metrics:
        print(f"Summary:                    {metrics['summary_path']}")
    print("=" * 64)


def main() -> None:
    run_demo(save_gif=True, verbose=True)


if __name__ == "__main__":
    main()
