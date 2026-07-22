"""Bullet holes — high-velocity drilling through terrain.

Demonstrates per-particle drilling on :class:`ParticleField`. A burst of
"bullets" (custom :class:`Material` with high ``drill_max_px`` and low
``binding_force``) fires from the left, drills through a stone wall in
the middle, ejects per-pixel debris carrying the wall's colour, and
exits out the right. Configurable knobs on the bullet material:

* ``drill_max_px``      — max pixels a bullet can punch through
* ``drill_velocity_loss`` — per-pixel velocity multiplier (0.95 = barely
                           slows; 0.5 = heavy braking)
* ``drill_eject_gain``  — fraction of drilled volume re-emitted as
                           debris (1.0 = full mass conservation; 0.0 =
                           clean tunnel, no ejecta)
* ``mass_conservation`` — system-wide multiplier on the above

Output:
    examples/output/particles/bullet_holes.gif
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from pharos_engine.physics.particle_field import Material, ParticleField


W, H = 640, 240
WALL_X0, WALL_X1 = 280, 320
WALL_Y0, WALL_Y1 = 40, 200
N_BULLETS = 14
SHOTS_PER_FRAME = 1
FRAMES = 130


def main() -> Path:
    rng = np.random.default_rng(2026)
    # Gravity now applied so bullets drop visibly (~720 px/s² as the
    # rest of the engine).
    field = ParticleField(width=W, height=H, gravity=720.0)

    # Bullet material — moderate drill, falling under gravity. Low
    # binding so it gets through stone walls, but reduced drill depth
    # so a wall doesn't evaporate from one shot.
    bullet = field.register_material(Material(
        name="bullet",
        binding_force=2.0e3,
        drill_max_px=10,
        drill_velocity_loss=0.65,
        drill_eject_gain=0.8,
        mass_conservation=1.0,
        gravity_scale=0.5,
        air_drag_per_sec=0.95,
        radius_min=1,
        radius_max=1,
        color=(255, 220, 100),
        drill_entry_crater=2,
        drill_entry_crater_jitter=1,          # craters vary 1..3 (3x3..7x7)
        drill_deflection=0.25,
        drill_fracture_threshold=0.55,
    ))
    # Stone material the wall is made of. Ejecta inherit THIS via the
    # mask sampling now built into _drill_through (no more bullets-as-
    # debris drilling their own walls).
    stone = field.register_material(Material(
        name="stone",
        binding_force=8.0e4,
        cohesion=0.4,
        # Hard floor friction — debris stops quickly instead of gliding.
        # 0.01/sec ≈ 7%/frame braking (was 0.1 ≈ 3.8%/frame).
        friction_per_sec=0.01,
        radius_min=1,
        radius_max=1,
        color=(110, 102, 96),
        kinetic_fluidity=0.3,
        rigidify_frames_min=4,
        rigidify_frames_max=10,
        impact_stickiness=0.7,
        settle_speed_threshold=18.0,  # debris settles sooner
    ))
    # Build the stone wall — set BOTH mask and material_grid so the
    # drill mechanic samples stone material id for ejecta.
    for x in range(WALL_X0, WALL_X1):
        for y in range(WALL_Y0, WALL_Y1):
            field.mask[y, x, 0] = 110 + int(rng.integers(-15, 15))
            field.mask[y, x, 1] = 102 + int(rng.integers(-15, 15))
            field.mask[y, x, 2] = 96 + int(rng.integers(-15, 15))
            field.mask[y, x, 3] = 255
            field.material_grid[y, x] = stone
    field._fixed_mask[WALL_Y0:WALL_Y1, WALL_X0:WALL_X1] = True
    # Floor so ejecta have something to pile on.
    field.fill_ground(top_y=H - 8, color=(60, 50, 40), material="stone")

    frames_out: list[Image.Image] = []
    bullets_fired = 0
    for f in range(FRAMES):
        if bullets_fired < N_BULLETS and f % 4 == 0:
            # Fire one bullet per 4 frames from the left.
            y0 = WALL_Y0 + int(rng.uniform(0, WALL_Y1 - WALL_Y0))
            field.spawn(
                x=20.0, y=float(y0),
                # Slight velocity randomness so not every bullet has
                # identical KE / impact behaviour.
                vx=float(rng.uniform(1500.0, 2100.0)),
                vy=float(rng.uniform(-30, 30)),
                material="bullet", radius=1,
            )
            bullets_fired += 1

        field.step(1.0 / 60.0)

        # Background gradient + composite the field.
        arr = np.zeros((H, W, 3), dtype=np.uint8)
        for y in range(H):
            t = y / H
            arr[y, :, 0] = int(15 + 25 * t)
            arr[y, :, 1] = int(20 + 30 * t)
            arr[y, :, 2] = int(40 + 40 * t)
        fg = field.render(mode="discs")
        solid = field.mask[..., 3] > 0
        live = fg.sum(axis=-1) > 0
        m = solid | live
        arr[m] = fg[m]
        im = Image.fromarray(arr, mode="RGB")
        d = ImageDraw.Draw(im)
        d.text((8, 8), "Bullet holes — high-velocity drilling",
               fill=(240, 240, 240))
        d.text((8, 22),
               f"f={f}  bullets={bullets_fired}  particles={field.pos.shape[0]}",
               fill=(200, 200, 200))
        frames_out.append(im)

    out_dir = Path(__file__).parent / "output" / "particles"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "bullet_holes.gif"
    frames_out[0].save(
        out_path,
        save_all=True,
        append_images=frames_out[1:],
        duration=33,
        loop=0,
        optimize=False,
    )
    # Count holes in the wall = pixels that USED to be solid and are now empty.
    cleared_in_wall = (field.mask[WALL_Y0:WALL_Y1, WALL_X0:WALL_X1, 3] == 0).sum()
    print(f"wrote {out_path}")
    print(f"  bullets fired: {bullets_fired}")
    print(f"  wall pixels drilled away: {int(cleared_in_wall)}")
    print(f"  total particles (bullets + ejecta): {field.pos.shape[0]}")
    return out_path


if __name__ == "__main__":
    main()
