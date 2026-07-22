"""Destructible wall demo.

Three steel bullets are fired at a brittle glass wall.  Each impact
weakens the wall's cell-bond field; once a region's bonds drop below
the fracture threshold ``cc_label.connected_components`` finds the
disjoint shards and :meth:`HullTree.spawn_fragment` splits them off as
independent rigid bodies.  The shards then fly off under gravity and
accumulate on a stone floor — the full fragmentation pipeline,
end-to-end.

Flagship demo for the ``cc_label`` + ``spawn_fragment`` work that
landed in earlier ticks.

Run::

    python examples/physics_destructible_wall_demo.py

Outputs (in ``examples/output/``):
  * ``physics_destructible_wall_demo.gif`` — full run animation.
  * ``physics_destructible_wall_demo.mp4`` — same, if ffmpeg is available.
"""
from __future__ import annotations

from pathlib import Path

from pharos_engine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)
from pharos_engine.physics.particle_graph import ParticleGraph
from pharos_engine.physics.particles import ParticleSystem
from pharos_engine.physics.post_process import default_post_process_chain
from pharos_engine.physics.render import PhysicsRenderer, RenderConfig


WORLD_BOUNDS: tuple[float, float, float, float] = (-300.0, -100.0, 300.0, 250.0)
FRAME_COUNT: int = 180

# Wall position (centre of the brittle glass rectangle).
WALL_X: float = 80.0
WALL_Y: float = 100.0
WALL_WIDTH: int = 40
WALL_HEIGHT: int = 180

# Floor (fixed stone slab).
FLOOR_Y: float = 220.0
FLOOR_WIDTH: int = 600
FLOOR_HEIGHT: int = 16

# Each tuple is (initial x, initial y, velocity x offset from base 450).
BULLET_LAUNCHES: tuple[tuple[float, float, float], ...] = (
    (-250.0, 60.0, 0.0),
    (-260.0, 90.0, 50.0),
    (-240.0, 130.0, -30.0),
)
BULLET_DIAMETER: int = 8
BULLET_BASE_VX: float = 450.0
BULLET_MATERIAL: str = "steel"
# Multiplier applied to bullet mass + inertia after creation so each
# impact carries enough momentum to drive the wall past its fracture
# threshold (the silhouette is tiny vs the wall's silhouette).
BULLET_MASS_MULTIPLIER: float = 200.0


def _try_save_mp4(frames, gif_path: Path) -> Path | None:
    """Best-effort MP4 emission via ffmpeg.  Returns None if ffmpeg is missing
    or the encode fails — never raises (the GIF is the canonical artifact)."""
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
                    "30",
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


def run_demo(out_path=None, frame_count: int = FRAME_COUNT, verbose: bool = True):
    """Build the scene, run the simulation, write the GIF, return summary."""
    w = PhysicsWorld(world_bounds=WORLD_BOUNDS)
    # Override world config with the demo-specific tuning (substeps=4, gravity).
    w.config.world = type(w.config.world)(
        default_dt=1.0 / 60.0,
        substeps=4,
        gravity=(0.0, 196.0),
    )

    # Stone floor for shards to settle on.
    w.create_body(
        make_rect_silhouette(FLOOR_WIDTH, FLOOR_HEIGHT),
        "stone",
        position=(0.0, FLOOR_Y),
        fixed=True,
    )

    # The brittle glass wall.
    w.create_body(
        make_rect_silhouette(WALL_WIDTH, WALL_HEIGHT),
        "glass",
        position=(WALL_X, WALL_Y),
    )

    # Three steel bullets, staggered timing/heights.  We crank the bullet
    # mass *after* creation so each impact carries enough momentum to push
    # the brittle glass past its bond-fracture threshold — without this
    # boost a tiny (~50 px²) steel disc just elastically ricochets off a
    # (~7200 px²) glass wall.  Scene authoring only; no physics module
    # touched.
    bullets = []
    for x_off, y_off, v_off in BULLET_LAUNCHES:
        bullet = w.create_body(
            make_circle_silhouette(BULLET_DIAMETER),
            BULLET_MATERIAL,
            position=(x_off, y_off),
            velocity=(BULLET_BASE_VX + v_off, 0.0),
        )
        hid = bullet.root_hull_id
        w.hulls.mass[hid] *= BULLET_MASS_MULTIPLIER
        w.hulls.inertia[hid] *= BULLET_MASS_MULTIPLIER
        bullets.append(bullet)

    renderer = PhysicsRenderer(
        config=RenderConfig(
            world_view=(WORLD_BOUNDS[0], WORLD_BOUNDS[1], WORLD_BOUNDS[2], WORLD_BOUNDS[3]),
            forward_splat=True,
            splat_radius_px=2,
            temporal_average_frames=3,
        )
    )
    psys = ParticleSystem(gravity=(0.0, 196.0), air_drag=0.85, max_particles=4096)
    graph = ParticleGraph.preset_glass_shatter()
    post = default_post_process_chain()

    frames = []
    n_bodies_history: list[int] = []
    # Track the rightmost x each bullet reaches during the run.  Bullets
    # may bounce back after striking the wall, so the final position
    # under-reports "did they reach the wall?".  Peak-x captures the
    # impact x even when the bullet ricochets all the way back.
    bullet_max_x: list[float] = [b.position[0] for b in bullets]
    for _f in range(frame_count):
        contacts = w.step()
        for i, b in enumerate(bullets):
            bx = b.position[0]
            if bx > bullet_max_x[i]:
                bullet_max_x[i] = bx
        psys.emit_from_contacts(
            contacts,
            world=w,
            hulls=w.hulls,
            body_lookup=w._body_for_hull,
        )
        # Layer the glass-shatter preset on top so impacts get the bright
        # shard look in addition to the default material-driven dust.
        graph.emit_for_contact(
            psys,
            contacts,
            world=w,
            body_lookup=w._body_for_hull,
        )
        psys.step(1.0 / 60.0)
        frame = renderer.render(w)
        frame = psys.render(frame, world_view=renderer.config.world_view)
        frame = post.apply(frame)
        frames.append(frame)
        n_bodies_history.append(len(w.bodies))

    out_path = (
        Path(out_path)
        if out_path is not None
        else Path(__file__).resolve().parent
        / "output"
        / "physics_destructible_wall_demo.gif"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Canonical GIF artifact (unchanged - the demo's contract).
    renderer.save_gif(frames, out_path, fps=30)

    # Best-effort MP4 via the unified media helper. Falls back to GIF
    # transparently (and silently here - GIF is already on disk).
    from pharos_engine.media import save_frames, have_ffmpeg
    mp4_path = None
    if have_ffmpeg():
        from PIL import Image
        pil_frames = [Image.fromarray(f, mode="RGBA") for f in frames]
        try:
            mp4_path = save_frames(
                pil_frames, out_path.with_suffix(".mp4"), fps=30
            )
        except Exception:
            mp4_path = None

    # Count bodies that have settled near/onto the floor (excluding the
    # fixed floor itself).  ``FLOOR_Y - FLOOR_HEIGHT/2`` is the floor's
    # top surface; we count anything with y > 200 as "on the floor".
    floor_y_threshold = 200.0
    shards_on_floor = sum(
        1
        for body in w.bodies
        if (not body.fixed) and body.position[1] > floor_y_threshold
    )

    result = {
        "path": out_path,
        "mp4_path": mp4_path,
        "n_frames": len(frames),
        "n_bodies_start": n_bodies_history[0],
        "n_bodies_end": n_bodies_history[-1],
        "n_bodies_peak": max(n_bodies_history),
        "shards_on_floor": shards_on_floor,
        "bullets": bullets,
        "bullet_max_x": bullet_max_x,
        "world": w,
    }

    if verbose:
        _print_report(result)

    return result


def _print_report(result: dict) -> None:
    print()
    print("=" * 64)
    print(" Destructible wall demo report")
    print("=" * 64)
    print(f"Frames simulated:      {result['n_frames']}")
    print(f"Bodies at start:       {result['n_bodies_start']}")
    print(f"Bodies at end:         {result['n_bodies_end']}")
    print(f"Bodies peak:           {result['n_bodies_peak']}")
    print(f"Fragments spawned:     {result['n_bodies_peak'] - result['n_bodies_start']}")
    print(f"Shards on floor:       {result['shards_on_floor']}")
    print()
    print(f"GIF:   {result['path']}")
    if result["mp4_path"] is not None:
        print(f"MP4:   {result['mp4_path']}")
    print("=" * 64)


if __name__ == "__main__":
    run_demo()
